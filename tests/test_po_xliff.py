"""Tests for PO and XLIFF import/export."""

import io

from tests.conftest import _setup


def test_export_po(client):
    _setup(client)
    client.post("/api/projects/1/keys", json={"key": "hello"})
    client.put("/api/translations/1/1", json={"value": "Hello"})

    resp = client.get("/api/projects/1/export?format=po&lang=en")
    assert resp.status_code == 200
    content = resp.text
    assert "hello" in content
    assert "Hello" in content


def test_export_po_requires_lang(client):
    _setup(client)
    resp = client.get("/api/projects/1/export?format=po")
    assert resp.status_code == 400


def test_import_po(client):
    _setup(client)
    po_content = '''
msgctxt "greeting"
msgid "greeting"
msgstr "Hola"
'''
    files = {"file": ("test.po", io.BytesIO(po_content.encode()), "application/x-gettext")}
    resp = client.post("/api/projects/1/import?lang=es", files=files)
    assert resp.status_code == 200
    data = resp.json()
    assert data["created_keys"] >= 1
    assert data["created_translations"] >= 1


def test_po_round_trip(client):
    _setup(client)
    client.post("/api/projects/1/keys", json={"key": "save_btn"})
    client.put("/api/translations/1/1", json={"value": "Save"})

    # Export
    resp = client.get("/api/projects/1/export?format=po&lang=en")
    assert resp.status_code == 200
    po_content = resp.content

    # Import into a new project
    client.post("/api/projects", json={"name": "PO Import"})
    files = {"file": ("test.po", io.BytesIO(po_content), "application/x-gettext")}
    resp = client.post("/api/projects/2/import?lang=en", files=files)
    assert resp.status_code == 200


def test_export_xliff(client):
    _setup(client)
    client.post("/api/projects/1/keys", json={"key": "hello"})
    client.put("/api/translations/1/1", json={"value": "Hello"})
    client.put("/api/translations/1/2", json={"value": "Hola"})

    resp = client.get("/api/projects/1/export?format=xliff&lang=es")
    assert resp.status_code == 200
    content = resp.text
    assert "xliff" in content.lower()
    assert "trans-unit" in content


def test_export_xliff_requires_lang(client):
    _setup(client)
    resp = client.get("/api/projects/1/export?format=xliff")
    assert resp.status_code == 400


def test_import_xliff(client):
    _setup(client)
    xliff_content = '''<?xml version="1.0" encoding="UTF-8"?>
<xliff version="1.2" xmlns="urn:oasis:names:tc:xliff:document:1.2">
  <file source-language="en" target-language="es" datatype="plaintext" original="test">
    <body>
      <trans-unit id="greeting">
        <source>Hello</source>
        <target>Hola</target>
      </trans-unit>
    </body>
  </file>
</xliff>'''
    files = {"file": ("test.xliff", io.BytesIO(xliff_content.encode()), "application/xml")}
    resp = client.post("/api/projects/1/import", files=files)
    assert resp.status_code == 200
    data = resp.json()
    assert data["created_keys"] >= 1


def test_xliff_round_trip(client):
    _setup(client)
    client.post("/api/projects/1/keys", json={"key": "farewell"})
    client.put("/api/translations/1/1", json={"value": "Goodbye"})
    client.put("/api/translations/1/2", json={"value": "Adiós"})

    # Export
    resp = client.get("/api/projects/1/export?format=xliff&lang=es")
    assert resp.status_code == 200
    xliff_content = resp.content

    # Import
    client.post("/api/projects", json={"name": "XLIFF Import"})
    files = {"file": ("test.xliff", io.BytesIO(xliff_content), "application/xml")}
    resp = client.post("/api/projects/2/import", files=files)
    assert resp.status_code == 200
