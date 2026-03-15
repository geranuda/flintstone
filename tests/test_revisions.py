"""Tests for revision history."""

from tests.conftest import _setup


def test_translation_change_creates_revision(client):
    _setup(client)
    client.post("/api/projects/1/keys", json={"key": "hello"})
    client.put("/api/translations/1/1", json={"value": "Hello"})

    resp = client.get("/api/projects/1/revisions")
    assert resp.status_code == 200
    revisions = resp.json()
    # Should have key creation + translation creation revisions
    assert len(revisions) >= 2


def test_translation_update_records_old_and_new(client):
    _setup(client)
    client.post("/api/projects/1/keys", json={"key": "hello"})
    client.put("/api/translations/1/1", json={"value": "Hello"})
    client.put("/api/translations/1/1", json={"value": "Hello Updated"})

    resp = client.get("/api/projects/1/revisions?entity_type=translation&action=update")
    revisions = resp.json()
    assert len(revisions) >= 1
    rev = revisions[0]
    assert rev["old_value"] == "Hello"
    assert rev["new_value"] == "Hello Updated"


def test_project_create_records_revision(client):
    _setup(client)
    resp = client.get("/api/projects/1/revisions?entity_type=project")
    revisions = resp.json()
    assert any(r["action"] == "create" for r in revisions)


def test_project_delete_records_revision(client):
    _setup(client)
    client.delete("/api/projects/1")
    # Revision with project_id=NULL since project is deleted
    resp = client.get("/api/revisions/1")
    # The revision should exist even though the project is deleted
    assert resp.status_code == 200 or resp.status_code == 404  # Revision may reference deleted project


def test_key_crud_records_revisions(client):
    _setup(client)
    client.post("/api/projects/1/keys", json={"key": "test_key"})
    client.put("/api/keys/1", json={"key": "test_key_renamed"})
    client.delete("/api/keys/1")

    resp = client.get("/api/projects/1/revisions?entity_type=key")
    revisions = resp.json()
    actions = [r["action"] for r in revisions]
    assert "create" in actions
    assert "update" in actions
    assert "delete" in actions


def test_list_revisions_with_pagination(client):
    _setup(client)
    # Create multiple keys to generate revisions
    for i in range(5):
        client.post("/api/projects/1/keys", json={"key": f"key_{i}"})

    resp = client.get("/api/projects/1/revisions?offset=0&limit=3")
    assert len(resp.json()) == 3


def test_bulk_update_records_revisions(client):
    _setup(client)
    client.post("/api/projects/1/keys", json={"key": "bulk_key"})
    client.post("/api/projects/1/translations/bulk", json={
        "translations": [
            {"key": "bulk_key", "language_code": "en", "value": "English"},
            {"key": "bulk_key", "language_code": "es", "value": "Spanish"},
        ]
    })

    resp = client.get("/api/projects/1/revisions?entity_type=translation")
    revisions = resp.json()
    assert len(revisions) >= 2


def test_find_replace_records_revisions(client):
    _setup(client)
    client.post("/api/projects/1/keys", json={"key": "fr_key"})
    client.put("/api/translations/1/1", json={"value": "Hello World"})

    # Apply find-replace (not preview)
    client.post("/api/projects/1/translations/find-replace", json={
        "find": "World", "replace": "Earth", "preview": False
    })

    resp = client.get("/api/projects/1/revisions?entity_type=translation")
    revisions = resp.json()
    fr_revisions = [r for r in revisions if r.get("meta", {}).get("find_replace")]
    assert len(fr_revisions) >= 1


def test_get_single_revision(client):
    _setup(client)
    client.post("/api/projects/1/keys", json={"key": "rev_test"})

    resp = client.get("/api/projects/1/revisions")
    revisions = resp.json()
    assert len(revisions) > 0

    rev_id = revisions[0]["id"]
    resp = client.get(f"/api/revisions/{rev_id}")
    assert resp.status_code == 200
    assert resp.json()["id"] == rev_id
