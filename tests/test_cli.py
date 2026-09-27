"""`flintstone push` / `pull` / `invalidate` against the app, with HTTP routed through TestClient."""

import json

import pytest

from flintstone import cli
from flintstone.client import CDSClient, CDSClientError

from .test_catalogs import _write_catalog


@pytest.fixture
def cds(client, monkeypatch):
    """Send CDSClient requests to the in-process app instead of the network."""

    def request(self, method, path, body=None, with_secret=False, params=None):
        credentials = f"{self.token}:{self.secret}" if with_secret and self.secret else self.token
        res = client.request(method, "/cds" + path, json=body, params=params,
                             headers={"Authorization": f"Bearer {credentials}", "X-NATIVE-SDK": "flintstone/cli/test"})
        if res.status_code >= 400:
            raise CDSClientError(res.status_code, res.json().get("message", res.text))
        return res.status_code, (res.json() if res.content else None)

    monkeypatch.setattr(CDSClient, "_request", request)
    for name in ("FLINTSTONE_TOKEN", "FLINTSTONE_SECRET", "TRANSIFEX_TOKEN", "TRANSIFEX_SECRET"):
        monkeypatch.delenv(name, raising=False)
    return client


def _credentials(project):
    return ["--token", project.token, "--secret", project.secret, "--cds-host", "http://testserver/cds"]


def test_push_with_translations_then_pull(cds, native_project, tmp_path, capsys):
    app = tmp_path / "MyApp"
    _write_catalog(app / "App" / "Localizable.xcstrings")
    (app / "MyApp.xcodeproj").mkdir()

    code = cli.main(["push", "--project", str(app / "MyApp.xcodeproj"), "--with-translations",
                     "--append-tags", "ios", *_credentials(native_project)])
    out = capsys.readouterr().out
    assert code == 0, out
    assert "Found 6 source strings in 1 file(s)" in out
    assert "Source strings pushed: 6 created" in out
    assert "es-MX translations: 3 created" in out

    content = cds.get("/cds/content/es-MX", headers=native_project.read).json()["data"]
    assert content["greeting"] == {"string": "Hola"}
    assert content["%lld days"] == {"string": "{cnt, plural, one {%lld día} other {%lld días}}"}
    keys = {k["key"]: k for k in cds.get(f"/api/projects/{native_project.id}/keys").json()}
    assert keys["greeting"]["tags"] == ["ios"]
    assert keys["greeting"]["occurrences"] == ["App/Localizable.xcstrings"]

    # Translate something in Flintstone, then pull it back
    es_id = next(l["id"] for l in cds.get("/api/languages").json() if l["code"] == "es-MX")
    cds.put(f"/api/translations/{keys['draft']['id']}/{es_id}", json={"value": "Borrador"})

    out_dir = tmp_path / "bundle"
    assert cli.main(["pull", "--output", str(out_dir), *_credentials(native_project)]) == 0
    bundle = json.loads((out_dir / "txstrings.json").read_text(encoding="utf-8"))
    assert set(bundle) == {"en", "es-MX", "fr"}
    assert bundle["es-MX"]["draft"] == {"string": "Borrador"}
    assert bundle["en"]["greeting"] == {"string": "Hello"}

    # ...or straight into the String Catalog
    assert cli.main(["pull", "--update-catalogs", "--translated-locales", "es-MX", "--project", str(app),
                     *_credentials(native_project)]) == 0
    doc = json.loads((app / "App" / "Localizable.xcstrings").read_text(encoding="utf-8"))
    assert doc["strings"]["draft"]["localizations"]["es-MX"] == {
        "stringUnit": {"state": "translated", "value": "Borrador"}
    }
    assert "updated" not in capsys.readouterr().err


def test_push_dry_run_changes_nothing(cds, native_project, tmp_path, capsys):
    _write_catalog(tmp_path / "Localizable.xcstrings")
    assert cli.main(["push", "--project", str(tmp_path), "--dry-run", *_credentials(native_project)]) == 0
    assert "dry run" in capsys.readouterr().out
    assert cds.get(f"/api/projects/{native_project.id}/keys").json() == []


def test_push_skips_languages_not_in_project(cds, tmp_path, capsys):
    project = cds.post("/api/projects", json={"name": "EnOnly", "target_languages": ["fr"]}).json()
    creds = ["--token", project["token"], "--secret", project["secret"]]
    _write_catalog(tmp_path / "Localizable.xcstrings")
    assert cli.main(["push", "--project", str(tmp_path), "--with-translations", *creds]) == 0
    assert "Skipping 3 'es-MX' translations" in capsys.readouterr().err


def test_push_requires_credentials(cds, tmp_path, capsys):
    _write_catalog(tmp_path / "Localizable.xcstrings")
    with pytest.raises(SystemExit):
        cli.main(["push", "--project", str(tmp_path)])
    assert "missing token" in capsys.readouterr().err


def test_push_env_credentials_and_bad_secret(cds, native_project, tmp_path, monkeypatch, capsys):
    _write_catalog(tmp_path / "Localizable.xcstrings")
    monkeypatch.setenv("TRANSIFEX_TOKEN", native_project.token)
    monkeypatch.setenv("TRANSIFEX_SECRET", "wrong")
    assert cli.main(["push", "--project", str(tmp_path)]) == 1
    assert "403" in capsys.readouterr().err
    monkeypatch.setenv("FLINTSTONE_SECRET", native_project.secret)
    assert cli.main(["push", "--project", str(tmp_path)]) == 0


def test_push_nothing_found(cds, native_project, tmp_path, capsys):
    assert cli.main(["push", "--project", str(tmp_path), *_credentials(native_project)]) == 1
    assert "no localizable strings found" in capsys.readouterr().err


def test_pull_missing_locale(cds, native_project, tmp_path, capsys):
    args = ["pull", "--translated-locales", "es-MX", "de", "--output", str(tmp_path), *_credentials(native_project)]
    assert cli.main(args) == 1
    assert cli.main(args + ["--ignore-missing-locales"]) == 0
    assert set(json.loads((tmp_path / "txstrings.json").read_text())) == {"es-MX"}


def test_invalidate(cds, native_project, capsys):
    assert cli.main(["invalidate", *_credentials(native_project)]) == 0
    assert "invalidated (3 languages)" in capsys.readouterr().out


def test_serve_is_the_default(monkeypatch):
    calls = []
    monkeypatch.setattr(cli, "cmd_serve", lambda args: calls.append(args) or 0)
    assert cli.main([]) == 0 and len(calls) == 1
