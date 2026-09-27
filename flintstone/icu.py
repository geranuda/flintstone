"""Pluralized string formats used by Transifex Native.

Two shapes travel through the CDS:

* ICU plurals, e.g. ``{cnt, plural, one {%lld day} other {%lld days}}``. This is
  what the iOS CLI pushes for simple String Catalog plural variations and what
  the iOS SDK parses at runtime, so the exact spacing matters.
* ``<cds-root>`` XML for complex String Catalog variations (per-device strings,
  substitutions), e.g.
  ``<cds-root><cds-unit id="device.iphone">...</cds-unit></cds-root>``.
"""

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from xml.sax.saxutils import escape

from .locales import PLURAL_ORDER

_HEAD = re.compile(r"\s*([^\s,{}]+)\s*,\s*plural\s*,")
_SELECTOR = re.compile(r"\s*(=\d+|zero|one|two|few|many|other)\s*\{")

CDS_ROOT = "cds-root"
CDS_UNIT = "cds-unit"


@dataclass
class PluralString:
    variable: str
    forms: dict[str, str] = field(default_factory=dict)


def _matching_brace(text: str, start: int) -> int:
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return i
    return -1


def parse_plural(text: str | None) -> PluralString | None:
    """Parse a string made of exactly one ICU plural expression, else return None."""
    if not text:
        return None
    s = text.strip()
    if not (s.startswith("{") and s.endswith("}")) or _matching_brace(s, 0) != len(s) - 1:
        return None
    inner = s[1:-1]
    head = _HEAD.match(inner)
    if not head:
        return None
    forms: dict[str, str] = {}
    pos = head.end()
    while inner[pos:].strip():
        sel = _SELECTOR.match(inner, pos)
        if not sel:
            return None
        open_at = sel.end() - 1
        close_at = _matching_brace(inner, open_at)
        if close_at < 0:
            return None
        forms[sel.group(1)] = inner[open_at + 1:close_at]
        pos = close_at + 1
    if "other" not in forms:
        return None
    return PluralString(variable=head.group(1), forms=forms)


def order_forms(forms: dict[str, str]) -> list[tuple[str, str]]:
    exact = sorted((k for k in forms if k.startswith("=")), key=lambda k: int(k[1:]))
    return [(k, forms[k]) for k in exact] + [(c, forms[c]) for c in PLURAL_ORDER if c in forms]


def build_plural(forms: dict[str, str], variable: str = "cnt") -> str:
    """Serialize plural forms the way the Transifex iOS CLI does.

    Empty forms are dropped; ``other`` is always kept because ICU requires it.
    """
    kept = {k: v for k, v in forms.items() if v or k == "other"}
    body = " ".join(f"{k} {{{v}}}" for k, v in order_forms(kept))
    return f"{{{variable}, plural, {body}}}"


def parse_units(text: str | None) -> list[tuple[str, str]] | None:
    """Parse a ``<cds-root>`` document into ``[(unit id, text), ...]``."""
    if not text or not text.lstrip().startswith(f"<{CDS_ROOT}"):
        return None
    try:
        root = ET.fromstring(text.strip())
    except ET.ParseError:
        return None
    if root.tag != CDS_ROOT:
        return None
    return [(el.get("id", ""), el.text or "") for el in root if el.tag == CDS_UNIT]


def build_units(units: list[tuple[str, str]]) -> str:
    body = "".join(
        f'<{CDS_UNIT} id="{escape(uid, {chr(34): "&quot;"})}">{escape(text)}</{CDS_UNIT}>'
        for uid, text in units
    )
    return f"<{CDS_ROOT}>{body}</{CDS_ROOT}>"


def kind(text: str | None) -> str:
    """Classify a stored string: ``plural``, ``variations`` or ``text``."""
    if parse_plural(text):
        return "plural"
    if parse_units(text) is not None:
        return "variations"
    return "text"


def display_length(text: str | None) -> int:
    """Longest visible variant, used for character-limit checks."""
    plural = parse_plural(text)
    if plural:
        return max((len(v) for v in plural.forms.values()), default=0)
    units = parse_units(text)
    if units is not None:
        return max((len(v) for _, v in units), default=0)
    return len(text or "")
