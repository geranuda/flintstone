"""Tests for Import/Export functionality."""

import io
import json


def _setup(client):
    p = client.post("/api/projects", json={"name": "export-proj"}).json()
    en = client.post("/api/languages", json={"code": "en", "name": "English"}).json()
    es = client.post("/api/languages", json={"code": "es", "name": "Spanish"}).json()
    return p["id"], en["id"], es["id"]


def test_export_json(client):
    pid, en_id, _ = _setup(client)
    key = client.post(f"/api/projects/{pid}/keys", json={"key": "hello"}).json()
    client.put(f"/api/translations/{key['id']}/{en_id}", json={"value": "Hello"})

    res = client.get(f"/api/projects/{pid}/export?format=json&lang=en")
    assert res.status_code == 200
    data = json.loads(res.content)
    assert data["hello"] == "Hello"


def test_export_csv(client):
    pid, en_id, es_id = _setup(client)
    key = client.post(f"/api/projects/{pid}/keys", json={"key": "hi"}).json()
    client.put(f"/api/translations/{key['id']}/{en_id}", json={"value": "Hi"})
    client.put(f"/api/translations/{key['id']}/{es_id}", json={"value": "Hola"})

    res = client.get(f"/api/projects/{pid}/export?format=csv")
    assert res.status_code == 200
    content = res.content.decode()
    assert "key" in content
    assert "Hi" in content
    assert "Hola" in content


def test_import_json(client):
    pid, _, _ = _setup(client)
    data = json.dumps({"greeting": "Bonjour", "farewell": "Au revoir"})
    # First add French language
    client.post("/api/languages", json={"code": "fr", "name": "French"})

    res = client.post(
        f"/api/projects/{pid}/import?lang=fr",
        files={"file": ("fr.json", io.BytesIO(data.encode()), "application/json")},
    )
    assert res.status_code == 200
    result = res.json()
    assert result["created_keys"] == 2
    assert result["created_translations"] == 2


def test_import_csv(client):
    pid, _, _ = _setup(client)
    csv_data = "key,en,es\nhello,Hello,Hola\nbye,Bye,Adios\n"
    res = client.post(
        f"/api/projects/{pid}/import",
        files={"file": ("data.csv", io.BytesIO(csv_data.encode()), "text/csv")},
    )
    assert res.status_code == 200
    result = res.json()
    assert result["created_keys"] == 2
    assert result["created_translations"] == 4


def test_json_round_trip(client):
    pid, en_id, _ = _setup(client)
    # Create key and translation
    key = client.post(f"/api/projects/{pid}/keys", json={"key": "round.trip"}).json()
    client.put(f"/api/translations/{key['id']}/{en_id}", json={"value": "Round Trip"})

    # Export
    export_res = client.get(f"/api/projects/{pid}/export?format=json&lang=en")
    exported = json.loads(export_res.content)
    assert exported["round.trip"] == "Round Trip"

    # Create new project and import
    p2 = client.post("/api/projects", json={"name": "import-target"}).json()
    res = client.post(
        f"/api/projects/{p2['id']}/import?lang=en",
        files={"file": ("en.json", io.BytesIO(json.dumps(exported).encode()), "application/json")},
    )
    assert res.status_code == 200
    assert res.json()["created_keys"] == 1
