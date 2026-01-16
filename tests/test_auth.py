"""Tests for authentication functions."""

import pytest
from auth import (
    generate_login_code,
    is_locked_out,
    record_failed_attempt,
    clear_failed_attempts,
    get_lockout_remaining,
)


class TestLoginCodeGeneration:
    """Tests for login code generation."""

    def test_generate_login_code_length(self):
        """Login code should be 6 digits."""
        code = generate_login_code()
        assert len(code) == 6

    def test_generate_login_code_is_numeric(self):
        """Login code should be all digits."""
        code = generate_login_code()
        assert code.isdigit()

    def test_generate_login_code_uniqueness(self):
        """Multiple codes should generally be different."""
        codes = [generate_login_code() for _ in range(10)]
        # At least some should be unique (probabilistic)
        assert len(set(codes)) > 1


class TestRateLimiting:
    """Tests for rate limiting on failed login attempts."""

    def setup_method(self):
        """Clear rate limit state before each test."""
        clear_failed_attempts("test@example.com")

    def test_not_locked_out_initially(self):
        """User should not be locked out with no failed attempts."""
        assert is_locked_out("test@example.com") is False

    def test_not_locked_out_after_few_attempts(self):
        """User should not be locked out after 4 failed attempts."""
        for _ in range(4):
            record_failed_attempt("test@example.com")
        assert is_locked_out("test@example.com") is False

    def test_locked_out_after_five_attempts(self):
        """User should be locked out after 5 failed attempts."""
        for _ in range(5):
            record_failed_attempt("test@example.com")
        assert is_locked_out("test@example.com") is True

    def test_lockout_remaining_is_positive(self):
        """Lockout remaining time should be positive when locked out."""
        for _ in range(5):
            record_failed_attempt("test@example.com")
        remaining = get_lockout_remaining("test@example.com")
        assert remaining > 0

    def test_clear_failed_attempts(self):
        """Clearing failed attempts should reset lockout."""
        for _ in range(5):
            record_failed_attempt("test@example.com")
        assert is_locked_out("test@example.com") is True

        clear_failed_attempts("test@example.com")
        assert is_locked_out("test@example.com") is False

    def test_email_case_insensitive(self):
        """Rate limiting should be case-insensitive for emails."""
        for _ in range(5):
            record_failed_attempt("Test@Example.com")
        assert is_locked_out("test@example.com") is True
