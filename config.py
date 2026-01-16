import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-change-me")
    APP_URL = os.environ.get("APP_URL", "http://localhost:5000")

    # Demo mode - uses mock data instead of real Airtable
    DEMO_MODE = os.environ.get("DEMO_MODE", "false").lower() == "true"

    # SQLite database for org configurations
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL", "sqlite:///portal.db"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Magic link expiry in minutes
    TOKEN_EXPIRY_MINUTES = 15
