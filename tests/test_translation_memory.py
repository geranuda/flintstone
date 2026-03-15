"""Tests for Translation Memory."""


def _setup(client):
    p = client.post("/api/projects", json={"name": "tm-proj"}).json()
    en = client.post("/api/languages", json={"code": "en", "name": "English"}).json()
    es = client.post("/api/languages", json={"code": "es", "name": "Spanish"}).json()
    fr = client.post("/api/languages", json={"code": "fr", "name": "French"}).json()
    return p["id"], en["id"], es["id"], fr["id"]


def test_tm_auto_populated_on_save(client):
    pid, en_id, es_id, _ = _setup(client)

    # Create a key with English translation
    key = client.post(f"/api/projects/{pid}/keys", json={"key": "greeting"}).json()
    client.put(f"/api/translations/{key['id']}/{en_id}", json={"value": "Hello"})

    # Now add Spanish — this should create TM entries
    client.put(f"/api/translations/{key['id']}/{es_id}", json={"value": "Hola"})

    # Check TM has entries
    tm = client.get("/api/memory?source_lang=en&target_lang=es").json()
    assert len(tm) > 0
    assert any(e["source_text"] == "Hello" and e["target_text"] == "Hola" for e in tm)


def test_tm_suggest_exact_match(client):
    pid, en_id, es_id, _ = _setup(client)

    # Create translations to populate TM
    key = client.post(f"/api/projects/{pid}/keys", json={"key": "btn.save"}).json()
    client.put(f"/api/translations/{key['id']}/{en_id}", json={"value": "Save"})
    client.put(f"/api/translations/{key['id']}/{es_id}", json={"value": "Guardar"})

    # Query suggestions
    res = client.get("/api/memory/suggest?source=Save&source_lang=en&target_lang=es")
    assert res.status_code == 200
    suggestions = res.json()
    assert len(suggestions) > 0
    assert suggestions[0]["target_text"] == "Guardar"
    assert suggestions[0]["match_type"] == "exact"


def test_tm_suggest_contains_match(client):
    pid, en_id, es_id, _ = _setup(client)

    key = client.post(f"/api/projects/{pid}/keys", json={"key": "msg"}).json()
    client.put(f"/api/translations/{key['id']}/{en_id}", json={"value": "Save changes"})
    client.put(f"/api/translations/{key['id']}/{es_id}", json={"value": "Guardar cambios"})

    # Search for substring
    res = client.get("/api/memory/suggest?source=Save&source_lang=en&target_lang=es")
    suggestions = res.json()
    assert len(suggestions) > 0
    # Should find "Save changes" -> "Guardar cambios" as a contains match
    contains = [s for s in suggestions if s["match_type"] == "contains"]
    assert len(contains) > 0


def test_tm_suggest_no_results(client):
    _setup(client)
    res = client.get("/api/memory/suggest?source=xyz123&source_lang=en&target_lang=es")
    assert res.status_code == 200
    assert res.json() == []


def test_tm_list(client):
    pid, en_id, es_id, fr_id = _setup(client)

    key = client.post(f"/api/projects/{pid}/keys", json={"key": "test"}).json()
    client.put(f"/api/translations/{key['id']}/{en_id}", json={"value": "Test"})
    client.put(f"/api/translations/{key['id']}/{es_id}", json={"value": "Prueba"})
    client.put(f"/api/translations/{key['id']}/{fr_id}", json={"value": "Essai"})

    # List all TM entries
    res = client.get("/api/memory")
    assert res.status_code == 200
    entries = res.json()
    assert len(entries) > 0


def test_tm_clear(client):
    pid, en_id, es_id, _ = _setup(client)

    key = client.post(f"/api/projects/{pid}/keys", json={"key": "del"}).json()
    client.put(f"/api/translations/{key['id']}/{en_id}", json={"value": "Delete"})
    client.put(f"/api/translations/{key['id']}/{es_id}", json={"value": "Eliminar"})

    # Clear
    res = client.delete("/api/memory")
    assert res.status_code == 204

    # Verify empty
    entries = client.get("/api/memory").json()
    assert len(entries) == 0


def test_tm_bidirectional(client):
    pid, en_id, es_id, _ = _setup(client)

    key = client.post(f"/api/projects/{pid}/keys", json={"key": "hello"}).json()
    client.put(f"/api/translations/{key['id']}/{en_id}", json={"value": "Hello"})
    client.put(f"/api/translations/{key['id']}/{es_id}", json={"value": "Hola"})

    # en->es should work
    res1 = client.get("/api/memory/suggest?source=Hello&source_lang=en&target_lang=es")
    assert any(s["target_text"] == "Hola" for s in res1.json())

    # es->en should also work (bidirectional)
    res2 = client.get("/api/memory/suggest?source=Hola&source_lang=es&target_lang=en")
    assert any(s["target_text"] == "Hello" for s in res2.json())
