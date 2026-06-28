"""
app.py

Flask web server for the Wikipedia Q&A UI.
Run with: python app.py
Then open http://localhost:5000 in your browser.
"""

from flask import Flask, render_template, request, jsonify
import sys
import os

# So Flask can find wiki_qa.py in the src folder
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from wiki_qa import search_wikipedia, answer_question

app = Flask(__name__)


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/search", methods=["POST"])
def search():
    query = request.json.get("query", "").strip()
    if not query:
        return jsonify({"error": "No query provided"}), 400
    try:
        results = search_wikipedia(query)
        return jsonify({"results": results})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/ask", methods=["POST"])
def ask():
    page = request.json.get("page", "").strip()
    question = request.json.get("question", "").strip()
    if not page or not question:
        return jsonify({"error": "Missing page or question"}), 400
    try:
        answer = answer_question(page, question)
        return jsonify({"answer": answer})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    app.run(debug=True)
