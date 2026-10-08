"""Reviewed language identities and data-only tokenization capabilities.

The complete catalog includes development languages. It does not grant
download eligibility; language-registry.json alone controls downloads.
Unknown local pack codes retain their own metadata and default boundaries.
"""

import json
from pathlib import Path


CATALOG = json.loads(
    Path(__file__).with_name("language-catalog.json").read_text(encoding="utf-8")
)


def language_entry(code):
    """Return a copy so callers cannot mutate the reviewed catalog."""
    return dict(CATALOG.get(code, {"profile": "default", "status": "review"}))


def display_name(code, fallback):
    """Repair generated garbage names while respecting custom pack titles."""
    if fallback == code.upper() or fallback.startswith("• ") or fallback in {
        "Data", "Caveats", "Non-UniMorph labels used:"
    }:
        return CATALOG.get(code, {}).get("name", fallback)
    return fallback
