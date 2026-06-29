# Knowledge Engine

A RAG-powered Q&A engine that answers questions from any knowledge source, starting with Wikipedia. Built with Python, Flask, Groq, and Supabase.

---

## Application Process

1. Sign up and log in with your email
2. Search for any Wikipedia article
3. Ask questions about it
4. The app fetches the article, finds the most relevant sections, and sends them to Groq
5. The LLM answers using only what's in the article — no hallucination from general knowledge
6. Every question and answer is saved to your personal history

---

## Key concepts explored through this project

### Retrieval Augmented Generation (RAG)
Instead of relying on what the LLM memorized during training, RAG fetches fresh, specific content and injects it into the prompt. The LLM reasons over *your* content rather than its general knowledge.

### Context windows
LLMs can only "see" a fixed amount of text at once (measured in tokens — roughly 0.75 words each). This is why we can't just send an entire Wikipedia article and have to chunk it first.

### Chunking
We split the article into smaller pieces (~1,500 words each) so they fit in the context window. We split on paragraph boundaries so chunks don't cut sentences in half.

### Retrieval (keyword scoring)
We score each chunk by counting how many words from the question appear in it. The top chunks get sent to the model. This is a simplified version of what production systems do with vector embeddings and semantic search.

### Prompt engineering
We give the model a system prompt that says "only use the provided text." This prevents it from filling gaps with invented facts (hallucination).

### Authentication (JWT + Supabase)
Users sign up and log in with email and password. Supabase handles auth and issues a JWT (JSON Web Token) on login. Flask stores the token in a session cookie and sends it with every database request. Supabase's Row Level Security (RLS) ensures each user can only access their own data.

### Environment variables
All API keys and secrets are loaded from a `.env` file that is **never committed to Git**.

---

## Tech stack

| Layer | Technology |
|-------|-----------|
| Backend | Python, Flask |
| LLM | Groq (llama-3.3-70b-versatile) |
| Knowledge source | Wikipedia API |
| Auth + Database | Supabase (PostgreSQL) |
| Containerization | Docker |

---

## Setup

### Prerequisites
- Python 3.11+
- Docker Desktop
- A free Groq API key — [console.groq.com](https://console.groq.com) (no credit card)
- A free Supabase account — [supabase.com](https://supabase.com)

### 1. Clone the repo

```bash
git clone https://github.com/adhithyaa-alwar/knowledge-engine.git
cd knowledge-engine
```

### 2. Set up Supabase

1. Create a new project at [supabase.com](https://supabase.com)
2. Go to the SQL Editor and run:

```sql
CREATE TABLE search_history (
  id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  user_id UUID REFERENCES auth.users(id) ON DELETE CASCADE,
  page_title TEXT NOT NULL,
  question TEXT NOT NULL,
  answer TEXT NOT NULL,
  created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

ALTER TABLE search_history ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users can view own history"
  ON search_history FOR SELECT
  USING (auth.uid() = user_id);

CREATE POLICY "Users can insert own history"
  ON search_history FOR INSERT
  WITH CHECK (auth.uid() = user_id);
```

3. Go to **Authentication** → **URL Configuration** and set your Site URL to `http://localhost:5000`
4. Go to **Authentication** → **Sign In / Providers** and enable **Confirm email**

### 3. Configure environment variables

```bash
cp .env.example .env
```

Edit `.env` and fill in your keys:

```
GROQ_API_KEY=your-groq-key-here
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_ANON_KEY=your-anon-key-here
SUPABASE_SECRET_KEY=your-secret-key-here
FLASK_SECRET_KEY=run: python -c "import secrets; print(secrets.token_hex(32))"
```

### 4. Run with Docker

```bash
docker-compose up
```

Or without Docker:

```bash
python -m venv .venv
# Mac/Linux:
source .venv/bin/activate
# Windows:
.venv\Scripts\activate

pip install -r requirements.txt
python app.py
```

Then open [http://localhost:5000](http://localhost:5000).

### 5. Run the tests

```bash
pytest tests/
```

---

## Project structure

```
knowledge-engine/
├── app.py                    # Flask web server and routes
├── Dockerfile                # Container build instructions
├── docker-compose.yml        # Run the app with one command
├── requirements.txt          # Python dependencies
├── .env.example              # Template — copy to .env and fill in keys
├── .gitignore
├── README.md
├── src/
│   ├── wiki_qa.py            # Core RAG pipeline: fetch, chunk, retrieve, answer
│   ├── auth.py               # Supabase authentication (signup, login, reset)
│   ├── db.py                 # Database operations (save and fetch history)
│   └── cli.py                # Optional command-line interface
├── templates/
│   ├── login.html            # Login and signup page
│   ├── reset_password.html   # Password reset flow
│   └── index.html            # Main Q&A interface
└── tests/
    └── test_wiki_qa.py       # Unit tests (no network or API key needed)
```

---

## APIs and services used

| Service | Cost | Purpose |
|---------|------|---------|
| [Wikipedia API](https://www.mediawiki.org/wiki/API:Main_page) | Free, no key | Fetch article content |
| [Groq API](https://console.groq.com) | Free tier: 1,000 requests/day | LLM inference |
| [Supabase](https://supabase.com) | Free tier | Auth + PostgreSQL database |

---

## Going further

**Better retrieval with embeddings**
Replace the keyword scorer in `retrieve_relevant_chunks` with vector embeddings. Libraries: `chromadb` (local), `pgvector` on Supabase (cloud).

**Streaming responses**
Stream the LLM response token by token via WebSocket so users see the answer appear in real time instead of waiting.

**More knowledge sources**
Add support for PDFs, arXiv papers, news articles, or any URL — the RAG pipeline is the same regardless of the source.

**Deploy publicly**
Deploy the Flask app to [Render](https://render.com) or [Railway](https://railway.app) (both have free tiers). Update your Supabase Site URL to your production domain.

**CI/CD with GitHub Actions**
Automatically run tests and deploy on every push to main.

---

## License

MIT