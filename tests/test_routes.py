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


class TestContactBotProtection:
    """Honeypot, timing check, and rate limit on /contact."""

    def _form(self, app, age=10, **overrides):
        from unittest.mock import patch
        import time as _time
        from app import _contact_form_token
        with app.test_request_context():
            with patch("app.time.time", return_value=_time.time() - age):
                token = _contact_form_token()
        data = {"name": "Ann", "email": "ann@example.com", "message": "Hi",
                "website": "", "form_token": token}
        data.update(overrides)
        return data

    def _post(self, client, app, **kw):
        from unittest.mock import patch
        from app import limiter
        limiter.reset()
        with patch("app.send_contact_email", return_value=True) as send:
            resp = client.post("/contact", data=self._form(app, **kw))
        return resp, send

    def test_human_submission_sends(self, client, app):
        resp, send = self._post(client, app)
        assert resp.status_code == 302
        send.assert_called_once()

    def test_honeypot_filled_is_dropped(self, client, app):
        resp, send = self._post(client, app, website="http://spam.example")
        assert resp.status_code == 302
        send.assert_not_called()

    def test_too_fast_is_dropped(self, client, app):
        resp, send = self._post(client, app, age=0)
        send.assert_not_called()

    def test_missing_token_is_dropped(self, client, app):
        resp, send = self._post(client, app, form_token="")
        send.assert_not_called()

    def test_rate_limited_per_client_ip(self, client, app):
        from unittest.mock import patch
        from app import limiter
        limiter.reset()
        headers = {"Fly-Client-IP": "203.0.113.5"}
        with patch("app.send_contact_email", return_value=True):
            codes = [client.post("/contact", data=self._form(app), headers=headers).status_code
                     for _ in range(6)]
        assert codes[:5] == [302] * 5
        assert codes[5] == 429
        # A different client is unaffected.
        with patch("app.send_contact_email", return_value=True):
            other = client.post("/contact", data=self._form(app),
                                headers={"Fly-Client-IP": "203.0.113.9"})
        assert other.status_code == 302

    def test_form_renders_honeypot_and_token(self, client):
        html = client.get("/contact").get_data(as_text=True)
        assert 'name="website"' in html
        assert 'name="form_token"' in html
