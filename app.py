from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, flash, session, abort
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from config import Config
from models import db, Organization
from airtable_client import get_client_for_org
from auth import send_login_code, verify_login_code, is_locked_out, get_lockout_remaining

app = Flask(__name__)
app.config.from_object(Config)

db.init_app(app)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"


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
    """Load user from session data."""
    if ":" not in user_id:
        return None

    org_code, airtable_id = user_id.split(":", 1)
    org = Organization.get_by_code(org_code)
    if not org:
        return None

    client = get_client_for_org(org)
    user_data = client.get_user_by_id(airtable_id)
    if not user_data:
        return None

    fields = user_data.get("fields", {})
    return User(
        org_code=org_code,
        user_id=airtable_id,
        email=fields.get("Email", ""),
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


# --- User Routes ---


@app.route("/")
def index():
    """Home page - prompt for org code."""
    return render_template("index.html")


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

        # Check if locked out
        if is_locked_out(email):
            remaining = get_lockout_remaining(email)
            flash(f"Too many failed attempts. Try again in {remaining // 60} minutes.", "error")
            return render_template("login.html", org_code=org_code, email=email)

        # Find the user in Airtable
        client = get_client_for_org(org)
        user = client.get_user_by_email(email)
        if not user:
            flash("Email not found. Please contact your administrator.", "error")
            return render_template("login.html", org_code=org_code, email=email)

        # Send login code
        code = send_login_code(org, email, user["id"])
        if code:
            # Store org_code and email in session for code verification
            session["pending_org_code"] = org_code
            session["pending_email"] = email
            # In demo mode, store code in session so we can display it
            if Config.DEMO_MODE:
                session["demo_code"] = code
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

    # Get demo code if in demo mode
    demo_code = session.get("demo_code") if Config.DEMO_MODE else None

    if request.method == "POST":
        code = request.form.get("code", "").strip()

        # Check lockout
        if is_locked_out(email):
            remaining = get_lockout_remaining(email)
            flash(f"Too many failed attempts. Try again in {remaining // 60} minutes.", "error")
            return render_template("verify_code.html", email=email, org=org, demo_code=demo_code)

        # Verify the code
        user_data = verify_login_code(org, email, code)
        if not user_data:
            flash("Invalid or expired code. Please try again.", "error")
            return render_template("verify_code.html", email=email, org=org, demo_code=demo_code)

        # Success - log them in
        fields = user_data.get("fields", {})
        user = User(
            org_code=org.org_code,
            user_id=user_data["id"],
            email=fields.get("Email", ""),
            name=fields.get("Name", ""),
        )
        login_user(user)

        # Clear pending session data and store org_code
        session.pop("pending_org_code", None)
        session.pop("pending_email", None)
        session.pop("demo_code", None)
        session["org_code"] = org.org_code

        return redirect(url_for("dashboard"))

    return render_template("verify_code.html", email=email, org=org, demo_code=demo_code)


@app.route("/logout")
@login_required
def logout():
    """Log out the current user."""
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

    client = get_client_for_org(org)

    # Get user's own profile data
    user_data = client.get_user_by_id(current_user.user_id)
    user_fields = user_data.get("fields", {}) if user_data else {}

    # Get linked field names to exclude from display
    linked_field_names = set()
    users_table_info = client.get_table_by_name(org.users_table)
    if users_table_info:
        for field in users_table_info.get("linked_fields", []):
            linked_field_names.add(field["name"])

    # Get field permissions for user profile, excluding link fields
    user_editable_fields = [f for f in org.get_user_editable_fields() if f not in linked_field_names]
    user_readonly_fields = [f for f in org.get_user_readonly_fields() if f not in linked_field_names]
    has_profile_fields = bool(user_editable_fields or user_readonly_fields)

    # Get linked records (only if configured)
    records = []
    if org.has_linked_records:
        records = client.get_records_for_user(current_user.user_id)

    return render_template(
        "dashboard.html",
        records=records,
        org=org,
        user=current_user,
        user_fields=user_fields,
        user_editable_fields=user_editable_fields,
        user_readonly_fields=user_readonly_fields,
        has_profile_fields=has_profile_fields,
    )


@app.route("/record/<record_id>", methods=["GET", "POST"])
@login_required
def edit_record(record_id: str):
    """Edit a specific record."""
    org = Organization.get_by_code(current_user.org_code)
    if not org:
        logout_user()
        return redirect(url_for("login"))

    client = get_client_for_org(org)

    # Verify user has access to this record
    if not client.can_user_access_record(current_user.user_id, record_id):
        abort(403)

    record = client.get_record_by_id(record_id)
    if not record:
        abort(404)

    # Get field permissions from org config (for linked records)
    editable_fields = org.get_record_editable_fields()
    readonly_fields = org.get_record_readonly_fields()

    # Get field metadata for type-aware rendering
    all_fields = editable_fields + readonly_fields
    field_metadata = client.get_field_metadata(org.records_table, all_fields)

    if request.method == "POST":
        # Build update dict with only editable fields
        updates = {}
        for field_name in editable_fields:
            field_type = field_metadata.get(field_name, {}).get("type", "singleLineText")

            # Handle checkbox fields specially
            if field_type == "checkbox":
                updates[field_name] = field_name in request.form
            # Handle multi-select fields (multiple values with same name)
            elif field_type == "multipleSelects":
                updates[field_name] = request.form.getlist(field_name)
            else:
                form_value = request.form.get(field_name)
                if form_value is not None:
                    # Convert empty strings to None for certain field types
                    if form_value == "" and field_type in ("number", "date"):
                        updates[field_name] = None
                    else:
                        updates[field_name] = form_value

        # Handle data confirmation
        if org.confirmation_enabled and org.confirmation_field:
            if "data_confirmed" in request.form:
                from datetime import date
                updates[org.confirmation_field] = date.today().isoformat()

        if updates:
            client.update_record(record_id, updates)
            flash("Changes saved successfully.", "success")

        return redirect(url_for("edit_record", record_id=record_id))

    # Get last confirmed date if confirmation is enabled
    last_confirmed = None
    if org.confirmation_enabled and org.confirmation_field:
        last_confirmed = record.get("fields", {}).get(org.confirmation_field)

    return render_template(
        "edit_record.html",
        record=record,
        editable_fields=editable_fields,
        readonly_fields=readonly_fields,
        field_metadata=field_metadata,
        org=org,
        last_confirmed=last_confirmed,
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

    # Get linked field names to exclude from display
    linked_field_names = set()
    users_table_info = client.get_table_by_name(org.users_table)
    if users_table_info:
        for field in users_table_info.get("linked_fields", []):
            linked_field_names.add(field["name"])

    # Get field permissions for user profile, excluding link fields
    editable_fields = [f for f in org.get_user_editable_fields() if f not in linked_field_names]
    readonly_fields = [f for f in org.get_user_readonly_fields() if f not in linked_field_names]

    # Get field metadata for type-aware rendering
    all_fields = editable_fields + readonly_fields
    field_metadata = client.get_field_metadata(org.users_table, all_fields)

    if request.method == "POST":
        # Build update dict with only editable fields
        updates = {}
        for field_name in editable_fields:
            field_type = field_metadata.get(field_name, {}).get("type", "singleLineText")

            # Handle checkbox fields specially
            if field_type == "checkbox":
                updates[field_name] = field_name in request.form
            # Handle multi-select fields (multiple values with same name)
            elif field_type == "multipleSelects":
                updates[field_name] = request.form.getlist(field_name)
            else:
                form_value = request.form.get(field_name)
                if form_value is not None:
                    # Convert empty strings to None for certain field types
                    if form_value == "" and field_type in ("number", "date"):
                        updates[field_name] = None
                    else:
                        updates[field_name] = form_value

        if updates:
            client.update_user(current_user.user_id, updates)
            flash("Profile updated successfully.", "success")

        return redirect(url_for("edit_profile"))

    return render_template(
        "edit_profile.html",
        user_data=user_data,
        editable_fields=editable_fields,
        readonly_fields=readonly_fields,
        field_metadata=field_metadata,
        org=org,
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

        if not org.check_admin_password(password):
            flash("Invalid password.", "error")
            return render_template("admin/login.html", org_code=org_code)

        # Success - store admin session
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
    org = Organization.get_by_code(session["admin_org_code"])
    if not org:
        session.pop("admin_org_code", None)
        return redirect(url_for("admin_login"))

    # If tables not configured, redirect to table setup
    if not org.tables_configured:
        return redirect(url_for("admin_tables"))

    return redirect(url_for("admin_fields"))


@app.route("/admin/settings", methods=["GET"])
@admin_required
def admin_settings():
    """Admin settings page - basic configuration."""
    org = Organization.get_by_code(session["admin_org_code"])
    if not org:
        session.pop("admin_org_code", None)
        return redirect(url_for("admin_login"))

    return render_template("admin/settings.html", org=org)


@app.route("/admin/save-settings", methods=["POST"])
@admin_required
def admin_save_settings():
    """Save admin settings."""
    org = Organization.get_by_code(session["admin_org_code"])
    if not org:
        return redirect(url_for("admin_login"))

    # Get form values
    name = request.form.get("name", "").strip()
    portal_title = request.form.get("portal_title", "").strip()
    logo_url = request.form.get("logo_url", "").strip() or None
    airtable_api_key = request.form.get("airtable_api_key", "").strip()
    airtable_base_id = request.form.get("airtable_base_id", "").strip()

    if not name:
        flash("Organization name is required.", "error")
        return redirect(url_for("admin_settings"))

    if not airtable_api_key or not airtable_base_id:
        flash("Airtable API key and Base ID are required.", "error")
        return redirect(url_for("admin_settings"))

    # Check if Airtable credentials changed - if so, clear table config
    credentials_changed = (
        airtable_api_key != org.airtable_api_key or
        airtable_base_id != org.airtable_base_id
    )

    org.name = name
    org.portal_title = portal_title or "Portal"
    org.logo_url = logo_url
    org.airtable_api_key = airtable_api_key
    org.airtable_base_id = airtable_base_id

    if credentials_changed:
        # Clear table and field config since we're connecting to a different base
        org.users_table = None
        org.records_table = None
        org.link_field = None
        org.field_config = {"user_fields": {}, "record_fields": {}}
        flash("Settings saved. Please reconfigure your tables.", "success")
        db.session.commit()
        return redirect(url_for("admin_tables"))

    db.session.commit()
    flash("Settings saved.", "success")
    return redirect(url_for("admin_settings"))


@app.route("/admin/tables", methods=["GET"])
@admin_required
def admin_tables():
    """Admin table configuration page."""
    org = Organization.get_by_code(session["admin_org_code"])
    if not org:
        session.pop("admin_org_code", None)
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
    org = Organization.get_by_code(session["admin_org_code"])
    if not org:
        return redirect(url_for("admin_login"))

    users_table = request.form.get("users_table", "").strip()
    records_table = request.form.get("records_table", "").strip()

    if not users_table:
        flash("Please select a Users table.", "error")
        return redirect(url_for("admin_tables"))

    # Validate that Users table has required fields
    client = get_client_for_org(org)
    org.users_table = users_table  # Temporarily set for client to use
    users_table_info = client.get_table_by_name(users_table)

    if users_table_info:
        field_names = {f["name"] for f in users_table_info.get("fields", [])}
        required_fields = {"Email", "Login Code", "Code Expires"}
        missing_fields = required_fields - field_names

        if missing_fields:
            flash(f"Warning: Users table is missing required fields: {', '.join(sorted(missing_fields))}. "
                  "Login will not work until these fields are added to your Airtable base.", "error")

    org.records_table = records_table if records_table else None
    org.link_field = None  # Auto-detected from schema

    # Clear field config when tables change
    org.field_config = {"user_fields": {}, "record_fields": {}}

    db.session.commit()

    flash("Table configuration saved.", "success")
    return redirect(url_for("admin_fields"))


@app.route("/admin/fields")
@admin_required
def admin_fields():
    """Admin field configuration page."""
    org = Organization.get_by_code(session["admin_org_code"])
    if not org:
        session.pop("admin_org_code", None)
        return redirect(url_for("admin_login"))

    # If tables not configured, redirect to table setup
    if not org.tables_configured:
        flash("Please configure tables first.", "info")
        return redirect(url_for("admin_tables"))

    client = get_client_for_org(org)
    user_fields = client.get_all_user_fields()
    record_fields = client.get_all_record_fields() if org.has_linked_records else []

    # Get date fields for confirmation feature
    date_fields = []
    if org.has_linked_records:
        field_metadata = client.get_field_metadata(org.records_table, record_fields)
        date_fields = [
            name for name, meta in field_metadata.items()
            if meta.get("type") in ("date", "dateTime")
        ]

    return render_template(
        "admin/fields.html",
        org=org,
        user_fields=user_fields,
        record_fields=record_fields,
        date_fields=date_fields,
        user_field_config=org.user_field_config,
        record_field_config=org.record_field_config,
    )


@app.route("/admin/save-fields", methods=["POST"])
@admin_required
def admin_save_fields():
    """Save field configuration."""
    org = Organization.get_by_code(session["admin_org_code"])
    if not org:
        return redirect(url_for("admin_login"))

    client = get_client_for_org(org)
    user_fields = client.get_all_user_fields()
    record_fields = client.get_all_record_fields()

    # Build user field config from form
    user_field_config = {}
    for field_name in user_fields:
        permission = request.form.get(f"user_field_{field_name}", "hidden")
        if permission in ("editable", "readonly", "hidden"):
            user_field_config[field_name] = permission

    # Build record field config from form
    record_field_config = {}
    for field_name in record_fields:
        permission = request.form.get(f"record_field_{field_name}", "editable")
        if permission in ("editable", "readonly", "hidden"):
            record_field_config[field_name] = permission

    # Save as nested structure
    org.field_config = {
        "user_fields": user_field_config,
        "record_fields": record_field_config,
    }

    # Save confirmation settings
    org.confirmation_enabled = "confirmation_enabled" in request.form
    org.confirmation_field = request.form.get("confirmation_field", "").strip() or None

    db.session.commit()

    flash("Field configuration saved.", "success")
    return redirect(url_for("admin_fields"))


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
    """Organization signup page."""
    if request.method == "POST":
        # Get form values
        name = request.form.get("name", "").strip()
        org_code = request.form.get("org_code", "").strip().upper()
        airtable_api_key = request.form.get("airtable_api_key", "").strip()
        airtable_base_id = request.form.get("airtable_base_id", "").strip()
        admin_password = request.form.get("admin_password", "").strip()
        admin_password_confirm = request.form.get("admin_password_confirm", "").strip()

        # Validation
        errors = []

        if not name:
            errors.append("Organization name is required.")

        if not org_code:
            # Auto-generate if not provided
            org_code = generate_org_code(name) if name else ""
        elif len(org_code) < 3:
            errors.append("Org code must be at least 3 characters.")
        elif Organization.query.filter_by(org_code=org_code).first():
            errors.append(f"Org code '{org_code}' is already taken.")

        if not airtable_api_key:
            errors.append("Airtable API key is required.")

        if not airtable_base_id:
            errors.append("Airtable Base ID is required.")

        if not admin_password:
            errors.append("Admin password is required.")
        elif len(admin_password) < 6:
            errors.append("Admin password must be at least 6 characters.")
        elif admin_password != admin_password_confirm:
            errors.append("Passwords do not match.")

        # If basic validation passes, test Airtable connection
        if not errors and airtable_api_key and airtable_base_id:
            is_valid, message = validate_airtable_credentials(airtable_api_key, airtable_base_id)
            if not is_valid:
                errors.append(message)

        if errors:
            for error in errors:
                flash(error, "error")
            return render_template("signup.html",
                                   name=name,
                                   org_code=org_code,
                                   airtable_base_id=airtable_base_id)

        # Create the organization
        org = Organization(
            org_code=org_code,
            name=name,
            airtable_api_key=airtable_api_key,
            airtable_base_id=airtable_base_id,
            portal_title=f"{name} Portal",
        )
        org.set_admin_password(admin_password)

        db.session.add(org)
        db.session.commit()

        # Log them into admin
        session["admin_org_code"] = org.org_code

        flash(f"Organization '{org_code}' created successfully! Now configure your tables.", "success")
        return redirect(url_for("admin_tables"))

    return render_template("signup.html", name="", org_code="", airtable_base_id="")


@app.cli.command("init-db")
def init_db():
    """Initialize the database."""
    db.create_all()
    print("Database initialized.")


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
    app.run(debug=True)
