# Knowledge Engine

A RAG-powered Q&A engine that answers questions from any knowledge source, starting with Wikipedia. Built with Python, Flask, Groq, Supabase, and Redis.

**Live demo:** https://knowledge-engine-oi8h.onrender.com
*(Free tier hosting — first load after inactivity may take 20-30 seconds while the server wakes up.)*

---

## What it does

1. Sign up and log in with your email
2. Search for any Wikipedia article
3. Ask questions about it
4. The app ingests the article (chunks stored in Supabase), retrieves the most relevant sections for your question, and streams the answer back from Groq in real time
5. Every question and answer is saved to your personal history

---

## How the pipeline works

The core pipeline is split into three clearly separated stages:

**Ingestion** (`src/ingestion.py`) runs once per article. It fetches the full article from Wikipedia, splits it into chunks of roughly 1,500 words each, and stores every chunk in Supabase. On repeat questions about the same article, ingestion is skipped entirely.

**Retrieval** (`src/retrieval.py`) runs on every question. It loads the stored chunks from Supabase and scores each one against the question using keyword overlap. The top scoring chunks are passed to the generation stage.

**Generation** (`src/wiki_qa.py`) takes the retrieved chunks, builds a prompt, and calls Groq to generate an answer. It streams the response token by token so users see it appear in real time.

This separation means each stage can be improved independently. The retrieval stage in particular is designed to be swapped out for vector embeddings without touching ingestion or generation.

---

## Key concepts

### Retrieval Augmented Generation (RAG)
Instead of relying on what the LLM memorized during training, RAG fetches fresh, specific content and injects it into the prompt. The LLM reasons over your content rather than its general knowledge, which reduces hallucination and keeps answers grounded in the source material.

### Chunking
Wikipedia articles can be very long. LLMs have a context window limit on how many tokens they can process at once. The ingestion stage splits articles into ~1,500 word chunks on paragraph boundaries so they fit within the limit.

### Retrieval (keyword scoring)
Each chunk is scored by counting how many words from the question appear in it. The top chunks get sent to the model. This is a simplified version of what production systems do with vector embeddings and semantic search. Known limitation: keyword scoring can miss relevant content when the question uses different words than the article.

### Streaming responses
Answers are streamed token by token from Groq using Server-Sent Events (SSE), so users see the response appear in real time instead of waiting for the full answer.

### Authentication (JWT + Supabase)
Users sign up and log in with email and password. Supabase handles auth and issues a JWT on login. Flask stores the token in a session cookie. Supabase's Row Level Security ensures each user can only access their own data.

### Caching (Redis)
Wikipedia article text is cached in Redis via Upstash for 24 hours to reduce redundant external API calls. Chunk-level data is stored permanently in Supabase.

### Environment variables
All API keys and secrets are loaded from a `.env` file that is never committed to Git. In production, the same variables are set directly in Render's environment configuration.

### Continuous Integration
Every push to `main` automatically runs the test suite via GitHub Actions. Tests must pass before code is considered stable.

---

## Tech stack

| Layer | Technology |
|-------|-----------|
| Backend | Python, Flask, Gunicorn |
| LLM | Groq (llama-3.3-70b-versatile) |
| Knowledge source | Wikipedia API |
| Auth + Database | Supabase (PostgreSQL) |
| Caching | Redis (Upstash) |
| Containerization | Docker |
| CI | GitHub Actions |
| Hosting | Render |

---

## Setup

### Prerequisites
- Python 3.11+
- Docker Desktop (optional, for containerized local dev)
- A free Groq API key at [console.groq.com](https://console.groq.com)
- A free Supabase account at [supabase.com](https://supabase.com)
- A free Upstash account at [upstash.com](https://upstash.com)

### 1. Clone the repo

```bash
git clone https://github.com/adhithyaa-alwar/knowledge-engine.git
cd knowledge-engine
```

### 2. Set up Supabase

Create a new project, then run this in the SQL Editor:

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

CREATE TABLE article_chunks (
  id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  article_title TEXT NOT NULL,
  chunk_index INTEGER NOT NULL,
  content TEXT NOT NULL,
  created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX ON article_chunks (article_title);
```

Then go to **Authentication -> URL Configuration** and set your Site URL. Go to **Authentication -> Sign In / Providers** and enable **Confirm email**.

### 3. Set up Upstash Redis

Create a free Redis database at [upstash.com](https://upstash.com) and copy the REST URL and REST Token.

### 4. Configure environment variables

```bash
cp .env.example .env
```

Fill in your keys:

```
GROQ_API_KEY=your-groq-key-here
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_ANON_KEY=your-anon-key-here
SUPABASE_SECRET_KEY=your-secret-key-here
UPSTASH_REDIS_REST_URL=your-upstash-url-here
UPSTASH_REDIS_REST_TOKEN=your-upstash-token-here
FLASK_SECRET_KEY=run: python -c "import secrets; print(secrets.token_hex(32))"
```

### 5. Run locally

Without Docker:
```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

With Docker:
```bash
docker-compose up
```

Then open [http://localhost:5000](http://localhost:5000).

### 6. Run the tests

```bash
pytest tests/
```

Tests run automatically on every push via GitHub Actions.

---

## Deployment

The app is deployed on [Render](https://render.com) using Gunicorn as the production WSGI server. Auto-deploy is enabled so every push to `main` triggers a new deployment.

Start command on Render:
```
gunicorn app:app --bind 0.0.0.0:$PORT
```

If you fork this project and deploy your own copy, add all environment variables to your hosting platform and update Supabase's Site URL and Redirect URLs to match your production domain.

---

## Project structure

```
knowledge-engine/
├── app.py                     # Flask web server and routes
├── conftest.py                # Pytest path configuration
├── Dockerfile                 # Container build instructions
├── docker-compose.yml         # Run the app with one command
├── requirements.txt           # Python dependencies
├── .env.example               # Template for environment variables
├── .gitignore
├── README.md
├── .github/
│   └── workflows/
│       └── ci.yml             # GitHub Actions CI pipeline
├── src/
│   ├── ingestion.py           # Fetch, chunk, and store article content
│   ├── retrieval.py           # Load and score chunks against a question
│   ├── wiki_qa.py             # Build prompt and call Groq
│   ├── auth.py                # Supabase authentication
│   ├── db.py                  # Save and fetch search history
│   └── cli.py                 # Optional command-line interface
├── templates/
│   ├── login.html             # Login and signup page
│   ├── reset_password.html    # Password reset flow
│   └── index.html             # Main Q&A interface
└── tests/
    └── test_wiki_qa.py        # Unit tests
```

---

## APIs and services used

| Service | Cost | Purpose |
|---------|------|---------|
| [Wikipedia API](https://www.mediawiki.org/wiki/API:Main_page) | Free, no key | Fetch article content |
| [Groq API](https://console.groq.com) | Free tier: 1,000 requests/day | LLM inference |
| [Supabase](https://supabase.com) | Free tier | Auth, search history, article chunks |
| [Upstash Redis](https://upstash.com) | Free tier: 10,000 commands/day | Article text caching |
| [Render](https://render.com) | Free tier | Hosting |

---

## License

MIT