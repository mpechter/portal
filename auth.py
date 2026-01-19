import random
import sys
from datetime import datetime, timedelta, timezone

import resend

from airtable_client import get_client_for_org
from config import Config

# In-memory rate limiting (in production, use Redis or database)
_failed_attempts = {}  # {email: {"count": int, "lockout_until": datetime}}


def generate_login_code() -> str:
    """Generate a 6-digit login code."""
    return str(random.randint(100000, 999999))


def send_login_code(org, user_email: str, user_id: str) -> str | None:
    """
    Generate and send a login code to the user's email.

    Args:
        org: Organization model instance
        user_email: The user's email address
        user_id: The user's Airtable record ID

    Returns:
        The generated code (for demo mode display), or None on failure
    """
    # Generate code and expiry (10 minutes)
    code = generate_login_code()
    expires = datetime.now(timezone.utc) + timedelta(minutes=10)

    # Save code to Airtable
    client = get_client_for_org(org)
    client.save_login_code(user_id, code, expires)

    # Send email via Resend if configured
    if Config.RESEND_API_KEY and not Config.DEMO_MODE:
        try:
            resend.api_key = Config.RESEND_API_KEY
            resend.Emails.send({
                "from": Config.EMAIL_FROM,
                "to": user_email,
                "subject": f"Your {org.portal_title} Login Code",
                "html": f"""
                    <h2>Your Login Code</h2>
                    <p>Use this code to log in to {org.portal_title}:</p>
                    <h1 style="font-size: 32px; letter-spacing: 4px; font-family: monospace;">{code}</h1>
                    <p>This code expires in 10 minutes.</p>
                    <p style="color: #666; font-size: 12px;">If you didn't request this code, you can safely ignore this email.</p>
                """,
            })
        except Exception as e:
            print(f"Error sending email: {e}", file=sys.stderr)
            # Still return code so demo mode fallback works
    else:
        # Print code to console for development/demo
        print("\n" + "=" * 60, file=sys.stderr)
        print(f"Login code for {user_email}:", file=sys.stderr)
        print(f"  {code}", file=sys.stderr)
        print("=" * 60 + "\n", file=sys.stderr)

    return code


def is_locked_out(email: str) -> bool:
    """Check if an email is locked out due to too many failed attempts."""
    email = email.lower()
    if email not in _failed_attempts:
        return False

    info = _failed_attempts[email]
    if info.get("lockout_until"):
        if datetime.now(timezone.utc) < info["lockout_until"]:
            return True
        else:
            # Lockout expired, reset
            del _failed_attempts[email]
            return False
    return False


def get_lockout_remaining(email: str) -> int:
    """Get remaining lockout time in seconds."""
    email = email.lower()
    if email not in _failed_attempts:
        return 0

    info = _failed_attempts[email]
    if info.get("lockout_until"):
        remaining = (info["lockout_until"] - datetime.now(timezone.utc)).total_seconds()
        return max(0, int(remaining))
    return 0


def record_failed_attempt(email: str):
    """Record a failed login attempt and potentially lock out the email."""
    email = email.lower()
    if email not in _failed_attempts:
        _failed_attempts[email] = {"count": 0}

    _failed_attempts[email]["count"] += 1

    # Lock out after 5 failed attempts for 15 minutes
    if _failed_attempts[email]["count"] >= 5:
        _failed_attempts[email]["lockout_until"] = datetime.now(timezone.utc) + timedelta(minutes=15)


def clear_failed_attempts(email: str):
    """Clear failed attempts after successful login."""
    email = email.lower()
    if email in _failed_attempts:
        del _failed_attempts[email]


def verify_login_code(org, email: str, code: str) -> dict | None:
    """
    Verify a login code and return the user if valid.

    Args:
        org: Organization model instance
        email: The user's email address
        code: The login code to verify

    Returns:
        User dict if valid, None otherwise
    """
    # Check lockout first
    if is_locked_out(email):
        return None

    client = get_client_for_org(org)

    # Find user by email first
    user = client.get_user_by_email(email)
    if not user:
        record_failed_attempt(email)
        return None

    # Check if the code matches and isn't expired
    fields = user.get("fields", {})
    stored_code = fields.get("Login Code", "")
    expires_str = fields.get("Code Expires")

    if stored_code != code:
        record_failed_attempt(email)
        return None

    # Check expiry
    if expires_str:
        expires = datetime.fromisoformat(expires_str.replace("Z", "+00:00"))
        if datetime.now(timezone.utc) > expires:
            record_failed_attempt(email)
            return None

    # Success - clear code and failed attempts
    client.clear_login_code(user["id"])
    clear_failed_attempts(email)

    return user
