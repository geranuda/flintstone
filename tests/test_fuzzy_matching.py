"""Tests for fuzzy TM matching."""

from tests.conftest import _setup


def test_fuzzy_match_similar_strings(client):
    _setup(client)
    # Add TM entries
    client.post("/api/projects/1/keys", json={"key": "hello_world"})
    client.put("/api/translations/1/1", json={"value": "Hello World"})
    client.put("/api/translations/1/2", json={"value": "Hola Mundo"})

    # Query with a similar but not exact string
    resp = client.get("/api/memory/suggest", params={
        "source": "Hello Word",  # typo
        "source_lang": "en",
        "target_lang": "es",
        "include_fuzzy": True,
        "min_similarity": 0.5,
    })
    assert resp.status_code == 200
    suggestions = resp.json()
    fuzzy = [s for s in suggestions if s["match_type"] == "fuzzy"]
    assert len(fuzzy) >= 1
    assert fuzzy[0]["similarity_score"] > 0.5


def test_fuzzy_match_below_threshold(client):
    _setup(client)
    client.post("/api/projects/1/keys", json={"key": "k1"})
    client.put("/api/translations/1/1", json={"value": "Hello World"})
    client.put("/api/translations/1/2", json={"value": "Hola Mundo"})

    resp = client.get("/api/memory/suggest", params={
        "source": "Completely different text",
        "source_lang": "en",
        "target_lang": "es",
        "include_fuzzy": True,
        "min_similarity": 0.9,
    })
    suggestions = resp.json()
    fuzzy = [s for s in suggestions if s["match_type"] == "fuzzy"]
    assert len(fuzzy) == 0


def test_fuzzy_disabled(client):
    _setup(client)
    client.post("/api/projects/1/keys", json={"key": "k1"})
    client.put("/api/translations/1/1", json={"value": "Hello World"})
    client.put("/api/translations/1/2", json={"value": "Hola Mundo"})

    resp = client.get("/api/memory/suggest", params={
        "source": "Hello Word",
        "source_lang": "en",
        "target_lang": "es",
        "include_fuzzy": False,
    })
    suggestions = resp.json()
    fuzzy = [s for s in suggestions if s["match_type"] == "fuzzy"]
    assert len(fuzzy) == 0


def test_exact_matches_return_first(client):
    _setup(client)
    client.post("/api/projects/1/keys", json={"key": "k1"})
    client.put("/api/translations/1/1", json={"value": "Hello"})
    client.put("/api/translations/1/2", json={"value": "Hola"})

    resp = client.get("/api/memory/suggest", params={
        "source": "Hello",
        "source_lang": "en",
        "target_lang": "es",
    })
    suggestions = resp.json()
    assert len(suggestions) >= 1
    assert suggestions[0]["match_type"] == "exact"
    assert suggestions[0]["similarity_score"] == 1.0


def test_fuzzy_fillup(client):
    _setup(client)
    # Create TM entry
    client.post("/api/projects/1/keys", json={"key": "k1"})
    client.put("/api/translations/1/1", json={"value": "Hello World"})
    client.put("/api/translations/1/2", json={"value": "Hola Mundo"})

    # Create a new key with similar source
    client.post("/api/projects/1/keys", json={"key": "k2"})
    client.put("/api/translations/2/1", json={"value": "Hello Word"})  # typo

    resp = client.post("/api/memory/fillup/1", json={
        "source_lang": "en",
        "target_lang": "es",
        "match_type": "fuzzy",
        "min_similarity": 0.5,
    })
    assert resp.status_code == 200
    result = resp.json()
    assert result["filled"] >= 1


def test_similarity_score_computation():
    from flintstone.fuzzy import compute_similarity

    assert compute_similarity("hello", "hello") == 1.0
    assert compute_similarity("hello", "helo") > 0.7
    assert compute_similarity("hello", "xyz") < 0.3


def test_tm_suggestion_includes_score(client):
    _setup(client)
    client.post("/api/projects/1/keys", json={"key": "k1"})
    client.put("/api/translations/1/1", json={"value": "Save"})
    client.put("/api/translations/1/2", json={"value": "Guardar"})

    resp = client.get("/api/memory/suggest", params={
        "source": "Save",
        "source_lang": "en",
        "target_lang": "es",
    })
    suggestions = resp.json()
    assert all("similarity_score" in s for s in suggestions)
