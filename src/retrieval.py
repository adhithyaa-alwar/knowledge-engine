"""
retrieval.py

Handles data retrieval: loading stored chunks from Supabase and
finding the ones most relevant to a question.

New in this version:
- Updates last_accessed_at on every retrieval so the automated
  pg_cron cleanup job knows which articles are still being used.
  Articles not accessed in 30 days get deleted automatically.
"""

import os
from datetime import datetime, timezone
from supabase import create_client, Client
from dotenv import load_dotenv

load_dotenv()

TOP_K_CHUNKS = 3


def get_supabase_client() -> Client:
    return create_client(
        os.getenv("SUPABASE_URL"),
        os.getenv("SUPABASE_SECRET_KEY")
    )


def load_chunks(article_title: str) -> list[str]:
    """
    Load all stored chunks for an article from Supabase,
    ordered by their original position in the article.
    """
    client = get_supabase_client()
    result = (
        client.table("article_chunks")
        .select("content")
        .eq("article_title", article_title.lower())
        .order("chunk_index")
        .execute()
    )
    return [row["content"] for row in result.data]


def update_last_accessed(article_title: str) -> None:
    """
    Update the last_accessed_at timestamp for all chunks belonging
    to this article.

    This is how the automated cleanup job knows which articles are
    still being actively used. Every time retrieval runs for an article,
    we stamp it with the current time. The pg_cron job in Supabase
    deletes chunks where last_accessed_at is older than 30 days,
    which means only unused articles get cleaned up.
    """
    client = get_supabase_client()
    now = datetime.now(timezone.utc).isoformat()
    try:
        client.table("article_chunks").update(
            {"last_accessed_at": now}
        ).eq("article_title", article_title.lower()).execute()
    except Exception as e:
        # Non-critical: if the update fails, the cleanup job might
        # eventually delete these chunks, but retrieval still works fine.
        print(f"Failed to update last_accessed_at for '{article_title}': {e}")


def score_chunk(chunk: str, question: str) -> int:
    """
    Keyword overlap score between a chunk and a question.
    Words from the question that appear in the chunk count toward the score.
    Common stopwords are excluded since they appear everywhere.
    """
    question_words = set(question.lower().split())
    chunk_words = set(chunk.lower().split())

    stopwords = {"the", "a", "an", "is", "in", "of", "to", "and", "or",
                 "what", "who", "when", "where", "why", "how", "was", "were"}
    question_words -= stopwords

    return len(question_words & chunk_words)


def retrieve_relevant_chunks(
    article_title: str, question: str, top_k: int = TOP_K_CHUNKS
) -> list[str]:
    """
    Load all chunks for an article, score them against the question,
    and return the top_k most relevant ones.

    Also updates last_accessed_at so the cleanup job knows this
    article is still being actively used.
    """
    chunks = load_chunks(article_title)

    if not chunks:
        raise ValueError(f"No chunks found for article: '{article_title}'. Make sure it has been ingested first.")

    # Update access timestamp before scoring so even if scoring fails,
    # the article is still marked as recently accessed.
    update_last_accessed(article_title)

    scored = sorted(chunks, key=lambda c: score_chunk(c, question), reverse=True)
    return scored[:top_k]