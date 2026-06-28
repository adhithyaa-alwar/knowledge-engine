#!/usr/bin/env python3
"""
cli.py

Command-line interface for the Wikipedia Q&A system.

Run it two ways:
  1. Interactive mode (no arguments):
       python cli.py

  2. One-shot mode:
       python cli.py --page "Python (programming language)" --question "Who created Python?"
"""

import argparse
import sys

from wiki_qa import answer_question, search_wikipedia

def pick_page_interactively() -> str:
    """
    Prompt the user to search for a Wikipedia page and choose from results.
    Returns the chosen page title.
    """
    while True:
        query = input("\nSearch for a Wikipedia page: ").strip()
        if not query:
            continue

        print("  Searching ...")
        results = search_wikipedia(query)

        if not results:
            print("  No results found. Try a different search term.")
            continue

        print("\n  Results:")
        for i, title in enumerate(results, 1):
            print(f"    {i}. {title}")

        choice = input("\n  Enter a number to select, or press Enter to search again: ").strip()
        if choice.isdigit() and 1 <= int(choice) <= len(results):
            return results[int(choice) - 1]


def run_interactive() -> None:
    """Interactive Q&A session."""
    print("=" * 60)
    print("  Wikipedia Q&A  (type 'quit' to exit)")
    print("=" * 60)

    page_title = pick_page_interactively()
    print(f"\n  Using page: '{page_title}'")
    print("  Ask as many questions as you like. Type 'new' to switch pages.\n")

    while True:
        question = input("Question: ").strip()

        if not question:
            continue
        if question.lower() in ("quit", "exit", "q"):
            print("Goodbye!")
            break
        if question.lower() == "new":
            page_title = pick_page_interactively()
            print(f"\n  Using page: '{page_title}'\n")
            continue

        print()
        try:
            answer = answer_question(page_title, question, verbose=True)
            print(f"Answer:\n{answer}\n")
        except Exception as exc:
            print(f"Error: {exc}\n")


def run_one_shot(page: str, question: str) -> None:
    """Single question, then exit."""
    try:
        answer = answer_question(page, question, verbose=True)
        print(answer)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Ask questions about any Wikipedia article."
    )
    parser.add_argument("--page", help="Wikipedia page title")
    parser.add_argument("--question", help="Question to answer")
    args = parser.parse_args()

    # Both flags must be supplied together, or neither.
    if bool(args.page) ^ bool(args.question):
        parser.error("--page and --question must be used together.")

    if args.page and args.question:
        run_one_shot(args.page, args.question)
    else:
        run_interactive()


if __name__ == "__main__":
    main()
