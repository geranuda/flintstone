"""Tests for TMX import/export."""

import io


SAMPLE_TMX = b"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE tmx SYSTEM "tmx14.dtd">
<tmx version="1.4">
  <header creationtool="TestTool" creationtoolversion="1.0"
          datatype="plaintext" segtype="sentence"
          adminlang="en" srclang="en" o-tmf="test"/>
  <body>
    <tu>
      <tuv xml:lang="en">
        <seg>Hello</seg>
      </tuv>
      <tuv xml:lang="es">
        <seg>Hola</seg>
      </tuv>
      <tuv xml:lang="fr">
        <seg>Bonjour</seg>
      </tuv>
    </tu>
    <tu>
      <tuv xml:lang="en">
        <seg>Goodbye</seg>
      </tuv>
      <tuv xml:lang="es">
        <seg>Adios</seg>
      </tuv>
    </tu>
    <tu>
      <tuv xml:lang="en">
        <seg>Thank you</seg>
      </tuv>
      <tuv xml:lang="fr">
        <seg>Merci</seg>
      </tuv>
    </tu>
  </body>
</tmx>"""


def _setup(client):
    p = client.post("/api/projects", json={"name": "tmx-proj"}).json()
    client.post("/api/languages", json={"code": "en", "name": "English"})
    client.post("/api/languages", json={"code": "es", "name": "Spanish"})
    client.post("/api/languages", json={"code": "fr", "name": "French"})
    return p["id"]


def test_import_tmx_to_project(client):
    pid = _setup(client)
    res = client.post(
        f"/api/projects/{pid}/import/tmx?source_lang=en",
        files={"file": ("test.tmx", io.BytesIO(SAMPLE_TMX), "application/xml")},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["total_units"] == 3
    assert data["created_keys"] == 3
    assert data["created_translations"] > 0
    assert data["tm_entries_added"] > 0

    # Verify keys were created
    keys = client.get(f"/api/projects/{pid}/keys").json()
    key_names = [k["key"] for k in keys]
    assert "Hello" in key_names
    assert "Goodbye" in key_names
    assert "Thank you" in key_names


def test_import_tmx_translations_correct(client):
    pid = _setup(client)
    client.post(
        f"/api/projects/{pid}/import/tmx?source_lang=en",
        files={"file": ("test.tmx", io.BytesIO(SAMPLE_TMX), "application/xml")},
    )

    # Check that the "Hello" key has the right translations
    keys = client.get(f"/api/projects/{pid}/keys").json()
    hello_key = next(k for k in keys if k["key"] == "Hello")
    assert hello_key["translations"]["en"] == "Hello"
    assert hello_key["translations"]["es"] == "Hola"
    assert hello_key["translations"]["fr"] == "Bonjour"


def test_import_tmx_to_memory_only(client):
    _setup(client)
    res = client.post(
        "/api/memory/import/tmx?source_lang=en",
        files={"file": ("test.tmx", io.BytesIO(SAMPLE_TMX), "application/xml")},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["total_units"] == 3
    assert data["entries_added"] > 0

    # Verify memory entries exist
    tm = client.get("/api/memory?source_lang=en&target_lang=es").json()
    assert len(tm) > 0
    texts = [e["target_text"] for e in tm]
    assert "Hola" in texts


def test_export_project_tmx(client):
    pid = _setup(client)
    # Import first
    client.post(
        f"/api/projects/{pid}/import/tmx?source_lang=en",
        files={"file": ("test.tmx", io.BytesIO(SAMPLE_TMX), "application/xml")},
    )

    # Export
    res = client.get(f"/api/projects/{pid}/export/tmx")
    assert res.status_code == 200
    content = res.content.decode()
    assert '<?xml version="1.0"' in content
    assert '<tmx version="1.4">' in content
    assert "Hello" in content
    assert "Hola" in content
    assert "Bonjour" in content


def test_export_memory_tmx(client):
    _setup(client)
    # Import to memory
    client.post(
        "/api/memory/import/tmx?source_lang=en",
        files={"file": ("test.tmx", io.BytesIO(SAMPLE_TMX), "application/xml")},
    )

    res = client.get("/api/memory/export/tmx?source_lang=en")
    assert res.status_code == 200
    content = res.content.decode()
    assert '<tmx version="1.4">' in content
    assert "Hello" in content


def test_tmx_round_trip(client):
    pid = _setup(client)
    # Import TMX
    client.post(
        f"/api/projects/{pid}/import/tmx?source_lang=en",
        files={"file": ("test.tmx", io.BytesIO(SAMPLE_TMX), "application/xml")},
    )

    # Export TMX
    export_res = client.get(f"/api/projects/{pid}/export/tmx")
    exported_tmx = export_res.content

    # Create new project and import the exported TMX
    p2 = client.post("/api/projects", json={"name": "tmx-roundtrip"}).json()
    res = client.post(
        f"/api/projects/{p2['id']}/import/tmx?source_lang=en",
        files={"file": ("exported.tmx", io.BytesIO(exported_tmx), "application/xml")},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["created_keys"] == 3
