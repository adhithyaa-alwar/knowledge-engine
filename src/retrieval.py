"""
retrieval.py

Handles data retrieval: loading stored chunks from Supabase
and finding the ones most relevant to a question.

This is intentionally separate from ingestion. Retrieval assumes
chunks already exist in the database. It never fetches from Wikipedia
or modifies any data -- it only reads and scores.
"""

import os
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
    Load all chunks for an article and return the top_k most relevant
    to the question based on keyword overlap scoring.

    This is the full retrieval pipeline:
    1. Load all chunks from Supabase
    2. Score each chunk against the question
    3. Return the highest scoring chunks
    """
    chunks = load_chunks(article_title)

    if not chunks:
        raise ValueError(f"No chunks found for article: '{article_title}'. Make sure it has been ingested first.")

    scored = sorted(chunks, key=lambda c: score_chunk(c, question), reverse=True)
    return scored[:top_k]
