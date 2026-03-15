"""Tests for machine translation integration."""

from unittest.mock import MagicMock, patch

from tests.conftest import _setup
from flintstone.config import settings


def test_mt_config_no_backends(client):
    resp = client.get("/api/mt/config")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data["available_backends"], list)
    assert isinstance(data["backends"], dict)


def test_mt_config_with_backend(client):
    original = settings.mt_google_api_key
    settings.mt_google_api_key = "test-key"
    try:
        resp = client.get("/api/mt/config")
        data = resp.json()
        assert data["backends"]["google"] is True
        assert "google" in data["available_backends"]
    finally:
        settings.mt_google_api_key = original


def test_mt_translate_no_backend(client):
    resp = client.post("/api/mt/translate", json={
        "source_lang": "en",
        "target_lang": "es",
        "texts": ["Hello"],
    })
    assert resp.status_code == 400


def test_mt_translate_with_mock(client):
    _setup(client)

    with patch("flintstone.api.mt.get_backend") as mock_get:
        mock_backend = type("MockBackend", (), {
            "name": "mock",
            "translate": lambda self, texts, sl, tl: ["Hola" for _ in texts],
        })()
        mock_get.return_value = mock_backend

        resp = client.post("/api/mt/translate", json={
            "source_lang": "en",
            "target_lang": "es",
            "texts": ["Hello"],
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["translations"] == ["Hola"]
        assert data["backend"] == "mock"
        assert data["character_count"] == 5


def test_mt_pre_translate_with_mock(client):
    _setup(client)
    client.post("/api/projects/1/keys", json={"key": "greeting"})
    client.put("/api/translations/1/1", json={"value": "Hello"})

    with patch("flintstone.api.mt.get_backend") as mock_get:
        mock_backend = type("MockBackend", (), {
            "name": "mock",
            "translate": lambda self, texts, sl, tl: ["Hola" for _ in texts],
        })()
        mock_get.return_value = mock_backend

        resp = client.post("/api/projects/1/mt/pre-translate", json={
            "source_lang": "en",
            "target_lang": "es",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["translated"] == 1
        assert data["backend"] == "mock"


def test_mt_pre_translate_no_overwrite(client):
    _setup(client)
    client.post("/api/projects/1/keys", json={"key": "greeting"})
    client.put("/api/translations/1/1", json={"value": "Hello"})
    client.put("/api/translations/1/2", json={"value": "Existing"})

    with patch("flintstone.api.mt.get_backend") as mock_get:
        mock_backend = type("MockBackend", (), {
            "name": "mock",
            "translate": lambda self, texts, sl, tl: ["Hola" for _ in texts],
        })()
        mock_get.return_value = mock_backend

        resp = client.post("/api/projects/1/mt/pre-translate", json={
            "source_lang": "en",
            "target_lang": "es",
            "overwrite": False,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["translated"] == 0  # existing translation not overwritten


def test_mt_pre_translate_overwrite(client):
    _setup(client)
    client.post("/api/projects/1/keys", json={"key": "greeting"})
    client.put("/api/translations/1/1", json={"value": "Hello"})
    client.put("/api/translations/1/2", json={"value": "Existing"})

    with patch("flintstone.api.mt.get_backend") as mock_get:
        mock_backend = type("MockBackend", (), {
            "name": "mock",
            "translate": lambda self, texts, sl, tl: ["Hola" for _ in texts],
        })()
        mock_get.return_value = mock_backend

        resp = client.post("/api/projects/1/mt/pre-translate", json={
            "source_lang": "en",
            "target_lang": "es",
            "overwrite": True,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["translated"] == 1  # overwritten


def test_mt_usage(client):
    _setup(client)
    resp = client.get("/api/mt/usage")
    assert resp.status_code == 200
    data = resp.json()
    assert "total_character_count" in data
    assert "by_backend" in data


def test_mt_project_not_found(client):
    with patch("flintstone.api.mt.get_backend") as mock_get:
        mock_backend = type("MockBackend", (), {
            "name": "mock",
            "translate": lambda self, texts, sl, tl: texts,
        })()
        mock_get.return_value = mock_backend

        resp = client.post("/api/projects/999/mt/pre-translate", json={
            "source_lang": "en",
            "target_lang": "es",
        })
        assert resp.status_code == 404
