"""Glossary validation logic."""

from sqlalchemy.orm import Session

from .models import GlossaryTerm, GlossaryTranslation
from .schemas import GlossaryViolation


def check_glossary(
    db: Session,
    source_text: str,
    source_lang: str,
    target_text: str,
    target_lang: str,
) -> list[GlossaryViolation]:
    """Check target text for glossary compliance.

    Returns a list of violations where a glossary source term appears
    in the source text but the approved translation is missing from the target.
    """
    if not source_text or not target_text:
        return []

    terms = db.query(GlossaryTerm).filter(
        GlossaryTerm.source_language == source_lang
    ).all()

    violations = []
    for term in terms:
        # Check if source term appears in source text
        if term.case_sensitive:
            if term.source_term not in source_text:
                continue
        else:
            if term.source_term.lower() not in source_text.lower():
                continue

        # Look up approved translation for target language
        gt = db.query(GlossaryTranslation).filter(
            GlossaryTranslation.term_id == term.id,
            GlossaryTranslation.language_code == target_lang,
        ).first()
        if not gt:
            continue

        # Check if approved translation appears in target text
        if term.case_sensitive:
            if gt.approved_value in target_text:
                continue
        else:
            if gt.approved_value.lower() in target_text.lower():
                continue

        violations.append(GlossaryViolation(
            term_id=term.id,
            source_term=term.source_term,
            expected_value=gt.approved_value,
            severity="error" if False else "warning",  # severity controlled by config at call site
        ))

    return violations
