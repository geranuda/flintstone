"""Fuzzy matching utilities using Levenshtein distance."""

from .models import TranslationMemory


def compute_similarity(s1: str, s2: str) -> float:
    """Compute similarity ratio between two strings (0.0 to 1.0)."""
    try:
        from rapidfuzz import fuzz
        return fuzz.ratio(s1, s2) / 100.0
    except ImportError:
        # Fallback: simple ratio based on common characters
        if not s1 or not s2:
            return 0.0
        matches = sum(1 for c in s1 if c in s2)
        return (2.0 * matches) / (len(s1) + len(s2))


def find_fuzzy_matches(
    source: str,
    candidates: list[TranslationMemory],
    min_similarity: float = 0.6,
) -> list[tuple[TranslationMemory, float]]:
    """Find fuzzy matches above threshold, sorted by similarity descending."""
    results = []
    for tm in candidates:
        score = compute_similarity(source, tm.source_text)
        if score >= min_similarity:
            results.append((tm, score))
    results.sort(key=lambda x: x[1], reverse=True)
    return results
