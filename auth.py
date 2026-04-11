import secrets
import sys
from datetime import datetime, timedelta, timezone

import resend
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired

from airtable_client import get_client_for_org
from config import Config
from models import db, LoginAttempt, LoginCode

# In-memory storage for demo mode
_demo_codes = {}  # {(org_id, email): {"code": str, "user_id": str, "expires": datetime, "token": str}}
_demo_attempts = {}  # {(org_id, email): {"count": int, "lockout_until": datetime}}

# Configure Resend API key once at module load
if Config.RESEND_API_KEY:
    resend.api_key = Config.RESEND_API_KEY

# Token serializer cache keyed by salt
_serializers = {}

def get_serializer(salt: str = "login-token") -> URLSafeTimedSerializer:
    """Get or create a token serializer for the given salt."""
    if salt not in _serializers:
        _serializers[salt] = URLSafeTimedSerializer(Config.SECRET_KEY, salt=salt)
    return _serializers[salt]


def generate_magic_token(org_id: int, email: str, user_id: str) -> str:
    """Generate a signed token for magic link login."""
    serializer = get_serializer()
    return serializer.dumps({"org_id": org_id, "email": email.lower(), "user_id": user_id})


def verify_magic_token(token: str, max_age: int = 600) -> dict | None:
    """
    Verify a magic link token.

    Args:
        token: The signed token
        max_age: Maximum age in seconds (default 10 minutes)

    Returns:
        Dict with org_id, email, user_id if valid, None otherwise
    """
    serializer = get_serializer()
    try:
        data = serializer.loads(token, max_age=max_age)
        return data
    except (BadSignature, SignatureExpired):
        return None


def generate_login_code() -> str:
    """Generate a cryptographically random 6-digit login code."""
    return str(secrets.randbelow(900000) + 100000)


def send_login_code(org, user_email: str, user_id: str, base_url: str = None) -> dict | None:
    """
    Generate and send a login code to the user's email.

    Args:
        org: Organization model instance
        user_email: The user's email address
        user_id: The user's Airtable record ID
        base_url: Base URL for magic links (e.g., "https://example.com")

    Returns:
        Dict with "code" and "token" keys, or None on failure
    """
    # Generate code and expiry (10 minutes)
    code = generate_login_code()
    token = generate_magic_token(org.id, user_email, user_id)
    expires = datetime.now(timezone.utc) + timedelta(minutes=10)

    # Save code (hashed in Postgres, plaintext in demo mode memory)
    if Config.DEMO_MODE:
        _demo_codes[(org.id, user_email.lower())] = {
            "code": code,
            "user_id": user_id,
            "expires": expires,
            "token": token,
        }
    else:
        LoginCode.create_code(
            org_id=org.id,
            user_email=user_email,
            airtable_user_id=user_id,
            code=code,
            expires_at=expires,
        )

    # Build magic link URL
    magic_link = f"{base_url}/auth?token={token}" if base_url else None

    # Send email via Resend if configured
    if Config.RESEND_API_KEY and not Config.DEMO_MODE:
        try:
            # Build email HTML with both code and magic link
            html_content = f"""
                <h2>Log in to {org.portal_title}</h2>
                <p>Click the button below to log in:</p>
                <p style="margin: 25px 0;">
                    <a href="{magic_link}"
                       style="background: #4a90d9; color: white; padding: 12px 24px;
                              text-decoration: none; border-radius: 6px; font-weight: 500;">
                        Log In to {org.portal_title}
                    </a>
                </p>
                <p style="color: #666; font-size: 14px;">Or enter this code manually:</p>
                <p style="font-size: 28px; letter-spacing: 4px; font-family: monospace;
                          background: #f5f5f5; padding: 15px; border-radius: 6px;
                          display: inline-block;">{code}</p>
                <p style="color: #666; font-size: 12px; margin-top: 20px;">
                    This link and code expire in 10 minutes.<br>
                    If you didn't request this, you can safely ignore this email.
                </p>
            """

            resend.Emails.send({
                "from": Config.EMAIL_FROM,
                "to": user_email,
                "subject": f"Log in to {org.portal_title}",
                "html": html_content,
            })
        except Exception as e:
            print(f"Error sending email: {e}", file=sys.stderr)
            # Still return code so demo mode fallback works
    else:
        # Print code and link to console for development/demo
        print("\n" + "=" * 60, file=sys.stderr)
        print(f"Login for {user_email}:", file=sys.stderr)
        print(f"  Code: {code}", file=sys.stderr)
        if magic_link:
            print(f"  Link: {magic_link}", file=sys.stderr)
        print("=" * 60 + "\n", file=sys.stderr)

    return {"code": code, "token": token}


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


def generate_admin_reset_token(org_id: int) -> str:
    """Generate a signed password-reset token for an admin."""
    return get_serializer("admin-reset").dumps({"org_id": org_id})


def verify_admin_reset_token(token: str, max_age: int = 900) -> int | None:
    """
    Verify an admin password-reset token.

    Returns:
        org_id if valid, None otherwise
    """
    try:
        data = get_serializer("admin-reset").loads(token, max_age=max_age)
        return data.get("org_id")
    except (BadSignature, SignatureExpired):
        return None


def send_admin_reset_email(org, base_url: str) -> bool:
    """
    Send a password-reset link to the org's admin email.

    Returns True if sent (or printed to console), False on error.
    """
    token = generate_admin_reset_token(org.id)
    reset_link = f"{base_url}/admin/reset-password/{token}"

    if Config.RESEND_API_KEY:
        try:
            html_content = f"""
                <h2>Reset your admin password</h2>
                <p>Click the button below to reset the admin password for
                   <strong>{org.name}</strong> ({org.org_code}):</p>
                <p style="margin: 25px 0;">
                    <a href="{reset_link}"
                       style="background: #007bff; color: white; padding: 12px 24px;
                              text-decoration: none; border-radius: 6px; font-weight: 500;">
                        Reset Admin Password
                    </a>
                </p>
                <p style="color: #666; font-size: 14px;">This link expires in 15 minutes.</p>
                <p style="color: #666; font-size: 12px;">
                    If you didn't request this, you can safely ignore this email.
                </p>
            """
            resend.Emails.send({
                "from": Config.EMAIL_FROM,
                "to": org.admin_email,
                "subject": f"Reset admin password for {org.org_code}",
                "html": html_content,
            })
            return True
        except Exception as e:
            print(f"Error sending reset email: {e}", file=sys.stderr)
            return False
    else:
        print("\n" + "=" * 60, file=sys.stderr)
        print(f"Admin password reset for {org.org_code}:", file=sys.stderr)
        print(f"  Link: {reset_link}", file=sys.stderr)
        print("=" * 60 + "\n", file=sys.stderr)
        return True


def generate_admin_email_token(org_id: int, new_email: str) -> str:
    """Generate a signed token to verify an admin email change."""
    return get_serializer("admin-email-change").dumps({"org_id": org_id, "new_email": new_email})


def verify_admin_email_token(token: str, max_age: int = 86400) -> tuple[int, str] | None:
    """
    Verify an admin email-change token (24-hour expiry).

    Returns:
        (org_id, new_email) if valid, None otherwise
    """
    try:
        data = get_serializer("admin-email-change").loads(token, max_age=max_age)
        return data.get("org_id"), data.get("new_email")
    except (BadSignature, SignatureExpired):
        return None


def send_admin_email_verification(org, new_email: str, base_url: str) -> bool:
    """
    Send a verification link to the new admin email address.

    Returns True if sent (or printed to console), False on error.
    """
    token = generate_admin_email_token(org.id, new_email)
    verify_link = f"{base_url}/admin/verify-email/{token}"

    if Config.RESEND_API_KEY:
        try:
            html_content = f"""
                <h2>Confirm your new admin email</h2>
                <p>You requested to change the admin email for
                   <strong>{org.name}</strong> ({org.org_code}) to this address.</p>
                <p style="margin: 25px 0;">
                    <a href="{verify_link}"
                       style="background: #007bff; color: white; padding: 12px 24px;
                              text-decoration: none; border-radius: 6px; font-weight: 500;">
                        Confirm New Email
                    </a>
                </p>
                <p style="color: #666; font-size: 14px;">This link expires in 24 hours.</p>
                <p style="color: #666; font-size: 12px;">
                    If you didn't request this change, you can safely ignore this email.
                </p>
            """
            resend.Emails.send({
                "from": Config.EMAIL_FROM,
                "to": new_email,
                "subject": f"Confirm admin email change for {org.org_code}",
                "html": html_content,
            })
            return True
        except Exception as e:
            print(f"Error sending email verification: {e}", file=sys.stderr)
            return False
    else:
        print("\n" + "=" * 60, file=sys.stderr)
        print(f"Admin email verification for {org.org_code}:", file=sys.stderr)
        print(f"  New email: {new_email}", file=sys.stderr)
        print(f"  Link: {verify_link}", file=sys.stderr)
        print("=" * 60 + "\n", file=sys.stderr)
        return True


def generate_signup_token(email: str, password_hash: str) -> str:
    """Generate a signed token for email verification during signup."""
    return get_serializer("signup-verify").dumps({"email": email, "password_hash": password_hash})


def verify_signup_token(token: str, max_age: int = 86400) -> dict | None:
    """Verify a signup email verification token (24-hour expiry)."""
    try:
        return get_serializer("signup-verify").loads(token, max_age=max_age)
    except (BadSignature, SignatureExpired):
        return None


def send_signup_verification_email(email: str, token: str, base_url: str) -> bool:
    """Send a verification link to confirm signup email."""
    verify_link = f"{base_url}/signup/verify/{token}"

    if Config.RESEND_API_KEY:
        try:
            html_content = f"""
                <h2>Verify your email for Airbud</h2>
                <p>Click the button below to verify your email and continue setting up your portal:</p>
                <p style="margin: 25px 0;">
                    <a href="{verify_link}"
                       style="background: #4a90d9; color: white; padding: 12px 24px;
                              text-decoration: none; border-radius: 6px; font-weight: 500;">
                        Verify Email &amp; Continue
                    </a>
                </p>
                <p style="color: #666; font-size: 14px;">This link expires in 24 hours.</p>
                <p style="color: #666; font-size: 12px;">
                    If you didn't sign up for Airbud, you can safely ignore this email.
                </p>
            """
            resend.Emails.send({
                "from": Config.EMAIL_FROM,
                "to": email,
                "subject": "Verify your email for Airbud",
                "html": html_content,
            })
            return True
        except Exception as e:
            print(f"Error sending signup verification: {e}", file=sys.stderr)
            return False
    else:
        print("\n" + "=" * 60, file=sys.stderr)
        print(f"Signup verification for {email}:", file=sys.stderr)
        print(f"  Link: {verify_link}", file=sys.stderr)
        print("=" * 60 + "\n", file=sys.stderr)
        return True


def verify_magic_link(token: str):
    """
    Verify a magic link token and return the user and org if valid.

    Args:
        token: The signed token from the magic link

    Returns:
        Tuple of (user_dict, org) if valid, (None, None) otherwise
    """
    from models import Organization

    # Verify the token signature and expiry
    data = verify_magic_token(token)
    if not data:
        return None, None

    org_id = data.get("org_id")
    email = data.get("email")
    user_id = data.get("user_id")

    if not all([org_id, email, user_id]):
        return None, None

    # Get the organization
    org = Organization.query.get(org_id)
    if not org:
        return None, None

    # Check lockout
    if is_locked_out(org_id, email):
        return None, None

    # In demo mode, verify the token matches what we stored
    if Config.DEMO_MODE:
        key = (org_id, email.lower())
        stored = _demo_codes.get(key)
        if not stored or stored.get("token") != token:
            record_failed_attempt(org_id, email)
            return None, None
        # Clear the stored code
        _demo_codes.pop(key, None)
    else:
        # Clear any stored login code for this user
        LoginCode.clear_code(org_id, email)

    # Get user from Airtable
    client = get_client_for_org(org)
    user = client.get_user_by_id(user_id)
    if not user:
        record_failed_attempt(org_id, email)
        return None, None

    # Success
    clear_failed_attempts(org_id, email)
    return user, org


def send_contact_email(name: str, email: str, message: str) -> bool:
    """Send a contact form submission to info@airbud.app."""
    import html
    safe_name = html.escape(name)
    safe_email = html.escape(email)
    safe_message = html.escape(message).replace("\n", "<br>")

    if Config.RESEND_API_KEY:
        try:
            resend.Emails.send({
                "from": Config.EMAIL_FROM,
                "to": "info@airbud.app",
                "reply_to": email,
                "subject": f"Contact: {safe_name}",
                "html": f"""
                    <p><strong>From:</strong> {safe_name} &lt;{safe_email}&gt;</p>
                    <p><strong>Message:</strong></p>
                    <p>{safe_message}</p>
                """,
            })
            return True
        except Exception as e:
            print(f"Error sending contact email: {e}", file=sys.stderr)
            return False
    else:
        print(f"\nContact from {name} <{email}>:\n{message}\n", file=sys.stderr)
        return True


def send_signup_notification(org_name: str, admin_email: str, plan: str) -> None:
    """Fire-and-forget notification to info@airbud.app when a new account is created."""
    import html as _html
    if not Config.RESEND_API_KEY:
        return
    try:
        resend.Emails.send({
            "from": Config.EMAIL_FROM,
            "to": "info@airbud.app",
            "subject": f"New signup: {_html.escape(org_name)}",
            "html": f"""
                <p>A new Airbud account was just created.</p>
                <ul>
                    <li><strong>Org:</strong> {_html.escape(org_name)}</li>
                    <li><strong>Email:</strong> {_html.escape(admin_email)}</li>
                    <li><strong>Plan:</strong> {_html.escape(plan)}</li>
                </ul>
            """,
        })
    except Exception as e:
        print(f"Error sending signup notification: {e}", file=sys.stderr)
