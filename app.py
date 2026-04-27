import hmac
import os
import time
from datetime import datetime, timezone
from functools import wraps
from types import SimpleNamespace
from flask import Flask, render_template, request, redirect, url_for, flash, session, abort, jsonify
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from flask_wtf.csrf import CSRFProtect
from config import Config
from models import db, Organization, LoginAttempt, LoginCode, PromoCode
from airtable_client import get_client_for_org, COMPUTED_FIELD_TYPES
from auth import (send_login_code, verify_login_code, verify_magic_link,
                  is_locked_out, get_lockout_remaining,
                  record_failed_attempt, clear_failed_attempts,
                  send_admin_reset_email, verify_admin_reset_token,
                  send_admin_email_verification, verify_admin_email_token,
                  generate_signup_token, verify_signup_token,
                  send_signup_verification_email,
                  send_contact_email, send_signup_notification)

app = Flask(__name__)
app.config.from_object(Config)

csrf = CSRFProtect(app)

db.init_app(app)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"

FEEDBACK_URL = "https://airtable.com/appYPwkzs25LDrae3/shrJuZD5M9EDp90iW"


@app.context_processor
def inject_globals():
    return {"feedback_url": FEEDBACK_URL}


class User(UserMixin):
    """Flask-Login user class that wraps Airtable user data."""

    def __init__(self, org_code: str, user_id: str, email: str, name: str):
        self.org_code = org_code
        self.user_id = user_id
        self.email = email
        self.name = name

    def get_id(self):
        return f"{self.org_code}:{self.user_id}"


@login_manager.user_loader
def load_user(user_id: str):
    """Load user from session cache, falling back to Airtable only when needed."""
    # Admin preview: serve the preview user directly from session
    preview = session.get("admin_preview")
    if preview:
        return User(
            org_code=preview["org_code"],
            user_id=preview["user_id"],
            email=preview.get("email", ""),
            name=preview.get("name", "Preview User"),
        )

    if ":" not in user_id:
        return None

    org_code, airtable_id = user_id.split(":", 1)
    org = Organization.get_by_code(org_code)
    if not org:
        return None

    # Use data cached in session at login time — avoids an Airtable API call on every request
    user_cache = session.get("user_cache")
    if user_cache:
        return User(
            org_code=org_code,
            user_id=airtable_id,
            email=user_cache.get("email", ""),
            name=user_cache.get("name", ""),
        )

    # Fallback: first request after login or cache miss — fetch from Airtable
    client = get_client_for_org(org)
    user_data = client.get_user_by_id(airtable_id)
    if not user_data:
        return None

    fields = user_data.get("fields", {})
    email_field = org.email_field or "Email"
    session["user_cache"] = {"email": fields.get(email_field, ""), "name": fields.get("Name", "")}
    return User(
        org_code=org_code,
        user_id=airtable_id,
        email=fields.get(email_field, ""),
        name=fields.get("Name", ""),
    )


# --- Admin Auth Decorator ---


def admin_required(f):
    """Decorator to require admin authentication."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        admin_org_code = session.get("admin_org_code")
        if not admin_org_code:
            flash("Please log in as admin.", "error")
            return redirect(url_for("admin_login"))
        return f(*args, **kwargs)
    return decorated_function


# --- Shared Helpers ---


def _build_field_updates(editable_fields: list, field_metadata: dict, form) -> dict:
    """Build an Airtable update dict from submitted form data.

    Skips computed/formula fields that Airtable won't accept writes to.
    """
    updates = {}
    for field_name in editable_fields:
        field_type = field_metadata.get(field_name, {}).get("type", "singleLineText")
        if field_type in COMPUTED_FIELD_TYPES:
            continue
        if field_type == "checkbox":
            updates[field_name] = field_name in form
        elif field_type == "multipleSelects":
            updates[field_name] = form.getlist(field_name)
        else:
            form_value = form.get(field_name)
            if form_value is not None:
                if form_value == "" and field_type in ("number", "date"):
                    updates[field_name] = None
                else:
                    updates[field_name] = form_value
    return updates


def _get_admin_org():
    """Get the current admin's organization, clearing the session if not found."""
    org = Organization.get_by_code(session.get("admin_org_code", ""))
    if not org:
        session.pop("admin_org_code", None)
    return org


def is_preview_mode() -> bool:
    """Return True if the current request is an admin portal preview."""
    return bool(session.get("admin_preview"))


def validate_password(password: str) -> str | None:
    """Returns an error message if password doesn't meet requirements, else None."""
    import re
    if len(password) < 8:
        return "Password must be at least 8 characters."
    if not re.search(r"[A-Z]", password):
        return "Password must contain at least one uppercase letter."
    if not re.search(r"[a-z]", password):
        return "Password must contain at least one lowercase letter."
    if not re.search(r"\d", password):
        return "Password must contain at least one number."
    if not re.search(r"[!@#$%^&*(),.?\":{}|<>_\-+=\[\]\\;'/`~]", password):
        return "Password must contain at least one special character."
    return None


# --- User Routes ---


@app.route("/")
def index():
    """Marketing home page."""
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))
    return render_template("index.html")


@app.route("/about")
def about():
    return render_template("about.html")


@app.route("/privacy")
def privacy():
    return render_template("privacy.html")


@app.route("/terms")
def terms():
    return render_template("terms.html")


@app.route("/faq")
def faq():
    """FAQ page."""
    return render_template("faq.html")


@app.route("/pricing")
def pricing():
    """Pricing page."""
    return render_template("pricing.html")


@app.route("/contact", methods=["GET", "POST"])
def contact():
    """Contact form page."""
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip()
        message = request.form.get("message", "").strip()

        if not name or not email or not message:
            flash("All fields are required.", "error")
            return render_template("contact.html", name=name, email=email, message=message)

        sent = send_contact_email(name, email, message)
        if sent:
            flash("Message sent! We'll get back to you soon.", "success")
            return redirect(url_for("index"))
        else:
            flash("Could not send your message. Please try again.", "error")
            return render_template("contact.html", name=name, email=email, message=message)

    return render_template("contact.html", name="", email="", message="")


# --- Demo Portal ---

_DEMO_ORG = SimpleNamespace(
    portal_title="Springfield Schools Family Portal",
    records_table="Students",
    confirmation_enabled=True,
    confirmation_field="Reviewed",
    confirmation_value="Yes",
    logo_url="https://pub-9399c658257349b181e8d9519256b183.r2.dev/logos/airbud.png",
    plan="active",
    field_aliases={"user_fields": {}, "record_fields": {}},
    field_annotations={"record_fields": {}},
    field_descriptions={"record_fields": {}},
)

_DEMO_USER = SimpleNamespace(name="Sarah Richardson", email="sarah.richardson@example.com")

_DEMO_USER_FIELDS = {
    "Name": "Sarah Richardson",
    "Email": "sarah.richardson@example.com",
    "Phone": "(555) 423-8876",
    "Address": "412 Maple Street, Springfield",
}

_DEMO_RECORDS = [
    SimpleNamespace(id="liam", fields={
        "Name": "Liam Richardson",
        "Grade": "8th Grade",
        "Homeroom": "Mr. Thompson",
        "School": "Springfield Middle School",
        "Emergency Contact": "Sarah Richardson — (555) 423-8876",
        "Medical Notes": "None",
        "Reviewed": "Yes",
    }),
    SimpleNamespace(id="aiden", fields={
        "Name": "Aiden Richardson",
        "Grade": "5th Grade",
        "Homeroom": "Ms. Patel",
        "School": "Lincoln Elementary",
        "Emergency Contact": "Sarah Richardson — (555) 423-8876",
        "Medical Notes": "Peanut allergy (EpiPen on file)",
    }),
    SimpleNamespace(id="abigail", fields={
        "Name": "Abigail Richardson",
        "Grade": "2nd Grade",
        "Homeroom": "Mrs. Chen",
        "School": "Lincoln Elementary",
        "Emergency Contact": "Sarah Richardson — (555) 423-8876",
        "Medical Notes": "None",
    }),
]

_DEMO_USER_READONLY_FIELDS = ["Name", "Email"]
_DEMO_USER_EDITABLE_FIELDS = ["Phone", "Address"]
_DEMO_USER_DESCRIPTIONS = {
    "Phone": "We'll use this number for school communications and emergency calls.",
    "Address": "Used for district enrollment verification.",
}
_DEMO_USER_TRANSLATIONS = {
    "Name": "Nombre",
    "Email": "Correo electrónico",
    "Phone": "Teléfono",
    "Address": "Dirección",
}
_DEMO_USER_FIELD_METADATA = {
    "Name": SimpleNamespace(type="singleLineText", options=[]),
    "Email": SimpleNamespace(type="email", options=[]),
    "Phone": SimpleNamespace(type="phoneNumber", options=[]),
    "Address": SimpleNamespace(type="multilineText", options=[]),
}

_DEMO_EDITABLE_FIELDS = ["Emergency Contact", "Medical Notes"]
_DEMO_READONLY_FIELDS = ["Grade", "Homeroom", "School"]
_DEMO_FIELD_DESCRIPTIONS = {
    "Emergency Contact": "List the name and phone number of someone we can reach if a parent is unavailable.",
    "Medical Notes": "Include any allergies, medications, or conditions the school should be aware of.",
}
_DEMO_FIELD_TRANSLATIONS = {
    "Grade": "Grado",
    "Homeroom": "Salón de clase",
    "School": "Escuela",
    "Emergency Contact": "Contacto de emergencia",
    "Medical Notes": "Notas médicas",
}
_DEMO_FIELD_METADATA = {
    "Emergency Contact": SimpleNamespace(type="singleLineText", options=[]),
    "Medical Notes": SimpleNamespace(type="multilineText", options=[]),
    "Grade": SimpleNamespace(type="singleLineText", options=[]),
    "Homeroom": SimpleNamespace(type="singleLineText", options=[]),
    "School": SimpleNamespace(type="singleLineText", options=[]),
}


@app.route("/demo")
def demo():
    return render_template(
        "demo_dashboard.html",
        org=_DEMO_ORG,
        user=_DEMO_USER,
        user_fields=_DEMO_USER_FIELDS,
        user_editable_fields=_DEMO_USER_EDITABLE_FIELDS,
        user_readonly_fields=_DEMO_USER_READONLY_FIELDS,
        has_profile_fields=True,
        user_aliases={},
        records=_DEMO_RECORDS,
    )


@app.route("/demo/record/<record_id>", methods=["GET", "POST"])
def demo_record(record_id: str):
    record = next((r for r in _DEMO_RECORDS if r.id == record_id), None)
    if not record:
        abort(404)

    if request.method == "POST":
        flash("Demo mode — changes are not saved. Sign up to create your own portal!", "info")
        return redirect(url_for("demo_record", record_id=record_id))

    last_confirmed = record.fields.get(_DEMO_ORG.confirmation_field)
    return render_template(
        "demo_record.html",
        org=_DEMO_ORG,
        record=record,
        editable_fields=_DEMO_EDITABLE_FIELDS,
        readonly_fields=_DEMO_READONLY_FIELDS,
        field_metadata=_DEMO_FIELD_METADATA,
        field_translations=_DEMO_FIELD_TRANSLATIONS,
        field_aliases={},
        field_descriptions=_DEMO_FIELD_DESCRIPTIONS,
        last_confirmed=last_confirmed,
    )


@app.route("/demo/profile", methods=["GET", "POST"])
def demo_profile():
    if request.method == "POST":
        flash("Demo mode — changes are not saved. Sign up to create your own portal!", "info")
        return redirect(url_for("demo_profile"))

    user_data = SimpleNamespace(fields=_DEMO_USER_FIELDS)
    return render_template(
        "demo_profile.html",
        org=_DEMO_ORG,
        user_data=user_data,
        editable_fields=_DEMO_USER_EDITABLE_FIELDS,
        readonly_fields=_DEMO_USER_READONLY_FIELDS,
        field_metadata=_DEMO_USER_FIELD_METADATA,
        field_translations=_DEMO_USER_TRANSLATIONS,
        field_aliases={},
        field_descriptions=_DEMO_USER_DESCRIPTIONS,
    )


@app.route("/api/check-org-code")
def check_org_code():
    """Check whether an org code is available (used by signup form)."""
    code = request.args.get("code", "").strip().upper()
    if not code or len(code) < 3:
        return jsonify({"available": False, "message": "Code must be at least 3 characters"})
    exists = Organization.query.filter_by(org_code=code).first() is not None
    return jsonify({"available": not exists})


@app.route("/org/<org_code>")
def org_landing(org_code):
    """Branded landing page for a specific org — auto-404 for inactive/deleted orgs."""
    org = Organization.get_by_code(org_code)
    if not org:
        abort(404)
    return render_template("org_login.html", org=org)


@app.route("/login", methods=["GET", "POST"])
def login():
    """Login page - enter org code and email."""
    if request.method == "POST":
        org_code = request.form.get("org_code", "").strip().upper()
        email = request.form.get("email", "").strip().lower()

        # Find the organization
        org = Organization.get_by_code(org_code)
        if not org:
            flash("Organization not found. Please check your org code.", "error")
            return render_template("login.html", org_code=org_code, email=email)

        # Check if tables are configured
        if not org.tables_configured:
            flash("This organization is not yet configured. Please contact your administrator.", "error")
            return render_template("login.html", org_code=org_code, email=email)

        # Check if trial has expired
        if org.trial_expired:
            flash("This portal is not currently active. Please contact your administrator.", "error")
            return render_template("login.html", org_code=org_code, email=email)

        # Check if locked out
        if is_locked_out(org.id, email):
            remaining = get_lockout_remaining(org.id, email)
            flash(f"Too many failed attempts. Try again in {remaining // 60} minutes.", "error")
            return render_template("login.html", org_code=org_code, email=email)

        # Find the user in Airtable
        try:
            client = get_client_for_org(org)
            user = client.get_user_by_email(email)
        except Exception as e:
            app.logger.error(f"Error looking up user in Airtable: {e}")
            flash("Unable to reach the directory service. Please try again.", "error")
            return render_template("login.html", org_code=org_code, email=email)
        if not user:
            flash("Email not found. Please contact your administrator.", "error")
            return render_template("login.html", org_code=org_code, email=email)

        # Send login code (with magic link)
        base_url = Config.APP_URL.rstrip("/")
        result = None
        for attempt in range(3):
            try:
                result = send_login_code(org, email, user["id"], base_url=base_url)
                break
            except Exception as e:
                app.logger.error(f"Error sending login code (attempt {attempt + 1}): {e}")
                if attempt < 2:
                    time.sleep(0.5)
        if result:
            # Store org_code and email in session for code verification
            session["pending_org_code"] = org_code
            session["pending_email"] = email
            # In demo mode, store code and token in session so we can display them
            if Config.DEMO_MODE:
                session["demo_code"] = result["code"]
                session["demo_token"] = result["token"]
            return redirect(url_for("verify_code"))
        else:
            flash("Error sending login code. Please try again.", "error")
            return render_template("login.html", org_code=org_code, email=email)

    # GET request - show login form
    org_code = request.args.get("org", "")
    return render_template("login.html", org_code=org_code, email="")


@app.route("/verify", methods=["GET", "POST"])
def verify_code():
    """Verify the login code."""
    # Check we have pending login info
    org_code = session.get("pending_org_code")
    email = session.get("pending_email")

    if not org_code or not email:
        flash("Please start the login process again.", "error")
        return redirect(url_for("login"))

    org = Organization.get_by_code(org_code)
    if not org:
        flash("Invalid session. Please try again.", "error")
        return redirect(url_for("login"))

    # Get demo code/token if in demo mode
    demo_code = session.get("demo_code") if Config.DEMO_MODE else None
    demo_token = session.get("demo_token") if Config.DEMO_MODE else None

    if request.method == "POST":
        code = request.form.get("code", "").strip()

        # Check lockout
        if is_locked_out(org.id, email):
            remaining = get_lockout_remaining(org.id, email)
            flash(f"Too many failed attempts. Try again in {remaining // 60} minutes.", "error")
            return render_template("verify_code.html", email=email, org=org, demo_code=demo_code, demo_token=demo_token)

        # Verify the code
        user_data = verify_login_code(org, email, code)
        if not user_data:
            flash("Invalid or expired code. Please try again.", "error")
            return render_template("verify_code.html", email=email, org=org, demo_code=demo_code, demo_token=demo_token)

        # Success - log them in
        fields = user_data.get("fields", {})
        user = User(
            org_code=org.org_code,
            user_id=user_data["id"],
            email=fields.get("Email", ""),
            name=fields.get("Name", ""),
        )
        login_user(user)

        # Clear pending session data and store org_code + user cache
        session.pop("pending_org_code", None)
        session.pop("pending_email", None)
        session.pop("demo_code", None)
        session.pop("demo_token", None)
        session["org_code"] = org.org_code
        session["user_cache"] = {"email": user.email, "name": user.name}

        return redirect(url_for("dashboard"))

    return render_template("verify_code.html", email=email, org=org, demo_code=demo_code, demo_token=demo_token)


@app.route("/auth")
def magic_link_auth():
    """Handle magic link authentication."""
    token = request.args.get("token")
    if not token:
        flash("Invalid login link.", "error")
        return redirect(url_for("login"))

    # Verify the magic link token
    user_data, org = verify_magic_link(token)
    if not user_data or not org:
        flash("This login link is invalid or has expired. Please request a new one.", "error")
        return redirect(url_for("login"))

    # Success - log them in
    fields = user_data.get("fields", {})
    user = User(
        org_code=org.org_code,
        user_id=user_data["id"],
        email=fields.get("Email", ""),
        name=fields.get("Name", ""),
    )
    login_user(user)

    # Clear any pending session data and store org_code + user cache
    session.pop("pending_org_code", None)
    session.pop("pending_email", None)
    session.pop("demo_code", None)
    session.pop("demo_token", None)
    session["org_code"] = org.org_code
    session["user_cache"] = {"email": user.email, "name": user.name}

    return redirect(url_for("dashboard"))


@app.route("/logout")
@login_required
def logout():
    """Log out the current user."""
    if is_preview_mode():
        session.pop("admin_preview", None)
        logout_user()
        return redirect(url_for("admin_dashboard"))
    logout_user()
    session.clear()
    flash("You have been logged out.", "info")
    return redirect(url_for("index"))


@app.route("/dashboard")
@login_required
def dashboard():
    """Show list of records the user can edit."""
    org = Organization.get_by_code(current_user.org_code)
    if not org:
        logout_user()
        return redirect(url_for("login"))

    if org.trial_expired:
        logout_user()
        flash("This portal is not currently active. Please contact your administrator.", "error")
        return redirect(url_for("login"))

    client = get_client_for_org(org)

    # Get user's own profile data
    user_data = client.get_user_by_id(current_user.user_id)
    user_fields = user_data.get("fields", {}) if user_data else {}
    user_fields = client.resolve_linked_fields(org.users_table, user_fields)

    # Get field permissions for user profile
    user_editable_fields = org.get_user_editable_fields()
    user_readonly_fields = org.get_user_readonly_fields()
    has_profile_fields = bool(user_editable_fields or user_readonly_fields)

    # Get linked records (only if configured)
    records = []
    if org.has_linked_records:
        records = client.get_records_for_user(current_user.user_id)

    user_aliases = org.field_aliases.get("user_fields", {})

    return render_template(
        "dashboard.html",
        records=records,
        org=org,
        user=current_user,
        user_fields=user_fields,
        user_editable_fields=user_editable_fields,
        user_readonly_fields=user_readonly_fields,
        has_profile_fields=has_profile_fields,
        user_aliases=user_aliases,
        preview_mode=is_preview_mode(),
    )


@app.route("/record/<record_id>", methods=["GET", "POST"])
@login_required
def edit_record(record_id: str):
    """Edit a specific record."""
    org = Organization.get_by_code(current_user.org_code)
    if not org:
        logout_user()
        return redirect(url_for("login"))

    if org.trial_expired:
        logout_user()
        flash("This portal is not currently active. Please contact your administrator.", "error")
        return redirect(url_for("login"))


    client = get_client_for_org(org)

    # Verify user has access to this record
    if not client.can_user_access_record(current_user.user_id, record_id):
        abort(403)

    record = client.get_record_by_id(record_id)
    if not record:
        abort(404)
    record["fields"] = client.resolve_linked_fields(org.records_table, record.get("fields", {}))

    # Get field permissions from org config (for linked records)
    editable_fields = org.get_record_editable_fields()
    readonly_fields = org.get_record_readonly_fields()

    # Exclude the confirmation field from display (it's handled separately)
    if org.confirmation_field:
        editable_fields = [f for f in editable_fields if f != org.confirmation_field]
        readonly_fields = [f for f in readonly_fields if f != org.confirmation_field]

    # Get field metadata for type-aware rendering
    all_fields = editable_fields + readonly_fields
    field_metadata = client.get_field_metadata(org.records_table, all_fields)

    if request.method == "POST":
        if is_preview_mode():
            flash("Preview mode — changes are not saved.", "info")
            return redirect(url_for("edit_record", record_id=record_id))

        # Build update dict with only editable fields
        updates = _build_field_updates(editable_fields, field_metadata, request.form)

        # Handle data confirmation
        data_confirmed = False
        if org.confirmation_enabled and org.confirmation_field and org.confirmation_value:
            if "data_confirmed" in request.form:
                updates[org.confirmation_field] = org.confirmation_value
                data_confirmed = True

        if updates:
            client.update_record(record_id, updates)
            flash("Changes saved successfully.", "success")

        # Redirect to dashboard if data was confirmed, otherwise stay on edit page
        if data_confirmed:
            return redirect(url_for("dashboard"))
        return redirect(url_for("edit_record", record_id=record_id))

    # Get current confirmation status if confirmation is enabled
    last_confirmed = None
    if org.confirmation_enabled and org.confirmation_field and org.confirmation_value:
        last_confirmed = record.get("fields", {}).get(org.confirmation_field)

    # Get translations, aliases, and descriptions for record fields
    record_translations = org.field_annotations.get("record_fields", {})
    record_aliases = org.field_aliases.get("record_fields", {})
    record_descriptions = org.field_descriptions.get("record_fields", {})

    return render_template(
        "edit_record.html",
        record=record,
        editable_fields=editable_fields,
        readonly_fields=readonly_fields,
        field_metadata=field_metadata,
        org=org,
        last_confirmed=last_confirmed,
        field_translations=record_translations,
        field_aliases=record_aliases,
        field_descriptions=record_descriptions,
        preview_mode=is_preview_mode(),
    )


@app.route("/profile", methods=["GET", "POST"])
@login_required
def edit_profile():
    """Edit the user's own profile."""
    org = Organization.get_by_code(current_user.org_code)
    if not org:
        logout_user()
        return redirect(url_for("login"))

    client = get_client_for_org(org)
    user_data = client.get_user_by_id(current_user.user_id)
    if not user_data:
        abort(404)
    user_data["fields"] = client.resolve_linked_fields(org.users_table, user_data.get("fields", {}))

    # Get field permissions for user profile
    editable_fields = org.get_user_editable_fields()
    readonly_fields = org.get_user_readonly_fields()

    # Get field metadata for type-aware rendering
    all_fields = editable_fields + readonly_fields
    field_metadata = client.get_field_metadata(org.users_table, all_fields)

    if request.method == "POST":
        if is_preview_mode():
            flash("Preview mode — changes are not saved.", "info")
            return redirect(url_for("edit_profile"))

        # Build update dict with only editable fields
        updates = _build_field_updates(editable_fields, field_metadata, request.form)

        if updates:
            client.update_user(current_user.user_id, updates)
            flash("Profile updated successfully.", "success")

        return redirect(url_for("edit_profile"))

    # Get translations, aliases, and descriptions for user fields
    user_translations = org.field_annotations.get("user_fields", {})
    user_aliases = org.field_aliases.get("user_fields", {})
    user_descriptions = org.field_descriptions.get("user_fields", {})

    return render_template(
        "edit_profile.html",
        user_data=user_data,
        editable_fields=editable_fields,
        readonly_fields=readonly_fields,
        field_metadata=field_metadata,
        org=org,
        field_translations=user_translations,
        field_aliases=user_aliases,
        field_descriptions=user_descriptions,
        preview_mode=is_preview_mode(),
    )


# --- Admin Routes ---


@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    """Admin login page."""
    if request.method == "POST":
        org_code = request.form.get("org_code", "").strip().upper()
        password = request.form.get("password", "")

        org = Organization.get_by_code(org_code)
        if not org:
            flash("Organization not found.", "error")
            return render_template("admin/login.html", org_code=org_code)

        if not org.admin_password_hash:
            flash("Admin access not configured for this organization.", "error")
            return render_template("admin/login.html", org_code=org_code)

        # Rate-limit admin login attempts by org_id + a fixed sentinel email
        _admin_sentinel = "__admin__"
        if is_locked_out(org.id, _admin_sentinel):
            remaining = get_lockout_remaining(org.id, _admin_sentinel)
            flash(f"Too many failed attempts. Try again in {remaining // 60 + 1} minute(s).", "error")
            return render_template("admin/login.html", org_code=org_code)

        if not org.check_admin_password(password):
            record_failed_attempt(org.id, _admin_sentinel)
            flash("Invalid password.", "error")
            return render_template("admin/login.html", org_code=org_code)

        # Success
        clear_failed_attempts(org.id, _admin_sentinel)
        session["admin_org_code"] = org.org_code
        flash("Logged in as admin.", "success")
        return redirect(url_for("admin_dashboard"))

    org_code = request.args.get("org", "")
    return render_template("admin/login.html", org_code=org_code)


@app.route("/admin/logout")
def admin_logout():
    """Admin logout."""
    session.pop("admin_org_code", None)
    flash("Logged out of admin.", "info")
    return redirect(url_for("admin_login"))


@app.route("/admin")
@admin_required
def admin_dashboard():
    """Admin dashboard - redirect to appropriate page."""
    org = _get_admin_org()
    if not org:
        return redirect(url_for("admin_login"))

    # If tables not configured, redirect to table setup
    if not org.tables_configured:
        return redirect(url_for("admin_tables"))

    return redirect(url_for("admin_fields"))


@app.route("/admin/settings", methods=["GET"])
@admin_required
def admin_settings():
    """Admin settings page - basic configuration."""
    org = _get_admin_org()
    if not org:
        return redirect(url_for("admin_login"))

    return render_template("admin/settings.html", org=org)


@app.route("/admin/save-settings", methods=["POST"])
@admin_required
def admin_save_settings():
    """Save admin settings."""
    org = _get_admin_org()
    if not org:
        return redirect(url_for("admin_login"))

    # Get form values
    name = request.form.get("name", "").strip()
    portal_title = request.form.get("portal_title", "").strip()
    airtable_api_key = request.form.get("airtable_api_key", "").strip()
    airtable_base_id = request.form.get("airtable_base_id", "").strip()

    if not name:
        flash("Organization name is required.", "error")
        return redirect(url_for("admin_settings"))

    if not airtable_base_id or (not airtable_api_key and not org.airtable_api_key):
        flash("Airtable API key and Base ID are required.", "error")
        return redirect(url_for("admin_settings"))

    # Check if Airtable credentials changed - if so, clear table config
    credentials_changed = (
        (airtable_api_key and airtable_api_key != org.airtable_api_key) or
        airtable_base_id != org.airtable_base_id
    )

    org.name = name
    org.portal_title = portal_title or "Portal"
    # Only update API key if a new one was provided (don't overwrite with empty)
    if airtable_api_key:
        org.airtable_api_key = airtable_api_key
    org.airtable_base_id = airtable_base_id

    if credentials_changed:
        # Clear schema cache for both old and new base
        from airtable_client import AirtableClient
        AirtableClient.clear_schema_cache(org.airtable_base_id)  # Old base
        AirtableClient.clear_schema_cache(airtable_base_id)  # New base

        # Clear table and field config since we're connecting to a different base
        org.users_table = None
        org.records_table = None
        org.link_field = None
        org.field_config = {"user_fields": {}, "record_fields": {}}
        flash("Settings saved. Please reconfigure your tables.", "success")
        db.session.commit()
        return redirect(url_for("admin_tables"))

    # Admin email — require verification before committing a change
    admin_email = request.form.get("admin_email", "").strip().lower()
    if admin_email and admin_email != (org.admin_email or ""):
        base_url = Config.APP_URL.rstrip("/")
        sent = send_admin_email_verification(org, admin_email, base_url)
        if sent:
            org.pending_admin_email = admin_email
            db.session.commit()
            flash(
                f"A verification link has been sent to {admin_email}. "
                "Your admin email will not change until you click that link.",
                "info",
            )
        else:
            flash("Could not send verification email. Check your email configuration.", "error")
        return redirect(url_for("admin_settings"))

    new_password = request.form.get("new_password", "").strip()
    if new_password:
        new_password_confirm = request.form.get("new_password_confirm", "").strip()
        pw_error = validate_password(new_password)
        if pw_error:
            flash(pw_error, "error")
            return redirect(url_for("admin_settings"))
        if new_password != new_password_confirm:
            flash("Passwords do not match.", "error")
            return redirect(url_for("admin_settings"))
        org.set_admin_password(new_password)

    db.session.commit()
    flash("Settings saved.", "success")
    return redirect(url_for("admin_settings"))


@app.errorhandler(413)
def handle_request_too_large(e):
    flash("File is too large. Maximum size is 5 MB.", "error")
    return redirect(request.referrer or url_for("admin_settings"))


@app.route("/admin/upload-logo", methods=["POST"])
@admin_required
def admin_upload_logo():
    """Upload a logo image to Cloudflare R2 and save the URL."""
    import uuid
    import boto3
    from botocore.exceptions import BotoCoreError, ClientError

    org = _get_admin_org()
    if not org:
        return redirect(url_for("admin_login"))

    cfg = app.config
    if not all([cfg.get("R2_ACCOUNT_ID"), cfg.get("R2_ACCESS_KEY_ID"),
                cfg.get("R2_SECRET_ACCESS_KEY"), cfg.get("R2_BUCKET_NAME"),
                cfg.get("R2_PUBLIC_URL")]):
        flash("Logo upload is not configured. Set R2_* environment variables.", "error")
        return redirect(url_for("admin_settings"))

    file = request.files.get("logo_file")
    if not file or not file.filename:
        flash("No file selected.", "error")
        return redirect(url_for("admin_settings"))

    ext = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
    if ext not in {"png", "jpg", "jpeg", "gif", "webp"}:
        flash("Unsupported file type. Use PNG, JPG, GIF, or WebP.", "error")
        return redirect(url_for("admin_settings"))

    content_types = {
        "png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
        "gif": "image/gif", "webp": "image/webp",
    }

    key = f"logos/{org.org_code}/{uuid.uuid4().hex}.{ext}"
    try:
        s3 = boto3.client(
            "s3",
            endpoint_url=f"https://{cfg['R2_ACCOUNT_ID']}.r2.cloudflarestorage.com",
            aws_access_key_id=cfg["R2_ACCESS_KEY_ID"],
            aws_secret_access_key=cfg["R2_SECRET_ACCESS_KEY"],
            region_name="auto",
        )
        s3.upload_fileobj(
            file,
            cfg["R2_BUCKET_NAME"],
            key,
            ExtraArgs={"ContentType": content_types[ext]},
        )
    except (BotoCoreError, ClientError) as e:
        app.logger.exception("R2 logo upload failed: %s", e)
        flash("Upload failed. Please try again.", "error")
        return redirect(url_for("admin_settings"))

    org.logo_url = f"{cfg['R2_PUBLIC_URL'].rstrip('/')}/{key}"
    db.session.commit()
    flash("Logo uploaded successfully.", "success")
    return redirect(url_for("admin_settings"))


@app.route("/admin/tables", methods=["GET"])
@admin_required
def admin_tables():
    """Admin table configuration page."""
    org = _get_admin_org()
    if not org:
        return redirect(url_for("admin_login"))

    client = get_client_for_org(org)
    tables = client.get_base_tables()

    return render_template(
        "admin/tables.html",
        org=org,
        tables=tables,
    )


@app.route("/admin/save-tables", methods=["POST"])
@admin_required
def admin_save_tables():
    """Save table configuration."""
    org = _get_admin_org()
    if not org:
        return redirect(url_for("admin_login"))

    users_table = request.form.get("users_table", "").strip()
    records_table = request.form.get("records_table", "").strip()
    email_field = request.form.get("email_field", "").strip() or "Email"

    if not users_table:
        flash("Please select a Users table.", "error")
        return redirect(url_for("admin_tables"))

    # Validate that Users table has required fields
    client = get_client_for_org(org)
    org.users_table = users_table  # Temporarily set for client to use
    users_table_info = client.get_table_by_name(users_table)

    if users_table_info:
        field_names = {f["name"] for f in users_table_info.get("fields", [])}
        if not field_names:
            flash("Warning: could not read fields from the selected Users table. "
                  "Check your Airtable token permissions.", "error")

    org.records_table = records_table if records_table else None
    org.link_field = None  # Auto-detected from schema
    org.email_field = email_field

    # Validate data.records:read permission by attempting a test read
    try:
        from pyairtable import Api as AirtableApi
        api = AirtableApi(org.airtable_api_key)
        api.table(org.airtable_base_id, users_table).first()
    except Exception as e:
        err = str(e)
        if "403" in err or "FORBIDDEN" in err.upper() or "PERMISSION" in err.upper():
            flash("Warning: your Airtable token is missing data.records:read permission. "
                  "Users won't be able to log in until you add that scope to your token.", "error")

    # Clear field config when tables change
    org.field_config = {"user_fields": {}, "record_fields": {}}

    # Save client review settings (only meaningful when a records table is selected)
    if records_table:
        org.confirmation_enabled = "confirmation_enabled" in request.form
        org.confirmation_field = request.form.get("confirmation_field", "").strip() or None
        org.confirmation_value = request.form.get("confirmation_value", "").strip() or None
    else:
        org.confirmation_enabled = False
        org.confirmation_field = None
        org.confirmation_value = None

    # Clear schema cache to pick up any Airtable changes
    from airtable_client import AirtableClient
    AirtableClient.clear_schema_cache(org.airtable_base_id)

    db.session.commit()

    flash("Table configuration saved.", "success")
    return redirect(url_for("admin_fields"))


@app.route("/admin/fields")
@admin_required
def admin_fields():
    """Admin field configuration page."""
    org = _get_admin_org()
    if not org:
        return redirect(url_for("admin_login"))

    # If tables not configured, redirect to table setup
    if not org.tables_configured:
        flash("Please configure tables first.", "info")
        return redirect(url_for("admin_tables"))

    client = get_client_for_org(org)
    user_fields = client.get_all_user_fields()
    record_fields = client.get_all_record_fields() if org.has_linked_records else []

    # Identify computed/formula and link fields that can't be made editable
    computed_user_fields = client.get_computed_field_names(org.users_table)
    computed_record_fields = client.get_computed_field_names(org.records_table) if org.has_linked_records else set()

    users_table_schema = client.get_table_by_name(org.users_table)
    link_user_fields = {f["name"] for f in (users_table_schema or {}).get("linked_fields", [])}
    link_record_fields = set()

    # Get single select fields with their options from schema (not sampled records)
    select_fields = {}
    if org.has_linked_records:
        table_schema = client.get_table_by_name(org.records_table)
        if table_schema:
            link_record_fields = {f["name"] for f in table_schema.get("linked_fields", [])}
            for field in table_schema.get("fields", []):
                if field.get("type") == "singleSelect":
                    select_fields[field["name"]] = field.get("options", [])

    # Sort fields by saved config order (preserves admin-configured drag order)
    saved_user_order = list(org.user_field_config.keys())
    if saved_user_order:
        user_fields = sorted(user_fields, key=lambda f: saved_user_order.index(f) if f in saved_user_order else len(saved_user_order))

    saved_record_order = list(org.record_field_config.keys())
    if saved_record_order:
        record_fields = sorted(record_fields, key=lambda f: saved_record_order.index(f) if f in saved_record_order else len(saved_record_order))

    # Get translations (formerly annotations), aliases, and descriptions
    annotations = org.field_annotations
    user_translations = annotations.get("user_fields", {})
    record_translations = annotations.get("record_fields", {})

    aliases = org.field_aliases
    user_aliases = aliases.get("user_fields", {})
    record_aliases = aliases.get("record_fields", {})

    descriptions = org.field_descriptions
    user_descriptions = descriptions.get("user_fields", {})
    record_descriptions = descriptions.get("record_fields", {})

    return render_template(
        "admin/fields.html",
        org=org,
        user_fields=user_fields,
        record_fields=record_fields,
        select_fields=select_fields,
        user_field_config=org.user_field_config,
        record_field_config=org.record_field_config,
        user_translations=user_translations,
        record_translations=record_translations,
        user_aliases=user_aliases,
        record_aliases=record_aliases,
        user_descriptions=user_descriptions,
        record_descriptions=record_descriptions,
        computed_user_fields=computed_user_fields,
        computed_record_fields=computed_record_fields,
        link_user_fields=link_user_fields,
        link_record_fields=link_record_fields,
    )


@app.route("/admin/save-fields", methods=["POST"])
@admin_required
def admin_save_fields():
    """Save field configuration."""
    org = _get_admin_org()
    if not org:
        return redirect(url_for("admin_login"))

    client = get_client_for_org(org)
    all_user_fields = set(client.get_all_user_fields())
    all_record_fields = set(client.get_all_record_fields())

    computed_user_fields = client.get_computed_field_names(org.users_table)
    computed_record_fields = client.get_computed_field_names(org.records_table)

    # Use the drag-ordered field list from the hidden input (if present), else fall back to Airtable order
    raw_user_order = request.form.get("user_field_order", "")
    user_fields = [f for f in raw_user_order.split(",") if f.strip() in all_user_fields] if raw_user_order else sorted(all_user_fields)
    # Append any fields not yet in the order (newly added in Airtable)
    user_fields += [f for f in sorted(all_user_fields) if f not in user_fields]

    raw_record_order = request.form.get("record_field_order", "")
    record_fields = [f for f in raw_record_order.split(",") if f.strip() in all_record_fields] if raw_record_order else sorted(all_record_fields)
    record_fields += [f for f in sorted(all_record_fields) if f not in record_fields]

    # Build user field config in the submitted order
    user_field_config = {}
    for field_name in user_fields:
        permission = request.form.get(f"user_field_{field_name}", "hidden")
        if permission not in ("editable", "readonly", "hidden"):
            permission = "hidden"
        if field_name in computed_user_fields and permission == "editable":
            permission = "readonly"
        user_field_config[field_name] = permission

    # Build record field config in the submitted order
    record_field_config = {}
    for field_name in record_fields:
        permission = request.form.get(f"record_field_{field_name}", "hidden")
        if permission not in ("editable", "readonly", "hidden"):
            permission = "hidden"
        if field_name in computed_record_fields and permission == "editable":
            permission = "readonly"
        record_field_config[field_name] = permission

    # Save as nested structure (dict insertion order = field display order)
    org.field_config = {
        "user_fields": user_field_config,
        "record_fields": record_field_config,
    }

    # Build translations from form (formerly "annotations" — UI label changed, DB column unchanged)
    user_translations = {}
    for field_name in user_fields:
        translation = request.form.get(f"user_translation_{field_name}", "").strip()
        if translation:
            user_translations[field_name] = translation

    record_translations = {}
    for field_name in record_fields:
        translation = request.form.get(f"record_translation_{field_name}", "").strip()
        if translation:
            record_translations[field_name] = translation

    org.field_annotations = {
        "user_fields": user_translations,
        "record_fields": record_translations,
    }

    # Build aliases from form (only save non-empty ones)
    user_aliases = {}
    for field_name in user_fields:
        alias = request.form.get(f"user_alias_{field_name}", "").strip()
        if alias and alias != field_name:
            user_aliases[field_name] = alias

    record_aliases = {}
    for field_name in record_fields:
        alias = request.form.get(f"record_alias_{field_name}", "").strip()
        if alias and alias != field_name:
            record_aliases[field_name] = alias

    org.field_aliases = {
        "user_fields": user_aliases,
        "record_fields": record_aliases,
    }

    # Build descriptions from form
    user_descriptions = {}
    for field_name in user_fields:
        description = request.form.get(f"user_description_{field_name}", "").strip()
        if description:
            user_descriptions[field_name] = description

    record_descriptions = {}
    for field_name in record_fields:
        description = request.form.get(f"record_description_{field_name}", "").strip()
        if description:
            record_descriptions[field_name] = description

    org.field_descriptions = {
        "user_fields": user_descriptions,
        "record_fields": record_descriptions,
    }

    db.session.commit()

    flash("Field configuration saved.", "success")
    return redirect(url_for("admin_fields"))


# --- Admin Preview Routes ---


@app.route("/admin/preview")
@admin_required
def admin_preview():
    """Enter preview mode: log in as a random user in the org's users table."""
    import random
    org = _get_admin_org()
    if not org:
        return redirect(url_for("admin_login"))

    if not org.tables_configured:
        flash("Configure tables before using preview.", "info")
        return redirect(url_for("admin_tables"))

    client = get_client_for_org(org)
    try:
        all_users = client.users_table.all(max_records=50)
    except Exception:
        flash("Could not load users for preview.", "error")
        return redirect(url_for("admin_dashboard"))

    if not all_users:
        flash("No users found in the users table.", "error")
        return redirect(url_for("admin_dashboard"))

    preview_user = random.choice(all_users)
    fields = preview_user.get("fields", {})
    email_field = org.email_field or "Email"

    session["admin_preview"] = {
        "user_id": preview_user["id"],
        "org_code": org.org_code,
        "email": fields.get(email_field, ""),
        "name": fields.get("Name", "Preview User"),
    }
    # Use a synthetic Flask-Login user ID so load_user is called
    session["_user_id"] = f"{org.org_code}:__preview__"

    return redirect(url_for("dashboard"))


@app.route("/admin/preview/exit", methods=["POST"])
@admin_required
def admin_preview_exit():
    """Exit preview mode and return to admin dashboard."""
    session.pop("admin_preview", None)
    session.pop("_user_id", None)
    session.pop("user_cache", None)
    logout_user()
    return redirect(url_for("admin_dashboard"))


# --- Support Route ---


@app.route("/admin/support", methods=["GET", "POST"])
@admin_required
def admin_support():
    """Priority support form for admin users."""
    org = Organization.get_by_code(session["admin_org_code"])
    if not org:
        session.pop("admin_org_code", None)
        return redirect(url_for("admin_login"))

    if request.method == "POST":
        message = request.form.get("message", "").strip()
        if not message:
            flash("Please enter a message.", "error")
            return render_template("admin/support.html", org=org, message="")

        import html as _html
        import resend as _resend
        from config import Config
        if Config.RESEND_API_KEY:
            try:
                _resend.api_key = Config.RESEND_API_KEY
                _resend.Emails.send({
                    "from": Config.EMAIL_FROM,
                    "to": "info@airbud.app",
                    "reply_to": org.admin_email,
                    "subject": f"PRIORITY SUPPORT: {_html.escape(org.name)}",
                    "html": f"""
                        <p><strong>⚡ Priority Support Request</strong></p>
                        <ul>
                            <li><strong>Org:</strong> {_html.escape(org.name)} ({_html.escape(org.org_code)})</li>
                            <li><strong>Email:</strong> {_html.escape(org.admin_email)}</li>
                            <li><strong>Plan:</strong> {_html.escape(org.plan or 'unknown')}</li>
                        </ul>
                        <p><strong>Message:</strong></p>
                        <p>{_html.escape(message).replace(chr(10), '<br>')}</p>
                    """,
                })
                flash("Message sent! We'll be in touch shortly.", "success")
                return redirect(url_for("admin_support"))
            except Exception as e:
                import sys
                print(f"Error sending support email: {e}", file=sys.stderr)
                flash("Could not send your message. Please try again.", "error")
        else:
            flash("Support email is not configured.", "error")

    return render_template("admin/support.html", org=org, message="")


# --- Billing Routes ---


@app.route("/admin/billing")
@admin_required
def admin_billing():
    """Admin billing page."""
    org = _get_admin_org()
    if not org:
        return redirect(url_for("admin_login"))
    stripe_enabled = bool(Config.STRIPE_SECRET_KEY and Config.STRIPE_PRICE_ID)
    return render_template("admin/billing.html", org=org, stripe_enabled=stripe_enabled)


@app.route("/admin/billing/create-checkout", methods=["POST"])
@admin_required
def admin_create_checkout():
    """Start a Stripe Checkout session for the base plan."""
    import stripe as stripe_lib
    org = _get_admin_org()
    if not org:
        return redirect(url_for("admin_login"))

    stripe_lib.api_key = Config.STRIPE_SECRET_KEY
    try:
        checkout = stripe_lib.checkout.Session.create(
            payment_method_types=["card"],
            mode="subscription",
            line_items=[{"price": Config.STRIPE_PRICE_ID, "quantity": 1}],
            success_url=url_for("admin_billing_success", _external=True) + "?session_id={CHECKOUT_SESSION_ID}",
            cancel_url=url_for("admin_billing", _external=True),
            customer_email=org.admin_email,
            metadata={"org_code": org.org_code},
        )
        return redirect(checkout.url)
    except Exception as e:
        flash(f"Could not start checkout: {e}", "error")
        return redirect(url_for("admin_billing"))


@app.route("/admin/billing/success")
@admin_required
def admin_billing_success():
    """Stripe redirects here after successful checkout.

    Plan activation is handled exclusively by the Stripe webhook (/stripe/webhook).
    This route only acknowledges the redirect.
    """
    flash("Payment received — your subscription is being activated.", "info")
    return redirect(url_for("admin_billing"))


@app.route("/admin/billing/portal", methods=["POST"])
@admin_required
def admin_billing_portal():
    """Open Stripe Customer Portal to manage/cancel subscription."""
    import stripe as stripe_lib
    org = _get_admin_org()
    if not org or not org.stripe_customer_id:
        flash("No billing account found.", "error")
        return redirect(url_for("admin_billing"))

    stripe_lib.api_key = Config.STRIPE_SECRET_KEY
    try:
        kwargs = dict(
            customer=org.stripe_customer_id,
            return_url=url_for("admin_billing", _external=True),
        )
        # Deep-link to payment method update if requested
        if request.form.get("action") == "payment":
            kwargs["flow_data"] = {
                "type": "payment_method_update",
            }
        portal = stripe_lib.billing_portal.Session.create(**kwargs)
        return redirect(portal.url)
    except Exception as e:
        flash(f"Could not open billing portal: {e}", "error")
        return redirect(url_for("admin_billing"))


@app.route("/admin/billing/activate-promo", methods=["POST"])
@admin_required
def admin_activate_promo():
    """Activate portal with a promo code."""
    org = _get_admin_org()
    if not org:
        return redirect(url_for("admin_login"))

    code = request.form.get("promo_code", "").strip().upper()
    valid_codes = PromoCode.get_active_codes()

    if code and code in valid_codes:
        if org.stripe_subscription_id:
            try:
                import stripe as stripe_lib
                stripe_lib.api_key = Config.STRIPE_SECRET_KEY
                stripe_lib.Subscription.cancel(org.stripe_subscription_id)
            except Exception:
                pass
            org.stripe_subscription_id = None
            org.stripe_customer_id = None
        org.plan = "active"
        org.promo_code = code
        org.subscription_cancel_at = None
        db.session.commit()
        flash("Promo code accepted. Your portal is now active!", "success")
    else:
        flash("Invalid promo code.", "error")
    return redirect(url_for("admin_billing"))


@app.route("/admin/close-account", methods=["POST"])
@admin_required
def admin_close_account():
    """Permanently delete the organization and cancel any Stripe subscription."""
    org = _get_admin_org()
    if not org:
        return redirect(url_for("admin_login"))

    # Cancel Stripe subscription if active
    if org.stripe_subscription_id and Config.STRIPE_SECRET_KEY:
        try:
            import stripe as stripe_lib
            stripe_lib.api_key = Config.STRIPE_SECRET_KEY
            stripe_lib.Subscription.cancel(org.stripe_subscription_id)
        except Exception as e:
            print(f"Could not cancel Stripe subscription for {org.org_code}: {e}", flush=True)

    # Remove child rows that have a FK to this org before deleting the org itself
    LoginAttempt.query.filter_by(org_id=org.id).delete()
    LoginCode.query.filter_by(org_id=org.id).delete()

    session.pop("admin_org_code", None)
    db.session.delete(org)
    db.session.commit()

    flash("Your account has been closed.", "info")
    return redirect(url_for("index"))


@app.route("/stripe/webhook", methods=["POST"])
@csrf.exempt
def stripe_webhook():
    """Handle Stripe webhook events."""
    import stripe as stripe_lib
    stripe_lib.api_key = Config.STRIPE_SECRET_KEY
    payload = request.get_data()
    sig_header = request.headers.get("Stripe-Signature")

    try:
        event = stripe_lib.Webhook.construct_event(payload, sig_header, Config.STRIPE_WEBHOOK_SECRET)
    except Exception:
        return "", 400

    if event["type"] == "checkout.session.completed":
        s = event["data"]["object"]
        org_code = (s.get("metadata") or {}).get("org_code")
        org = Organization.get_by_code(org_code) if org_code else None
        if org:
            org.plan = "active"
            org.stripe_customer_id = s.get("customer")
            org.stripe_subscription_id = s.get("subscription")
            db.session.commit()

    elif event["type"] == "customer.subscription.updated":
        sub = event["data"]["object"]
        org = Organization.query.filter_by(stripe_subscription_id=sub["id"]).first()
        if org:
            cancel_ts = sub.get("cancel_at") or (sub.get("current_period_end") if sub.get("cancel_at_period_end") else None)
            org.subscription_cancel_at = datetime.fromtimestamp(cancel_ts, tz=timezone.utc) if cancel_ts else None
            db.session.commit()

    elif event["type"] == "customer.subscription.deleted":
        sub = event["data"]["object"]
        org = Organization.query.filter_by(stripe_subscription_id=sub["id"]).first()
        if org:
            org.plan = "suspended"
            org.subscription_cancel_at = None
            db.session.commit()

    return "", 200


# --- Admin Password Recovery ---


@app.route("/admin/forgot-password", methods=["GET", "POST"])
def admin_forgot_password():
    """Send admin password reset link."""
    if request.method == "POST":
        org_code = request.form.get("org_code", "").strip().upper()
        org = Organization.get_by_code(org_code)

        if org and org.admin_email:
            base_url = Config.APP_URL.rstrip("/")
            sent = send_admin_reset_email(org, base_url)
            if not sent:
                flash(
                    "Could not send the reset email — there may be an issue with your email configuration. "
                    "Check that RESEND_API_KEY and EMAIL_FROM are set correctly.",
                    "error",
                )
                return redirect(url_for("admin_forgot_password"))
        # Always show the same generic confirmation — don't reveal whether org/email exists
        flash("If that organization has an admin email on file, you'll receive a reset link shortly.", "info")
        return redirect(url_for("admin_forgot_password"))

    org_code = request.args.get("org", "")
    return render_template("admin/forgot_password.html", org_code=org_code)


@app.route("/admin/reset-password/<token>", methods=["GET", "POST"])
def admin_reset_password(token):
    """Reset admin password via token from email."""
    org_id = verify_admin_reset_token(token)
    if not org_id:
        flash("This reset link is invalid or has expired.", "error")
        return redirect(url_for("admin_login"))

    org = Organization.query.get(org_id)
    if not org:
        flash("Organization not found.", "error")
        return redirect(url_for("admin_login"))

    if request.method == "POST":
        password = request.form.get("password", "").strip()
        confirm = request.form.get("password_confirm", "").strip()

        pw_error = validate_password(password) if password else "Password is required."
        if pw_error:
            flash(pw_error, "error")
            return render_template("admin/reset_password.html", token=token, org=org)

        if password != confirm:
            flash("Passwords do not match.", "error")
            return render_template("admin/reset_password.html", token=token, org=org)

        org.set_admin_password(password)
        db.session.commit()
        flash("Password reset successfully. Please log in.", "success")
        return redirect(url_for("admin_login", org=org.org_code))

    return render_template("admin/reset_password.html", token=token, org=org)


@app.route("/admin/cancel-pending-email", methods=["POST"])
@admin_required
def admin_cancel_pending_email():
    """Cancel a pending admin email change."""
    org = _get_admin_org()
    if org and org.pending_admin_email:
        org.pending_admin_email = None
        db.session.commit()
        flash("Pending email change cancelled.", "info")
    return redirect(url_for("admin_settings"))


@app.route("/admin/verify-email/<token>")
def admin_verify_email(token):
    """Confirm an admin email change via token."""
    result = verify_admin_email_token(token)
    if not result:
        flash("This verification link is invalid or has expired.", "error")
        return redirect(url_for("admin_login"))

    org_id, new_email = result
    org = Organization.query.get(org_id)
    if not org:
        flash("Organization not found.", "error")
        return redirect(url_for("admin_login"))

    if org.pending_admin_email != new_email:
        flash("This verification link is no longer valid (a newer request may have superseded it).", "error")
        return redirect(url_for("admin_login"))

    org.admin_email = new_email
    org.pending_admin_email = None
    db.session.commit()
    flash(f"Admin email updated to {new_email}.", "success")

    # If already logged in as this org, send them to settings; otherwise login.
    if session.get("admin_org_code") == org.org_code:
        return redirect(url_for("admin_settings"))
    return redirect(url_for("admin_login", org=org.org_code))


# --- Superadmin Routes ---


def _email_body_to_html(body_text: str) -> str:
    import html as _html
    escaped = _html.escape(body_text)
    paragraphs = escaped.split("\n\n")
    return "".join(f"<p>{p.replace(chr(10), '<br>')}</p>" for p in paragraphs)


def superadmin_required(f):
    """Decorator to require superadmin authentication."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get("superadmin"):
            return redirect(url_for("superadmin_login"))
        return f(*args, **kwargs)
    return decorated_function


@app.route("/superadmin/login", methods=["GET", "POST"])
def superadmin_login():
    """Superadmin login — password-only, protected by SUPERADMIN_PASSWORD env var."""
    if session.get("superadmin"):
        return redirect(url_for("superadmin_users"))

    if not Config.SUPERADMIN_PASSWORD:
        abort(404)

    _SA_ORG_ID = 0
    _SA_EMAIL = "__superadmin__"

    if request.method == "POST":
        if is_locked_out(_SA_ORG_ID, _SA_EMAIL):
            remaining = get_lockout_remaining(_SA_ORG_ID, _SA_EMAIL)
            flash(f"Too many failed attempts. Try again in {remaining // 60} minutes.", "error")
            return render_template("superadmin/login.html")

        password = request.form.get("password", "")
        if password and Config.SUPERADMIN_PASSWORD and hmac.compare_digest(password, Config.SUPERADMIN_PASSWORD):
            clear_failed_attempts(_SA_ORG_ID, _SA_EMAIL)
            session["superadmin"] = True
            return redirect(url_for("superadmin_users"))

        record_failed_attempt(_SA_ORG_ID, _SA_EMAIL)
        flash("Incorrect password.", "error")

    return render_template("superadmin/login.html")


@app.route("/superadmin/logout")
def superadmin_logout():
    """Superadmin logout."""
    session.pop("superadmin", None)
    return redirect(url_for("superadmin_login"))


@app.route("/superadmin/users")
@superadmin_required
def superadmin_users():
    """Superadmin users list — all organizations."""
    orgs = Organization.query.order_by(Organization.created_at.desc().nullslast()).all()
    promo_codes = PromoCode.query.order_by(PromoCode.created_at.desc()).all()
    return render_template("superadmin/users.html", orgs=orgs, promo_codes=promo_codes)


@app.route("/superadmin/toggle-active/<int:org_id>", methods=["POST"])
@superadmin_required
def superadmin_toggle_active(org_id):
    """Toggle is_active for an organization."""
    org = Organization.query.get(org_id)
    if not org:
        abort(404)
    org.is_active = not org.is_active
    db.session.commit()
    return redirect(url_for("superadmin_users"))


@app.route("/superadmin/promo-codes/create", methods=["POST"])
@superadmin_required
def superadmin_create_promo():
    """Create a new promo code."""
    code = request.form.get("code", "").strip().upper()
    if not code:
        flash("Code cannot be empty.", "error")
        return redirect(url_for("superadmin_users"))
    if PromoCode.query.filter_by(code=code).first():
        flash(f"Code {code} already exists.", "error")
        return redirect(url_for("superadmin_users"))
    db.session.add(PromoCode(code=code, active=True))
    db.session.commit()
    flash(f"Promo code {code} created.", "success")
    return redirect(url_for("superadmin_users"))


@app.route("/superadmin/delete-org/<int:org_id>", methods=["POST"])
@superadmin_required
def superadmin_delete_org(org_id):
    """Permanently delete an organization and all associated data."""
    org = Organization.query.get(org_id)
    if not org:
        abort(404)

    # Require the org code to be echoed back as confirmation
    confirm_code = request.form.get("confirm_code", "").strip().upper()
    if confirm_code != org.org_code:
        flash("Org code did not match — deletion cancelled.", "error")
        return redirect(url_for("superadmin_users"))

    org_name = org.name
    LoginAttempt.query.filter_by(org_id=org_id).delete()
    LoginCode.query.filter_by(org_id=org_id).delete()
    db.session.delete(org)
    db.session.commit()

    flash(f"Organization '{org_name}' has been permanently deleted.", "success")
    return redirect(url_for("superadmin_users"))


@app.route("/superadmin/promo-codes/toggle/<int:code_id>", methods=["POST"])
@superadmin_required
def superadmin_toggle_promo(code_id):
    """Toggle a promo code active/inactive. Sunsetting converts orgs on that code to a 7-day trial."""
    promo = PromoCode.query.get(code_id)
    if not promo:
        abort(404)
    promo.active = not promo.active
    if not promo.active:
        affected = Organization.query.filter_by(promo_code=promo.code, plan="active").all()
        for org in affected:
            org.plan = "trial"
            org.trial_started_at = datetime.now(timezone.utc)
        if affected:
            flash(f"{len(affected)} org(s) converted to 7-day trial.", "warning")
    db.session.commit()
    return redirect(url_for("superadmin_users"))


@app.route("/superadmin/leads/send", methods=["POST"])
@superadmin_required
def superadmin_send_leads():
    """Send a one-off outreach email."""
    import resend as _resend
    _resend.api_key = Config.RESEND_API_KEY

    to_email = request.form.get("to_email", "").strip()
    subject = request.form.get("subject", "").strip()
    body_text = request.form.get("body", "").strip()

    if not to_email or not subject or not body_text:
        flash("To, subject, and body are all required.", "error")
        return redirect(url_for("superadmin_users") + "#leads")

    try:
        _resend.Emails.send({
            "from": "Mike Pechter <info@airbud.app>",
            "to": to_email,
            "subject": subject,
            "html": _email_body_to_html(body_text),
        })
        flash(f"Sent to {to_email}.", "success")
    except Exception as e:
        flash(f"Failed to send: {e}", "error")

    return redirect(url_for("superadmin_users") + "#leads")


# --- CLI Commands ---


# --- Signup Routes ---


def generate_org_code(name: str) -> str:
    """Generate a unique org code from organization name."""
    import re
    import random
    import string

    # Create base code from name (uppercase, alphanumeric only)
    base = re.sub(r'[^A-Z0-9]', '', name.upper())[:6]
    if len(base) < 3:
        base = base + ''.join(random.choices(string.ascii_uppercase, k=3-len(base)))

    # Check uniqueness, add suffix if needed
    code = base
    suffix = 1
    while Organization.query.filter_by(org_code=code).first():
        code = f"{base}{suffix}"
        suffix += 1

    return code


def validate_airtable_credentials(api_key: str, base_id: str) -> tuple[bool, str]:
    """Test if Airtable credentials are valid by trying to fetch base schema."""
    try:
        from pyairtable import Api
        api = Api(api_key)
        base = api.base(base_id)
        schema = base.schema()
        if schema.tables:
            return True, f"Connected successfully. Found {len(schema.tables)} tables."
        return True, "Connected successfully."
    except Exception as e:
        error_msg = str(e)
        if "401" in error_msg or "AUTHENTICATION" in error_msg.upper():
            return False, "Invalid API key. Please check your Airtable Personal Access Token."
        elif "404" in error_msg or "NOT_FOUND" in error_msg.upper():
            return False, "Base not found. Please check your Base ID."
        elif "403" in error_msg or "FORBIDDEN" in error_msg.upper():
            return False, "Access denied. Make sure your API key has access to this base."
        else:
            return False, f"Connection failed: {error_msg}"


@app.route("/signup", methods=["GET", "POST"])
def signup():
    """Step 1: Create account — email + password, then send verification email."""
    if request.method == "POST":
        from werkzeug.security import generate_password_hash
        admin_email = request.form.get("admin_email", "").strip().lower()
        admin_password = request.form.get("admin_password", "").strip()
        admin_password_confirm = request.form.get("admin_password_confirm", "").strip()

        agree_terms = request.form.get("agree_terms")

        errors = []
        if not admin_email:
            errors.append("Email is required.")
        if not admin_password:
            errors.append("Password is required.")
        elif (pw_error := validate_password(admin_password)):
            errors.append(pw_error)
        elif admin_password != admin_password_confirm:
            errors.append("Passwords do not match.")
        if not agree_terms:
            errors.append("You must agree to the Terms of Service and Privacy Policy.")

        if not errors:
            if Organization.query.filter_by(admin_email=admin_email).first():
                errors.append("An account with this email already exists.")

        if errors:
            for error in errors:
                flash(error, "error")
            return render_template("signup.html", admin_email=admin_email)

        password_hash = generate_password_hash(admin_password)
        token = generate_signup_token(admin_email, password_hash)
        base_url = Config.APP_URL.rstrip("/")
        sent = send_signup_verification_email(admin_email, token, base_url)

        if sent:
            return render_template("signup_check_email.html", email=admin_email)
        else:
            flash("Could not send verification email. Please try again.", "error")
            return render_template("signup.html", admin_email=admin_email)

    return render_template("signup.html", admin_email="")


@app.route("/signup/verify/<token>")
def signup_verify(token):
    """Verify the email token from the signup confirmation link."""
    data = verify_signup_token(token)
    if not data:
        flash("This verification link has expired or is invalid.", "error")
        return redirect(url_for("signup"))

    # Store credentials in session so step 2 can use them
    session["pending_signup"] = {
        "email": data["email"],
        "password_hash": data["password_hash"],
    }
    return redirect(url_for("signup_setup"))


@app.route("/signup/setup", methods=["GET", "POST"])
def signup_setup():
    """Step 2: Set up the portal — org name, promo code, Airtable keys."""
    pending = session.get("pending_signup")
    if not pending:
        flash("Please start signup from the beginning.", "error")
        return redirect(url_for("signup"))

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        org_code = request.form.get("org_code", "").strip().upper()
        promo_code = request.form.get("promo_code", "").strip().upper()
        airtable_api_key = request.form.get("airtable_api_key", "").strip()
        airtable_base_id = request.form.get("airtable_base_id", "").strip()

        errors = []
        if not name:
            errors.append("Organization name is required.")

        if not org_code:
            org_code = generate_org_code(name) if name else ""
        elif len(org_code) < 3:
            errors.append("Org code must be at least 3 characters.")
        elif Organization.query.filter_by(org_code=org_code).first():
            errors.append(f"Org code '{org_code}' is already taken.")

        if not airtable_api_key:
            errors.append("Airtable API key is required.")
        if not airtable_base_id:
            errors.append("Airtable Base ID is required.")

        if not errors and airtable_api_key and airtable_base_id:
            is_valid, message = validate_airtable_credentials(airtable_api_key, airtable_base_id)
            if not is_valid:
                errors.append(message)

        if errors:
            for error in errors:
                flash(error, "error")
            return render_template("signup_setup.html",
                                   name=name,
                                   org_code=org_code,
                                   airtable_base_id=airtable_base_id,
                                   promo_code=promo_code)

        # Determine plan
        plan = "trial"
        valid_promo = None
        if promo_code:
            valid_codes = PromoCode.get_active_codes()
            if promo_code in valid_codes:
                plan = "active"
                valid_promo = promo_code
            else:
                flash("Invalid promo code — your portal will start on a free trial.", "warning")

        # Guard against duplicate email (race condition)
        email = pending["email"]
        if Organization.query.filter_by(admin_email=email).first():
            flash("An account with this email already exists.", "error")
            session.pop("pending_signup", None)
            return redirect(url_for("signup"))

        from datetime import datetime, timezone as _tz
        org = Organization(
            org_code=org_code,
            name=name,
            admin_email=email,
            airtable_api_key=airtable_api_key,
            airtable_base_id=airtable_base_id,
            portal_title=f"{name} Portal",
            plan=plan,
            promo_code=valid_promo,
            trial_started_at=datetime.now(_tz.utc) if plan == "trial" else None,
        )
        org.admin_password_hash = pending["password_hash"]

        db.session.add(org)
        db.session.commit()

        send_signup_notification(org.name, org.admin_email, plan)

        session.pop("pending_signup", None)
        session["admin_org_code"] = org.org_code

        flash("Portal created! Now let's connect your tables.", "success")
        return redirect(url_for("admin_tables"))

    return render_template("signup_setup.html", name="", org_code="", airtable_base_id="", promo_code="")


@app.cli.command("init-db")
def init_db():
    """Initialize the database."""
    db.create_all()
    print("Database initialized.")


@app.cli.command("migrate-db")
def migrate_db():
    """Apply incremental schema migrations."""
    with db.engine.connect() as conn:
        # Add email_field column if it doesn't exist
        from sqlalchemy import text, inspect
        inspector = inspect(db.engine)
        cols = {c["name"] for c in inspector.get_columns("organizations")}
        new_cols = {
            "email_field": "VARCHAR(100) DEFAULT 'Email'",
            "stripe_customer_id": "VARCHAR(100)",
            "stripe_subscription_id": "VARCHAR(100)",
            "promo_code": "VARCHAR(100)",
            "pending_admin_email": "VARCHAR(255)",
            "trial_started_at": "TIMESTAMP WITH TIME ZONE",
            "created_at": "TIMESTAMP WITH TIME ZONE DEFAULT NOW()",
            "field_aliases": "TEXT DEFAULT '{}'",
            "field_descriptions": "TEXT DEFAULT '{}'",
            "subscription_cancel_at": "TIMESTAMP WITH TIME ZONE",
        }
        for col, col_def in new_cols.items():
            if col not in cols:
                conn.execute(text(f"ALTER TABLE organizations ADD COLUMN {col} {col_def}"))
                conn.commit()
                print(f"Added {col} column.")
            else:
                print(f"{col} already exists.")

        # Create promo_codes table if missing
        tables = inspect(db.engine).get_table_names()
        if "promo_codes" not in tables:
            conn.execute(text("""
                CREATE TABLE promo_codes (
                    id SERIAL PRIMARY KEY,
                    code VARCHAR(100) UNIQUE NOT NULL,
                    active BOOLEAN NOT NULL DEFAULT TRUE,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
                )
            """))
            conn.commit()
            print("Created promo_codes table.")

            # Seed from PROMO_CODES env var
            from config import Config as _Config
            env_codes = [c.strip().upper() for c in (_Config.PROMO_CODES or "").split(",") if c.strip()]
            for code in env_codes:
                conn.execute(text("INSERT INTO promo_codes (code, active) VALUES (:code, TRUE) ON CONFLICT DO NOTHING"), {"code": code})
            conn.commit()
            if env_codes:
                print(f"Seeded {len(env_codes)} promo code(s) from PROMO_CODES env var.")
        else:
            print("promo_codes table already exists.")

    print("Migration complete.")


@app.cli.command("add-org")
def add_org():
    """Interactively add a new organization."""
    print("Add a new organization")
    print("-" * 30)

    org_code = input("Org code (e.g., SCHOOL1): ").strip().upper()
    name = input("Organization name: ").strip()
    api_key = input("Airtable API key: ").strip()
    base_id = input("Airtable base ID: ").strip()
    portal_title = input("Portal title [Parent Portal]: ").strip() or "Parent Portal"
    admin_password = input("Admin password: ").strip()

    org = Organization(
        org_code=org_code,
        name=name,
        airtable_api_key=api_key,
        airtable_base_id=base_id,
        portal_title=portal_title,
    )
    if admin_password:
        org.set_admin_password(admin_password)

    db.session.add(org)
    db.session.commit()
    print(f"Organization '{org_code}' added successfully.")
    print("Log in as admin to configure tables and fields.")


@app.cli.command("add-admin-columns")
def add_admin_columns():
    """Add admin_email and plan columns to organizations table (safe to run multiple times)."""
    with db.engine.connect() as conn:
        for col, definition in [
            ("admin_email", "VARCHAR(255)"),
            ("plan", "VARCHAR(20)"),
        ]:
            try:
                conn.execute(db.text(f"ALTER TABLE organizations ADD COLUMN {col} {definition}"))
                conn.commit()
                print(f"Added column: {col}")
            except Exception:
                print(f"Column already exists (skipping): {col}")


@app.cli.command("set-admin-password")
def set_admin_password():
    """Set admin password for an organization."""
    org_code = input("Org code: ").strip().upper()
    org = Organization.get_by_code(org_code)
    if not org:
        print(f"Organization '{org_code}' not found.")
        return

    password = input("New admin password: ").strip()
    org.set_admin_password(password)
    db.session.commit()
    print(f"Admin password set for '{org_code}'.")


if __name__ == "__main__":
    with app.app_context():
        db.create_all()
    app.run(debug=os.environ.get("FLASK_DEBUG", "false").lower() == "true")
