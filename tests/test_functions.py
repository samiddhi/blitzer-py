"""Check pure processing rules and application readability.

Purpose
-------
Verify important language-learning decisions with ordinary in-memory
inputs and guard against a return to deeply nested application code.

In scope
--------
- Filtering and proposals independent of display mode.
- Flagged examples, original offsets and immutable entry replacement.
- Sorting, known-list parsing, mapping normalization and frequency
  values.
- History rows using explicit time and processing without I/O.
- Preserving caller-owned inputs during pure function calls.
- Application function docstrings, nesting limits and nested
  definitions.

Out of scope
------------
- File/database lifecycle and public-service integration: test_core.py.
- Config-file selection: test_config.py; terminal behavior: test_cli.py.
- Full style-tool implementations or performance benchmarks.

Start here
----------
The tests call functions implemented in processing.py through core.py's
public exports. The last tests inspect application syntax; they do not
run vocabulary processing or open user data.
"""

import ast
from copy import deepcopy
from pathlib import Path

import pytest

from blitzer.core import (
    BASE_NORMALIZATION,
    Context,
    Token,
    VocabularyEntry,
    add_occurrence,
    collect_vocabulary,
    context_for_token,
    context_rows,
    filter_occurrence,
    normalize_mapping,
    parse_frequency,
    parse_terms,
    processing_options,
    sort_vocabulary,
)

OPTIONS = {
    "lemmatize": True,
    "filter_by": "forms",
    "exclude_unknown": False,
    "context": True,
    "sentence_pattern": r"[.!?]+(?=\s|$)",
    "context_limit": 2,
    "sort": "textual-frequency",
}


def unexpected_io(*args, **kwargs):
    """Fail if a pure function attempts external I/O."""
    raise AssertionError("Pure processing must not perform I/O")


@pytest.mark.parametrize("hyphen", ["-", "‐", "‑"])
@pytest.mark.parametrize("profile", ["default", "middle-dot", "tone"])
def test_known_list_accepts_hyphenated_words(hyphen, profile):
    """Hyphenated entries keep normalization and duplicate detection."""
    normal = dict(BASE_NORMALIZATION, _profile=profile)
    term = f"sally{hyphen}anne"
    assert parse_terms(f"# Names\n{term.upper()}\n{term}\n", normal) == (
        [term], [term], ["# Names"]
    )


@pytest.mark.parametrize("value", [
    "-sally", "sally-", "sally--anne", "sally- anne", "sally anne",
    "sally-123", "sally/anne",
])
def test_known_list_rejects_malformed_compounds(value):
    """Allow internal hyphens while retaining located validation errors."""
    with pytest.raises(ValueError, match="exclusions.txt:2: expected one word"):
        parse_terms(f"# Names\n{value}\n", BASE_NORMALIZATION, "exclusions.txt")


def test_options_preserve_defaults_and_ignore_none():
    """Check option resolution leaves defaults unchanged."""
    original = deepcopy(OPTIONS)
    selected = processing_options(OPTIONS, lemmatize=False, sort=None)
    assert selected["lemmatize"] is False
    assert selected["sort"] == "textual-frequency"
    assert OPTIONS == original


def test_filter_candidates_and_known_proposals_are_independent():
    """Check form display proposes only surviving known lemmas."""
    candidates = ["Biti", "Jesti", "On"]
    known = {"biti", "on"}
    original = deepcopy((candidates, known, BASE_NORMALIZATION))
    result = filter_occurrence(
        "je",
        candidates,
        known,
        set(),
        BASE_NORMALIZATION,
        lemmatize=False,
        filter_by="lemmas",
        exclude_unknown=False,
    )
    assert result == [("je", {"jesti"})]
    assert (candidates, known, BASE_NORMALIZATION) == original


@pytest.mark.parametrize("mode", ["forms", "lemmas"])
def test_literal_known_form_is_removed_in_each_mode(mode):
    """Check known forms supply neither display nor proposals."""
    assert (
        filter_occurrence(
            "sem",
            ["biti"],
            {"sem"},
            set(),
            BASE_NORMALIZATION,
            lemmatize=True,
            filter_by=mode,
            exclude_unknown=False,
        )
        == []
    )


def test_unknown_forms_never_propose_known_updates():
    """Check included unknown words have no known-list proposals."""
    assert filter_occurrence(
        "xyzzy",
        [],
        set(),
        set(),
        BASE_NORMALIZATION,
        lemmatize=True,
        filter_by="forms",
        exclude_unknown=False,
    ) == [("xyzzy", set())]


def test_collect_is_pure_and_highlights_only_surviving_forms(monkeypatch):
    """A known sem never supplies the example for an unknown smo."""
    monkeypatch.setattr(Path, "open", unexpected_io)
    monkeypatch.setattr("sqlite3.connect", unexpected_io)
    inputs = (
        BASE_NORMALIZATION,
        {"sem"},
        set(),
        {"sem": ["biti"], "smo": ["biti"]},
        OPTIONS,
    )
    original = deepcopy(inputs)
    entries = collect_vocabulary("SEM smo! Sem.", *inputs)
    assert len(entries) == 1
    assert entries[0].term == "biti"
    assert entries[0].count == 1
    assert entries[0].contexts == [Context("SEM smo!", 4, 7)]
    assert entries[0].known_terms == {"smo"}
    assert inputs == original


def test_add_occurrence_returns_fresh_records_and_collections():
    """Check counting preserves prior entries and their collections."""
    entry = VocabularyEntry(
        "biti", 1, 5, [Context("Sem!", 0, 3)], known_terms={"sem"}
    )
    original = deepcopy(entry)
    next_entry = add_occurrence(entry, Context("Smo!", 0, 3), {"smo"}, 1)
    assert next_entry.count == 2
    assert next_entry.first_position == 5
    assert next_entry.contexts == entry.contexts
    assert next_entry.known_terms == {"sem", "smo"}
    assert entry == original
    assert next_entry.contexts is not entry.contexts
    assert next_entry.known_terms is not entry.known_terms


def test_repeated_sentence_keeps_first_flagged_highlight():
    """Check repeated sentences keep their first flagged highlight."""
    entry = VocabularyEntry("biti", 1, 0, [Context("Sem smo!", 0, 3)])
    next_entry = add_occurrence(entry, Context("Sem smo!", 4, 7), set(), 2)
    assert next_entry.count == 2
    assert next_entry.contexts == [Context("Sem smo!", 0, 3)]


def test_context_requires_a_whole_token_inside_the_span():
    """Custom delimiters cannot produce truncated highlighted words."""
    assert (
        context_for_token(
            "hello world", Token("hello", 0, 5), [(0, 3), (3, 11)], [0, 3]
        )
        is None
    )
    assert context_for_token("hello", Token("hello", 0, 5), [], []) is None


def test_sort_returns_a_copy_and_does_not_change_records():
    """Check sorting leaves entries and their records unchanged."""
    entries = [
        VocabularyEntry("cat", 1, 0),
        VocabularyEntry("dog", 2, 4, global_frequency=0),
    ]
    original = deepcopy(entries)
    result = sort_vocabulary(
        entries, "global-frequency", [], BASE_NORMALIZATION
    )
    assert [entry.term for entry in result] == ["dog", "cat"]
    assert entries == original
    assert result is not entries
    with pytest.raises(ValueError, match="Invalid sort"):
        sort_vocabulary(entries, "invalid", [], BASE_NORMALIZATION)


def test_known_text_parsing_preserves_notes_and_reports_duplicates():
    """Check known-list parsing preserves notes and term order."""
    assert parse_terms("# My note\nSEM\n\nsem\nSmo\n", BASE_NORMALIZATION) == (
        ["sem", "smo"],
        ["sem"],
        ["# My note"],
    )
    with pytest.raises(ValueError, match="known list:2"):
        parse_terms("sem\nseveral words", BASE_NORMALIZATION)


def test_mapping_normalization_and_skip_policy():
    """Check only explicit skips accept unsupported mappings."""
    assert normalize_mapping("SEM", "biti", BASE_NORMALIZATION) == (
        "sem",
        "biti",
    )
    assert (
        normalize_mapping(
            "two words", "biti", BASE_NORMALIZATION, skip_unsupported=True
        )
        is None
    )
    with pytest.raises(ValueError, match="blank"):
        normalize_mapping(
            "", "biti", BASE_NORMALIZATION, skip_unsupported=True
        )
    with pytest.raises(ValueError, match="unsupported"):
        normalize_mapping("two words", "biti", BASE_NORMALIZATION)


def test_mapping_rejects_non_idempotent_rules():
    """Check stored keys survive repeated normalization."""
    normal = {
        "lowercase": True,
        "substitutions": [
            {"from": "a", "to": "b"},
            {"from": "c", "to": "a"},
        ],
    }
    original = deepcopy(normal)
    with pytest.raises(ValueError, match="idempotent"):
        normalize_mapping("c", "lemma", normal)
    assert normal == original


@pytest.mark.parametrize("value", ["nan", "inf", "-1", "not a number"])
def test_frequency_parser_rejects_invalid_numbers(value):
    """Frequency values must be real, finite and nonnegative."""
    with pytest.raises(ValueError):
        parse_frequency("biti", value)


def test_frequency_parser_preserves_unicode_word():
    """Check frequency parsing composes Unicode and accepts zero."""
    assert parse_frequency("c\u030caj", "0") == ("čaj", 0)


def test_history_rows_use_supplied_time_without_mutation():
    """Check history rows use supplied time and original offsets."""
    entry = VocabularyEntry("biti", 1, 0, [Context("Smo!", 0, 3)])
    original = deepcopy(entry)
    assert list(context_rows("slv", [entry], "fixed-time")) == [
        ("slv", "biti", "Smo!", 0, 3, "fixed-time"),
    ]
    assert entry == original


def control_depth(node):
    """Count the deepest chain of explicit control-flow blocks."""
    blocks = (
        ast.If,
        ast.For,
        ast.While,
        ast.With,
        ast.Try,
        ast.AsyncFor,
        ast.AsyncWith,
    )
    children = (control_depth(child) for child in ast.iter_child_nodes(node))
    return int(isinstance(node, blocks)) + max(children, default=0)


def test_application_functions_remain_flat_and_documented():
    """Check application functions stay flat and documented."""
    package = Path(__file__).resolve().parents[1] / "blitzer"
    for path in package.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        check_documented_functions(tree, path)


def check_documented_functions(tree, path):
    """Check each function against the readability constraints."""
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        label = f"{path.name}:{node.lineno}: {node.name}"
        assert ast.get_docstring(node), label
        assert max(map(control_depth, node.body), default=0) <= 2, label
        nested = [
            child
            for child in ast.walk(node)
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
            and child is not node
        ]
        assert not nested, label
