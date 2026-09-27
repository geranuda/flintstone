"""Transifex Native CDS protocol (/cds): what the official SDKs and CLIs send and expect."""

from flintstone import native
from flintstone.models import Project

# Payload in the shape the Transifex iOS SDK (TXSourceString) serializes:
# context is a list, character_limit 0 means "no limit", tags may be empty.
IOS_PUSH = {
    "data": {
        "greeting": {
            "string": "Hello",
            "meta": {
                "developer_comment": "Home screen greeting",
                "character_limit": 0,
                "tags": [],
                "occurrences": ["App/Localizable.xcstrings"],
                "context": ["home"],
            },
        },
        "%lld days": {
            "string": "{cnt, plural, one {%lld day} other {%lld days}}",
            "meta": {"character_limit": 0, "tags": [], "occurrences": ["App/Localizable.xcstrings"]},
        },
    },
    "meta": {"purge": False, "override_tags": False, "override_occurrences": False,
             "keep_translations": True, "dry_run": False},
}


def _push(client, project, data, **meta):
    res = client.post("/cds/content", headers=project.write, json={"data": data, "meta": meta})
    assert res.status_code == 202, res.text
    link = res.json()["data"]["links"]["job"]
    job = client.get("/cds" + link, headers=project.write)
    assert job.status_code == 200
    return job.json()["data"]


def _translate(client, project, lang, data, **meta):
    res = client.post(f"/cds/content/{lang}", headers=project.write, json={"data": data, "meta": meta})
    assert res.status_code == 202, res.text
    return client.get("/cds" + res.json()["data"]["links"]["job"], headers=project.write).json()["data"]


def _content(client, project, lang, query=""):
    res = client.get(f"/cds/content/{lang}{query}", headers=project.read)
    assert res.status_code == 200, res.text
    return res.json()["data"]


# --- Credentials ---

def test_project_gets_token_and_one_time_secret(client, native_project, db_session):
    assert native_project.token.startswith("1/")
    assert native_project.secret.startswith("1/")
    stored = db_session.get(Project, native_project.id)
    assert stored.secret_hash and native_project.secret not in (stored.secret_hash, stored.token)
    # The secret is never returned again
    assert client.get(f"/api/projects/{native_project.id}").json()["secret"] is None


def test_auth_errors(client, native_project):
    assert client.get("/cds/languages").status_code == 401
    assert client.get("/cds/languages", headers={"Authorization": "Bearer nope"}).status_code == 403
    wrong_secret = {"Authorization": f"Bearer {native_project.token}:wrong"}
    assert client.get("/cds/languages", headers=wrong_secret).status_code == 403
    # write endpoints need the secret
    assert client.post("/cds/content", headers=native_project.read, json={"data": {}}).status_code == 403
    assert client.post("/cds/invalidate", headers=native_project.read).status_code == 403
    body = client.get("/cds/languages", headers={"Authorization": "Bearer nope"}).json()
    assert body == {"status": 403, "message": "Forbidden"}


def test_rotating_secret_revokes_old_one(client, native_project):
    new = client.post(f"/api/projects/{native_project.id}/credentials", json={"rotate": "secret"}).json()
    assert new["token"] == native_project.token and new["secret"]
    assert client.post("/cds/invalidate", headers=native_project.write).status_code == 403
    headers = {"Authorization": f"Bearer {native_project.token}:{new['secret']}"}
    assert client.post("/cds/invalidate", headers=headers).status_code == 200


# --- Languages ---

def test_languages(client, native_project):
    res = client.get("/cds/languages", headers=native_project.read)
    assert res.status_code == 200
    body = res.json()
    assert body["meta"]["source_lang_code"] == "en"
    codes = [lang["code"] for lang in body["data"]]
    assert codes[0] == "en" and set(codes) == {"en", "es-MX", "fr"}
    es = next(lang for lang in body["data"] if lang["code"] == "es-MX")
    assert es == {"name": "Spanish (Mexico)", "code": "es-MX", "localized_name": "Español (México)", "rtl": False}


# --- Push source content ---

def test_push_source_ios_payload(client, native_project):
    res = client.post("/cds/content", headers=native_project.write, json=IOS_PUSH)
    assert res.status_code == 202
    data = res.json()["data"]
    # SDKs append the job link to their cdsHost, so it must be relative to the CDS root
    assert data["links"]["job"] == f"/jobs/content/{data['id']}"

    job = client.get("/cds" + data["links"]["job"], headers=native_project.write).json()["data"]
    assert job["status"] == "completed"
    assert job["details"] == {"created": 2, "updated": 0, "skipped": 0, "deleted": 0, "failed": 0}

    keys = {k["key"]: k for k in client.get(f"/api/projects/{native_project.id}/keys").json()}
    greeting = keys["greeting"]
    assert greeting["description"] == "Home screen greeting"
    assert greeting["context"] == "home"
    assert greeting["character_limit"] is None
    assert greeting["occurrences"] == ["App/Localizable.xcstrings"]
    assert greeting["translations"] == {"en": "Hello"}
    assert _content(client, native_project, "en")["%lld days"] == {
        "string": "{cnt, plural, one {%lld day} other {%lld days}}"
    }


def test_push_again_is_skipped(client, native_project):
    _push(client, native_project, IOS_PUSH["data"])
    job = _push(client, native_project, IOS_PUSH["data"])
    assert job["details"]["skipped"] == 2 and job["details"]["created"] == 0


def test_tags_and_occurrences_append_or_override(client, native_project):
    _push(client, native_project, {"k": {"string": "K", "meta": {"tags": ["a"], "occurrences": ["x.swift"]}}})
    _push(client, native_project, {"k": {"string": "K", "meta": {"tags": ["b"], "occurrences": ["y.swift"]}}})
    key = client.get(f"/api/projects/{native_project.id}/keys").json()[0]
    assert key["tags"] == ["a", "b"] and key["occurrences"] == ["x.swift", "y.swift"]

    job = _push(client, native_project, {"k": {"string": "K", "meta": {"tags": ["c"], "occurrences": ["z.swift"]}}},
                override_tags=True, override_occurrences=True)
    assert job["details"]["updated"] == 1
    key = client.get(f"/api/projects/{native_project.id}/keys").json()[0]
    assert key["tags"] == ["c"] and key["occurrences"] == ["z.swift"]


def test_source_change_keeps_translations_but_resets_review(client, native_project):
    _push(client, native_project, {"k": {"string": "Old"}})
    _translate(client, native_project, "es-MX", {"k": {"string": "Viejo", "status": "reviewed"}})
    job = _push(client, native_project, {"k": {"string": "New"}})
    assert job["details"]["updated"] == 1
    assert _content(client, native_project, "es-MX") == {"k": {"string": "Viejo"}}
    assert _content(client, native_project, "es-MX", "?filter[status]=reviewed") == {}


def test_source_change_can_delete_translations(client, native_project):
    _push(client, native_project, {"k": {"string": "Old"}})
    _translate(client, native_project, "es-MX", {"k": "Viejo"})
    _push(client, native_project, {"k": {"string": "New"}}, keep_translations=False)
    assert _content(client, native_project, "es-MX") == {"k": {"string": ""}}


def test_purge_and_dry_run(client, native_project):
    _push(client, native_project, {"a": {"string": "A"}, "b": {"string": "B"}})
    job = _push(client, native_project, {"a": {"string": "A2"}}, purge=True, dry_run=True)
    assert job["details"] == {"created": 0, "updated": 1, "skipped": 0, "deleted": 1, "failed": 0}
    assert _content(client, native_project, "en") == {"a": {"string": "A"}, "b": {"string": "B"}}

    job = _push(client, native_project, {"a": {"string": "A"}}, purge=True)
    assert job["details"]["deleted"] == 1
    assert _content(client, native_project, "en") == {"a": {"string": "A"}}


def test_invalid_entries_are_reported_as_strings(client, native_project):
    job = _push(client, native_project, {"ok": {"string": "Fine"}, "bad": {"meta": {}}, "": {"string": "x"}})
    assert job["status"] == "completed"
    assert job["details"]["created"] == 1 and job["details"]["failed"] == 2
    # The iOS SDK decodes errors as {status, code, title, detail: String, source: [String: String]}
    for error in job["errors"]:
        assert all(isinstance(error[f], str) for f in ("status", "code", "title", "detail"))
        assert all(isinstance(v, str) for v in error["source"].values())


def test_whitespace_key_is_accepted(client, native_project):
    # String Catalogs can contain keys like " " (SwiftUI Text(" "))
    job = _push(client, native_project, {" ": {"string": " "}})
    assert job["details"]["created"] == 1


def test_push_body_errors(client, native_project):
    res = client.post("/cds/content", headers=native_project.write, content=b"not json")
    assert res.status_code == 400 and res.json()["status"] == 400
    res = client.post("/cds/content", headers=native_project.write, json={"data": ["nope"]})
    assert res.status_code == 400


def test_concurrent_push_is_rejected(client, native_project):
    lock = native._project_lock(native_project.id)
    assert lock.acquire(blocking=False)
    try:
        res = client.post("/cds/content", headers=native_project.write, json={"data": {}})
        assert res.status_code == 409
        assert res.json()["message"] == "Another content upload is already in progress"
    finally:
        lock.release()


def test_job_is_scoped_to_project(client, native_project):
    res = client.post("/cds/content", headers=native_project.write, json={"data": {"a": {"string": "A"}}})
    link = res.json()["data"]["links"]["job"]
    other = client.post("/api/projects", json={"name": "Other", "target_languages": []}).json()
    headers = {"Authorization": f"Bearer {other['token']}:{other['secret']}"}
    assert client.get("/cds" + link, headers=headers).status_code == 404
    assert client.get("/cds/jobs/content/unknown", headers=native_project.write).status_code == 404


# --- Pull content ---

def test_content_includes_untranslated_as_empty(client, native_project):
    _push(client, native_project, {"a": {"string": "A"}, "b": {"string": "B"}})
    _translate(client, native_project, "es-MX", {"a": "Á"})
    assert _content(client, native_project, "es-MX") == {"a": {"string": "Á"}, "b": {"string": ""}}
    assert _content(client, native_project, "es-MX", "?filter[status]=translated") == {"a": {"string": "Á"}}


def test_content_filters(client, native_project):
    _push(client, native_project, {
        "a": {"string": "A", "meta": {"tags": ["ios", "home"]}},
        "b": {"string": "B", "meta": {"tags": ["ios"]}},
        "c": {"string": "C"},
    })
    _translate(client, native_project, "fr", {"a": {"string": "a-fr", "status": "reviewed"}, "b": "b-fr",
                                              "c": {"string": "c-fr", "status": "proofread"}})
    assert set(_content(client, native_project, "fr", "?filter[tags]=ios")) == {"a", "b"}
    assert set(_content(client, native_project, "fr", "?filter[tags]=ios,home")) == {"a"}
    assert set(_content(client, native_project, "fr", "?filter[status]=reviewed")) == {"a", "c"}
    assert set(_content(client, native_project, "fr", "?filter[status]=proofread")) == {"c"}
    assert set(_content(client, native_project, "fr", "?filter[status]=finalized")) == {"a", "c"}
    assert set(_content(client, native_project, "fr", "?filter[tags]=ios&filter[status]=reviewed")) == {"a"}
    res = client.get("/cds/content/fr?filter[status]=done", headers=native_project.read)
    assert res.status_code == 400


def test_content_language_codes(client, native_project):
    _push(client, native_project, {"a": {"string": "A"}})
    _translate(client, native_project, "es-MX", {"a": "Á"})
    # Transifex style (underscore) and lowercase codes resolve to the same language
    assert _content(client, native_project, "es_MX") == {"a": {"string": "Á"}}
    assert _content(client, native_project, "es-mx") == {"a": {"string": "Á"}}
    res = client.get("/cds/content/de", headers=native_project.read)
    assert res.status_code == 404
    assert res.json()["status"] == 404


def test_content_etag(client, native_project):
    _push(client, native_project, {"a": {"string": "A"}})
    first = client.get("/cds/content/en", headers=native_project.read)
    etag = first.headers["etag"]
    again = client.get("/cds/content/en", headers={**native_project.read, "If-None-Match": etag})
    assert again.status_code == 304
    _push(client, native_project, {"a": {"string": "A!"}})
    changed = client.get("/cds/content/en", headers={**native_project.read, "If-None-Match": etag})
    assert changed.status_code == 200 and changed.headers["etag"] != etag


def test_reads_accept_token_and_secret(client, native_project):
    # txjs-cli pull authenticates reads with token:secret
    assert client.get("/cds/languages", headers=native_project.write).status_code == 200


# --- Translations import (Flintstone extension) ---

def test_push_translations(client, native_project, db_session):
    _push(client, native_project, {"a": {"string": "Hello"}, "b": {"string": "Bye"}})
    job = _translate(client, native_project, "es-MX", {
        "a": {"string": "Hola"}, "b": {"string": "Adiós", "status": "reviewed"},
        "missing": {"string": "?"}, "empty": {"string": ""},
    })
    assert job["details"] == {"created": 2, "updated": 0, "skipped": 2, "deleted": 0, "failed": 0}

    # existing translations are kept unless override_translations is set
    job = _translate(client, native_project, "es-MX", {"a": "Hola!"})
    assert job["details"]["skipped"] == 1
    job = _translate(client, native_project, "es-MX", {"a": "Hola!"}, override_translations=True)
    assert job["details"]["updated"] == 1
    assert _content(client, native_project, "es-MX")["a"] == {"string": "Hola!"}

    # translation memory learns from imports
    suggestions = client.get("/api/memory/suggest", params={
        "source": "Hello", "source_lang": "en", "target_lang": "es-MX"
    }).json()
    assert "Hola!" in [s["target_text"] for s in suggestions]


def test_push_translations_errors(client, native_project):
    _push(client, native_project, {"a": {"string": "Hello"}})
    job = _translate(client, native_project, "es-MX", {"a": {"string": "Hola", "status": "done"}})
    assert job["details"]["failed"] == 1
    res = client.post("/cds/content/en", headers=native_project.write, json={"data": {"a": "x"}})
    assert res.status_code == 400
    res = client.post("/cds/content/de", headers=native_project.write, json={"data": {"a": "x"}})
    assert res.status_code == 404


# --- Invalidate / purge ---

def test_invalidate_and_purge(client, native_project):
    res = client.post("/cds/invalidate", headers=native_project.write)
    assert res.status_code == 200
    assert res.json() == {"data": {"status": "success", "token": native_project.token, "count": 3}}
    assert client.post("/cds/invalidate/es-MX", headers=native_project.write).json()["data"]["count"] == 1
    assert client.post("/cds/purge", headers=native_project.write).json()["data"]["status"] == "success"
    assert client.post("/cds/invalidate/de", headers=native_project.write).status_code == 404
    trust = {**native_project.read, "X-TRANSIFEX-TRUST-SECRET": native_project.secret}
    assert client.post("/cds/invalidate", headers=trust).status_code == 200


# --- HTTP details ---

def test_cors_for_browser_sdks(client, native_project):
    preflight = client.options("/cds/content/es-MX", headers={
        "Origin": "https://app.example", "Access-Control-Request-Method": "GET",
        "Access-Control-Request-Headers": "authorization,accept-version,x-native-sdk",
    })
    assert preflight.status_code == 204
    assert preflight.headers["access-control-allow-origin"] == "*"
    assert "x-native-sdk" in preflight.headers["access-control-allow-headers"]
    res = client.get("/cds/languages", headers={**native_project.read, "Origin": "https://app.example"})
    assert res.headers["access-control-allow-origin"] == "*"
    # the admin API is not opened up
    api = client.get("/api/projects", headers={"Origin": "https://app.example"})
    assert "access-control-allow-origin" not in api.headers


def test_double_slashes_are_tolerated(client, native_project):
    # cdsHost configured with a trailing slash: "<host>/cds/" + "/content/en"
    assert client.get("/cds//content/en", headers=native_project.read).status_code == 200
    res = client.post("/cds/content", headers=native_project.write, json={"data": {"a": {"string": "A"}}})
    link = res.json()["data"]["links"]["job"]
    assert client.get("/cds/" + link, headers=native_project.write).status_code == 200


def test_health(client):
    assert client.get("/cds/health").json() == {"status": "ok"}

