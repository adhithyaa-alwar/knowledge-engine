"""
ingestion.py

Handles data ingestion: fetching Wikipedia articles, chunking them,
and storing the chunks in Supabase for later retrieval.

Raw article text is no longer cached in Redis. Redis is now used
exclusively for search suggestion caching and rate limiting in app.py.
Chunks are stored permanently in Supabase, so the raw text is only
needed once during ingestion and does not need to be cached.

This version includes:
- Wikipedia freshness check: compares the article's last edit timestamp
  against our stored chunk timestamp before deciding to re-ingest.
- Automated cleanup support: pg_cron in Supabase deletes chunks not
  accessed in 30 days. last_accessed_at is updated in retrieval.py
  on every question.
"""

import os
import requests
from datetime import timezone
from dateutil import parser as dateparser
from supabase import create_client, Client
from dotenv import load_dotenv

load_dotenv()

WIKIPEDIA_API = "https://en.wikipedia.org/w/api.php"
CHUNK_SIZE_WORDS = 1_500


def get_supabase_client() -> Client:
    return create_client(
        os.getenv("SUPABASE_URL"),
        os.getenv("SUPABASE_SECRET_KEY")
    )


def fetch_wikipedia_text(title: str) -> str:
    """
    Fetch the full plain-text content of a Wikipedia article directly
    from Wikipedia's API.

    No caching here. Raw article text is only needed during ingestion
    and is not worth caching since processed chunks are stored
    permanently in Supabase. Caching the raw text would add complexity
    without meaningful benefit given the current architecture.
    """
    params = {
        "action": "query",
        "titles": title,
        "prop": "extracts",
        "explaintext": True,
        "exsectionformat": "plain",
        "format": "json",
    }
    headers = {"User-Agent": "knowledge-engine/1.0 (github.com/adhithyaa-alwar/knowledge-engine)"}
    response = requests.get(WIKIPEDIA_API, params=params, headers=headers, timeout=10)
    response.raise_for_status()

    pages = response.json()["query"]["pages"]
    page = next(iter(pages.values()))

    if "missing" in page:
        raise ValueError(f"Wikipedia page not found: '{title}'")

    return page["extract"]


def fetch_last_edit_timestamp(title: str) -> str | None:
    """
    Fetch the timestamp of the most recent edit to a Wikipedia article.

    Wikipedia's revisions API returns the exact datetime the article
    was last modified. We compare this against our stored chunk timestamp
    to decide whether re-ingestion is needed.

    Returns an ISO 8601 string like "2024-03-15T10:22:00Z",
    or None if the request fails.
    """
    params = {
        "action": "query",
        "titles": title,
        "prop": "revisions",
        "rvprop": "timestamp",
        "rvlimit": 1,        # we only need the most recent edit
        "format": "json",
    }
    headers = {"User-Agent": "knowledge-engine/1.0 (github.com/adhithyaa-alwar/knowledge-engine)"}
    try:
        response = requests.get(WIKIPEDIA_API, params=params, headers=headers, timeout=10)
        response.raise_for_status()
        pages = response.json()["query"]["pages"]
        page = next(iter(pages.values()))
        return page["revisions"][0]["timestamp"]
    except Exception as e:
        print(f"Could not fetch last edit timestamp for '{title}': {e}")
        return None


def get_stored_chunk_timestamp(title: str) -> str | None:
    """
    Fetch the created_at timestamp of the most recently stored chunk
    for this article from Supabase.

    This tells us when we last ingested the article. We compare it
    against Wikipedia's last edit timestamp to decide freshness.

    Returns an ISO 8601 string, or None if no chunks exist yet.
    """
    client = get_supabase_client()
    result = (
        client.table("article_chunks")
        .select("created_at")
        .eq("article_title", title.lower())
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )
    if result.data:
        return result.data[0]["created_at"]
    return None


def chunks_are_fresh(title: str) -> bool:
    """
    Return True if our stored chunks are up to date with Wikipedia.

    Logic:
    1. Get our stored chunk timestamp. If none, return False (need to ingest).
    2. Get Wikipedia's last edit timestamp.
    3. If Wikipedia's timestamp is unavailable, assume fresh to avoid
       unnecessary re-ingestion on API failures.
    4. If our chunks were created after Wikipedia's last edit, we are fresh.
       Otherwise, stale and re-ingestion is needed.
    """
    stored_timestamp = get_stored_chunk_timestamp(title)

    # No chunks stored at all -- must ingest.
    if not stored_timestamp:
        return False

    wiki_timestamp = fetch_last_edit_timestamp(title)

    # Cannot reach Wikipedia's revision API -- assume fresh rather than
    # triggering a potentially unnecessary re-ingest.
    if not wiki_timestamp:
        return True

    # Parse both to timezone-aware datetimes so comparison works
    # regardless of format differences between Supabase and Wikipedia.
    stored_dt = dateparser.parse(stored_timestamp)
    wiki_dt = dateparser.parse(wiki_timestamp)

    if stored_dt.tzinfo is None:
        stored_dt = stored_dt.replace(tzinfo=timezone.utc)
    if wiki_dt.tzinfo is None:
        wiki_dt = wiki_dt.replace(tzinfo=timezone.utc)

    # Our chunks are fresh if they were stored after the last Wikipedia edit.
    return stored_dt >= wiki_dt


def chunk_text(text: str, chunk_size: int = CHUNK_SIZE_WORDS) -> list[str]:
    """
    Split text into chunks of roughly chunk_size words each,
    splitting on paragraph boundaries where possible so chunks
    do not cut sentences in half.
    """
    paragraphs = text.split("\n\n")
    chunks: list[str] = []
    current_words: list[str] = []

    for paragraph in paragraphs:
        words = paragraph.split()
        if current_words and len(current_words) + len(words) > chunk_size:
            chunks.append(" ".join(current_words))
            current_words = []
        current_words.extend(words)

    if current_words:
        chunks.append(" ".join(current_words))

    return chunks


def ingest_article(title: str) -> int:
    """
    Fetch a Wikipedia article, chunk it, and store the chunks in Supabase.

    Deletes any existing chunks for this article before inserting new ones
    so re-ingestion always produces a clean, complete, up-to-date set.

    Returns the number of chunks stored.
    """
    # Fetch fresh content directly from Wikipedia.
    text = fetch_wikipedia_text(title)

    # Split into chunks.
    chunks = chunk_text(text)

    client = get_supabase_client()

    # Delete old chunks before inserting new ones.
    # This ensures re-ingestion produces a clean result with no leftover
    # chunks from a previous version of the article.
    client.table("article_chunks").delete().eq("article_title", title.lower()).execute()

    # Insert all chunks in a single batch operation.
    # Batching is much faster than inserting one row at a time.
    rows = [
        {
            "article_title": title.lower(),
            "chunk_index": i,
            "content": chunk,
        }
        for i, chunk in enumerate(chunks)
    ]
    client.table("article_chunks").insert(rows).execute()

    return len(chunks)


def ensure_ingested(title: str) -> None:
    """
    The main entry point called by app.py before every question.

    Checks freshness using Wikipedia's revision timestamp. Re-ingests
    only when necessary: either no chunks exist, or Wikipedia has been
    updated since we last ingested. Fresh articles are skipped entirely.
    """
    if not chunks_are_fresh(title):
        print(f"Ingesting '{title}' -- no chunks or Wikipedia has been updated.")
        ingest_article(title)
    else:
        print(f"Chunks for '{title}' are fresh, skipping re-ingestion.")