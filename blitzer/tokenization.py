"""Application-owned word profiles with offsets into unchanged source text.

Lexical validation is separate from prose segmentation: a Japanese lemma
can be a valid database entry even if an analyzer splits it in prose.
Downloaded packs select profile IDs, never executable plugin code.
"""

import unicodedata
from dataclasses import dataclass
from functools import lru_cache


@dataclass(frozen=True)
class Token:
    """Store the original substring, Python offsets and optional lookup key."""

    text: str
    start: int
    end: int
    lookup: str | None = None


PROFILES = frozenset({
    "default", "joiners", "hebrew", "mongolian", "tone", "tone-ascii", "tone-hyphen",
    "middle-dot", "colon-glottal", "final-glottal", "internal-dot",
    "elision-french", "elision-italian", "pali", "sudachi", "unavailable",
})
APOSTROPHES = "'’"
TONE_DIGITS = "¹²³⁴⁵⁶⁷⁸⁹⁰"


def validate_profile(profile):
    """Reject unknown or executable-looking capability selections."""
    if not isinstance(profile, str) or profile not in PROFILES:
        raise ValueError(f"Unknown tokenization profile {profile!r}")
    return profile


def _letter(char):
    """Recognize letters in every Unicode script."""
    return unicodedata.category(char).startswith("L")


def _next_letter(text, index):
    """Look past combining marks/joiners without accepting trailing controls."""
    for offset in range(index + 1, len(text)):
        char = text[offset]
        if unicodedata.category(char).startswith("M") or char in "\u200c\u200d":
            continue
        return _letter(char)
    return False


def _continues(text, index, profile):
    """Apply narrowly scoped rules for word-internal punctuation."""
    char = text[index]
    if char in APOSTROPHES and index + 1 < len(text) and _letter(text[index + 1]):
        return True
    if profile in {"joiners", "hebrew", "mongolian"}:
        controls = "\u180e" if profile == "mongolian" else "\u200c\u200d"
        if char in controls and _next_letter(text, index):
            return True
    if profile in {"tone", "tone-ascii", "tone-hyphen"}:
        if char in TONE_DIGITS or (profile == "tone-ascii" and char in "0123456789"):
            return True
    if profile == "tone-hyphen" and char in "-‐‑" and _next_letter(text, index):
        return True
    if profile == "middle-dot" and char == "·" and _next_letter(text, index):
        return True
    if profile == "colon-glottal" and char == ":" and _next_letter(text, index):
        return True
    if profile == "internal-dot" and char == "." and _next_letter(text, index):
        return True
    if profile == "pali" and char == "”" and _next_letter(text, index):
        return True
    if profile == "hebrew" and char in '״"' and _next_letter(text, index):
        return True
    if profile == "hebrew" and char == "׳":
        return True
    if profile in {"colon-glottal", "final-glottal"} and char in APOSTROPHES:
        # Only a single final apostrophe; closing quotes remain ambiguous
        # in these orthographies and are documented as such.
        return index + 1 == len(text) or not (
            text[index + 1] in APOSTROPHES or _letter(text[index + 1])
        )
    return False


def lexical_tokens(text, profile="default"):
    """Yield orthographic runs; do not invoke an analyzer or strip tones."""
    validate_profile(profile)
    start = None
    for index, char in enumerate(text):
        starts = _letter(char)
        leading = (
            profile == "colon-glottal" and char in APOSTROPHES
            and start is None and _next_letter(text, index)
        )
        if starts or leading or (
            start is not None and (
                unicodedata.category(char).startswith("M")
                or _continues(text, index, profile)
            )
        ):
            start = index if start is None else start
            continue
        if start is None:
            continue
        yield Token(text[start:index], start, index)
        start = None
    if start is not None:
        yield Token(text[start:], start, len(text))


@lru_cache(maxsize=1)
def _japanese_tokenizer():
    """Load the optional installed dictionary without network access."""
    try:
        from sudachipy import dictionary
        return dictionary.Dictionary(dict="core").create()
    except (ImportError, ModuleNotFoundError) as error:
        raise ValueError(
            "Japanese requires SudachiPy and its core dictionary. "
            "Install with: python -m pip install 'bltzr[japanese]'"
        ) from error


def tokenize(text, profile="default"):
    """Segment prose using an explicitly selected application capability."""
    validate_profile(profile)
    if profile == "unavailable":
        raise ValueError(
            "This language requires a lexical segmenter that is not yet "
            "supported; use explicitly presegmented data with a local "
            "pack configured for an appropriate orthographic profile."
        )
    if profile != "sudachi":
        yield from lexical_tokens(text, profile)
        return
    engine = _japanese_tokenizer()
    from sudachipy import tokenizer
    for item in engine.tokenize(text, tokenizer.Tokenizer.SplitMode.C):
        left, right = item.begin(), item.end()
        surface = text[left:right]
        if any(_letter(char) for char in surface):
            yield Token(surface, left, right, item.dictionary_form())


def word(value, profile="default"):
    """Validate one lexical entry without invoking prose segmentation."""
    if not isinstance(value, str):
        return False
    tokens = list(lexical_tokens(value, profile))
    return len(tokens) == 1 and tokens[0].text == value


def elision_parts(token, profile):
    """Offer a conservative prefix split only for an unmatched full form."""
    prefixes = {
        "elision-french": {"l", "d", "j", "m", "n", "s", "t", "c", "qu"},
        "elision-italian": {"l", "d", "un", "dell", "all", "dall", "nell", "sull"},
    }.get(profile, set())
    for index, char in enumerate(token.text):
        if char in APOSTROPHES and token.text[:index].lower() in prefixes:
            return (
                Token(token.text[:index], token.start, token.start + index),
                Token(token.text[index + 1:], token.start + index + 1, token.end),
            )
    return (token,)
