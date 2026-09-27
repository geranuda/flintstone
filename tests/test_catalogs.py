"""Reading and writing app localization files (String Catalogs, .strings, .stringsdict, XLIFF)."""

import json
import plistlib

from flintstone import catalogs, icu


def _unit(value, state="translated"):
    return {"stringUnit": {"state": state, "value": value}}


def _plural(**forms):
    return {"variations": {"plural": {k: _unit(v) for k, v in forms.items()}}}


CATALOG = {
    "sourceLanguage": "en",
    "strings": {
        "greeting": {
            "comment": "Home title",
            "localizations": {"en": _unit("Hello"), "es-MX": _unit("Hola")},
        },
        "Swift key used as source": {"localizations": {"es-MX": _unit("Clave")}},
        "%lld days": {
            "localizations": {
                "en": _plural(one="%lld day", other="%lld days"),
                "es-MX": _plural(one="%lld día", other="%lld días"),
            }
        },
        "device": {
            "localizations": {
                "en": {"variations": {"device": {
                    "iphone": _unit("This is an iPhone"),
                    "applewatch": _plural(one="%d item on Watch", other="%d items on Watch"),
                }}},
            }
        },
        "found": {
            "localizations": {
                "en": {
                    "stringUnit": {"state": "translated", "value": "Found %#@users@ on %#@devices@"},
                    "substitutions": {
                        "users": {"argNum": 1, "formatSpecifier": "ld", "variations": {"plural": {
                            "one": _unit("%arg user"), "other": _unit("%arg users")}}},
                        "devices": {"argNum": 2, "formatSpecifier": "ld", "variations": {"plural": {
                            "one": _unit("%arg device"), "other": _unit("%arg devices")}}},
                    },
                }
            }
        },
        "draft": {"localizations": {"en": _unit("Draft"), "es-MX": _unit("Borrador", state="new")}},
        "internal": {"shouldTranslate": False, "localizations": {"en": _unit("DEBUG")}},
    },
    "version": "1.0",
}


def _write_catalog(path, doc=CATALOG):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=2, separators=(",", " : "), ensure_ascii=False), encoding="utf-8")
    return path


def test_read_xcstrings(tmp_path):
    path = _write_catalog(tmp_path / "App" / "Localizable.xcstrings")
    catalog = catalogs.read_xcstrings(path, "App/Localizable.xcstrings")
    strings = {s.key: s for s in catalog.strings}

    assert "internal" not in strings  # shouldTranslate: false is not exported
    greeting = strings["greeting"]
    assert (greeting.string, greeting.developer_comment) == ("Hello", "Home title")
    assert greeting.occurrences == ["App/Localizable.xcstrings"]
    assert greeting.translations == {"es-MX": "Hola"}
    # SwiftUI keys without an explicit source value use the key itself
    assert strings["Swift key used as source"].string == "Swift key used as source"
    # Simple plurals become ICU exactly like txios-cli sends them
    assert strings["%lld days"].string == "{cnt, plural, one {%lld day} other {%lld days}}"
    assert strings["%lld days"].translations["es-MX"] == "{cnt, plural, one {%lld día} other {%lld días}}"
    # Untranslated ("new") target values are not migrated
    assert strings["draft"].translations == {}


def test_device_variations_and_substitutions_become_cds_xml(tmp_path):
    catalog = catalogs.read_xcstrings(_write_catalog(tmp_path / "L.xcstrings"), "L.xcstrings")
    strings = {s.key: s.string for s in catalog.strings}
    assert icu.parse_units(strings["device"]) == [
        ("device.iphone", "This is an iPhone"),
        ("device.applewatch.plural.one", "%d item on Watch"),
        ("device.applewatch.plural.other", "%d items on Watch"),
    ]
    # Same shape as the Transifex iOS SDK test fixtures
    assert strings["found"] == (
        '<cds-root><cds-unit id="substitutions">Found %1$#@users@ on %2$#@devices@</cds-unit>'
        '<cds-unit id="substitutions.users.plural.one">%1$ld user</cds-unit>'
        '<cds-unit id="substitutions.users.plural.other">%1$ld users</cds-unit>'
        '<cds-unit id="substitutions.devices.plural.one">%2$ld device</cds-unit>'
        '<cds-unit id="substitutions.devices.plural.other">%2$ld devices</cds-unit></cds-root>'
    )


def test_localization_round_trip():
    for key in ("greeting", "%lld days", "device", "found"):
        source_loc = CATALOG["strings"][key]["localizations"]["en"]
        value = catalogs.xcstrings_value(source_loc)
        assert catalogs.xcstrings_localization(value, source_loc) == catalogs._sort_tree(source_loc), key


def test_plural_without_other_is_incomplete():
    assert catalogs.xcstrings_value(_plural(one="x"), states=catalogs.TRANSLATED_STATES) is None


def test_discover_and_consolidate(tmp_path):
    _write_catalog(tmp_path / "App" / "Localizable.xcstrings")
    watch = {"sourceLanguage": "en", "strings": {
        "greeting": {"localizations": {"en": _unit("Hello")}, "comment": "Watch title"},
        "%lld days": {"localizations": {"en": _unit("%lld days (old)")}},
    }}
    _write_catalog(tmp_path / "Watch" / "Localizable.xcstrings", watch)
    _write_catalog(tmp_path / "App" / "InfoPlist.xcstrings", {"sourceLanguage": "en", "strings": {
        "CFBundleDisplayName": {"localizations": {"en": _unit("App")}}}})
    (tmp_path / "App.xcodeproj").mkdir()
    (tmp_path / "build").mkdir()
    _write_catalog(tmp_path / "build" / "Localizable.xcstrings")

    root, files = catalogs.discover(tmp_path / "App.xcodeproj")
    assert root == tmp_path
    assert [f.relative_to(tmp_path).as_posix() for f in files] == [
        "App/Localizable.xcstrings", "Watch/Localizable.xcstrings",
    ]
    _, with_plist = catalogs.discover(tmp_path, include_unsupported=True)
    assert len(with_plist) == 3
    _, excluded = catalogs.discover(tmp_path, excluded=["Watch/Localizable.xcstrings"])
    assert len(excluded) == 1

    merged, warnings = catalogs.consolidate(catalogs.load(files, root))
    assert merged["greeting"].occurrences == ["App/Localizable.xcstrings", "Watch/Localizable.xcstrings"]
    assert merged["greeting"].developer_comment == "Home title"
    # Conflicting source text: first catalog wins, with a warning
    assert merged["%lld days"].string.startswith("{cnt, plural")
    assert len(warnings) == 1 and warnings[0][0] == "%lld days" and "Watch/" in warnings[0][1]


def test_update_xcstrings_writes_xcode_style(tmp_path):
    path = _write_catalog(tmp_path / "Localizable.xcstrings")
    original = path.read_text(encoding="utf-8")

    # Pulling back what is already there changes nothing, byte for byte
    same = {"es-MX": {"greeting": "Hola", "%lld days": "{cnt, plural, one {%lld día} other {%lld días}}"}}
    assert catalogs.update_xcstrings(path, same) == {}
    assert path.read_text(encoding="utf-8") == original

    changed = catalogs.update_xcstrings(path, {
        "es_MX": {"greeting": "¡Hola!", "%lld days": "{cnt, plural, one {%lld día} many {%lld de días} other {%lld días}}"},
        "fr": {"greeting": "Bonjour", "unknown": "ignored"},
        "en": {"greeting": "ignored: source language"},
    })
    assert changed == {"es-MX": 2, "fr": 1}
    text = path.read_text(encoding="utf-8")
    assert '"value" : "¡Hola!"' in text  # Xcode's " : " separator, no ASCII escaping
    doc = json.loads(text)
    locs = doc["strings"]["greeting"]["localizations"]
    assert list(locs) == ["en", "es-MX", "fr"]
    assert locs["fr"] == _unit("Bonjour")
    assert list(doc["strings"]["%lld days"]["localizations"]["es-MX"]["variations"]["plural"]) == ["many", "one", "other"]
    assert "unknown" not in doc["strings"]


def test_update_xcstrings_substitutions(tmp_path):
    path = _write_catalog(tmp_path / "Localizable.xcstrings")
    value = icu.build_units([
        ("substitutions", "Encontré %1$#@users@ en %2$#@devices@"),
        ("substitutions.users.plural.one", "%1$ld usuario"),
        ("substitutions.users.plural.other", "%1$ld usuarios"),
        ("substitutions.devices.plural.one", "%2$ld dispositivo"),
        ("substitutions.devices.plural.other", "%2$ld dispositivos"),
    ])
    catalogs.update_xcstrings(path, {"es-MX": {"found": value}})
    loc = json.loads(path.read_text(encoding="utf-8"))["strings"]["found"]["localizations"]["es-MX"]
    assert loc["stringUnit"]["value"] == "Encontré %#@users@ en %#@devices@"
    users = loc["substitutions"]["users"]
    assert (users["argNum"], users["formatSpecifier"]) == (1, "ld")
    assert users["variations"]["plural"]["other"]["stringUnit"]["value"] == "%arg usuarios"


def test_strings_and_stringsdict(tmp_path):
    en = tmp_path / "en.lproj"
    es = tmp_path / "es.lproj"
    en.mkdir()
    es.mkdir()
    (en / "Localizable.strings").write_text(
        '/* Greeting on the home screen */\n"greeting" = "Hello \\"friend\\"";\n'
        '// line comment\n"multi" = "Line 1\\nLine 2";\n', encoding="utf-8")
    (es / "Localizable.strings").write_text('"greeting" = "Hola \\"amigo\\"";\n', encoding="utf-16")
    with open(en / "Localizable.stringsdict", "wb") as fh:
        plistlib.dump({
            "%d files": {
                "NSStringLocalizedFormatKey": "%#@files@",
                "files": {"NSStringFormatSpecTypeKey": "NSStringPluralRuleType", "NSStringFormatValueTypeKey": "d",
                          "one": "%d file", "other": "%d files"},
            },
            "summary": {
                "NSStringLocalizedFormatKey": "%#@files@ in %#@folders@",
                "files": {"NSStringFormatSpecTypeKey": "NSStringPluralRuleType", "one": "%d file", "other": "%d files"},
                "folders": {"NSStringFormatSpecTypeKey": "NSStringPluralRuleType", "one": "%d folder", "other": "%d folders"},
            },
        }, fh)

    root, files = catalogs.discover(tmp_path)
    loaded = catalogs.load(files, root)
    strings = {s.key: s for c in loaded for s in c.strings}
    assert strings["greeting"].string == 'Hello "friend"'
    assert strings["greeting"].developer_comment == "Greeting on the home screen"
    assert strings["greeting"].translations == {"es": 'Hola "amigo"'}
    assert strings["multi"].string == "Line 1\nLine 2"
    assert strings["%d files"].string == "{cnt, plural, one {%d file} other {%d files}}"
    units = dict(icu.parse_units(strings["summary"].string))
    assert units["substitutions"] == "%#@files@ in %#@folders@"
    assert units["substitutions.folders.plural.other"] == "%d folders"


XLIFF = """<?xml version="1.0" encoding="UTF-8"?>
<xliff xmlns="urn:oasis:names:tc:xliff:document:1.2" version="1.2">
  <file original="App/Localizable.xcstrings" source-language="en" target-language="{target}" datatype="plaintext">
    <body>
      <trans-unit id="greeting" xml:space="preserve">
        <source>Hello</source><target state="translated">{greeting}</target><note>Home title</note>
      </trans-unit>
      <trans-unit id="%lld days|==|plural.one" xml:space="preserve">
        <source>%lld day</source><target state="translated">{one}</target><note/>
      </trans-unit>
      <trans-unit id="%lld days|==|plural.other" xml:space="preserve">
        <source>%lld days</source><target state="translated">{other}</target><note/>
      </trans-unit>
    </body>
  </file>
</xliff>
"""


def test_xliff_base_and_translation(tmp_path):
    base = tmp_path / "en.xliff"
    base.write_text(XLIFF.format(target="en", greeting="Hello", one="%lld day", other="%lld days"), encoding="utf-8")
    strings = {s.key: s for s in catalogs.read_xliff(base, "en.xliff").strings}
    assert strings["greeting"].string == "Hello" and strings["greeting"].developer_comment == "Home title"
    assert strings["greeting"].occurrences == ["App/Localizable.xcstrings"]
    assert strings["%lld days"].string == "{cnt, plural, one {%lld day} other {%lld days}}"

    es = tmp_path / "es-MX.xliff"
    es.write_text(XLIFF.format(target="es-MX", greeting="Hola", one="%lld día", other="%lld días"), encoding="utf-8")
    strings = {s.key: s for s in catalogs.read_xliff(es, "es-MX.xliff").strings}
    assert strings["greeting"].string == "Hello"
    assert strings["%lld days"].translations == {"es-MX": "{cnt, plural, one {%lld día} other {%lld días}}"}


def test_json_source(tmp_path):
    path = tmp_path / "en.json"
    path.write_text(json.dumps({"home": {"title": "Home", "cta": "Start"}, "flat": "Flat"}), encoding="utf-8")
    strings = {s.key: s.string for s in catalogs.read_json(path, "en.json").strings}
    assert strings == {"home.title": "Home", "home.cta": "Start", "flat": "Flat"}


def test_icu_helpers():
    plural = icu.parse_plural("{cnt, plural, =0 {none} one {# item} other {# items}}")
    assert plural.forms == {"=0": "none", "one": "# item", "other": "# items"}
    assert icu.build_plural(plural.forms, plural.variable) == "{cnt, plural, =0 {none} one {# item} other {# items}}"
    assert icu.build_plural({"one": "", "other": "x"}) == "{cnt, plural, other {x}}"
    assert icu.parse_plural("Hello {name}") is None
    assert icu.parse_plural("{cnt, plural, one {x}}") is None  # "other" is required
    assert icu.kind("<cds-root><cds-unit id=\"device.mac\">Mac</cds-unit></cds-root>") == "variations"
    assert icu.display_length("{cnt, plural, one {ab} other {abcd}}") == 4


def test_empty_units_are_not_written_back():
    value = icu.build_units([("device.iphone", "Toca"), ("device.mac", "")])
    assert catalogs.xcstrings_localization(value) == {"variations": {"device": {"iphone": _unit("Toca")}}}


def test_stringsdict_wins_over_strings_for_the_same_table(tmp_path):
    lproj = tmp_path / "en.lproj"
    lproj.mkdir()
    (lproj / "Localizable.strings").write_text('"%d files" = "%d files";\n"title" = "Files";\n', encoding="utf-8")
    with open(lproj / "Localizable.stringsdict", "wb") as fh:
        plistlib.dump({"%d files": {
            "NSStringLocalizedFormatKey": "%#@files@",
            "files": {"NSStringFormatSpecTypeKey": "NSStringPluralRuleType", "one": "%d file", "other": "%d files"},
        }}, fh)
    root, files = catalogs.discover(tmp_path)
    loaded = catalogs.load(files, root)
    for order in (loaded, list(reversed(loaded))):
        merged, warnings = catalogs.consolidate(order)
        assert merged["%d files"].string == "{cnt, plural, one {%d file} other {%d files}}"
        assert merged["title"].string == "Files"
        assert warnings == []
