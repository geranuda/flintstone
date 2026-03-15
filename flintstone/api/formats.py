"""PO and XLIFF format import/export helpers."""

import io
import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape

from sqlalchemy.orm import Session

from ..models import Language, Translation, TranslationKey


def export_po(keys: list[TranslationKey], language: Language, db: Session) -> bytes:
    """Export translations as a PO file."""
    try:
        import polib
    except ImportError:
        raise RuntimeError("polib is required for PO export. Install with: pip install polib")

    po = polib.POFile()
    po.metadata = {
        "Content-Type": "text/plain; charset=utf-8",
        "Content-Transfer-Encoding": "8bit",
        "Language": language.code,
        "Generated-By": "Flintstone 0.1.0",
    }

    for tk in keys:
        t = db.query(Translation).filter(
            Translation.key_id == tk.id,
            Translation.language_id == language.id,
        ).first()
        entry = polib.POEntry(
            msgctxt=tk.key,
            msgid=tk.key,
            msgstr=t.value if t else "",
        )
        if tk.description:
            entry.comment = tk.description
        po.append(entry)

    return str(po).encode("utf-8")


def import_po(content: bytes, project_id: int, language: Language, db: Session) -> dict:
    """Import translations from a PO file."""
    try:
        import polib
    except ImportError:
        raise RuntimeError("polib is required for PO import. Install with: pip install polib")

    try:
        po = polib.pofile(content.decode("utf-8"))
    except Exception as e:
        raise ValueError(f"Invalid PO file: {e}")

    created_keys = 0
    created_translations = 0
    updated_translations = 0

    for entry in po:
        key_name = entry.msgctxt or entry.msgid
        if not key_name:
            continue

        tk = db.query(TranslationKey).filter(
            TranslationKey.project_id == project_id,
            TranslationKey.key == key_name,
        ).first()
        if not tk:
            tk = TranslationKey(project_id=project_id, key=key_name)
            if entry.comment:
                tk.description = entry.comment
            db.add(tk)
            db.flush()
            created_keys += 1

        if entry.msgstr:
            t = db.query(Translation).filter(
                Translation.key_id == tk.id,
                Translation.language_id == language.id,
            ).first()
            if t:
                t.value = entry.msgstr
                updated_translations += 1
            else:
                db.add(Translation(key_id=tk.id, language_id=language.id, value=entry.msgstr))
                created_translations += 1

    return {
        "created_keys": created_keys,
        "created_translations": created_translations,
        "updated_translations": updated_translations,
    }


def export_xliff(
    keys: list[TranslationKey],
    source_language: Language,
    target_language: Language,
    project_name: str,
    db: Session,
) -> bytes:
    """Export translations as XLIFF 1.2."""
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<xliff version="1.2" xmlns="urn:oasis:names:tc:xliff:document:1.2">',
        f'  <file source-language="{escape(source_language.code)}"'
        f' target-language="{escape(target_language.code)}"'
        f' datatype="plaintext" original="{escape(project_name)}">',
        '    <body>',
    ]

    for tk in keys:
        source_t = db.query(Translation).filter(
            Translation.key_id == tk.id,
            Translation.language_id == source_language.id,
        ).first()
        target_t = db.query(Translation).filter(
            Translation.key_id == tk.id,
            Translation.language_id == target_language.id,
        ).first()

        source_text = source_t.value if source_t else tk.key
        target_text = target_t.value if target_t else ""

        lines.append(f'      <trans-unit id="{escape(tk.key)}">')
        lines.append(f'        <source>{escape(source_text)}</source>')
        if target_text:
            lines.append(f'        <target>{escape(target_text)}</target>')
        else:
            lines.append('        <target/>')
        if tk.description:
            lines.append(f'        <note>{escape(tk.description)}</note>')
        lines.append('      </trans-unit>')

    lines.append('    </body>')
    lines.append('  </file>')
    lines.append('</xliff>')
    return '\n'.join(lines).encode("utf-8")


def import_xliff(content: bytes, project_id: int, db: Session) -> dict:
    """Import translations from an XLIFF file."""
    try:
        root = ET.fromstring(content)
    except ET.ParseError as e:
        raise ValueError(f"Invalid XLIFF XML: {e}")

    ns = {"xliff": "urn:oasis:names:tc:xliff:document:1.2"}
    created_keys = 0
    created_translations = 0
    updated_translations = 0

    # Try with namespace first, then without
    files = root.findall("xliff:file", ns)
    if not files:
        files = root.findall("file")

    for file_elem in files:
        source_lang_code = file_elem.get("source-language", "en")
        target_lang_code = file_elem.get("target-language", "")

        # Ensure languages exist
        source_lang = db.query(Language).filter(Language.code == source_lang_code).first()
        if not source_lang:
            source_lang = Language(code=source_lang_code, name=source_lang_code.upper())
            db.add(source_lang)
            db.flush()

        target_lang = None
        if target_lang_code:
            target_lang = db.query(Language).filter(Language.code == target_lang_code).first()
            if not target_lang:
                target_lang = Language(code=target_lang_code, name=target_lang_code.upper())
                db.add(target_lang)
                db.flush()

        body = file_elem.find("xliff:body", ns)
        if body is None:
            body = file_elem.find("body")
        if body is None:
            continue

        trans_units = body.findall("xliff:trans-unit", ns)
        if not trans_units:
            trans_units = body.findall("trans-unit")

        for tu in trans_units:
            key_name = tu.get("id", "")
            if not key_name:
                continue

            tk = db.query(TranslationKey).filter(
                TranslationKey.project_id == project_id,
                TranslationKey.key == key_name,
            ).first()
            if not tk:
                tk = TranslationKey(project_id=project_id, key=key_name)
                note = tu.find("xliff:note", ns) or tu.find("note")
                if note is not None and note.text:
                    tk.description = note.text
                db.add(tk)
                db.flush()
                created_keys += 1

            # Source translation
            source_elem = tu.find("xliff:source", ns) or tu.find("source")
            if source_elem is not None and source_elem.text and source_lang:
                t = db.query(Translation).filter(
                    Translation.key_id == tk.id,
                    Translation.language_id == source_lang.id,
                ).first()
                if t:
                    t.value = source_elem.text
                    updated_translations += 1
                else:
                    db.add(Translation(
                        key_id=tk.id, language_id=source_lang.id, value=source_elem.text
                    ))
                    created_translations += 1

            # Target translation
            target_elem = tu.find("xliff:target", ns) or tu.find("target")
            if target_elem is not None and target_elem.text and target_lang:
                t = db.query(Translation).filter(
                    Translation.key_id == tk.id,
                    Translation.language_id == target_lang.id,
                ).first()
                if t:
                    t.value = target_elem.text
                    updated_translations += 1
                else:
                    db.add(Translation(
                        key_id=tk.id, language_id=target_lang.id, value=target_elem.text
                    ))
                    created_translations += 1

    return {
        "created_keys": created_keys,
        "created_translations": created_translations,
        "updated_translations": updated_translations,
    }
