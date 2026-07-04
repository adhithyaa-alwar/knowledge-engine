"""
app.py

Flask web server for the Knowledge Engine.

The pipeline is now properly separated:
  ingestion.py  -- fetches and stores article chunks
  retrieval.py  -- loads and scores chunks against a question
  wiki_qa.py    -- builds the prompt and calls Groq
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
    try:
        results = search_wikipedia(query)
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

    access_token = session["access_token"]
    user_id = session["user_id"]

    def generate():
        full_answer = []
        try:
            # Step 1: Ingestion -- fetch and store chunks if not already done
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