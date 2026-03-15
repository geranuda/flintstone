"""Tests for Projects API."""


def test_create_project(client):
    res = client.post("/api/projects", json={"name": "test-app", "description": "A test app"})
    assert res.status_code == 201
    data = res.json()
    assert data["name"] == "test-app"
    assert data["description"] == "A test app"
    assert data["key_count"] == 0


def test_create_duplicate_project(client):
    client.post("/api/projects", json={"name": "dup"})
    res = client.post("/api/projects", json={"name": "dup"})
    assert res.status_code == 400


def test_list_projects(client):
    client.post("/api/projects", json={"name": "alpha"})
    client.post("/api/projects", json={"name": "beta"})
    res = client.get("/api/projects")
    assert res.status_code == 200
    data = res.json()
    assert len(data) == 2
    assert data[0]["name"] == "alpha"


def test_get_project(client):
    create = client.post("/api/projects", json={"name": "get-me"})
    pid = create.json()["id"]
    res = client.get(f"/api/projects/{pid}")
    assert res.status_code == 200
    assert res.json()["name"] == "get-me"


def test_get_project_not_found(client):
    res = client.get("/api/projects/999")
    assert res.status_code == 404


def test_update_project(client):
    create = client.post("/api/projects", json={"name": "old-name"})
    pid = create.json()["id"]
    res = client.put(f"/api/projects/{pid}", json={"name": "new-name"})
    assert res.status_code == 200
    assert res.json()["name"] == "new-name"


def test_delete_project(client):
    create = client.post("/api/projects", json={"name": "delete-me"})
    pid = create.json()["id"]
    res = client.delete(f"/api/projects/{pid}")
    assert res.status_code == 204
    res = client.get(f"/api/projects/{pid}")
    assert res.status_code == 404
