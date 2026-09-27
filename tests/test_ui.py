"""Web UI pages render with Native content."""

from flintstone.ui.views import highlight_placeholders, short_file, show_key


def _seed(client, project):
    client.post("/cds/content", headers=project.write, json={"data": {
        "greeting": {"string": "Hello %@", "meta": {"developer_comment": "Home <title>",
                                                   "occurrences": ["App/Sub/Localizable.xcstrings"],
                                                   "tags": ["ui"], "character_limit": 10}},
        "%lld days": {"string": "{cnt, plural, one {%lld day} other {%lld days}}"},
        "device": {"string": '<cds-root><cds-unit id="device.iphone">iPhone</cds-unit>'
                             '<cds-unit id="device.mac">Mac</cds-unit></cds-root>'},
    }})
    client.post("/cds/content/es-MX", headers=project.write, json={"data": {"greeting": "Hola %@"}})


def test_dashboard(client, native_project):
    _seed(client, native_project)
    res = client.get("/")
    assert res.status_code == 200
    assert "App" in res.text and "es-MX" in res.text and "3</strong> strings" in res.text


def test_project_page(client, native_project):
    _seed(client, native_project)
    res = client.get(f"/projects/{native_project.id}")
    assert res.status_code == 200
    html = res.text
    assert native_project.token in html
    assert native_project.secret not in html
    assert 'setCDSHost("http://testserver/cds")' in html
    assert "App/Sub/Localizable.xcstrings" in html
    assert "source strings" in html and "Spanish (Mexico)" in html


def test_editor(client, native_project):
    _seed(client, native_project)
    res = client.get(f"/projects/{native_project.id}/translate?lang=es-MX")
    assert res.status_code == 200
    html = res.text
    assert 'data-form="one"' in html and 'data-form="many"' in html and 'data-form="other"' in html
    assert "Optional: large round numbers" in html  # Spanish "many"
    assert 'data-unit="device.mac"' in html
    assert "Home &lt;title&gt;" in html  # developer comments are escaped
    assert '<span class="ph">%@</span>' in html
    assert "0/10" not in html and "7/10" in html  # character limit counter
    fr = client.get(f"/projects/{native_project.id}/translate?lang=fr&status=untranslated&q=day")
    assert fr.status_code == 200 and "%lld days" in fr.text


def test_editor_without_targets(client):
    project = client.post("/api/projects", json={"name": "Solo", "target_languages": []}).json()
    res = client.get(f"/projects/{project['id']}/translate")
    assert res.status_code == 200 and "No target languages yet" in res.text


def test_other_pages(client, native_project):
    assert client.get(f"/projects/{native_project.id}/import-export").status_code == 200
    assert client.get("/projects/999").status_code == 404
    assert client.get("/projects/999/translate").status_code == 404
    assert client.get("/api/docs").status_code == 200
    assert client.get("/static/vendor/pico.min.css").status_code == 200


def test_filters():
    assert str(highlight_placeholders("Hi %1$@, <b>%lld</b> 100%% {name}")) == (
        'Hi <span class="ph">%1$@</span>, &lt;b&gt;<span class="ph">%lld</span>&lt;/b&gt; 100'
        '<span class="ph">%%</span> <span class="ph">{name}</span>'
    )
    assert short_file("Spoon Watch App/Localization/Localizable.xcstrings") == "Spoon Watch App/…/Localizable.xcstrings"
    assert short_file("Localizable.xcstrings") == "Localizable.xcstrings"
    assert "␣" in str(highlight_placeholders(" ")) and "␣" in str(show_key(" "))
    assert str(show_key("a<b")) == "a&lt;b"
