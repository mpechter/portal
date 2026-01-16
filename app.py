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
        if send_login_code(org, email, user["id"]):
            # Store org_code and email in session for code verification
            session["pending_org_code"] = org_code
            session["pending_email"] = email
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

    if request.method == "POST":
        code = request.form.get("code", "").strip()

        # Check lockout
        if is_locked_out(email):
            remaining = get_lockout_remaining(email)
            flash(f"Too many failed attempts. Try again in {remaining // 60} minutes.", "error")
            return render_template("verify_code.html", email=email, org=org)

        # Verify the code
        user_data = verify_login_code(org, email, code)
        if not user_data:
            flash("Invalid or expired code. Please try again.", "error")
            return render_template("verify_code.html", email=email, org=org)

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
        session["org_code"] = org.org_code

        return redirect(url_for("dashboard"))

    return render_template("verify_code.html", email=email, org=org)


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

    # Get field permissions for user profile
    user_editable_fields = org.get_user_editable_fields()
    user_readonly_fields = org.get_user_readonly_fields()
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

        if updates:
            client.update_record(record_id, updates)
            flash("Changes saved successfully.", "success")

        return redirect(url_for("edit_record", record_id=record_id))

    return render_template(
        "edit_record.html",
        record=record,
        editable_fields=editable_fields,
        readonly_fields=readonly_fields,
        field_metadata=field_metadata,
        org=org,
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

    # Get field permissions for user profile
    editable_fields = org.get_user_editable_fields()
    readonly_fields = org.get_user_readonly_fields()

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

    # Get linked fields for the selected users table
    linked_fields = []
    if org.users_table:
        users_table_info = client.get_table_by_name(org.users_table)
        if users_table_info:
            linked_fields = users_table_info.get("linked_fields", [])
            # Resolve linked table names
            for field in linked_fields:
                linked_table_id = field.get("linked_table_id")
                if linked_table_id:
                    for table in tables:
                        if table["id"] == linked_table_id:
                            field["linked_table_name"] = table["name"]
                            break

    return render_template(
        "admin/tables.html",
        org=org,
        tables=tables,
        linked_fields=linked_fields,
    )


@app.route("/admin/save-tables", methods=["POST"])
@admin_required
def admin_save_tables():
    """Save table configuration."""
    org = Organization.get_by_code(session["admin_org_code"])
    if not org:
        return redirect(url_for("admin_login"))

    users_table = request.form.get("users_table", "").strip()
    link_field = request.form.get("link_field", "").strip()

    if not users_table:
        flash("Please select a Users table.", "error")
        return redirect(url_for("admin_tables"))

    # Get the linked table name from the link field
    records_table = None
    if link_field:
        client = get_client_for_org(org)
        # Temporarily set users_table to get its schema
        org.users_table = users_table
        users_table_info = client.get_table_by_name(users_table)
        if users_table_info:
            for field in users_table_info.get("linked_fields", []):
                if field["name"] == link_field:
                    linked_table_id = field.get("linked_table_id")
                    if linked_table_id:
                        tables = client.get_base_tables()
                        for table in tables:
                            if table["id"] == linked_table_id:
                                records_table = table["name"]
                                break
                    break

    org.users_table = users_table
    org.link_field = link_field if link_field else None
    org.records_table = records_table

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

    return render_template(
        "admin/fields.html",
        org=org,
        user_fields=user_fields,
        record_fields=record_fields,
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
    db.session.commit()

    flash("Field configuration saved.", "success")
    return redirect(url_for("admin_fields"))


# --- CLI Commands ---


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
