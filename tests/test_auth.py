"""Tests for authentication."""

import pytest
from flintstone.auth import _sign_key, verify_key
from flintstone.config import settings


def _enable_auth():
    """Temporarily enable auth for testing."""
    settings.auth_keys = ["test-key-123", "test-key-456"]


def _disable_auth():
    """Disable auth."""
    settings.auth_keys = []


@pytest.fixture(autouse=True)
def cleanup_auth():
    yield
    _disable_auth()


def test_api_accessible_without_auth_when_disabled(client):
    _disable_auth()
    resp = client.post("/api/projects", json={"name": "No Auth"})
    assert resp.status_code == 201


def test_api_returns_401_when_auth_enabled_and_no_key(client):
    _enable_auth()
    resp = client.get("/api/projects")
    assert resp.status_code == 401


def test_api_returns_200_with_valid_key(client):
    _enable_auth()
    resp = client.get("/api/projects", headers={"Authorization": "Bearer test-key-123"})
    assert resp.status_code == 200


def test_api_returns_401_with_invalid_key(client):
    _enable_auth()
    resp = client.get("/api/projects", headers={"Authorization": "Bearer wrong-key"})
    assert resp.status_code == 401


def test_login_page_renders(client):
    _enable_auth()
    resp = client.get("/login")
    assert resp.status_code == 200
    assert "Login" in resp.text


def test_login_sets_cookie(client):
    _enable_auth()
    resp = client.post("/login", data={"api_key": "test-key-123"}, follow_redirects=False)
    assert resp.status_code == 303
    assert settings.auth_cookie_name in resp.cookies


def test_login_rejects_invalid_key(client):
    _enable_auth()
    resp = client.post("/login", data={"api_key": "wrong-key"})
    assert resp.status_code == 200
    assert "Invalid" in resp.text


def test_ui_accessible_with_valid_cookie(client):
    _enable_auth()
    # First login to get cookie
    resp = client.post("/login", data={"api_key": "test-key-123"}, follow_redirects=False)
    cookie_value = resp.cookies[settings.auth_cookie_name]
    # Then access dashboard with cookie
    resp = client.get("/", cookies={settings.auth_cookie_name: cookie_value})
    assert resp.status_code == 200


def test_verify_key():
    _enable_auth()
    assert verify_key("test-key-123") is True
    assert verify_key("wrong") is False
