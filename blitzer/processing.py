"""Compute vocabulary using explicitly supplied text and data.

Purpose
-------
Keep language-learning rules understandable and testable without files,
databases, terminal input or application startup.

In scope
--------
- Token, Context and VocabularyEntry records with original text offsets.
- Unicode tokenization, normalization and sentence-span detection.
- Independent known-form/known-lemma filtering and display selection.
- Surviving occurrence counts, known-term proposals and example
  selection.
- Deterministic vocabulary sorting using supplied ranks and frequencies.
- Parsing known-list text and validating mapping and frequency values.
- Constructing history rows using a timestamp supplied by the caller.

Out of scope
------------
- Reading files, querying databases or changing persistent data.
- Resolving paths, reading environment variables or reading the clock.
- Click commands, prompts, output formats and emphasis markup.
- Building, installing or removing language packs.

Start here
----------
Read collect_vocabulary for the main pure processing sequence, then
filter_occurrence, context_for_token and add_occurrence for its rules.
core.py reads the required data and calls these functions. config.py
provides supported choices and sentence-pattern validation.
"""

import math
import re
import unicodedata
from bisect import bisect_right
from dataclasses import dataclass, field, replace

from blitzer.config import SORTS, validate_pattern
from blitzer.tokenization import Token, tokenize, word


@dataclass(frozen=True)
class Context:
    """Store an original sentence and its highlight offsets."""

    text: str
    highlight_start: int
    highlight_end: int


@dataclass
class VocabularyEntry:
    """Store one displayed term and its surviving occurrence data."""

    term: str
    count: int
    first_position: int
    contexts: list[Context] = field(default_factory=list)
    global_frequency: float | None = None
    known_terms: set[str] = field(default_factory=set)


def normalize(text: str, settings: dict) -> str:
    """Return normalized text using the supplied rules.

    Apply literal replacement rules in their supplied order, then
    compose Unicode again. Both inputs stay unchanged; no external state
    is read.
    """
    text = unicodedata.normalize("NFC", text)
    if settings["lowercase"]:
        text = text.lower()
    for rule in settings["substitutions"]:
        text = text.replace(rule["from"], rule["to"])
    return unicodedata.normalize("NFC", text)


def _word(value: str, profile="default") -> bool:
    """Check whether a string is exactly one supported word."""
    return word(value, profile)


def _sentences(text: str, pattern: str) -> list[tuple[int, int]]:
    """Return sentence spans with punctuation preserved.

    Reject zero-width matches in the actual input, even if the pattern
    passed validation on sample text. Whitespace-only spans are omitted.
    """
    spans = []
    start = 0
    for match in re.finditer(pattern, text):
        if match.start() == match.end():
            raise ValueError("sentence_pattern matched empty text")
        span = _trim_span(text, start, match.end())
        if span is not None:
            spans.append(span)
        start = match.end()
    tail = _trim_span(text, start, len(text))
    return spans + ([tail] if tail is not None else [])


def _trim_span(text, start, end) -> tuple[int, int] | None:
    """Trim boundary whitespace without changing the underlying text."""
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    return (start, end) if end > start else None


def parse_terms(text: str, normal: dict, label="known list"):
    """Parse known-list text into terms, duplicates and comments.

    Preserve first-seen term order and the original comment lines. Blank
    lines are ignored. Reject invalid words with their source line
    number. This function has no I/O and does not change the supplied
    rules.
    """
    terms, duplicates, comments = [], [], []
    seen = set()
    for number, line in enumerate(text.splitlines(), 1):
        value = line.strip()
        if not value:
            continue
        if value.startswith("#"):
            comments.append(line)
            continue
        key = _known_term(value, normal, label, number)
        if key in seen:
            duplicates.append(key)
            continue
        terms.append(key)
        seen.add(key)
    return terms, duplicates, comments


def _known_term(value, normal, label, number) -> str:
    """Validate and normalize one known term with a source location."""
    profile = normal.get("_profile", "default")
    if not _word(value, profile) and not all(
        _word(part, profile) for part in re.split("[-‐‑]", value)
    ):
        raise ValueError(
            f"{label}:{number}: expected one word per line, got {value!r}"
        )
    key = normalize(value, normal)
    if not key:
        raise ValueError(
            f"{label}:{number}: normalization produced an empty term"
        )
    return key


def processing_options(settings: dict, **overrides) -> dict:
    """Return processing settings with explicit, non-None overrides.

    The input dictionary is unchanged. Sentence patterns are validated
    before any processing resources are opened.
    """
    options = dict(settings)
    options.update(
        {key: value for key, value in overrides.items() if value is not None}
    )
    pattern = options.pop("sentence_pattern")
    options["sentence_pattern"] = validate_pattern(pattern)
    return options


def validate_processing(
    text, code, options, no_exclusions, track_known, exclusions, forms_only
) -> None:
    """Reject invalid or incompatible processing options."""
    if not isinstance(text, str) or not text.strip():
        raise ValueError("No input text provided")
    bools = {
        key: options[key]
        for key in ("lemmatize", "context", "exclude_unknown")
    }
    bools.update(no_exclusions=no_exclusions, track_known=track_known)
    for name, value in bools.items():
        if type(value) is not bool:
            raise ValueError(f"{name} must be a boolean")
    if options["filter_by"] not in ("forms", "lemmas"):
        raise ValueError("Invalid filtering mode or sort order")
    if options["sort"] not in SORTS:
        raise ValueError("Invalid filtering mode or sort order")
    limit = options["context_limit"]
    if type(limit) is not int or not 1 <= limit <= 20:
        raise ValueError("context_limit must be an integer from 1 to 20")
    if no_exclusions and (exclusions is not None or forms_only is not None):
        raise ValueError(
            "no_exclusions conflicts with explicit exclusion files"
        )
    needs_dictionary = (
        options["lemmatize"]
        or options["exclude_unknown"]
        or track_known
        or options["filter_by"] == "lemmas"
        or options["sort"] == "global-frequency"
    )
    if code == "base" and needs_dictionary:
        raise ValueError(
            "base has no dictionary: use exact words and words as written, "
            "without word-family skipping, dictionary sorting or automatic updates"
        )


def filter_occurrence(
    key,
    candidates,
    known,
    exact,
    normal,
    *,
    lemmatize,
    filter_by,
    exclude_unknown,
    known_update_mode=None,
) -> list[tuple[str, set[str]]]:
    """Return displayed terms for a surviving occurrence.

    Literal known forms always remove the occurrence. Lemma filtering
    removes candidates independently of display mode. Unknown forms can
    survive, but never qualify for automatic known-list additions.
    Inputs are unchanged and no dictionary or file access occurs here.
    """
    if not key or key in exact or key in known:
        return []
    if exclude_unknown and not candidates:
        return []
    surviving = candidates
    if filter_by == "lemmas":
        surviving = [
            term for term in candidates if normalize(term, normal) not in known
        ]
    if candidates and not surviving:
        return []
    terms = surviving if lemmatize and candidates else [key]
    return [
        (
            term,
            _matched_keys(term, key, surviving, normal, lemmatize,
                          known_update_mode or filter_by),
        )
        for term in terms
    ]


def _matched_keys(
    term, key, surviving, normal, lemmatize, filter_by
) -> set[str]:
    """Return known-list proposals from matched survivors."""
    if not surviving:
        return set()
    if filter_by == "forms":
        return {key}
    if lemmatize:
        return {normalize(term, normal)}
    return {normalize(candidate, normal) for candidate in surviving}


def context_for_token(text, token, spans, starts) -> Context | None:
    """Return the sentence containing a flagged token.

    Offsets in the returned context index its own text. Return None when
    sentence delimiters leave the token outside a complete sentence
    span.
    """
    index = bisect_right(starts, token.start) - 1
    if index < 0:
        return None
    left, right = spans[index]
    if token.end > right:
        return None
    return Context(text[left:right], token.start - left, token.end - left)


def add_occurrence(entry, snippet, matched_keys, limit) -> VocabularyEntry:
    """Return a new entry with one surviving occurrence added.

    Preserve the first position and at most limit distinct sentence
    texts. The supplied entry, its contexts and its known-term set are
    unchanged.
    """
    contexts = list(entry.contexts)
    has_room = len(contexts) < limit
    distinct = snippet is not None and all(
        item.text != snippet.text for item in contexts
    )
    if has_room and distinct:
        contexts.append(snippet)
    return replace(
        entry,
        count=entry.count + 1,
        contexts=contexts,
        known_terms=entry.known_terms | matched_keys,
    )


def collect_vocabulary(
    text, normal, known, exact, candidates, options, *, tokens=None
) -> list[VocabularyEntry]:
    """Build vocabulary from supplied text and lookup data.

    Only surviving occurrences contribute counts, known-list proposals
    or examples. Every returned record is new; caller-owned data is
    unchanged.
    """
    spans = (
        _sentences(text, options["sentence_pattern"])
        if options["context"]
        else []
    )
    starts = [left for left, _ in spans]
    entries = {}
    if tokens is None:
        tokens = tokenize(text, normal.get("_profile", "default"))
    for token in tokens:
        key = normalize(token.text, normal)
        flagged = filter_occurrence(
            key,
            candidates.get(key, ()),
            known,
            exact,
            normal,
            lemmatize=options["lemmatize"],
            filter_by=options["filter_by"],
            exclude_unknown=options["exclude_unknown"],
            known_update_mode=options.get("known_update_mode"),
        )
        snippet = context_for_token(text, token, spans, starts)
        for term, matched_keys in flagged:
            entry = entries.get(term) or VocabularyEntry(term, 0, token.start)
            entries[term] = add_occurrence(
                entry,
                snippet,
                matched_keys,
                options["context_limit"],
            )
    return list(entries.values())


def sort_vocabulary(
    entries, order, custom_order, normal
) -> list[VocabularyEntry]:
    """Return entries in order without changing the input.

    Custom order uses normalized lookup keys. Ties use spelling so
    output stays deterministic across repeated calls.
    """
    if order not in SORTS:
        raise ValueError(f"Invalid sort order {order!r}")
    if order == "alphabetical":
        return sorted(entries, key=lambda entry: entry.term)
    if order == "appearance":
        return sorted(
            entries, key=lambda entry: (entry.first_position, entry.term)
        )
    if order == "global-frequency":
        return sorted(
            entries,
            key=lambda entry: (
                entry.global_frequency is None,
                -(entry.global_frequency or 0),
                entry.term,
            ),
        )
    if order == "custom":
        ranks = {term: index for index, term in enumerate(custom_order)}
        return sorted(
            entries,
            key=lambda entry: (
                ranks.get(normalize(entry.term, normal), len(ranks)),
                entry.term,
            ),
        )
    return sorted(entries, key=lambda entry: (-entry.count, entry.term))


def normalize_mapping(form, lemma, normal, *, skip_unsupported=False):
    """Return a normalized form/lemma pair without accessing storage.

    Blank or non-text values always raise ValueError. Return None for
    unsupported multiword data only when skipping is explicitly enabled.
    Stored form keys must remain unchanged by repeated normalization.
    """
    if (
        not isinstance(form, str)
        or not isinstance(lemma, str)
        or not form
        or not lemma
    ):
        raise ValueError("blank or non-text form/lemma")
    key = normalize(form, normal)
    normalized_lemma = unicodedata.normalize("NFC", lemma)
    profile = normal.get("_profile", "default")
    unsupported = not _word(key, profile) or not _word(normalized_lemma, profile)
    if unsupported and skip_unsupported:
        return None
    if unsupported:
        raise ValueError(
            f"unsupported single-word mapping {form!r} -> {lemma!r}"
        )
    if normalize(key, normal) != key:
        raise ValueError(
            "Normalization rules must be idempotent for stored form keys"
        )
    return key, normalized_lemma


def parse_frequency(term: str, value: str, profile="default") -> tuple[str, float]:
    """Return an NFC word and finite nonnegative corpus frequency.

    Raise ValueError for malformed words or invalid numbers. This
    function reads no files and changes no caller-owned data.
    """
    if not _word(term, profile):
        raise ValueError("invalid frequency row")
    frequency = float(value)
    if not math.isfinite(frequency) or frequency < 0:
        raise ValueError("frequency must be finite and nonnegative")
    return unicodedata.normalize("NFC", term), frequency


def context_rows(code, entries, timestamp):
    """Yield history rows using an explicit timestamp.

    This function performs no writes and does not read the clock. The
    caller supplies time so row generation can be tested
    deterministically.
    """
    return (
        (
            code,
            entry.term,
            context.text,
            context.highlight_start,
            context.highlight_end,
            timestamp,
        )
        for entry in entries
        for context in entry.contexts
    )
