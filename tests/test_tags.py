"""Tests for Tagging system."""


def _setup(client):
    p = client.post("/api/projects", json={"name": "tag-proj"}).json()
    client.post("/api/languages", json={"code": "en", "name": "English"})
    return p["id"]


def test_create_key_with_tags(client):
    pid = _setup(client)
    res = client.post(f"/api/projects/{pid}/keys", json={
        "key": "btn.save", "tags": ["ui", "buttons"]
    })
    assert res.status_code == 201
    data = res.json()
    assert "ui" in data["tags"]
    assert "buttons" in data["tags"]


def test_update_key_tags(client):
    pid = _setup(client)
    key = client.post(f"/api/projects/{pid}/keys", json={
        "key": "msg.hello", "tags": ["greetings"]
    }).json()
    res = client.put(f"/api/keys/{key['id']}", json={"tags": ["messages", "ui"]})
    assert res.status_code == 200
    assert "messages" in res.json()["tags"]
    assert "greetings" not in res.json()["tags"]


def test_filter_by_tag(client):
    pid = _setup(client)
    client.post(f"/api/projects/{pid}/keys", json={"key": "a", "tags": ["ui"]})
    client.post(f"/api/projects/{pid}/keys", json={"key": "b", "tags": ["api"]})
    client.post(f"/api/projects/{pid}/keys", json={"key": "c", "tags": ["ui", "buttons"]})

    res = client.get(f"/api/projects/{pid}/keys?tag=ui")
    data = res.json()
    assert len(data) == 2
    keys = [k["key"] for k in data]
    assert "a" in keys
    assert "c" in keys


def test_list_tags(client):
    pid = _setup(client)
    client.post(f"/api/projects/{pid}/keys", json={"key": "a", "tags": ["ui"]})
    client.post(f"/api/projects/{pid}/keys", json={"key": "b", "tags": ["ui", "buttons"]})
    client.post(f"/api/projects/{pid}/keys", json={"key": "c", "tags": ["api"]})

    res = client.get(f"/api/projects/{pid}/tags")
    assert res.status_code == 200
    tags = res.json()
    tag_map = {t["tag"]: t["count"] for t in tags}
    assert tag_map["ui"] == 2
    assert tag_map["buttons"] == 1
    assert tag_map["api"] == 1


def test_key_without_tags(client):
    pid = _setup(client)
    res = client.post(f"/api/projects/{pid}/keys", json={"key": "no-tags"})
    assert res.status_code == 201
    assert res.json()["tags"] == []
