"""Read and write localizable strings in app projects (``flintstone push`` / ``pull``).

Reads Apple String Catalogs (``.xcstrings``), ``.strings`` / ``.stringsdict``
files, XLIFF exports and JSON, and turns them into the shape Transifex's iOS CLI
sends to the CDS:

* key: the catalog key, unchanged (what ``NSLocalizedString`` / SwiftUI look up)
* string: the source-language value; simple plural variations become ICU
  (``{cnt, plural, one {...} other {...}}``) and device variations or
  substitutions become ``<cds-root>`` XML
* occurrences: the files the key was found in, relative to the project root
* developer comment: the catalog comment

Pulled translations can be written back into String Catalogs, so translations
made in Flintstone ship with the app even without the Native SDK.
"""

import json
import os
import plistlib
import re
import xml.etree.ElementTree as ET
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from . import icu, locales

# Files the Transifex iOS SDK cannot serve over the air (managed by the OS).
UNSUPPORTED_FILES = ("InfoPlist.xcstrings", "InfoPlist.strings", "Root.strings")
SKIP_DIRS = {".git", ".build", ".swiftpm", "build", "DerivedData", "Pods", "Carthage", "node_modules", "xcuserdata"}
TRANSLATED_STATES = {"translated", "needs_review"}
_XLIFF_NS = "{urn:oasis:names:tc:xliff:document:1.2}"
_TOKEN = re.compile(r"%(\d+\$)?#@([^@]+)@")


@dataclass
class SourceString:
    key: str
    string: str
    developer_comment: str = ""
    occurrences: list[str] = field(default_factory=list)
    translations: dict[str, str] = field(default_factory=dict)  # language code -> value
    origin: str = ""

    def payload(self, tags: list[str] | None = None) -> dict:
        meta: dict = {"occurrences": list(self.occurrences)}
        if self.developer_comment:
            meta["developer_comment"] = self.developer_comment
        if tags:
            meta["tags"] = list(tags)
        return {"string": self.string, "meta": meta}


@dataclass
class Catalog:
    path: Path
    rel: str
    format: str
    source_language: str
    strings: list[SourceString]


class CatalogError(Exception):
    pass


# --- Discovery ---

def discover(project: str | Path, include_unsupported: bool = False,
             excluded: list[str] | None = None) -> tuple[Path, list[Path]]:
    """Return ``(root, files)`` for a project path.

    ``project`` may be an ``.xcodeproj`` / ``.xcworkspace`` (its folder is
    scanned), a directory, or a single localization file.
    """
    project = Path(project).expanduser()
    if not project.exists():
        raise CatalogError(f"Path not found: {project}")
    if project.is_file():
        cwd = Path.cwd().resolve()
        root = cwd if project.resolve().is_relative_to(cwd) else project.parent
        return root, [project]
    root = project.parent if project.suffix in (".xcodeproj", ".xcworkspace") else project
    skip_names = set(excluded or [])
    if not include_unsupported:
        skip_names.update(UNSUPPORTED_FILES)
    files = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(
            d for d in dirnames
            if d not in SKIP_DIRS and not d.endswith((".xcodeproj", ".xcworkspace", ".xcassets", ".xcframework"))
        )
        folder = Path(dirpath)
        for name in sorted(filenames):
            path = folder / name
            if name in skip_names or str(path.relative_to(root)) in skip_names:
                continue
            if name.endswith(".xcstrings"):
                files.append(path)
            elif name.endswith((".strings", ".stringsdict")) and folder.suffix == ".lproj":
                files.append(path)
    return root, files


def _rel(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.name


def load(paths: list[Path], root: Path, source_locale: str = "en") -> list[Catalog]:
    """Parse files into catalogs. ``.strings``/``.stringsdict`` files of all
    ``xx.lproj`` folders are merged into one catalog per source file."""
    catalogs = []
    lproj_groups: dict[tuple[Path, str], dict[str, Path]] = {}
    for path in paths:
        suffix = path.suffix
        if suffix in (".strings", ".stringsdict") and path.parent.suffix == ".lproj":
            lang = path.parent.stem
            lproj_groups.setdefault((path.parent.parent, path.name), {})[lang] = path
            continue
        rel = _rel(path, root)
        if suffix == ".xcstrings":
            catalogs.append(read_xcstrings(path, rel))
        elif suffix == ".xliff":
            catalogs.append(read_xliff(path, rel, source_locale))
        elif suffix == ".json":
            catalogs.append(read_json(path, rel, source_locale))
        elif suffix in (".strings", ".stringsdict"):
            catalogs.append(_read_lproj_group({source_locale: path}, rel, source_locale))
        else:
            raise CatalogError(f"Unsupported file type: {path}")
    for (_, name), by_lang in sorted(lproj_groups.items()):
        source_path = by_lang.get(source_locale) or by_lang.get("Base") or by_lang.get("en")
        if source_path is None:
            continue
        catalogs.append(_read_lproj_group(by_lang, _rel(source_path, root), source_locale))
    return catalogs


def consolidate(catalogs: list[Catalog]) -> tuple[dict[str, SourceString], list[tuple[str, str]]]:
    """Merge catalogs into one string per key, like the Transifex iOS CLI.

    Occurrences of the same key are combined. When the source text differs
    between files, the first catalog wins and a ``(key, message)`` warning is
    returned.
    """
    merged: dict[str, SourceString] = {}
    warnings = []
    for catalog in catalogs:
        for s in catalog.strings:
            current = merged.get(s.key)
            if current is None:
                merged[s.key] = SourceString(
                    key=s.key, string=s.string, developer_comment=s.developer_comment,
                    occurrences=list(s.occurrences), translations=dict(s.translations), origin=s.origin,
                )
                continue
            for occurrence in s.occurrences:
                if occurrence not in current.occurrences:
                    current.occurrences.append(occurrence)
            if _same_table(current.origin, s.origin):
                # iOS resolves a key from Table.stringsdict before Table.strings
                if s.origin.endswith(".stringsdict") and current.origin.endswith(".strings"):
                    current.string, current.origin = s.string, s.origin
                    current.translations = {**current.translations, **s.translations}
                elif s.origin.endswith(".strings") and current.origin.endswith(".stringsdict"):
                    for lang, value in s.translations.items():
                        current.translations.setdefault(lang, value)
                if not current.developer_comment and s.developer_comment:
                    current.developer_comment = s.developer_comment
                continue
            if current.string != s.string:
                warnings.append((s.key, (
                    f"{s.key!r}: source differs in {s.origin} ({_short(s.string)}); "
                    f"keeping {current.origin} ({_short(current.string)})"
                )))
                continue
            if not current.developer_comment and s.developer_comment:
                current.developer_comment = s.developer_comment
            for lang, value in s.translations.items():
                current.translations.setdefault(lang, value)
    return merged, warnings


def _same_table(a: str, b: str) -> bool:
    """``en.lproj/Localizable.strings`` and ``en.lproj/Localizable.stringsdict``."""
    return a != b and a.rsplit(".", 1)[0] == b.rsplit(".", 1)[0]


def _short(text: str, limit: int = 40) -> str:
    text = text.replace("\n", " ")
    return repr(text if len(text) <= limit else text[:limit - 1] + "…")


# --- String Catalogs (.xcstrings) ---

def _flatten_variations(variations: dict, prefix: str = "") -> list[tuple[str, str, str]]:
    """``{"plural": {"one": {...}}}`` -> ``[("plural.one", value, state), ...]``."""
    out = []
    for vtype, cases in (variations or {}).items():
        items = cases.items()
        if vtype == "plural":
            items = sorted(items, key=lambda kv: locales.PLURAL_ORDER.index(kv[0]) if kv[0] in locales.PLURAL_ORDER else 99)
        for case, node in items:
            path = f"{prefix}{vtype}.{case}"
            if not isinstance(node, dict):
                continue
            if "variations" in node:
                out.extend(_flatten_variations(node["variations"], path + "."))
            elif "stringUnit" in node:
                unit = node["stringUnit"]
                out.append((path, unit.get("value", ""), unit.get("state", "translated")))
    return out


def _positional(phrase: str, substitutions: dict) -> str:
    """``%#@arg1@`` -> ``%1$#@arg1@`` using each substitution's argNum (as Xcode exports)."""
    def replace(match):
        if match.group(1):
            return match.group(0)
        arg = (substitutions.get(match.group(2)) or {}).get("argNum")
        return f"%{arg}$#@{match.group(2)}@" if arg else match.group(0)
    return _TOKEN.sub(replace, phrase)


def _substitution_units(substitutions: dict, states: set | None) -> list[tuple[str, str]]:
    units = []
    for name, sub in substitutions.items():
        arg = sub.get("argNum")
        spec = sub.get("formatSpecifier") or "lld"
        placeholder = f"%{arg}${spec}" if arg else f"%{spec}"
        for path, value, state in _flatten_variations(sub.get("variations") or {}):
            if states is None or state in states:
                units.append((f"substitutions.{name}.{path}", value.replace("%arg", placeholder)))
    return units


def xcstrings_value(loc: dict | None, states: set | None = None, fallback: str | None = None) -> str | None:
    """CDS string for one String Catalog localization, or None if not translated.

    ``states`` limits which ``stringUnit`` states count (None = all).
    ``fallback`` is used as the main phrase when the localization is missing
    (source strings default to their key).
    """
    if not isinstance(loc, dict):
        return fallback
    unit = loc.get("stringUnit") if isinstance(loc.get("stringUnit"), dict) else None
    unit_ok = unit is not None and (states is None or unit.get("state", "translated") in states)
    substitutions = loc.get("substitutions") or {}
    if loc.get("variations"):
        flat = [(p, v) for p, v, st in _flatten_variations(loc["variations"]) if states is None or st in states]
        if not flat:
            return None
        if not substitutions and all(p.startswith("plural.") and p.count(".") == 1 for p, _ in flat):
            forms = {p.split(".", 1)[1]: v for p, v in flat}
            return icu.build_plural(forms) if "other" in forms else None
        return icu.build_units(flat + _substitution_units(substitutions, states))
    if substitutions:
        main = unit.get("value") if unit_ok else fallback
        if main is None:
            return None
        return icu.build_units(
            [("substitutions", _positional(main, substitutions))] + _substitution_units(substitutions, states)
        )
    if unit_ok:
        return unit.get("value", "")
    return fallback


def read_xcstrings(path: Path, rel: str) -> Catalog:
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise CatalogError(f"Cannot read {path}: {exc}")
    source_language = doc.get("sourceLanguage", "en")
    strings = []
    for key, entry in (doc.get("strings") or {}).items():
        if entry.get("shouldTranslate") is False:
            continue
        localizations = entry.get("localizations") or {}
        source = xcstrings_value(localizations.get(source_language), fallback=key)
        if source is None:
            source = key
        translations = {}
        for lang, loc in localizations.items():
            if lang == source_language:
                continue
            value = xcstrings_value(loc, states=TRANSLATED_STATES)
            if value:
                translations[lang] = value
        strings.append(SourceString(
            key=key, string=source, developer_comment=entry.get("comment") or "",
            occurrences=[rel], translations=translations, origin=rel,
        ))
    return Catalog(path=path, rel=rel, format="xcstrings", source_language=source_language, strings=strings)


def _set_variation(variations: dict, parts: list[str], text: str) -> None:
    """Place ``text`` at ``plural.one`` / ``device.iphone.plural.one`` in a variations tree."""
    vtype, case, rest = parts[0], parts[1], parts[2:]
    node = variations.setdefault(vtype, {}).setdefault(case, {})
    if rest:
        _set_variation(node.setdefault("variations", {}), rest, text)
    else:
        node["stringUnit"] = {"state": "translated", "value": text}


def _sort_tree(node):
    if isinstance(node, dict):
        return {k: _sort_tree(node[k]) for k in sorted(node)}
    return node


def xcstrings_localization(value: str, source_loc: dict | None = None) -> dict:
    """Inverse of :func:`xcstrings_value`: a CDS string as a catalog localization."""
    plural = icu.parse_plural(value)
    if plural:
        variations: dict = {}
        for case, text in plural.forms.items():
            if not case.startswith("="):
                _set_variation(variations, ["plural", case], text)
        return _sort_tree({"variations": variations})
    units = icu.parse_units(value)
    if units is None:
        return {"stringUnit": {"state": "translated", "value": value}}
    source_subs = (source_loc or {}).get("substitutions") or {}
    source_main = ((source_loc or {}).get("stringUnit") or {}).get("value", "")
    loc: dict = {}
    for uid, text in units:
        if not text:
            continue  # an empty "translated" unit would show blank text in the app
        parts = uid.split(".")
        if parts[0] == "substitutions" and len(parts) == 1:
            if not re.search(r"%\d+\$#@", source_main):
                text = _TOKEN.sub(lambda m: f"%#@{m.group(2)}@", text)
            loc["stringUnit"] = {"state": "translated", "value": text}
        elif parts[0] == "substitutions" and len(parts) >= 4:
            name = parts[1]
            spec_source = source_subs.get(name) or {}
            sub = loc.setdefault("substitutions", {}).setdefault(
                name, {k: v for k, v in spec_source.items() if k != "variations"}
            )
            arg, spec = spec_source.get("argNum"), spec_source.get("formatSpecifier") or "lld"
            if arg:
                text = text.replace(f"%{arg}${spec}", "%arg")
            _set_variation(sub.setdefault("variations", {}), parts[2:], text)
        elif len(parts) >= 2 and len(parts) % 2 == 0:
            _set_variation(loc.setdefault("variations", {}), parts, text)
    return _sort_tree(loc)


def update_xcstrings(path: Path, translations: dict[str, dict[str, str]]) -> Counter:
    """Write pulled translations (``{lang: {key: value}}``) into a String Catalog.

    Only keys that exist in the catalog are touched, unchanged values keep their
    state, and the file is written in Xcode's own JSON style so diffs stay small.
    Returns the number of updated strings per language.
    """
    raw = path.read_text(encoding="utf-8")
    doc = json.loads(raw)
    source_language = doc.get("sourceLanguage", "en")
    changed: Counter = Counter()
    for key, entry in (doc.get("strings") or {}).items():
        if entry.get("shouldTranslate") is False:
            continue
        localizations = entry.get("localizations") or {}
        source_loc = localizations.get(source_language)
        entry_changed = False
        for lang, values in translations.items():
            if locales.same_code(lang, source_language):
                continue
            value = values.get(key)
            if not value:
                continue
            code = next((c for c in localizations if locales.same_code(c, lang)), locales.normalize_code(lang))
            if xcstrings_value(localizations.get(code), states=TRANSLATED_STATES) == value:
                continue  # same text, already marked translated
            localizations[code] = xcstrings_localization(value, source_loc)
            changed[code] += 1
            entry_changed = True
        if entry_changed:
            entry["localizations"] = {k: localizations[k] for k in sorted(localizations)}
    if changed:
        text = json.dumps(doc, indent=2, separators=(",", " : "), ensure_ascii=False)
        if raw.endswith("\n"):
            text += "\n"
        path.write_text(text, encoding="utf-8")
    return changed


# --- .strings / .stringsdict ---

_STRINGS_ENTRY = re.compile(
    r'/\*(?P<comment>.*?)\*/|//(?P<line>[^\n]*)|"(?P<key>(?:[^"\\]|\\.)*)"\s*=\s*"(?P<value>(?:[^"\\]|\\.)*)"\s*;',
    re.S,
)
_ESCAPES = {"n": "\n", "t": "\t", "r": "\r", '"': '"', "\\": "\\", "'": "'", "0": "\0"}


def _unescape(text: str) -> str:
    def replace(match):
        body = match.group(1)
        if body[0] in "uU":
            return chr(int(body[1:], 16))
        return _ESCAPES.get(body, body)
    return re.sub(r"\\([uU][0-9a-fA-F]{4}|.)", replace, text)


def _read_text(path: Path) -> str:
    data = path.read_bytes()
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return data.decode("utf-16")
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("utf-16")


def read_strings(path: Path) -> dict[str, tuple[str, str]]:
    """``{key: (value, comment)}`` from an old-style ``.strings`` file."""
    entries = {}
    comment = ""
    for match in _STRINGS_ENTRY.finditer(_read_text(path)):
        if match.group("comment") is not None:
            comment = match.group("comment").strip()
        elif match.group("key") is not None:
            entries[_unescape(match.group("key"))] = (_unescape(match.group("value")), comment)
            comment = ""
    return entries


def read_stringsdict(path: Path) -> dict[str, str]:
    """``{key: CDS string}`` from a ``.stringsdict`` plist."""
    try:
        with path.open("rb") as fh:
            plist = plistlib.load(fh)
    except (OSError, plistlib.InvalidFileException, ValueError) as exc:
        raise CatalogError(f"Cannot read {path}: {exc}")
    out = {}
    for key, spec in plist.items():
        if not isinstance(spec, dict):
            continue
        fmt = spec.get("NSStringLocalizedFormatKey", "")
        rules = {
            name: {c: v for c, v in rule.items() if c in locales.PLURAL_ORDER}
            for name, rule in spec.items()
            if isinstance(rule, dict) and rule.get("NSStringFormatSpecTypeKey") == "NSStringPluralRuleType"
        }
        single = _TOKEN.fullmatch(fmt)
        if single and single.group(2) in rules:
            out[key] = icu.build_plural(rules[single.group(2)])
        elif rules:
            units = [("substitutions", fmt)]
            for name, forms in rules.items():
                for case, text in forms.items():
                    units.append((f"substitutions.{name}.plural.{case}", text))
            out[key] = icu.build_units(units)
    return out


def _read_lproj_group(by_lang: dict[str, Path], rel: str, source_locale: str) -> Catalog:
    def values(path: Path) -> dict[str, tuple[str, str]]:
        if path.suffix == ".stringsdict":
            return {k: (v, "") for k, v in read_stringsdict(path).items()}
        return read_strings(path)

    source_path = by_lang.get(source_locale) or by_lang.get("Base") or by_lang.get("en")
    source = values(source_path)
    others = {lang: values(p) for lang, p in by_lang.items() if p != source_path and lang != "Base"}
    strings = [
        SourceString(
            key=key, string=value, developer_comment=comment, occurrences=[rel], origin=rel,
            translations={lang: vals[key][0] for lang, vals in others.items() if vals.get(key, ("",))[0]},
        )
        for key, (value, comment) in source.items()
    ]
    return Catalog(path=source_path, rel=rel, format=source_path.suffix.lstrip("."),
                   source_language=source_locale, strings=strings)


# --- XLIFF (e.g. ``xcodebuild -exportLocalizations``) ---

def read_xliff(path: Path, rel: str, source_locale: str = "en") -> Catalog:
    try:
        root = ET.parse(path).getroot()
    except (OSError, ET.ParseError) as exc:
        raise CatalogError(f"Cannot read {path}: {exc}")
    strings = []

    def text_of(el):
        return "".join(el.itertext()) if el is not None else None

    for file_el in root.iter(f"{_XLIFF_NS}file"):
        original = file_el.get("original") or rel
        source_lang = file_el.get("source-language") or source_locale
        target_lang = file_el.get("target-language") or source_lang
        is_translation = not locales.same_code(target_lang, source_lang)
        units: dict[str, tuple[str, str | None, str]] = {}
        rules: dict[str, list[tuple[str, str, str | None]]] = {}
        for tu in file_el.iter(f"{_XLIFF_NS}trans-unit"):
            uid = tu.get("id") or ""
            source = text_of(tu.find(f"{_XLIFF_NS}source")) or ""
            target_el = tu.find(f"{_XLIFF_NS}target")
            target = text_of(target_el)
            if target_el is not None and target_el.get("state") in ("new", "needs-translation"):
                target = None
            note = text_of(tu.find(f"{_XLIFF_NS}note")) or ""
            if "|==|" in uid:
                base, rule = uid.split("|==|", 1)
                rules.setdefault(base, []).append((rule, source, target))
            else:
                units[uid] = (source, target, note)
        for base in rules:
            units.setdefault(base, (base, base, ""))

        for uid, (source, target, note) in units.items():
            def combine(pick):
                parts = [(rule, pick(s, t)) for rule, s, t in rules.get(uid, [])]
                if not parts:
                    return None
                if any(value is None for _, value in parts):
                    return None
                if all(r.startswith("plural.") and r.count(".") == 1 for r, _ in parts):
                    return icu.build_plural({r.split(".", 1)[1]: v for r, v in parts})
                main = pick(source, target)
                head = [("substitutions", main)] if any(r.startswith("substitutions.") for r, _ in parts) else []
                return icu.build_units(head + parts)

            if is_translation:
                src_value = combine(lambda s, t: s) or source
                tgt_value = combine(lambda s, t: t) or (target if not rules.get(uid) else None)
            else:
                src_value = combine(lambda s, t: t if t is not None else s) or (target if target is not None else source)
                tgt_value = None
            strings.append(SourceString(
                key=uid, string=src_value, developer_comment=note, occurrences=[original], origin=original,
                translations={target_lang: tgt_value} if tgt_value else {},
            ))
    return Catalog(path=path, rel=rel, format="xliff", source_language=source_locale, strings=strings)


# --- JSON (flat or nested key/value) ---

def read_json(path: Path, rel: str, source_locale: str = "en") -> Catalog:
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise CatalogError(f"Cannot read {path}: {exc}")
    if not isinstance(doc, dict):
        raise CatalogError(f"{path}: expected a JSON object")

    flat: dict[str, str] = {}

    def walk(node, prefix):
        for k, v in node.items():
            name = f"{prefix}.{k}" if prefix else str(k)
            if isinstance(v, dict):
                walk(v, name)
            elif v is not None:
                flat[name] = str(v)

    walk(doc, "")
    strings = [SourceString(key=k, string=v, occurrences=[rel], origin=rel) for k, v in flat.items()]
    return Catalog(path=path, rel=rel, format="json", source_language=source_locale, strings=strings)
