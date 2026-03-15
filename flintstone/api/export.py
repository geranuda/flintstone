"""Import/Export API endpoints."""

import csv
import io
import json

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Language, Project, Translation, TranslationKey

router = APIRouter(prefix="/api/projects/{project_id}", tags=["import/export"])


def _get_project_or_404(project_id: int, db: Session) -> Project:
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(404, "Project not found")
    return project


@router.get("/export")
def export_translations(
    project_id: int,
    format: str = Query("json", pattern="^(json|csv|po|xliff)$"),
    lang: str | None = Query(None, description="Language code (required for JSON)"),
    db: Session = Depends(get_db),
):
    project = _get_project_or_404(project_id, db)
    keys = db.query(TranslationKey).filter(
        TranslationKey.project_id == project_id
    ).order_by(TranslationKey.key).all()

    if format == "json":
        if not lang:
            raise HTTPException(400, "Language code required for JSON export")
        language = db.query(Language).filter(Language.code == lang).first()
        if not language:
            raise HTTPException(404, f"Language '{lang}' not found")

        data = {}
        for tk in keys:
            t = db.query(Translation).filter(
                Translation.key_id == tk.id,
                Translation.language_id == language.id,
            ).first()
            data[tk.key] = t.value if t else ""

        content = json.dumps(data, indent=2, ensure_ascii=False)
        return StreamingResponse(
            io.BytesIO(content.encode("utf-8")),
            media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="{project.name}_{lang}.json"'},
        )

    elif format == "po":
        if not lang:
            raise HTTPException(400, "Language code required for PO export")
        language = db.query(Language).filter(Language.code == lang).first()
        if not language:
            raise HTTPException(404, f"Language '{lang}' not found")

        from .formats import export_po
        content = export_po(keys, language, db)
        return StreamingResponse(
            io.BytesIO(content),
            media_type="application/x-gettext",
            headers={"Content-Disposition": f'attachment; filename="{project.name}_{lang}.po"'},
        )

    elif format == "xliff":
        if not lang:
            raise HTTPException(400, "Language code required for XLIFF export")
        language = db.query(Language).filter(Language.code == lang).first()
        if not language:
            raise HTTPException(404, f"Language '{lang}' not found")

        from fastapi import Query as Q
        source_lang_code = "en"  # default source language
        source_language = db.query(Language).filter(Language.code == source_lang_code).first()
        if not source_language:
            # Use the first available language as source
            source_language = db.query(Language).first()
            if not source_language:
                raise HTTPException(400, "No languages configured")

        from .formats import export_xliff
        content = export_xliff(keys, source_language, language, project.name, db)
        return StreamingResponse(
            io.BytesIO(content),
            media_type="application/xml",
            headers={"Content-Disposition": f'attachment; filename="{project.name}_{lang}.xliff"'},
        )

    else:  # csv
        languages = db.query(Language).order_by(Language.code).all()
        output = io.StringIO()
        writer = csv.writer(output)
        header = ["key"] + [l.code for l in languages]
        writer.writerow(header)

        for tk in keys:
            row = [tk.key]
            for language in languages:
                t = db.query(Translation).filter(
                    Translation.key_id == tk.id,
                    Translation.language_id == language.id,
                ).first()
                row.append(t.value if t else "")
            writer.writerow(row)

        output.seek(0)
        return StreamingResponse(
            io.BytesIO(output.getvalue().encode("utf-8")),
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{project.name}_translations.csv"'},
        )


@router.post("/import")
async def import_translations(
    project_id: int,
    file: UploadFile = File(...),
    lang: str | None = Query(None, description="Language code (required for JSON)"),
    db: Session = Depends(get_db),
):
    _get_project_or_404(project_id, db)
    content = await file.read()
    filename = file.filename or ""

    created_keys = 0
    created_translations = 0
    updated_translations = 0

    if filename.endswith(".json") or (lang and not filename.endswith((".csv", ".po", ".xliff", ".xlf"))):
        if not lang:
            raise HTTPException(400, "Language code required for JSON import")
        language = db.query(Language).filter(Language.code == lang).first()
        if not language:
            raise HTTPException(404, f"Language '{lang}' not found")

        try:
            data = json.loads(content.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            raise HTTPException(400, f"Invalid JSON: {e}")

        for key, value in data.items():
            tk = db.query(TranslationKey).filter(
                TranslationKey.project_id == project_id,
                TranslationKey.key == key,
            ).first()
            if not tk:
                tk = TranslationKey(project_id=project_id, key=key)
                db.add(tk)
                db.flush()
                created_keys += 1

            t = db.query(Translation).filter(
                Translation.key_id == tk.id,
                Translation.language_id == language.id,
            ).first()
            if t:
                t.value = str(value)
                updated_translations += 1
            else:
                t = Translation(key_id=tk.id, language_id=language.id, value=str(value))
                db.add(t)
                created_translations += 1

    elif filename.endswith(".csv"):
        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError:
            text = content.decode("latin-1")

        reader = csv.reader(io.StringIO(text))
        header = next(reader, None)
        if not header or header[0].lower() != "key":
            raise HTTPException(400, "CSV must have 'key' as first column header")

        lang_codes = header[1:]
        lang_map = {}
        for code in lang_codes:
            language = db.query(Language).filter(Language.code == code).first()
            if language:
                lang_map[code] = language

        for row in reader:
            if not row:
                continue
            key = row[0]
            tk = db.query(TranslationKey).filter(
                TranslationKey.project_id == project_id,
                TranslationKey.key == key,
            ).first()
            if not tk:
                tk = TranslationKey(project_id=project_id, key=key)
                db.add(tk)
                db.flush()
                created_keys += 1

            for i, code in enumerate(lang_codes):
                if code not in lang_map or i + 1 >= len(row):
                    continue
                value = row[i + 1]
                if not value:
                    continue
                language = lang_map[code]
                t = db.query(Translation).filter(
                    Translation.key_id == tk.id,
                    Translation.language_id == language.id,
                ).first()
                if t:
                    t.value = value
                    updated_translations += 1
                else:
                    t = Translation(key_id=tk.id, language_id=language.id, value=value)
                    db.add(t)
                    created_translations += 1
    elif filename.endswith(".po"):
        if not lang:
            raise HTTPException(400, "Language code required for PO import")
        language = db.query(Language).filter(Language.code == lang).first()
        if not language:
            raise HTTPException(404, f"Language '{lang}' not found")

        from .formats import import_po
        try:
            result = import_po(content, project_id, language, db)
        except ValueError as e:
            raise HTTPException(400, str(e))
        created_keys = result["created_keys"]
        created_translations = result["created_translations"]
        updated_translations = result["updated_translations"]

    elif filename.endswith((".xliff", ".xlf")):
        from .formats import import_xliff
        try:
            result = import_xliff(content, project_id, db)
        except ValueError as e:
            raise HTTPException(400, str(e))
        created_keys = result["created_keys"]
        created_translations = result["created_translations"]
        updated_translations = result["updated_translations"]

    else:
        raise HTTPException(400, "Unsupported file format. Use .json, .csv, .po, .xliff, or .xlf")

    db.commit()
    return {
        "created_keys": created_keys,
        "created_translations": created_translations,
        "updated_translations": updated_translations,
    }
