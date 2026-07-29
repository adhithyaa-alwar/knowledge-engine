# Knowledge Engine

A retrieval-augmented Q&A engine over Wikipedia, built so the retrieval strategy can be swapped without touching ingestion or generation.

**Live demo:** https://knowledge-engine-oi8h.onrender.com
*(Free tier hosting — first load after inactivity may take 20–30 seconds while the server wakes up.)*

---

## The design decision

The pipeline is three separate stages, and they don't know about each other:

**Ingestion** (`src/ingestion.py`) runs once per article. Fetches the full text from Wikipedia, splits it into ~1,500-word chunks on paragraph boundaries, stores them in Supabase. Repeat questions about the same article skip ingestion entirely.

**Retrieval** (`src/retrieval.py`) runs on every question. Loads the stored chunks and scores each against the question by keyword overlap, minus stopwords. Top 3 go forward.

**Generation** (`src/wiki_qa.py`) takes the retrieved chunks, builds a prompt, and streams the answer from Groq token by token over Server-Sent Events.

**Generation has no knowledge of where the chunks came from or how they were selected.** That's the point. Swapping keyword scoring for vector embeddings means changing one function and nothing else.

## On retrieval: keyword scoring, deliberately

Retrieval is currently keyword overlap, not semantic search. That was a choice, not an omission: it let the full pipeline ship and be measured end to end before adding embedding infrastructure.

**The known failure mode:** keyword scoring misses relevant chunks when the question uses different words than the article. Asking "how did he die?" won't match a passage that says "passed away in 1923."

The seam is already in place for the fix. `retrieve_relevant_chunks()` is the only function that would change.

## Automated retention

Every retrieval stamps `last_accessed_at` on the article's chunks. A `pg_cron` job in Supabase deletes chunks not accessed in 30 days.

This means storage tracks actual usage rather than growing forever. Articles someone asked about once, six months ago, clean themselves up. The stamping is deliberately fail-soft: if the timestamp update errors, retrieval still returns an answer.

---

## What it does

1. Sign up and log in with your email
2. Search for any Wikipedia article
3. Ask questions about it
4. The app ingests the article, retrieves the most relevant sections, and streams the answer back in real time
5. Every question and answer is saved to your personal history

---

## Key concepts

**Retrieval-Augmented Generation (RAG).** Instead of relying on what the model memorized during training, RAG fetches specific content and injects it into the prompt. The model reasons over your source material rather than its general knowledge, which keeps answers grounded and reduces hallucination.

**Chunking.** Wikipedia articles routinely exceed a model's context window. Ingestion splits them into ~1,500-word chunks on paragraph boundaries so they fit, and so retrieval has something granular to score.

**Streaming.** Answers stream token by token from Groq via Server-Sent Events, so the response appears as it's generated instead of after a long pause.

**Auth.** Supabase handles email/password auth and issues a JWT on login. Flask stores it in a session cookie. Row Level Security means a user can only ever read their own history, enforced at the database rather than in application code.

**Caching.** Wikipedia article text is cached in Upstash Redis for 24 hours to avoid re-fetching the same article. Chunk data lives permanently in Supabase.

**CI.** Every push to `main` runs the test suite via GitHub Actions.

---

## Tech stack

| Layer | Technology |
|---|---|
| Backend | Python, Flask, Gunicorn |
| LLM | Groq (`llama-3.3-70b-versatile`) |
| Knowledge source | Wikipedia API |
| Auth + database | Supabase (PostgreSQL, RLS, pg_cron) |
| Caching | Upstash Redis |
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

### 1. Clone

```bash
git clone https://github.com/adhithyaa-alwar/knowledge-engine.git
cd knowledge-engine
```

### 2. Set up Supabase

Create a project, then run this in the SQL Editor:

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
  created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
  last_accessed_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX ON article_chunks (article_title);
```

Then enable the retention job:

```sql
CREATE EXTENSION IF NOT EXISTS pg_cron;

SELECT cron.schedule(
  'purge-stale-chunks',
  '0 3 * * *',
  $$DELETE FROM article_chunks
    WHERE last_accessed_at < NOW() - INTERVAL '30 days'$$
);
```

Then go to **Authentication → URL Configuration** and set your Site URL. Under **Authentication → Sign In / Providers**, enable **Confirm email**.

### 3. Set up Upstash Redis

Create a free Redis database at [upstash.com](https://upstash.com) and copy the REST URL and REST Token.

### 4. Configure environment variables

```bash
cp .env.example .env
```

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

Open [http://localhost:5000](http://localhost:5000).

### 6. Tests

```bash
pytest tests/
```

Runs automatically on every push via GitHub Actions.

---

## Deployment

Deployed on [Render](https://render.com) with Gunicorn as the production WSGI server. Auto-deploy is on, so every push to `main` ships.

Start command:
```
gunicorn app:app --bind 0.0.0.0:$PORT
```

If you fork and deploy your own copy, add every environment variable to your host and update Supabase's Site URL and Redirect URLs to match your domain.

---

## Project structure

```
knowledge-engine/
├── app.py                     # Flask web server and routes
├── conftest.py                # Pytest path configuration
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── .env.example
├── .github/workflows/ci.yml   # GitHub Actions CI
├── src/
│   ├── ingestion.py           # Fetch, chunk, store
│   ├── retrieval.py           # Load, score, rank
│   ├── wiki_qa.py             # Build prompt, call Groq, stream
│   ├── auth.py                # Supabase authentication
│   ├── db.py                  # Search history
│   └── cli.py                 # Optional CLI
├── templates/
└── tests/
```

---

## Services and cost

| Service | Cost | Purpose |
|---|---|---|
| [Wikipedia API](https://www.mediawiki.org/wiki/API:Main_page) | Free, no key | Article content |
| [Groq](https://console.groq.com) | Free tier, 1,000 req/day | LLM inference |
| [Supabase](https://supabase.com) | Free tier | Auth, history, chunks, retention job |
| [Upstash Redis](https://upstash.com) | Free tier, 10,000 cmd/day | Article caching |
| [Render](https://render.com) | Free tier | Hosting |

Total running cost: $0.

---

## Known limitations

- **Keyword retrieval** misses semantically related content phrased differently. See the retrieval section above.
- **No reranking.** Top 3 chunks by raw score, with no second pass.
- **Retrieval quality is unmeasured.** There's no eval set, so "better retrieval" is currently a judgment call rather than a number. That's the next thing worth building.

---

## License

MIT
