"""Tests for webhook notifications."""

from tests.conftest import _setup


def test_create_webhook(client):
    _setup(client)
    resp = client.post("/api/webhooks", json={
        "url": "https://example.com/hook",
        "events": ["translation.updated"],
    })
    assert resp.status_code == 201
    assert resp.json()["url"] == "https://example.com/hook"


def test_list_webhooks(client):
    _setup(client)
    client.post("/api/webhooks", json={
        "url": "https://example.com/hook1",
        "events": ["translation.updated"],
    })
    client.post("/api/webhooks", json={
        "url": "https://example.com/hook2",
        "events": ["key.created"],
    })
    resp = client.get("/api/webhooks")
    assert len(resp.json()) == 2


def test_update_webhook(client):
    _setup(client)
    client.post("/api/webhooks", json={
        "url": "https://example.com/hook",
        "events": ["translation.updated"],
    })
    resp = client.put("/api/webhooks/1", json={
        "events": ["translation.updated", "key.created"],
    })
    assert resp.status_code == 200
    assert len(resp.json()["events"]) == 2


def test_delete_webhook(client):
    _setup(client)
    client.post("/api/webhooks", json={
        "url": "https://example.com/hook",
        "events": ["translation.updated"],
    })
    resp = client.delete("/api/webhooks/1")
    assert resp.status_code == 204
    resp = client.get("/api/webhooks")
    assert len(resp.json()) == 0


def test_webhook_delivery_log(client):
    _setup(client)
    client.post("/api/webhooks", json={
        "url": "https://example.com/hook",
        "events": ["translation.updated"],
    })
    resp = client.get("/api/webhooks/1/deliveries")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_webhook_with_secret(client):
    _setup(client)
    resp = client.post("/api/webhooks", json={
        "url": "https://example.com/hook",
        "events": ["translation.updated"],
        "secret": "my-secret",
    })
    assert resp.status_code == 201
    assert resp.json()["secret"] == "***"


def test_webhook_project_filter(client):
    _setup(client)
    client.post("/api/webhooks", json={
        "url": "https://example.com/hook1",
        "events": ["translation.updated"],
        "project_id": 1,
    })
    client.post("/api/webhooks", json={
        "url": "https://example.com/hook2",
        "events": ["key.created"],
    })
    resp = client.get("/api/webhooks?project_id=1")
    assert len(resp.json()) == 1


def test_get_webhook(client):
    _setup(client)
    client.post("/api/webhooks", json={
        "url": "https://example.com/hook",
        "events": ["translation.updated"],
    })
    resp = client.get("/api/webhooks/1")
    assert resp.status_code == 200
    assert resp.json()["url"] == "https://example.com/hook"


def test_webhook_not_found(client):
    resp = client.get("/api/webhooks/999")
    assert resp.status_code == 404
