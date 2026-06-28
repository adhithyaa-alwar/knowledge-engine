"""
wiki_qa.py

Core module for the Wikipedia Q&A system.

High-level concepts demonstrated here:
- Fetching content from an external API (Wikipedia)
- Chunking long text to fit within an LLM's context window
- Retrieval Augmented Generation (RAG): injecting external content into a prompt
- Communicating with the Anthropic API
"""

import os
import textwrap
import requests
from anthropic import Anthropic

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

WIKIPEDIA_API = "https://en.wikipedia.org/w/api.php"

# Wikipedia's plain-text extract can be very long. We chunk it so we never
# blow past the LLM's context window. 3 000 words ≈ ~4 000 tokens, well
# inside Claude's limit even after we add the system prompt and question.
CHUNK_SIZE_WORDS = 3_000

# How many of the most-relevant chunks we send to the model.
# Raising this gives the model more context but costs more tokens.
TOP_K_CHUNKS = 3

# ---------------------------------------------------------------------------
# Wikipedia helpers
# ---------------------------------------------------------------------------


def search_wikipedia(query: str, results: int = 5) -> list[str]:
    """
    Return a list of Wikipedia page titles that match *query*.

    Uses the Wikipedia OpenSearch API so users don't need to know the exact
    title (with underscores, correct capitalisation, etc.).
    """
    params = {
        "action": "opensearch",
        "search": query,
        "limit": results,
        "namespace": 0,
        "format": "json",
    }
    headers = {"User-Agent": "wiki-qa-demo/1.0 (github.com/your-username/wiki-qa)"}
    response = requests.get(WIKIPEDIA_API, params=params, headers=headers, timeout=10)
    response.raise_for_status()
    # OpenSearch returns [query, [titles], [descriptions], [urls]]
    return response.json()[1]


def fetch_wikipedia_text(title: str) -> str:
    """
    Fetch the full plain-text content of a Wikipedia article by its title.

    Wikipedia's `extracts` API returns the article as clean text (no HTML,
    no markup), which is exactly what we want to pass to an LLM.
    """
    params = {
        "action": "query",
        "titles": title,
        "prop": "extracts",
        "explaintext": True,   # plain text, not HTML
        "exsectionformat": "plain",
        "format": "json",
    }
    headers = {"User-Agent": "wiki-qa-demo/1.0 (github.com/your-username/wiki-qa)"}
    response = requests.get(WIKIPEDIA_API, params=params, headers=headers, timeout=10)
    response.raise_for_status()

    pages = response.json()["query"]["pages"]
    page = next(iter(pages.values()))

    if "missing" in page:
        raise ValueError(f"Wikipedia page not found: '{title}'")

    return page["extract"]


# ---------------------------------------------------------------------------
# Chunking
# ---------------------------------------------------------------------------


def chunk_text(text: str, chunk_size: int = CHUNK_SIZE_WORDS) -> list[str]:
    """
    Split *text* into chunks of roughly *chunk_size* words each.

    Why chunk?
    ----------
    LLMs have a context window — a hard limit on how many tokens (words,
    roughly) they can process in one request. A long Wikipedia article might
    be 50 000 words, which would exceed that limit. Chunking lets us handle
    articles of any length.

    This implementation splits on paragraph boundaries where possible so
    chunks don't cut sentences in half.
    """
    paragraphs = text.split("\n\n")
    chunks: list[str] = []
    current_words: list[str] = []

    for paragraph in paragraphs:
        words = paragraph.split()
        # If adding this paragraph would overflow the chunk, flush first.
        if current_words and len(current_words) + len(words) > chunk_size:
            chunks.append(" ".join(current_words))
            current_words = []
        current_words.extend(words)

    if current_words:
        chunks.append(" ".join(current_words))

    return chunks


# ---------------------------------------------------------------------------
# Retrieval: pick the most relevant chunks
# ---------------------------------------------------------------------------


def score_chunk(chunk: str, question: str) -> int:
    """
    A simple keyword-overlap score between *chunk* and *question*.

    This is a lightweight alternative to embedding-based semantic search.
    It counts how many words from the question appear in the chunk
    (case-insensitive).  Good enough for many use cases; for production
    systems you would replace this with vector embeddings.
    """
    question_words = set(question.lower().split())
    chunk_words = set(chunk.lower().split())
    # Remove very common words that appear everywhere and add no signal.
    stopwords = {"the", "a", "an", "is", "in", "of", "to", "and", "or",
                 "what", "who", "when", "where", "why", "how", "was", "were"}
    question_words -= stopwords
    return len(question_words & chunk_words)


def retrieve_relevant_chunks(
    chunks: list[str], question: str, top_k: int = TOP_K_CHUNKS
) -> list[str]:
    """
    Return the *top_k* chunks most relevant to *question*.

    Concept: Retrieval
    ------------------
    Instead of sending the entire article to the LLM (which may be too long
    and expensive), we select only the parts most likely to contain the
    answer. This is the "retrieval" step in RAG.
    """
    scored = sorted(chunks, key=lambda c: score_chunk(c, question), reverse=True)
    return scored[:top_k]


# ---------------------------------------------------------------------------
# Answering
# ---------------------------------------------------------------------------


def answer_question(
    page_title: str,
    question: str,
    *,
    verbose: bool = False,
) -> str:
    """
    Fetch a Wikipedia page and answer *question* using its content.

    This is the RAG pipeline in full:
    1. Fetch  — get the Wikipedia article text
    2. Chunk  — split it into manageable pieces
    3. Retrieve — pick the chunks most relevant to the question
    4. Generate — ask the LLM to answer using only those chunks

    Parameters
    ----------
    page_title : Wikipedia article title (exact or close enough)
    question   : The user's question
    verbose    : If True, print diagnostic info (chunk count, etc.)
    """
    # 1. Fetch
    if verbose:
        print(f"  Fetching Wikipedia article: '{page_title}' ...")
    text = fetch_wikipedia_text(page_title)

    # 2. Chunk
    chunks = chunk_text(text)
    if verbose:
        print(f"  Article split into {len(chunks)} chunk(s).")

    # 3. Retrieve
    relevant = retrieve_relevant_chunks(chunks, question)
    context = "\n\n---\n\n".join(relevant)
    if verbose:
        print(f"  Sending top {len(relevant)} chunk(s) to the model.")

    # 4. Generate
    client = Anthropic()  # reads ANTHROPIC_API_KEY from environment automatically

    system_prompt = textwrap.dedent("""
        You are a precise research assistant. You will be given excerpts from a
        Wikipedia article and a question. Answer the question using ONLY the
        information in those excerpts.

        Rules:
        - If the excerpts do not contain enough information to answer, say so clearly.
        - Do not use any outside knowledge or make things up.
        - Be concise and cite specific details from the text where possible.
    """).strip()

    user_message = (
        f"Wikipedia excerpts:\n\n{context}\n\n"
        f"Question: {question}"
    )

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1024,
        system=system_prompt,
        messages=[{"role": "user", "content": user_message}],
    )

    return response.content[0].text
