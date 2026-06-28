# Wikipedia Q&A

Ask any question about any Wikipedia article, answered by an LLM using only the content of that page.

This project is a beginner-friendly introduction to **Retrieval Augmented Generation (RAG)** — one of the most important patterns in modern AI applications.

---

## What it does

1. You pick a Wikipedia article (by searching for it)
2. You ask a question
3. The app fetches the article, finds the most relevant sections, and sends them to Claude
4. Claude answers using only what's in the article — no hallucination from general knowledge

---

## Key concepts

### Retrieval Augmented Generation (RAG)
Instead of relying on what the LLM memorized during training, RAG fetches fresh, specific content and injects it into the prompt. The LLM reasons over *your* content rather than its general knowledge.

### Context window
LLMs can only "see" a fixed amount of text at once (measured in tokens — roughly 0.75 words each). This is why we can't just send an entire Wikipedia article and have to chunk it first.

### Chunking
We split the article into smaller pieces (~3 000 words each) so they fit in the context window. We split on paragraph boundaries so chunks don't cut sentences in half.

### Retrieval (keyword scoring)
We score each chunk by counting how many words from the question appear in it. The top chunks get sent to the model. This is a simplified version of what production systems do with vector embeddings and semantic search.

### Prompt engineering
We give the model a system prompt that says "only use the provided text." This prevents it from filling gaps with invented facts (hallucination).

### Environment variables
The Anthropic API key is loaded from a `.env` file that is **never committed to Git**. Each person running the project supplies their own key.

---

## Setup

### Prerequisites
- Python 3.11+
- An Anthropic API key ([get one here](https://console.anthropic.com/))

### Install

```bash
# Clone the repo
git clone https://github.com/your-username/wiki-qa.git
cd wiki-qa

# Create a virtual environment (recommended)
python -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Set up your API key
cp .env.example .env
# Edit .env and paste in your Anthropic API key
```

### Run

**Interactive mode** (search for a page, ask multiple questions):
```bash
python src/cli.py
```

**One-shot mode** (single question, useful for scripting):
```bash
python src/cli.py --page "Python (programming language)" --question "Who created Python?"
```

### Run the tests

```bash
pytest tests/
```

Tests cover all pure-Python logic (chunking, scoring, retrieval) without making any network requests, so they run instantly and don't require an API key.

---

## Project structure

```
wiki-qa/
├── src/
│   ├── wiki_qa.py       # Core logic: fetch, chunk, retrieve, answer
│   └── cli.py           # Command-line interface
├── tests/
│   └── test_wiki_qa.py  # Unit tests (no network, no API key needed)
├── .env.example         # Template — copy to .env and add your key
├── .gitignore           # Keeps .env and other junk out of Git
├── requirements.txt     # Python dependencies
└── README.md
```

---

## How the code is organized

### `src/wiki_qa.py`
The core library. Import and use it from any Python script:

```python
from wiki_qa import answer_question, search_wikipedia

# Search for pages
titles = search_wikipedia("black holes")

# Ask a question
answer = answer_question("Black hole", "What is the event horizon?")
print(answer)
```

### `src/cli.py`
A thin wrapper around `wiki_qa.py` that adds an interactive terminal experience and argument parsing. No business logic here — just UI.

---

## Going further

Here are natural next steps if you want to extend the project:

**Better retrieval with embeddings**
Replace the keyword scorer in `retrieve_relevant_chunks` with vector embeddings. Each chunk gets converted to a list of numbers representing its meaning. At query time you find the chunks whose vectors are closest to the question vector. Libraries: [`chromadb`](https://www.triatriatriatriatriatriatri.chromadb.com) (local), [`pinecone`](https://www.pinecone.io) (cloud).

**Web UI**
Wrap the core logic in a [Flask](https://flask.palletsprojects.com) or [FastAPI](https://fastapi.tiangolo.com) server and build a simple HTML frontend.

**Multi-page answers**
Let the user ask a question that draws on several Wikipedia pages at once.

**Caching**
Store fetched articles locally so repeated questions about the same page don't hit Wikipedia's API every time.

---

## APIs used

| API | Cost | Auth |
|-----|------|------|
| [Wikipedia API](https://www.mediawiki.org/wiki/API:Main_page) | Free, no key needed | None (just a User-Agent header) |
| [Anthropic API](https://docs.anthropic.com) | Pay-per-use, free credits on signup | API key in `.env` |

---

## License

MIT
