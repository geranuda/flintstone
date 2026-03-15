"""TMX (Translation Memory eXchange) import/export endpoints."""

import io
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from xml.sax.saxutils import escape

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Language, Project, Translation, TranslationKey, TranslationMemory

router = APIRouter(tags=["tmx"])


def _parse_tmx(content: bytes) -> list[dict]:
    """Parse a TMX file and return translation units.

    Each unit is: {"source_lang": ..., "segments": {"en": "Hello", "fr": "Bonjour"}}
    """
    try:
        root = ET.fromstring(content)
    except ET.ParseError as e:
        raise HTTPException(400, f"Invalid TMX XML: {e}")

    # TMX header has srclang attribute
    header = root.find("header")
    source_lang = header.get("srclang", "en") if header is not None else "en"
    # Normalize *all to empty (means source lang varies per TU)
    if source_lang == "*all*":
        source_lang = ""

    body = root.find("body")
    if body is None:
        raise HTTPException(400, "TMX file has no <body> element")

    units = []
    for tu in body.findall("tu"):
        segments = {}
        tu_src = tu.get("srclang", source_lang)
        for tuv in tu.findall("tuv"):
            lang = tuv.get("{http://www.w3.org/XML/1998/namespace}lang") or tuv.get("lang", "")
            seg = tuv.find("seg")
            if seg is not None and seg.text:
                # Normalize lang codes: en-US -> en, pt-BR stays pt-BR
                segments[lang.lower()] = seg.text.strip()
        if segments:
            units.append({"source_lang": tu_src.lower() if tu_src else "", "segments": segments})

    return units


def _generate_tmx(entries: list[dict], source_lang: str = "en") -> str:
    """Generate TMX 1.4 XML from translation entries.

    Each entry: {"segments": {"en": "Hello", "fr": "Bonjour"}}
    """
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<!DOCTYPE tmx SYSTEM "tmx14.dtd">',
        '<tmx version="1.4">',
        f'  <header creationtool="Flintstone" creationtoolversion="0.1.0"'
        f' datatype="plaintext" segtype="sentence"'
        f' adminlang="en" srclang="{escape(source_lang)}"'
        f' o-tmf="Flintstone"/>',
        '  <body>',
    ]

    for entry in entries:
        lines.append('    <tu>')
        for lang, text in sorted(entry["segments"].items()):
            lines.append(f'      <tuv xml:lang="{escape(lang)}">')
            lines.append(f'        <seg>{escape(text)}</seg>')
            lines.append('      </tuv>')
        lines.append('    </tu>')

    lines.append('  </body>')
    lines.append('</tmx>')
    return '\n'.join(lines)


# --- Import TMX into a project ---

@router.post("/api/projects/{project_id}/import/tmx")
async def import_tmx(
    project_id: int,
    file: UploadFile = File(...),
    source_lang: str = Query("en", description="Source language code for keys"),
    db: Session = Depends(get_db),
):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(404, "Project not found")

    content = await file.read()
    units = _parse_tmx(content)

    created_keys = 0
    created_translations = 0
    updated_translations = 0
    tm_entries_added = 0

    for unit in units:
        segments = unit["segments"]
        src_lang = unit["source_lang"] or source_lang

        # Use source text as the key name
        source_text = segments.get(src_lang, "")
        if not source_text:
            # Try to find any source text
            for lang_code, text in segments.items():
                if lang_code == src_lang:
                    source_text = text
                    break
            if not source_text:
                continue

        # Create a key from the source text (use it as-is or create a slug)
        key_name = source_text[:500]

        tk = db.query(TranslationKey).filter(
            TranslationKey.project_id == project_id,
            TranslationKey.key == key_name,
        ).first()
        if not tk:
            tk = TranslationKey(project_id=project_id, key=key_name)
            db.add(tk)
            db.flush()
            created_keys += 1

        # Add translations for each language segment
        for lang_code, text in segments.items():
            lang = db.query(Language).filter(Language.code == lang_code).first()
            if not lang:
                # Auto-create the language
                lang = Language(code=lang_code, name=lang_code.upper())
                db.add(lang)
                db.flush()

            t = db.query(Translation).filter(
                Translation.key_id == tk.id,
                Translation.language_id == lang.id,
            ).first()
            if t:
                t.value = text
                updated_translations += 1
            else:
                t = Translation(key_id=tk.id, language_id=lang.id, value=text)
                db.add(t)
                created_translations += 1

            # Also add to translation memory (if not source lang)
            if lang_code != src_lang and source_text:
                tm = TranslationMemory(
                    source_lang=src_lang, source_text=source_text,
                    target_lang=lang_code, target_text=text,
                    project_id=project_id,
                )
                db.add(tm)
                tm_entries_added += 1

    db.commit()
    return {
        "created_keys": created_keys,
        "created_translations": created_translations,
        "updated_translations": updated_translations,
        "tm_entries_added": tm_entries_added,
        "total_units": len(units),
    }


# --- Import TMX directly into translation memory (no project) ---

@router.post("/api/memory/import/tmx")
async def import_tmx_to_memory(
    file: UploadFile = File(...),
    source_lang: str = Query("en", description="Source language code"),
    db: Session = Depends(get_db),
):
    content = await file.read()
    units = _parse_tmx(content)

    entries_added = 0
    for unit in units:
        segments = unit["segments"]
        src_lang = unit["source_lang"] or source_lang
        source_text = segments.get(src_lang, "")
        if not source_text:
            continue

        for lang_code, text in segments.items():
            if lang_code == src_lang:
                continue
            tm = TranslationMemory(
                source_lang=src_lang, source_text=source_text,
                target_lang=lang_code, target_text=text,
            )
            db.add(tm)
            entries_added += 1

    db.commit()
    return {"entries_added": entries_added, "total_units": len(units)}


# --- Export project translations as TMX ---

@router.get("/api/projects/{project_id}/export/tmx")
def export_project_tmx(
    project_id: int,
    source_lang: str = Query("en", description="Source language for TMX header"),
    db: Session = Depends(get_db),
):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(404, "Project not found")

    keys = db.query(TranslationKey).filter(
        TranslationKey.project_id == project_id
    ).order_by(TranslationKey.key).all()

    entries = []
    for tk in keys:
        segments = {}
        for t in tk.translations:
            lang = db.query(Language).filter(Language.id == t.language_id).first()
            if lang:
                segments[lang.code] = t.value
        if segments:
            entries.append({"segments": segments})

    tmx_content = _generate_tmx(entries, source_lang=source_lang)

    return StreamingResponse(
        io.BytesIO(tmx_content.encode("utf-8")),
        media_type="application/xml",
        headers={"Content-Disposition": f'attachment; filename="{project.name}.tmx"'},
    )


# --- Export translation memory as TMX ---

@router.get("/api/memory/export/tmx")
def export_memory_tmx(
    source_lang: str = Query("en"),
    target_lang: str | None = Query(None),
    db: Session = Depends(get_db),
):
    query = db.query(TranslationMemory).filter(
        TranslationMemory.source_lang == source_lang
    )
    if target_lang:
        query = query.filter(TranslationMemory.target_lang == target_lang)

    tm_entries = query.order_by(TranslationMemory.created_at).all()

    # Group by source_text to create multi-language TUs
    grouped: dict[str, dict[str, str]] = {}
    for tm in tm_entries:
        if tm.source_text not in grouped:
            grouped[tm.source_text] = {source_lang: tm.source_text}
        grouped[tm.source_text][tm.target_lang] = tm.target_text

    entries = [{"segments": segs} for segs in grouped.values()]
    tmx_content = _generate_tmx(entries, source_lang=source_lang)

    return StreamingResponse(
        io.BytesIO(tmx_content.encode("utf-8")),
        media_type="application/xml",
        headers={"Content-Disposition": 'attachment; filename="translation_memory.tmx"'},
    )
