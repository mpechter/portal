"""Pytest fixtures for Portal tests."""

import os
import sys
import pytest
import tempfile

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Set test environment before importing app
os.environ["DEMO_MODE"] = "true"
os.environ["SECRET_KEY"] = "test-secret-key"

from app import app as flask_app, db
from models import Organization, PortalConfig


@pytest.fixture
def app():
    """Create application for testing."""
    # Use a temporary database
    db_fd, db_path = tempfile.mkstemp()
    flask_app.config.update({
        "TESTING": True,
        "SQLALCHEMY_DATABASE_URI": f"sqlite:///{db_path}",
        "WTF_CSRF_ENABLED": False,
        "SECRET_KEY": "test-secret-key",
    })

    with flask_app.app_context():
        db.create_all()
        yield flask_app
        db.drop_all()

    os.close(db_fd)
    os.unlink(db_path)


@pytest.fixture
def client(app):
    """Create test client."""
    return app.test_client()


@pytest.fixture
def runner(app):
    """Create CLI runner."""
    return app.test_cli_runner()


@pytest.fixture
def demo_org(app):
    """Create a demo organization for testing."""
    with app.app_context():
        org = Organization(org_code="TEST", name="Test Organization")
        org.portal_configs.append(PortalConfig(
            airtable_api_key="fake_key",
            airtable_base_id="fake_base",
            portal_title="Test Portal",
            users_table="Parents",
            records_table="Students",
            link_field="Students",
        ))
        org.set_admin_password("admin123")
        db.session.add(org)
        db.session.commit()

        # Refresh to get the ID
        db.session.refresh(org)
        yield org
