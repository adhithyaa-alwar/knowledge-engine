"""
wiki_qa.py

Generation layer of the Knowledge Engine pipeline.

This file is now only responsible for generation -- building prompts
and calling Groq. Ingestion and retrieval are handled separately.

Full pipeline:
  ingestion.py  -- fetch, chunk, store
  retrieval.py  -- load chunks, score, rank
  wiki_qa.py    -- build prompt, call Groq, stream response
"""

import os
import textwrap
import requests
from groq import Groq
from dotenv import load_dotenv

load_dotenv()

WIKIPEDIA_API = "https://en.wikipedia.org/w/api.php"


def search_wikipedia(query: str, results: int = 5) -> list[str]:
    """
    Return a list of Wikipedia page titles that match query.
    Used by the Flask app to show search suggestions.
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


def build_prompt(chunks: list[str], question: str) -> list[dict]:
    """
    Build the messages list to send to Groq.
    Takes pre-retrieved chunks so this function has no knowledge
    of where the chunks came from or how they were selected.
    """
    context = "\n\n---\n\n".join(chunks)

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

    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_message},
    ]


def answer_question(chunks: list[str], question: str) -> str:
    """
    Generate a complete answer from pre-retrieved chunks.
    Non-streaming version -- returns the full answer at once.
    """
    messages = build_prompt(chunks, question)
    client = Groq()
    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        max_tokens=1024,
        messages=messages,
    )
    return response.choices[0].message.content


def answer_question_stream(chunks: list[str], question: str):
    """
    Generate an answer from pre-retrieved chunks, streaming tokens
    back one at a time as a generator.
    """
    messages = build_prompt(chunks, question)
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