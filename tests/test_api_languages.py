"""Tests for Languages API."""


def test_create_language(client):
    res = client.post("/api/languages", json={"code": "en", "name": "English"})
    assert res.status_code == 201
    assert res.json()["code"] == "en"


def test_create_duplicate_language(client):
    client.post("/api/languages", json={"code": "fr", "name": "French"})
    res = client.post("/api/languages", json={"code": "fr", "name": "French Again"})
    assert res.status_code == 400


def test_list_languages(client):
    client.post("/api/languages", json={"code": "en", "name": "English"})
    client.post("/api/languages", json={"code": "es", "name": "Spanish"})
    res = client.get("/api/languages")
    assert res.status_code == 200
    data = res.json()
    assert len(data) == 2
    assert data[0]["code"] == "en"


def test_delete_language(client):
    create = client.post("/api/languages", json={"code": "de", "name": "German"})
    lid = create.json()["id"]
    res = client.delete(f"/api/languages/{lid}")
    assert res.status_code == 204
