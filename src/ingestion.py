"""
ingestion.py

Handles data ingestion: fetching Wikipedia articles, chunking them,
and storing the chunks in Supabase for later retrieval.

New in this version:
- Checks Wikipedia's last edit timestamp before deciding to re-ingest.
  If the stored chunks are newer than the last Wikipedia edit, we skip
  re-ingestion entirely. If Wikipedia has been updated since we last
  ingested, we delete the old chunks and re-ingest fresh ones.
- Updates last_accessed_at on every retrieval so the cleanup job
  knows which articles are still being used.
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
    Fetch the full plain-text content of a Wikipedia article.
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
    was last modified. We use this to decide whether our stored chunks
    are still current or need to be refreshed.

    Returns an ISO 8601 timestamp string like "2024-03-15T10:22:00Z",
    or None if the request fails.
    """
    params = {
        "action": "query",
        "titles": title,
        "prop": "revisions",
        "rvprop": "timestamp",
        "rvlimit": 1,           # we only need the most recent edit
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

    Returns an ISO 8601 timestamp string, or None if no chunks exist.
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

    The logic:
    1. Get the timestamp of our most recently stored chunk.
    2. If no chunks exist, return False (need to ingest).
    3. Get Wikipedia's last edit timestamp.
    4. If we can't fetch Wikipedia's timestamp, assume chunks are fresh
       to avoid unnecessary re-ingestion on API failures.
    5. Compare: if our chunks were created after Wikipedia's last edit,
       the content has not changed and we are fresh. Otherwise, stale.
    """
    stored_timestamp = get_stored_chunk_timestamp(title)

    # No chunks stored yet -- definitely need to ingest.
    if not stored_timestamp:
        return False

    wiki_timestamp = fetch_last_edit_timestamp(title)

    # If we cannot reach Wikipedia's revision API, assume fresh
    # rather than triggering a potentially unnecessary re-ingest.
    if not wiki_timestamp:
        return True

    # Parse both timestamps to timezone-aware datetimes for comparison.
    stored_dt = dateparser.parse(stored_timestamp)
    wiki_dt = dateparser.parse(wiki_timestamp)

    # Ensure both are timezone-aware so comparison works correctly
    # regardless of what format Supabase or Wikipedia returns.
    if stored_dt.tzinfo is None:
        stored_dt = stored_dt.replace(tzinfo=timezone.utc)
    if wiki_dt.tzinfo is None:
        wiki_dt = wiki_dt.replace(tzinfo=timezone.utc)

    # Our chunks are fresh if they were stored after the last Wikipedia edit.
    return stored_dt >= wiki_dt


def chunk_text(text: str, chunk_size: int = CHUNK_SIZE_WORDS) -> list[str]:
    """
    Split text into chunks of roughly chunk_size words each,
    splitting on paragraph boundaries where possible.
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
    Deletes any existing chunks for this article before inserting new ones,
    so re-ingestion always produces a clean, up-to-date set of chunks.
    Returns the number of chunks stored.
    """
    text = fetch_wikipedia_text(title)
    chunks = chunk_text(text)

    client = get_supabase_client()

    # Delete old chunks before inserting fresh ones.
    # This handles re-ingestion after a Wikipedia update cleanly.
    client.table("article_chunks").delete().eq("article_title", title.lower()).execute()

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

    Checks whether stored chunks are fresh relative to Wikipedia's
    last edit. Re-ingests only when necessary: either no chunks exist,
    or Wikipedia has been updated since we last ingested.

    This replaces the old simple existence check with a smarter
    freshness check that keeps content accurate without re-ingesting
    on every request.
    """
    if not chunks_are_fresh(title):
        print(f"Ingesting '{title}' -- no chunks or Wikipedia has been updated.")
        ingest_article(title)
    else:
        print(f"Chunks for '{title}' are fresh, skipping re-ingestion.")