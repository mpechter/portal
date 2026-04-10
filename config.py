import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-change-me")
    APP_URL = os.environ.get("APP_URL", "http://localhost:5000")

    # Demo mode - uses mock data instead of real Airtable
    DEMO_MODE = os.environ.get("DEMO_MODE", "false").lower() == "true"

    # Database - supports PostgreSQL (production) or SQLite (development)
    # Some platforms use postgres:// but SQLAlchemy needs postgresql://
    _database_url = os.environ.get("DATABASE_URL", "sqlite:///portal.db")
    if _database_url.startswith("postgres://"):
        _database_url = _database_url.replace("postgres://", "postgresql://", 1)
    SQLALCHEMY_DATABASE_URI = _database_url
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Magic link expiry in minutes
    TOKEN_EXPIRY_MINUTES = 15

    # Resend email API
    RESEND_API_KEY = os.environ.get("RESEND_API_KEY")
    EMAIL_FROM = os.environ.get("EMAIL_FROM", "onboarding@resend.dev")

    # Stripe billing
    STRIPE_SECRET_KEY = os.environ.get("STRIPE_SECRET_KEY")
    STRIPE_PUBLISHABLE_KEY = os.environ.get("STRIPE_PUBLISHABLE_KEY")
    STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET")
    STRIPE_PRICE_ID = os.environ.get("STRIPE_PRICE_ID")  # Price ID for the base plan

    # Comma-separated list of valid promo codes
    PROMO_CODES = os.environ.get("PROMO_CODES", "")

    # Superadmin dashboard password (internal use only)
    SUPERADMIN_PASSWORD = os.environ.get("SUPERADMIN_PASSWORD")
