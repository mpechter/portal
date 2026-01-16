"""Tests for database models."""

import pytest
from models import Organization, db


class TestOrganization:
    """Tests for the Organization model."""

    def test_create_organization(self, app):
        """Should be able to create an organization."""
        with app.app_context():
            org = Organization(
                org_code="TESTORG",
                name="Test Org",
                airtable_api_key="key123",
                airtable_base_id="base123",
            )
            db.session.add(org)
            db.session.commit()

            assert org.id is not None
            assert org.org_code == "TESTORG"

    def test_get_by_code(self, app, demo_org):
        """Should find organization by code."""
        with app.app_context():
            found = Organization.get_by_code("TEST")
            assert found is not None
            assert found.name == "Test Organization"

    def test_get_by_code_is_case_sensitive(self, app, demo_org):
        """Organization lookup is case-sensitive (routes handle normalization)."""
        with app.app_context():
            # Model itself is case-sensitive
            found_lower = Organization.get_by_code("test")
            found_upper = Organization.get_by_code("TEST")
            assert found_lower is None  # lowercase not found
            assert found_upper is not None  # uppercase found

    def test_get_by_code_not_found(self, app):
        """Should return None for non-existent org code."""
        with app.app_context():
            found = Organization.get_by_code("NONEXISTENT")
            assert found is None


class TestOrganizationPassword:
    """Tests for organization admin password."""

    def test_set_admin_password(self, app):
        """Should be able to set admin password."""
        with app.app_context():
            org = Organization(
                org_code="PWTEST",
                name="Password Test",
                airtable_api_key="key",
                airtable_base_id="base",
            )
            org.set_admin_password("secret123")
            db.session.add(org)
            db.session.commit()

            assert org.admin_password_hash is not None
            assert org.admin_password_hash != "secret123"

    def test_check_admin_password_correct(self, app, demo_org):
        """Should return True for correct password."""
        with app.app_context():
            org = Organization.get_by_code("TEST")
            assert org.check_admin_password("admin123") is True

    def test_check_admin_password_incorrect(self, app, demo_org):
        """Should return False for incorrect password."""
        with app.app_context():
            org = Organization.get_by_code("TEST")
            assert org.check_admin_password("wrongpassword") is False


class TestOrganizationFieldConfig:
    """Tests for organization field configuration."""

    def test_default_field_config(self, app):
        """New organization should have empty field config."""
        with app.app_context():
            org = Organization(
                org_code="FIELDTEST",
                name="Field Test",
                airtable_api_key="key",
                airtable_base_id="base",
            )
            assert org.user_field_config == {}
            assert org.record_field_config == {}

    def test_set_user_field_config(self, app):
        """Should be able to set user field config."""
        with app.app_context():
            org = Organization(
                org_code="FIELDTEST",
                name="Field Test",
                airtable_api_key="key",
                airtable_base_id="base",
            )
            org.field_config = {
                "user_fields": {"Name": "editable", "Email": "readonly"},
                "record_fields": {},
            }
            db.session.add(org)
            db.session.commit()

            assert org.user_field_config == {"Name": "editable", "Email": "readonly"}

    def test_get_user_editable_fields(self, app):
        """Should return list of editable user fields."""
        with app.app_context():
            org = Organization(
                org_code="FIELDTEST",
                name="Field Test",
                airtable_api_key="key",
                airtable_base_id="base",
            )
            org.field_config = {
                "user_fields": {
                    "Name": "editable",
                    "Phone": "editable",
                    "Email": "readonly",
                    "Secret": "hidden",
                },
                "record_fields": {},
            }
            db.session.add(org)
            db.session.commit()

            editable = org.get_user_editable_fields()
            assert "Name" in editable
            assert "Phone" in editable
            assert "Email" not in editable
            assert "Secret" not in editable

    def test_get_user_readonly_fields(self, app):
        """Should return list of readonly user fields."""
        with app.app_context():
            org = Organization(
                org_code="FIELDTEST",
                name="Field Test",
                airtable_api_key="key",
                airtable_base_id="base",
            )
            org.field_config = {
                "user_fields": {
                    "Name": "editable",
                    "Email": "readonly",
                    "ID": "readonly",
                },
                "record_fields": {},
            }
            db.session.add(org)
            db.session.commit()

            readonly = org.get_user_readonly_fields()
            assert "Email" in readonly
            assert "ID" in readonly
            assert "Name" not in readonly


class TestOrganizationTableConfig:
    """Tests for organization table configuration."""

    def test_tables_configured_false_when_no_users_table(self, app):
        """tables_configured should be False when users_table is not set."""
        with app.app_context():
            org = Organization(
                org_code="TABLETEST",
                name="Table Test",
                airtable_api_key="key",
                airtable_base_id="base",
            )
            assert org.tables_configured is False

    def test_tables_configured_true_when_users_table_set(self, app):
        """tables_configured should be True when users_table is set."""
        with app.app_context():
            org = Organization(
                org_code="TABLETEST",
                name="Table Test",
                airtable_api_key="key",
                airtable_base_id="base",
                users_table="Users",
            )
            assert org.tables_configured is True

    def test_has_linked_records_false_when_not_configured(self, app):
        """has_linked_records should be False when not configured."""
        with app.app_context():
            org = Organization(
                org_code="TABLETEST",
                name="Table Test",
                airtable_api_key="key",
                airtable_base_id="base",
                users_table="Users",
            )
            assert org.has_linked_records is False

    def test_has_linked_records_true_when_configured(self, app, demo_org):
        """has_linked_records should be True when both records_table and link_field set."""
        with app.app_context():
            org = Organization.get_by_code("TEST")
            assert org.has_linked_records is True
