"""Tests for Find & Replace."""


def _setup(client):
    p = client.post("/api/projects", json={"name": "fr-proj"}).json()
    en = client.post("/api/languages", json={"code": "en", "name": "English"}).json()
    es = client.post("/api/languages", json={"code": "es", "name": "Spanish"}).json()
    pid = p["id"]

    k1 = client.post(f"/api/projects/{pid}/keys", json={"key": "msg1"}).json()
    k2 = client.post(f"/api/projects/{pid}/keys", json={"key": "msg2"}).json()
    k3 = client.post(f"/api/projects/{pid}/keys", json={"key": "msg3"}).json()

    client.put(f"/api/translations/{k1['id']}/{en['id']}", json={"value": "Hello World"})
    client.put(f"/api/translations/{k2['id']}/{en['id']}", json={"value": "Hello User"})
    client.put(f"/api/translations/{k3['id']}/{en['id']}", json={"value": "Goodbye"})
    client.put(f"/api/translations/{k1['id']}/{es['id']}", json={"value": "Hola Mundo"})

    return pid


def test_find_replace_preview(client):
    pid = _setup(client)
    res = client.post(f"/api/projects/{pid}/translations/find-replace", json={
        "find": "Hello", "replace": "Hi", "preview": True
    })
    assert res.status_code == 200
    data = res.json()
    assert data["total"] == 2
    assert data["applied"] is False
    assert all(m["old_value"].startswith("Hello") for m in data["matches"])
    assert all("Hi" in m["new_value"] for m in data["matches"])


def test_find_replace_apply(client):
    pid = _setup(client)
    res = client.post(f"/api/projects/{pid}/translations/find-replace", json={
        "find": "Hello", "replace": "Hi", "preview": False
    })
    assert res.status_code == 200
    data = res.json()
    assert data["total"] == 2
    assert data["applied"] is True

    # Verify the translations were actually changed
    keys = client.get(f"/api/projects/{pid}/keys").json()
    msg1 = next(k for k in keys if k["key"] == "msg1")
    assert msg1["translations"]["en"] == "Hi World"
    msg2 = next(k for k in keys if k["key"] == "msg2")
    assert msg2["translations"]["en"] == "Hi User"


def test_find_replace_by_language(client):
    pid = _setup(client)
    # Only replace in Spanish
    res = client.post(f"/api/projects/{pid}/translations/find-replace", json={
        "find": "Hola", "replace": "Hey", "language_code": "es", "preview": False
    })
    assert res.status_code == 200
    assert res.json()["total"] == 1

    # English should be untouched
    keys = client.get(f"/api/projects/{pid}/keys").json()
    msg1 = next(k for k in keys if k["key"] == "msg1")
    assert msg1["translations"]["en"] == "Hello World"
    assert msg1["translations"]["es"] == "Hey Mundo"


def test_find_replace_no_matches(client):
    pid = _setup(client)
    res = client.post(f"/api/projects/{pid}/translations/find-replace", json={
        "find": "nonexistent", "replace": "x", "preview": True
    })
    assert res.json()["total"] == 0
