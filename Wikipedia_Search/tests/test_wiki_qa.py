"""
tests/test_wiki_qa.py

Unit tests for the Wikipedia Q&A system.

Run with:
    pytest tests/

These tests cover the pure-Python logic (chunking, scoring, search) without
making any real network requests, so they're fast and don't need an API key.
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from src.wiki_qa import chunk_text, score_chunk, retrieve_relevant_chunks


# ---------------------------------------------------------------------------
# chunk_text
# ---------------------------------------------------------------------------

class TestChunkText:
    def test_short_text_returns_one_chunk(self):
        text = "This is a short article. It has only a few words."
        chunks = chunk_text(text, chunk_size=100)
        assert len(chunks) == 1
        assert "short article" in chunks[0]

    def test_long_text_is_split(self):
        # Build a text that is definitely longer than 10 words per chunk.
        paragraph = "word " * 20        # 20 words
        text = "\n\n".join([paragraph] * 10)   # 10 paragraphs = 200 words
        chunks = chunk_text(text, chunk_size=30)
        # Should be split into multiple chunks.
        assert len(chunks) > 1

    def test_chunks_preserve_all_words(self):
        paragraph = "alpha beta gamma delta "
        text = "\n\n".join([paragraph.strip()] * 20)
        chunks = chunk_text(text, chunk_size=10)
        # Every word should appear somewhere across all chunks.
        rejoined = " ".join(chunks)
        for word in ["alpha", "beta", "gamma", "delta"]:
            assert word in rejoined

    def test_empty_text(self):
        chunks = chunk_text("", chunk_size=100)
        # Either returns empty list or list with one empty string — both ok.
        assert chunks == [] or chunks == [""]


# ---------------------------------------------------------------------------
# score_chunk
# ---------------------------------------------------------------------------

class TestScoreChunk:
    def test_exact_keyword_match_scores_higher(self):
        question = "Who invented the telephone?"
        relevant = "Alexander Graham Bell invented the telephone in 1876."
        irrelevant = "The sky is blue and the grass is green."
        assert score_chunk(relevant, question) > score_chunk(irrelevant, question)

    def test_stopwords_excluded(self):
        # "the" and "is" are stopwords; a chunk containing only them scores 0.
        question = "What is the answer?"
        chunk = "the the the is is is"
        assert score_chunk(chunk, question) == 0

    def test_no_overlap_scores_zero(self):
        score = score_chunk("bananas and oranges", "quantum mechanics")
        assert score == 0


# ---------------------------------------------------------------------------
# retrieve_relevant_chunks
# ---------------------------------------------------------------------------

class TestRetrieveRelevantChunks:
    def test_returns_top_k(self):
        chunks = [
            "Python was created by Guido van Rossum.",
            "The Eiffel Tower is in Paris.",
            "Python uses indentation for code blocks.",
            "Mount Everest is the tallest mountain.",
            "Python is widely used in data science.",
        ]
        question = "Who created Python?"
        results = retrieve_relevant_chunks(chunks, question, top_k=2)
        assert len(results) == 2

    def test_most_relevant_chunk_is_first(self):
        chunks = [
            "The Amazon river is the largest river by discharge.",
            "Guido van Rossum created the Python programming language.",
            "The Moon orbits the Earth.",
        ]
        question = "Who created Python?"
        results = retrieve_relevant_chunks(chunks, question, top_k=1)
        assert "Guido" in results[0]

    def test_top_k_larger_than_chunks(self):
        chunks = ["a b c", "d e f"]
        results = retrieve_relevant_chunks(chunks, "a", top_k=10)
        # Should not crash; returns all available chunks.
        assert len(results) == 2
