"""Tests for TM Fill-up."""

import io


SAMPLE_TMX = b"""<?xml version="1.0" encoding="UTF-8"?>
<tmx version="1.4">
  <header srclang="en"/>
  <body>
    <tu>
      <tuv xml:lang="en"><seg>Save</seg></tuv>
      <tuv xml:lang="es"><seg>Guardar</seg></tuv>
    </tu>
    <tu>
      <tuv xml:lang="en"><seg>Cancel</seg></tuv>
      <tuv xml:lang="es"><seg>Cancelar</seg></tuv>
    </tu>
    <tu>
      <tuv xml:lang="en"><seg>Delete</seg></tuv>
      <tuv xml:lang="es"><seg>Eliminar</seg></tuv>
    </tu>
  </body>
</tmx>"""


def _setup(client):
    p = client.post("/api/projects", json={"name": "fillup-proj"}).json()
    en = client.post("/api/languages", json={"code": "en", "name": "English"}).json()
    es = client.post("/api/languages", json={"code": "es", "name": "Spanish"}).json()
    return p["id"], en["id"], es["id"]


def test_fillup_exact_match(client):
    pid, en_id, es_id = _setup(client)

    # Load TMX into memory
    client.post(
        "/api/memory/import/tmx?source_lang=en",
        files={"file": ("tm.tmx", io.BytesIO(SAMPLE_TMX), "application/xml")},
    )

    # Create keys with English translations matching TM
    k1 = client.post(f"/api/projects/{pid}/keys", json={"key": "btn.save"}).json()
    k2 = client.post(f"/api/projects/{pid}/keys", json={"key": "btn.cancel"}).json()
    k3 = client.post(f"/api/projects/{pid}/keys", json={"key": "btn.delete"}).json()
    k4 = client.post(f"/api/projects/{pid}/keys", json={"key": "btn.submit"}).json()

    client.put(f"/api/translations/{k1['id']}/{en_id}", json={"value": "Save"})
    client.put(f"/api/translations/{k2['id']}/{en_id}", json={"value": "Cancel"})
    client.put(f"/api/translations/{k3['id']}/{en_id}", json={"value": "Delete"})
    client.put(f"/api/translations/{k4['id']}/{en_id}", json={"value": "Submit"})  # no TM match

    # Run fill-up
    res = client.post(f"/api/memory/fillup/{pid}", json={
        "source_lang": "en", "target_lang": "es", "match_type": "exact"
    })
    assert res.status_code == 200
    data = res.json()
    assert data["filled"] == 3  # Save, Cancel, Delete
    assert data["skipped"] == 1  # Submit (no TM match)
    assert data["total_missing"] == 4

    # Verify translations were created
    keys = client.get(f"/api/projects/{pid}/keys").json()
    save = next(k for k in keys if k["key"] == "btn.save")
    assert save["translations"]["es"] == "Guardar"
    cancel = next(k for k in keys if k["key"] == "btn.cancel")
    assert cancel["translations"]["es"] == "Cancelar"


def test_fillup_skips_existing(client):
    pid, en_id, es_id = _setup(client)

    # Load TM
    client.post(
        "/api/memory/import/tmx?source_lang=en",
        files={"file": ("tm.tmx", io.BytesIO(SAMPLE_TMX), "application/xml")},
    )

    # Create key with both translations already
    k1 = client.post(f"/api/projects/{pid}/keys", json={"key": "btn.save"}).json()
    client.put(f"/api/translations/{k1['id']}/{en_id}", json={"value": "Save"})
    client.put(f"/api/translations/{k1['id']}/{es_id}", json={"value": "Already translated"})

    # Fill-up should skip it
    res = client.post(f"/api/memory/fillup/{pid}", json={
        "source_lang": "en", "target_lang": "es"
    })
    assert res.json()["filled"] == 0
    assert res.json()["total_missing"] == 0


def test_fillup_no_source_translation(client):
    pid, en_id, es_id = _setup(client)

    # Key with no source translation
    client.post(f"/api/projects/{pid}/keys", json={"key": "orphan"})

    res = client.post(f"/api/memory/fillup/{pid}", json={
        "source_lang": "en", "target_lang": "es"
    })
    assert res.json()["filled"] == 0
    assert res.json()["skipped"] == 1
