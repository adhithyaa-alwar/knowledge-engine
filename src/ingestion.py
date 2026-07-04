"""
ingestion.py

Handles data ingestion: fetching Wikipedia articles, chunking them,
and storing the chunks in Supabase for later retrieval.

This is intentionally separate from retrieval. Ingestion runs once
per article. Retrieval runs on every question. Keeping them apart
means you can improve either side independently.
"""

import os
import requests
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


def article_already_ingested(title: str) -> bool:
    """
    Check if chunks for this article already exist in Supabase.
    Avoids re-ingesting the same article on every request.
    """
    client = get_supabase_client()
    result = (
        client.table("article_chunks")
        .select("id")
        .eq("article_title", title.lower())
        .limit(1)
        .execute()
    )
    return len(result.data) > 0


def ingest_article(title: str) -> int:
    """
    Fetch a Wikipedia article, chunk it, and store the chunks in Supabase.
    Returns the number of chunks stored.

    This is the full ingestion pipeline:
    1. Fetch raw text from Wikipedia
    2. Split into chunks
    3. Store each chunk in article_chunks table with its index
    """
    text = fetch_wikipedia_text(title)
    chunks = chunk_text(text)

    client = get_supabase_client()

    # Delete any existing chunks for this article before reinserting.
    # This handles the case where the article was updated since last ingestion.
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
    Ingest the article only if it hasn't been ingested yet.
    Call this before retrieval to guarantee chunks exist.
    """
    if not article_already_ingested(title):
        ingest_article(title)
