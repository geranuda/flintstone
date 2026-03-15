"""Tests for Translations API."""


def _setup(client):
    """Create a project and language for tests."""
    p = client.post("/api/projects", json={"name": "test-proj"}).json()
    l_en = client.post("/api/languages", json={"code": "en", "name": "English"}).json()
    l_es = client.post("/api/languages", json={"code": "es", "name": "Spanish"}).json()
    return p["id"], l_en["id"], l_es["id"]


def test_create_key(client):
    pid, _, _ = _setup(client)
    res = client.post(f"/api/projects/{pid}/keys", json={"key": "hello", "description": "Greeting"})
    assert res.status_code == 201
    assert res.json()["key"] == "hello"


def test_list_keys(client):
    pid, _, _ = _setup(client)
    client.post(f"/api/projects/{pid}/keys", json={"key": "a.key"})
    client.post(f"/api/projects/{pid}/keys", json={"key": "b.key"})
    res = client.get(f"/api/projects/{pid}/keys")
    assert res.status_code == 200
    assert len(res.json()) == 2


def test_search_keys(client):
    pid, _, _ = _setup(client)
    client.post(f"/api/projects/{pid}/keys", json={"key": "button.save"})
    client.post(f"/api/projects/{pid}/keys", json={"key": "label.name"})
    res = client.get(f"/api/projects/{pid}/keys?q=button")
    assert len(res.json()) == 1
    assert res.json()[0]["key"] == "button.save"


def test_set_translation(client):
    pid, en_id, _ = _setup(client)
    key = client.post(f"/api/projects/{pid}/keys", json={"key": "greeting"}).json()
    res = client.put(f"/api/translations/{key['id']}/{en_id}", json={"value": "Hello"})
    assert res.status_code == 200
    assert res.json()["value"] == "Hello"


def test_update_translation(client):
    pid, en_id, _ = _setup(client)
    key = client.post(f"/api/projects/{pid}/keys", json={"key": "greeting"}).json()
    client.put(f"/api/translations/{key['id']}/{en_id}", json={"value": "Hello"})
    res = client.put(f"/api/translations/{key['id']}/{en_id}", json={"value": "Hi"})
    assert res.json()["value"] == "Hi"


def test_bulk_update(client):
    pid, _, _ = _setup(client)
    res = client.post(f"/api/projects/{pid}/translations/bulk", json={
        "translations": [
            {"key": "save", "language_code": "en", "value": "Save"},
            {"key": "save", "language_code": "es", "value": "Guardar"},
            {"key": "cancel", "language_code": "en", "value": "Cancel"},
        ]
    })
    assert res.status_code == 200
    data = res.json()
    assert data["created"] == 3


def test_search_translations(client):
    pid, en_id, _ = _setup(client)
    key = client.post(f"/api/projects/{pid}/keys", json={"key": "msg"}).json()
    client.put(f"/api/translations/{key['id']}/{en_id}", json={"value": "Hello World"})
    res = client.get(f"/api/projects/{pid}/translations/search?q=World")
    assert len(res.json()) == 1


def test_project_stats(client):
    pid, en_id, es_id = _setup(client)
    key = client.post(f"/api/projects/{pid}/keys", json={"key": "k1"}).json()
    client.post(f"/api/projects/{pid}/keys", json={"key": "k2"})
    client.put(f"/api/translations/{key['id']}/{en_id}", json={"value": "v1"})
    res = client.get(f"/api/projects/{pid}/stats")
    assert res.status_code == 200
    stats = res.json()
    assert stats["total_keys"] == 2
    en_stats = next(l for l in stats["languages"] if l["language_code"] == "en")
    assert en_stats["translated"] == 1
    assert en_stats["percentage"] == 50.0


def test_delete_key(client):
    pid, _, _ = _setup(client)
    key = client.post(f"/api/projects/{pid}/keys", json={"key": "delete-me"}).json()
    res = client.delete(f"/api/keys/{key['id']}")
    assert res.status_code == 204
