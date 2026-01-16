"""Tests for Flask routes."""

import pytest


class TestPublicRoutes:
    """Tests for public (unauthenticated) routes."""

    def test_index_page(self, client):
        """Index page should load successfully."""
        response = client.get("/")
        assert response.status_code == 200
        assert b"Portal" in response.data

    def test_login_page(self, client):
        """Login page should load successfully."""
        response = client.get("/login")
        assert response.status_code == 200

    def test_login_with_org_code_param(self, client):
        """Login page should accept org code as query param."""
        response = client.get("/login?org=DEMO")
        assert response.status_code == 200

    def test_admin_login_page(self, client):
        """Admin login page should load successfully."""
        response = client.get("/admin/login")
        assert response.status_code == 200


class TestLoginFlow:
    """Tests for the login flow."""

    def test_login_with_invalid_org(self, client):
        """Login with invalid org code should show error."""
        response = client.post("/login", data={
            "org_code": "INVALID",
            "email": "test@example.com",
        })
        assert response.status_code == 200
        assert b"Organization not found" in response.data

    def test_login_with_valid_org_invalid_email(self, client, demo_org):
        """Login with valid org but invalid email should show error."""
        response = client.post("/login", data={
            "org_code": "TEST",
            "email": "nonexistent@example.com",
        })
        assert response.status_code == 200
        assert b"Email not found" in response.data

    def test_login_with_valid_credentials(self, client, demo_org):
        """Login with valid org and email should redirect to verify."""
        response = client.post("/login", data={
            "org_code": "TEST",
            "email": "parent@example.com",
        }, follow_redirects=False)
        assert response.status_code == 302
        assert "/verify" in response.location


class TestProtectedRoutes:
    """Tests for protected routes that require authentication."""

    def test_dashboard_redirects_when_not_logged_in(self, client):
        """Dashboard should redirect to login when not authenticated."""
        response = client.get("/dashboard", follow_redirects=False)
        assert response.status_code == 302

    def test_profile_redirects_when_not_logged_in(self, client):
        """Profile should redirect to login when not authenticated."""
        response = client.get("/profile", follow_redirects=False)
        assert response.status_code == 302


class TestAdminRoutes:
    """Tests for admin routes."""

    def test_admin_dashboard_redirects_when_not_logged_in(self, client):
        """Admin dashboard should redirect to login when not authenticated."""
        response = client.get("/admin", follow_redirects=False)
        assert response.status_code == 302
        assert "/admin/login" in response.location

    def test_admin_login_with_invalid_org(self, client):
        """Admin login with invalid org should show error."""
        response = client.post("/admin/login", data={
            "org_code": "INVALID",
            "password": "admin123",
        })
        assert response.status_code == 200
        assert b"Organization not found" in response.data

    def test_admin_login_with_wrong_password(self, client, demo_org):
        """Admin login with wrong password should show error."""
        response = client.post("/admin/login", data={
            "org_code": "TEST",
            "password": "wrongpassword",
        })
        assert response.status_code == 200
        assert b"Invalid password" in response.data

    def test_admin_login_success(self, client, demo_org):
        """Admin login with valid credentials should redirect."""
        response = client.post("/admin/login", data={
            "org_code": "TEST",
            "password": "admin123",
        }, follow_redirects=False)
        assert response.status_code == 302
        assert "/admin" in response.location

    def test_admin_logout(self, client, demo_org):
        """Admin logout should redirect to login."""
        # First login
        client.post("/admin/login", data={
            "org_code": "TEST",
            "password": "admin123",
        })
        # Then logout
        response = client.get("/admin/logout", follow_redirects=False)
        assert response.status_code == 302
        assert "/admin/login" in response.location
