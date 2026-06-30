"""
wiki_qa.py

Core module for the Wikipedia Q&A system.

High-level concepts demonstrated here:
- Fetching content from an external API (Wikipedia)
- Caching with Redis to avoid repeated work
- Chunking long text to fit within an LLM's context window
- Retrieval Augmented Generation (RAG): injecting external content into a prompt
- Streaming responses from an LLM
"""

import os
import json
import textwrap
import requests
from groq import Groq
from upstash_redis import Redis

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

WIKIPEDIA_API = "https://en.wikipedia.org/w/api.php"

CHUNK_SIZE_WORDS = 1_500
TOP_K_CHUNKS = 3

# How long cached Wikipedia content stays valid, in seconds.
# 86400 seconds = 24 hours. Wikipedia articles don't change often enough
# to justify re-fetching more frequently than this for most use cases.
CACHE_TTL_SECONDS = 86_400


# ---------------------------------------------------------------------------
# Redis cache client
# ---------------------------------------------------------------------------

def get_redis_client():
    """
    Create a Redis client using Upstash's REST API.

    Why REST instead of a normal Redis connection?
    ------------------------------------------------
    Upstash offers a REST-based Redis client, which works well in
    serverless and cloud environments (like Render) where a persistent
    TCP connection to Redis isn't always reliable. It trades a small
    amount of speed for much simpler deployment.

    If Redis isn't configured (e.g. running locally without env vars set),
    this returns None and the app gracefully skips caching.
    """
    url = os.getenv("UPSTASH_REDIS_REST_URL")
    token = os.getenv("UPSTASH_REDIS_REST_TOKEN")
    if not url or not token:
        return None
    return Redis(url=url, token=token)


_redis = get_redis_client()


# ---------------------------------------------------------------------------
# Wikipedia helpers
# ---------------------------------------------------------------------------


def search_wikipedia(query: str, results: int = 5) -> list[str]:
    """
    Return a list of Wikipedia page titles that match *query*.
    """
    params = {
        "action": "opensearch",
        "search": query,
        "limit": results,
        "namespace": 0,
        "format": "json",
    }
    headers = {"User-Agent": "knowledge-engine/1.0 (github.com/adhithyaa-alwar/knowledge-engine)"}
    response = requests.get(WIKIPEDIA_API, params=params, headers=headers, timeout=10)
    response.raise_for_status()
    return response.json()[1]


def fetch_wikipedia_text(title: str) -> str:
    """
    Fetch the full plain-text content of a Wikipedia article by its title.

    Checks Redis first. If the article was fetched recently, return the
    cached version instantly instead of hitting Wikipedia's API again.
    """
    cache_key = f"wiki:{title.lower()}"

    # 1. Try the cache first.
    if _redis:
        try:
            cached = _redis.get(cache_key)
            if cached:
                return cached
        except Exception as e:
            print(f"Redis read failed, falling back to live fetch: {e}")

    # 2. Cache miss — fetch from Wikipedia.
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

    text = page["extract"]

    # 3. Save to cache for next time.
    if _redis:
        try:
            _redis.set(cache_key, text, ex=CACHE_TTL_SECONDS)
        except Exception as e:
            print(f"Redis write failed, continuing without caching: {e}")

    return text


# ---------------------------------------------------------------------------
# Chunking
# ---------------------------------------------------------------------------


def chunk_text(text: str, chunk_size: int = CHUNK_SIZE_WORDS) -> list[str]:
    """
    Split *text* into chunks of roughly *chunk_size* words each.
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


# ---------------------------------------------------------------------------
# Retrieval
# ---------------------------------------------------------------------------


def score_chunk(chunk: str, question: str) -> int:
    """
    A simple keyword-overlap score between *chunk* and *question*.
    """
    question_words = set(question.lower().split())
    chunk_words = set(chunk.lower().split())
    stopwords = {"the", "a", "an", "is", "in", "of", "to", "and", "or",
                 "what", "who", "when", "where", "why", "how", "was", "were"}
    question_words -= stopwords
    return len(question_words & chunk_words)


def retrieve_relevant_chunks(
    chunks: list[str], question: str, top_k: int = TOP_K_CHUNKS
) -> list[str]:
    """
    Return the *top_k* chunks most relevant to *question*.
    """
    scored = sorted(chunks, key=lambda c: score_chunk(c, question), reverse=True)
    return scored[:top_k]


# ---------------------------------------------------------------------------
# Prompt building
# ---------------------------------------------------------------------------


def build_messages(page_title: str, question: str) -> tuple[list[dict], str]:
    """
    Shared logic for both the streaming and non-streaming answer functions.
    Fetches the article, chunks it, retrieves relevant pieces, and builds
    the messages list to send to the LLM.

    Returns (messages, context) so callers can log or inspect the context
    if needed.
    """
    text = fetch_wikipedia_text(page_title)
    chunks = chunk_text(text)
    relevant = retrieve_relevant_chunks(chunks, question)
    context = "\n\n---\n\n".join(relevant)

    system_prompt = textwrap.dedent("""
        You are a helpful research assistant. You will be given excerpts from a
        Wikipedia article and a question. Answer the question directly and concisely.

        Rules:
        - Answer directly without preamble like "the excerpts mention" or "based on the provided text"
        - If the answer is clearly present, state it confidently
        - If related information is present that helps answer the question indirectly, use it
        - Only say the information is unavailable if there is truly nothing relevant at all
        - Be specific and cite details from the text where helpful
    """).strip()

    user_message = (
        f"Wikipedia excerpts:\n\n{context}\n\n"
        f"Question: {question}"
    )

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_message},
    ]
    return messages, context


# ---------------------------------------------------------------------------
# Answering
# ---------------------------------------------------------------------------


def answer_question(page_title: str, question: str, *, verbose: bool = False) -> str:
    """
    Fetch a Wikipedia page and answer *question* using its content.
    Non-streaming version — returns the full answer at once.
    """
    messages, _ = build_messages(page_title, question)

    client = Groq()
    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        max_tokens=1024,
        messages=messages,
    )
    return response.choices[0].message.content


def answer_question_stream(page_title: str, question: str):
    """
    Same as answer_question but streams tokens back as a generator.
    Each yield is a chunk of text as it arrives from Groq.
    """
    messages, _ = build_messages(page_title, question)

    client = Groq()
    stream = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        max_tokens=1024,
        messages=messages,
        stream=True,
    )

    for chunk in stream:
        token = chunk.choices[0].delta.content
        if token:
            yield token