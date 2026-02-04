import json
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()


class Organization(db.Model):
    """Stores configuration for each organization using the portal."""

    __tablename__ = "organizations"

    id = db.Column(db.Integer, primary_key=True)
    org_code = db.Column(db.String(50), unique=True, nullable=False, index=True)
    name = db.Column(db.String(200), nullable=False)

    # Airtable configuration
    airtable_api_key = db.Column(db.String(200), nullable=False)
    airtable_base_id = db.Column(db.String(50), nullable=False)

    # Table configuration (set by admin)
    users_table = db.Column(db.String(100), nullable=True)  # The "parent" table (users log in here)
    records_table = db.Column(db.String(100), nullable=True)  # The "child" table (optional linked records)
    link_field = db.Column(db.String(100), nullable=True)  # Field name in users_table that links to records

    # Customization
    portal_title = db.Column(db.String(200), default="Parent Portal")
    logo_url = db.Column(db.String(500), nullable=True)  # URL to organization logo

    # Data confirmation feature - sets a single select field to a specific value when user confirms
    confirmation_enabled = db.Column(db.Boolean, default=False)
    confirmation_field = db.Column(db.String(100), nullable=True)  # Single select field name
    confirmation_value = db.Column(db.String(200), nullable=True)  # Value to set when confirmed

    # Admin authentication
    admin_password_hash = db.Column(db.String(256), nullable=True)

    # Field permissions stored as JSON with structure:
    # {"user_fields": {"Name": "readonly", ...}, "record_fields": {"Grade": "editable", ...}}
    # Values: "editable", "readonly", "hidden"
    _field_config = db.Column("field_config", db.Text, default="{}")

    # Field annotations stored as JSON with structure:
    # {"user_fields": {"Name": "Your full name", ...}, "record_fields": {"Grade": "Nivel escolar", ...}}
    _field_annotations = db.Column("field_annotations", db.Text, default="{}")

    is_active = db.Column(db.Boolean, default=True)

    def __repr__(self):
        return f"<Organization {self.org_code}: {self.name}>"

    @property
    def tables_configured(self) -> bool:
        """Check if the users table has been configured."""
        return bool(self.users_table)

    @property
    def has_linked_records(self) -> bool:
        """Check if linked records (child table) are configured."""
        # link_field can be auto-detected, so just check if records_table is set
        return bool(self.records_table)

    @classmethod
    def get_by_code(cls, org_code: str):
        """Find an organization by its code."""
        return cls.query.filter_by(org_code=org_code, is_active=True).first()

    def set_admin_password(self, password: str):
        """Set the admin password (hashed)."""
        self.admin_password_hash = generate_password_hash(password)

    def check_admin_password(self, password: str) -> bool:
        """Verify the admin password."""
        if not self.admin_password_hash:
            return False
        return check_password_hash(self.admin_password_hash, password)

    @property
    def field_config(self) -> dict:
        """Get full field configuration as a dict."""
        try:
            config = json.loads(self._field_config or "{}")
            # Handle migration from old flat format to new nested format
            if config and "user_fields" not in config and "record_fields" not in config:
                # Old format - migrate to new format (treat as record_fields)
                return {"user_fields": {}, "record_fields": config}
            return config
        except json.JSONDecodeError:
            return {"user_fields": {}, "record_fields": {}}

    @field_config.setter
    def field_config(self, value: dict):
        """Set field configuration from a dict."""
        self._field_config = json.dumps(value)

    # User fields (the logged-in user's own record)
    @property
    def user_field_config(self) -> dict:
        """Get field config for user's own record."""
        return self.field_config.get("user_fields", {})

    def get_user_field_permission(self, field_name: str) -> str:
        """Get permission for a user field. Defaults to 'hidden' if not set."""
        return self.user_field_config.get(field_name, "hidden")

    def get_user_editable_fields(self) -> list:
        """Get list of user fields that are editable."""
        return [f for f, p in self.user_field_config.items() if p == "editable"]

    def get_user_readonly_fields(self) -> list:
        """Get list of user fields that are read-only."""
        return [f for f, p in self.user_field_config.items() if p == "readonly"]

    def get_user_hidden_fields(self) -> list:
        """Get list of user fields that are hidden."""
        return [f for f, p in self.user_field_config.items() if p == "hidden"]

    # Record fields (linked records like students)
    @property
    def record_field_config(self) -> dict:
        """Get field config for linked records."""
        return self.field_config.get("record_fields", {})

    def get_record_field_permission(self, field_name: str) -> str:
        """Get permission for a record field. Defaults to 'editable' if not set."""
        return self.record_field_config.get(field_name, "editable")

    def get_record_editable_fields(self) -> list:
        """Get list of record fields that are editable."""
        return [f for f, p in self.record_field_config.items() if p == "editable"]

    def get_record_readonly_fields(self) -> list:
        """Get list of record fields that are read-only."""
        return [f for f, p in self.record_field_config.items() if p == "readonly"]

    def get_record_hidden_fields(self) -> list:
        """Get list of record fields that are hidden."""
        return [f for f, p in self.record_field_config.items() if p == "hidden"]

    # Field annotations
    @property
    def field_annotations(self) -> dict:
        """Get full field annotations as a dict."""
        try:
            return json.loads(self._field_annotations or "{}")
        except json.JSONDecodeError:
            return {"user_fields": {}, "record_fields": {}}

    @field_annotations.setter
    def field_annotations(self, value: dict):
        """Set field annotations from a dict."""
        self._field_annotations = json.dumps(value)

    def get_user_field_annotation(self, field_name: str) -> str:
        """Get annotation for a user field. Returns empty string if not set."""
        return self.field_annotations.get("user_fields", {}).get(field_name, "")

    def get_record_field_annotation(self, field_name: str) -> str:
        """Get annotation for a record field. Returns empty string if not set."""
        return self.field_annotations.get("record_fields", {}).get(field_name, "")


class LoginAttempt(db.Model):
    """Tracks failed login attempts for rate limiting."""

    __tablename__ = "login_attempts"

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), nullable=False, index=True)
    org_id = db.Column(db.Integer, db.ForeignKey("organizations.id"), nullable=False)
    failed_count = db.Column(db.Integer, default=0)
    lockout_until = db.Column(db.DateTime(timezone=True), nullable=True)

    @classmethod
    def get_or_create(cls, email: str, org_id: int):
        """Get existing record or create new one."""
        email = email.lower()
        attempt = cls.query.filter_by(email=email, org_id=org_id).first()
        if not attempt:
            attempt = cls(email=email, org_id=org_id, failed_count=0)
            db.session.add(attempt)
        return attempt


class LoginCode(db.Model):
    """Stores hashed login codes in Postgres instead of Airtable."""

    __tablename__ = "login_codes"

    id = db.Column(db.Integer, primary_key=True)
    org_id = db.Column(db.Integer, db.ForeignKey("organizations.id"), nullable=False)
    user_email = db.Column(db.String(255), nullable=False, index=True)
    airtable_user_id = db.Column(db.String(50), nullable=False)  # Reference to Airtable record
    code_hash = db.Column(db.String(256), nullable=False)
    expires_at = db.Column(db.DateTime(timezone=True), nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: __import__('datetime').datetime.now(__import__('datetime').timezone.utc))

    @classmethod
    def create_code(cls, org_id: int, user_email: str, airtable_user_id: str, code: str, expires_at):
        """Create a new login code, replacing any existing one for this user."""
        user_email = user_email.lower()
        # Delete any existing codes for this user
        cls.query.filter_by(org_id=org_id, user_email=user_email).delete()

        # Create new code with hashed value
        login_code = cls(
            org_id=org_id,
            user_email=user_email,
            airtable_user_id=airtable_user_id,
            code_hash=generate_password_hash(code),
            expires_at=expires_at,
        )
        db.session.add(login_code)
        db.session.commit()
        return login_code

    @classmethod
    def verify_code(cls, org_id: int, user_email: str, code: str):
        """Verify a code and return the LoginCode record if valid."""
        from datetime import datetime, timezone
        user_email = user_email.lower()
        login_code = cls.query.filter_by(org_id=org_id, user_email=user_email).first()

        if not login_code:
            return None

        # Check expiry
        if datetime.now(timezone.utc) > login_code.expires_at:
            return None

        # Check code hash
        if not check_password_hash(login_code.code_hash, code):
            return None

        return login_code

    @classmethod
    def clear_code(cls, org_id: int, user_email: str):
        """Delete the login code after successful login."""
        user_email = user_email.lower()
        cls.query.filter_by(org_id=org_id, user_email=user_email).delete()
        db.session.commit()
