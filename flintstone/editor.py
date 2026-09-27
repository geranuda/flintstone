"""Queries and view models behind the translation editor (web UI and API)."""

from collections import Counter
from dataclasses import dataclass

from sqlalchemy import and_, or_
from sqlalchemy.orm import Session, aliased

from . import icu, locales
from .models import Language, Project, Translation, TranslationKey

STATUS_FILTERS = {
    "untranslated": "Untranslated",
    "translated": "Translated",
    "unreviewed": "Needs review",
    "reviewed": "Reviewed",
}
SORTS = {"key": "Key", "source": "Source text", "recent": "Recently updated"}
STATUS_LABELS = {"untranslated": "Untranslated", "translated": "Translated", "reviewed": "Reviewed", "proofread": "Proofread"}


@dataclass
class StringRow:
    key: TranslationKey
    source: str | None
    translation: Translation | None


def _like(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _filtered(db: Session, project: Project, target: Language, source: Language | None,
              q: str, tag: str, file: str):
    src = aliased(Translation)
    tgt = aliased(Translation)
    query = (
        db.query(TranslationKey, src.value, tgt)
        .outerjoin(src, and_(src.key_id == TranslationKey.id, src.language_id == (source.id if source else -1)))
        .outerjoin(tgt, and_(tgt.key_id == TranslationKey.id, tgt.language_id == target.id))
        .filter(TranslationKey.project_id == project.id)
    )
    if q:
        pattern = _like(q)
        query = query.filter(or_(
            TranslationKey.key.ilike(pattern, escape="\\"),
            src.value.ilike(pattern, escape="\\"),
            tgt.value.ilike(pattern, escape="\\"),
            TranslationKey.description.ilike(pattern, escape="\\"),
        ))
    if tag:
        query = query.filter(("," + TranslationKey.tags + ",").like(_like(f",{tag},"), escape="\\"))
    if file:
        query = query.filter(TranslationKey.occurrences.like(_like(file), escape="\\"))
    return query, src, tgt


def _with_status(query, tgt, status: str):
    translated = and_(tgt.id.isnot(None), tgt.value != "")
    if status == "untranslated":
        return query.filter(or_(tgt.id.is_(None), tgt.value == ""))
    if status == "translated":
        return query.filter(translated)
    if status == "unreviewed":
        return query.filter(translated, tgt.status == "translated")
    if status == "reviewed":
        return query.filter(translated, tgt.status.in_(("reviewed", "proofread")))
    return query


def status_counts(db: Session, project: Project, target: Language, source: Language | None,
                  q: str = "", tag: str = "", file: str = "") -> dict[str, int]:
    """Number of strings per status filter, honouring the search/tag/file filters."""
    query, _, tgt = _filtered(db, project, target, source, q, tag, file)
    counts = {"": query.count()}
    for status in STATUS_FILTERS:
        counts[status] = _with_status(query, tgt, status).count()
    return counts


def query_strings(
    db: Session,
    project: Project,
    target: Language,
    source: Language | None,
    q: str = "",
    tag: str = "",
    status: str = "",
    file: str = "",
    sort: str = "key",
    page: int = 1,
    per_page: int = 50,
) -> tuple[list[StringRow], int]:
    query, src, tgt = _filtered(db, project, target, source, q, tag, file)
    query = _with_status(query, tgt, status)
    total = query.count()
    if sort == "recent":
        query = query.order_by(TranslationKey.updated_at.desc(), TranslationKey.key)
    elif sort == "source":
        query = query.order_by(src.value, TranslationKey.key)
    else:
        query = query.order_by(TranslationKey.key)
    rows = query.offset(max(page - 1, 0) * per_page).limit(per_page).all()
    return [StringRow(key=tk, source=source_value, translation=t) for tk, source_value, t in rows], total


def project_files(db: Session, project: Project) -> list[tuple[str, int]]:
    """Occurrence files with the number of strings found in each."""
    counts: Counter = Counter()
    for (occurrences,) in db.query(TranslationKey.occurrences).filter(TranslationKey.project_id == project.id):
        counts.update(o for o in (occurrences or "").split("\n") if o)
    return sorted(counts.items())


def row_view(row: StringRow, target: Language) -> dict:
    """Everything a template needs to render one editable string."""
    tk = row.key
    source = row.source if row.source is not None else tk.key
    value = row.translation.value if row.translation else ""
    view = {
        "key": tk,
        "source": source,
        "value": value,
        "status": (row.translation.status if row.translation and value else "untranslated"),
        "kind": icu.kind(source),
        "tags": tk.tag_list,
        "occurrences": tk.occurrence_list,
        "length": icu.display_length(value),
    }
    view["status_label"] = STATUS_LABELS.get(view["status"], view["status"])
    if view["kind"] == "plural":
        source_plural = icu.parse_plural(source)
        target_plural = icu.parse_plural(value)
        target_forms = target_plural.forms if target_plural else {}
        wanted = set(locales.plural_categories(target.code)) | set(target_forms)
        wanted |= {k for k in source_plural.forms if k.startswith("=")}
        view["variable"] = source_plural.variable
        view["source_forms"] = icu.order_forms(source_plural.forms)
        view["forms"] = [(k, target_forms.get(k, "")) for k, _ in icu.order_forms(dict.fromkeys(wanted, ""))]
        view["optional_forms"] = set(locales.optional_categories(target.code))
    elif view["kind"] == "variations":
        target_units = dict(icu.parse_units(value) or [])
        view["source_units"] = icu.parse_units(source)
        view["units"] = [(uid, target_units.get(uid, "")) for uid, _ in view["source_units"]]
    return view


def row_json(view: dict) -> dict:
    tk = view["key"]
    return {
        "id": tk.id,
        "key": tk.key,
        "source": view["source"],
        "translation": view["value"],
        "status": view["status"],
        "kind": view["kind"],
        "developer_comment": tk.description or "",
        "context": tk.context or "",
        "character_limit": tk.character_limit,
        "tags": view["tags"],
        "occurrences": view["occurrences"],
    }
