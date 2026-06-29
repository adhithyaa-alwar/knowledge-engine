"""
db.py

Handles all database operations using Supabase's PostgreSQL.

Concepts demonstrated:
- Inserting and querying data from PostgreSQL
- Using JWT tokens to scope database operations to the current user
- Row Level Security in action (each user only sees their own data)
"""

import os
from supabase import create_client, Client
from dotenv import load_dotenv

load_dotenv()


def get_client(access_token: str) -> Client:
    """
    Create a Supabase client authenticated as the current user.

    Why pass the token here?
    ------------------------
    When we use the user's own token, Supabase's Row Level Security
    kicks in automatically — the user can only read and write their
    own rows. If we used the secret key instead, RLS would be bypassed
    and users could access each other's data.
    """
    client = create_client(
        os.getenv("SUPABASE_URL"),
        os.getenv("SUPABASE_ANON_KEY")
    )
    client.postgrest.auth(access_token)
    return client


def save_search(access_token: str, user_id: str, page_title: str, question: str, answer: str) -> None:
    """
    Save a Q&A interaction to the search_history table.
    """
    try:
        client = get_client(access_token)
        client.table("search_history").insert({
            "user_id": user_id,
            "page_title": page_title,
            "question": question,
            "answer": answer
        }).execute()
    except Exception as e:
        print(f"Failed to save search: {e}")


def get_history(access_token: str, limit: int = 20) -> list:
    """
    Fetch the most recent Q&A interactions for the current user.
    Returns a list of records ordered by most recent first.
    """
    try:
        client = get_client(access_token)
        response = (
            client.table("search_history")
            .select("*")
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )
        return response.data
    except Exception as e:
        print(f"Failed to fetch history: {e}")
        return []
