import random
import sys
from datetime import datetime, timedelta, timezone

import resend

from airtable_client import get_client_for_org
from config import Config
from models import db, LoginAttempt, LoginCode

# In-memory storage for demo mode
_demo_codes = {}  # {(org_id, email): {"code": str, "user_id": str, "expires": datetime}}
_demo_attempts = {}  # {(org_id, email): {"count": int, "lockout_until": datetime}}


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

    # Save code (hashed in Postgres, plaintext in demo mode memory)
    if Config.DEMO_MODE:
        _demo_codes[(org.id, user_email.lower())] = {
            "code": code,
            "user_id": user_id,
            "expires": expires,
        }
    else:
        LoginCode.create_code(
            org_id=org.id,
            user_email=user_email,
            airtable_user_id=user_id,
            code=code,
            expires_at=expires,
        )

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


def is_locked_out(org_id: int, email: str) -> bool:
    """Check if an email is locked out due to too many failed attempts."""
    email = email.lower()

    if Config.DEMO_MODE:
        key = (org_id, email)
        if key not in _demo_attempts:
            return False
        info = _demo_attempts[key]
        if info.get("lockout_until"):
            if datetime.now(timezone.utc) < info["lockout_until"]:
                return True
            del _demo_attempts[key]
        return False

    attempt = LoginAttempt.query.filter_by(email=email, org_id=org_id).first()

    if not attempt or not attempt.lockout_until:
        return False

    if datetime.now(timezone.utc) < attempt.lockout_until:
        return True

    # Lockout expired, reset
    db.session.delete(attempt)
    db.session.commit()
    return False


def get_lockout_remaining(org_id: int, email: str) -> int:
    """Get remaining lockout time in seconds."""
    email = email.lower()

    if Config.DEMO_MODE:
        key = (org_id, email)
        if key not in _demo_attempts:
            return 0
        info = _demo_attempts[key]
        if info.get("lockout_until"):
            remaining = (info["lockout_until"] - datetime.now(timezone.utc)).total_seconds()
            return max(0, int(remaining))
        return 0

    attempt = LoginAttempt.query.filter_by(email=email, org_id=org_id).first()

    if not attempt or not attempt.lockout_until:
        return 0

    remaining = (attempt.lockout_until - datetime.now(timezone.utc)).total_seconds()
    return max(0, int(remaining))


def record_failed_attempt(org_id: int, email: str):
    """Record a failed login attempt and potentially lock out the email."""
    email = email.lower()

    if Config.DEMO_MODE:
        key = (org_id, email)
        if key not in _demo_attempts:
            _demo_attempts[key] = {"count": 0}
        _demo_attempts[key]["count"] += 1
        if _demo_attempts[key]["count"] >= 5:
            _demo_attempts[key]["lockout_until"] = datetime.now(timezone.utc) + timedelta(minutes=15)
        return

    attempt = LoginAttempt.get_or_create(email, org_id)
    attempt.failed_count += 1

    # Lock out after 5 failed attempts for 15 minutes
    if attempt.failed_count >= 5:
        attempt.lockout_until = datetime.now(timezone.utc) + timedelta(minutes=15)

    db.session.commit()


def clear_failed_attempts(org_id: int, email: str):
    """Clear failed attempts after successful login."""
    email = email.lower()

    if Config.DEMO_MODE:
        _demo_attempts.pop((org_id, email), None)
        return

    LoginAttempt.query.filter_by(email=email, org_id=org_id).delete()
    db.session.commit()


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
    email_lower = email.lower()

    # Check lockout first
    if is_locked_out(org.id, email):
        return None

    if Config.DEMO_MODE:
        # Demo mode: check in-memory storage
        key = (org.id, email_lower)
        stored = _demo_codes.get(key)

        if not stored:
            record_failed_attempt(org.id, email)
            return None

        # Check expiry
        if datetime.now(timezone.utc) > stored["expires"]:
            record_failed_attempt(org.id, email)
            return None

        # Check code (plaintext comparison in demo mode)
        if stored["code"] != code:
            record_failed_attempt(org.id, email)
            return None

        # Get user from demo client
        client = get_client_for_org(org)
        user = client.get_user_by_id(stored["user_id"])
        if not user:
            record_failed_attempt(org.id, email)
            return None

        # Success - clear code and failed attempts
        _demo_codes.pop(key, None)
        clear_failed_attempts(org.id, email)
        return user

    # Production mode: verify from Postgres
    login_code = LoginCode.verify_code(org.id, email, code)
    if not login_code:
        record_failed_attempt(org.id, email)
        return None

    # Code is valid - get user from Airtable to return user data
    client = get_client_for_org(org)
    user = client.get_user_by_id(login_code.airtable_user_id)
    if not user:
        record_failed_attempt(org.id, email)
        return None

    # Success - clear code and failed attempts
    LoginCode.clear_code(org.id, email)
    clear_failed_attempts(org.id, email)

    return user
