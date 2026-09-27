"""Project languages, stats, editor strings API and translation review status."""


def _push(client, project, data):
    res = client.post("/cds/content", headers=project.write, json={"data": data})
    assert res.status_code == 202


def _lang_id(client, code):
    return next(lang["id"] for lang in client.get("/api/languages").json() if lang["code"] == code)


def test_create_project_with_languages(client, native_project):
    project = client.get(f"/api/projects/{native_project.id}").json()
    assert project["source_language"] == "en"
    assert sorted(project["target_languages"]) == ["es-MX", "fr"]
    langs = client.get(f"/api/projects/{native_project.id}/languages").json()
    assert [(l["code"], l["is_source"]) for l in langs][0] == ("en", True)
    es = next(l for l in langs if l["code"] == "es-MX")
    assert es["plural_categories"] == ["one", "many", "other"]


def test_language_codes_are_normalized(client):
    project = client.post("/api/projects", json={
        "name": "P", "source_language": "EN", "target_languages": ["pt_br", "zh-hans"],
    }).json()
    assert project["source_language"] == "en"
    assert sorted(project["target_languages"]) == ["pt-BR", "zh-Hans"]


def test_invalid_language_codes_are_rejected(client, native_project):
    res = client.post("/api/projects", json={"name": "Bad", "target_languages": ["es-MX", "');x()"]})
    assert res.status_code == 400
    assert client.get("/api/projects").json()[0]["name"] == "App"  # nothing half-created
    res = client.post(f"/api/projects/{native_project.id}/languages", json={"code": "<b>"})
    assert res.status_code == 400


def test_add_and_remove_target_language(client, native_project):
    pid = native_project.id
    res = client.post(f"/api/projects/{pid}/languages", json={"code": "de"})
    assert res.status_code == 201 and res.json()["name"] == "German"
    assert client.post(f"/api/projects/{pid}/languages", json={"code": "en"}).status_code == 400
    assert client.delete(f"/api/projects/{pid}/languages/fr").status_code == 204
    assert client.delete(f"/api/projects/{pid}/languages/fr").status_code == 404
    codes = [l["code"] for l in client.get(f"/api/projects/{pid}/languages").json()]
    assert codes == ["en", "de", "es-MX"]
    assert client.get("/cds/content/fr", headers=native_project.read).status_code == 404


def test_legacy_project_uses_all_languages_until_configured(client):
    pid = client.post("/api/projects", json={"name": "legacy"}).json()["id"]
    for code, name in (("en", "English"), ("es", "Spanish"), ("fr", "French")):
        client.post("/api/languages", json={"code": code, "name": name})
    assert client.get(f"/api/projects/{pid}").json()["target_languages"] == ["es", "fr"]
    # Adding a language keeps the ones the project already had
    client.post(f"/api/projects/{pid}/languages", json={"code": "de"})
    client.post("/api/languages", json={"code": "it", "name": "Italian"})
    assert client.get(f"/api/projects/{pid}").json()["target_languages"] == ["de", "es", "fr"]


def test_stats_include_review_progress(client, native_project):
    _push(client, native_project, {"a": {"string": "A"}, "b": {"string": "B"}})
    client.post("/cds/content/es-MX", headers=native_project.write,
                json={"data": {"a": {"string": "Á", "status": "reviewed"}, "b": "B!"}})
    stats = client.get(f"/api/projects/{native_project.id}/stats").json()
    es = next(s for s in stats["languages"] if s["language_code"] == "es-MX")
    assert (es["translated"], es["reviewed"], es["percentage"]) == (2, 1, 100.0)
    en = next(s for s in stats["languages"] if s["language_code"] == "en")
    assert en["is_source"] is True


def test_review_status_and_edits(client, native_project):
    _push(client, native_project, {"a": {"string": "A"}})
    key_id = client.get(f"/api/projects/{native_project.id}/keys").json()[0]["id"]
    es = _lang_id(client, "es-MX")
    res = client.put(f"/api/translations/{key_id}/{es}", json={"value": "Á"})
    assert res.json()["status"] == "translated"
    res = client.put(f"/api/translations/{key_id}/{es}/status", json={"status": "reviewed"})
    assert res.json()["status"] == "reviewed"
    # Same value keeps the review, a new value needs a new review
    assert client.put(f"/api/translations/{key_id}/{es}", json={"value": "Á"}).json()["status"] == "reviewed"
    assert client.put(f"/api/translations/{key_id}/{es}", json={"value": "Áa"}).json()["status"] == "translated"
    assert client.put(f"/api/translations/{key_id}/{es}/status", json={"status": "bogus"}).status_code == 422
    assert client.delete(f"/api/translations/{key_id}/{es}").status_code == 204
    assert client.delete(f"/api/translations/{key_id}/{es}").status_code == 404


def test_strings_endpoint_filters(client, native_project):
    _push(client, native_project, {
        "count": {"string": "{cnt, plural, one {%lld item} other {%lld items}}",
                  "meta": {"occurrences": ["App/Localizable.xcstrings"], "tags": ["ui"]}},
        "discount": {"string": "50% off", "meta": {"occurrences": ["Watch/Localizable.xcstrings"],
                                                   "developer_comment": "Sale badge"}},
        "hello": {"string": "Hello", "meta": {"occurrences": ["App/Localizable.xcstrings"]}},
    })
    client.post("/cds/content/es-MX", headers=native_project.write,
                json={"data": {"hello": {"string": "Hola", "status": "reviewed"}, "discount": "50% menos"}})
    url = f"/api/projects/{native_project.id}/strings"

    def keys(**params):
        return [s["key"] for s in client.get(url, params={"lang": "es-MX", **params}).json()["strings"]]

    assert keys() == ["count", "discount", "hello"]
    assert keys(q="0%") == ["discount"]  # LIKE wildcards are literal
    assert keys(q="_") == []
    assert keys(q="sale") == ["discount"]  # developer comments are searchable
    assert keys(q="hola") == ["hello"]  # so are translations
    assert keys(tag="ui") == ["count"]
    assert keys(file="Watch/") == ["discount"]
    assert keys(status="untranslated") == ["count"]
    assert keys(status="unreviewed") == ["discount"]
    assert keys(status="reviewed") == ["hello"]
    page = client.get(url, params={"lang": "es-MX", "per_page": 2, "page": 2}).json()
    assert page["total"] == 3 and [s["key"] for s in page["strings"]] == ["hello"]
    count = client.get(url, params={"lang": "es-MX", "q": "item"}).json()["strings"][0]
    assert count["kind"] == "plural" and count["tags"] == ["ui"]
    assert client.get(url, params={"lang": "de"}).status_code == 404


def test_jobs_listing(client, native_project):
    _push(client, native_project, {"a": {"string": "A"}})
    jobs = client.get(f"/api/projects/{native_project.id}/jobs").json()
    assert len(jobs) == 1 and jobs[0]["kind"] == "source" and jobs[0]["created"] == 1


def test_key_metadata_via_api(client, native_project):
    res = client.post(f"/api/projects/{native_project.id}/keys", json={
        "key": "title", "description": "Screen title", "tags": ["ui", "a,b"],
        "context": "settings", "character_limit": 12, "occurrences": ["Settings.swift"],
    })
    key = res.json()
    assert key["tags"] == ["ui", "a b"] and key["character_limit"] == 12 and key["context"] == "settings"
    res = client.put(f"/api/keys/{key['id']}", json={"character_limit": 0, "occurrences": []})
    assert res.json()["character_limit"] is None and res.json()["occurrences"] == []
