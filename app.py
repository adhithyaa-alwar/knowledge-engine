"""
app.py

Flask web server for the Knowledge Engine.

Redis is used for two real purposes:
- Search suggestion caching: Wikipedia OpenSearch results are cached
  for 1 hour so repeated searches for the same query skip the API call.
- Rate limiting: users are limited to 20 questions per minute to prevent
  abuse and protect the Groq API quota.
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from flask import Flask, render_template, request, jsonify, session, redirect, url_for, Response, stream_with_context
from dotenv import load_dotenv

from wiki_qa import search_wikipedia, answer_question, answer_question_stream
from ingestion import ensure_ingested
from retrieval import retrieve_relevant_chunks
from auth import sign_up, sign_in, sign_out, get_user, request_password_reset, update_password
from db import save_search, get_history

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "dev-secret-change-in-production")


# ---------------------------------------------------------------------------
# Redis client
# ---------------------------------------------------------------------------

def get_redis_client():
    """
    Create a Redis client if credentials are available.
    Returns None gracefully if Redis is not configured so the app
    continues working without caching or rate limiting.
    """
    url = os.getenv("UPSTASH_REDIS_REST_URL")
    token = os.getenv("UPSTASH_REDIS_REST_TOKEN")
    if not url or not token:
        return None
    try:
        from upstash_redis import Redis
        return Redis(url=url, token=token)
    except Exception as e:
        print(f"Could not connect to Redis: {e}")
        return None


# ---------------------------------------------------------------------------
# Rate limiting
# ---------------------------------------------------------------------------

RATE_LIMIT_REQUESTS = 20   # max requests per window
RATE_LIMIT_WINDOW = 60     # window size in seconds


def check_rate_limit(user_id: str) -> bool:
    """
    Check whether the user has exceeded the rate limit.

    Uses Redis to track request counts per user within a rolling window.
    Each request increments a counter keyed to the user ID. The counter
    expires automatically after the window closes, resetting the count.

    incr is atomic in Redis, meaning concurrent requests are counted
    correctly without race conditions.

    Returns True if the request is allowed, False if the limit is exceeded.
    """
    redis = get_redis_client()

    # If Redis is unavailable, allow the request rather than blocking everyone.
    if not redis:
        return True

    key = f"rate_limit:{user_id}"
    try:
        count = redis.incr(key)
        # Set the TTL only on the first request so the window starts then.
        # If we set it on every request, the window would never close.
        if count == 1:
            redis.expire(key, RATE_LIMIT_WINDOW)
        return count <= RATE_LIMIT_REQUESTS
    except Exception as e:
        print(f"Rate limit check failed: {e}")
        # If the check itself fails, allow the request.
        return True


# ---------------------------------------------------------------------------
# Search suggestion caching
# ---------------------------------------------------------------------------

SEARCH_CACHE_TTL = 3600    # cache search results for 1 hour


def get_cached_search(query: str) -> list[str] | None:
    """
    Check Redis for cached search suggestions for this query.
    Returns the cached list of titles, or None if not cached.

    Search suggestions are safe to cache because Wikipedia article
    titles rarely change. A 1 hour TTL means stale results are
    unlikely and the cache stays reasonably fresh.
    """
    redis = get_redis_client()
    if not redis:
        return None
    try:
        import json
        cached = redis.get(f"search:{query.lower()}")
        if cached:
            return json.loads(cached)
    except Exception as e:
        print(f"Search cache read failed: {e}")
    return None


def cache_search_results(query: str, results: list[str]) -> None:
    """
    Store search suggestions in Redis with a 1 hour TTL.
    """
    redis = get_redis_client()
    if not redis:
        return
    try:
        import json
        redis.set(f"search:{query.lower()}", json.dumps(results), ex=SEARCH_CACHE_TTL)
    except Exception as e:
        print(f"Search cache write failed: {e}")


# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------

def current_user():
    token = session.get("access_token")
    if not token:
        return None
    return get_user(token)


def login_required(f):
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user():
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated


# ---------------------------------------------------------------------------
# Auth routes
# ---------------------------------------------------------------------------

@app.route("/login", methods=["GET"])
def login():
    if current_user():
        return redirect(url_for("index"))
    return render_template("login.html")


@app.route("/signup", methods=["POST"])
def signup():
    data = request.json
    try:
        sign_up(data["email"], data["password"])
        return jsonify({"message": "Account created! Please check your email to confirm, then log in."})
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.route("/signin", methods=["POST"])
def signin():
    data = request.json
    try:
        result = sign_in(data["email"], data["password"])
        session["access_token"] = result["session"].access_token
        session["user_id"] = result["user"].id
        session["user_email"] = result["user"].email
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.route("/logout")
def logout():
    token = session.get("access_token")
    if token:
        sign_out(token)
    session.clear()
    return redirect(url_for("login"))


# ---------------------------------------------------------------------------
# Password reset routes
# ---------------------------------------------------------------------------

@app.route("/forgot-password", methods=["GET"])
def forgot_password():
    return render_template("reset_password.html")


@app.route("/request-reset", methods=["POST"])
def request_reset():
    data = request.json
    email = data.get("email", "").strip()
    if not email:
        return jsonify({"error": "Email is required."}), 400
    try:
        redirect_url = request.host_url + "forgot-password"
        request_password_reset(email, redirect_url)
        return jsonify({"message": "Reset link sent! Check your email."})
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.route("/update-password", methods=["POST"])
def update_pwd():
    data = request.json
    password = data.get("password", "")
    access_token = data.get("access_token", "")
    if not password or not access_token:
        return jsonify({"error": "Missing password or token."}), 400
    try:
        update_password(access_token, password)
        return jsonify({"message": "Password updated successfully."})
    except Exception as e:
        return jsonify({"error": str(e)}), 400


# ---------------------------------------------------------------------------
# Main app routes
# ---------------------------------------------------------------------------

@app.route("/")
@login_required
def index():
    return render_template("index.html", email=session.get("user_email"))


@app.route("/search", methods=["POST"])
@login_required
def search():
    query = request.json.get("query", "").strip()
    if not query:
        return jsonify({"error": "No query provided"}), 400

    # Check Redis cache first.
    # If we have cached results for this query, return them instantly
    # without calling Wikipedia's API.
    cached = get_cached_search(query)
    if cached:
        print(f"Search cache hit for '{query}'.")
        return jsonify({"results": cached})

    # Cache miss: call Wikipedia and store the results.
    try:
        results = search_wikipedia(query)
        cache_search_results(query, results)
        return jsonify({"results": results})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/ask-stream", methods=["POST"])
@login_required
def ask_stream():
    page = request.json.get("page", "").strip()
    question = request.json.get("question", "").strip()
    if not page or not question:
        return jsonify({"error": "Missing page or question"}), 400

    # Check rate limit before doing any expensive work.
    # If the user has exceeded 20 requests per minute, reject immediately.
    user_id = session.get("user_id")
    if not check_rate_limit(user_id):
        return jsonify({"error": "Too many requests. Please wait a moment before asking again."}), 429

    access_token = session["access_token"]

    def generate():
        full_answer = []
        try:
            # Step 1: Ingestion -- ingest or verify freshness
            ensure_ingested(page)

            # Step 2: Retrieval -- load and rank chunks from Supabase
            chunks = retrieve_relevant_chunks(page, question)

            # Step 3: Generation -- stream the answer from Groq
            for token in answer_question_stream(chunks, question):
                full_answer.append(token)
                yield f"data: {token}\n\n"

        except Exception as e:
            yield f"data: [ERROR] {str(e)}\n\n"
        finally:
            if full_answer:
                save_search(
                    access_token=access_token,
                    user_id=user_id,
                    page_title=page,
                    question=question,
                    answer="".join(full_answer)
                )
            yield "data: [DONE]\n\n"

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no"
        }
    )


@app.route("/history", methods=["GET"])
@login_required
def history():
    records = get_history(session["access_token"])
    return jsonify({"history": records})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(debug=False, host="0.0.0.0", port=port)