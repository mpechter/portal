import json
from datetime import datetime, timezone
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()


class Organization(db.Model):
    """Account identity and billing for each organization."""

    __tablename__ = "organizations"

    id = db.Column(db.Integer, primary_key=True)
    org_code = db.Column(db.String(50), unique=True, nullable=False, index=True)
    name = db.Column(db.String(200), nullable=False)

    # Admin authentication
    admin_email = db.Column(db.String(255), nullable=True)
    pending_admin_email = db.Column(db.String(255), nullable=True)
    admin_password_hash = db.Column(db.String(256), nullable=True)

    # Billing / plan
    plan = db.Column(db.String(20), nullable=True)  # 'trial', 'active', 'suspended'
    trial_started_at = db.Column(db.DateTime(timezone=True), nullable=True)
    stripe_customer_id = db.Column(db.String(100), nullable=True)
    stripe_subscription_id = db.Column(db.String(100), nullable=True)
    promo_code = db.Column(db.String(100), nullable=True)
    subscription_cancel_at = db.Column(db.DateTime(timezone=True), nullable=True)

    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(
        db.DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        server_default=db.func.now(),
    )

    portal_configs = db.relationship(
        "PortalConfig",
        backref="org",
        lazy=True,
        order_by="PortalConfig.id",
        cascade="all, delete-orphan",
    )

    TRIAL_DAYS = 7

    # --- Convenience accessors ---

    @property
    def portal_config(self):
        """Return the default (first) PortalConfig for this org."""
        configs = self.portal_configs
        return configs[0] if configs else None

    def _ensure_portal_config(self):
        """Return the default PortalConfig, creating one lazily if absent."""
        if not self.portal_configs:
            config = PortalConfig()
            self.portal_configs.append(config)
        return self.portal_configs[0]

    # --- Proxy properties: Airtable connection ---

    @property
    def airtable_api_key(self):
        pc = self.portal_config
        return pc.airtable_api_key if pc else None

    @airtable_api_key.setter
    def airtable_api_key(self, value):
        self._ensure_portal_config().airtable_api_key = value

    @property
    def airtable_base_id(self):
        pc = self.portal_config
        return pc.airtable_base_id if pc else None

    @airtable_base_id.setter
    def airtable_base_id(self, value):
        self._ensure_portal_config().airtable_base_id = value

    # --- Proxy properties: table configuration ---

    @property
    def users_table(self):
        pc = self.portal_config
        return pc.users_table if pc else None

    @users_table.setter
    def users_table(self, value):
        self._ensure_portal_config().users_table = value

    @property
    def records_table(self):
        pc = self.portal_config
        return pc.records_table if pc else None

    @records_table.setter
    def records_table(self, value):
        self._ensure_portal_config().records_table = value

    @property
    def link_field(self):
        pc = self.portal_config
        return pc.link_field if pc else None

    @link_field.setter
    def link_field(self, value):
        self._ensure_portal_config().link_field = value

    @property
    def email_field(self):
        pc = self.portal_config
        return pc.email_field if pc else "Email"

    @email_field.setter
    def email_field(self, value):
        self._ensure_portal_config().email_field = value

    # --- Proxy properties: customization ---

    @property
    def portal_title(self):
        pc = self.portal_config
        return pc.portal_title if pc else "Parent Portal"

    @portal_title.setter
    def portal_title(self, value):
        self._ensure_portal_config().portal_title = value

    @property
    def logo_url(self):
        pc = self.portal_config
        return pc.logo_url if pc else None

    @logo_url.setter
    def logo_url(self, value):
        self._ensure_portal_config().logo_url = value

    # --- Proxy properties: confirmation feature ---

    @property
    def confirmation_enabled(self):
        pc = self.portal_config
        return pc.confirmation_enabled if pc else False

    @confirmation_enabled.setter
    def confirmation_enabled(self, value):
        self._ensure_portal_config().confirmation_enabled = value

    @property
    def confirmation_field(self):
        pc = self.portal_config
        return pc.confirmation_field if pc else None

    @confirmation_field.setter
    def confirmation_field(self, value):
        self._ensure_portal_config().confirmation_field = value

    @property
    def confirmation_value(self):
        pc = self.portal_config
        return pc.confirmation_value if pc else None

    @confirmation_value.setter
    def confirmation_value(self, value):
        self._ensure_portal_config().confirmation_value = value

    # --- Proxy properties: field JSON blobs ---

    @property
    def field_config(self) -> dict:
        pc = self.portal_config
        return pc.field_config if pc else {"user_fields": {}, "record_fields": {}}

    @field_config.setter
    def field_config(self, value: dict):
        self._ensure_portal_config().field_config = value

    @property
    def field_annotations(self) -> dict:
        pc = self.portal_config
        return pc.field_annotations if pc else {"user_fields": {}, "record_fields": {}}

    @field_annotations.setter
    def field_annotations(self, value: dict):
        self._ensure_portal_config().field_annotations = value

    @property
    def field_aliases(self) -> dict:
        pc = self.portal_config
        return pc.field_aliases if pc else {"user_fields": {}, "record_fields": {}}

    @field_aliases.setter
    def field_aliases(self, value: dict):
        self._ensure_portal_config().field_aliases = value

    @property
    def field_descriptions(self) -> dict:
        pc = self.portal_config
        return pc.field_descriptions if pc else {"user_fields": {}, "record_fields": {}}

    @field_descriptions.setter
    def field_descriptions(self, value: dict):
        self._ensure_portal_config().field_descriptions = value

    # --- Computed properties (unchanged — use proxies above) ---

    @property
    def trial_expired(self) -> bool:
        if self.plan != "trial":
            return False
        if self.trial_started_at is None:
            return False
        return (datetime.now(timezone.utc) - self.trial_started_at).days >= self.TRIAL_DAYS

    @property
    def trial_days_remaining(self) -> int:
        if self.plan != "trial":
            return 0
        if self.trial_started_at is None:
            return self.TRIAL_DAYS
        elapsed = (datetime.now(timezone.utc) - self.trial_started_at).days
        return max(0, self.TRIAL_DAYS - elapsed)

    def __repr__(self):
        return f"<Organization {self.org_code}: {self.name}>"

    @property
    def tables_configured(self) -> bool:
        return bool(self.users_table)

    @property
    def has_linked_records(self) -> bool:
        return bool(self.records_table)

    @classmethod
    def get_by_code(cls, org_code: str):
        return cls.query.filter_by(org_code=org_code, is_active=True).first()

    def set_admin_password(self, password: str):
        self.admin_password_hash = generate_password_hash(password)

    def check_admin_password(self, password: str) -> bool:
        if not self.admin_password_hash:
            return False
        return check_password_hash(self.admin_password_hash, password)

    # --- Field config methods (unchanged — delegate through proxy properties) ---

    @property
    def user_field_config(self) -> dict:
        return self.field_config.get("user_fields", {})

    def get_user_field_permission(self, field_name: str) -> str:
        return self.user_field_config.get(field_name, "hidden")

    def get_user_editable_fields(self) -> list:
        return [f for f, p in self.user_field_config.items() if p == "editable"]

    def get_user_readonly_fields(self) -> list:
        return [f for f, p in self.user_field_config.items() if p == "readonly"]

    def get_user_hidden_fields(self) -> list:
        return [f for f, p in self.user_field_config.items() if p == "hidden"]

    @property
    def record_field_config(self) -> dict:
        return self.field_config.get("record_fields", {})

    def get_record_field_permission(self, field_name: str) -> str:
        return self.record_field_config.get(field_name, "editable")

    def get_record_editable_fields(self) -> list:
        return [f for f, p in self.record_field_config.items() if p == "editable"]

    def get_record_readonly_fields(self) -> list:
        return [f for f, p in self.record_field_config.items() if p == "readonly"]

    def get_record_hidden_fields(self) -> list:
        return [f for f, p in self.record_field_config.items() if p == "hidden"]

    def get_user_field_annotation(self, field_name: str) -> str:
        return self.field_annotations.get("user_fields", {}).get(field_name, "")

    def get_record_field_annotation(self, field_name: str) -> str:
        return self.field_annotations.get("record_fields", {}).get(field_name, "")

    def get_user_field_alias(self, field_name: str) -> str:
        return self.field_aliases.get("user_fields", {}).get(field_name, field_name)

    def get_record_field_alias(self, field_name: str) -> str:
        return self.field_aliases.get("record_fields", {}).get(field_name, field_name)

    def get_user_field_description(self, field_name: str) -> str:
        return self.field_descriptions.get("user_fields", {}).get(field_name, "")

    def get_record_field_description(self, field_name: str) -> str:
        return self.field_descriptions.get("record_fields", {}).get(field_name, "")


class PortalConfig(db.Model):
    """Portal-specific configuration for an organization.

    One org can have multiple PortalConfigs (future: multi-portal). For now,
    each org has exactly one and Organization proxies all portal attributes here.
    """

    __tablename__ = "portal_configs"

    id = db.Column(db.Integer, primary_key=True)
    org_id = db.Column(db.Integer, db.ForeignKey("organizations.id"), nullable=False, index=True)

    # Airtable connection
    airtable_api_key = db.Column(db.String(200), nullable=True)
    airtable_base_id = db.Column(db.String(50), nullable=True)

    # Table configuration
    users_table = db.Column(db.String(100), nullable=True)
    records_table = db.Column(db.String(100), nullable=True)
    link_field = db.Column(db.String(100), nullable=True)
    email_field = db.Column(db.String(100), default="Email")

    # Customization
    portal_title = db.Column(db.String(200), default="Parent Portal")
    logo_url = db.Column(db.String(500), nullable=True)

    # Data confirmation feature
    confirmation_enabled = db.Column(db.Boolean, default=False)
    confirmation_field = db.Column(db.String(100), nullable=True)
    confirmation_value = db.Column(db.String(200), nullable=True)

    # Field permissions / annotations / aliases / descriptions (JSON blobs)
    _field_config = db.Column("field_config", db.Text, default="{}")
    _field_annotations = db.Column("field_annotations", db.Text, default="{}")
    _field_aliases = db.Column("field_aliases", db.Text, default="{}")
    _field_descriptions = db.Column("field_descriptions", db.Text, default="{}")

    created_at = db.Column(
        db.DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        server_default=db.func.now(),
    )

    @property
    def field_config(self) -> dict:
        try:
            config = json.loads(self._field_config or "{}")
            if config and "user_fields" not in config and "record_fields" not in config:
                return {"user_fields": {}, "record_fields": config}
            return config
        except json.JSONDecodeError:
            return {"user_fields": {}, "record_fields": {}}

    @field_config.setter
    def field_config(self, value: dict):
        self._field_config = json.dumps(value)

    @property
    def field_annotations(self) -> dict:
        try:
            return json.loads(self._field_annotations or "{}")
        except json.JSONDecodeError:
            return {"user_fields": {}, "record_fields": {}}

    @field_annotations.setter
    def field_annotations(self, value: dict):
        self._field_annotations = json.dumps(value)

    @property
    def field_aliases(self) -> dict:
        try:
            return json.loads(self._field_aliases or "{}")
        except json.JSONDecodeError:
            return {"user_fields": {}, "record_fields": {}}

    @field_aliases.setter
    def field_aliases(self, value: dict):
        self._field_aliases = json.dumps(value)

    @property
    def field_descriptions(self) -> dict:
        try:
            return json.loads(self._field_descriptions or "{}")
        except json.JSONDecodeError:
            return {"user_fields": {}, "record_fields": {}}

    @field_descriptions.setter
    def field_descriptions(self, value: dict):
        self._field_descriptions = json.dumps(value)

    def __repr__(self):
        return f"<PortalConfig org_id={self.org_id} base={self.airtable_base_id}>"


class PromoCode(db.Model):
    """Promo codes for activating portals without payment."""

    __tablename__ = "promo_codes"

    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(100), unique=True, nullable=False)
    active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(
        db.DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )

    @classmethod
    def get_active_codes(cls) -> set:
        return {pc.code.upper() for pc in cls.query.filter_by(active=True).all()}


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
    airtable_user_id = db.Column(db.String(50), nullable=False)
    code_hash = db.Column(db.String(256), nullable=False)
    expires_at = db.Column(db.DateTime(timezone=True), nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    @classmethod
    def create_code(cls, org_id: int, user_email: str, airtable_user_id: str, code: str, expires_at):
        user_email = user_email.lower()
        cls.query.filter_by(org_id=org_id, user_email=user_email).delete()
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
        from datetime import datetime, timezone
        user_email = user_email.lower()
        login_code = cls.query.filter_by(org_id=org_id, user_email=user_email).first()
        if not login_code:
            return None
        if datetime.now(timezone.utc) > login_code.expires_at:
            return None
        if not check_password_hash(login_code.code_hash, code):
            return None
        return login_code

    @classmethod
    def clear_code(cls, org_id: int, user_email: str):
        user_email = user_email.lower()
        cls.query.filter_by(org_id=org_id, user_email=user_email).delete()
        db.session.commit()
