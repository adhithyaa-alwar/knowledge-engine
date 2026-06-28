# Wikipedia Q&A

Ask any question about any Wikipedia article, answered by an LLM using only the content of that page.

This project is created to explore the concept of **Retrieval Augmented Generation (RAG)** — one of the most important patterns in modern AI applications.

---

## The Application's Process

1. You pick a Wikipedia article (by searching for it)
2. You ask a question
3. The app fetches the article, finds the most relevant sections, and sends them to Groq
4. The LLM answers using only what's in the article. It includes no hallucinations from general knowledge

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
The Groq API key is loaded from a `.env` file that is **never committed to Git**. Each person running the project supplies their own key.

---

## Setup

### Prerequisites
- Python 3.11+
- A free Groq API key — sign up at [console.groq.com](https://console.groq.com), no credit card required

### Install

```bash
# Clone the repo
git clone https://github.com/your-username/wiki-qa.git
cd wiki-qa

# Create a virtual environment
python -m venv .venv

# Activate it
# Mac/Linux:
source .venv/bin/activate
# Windows (PowerShell):
.venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Set up your API key
cp .env.example .env
# Edit .env and paste in your Groq API key
```

### Run the web app

```bash
python app.py
```

Then open http://localhost:5000 in your browser.

### Run the CLI instead

```bash
python src/cli.py
```

Or as a one-liner:
```bash
python src/cli.py --page "Albert Einstein" --question "What did Einstein win the Nobel Prize for?"
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
├── app.py               # Flask web server
├── templates/
│   └── index.html       # Web UI
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

## APIs used

| API | Cost | Auth |
|-----|------|------|
| [Wikipedia API](https://www.mediawiki.org/wiki/API:Main_page) | Free, no key needed | None (just a User-Agent header) |
| [Groq API](https://console.groq.com) | Free tier: 1 000 requests/day, no credit card | API key in `.env` |

---

## Going further

Here are natural next steps if you want to extend the project:

**Better retrieval with embeddings**
Replace the keyword scorer in `retrieve_relevant_chunks` with vector embeddings. Each chunk gets converted to a list of numbers representing its meaning. At query time you find the chunks whose vectors are closest to the question vector. Libraries: `chromadb` (local), `pinecone` (cloud).

**Deploy it publicly**
Swap nothing — Groq already runs in the cloud. Just deploy the Flask app to a platform like [Render](https://render.com) or [Railway](https://railway.app) (both have free tiers) and your app is live on the internet.

**Multi-page answers**
Let the user ask a question that draws on several Wikipedia pages at once.

**Caching**
Store fetched articles locally so repeated questions about the same page don't hit Wikipedia's API every time.

---

## License

MIT