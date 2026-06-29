"""
auth.py

Handles all authentication logic using Supabase.

Concepts demonstrated:
- Token-based authentication (JWT tokens)
- Session management
- Supabase Auth API
"""

import os
from supabase import create_client, Client
from dotenv import load_dotenv

load_dotenv()

# Initialize the Supabase client using credentials from .env
supabase: Client = create_client(
    os.getenv("SUPABASE_URL"),
    os.getenv("SUPABASE_ANON_KEY")
)


def sign_up(email: str, password: str) -> dict:
    """
    Create a new user account.
    Returns the user object if successful, raises an error if not.
    """
    try:
        response = supabase.auth.sign_up({
            "email": email,
            "password": password
        })
        return {"user": response.user, "session": response.session}
    except Exception as e:
        raise Exception(f"Signup failed: {str(e)}")


def sign_in(email: str, password: str) -> dict:
    """
    Sign in an existing user.
    Returns the session (which contains the JWT access token) if successful.

    What is a JWT?
    -------------
    A JSON Web Token is a string that proves who the user is.
    After login, Supabase gives us one. We store it in Flask's session
    and send it with every database request so Supabase knows which
    user is making the request and enforces RLS policies.
    """
    try:
        response = supabase.auth.sign_in_with_password({
            "email": email,
            "password": password
        })
        return {"user": response.user, "session": response.session}
    except Exception as e:
        raise Exception(f"Login failed: {str(e)}")


def sign_out(access_token: str) -> None:
    """Sign out the current user and invalidate their token."""
    try:
        supabase.auth.sign_out()
    except Exception:
        pass


def get_user(access_token: str):
    """
    Verify a token and return the user it belongs to.
    Used to check if a user is still logged in on each request.
    """
    try:
        response = supabase.auth.get_user(access_token)
        return response.user
    except Exception:
        return None


def request_password_reset(email: str, redirect_url: str) -> None:
    """
    Send a password reset email to the user.
    Supabase emails them a link that includes a recovery token.
    """
    try:
        supabase.auth.reset_password_email(email, options={"redirect_to": redirect_url})
    except Exception as e:
        raise Exception(f"Password reset request failed: {str(e)}")


def update_password(access_token: str, new_password: str) -> None:
    """
    Update the user's password using the recovery token from the reset email.
    """
    try:
        # Set the session using the recovery token
        supabase.auth.set_session(access_token, "")
        supabase.auth.update_user({"password": new_password})
    except Exception as e:
        raise Exception(f"Password update failed: {str(e)}")