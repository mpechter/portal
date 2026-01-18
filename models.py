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

    # Data confirmation feature - updates a date field when user confirms data is current
    confirmation_enabled = db.Column(db.Boolean, default=False)
    confirmation_field = db.Column(db.String(100), nullable=True)  # Field name to update with current date

    # Admin authentication
    admin_password_hash = db.Column(db.String(256), nullable=True)

    # Field permissions stored as JSON with structure:
    # {"user_fields": {"Name": "readonly", ...}, "record_fields": {"Grade": "editable", ...}}
    # Values: "editable", "readonly", "hidden"
    _field_config = db.Column("field_config", db.Text, default="{}")

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
