"""Tests for glossary."""

from tests.conftest import _setup


def test_create_glossary_term(client):
    _setup(client)
    resp = client.post("/api/glossary", json={
        "source_term": "Save", "source_language": "en"
    })
    assert resp.status_code == 201
    assert resp.json()["source_term"] == "Save"


def test_create_term_with_translations(client):
    _setup(client)
    resp = client.post("/api/glossary", json={
        "source_term": "Save",
        "source_language": "en",
        "translations": [{"language_code": "es", "approved_value": "Guardar"}],
    })
    assert resp.status_code == 201
    assert resp.json()["translations"]["es"] == "Guardar"


def test_duplicate_term_rejected(client):
    _setup(client)
    client.post("/api/glossary", json={"source_term": "Save", "source_language": "en"})
    resp = client.post("/api/glossary", json={"source_term": "Save", "source_language": "en"})
    assert resp.status_code == 400


def test_list_glossary_terms(client):
    _setup(client)
    client.post("/api/glossary", json={"source_term": "Save", "source_language": "en"})
    client.post("/api/glossary", json={"source_term": "Cancel", "source_language": "en"})
    resp = client.get("/api/glossary")
    assert len(resp.json()) == 2


def test_list_glossary_search(client):
    _setup(client)
    client.post("/api/glossary", json={"source_term": "Save", "source_language": "en"})
    client.post("/api/glossary", json={"source_term": "Cancel", "source_language": "en"})
    resp = client.get("/api/glossary?q=Sav")
    assert len(resp.json()) == 1


def test_update_glossary_term(client):
    _setup(client)
    client.post("/api/glossary", json={"source_term": "Save", "source_language": "en"})
    resp = client.put("/api/glossary/1", json={"description": "Action button"})
    assert resp.status_code == 200
    assert resp.json()["description"] == "Action button"


def test_delete_glossary_term(client):
    _setup(client)
    client.post("/api/glossary", json={"source_term": "Save", "source_language": "en"})
    resp = client.delete("/api/glossary/1")
    assert resp.status_code == 204
    resp = client.get("/api/glossary")
    assert len(resp.json()) == 0


def test_add_glossary_translation(client):
    _setup(client)
    client.post("/api/glossary", json={"source_term": "Save", "source_language": "en"})
    resp = client.post("/api/glossary/1/translations", json={
        "language_code": "es", "approved_value": "Guardar"
    })
    assert resp.status_code == 200
    assert resp.json()["translations"]["es"] == "Guardar"


def test_delete_glossary_translation(client):
    _setup(client)
    client.post("/api/glossary", json={
        "source_term": "Save", "source_language": "en",
        "translations": [{"language_code": "es", "approved_value": "Guardar"}],
    })
    resp = client.delete("/api/glossary/1/translations/es")
    assert resp.status_code == 204


def test_glossary_check_detects_violation(client):
    _setup(client)
    client.post("/api/glossary", json={
        "source_term": "Save",
        "source_language": "en",
        "translations": [{"language_code": "es", "approved_value": "Guardar"}],
    })
    resp = client.post("/api/glossary/check", json={
        "source_text": "Click Save to continue",
        "source_lang": "en",
        "target_text": "Haz clic en Salvar para continuar",
        "target_lang": "es",
    })
    assert resp.status_code == 200
    violations = resp.json()
    assert len(violations) == 1
    assert violations[0]["expected_value"] == "Guardar"


def test_glossary_check_passes_when_correct(client):
    _setup(client)
    client.post("/api/glossary", json={
        "source_term": "Save",
        "source_language": "en",
        "translations": [{"language_code": "es", "approved_value": "Guardar"}],
    })
    resp = client.post("/api/glossary/check", json={
        "source_text": "Click Save",
        "source_lang": "en",
        "target_text": "Haz clic en Guardar",
        "target_lang": "es",
    })
    violations = resp.json()
    assert len(violations) == 0


def test_glossary_case_sensitive(client):
    _setup(client)
    client.post("/api/glossary", json={
        "source_term": "API",
        "source_language": "en",
        "case_sensitive": True,
        "translations": [{"language_code": "es", "approved_value": "API"}],
    })
    # "api" lowercase should NOT trigger
    resp = client.post("/api/glossary/check", json={
        "source_text": "Use the api",
        "source_lang": "en",
        "target_text": "Usa la interfaz",
        "target_lang": "es",
    })
    assert len(resp.json()) == 0

    # "API" uppercase SHOULD trigger
    resp = client.post("/api/glossary/check", json={
        "source_text": "Use the API",
        "source_lang": "en",
        "target_text": "Usa la interfaz",
        "target_lang": "es",
    })
    assert len(resp.json()) == 1


def test_glossary_ui_page(client):
    _setup(client)
    resp = client.get("/glossary")
    assert resp.status_code == 200
    assert "Glossary" in resp.text
