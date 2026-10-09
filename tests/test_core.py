"""Check application operations using temporary files and databases.

Purpose
-------
Verify that the public API coordinates processing and local persistence
correctly across complete operations.

In scope
--------
- Service-level filtering, ambiguity, context selection and sorting.
- Pack builds, provenance, checks, copies, removal and failed-build
  cleanup.
- Explicit orphan/unsupported-row skips and preservation of source data.
- Known-list previews, backups, cleanup and deduplicated history.
- Missing/corrupt data, mutation locks and unsafe pack paths.
- API independence from terminal output and previous calls.

Out of scope
------------
- Click flag parsing, formatting and prompts: test_cli.py.
- Config-file precedence and field validation: test_config.py.
- Focused pure-function and input-preservation checks:
  test_functions.py.

Start here
----------
Read a test matching the BlitzerService method you are changing.
conftest.py creates the small source and service fixtures these tests
use.
"""

import json
import shutil
import sqlite3
from contextlib import closing

import pytest

from blitzer.core import (
    BASE_NORMALIZATION,
    BlitzerService,
    normalize,
    tokenize,
)


def terms(entries):
    """Return term/count pairs for readable vocabulary assertions."""
    return [(x.term, x.count) for x in entries]


def test_unicode_spans():
    """Check Unicode tokens retain their original source offsets."""
    text = "ČAJ c\u030caj don't ’hello’ well-known 123 abc123def Ελληνικά"
    tokens = list(tokenize(text))
    assert [x.text for x in tokens] == [
        "ČAJ",
        "c\u030caj",
        "don't",
        "hello",
        "well",
        "known",
        "abc",
        "def",
        "Ελληνικά",
    ]
    assert all(text[slice(x.start, x.end)] == x.text for x in tokens)
    assert normalize("ČAJ", BASE_NORMALIZATION) == normalize(
        "c\u030caj", BASE_NORMALIZATION
    )


def test_ordered_substitutions():
    """Check literal substitutions run in their supplied order."""
    assert (
        normalize(
            "ABC",
            {
                "lowercase": True,
                "substitutions": [
                    {"from": "abc", "to": "x"},
                    {"from": "x", "to": "y"},
                ],
            },
        )
        == "y"
    )


def test_base_is_independent_and_sorted():
    """Check base processing works without a dictionary."""
    service = BlitzerService(use_config=False)
    assert terms(service.blitz("Dogs cats cats", "base")) == [
        ("cats", 2),
        ("dogs", 1),
    ]
    assert terms(
        service.blitz("Dogs cats cats", "base", sort="appearance")
    ) == [("dogs", 1), ("cats", 2)]
    assert service.blitz("...?! 123", "base") == []
    assert terms(service.blitz("ONE", "base")) == [("one", 1)]
    for options in (
        {"lemmatize": True},
        {"exclude_unknown": True},
        {"filter_by": "lemmas"},
    ):
        with pytest.raises(ValueError):
            service.blitz("word", "base", **options)


def test_ambiguity_unknown_and_repeat_calls(service):
    """Check ambiguity, unknowns and repeat calls remain independent."""
    assert terms(service.blitz("Je je xyzzy", "slv", lemmatize=True)) == [
        ("biti", 2),
        ("jesti", 2),
        ("on", 2),
        ("xyzzy", 1),
    ]
    assert terms(service.blitz("Je xyzzy", "slv", exclude_unknown=True)) == [
        ("je", 1)
    ]
    assert terms(service.blitz("JE", "slv", lemmatize=True)) == [
        ("biti", 1),
        ("jesti", 1),
        ("on", 1),
    ]


@pytest.mark.parametrize(
    "known,exact,mode,lemma,expected",
    [
        ("biti", "", "forms", True, [("biti", 1), ("jesti", 1), ("on", 1)]),
        ("biti", "", "lemmas", True, [("jesti", 1), ("on", 1)]),
        ("biti", "", "lemmas", False, [("je", 1)]),
        ("biti\njesti\non", "", "lemmas", False, []),
        ("je", "", "forms", True, []),
        ("", "je", "lemmas", True, []),
        ("", "biti", "lemmas", True, [("biti", 1), ("jesti", 1), ("on", 1)]),
    ],
)
def test_filter_truth_table(
    service, tmp_path, known, exact, mode, lemma, expected
):
    """Check filtering remains independent of display mode."""
    a, b = tmp_path / "known", tmp_path / "forms"
    a.write_text(known)
    b.write_text(exact)
    assert (
        terms(
            service.blitz(
                "je",
                "slv",
                exclusions=(a,),
                forms_only=(b,),
                filter_by=mode,
                lemmatize=lemma,
            )
        )
        == expected
    )


def test_exclusion_file_accepts_hyphenated_entries(service, tmp_path):
    """An unrelated compound must not prevent ordinary exclusions loading."""
    known = tmp_path / "exclusions.txt"
    known.write_text("sally-anne\nsem\n", encoding="utf-8")
    assert terms(service.blitz("sem smo", "slv", exclusions=(known,))) == [
        ("smo", 1)
    ]


def test_known_forms_never_supply_highlights(service, tmp_path):
    """Check known forms never contribute highlighted examples."""
    known = tmp_path / "known.txt"
    known.write_text("sem\n")
    entries = service.blitz(
        "Sem. SEM smo! Smo smo.",
        "slv",
        lemmatize=True,
        context=True,
        exclusions=(known,),
    )
    assert terms(entries) == [("biti", 3)]
    contexts = entries[0].contexts
    assert [
        x.text[slice(x.highlight_start, x.highlight_end)] for x in contexts
    ] == [
        "smo",
        "Smo",
    ]
    assert all(x.text != "Sem." for x in contexts)


def test_sort_modes_and_frequency_requirements(service, tmp_path):
    """Check custom and global sorts require supporting data."""
    assert [
        x.term
        for x in service.blitz(
            "je", "slv", lemmatize=True, sort="global-frequency"
        )
    ] == ["on", "biti", "jesti"]
    order = tmp_path / "order"
    order.write_text("jesti\nbiti\n")
    assert [
        x.term
        for x in service.blitz(
            "je", "slv", lemmatize=True, sort="custom", custom_order=order
        )
    ] == ["jesti", "biti", "on"]
    with pytest.raises(ValueError):
        service.blitz("je", "slv", sort="custom")
    with closing(
        sqlite3.connect(service.plugins_dir / "slv" / "lemmas.db")
    ) as conn:
        conn.execute("DELETE FROM frequencies")
        conn.commit()
    with pytest.raises(ValueError, match="frequency data"):
        service.blitz("je", "slv", sort="global-frequency")


def test_custom_sentences(service):
    """Check custom delimiters preserve sentence punctuation."""
    entries = service.blitz(
        "Sem;Smo;Je", "slv", context=True, lemmatize=True, sentence_pattern=";"
    )
    biti = next(x for x in entries if x.term == "biti")
    assert [x.text for x in biti.contexts] == ["Sem;", "Smo;"]


def test_build_provenance_conflicts_and_checks(service, source):
    """Check build counts, validation and destination conflicts."""
    stats = json.loads(
        (service.plugins_dir / "slv" / "build-info.json").read_text()
    )
    assert stats["duplicate_pairs"] == 1
    assert stats["source_rows"] == 7
    assert all(x.status == "pass" for x in service.check_plugin("slv"))
    with pytest.raises(FileExistsError):
        service.build_plugin(source)
    assert all(x.status == "pass" for x in service.check_plugin("slv"))


def test_failed_build_leaves_no_pack_or_staging(tmp_path, source):
    """Check failed imports discard staging and release their lock."""
    (source / "forms.tsv").write_text("form\tlemma\nbad entry\tlemma\n")
    service = BlitzerService(use_config=False, plugins_dir=tmp_path / "packs")
    with pytest.raises(ValueError):
        service.build_plugin(source)
    assert not list(service.plugins_dir.iterdir())


def test_install_is_independent_remove_only_one(service, tmp_path):
    """Check copied packs survive removal of the original pack."""
    other = BlitzerService(use_config=False, plugins_dir=tmp_path / "other")
    other.install_plugin(service.plugins_dir / "slv")
    service.remove_plugin("slv")
    assert terms(other.blitz("sem", "slv", lemmatize=True)) == [("biti", 1)]
    for code in ("base", "../slv", "/tmp", "SLV"):
        with pytest.raises(ValueError):
            other.remove_plugin(code)
    assert "slv" in other.list_languages()
    other.remove_plugin("slv")
    assert other.list_languages() == ["base", "eng"]


def test_missing_and_broken_db_visible(service):
    """Check missing databases fail without silently creating files."""
    db = service.plugins_dir / "slv" / "lemmas.db"
    db.unlink()
    with pytest.raises(sqlite3.Error):
        service.blitz("je", "slv", lemmatize=True)
    assert not db.exists()
    assert any(x.status == "fail" for x in service.check_plugin("slv"))


def test_known_preview_cleanup_and_history(service, tmp_path):
    """Check known-list backups and deduplicated history writes."""
    known = tmp_path / "known.txt"
    known.write_text("# Keep my note\nSEM\nsem\n")
    preview = service.cleanup_known("slv", known)
    assert preview["duplicates"] == ["sem"]
    assert known.read_text() == "# Keep my note\nSEM\nsem\n"
    service.cleanup_known("slv", known, apply=True)
    assert known.read_text() == "# Keep my note\nsem\n"
    assert (
        known.with_name("known.txt.bak").read_text()
        == "# Keep my note\nSEM\nsem\n"
    )
    entries = service.blitz(
        "Sem. Smo! xyzzy",
        "slv",
        lemmatize=True,
        context=True,
        exclusions=(known,),
        track_known=True,
    )
    change = service.update_known("slv", entries, path=known)
    assert change.additions == ("smo",)
    assert known.read_text() == "# Keep my note\nsem\n"
    assert service.history("slv") == []
    assert service.save_contexts("slv", entries) == 2
    assert service.save_contexts("slv", entries) == 0
    saved = service.history("slv", "biti")
    assert len(saved) == 1
    assert saved[0]["text"] == "Smo!"
    applied = service.update_known("slv", entries, path=known, dry_run=False)
    assert applied.applied
    assert "xyzzy" not in known.read_text()


def test_no_terminal_output(service, capsys):
    """Check API processing produces no terminal output."""
    service.blitz("Je", "slv", lemmatize=True)
    assert capsys.readouterr() == ("", "")


def test_sqlite_source_orphans_are_explicit(tmp_path, source):
    """Check explicit orphan skips preserve the source database."""
    database = tmp_path / "source.db"
    with closing(sqlite3.connect(database)) as conn:
        conn.executescript(
            "CREATE TABLE lemmas(id INTEGER,lemma TEXT); "
            "CREATE TABLE forms(form_representation TEXT,lemma_id INTEGER);"
        )
        conn.execute("INSERT INTO lemmas VALUES(1,'biti')")
        conn.executemany(
            "INSERT INTO forms VALUES(?,?)", [("sem", 1), ("orphan", 99)]
        )
        conn.commit()
    original = database.read_bytes()
    service = BlitzerService(use_config=False, plugins_dir=tmp_path / "packs")
    with pytest.raises(ValueError, match="1 orphan"):
        service.build_plugin(source, source_database=database)
    pack = service.build_plugin(
        source, source_database=database, skip_orphans=True
    )
    stats = json.loads((pack / "build-info.json").read_text())
    assert stats["source_rows"] == 2
    assert stats["orphan_source_rows"] == 1
    assert database.read_bytes() == original
    assert terms(service.blitz("sem orphan", "slv", exclude_unknown=True)) == [
        ("sem", 1)
    ]


def test_unsupported_entries_are_counted_only_when_requested(tmp_path, source):
    """Check unsupported rows are skipped only with explicit opt-in."""
    (source / "forms.tsv").write_text(
        "form\tlemma\nsem\tbiti\nveč besed\tlemma\n"
    )
    service = BlitzerService(use_config=False, plugins_dir=tmp_path / "packs")
    with pytest.raises(ValueError):
        service.build_plugin(source)
    path = service.build_plugin(source, skip_unsupported=True)
    assert (
        json.loads((path / "build-info.json").read_text())["unsupported_rows"]
        == 1
    )


def test_pack_symlink_and_traversal_protection(service, tmp_path):
    """Check pack mutations reject symlinks and unsafe codes."""
    alias = tmp_path / "alias"
    alias.symlink_to(service.plugins_dir / "slv", target_is_directory=True)
    other = BlitzerService(use_config=False, plugins_dir=tmp_path / "other")
    with pytest.raises(ValueError, match="symlink"):
        other.install_plugin(alias)
    (service.plugins_dir / "pli").symlink_to(
        service.plugins_dir / "slv", target_is_directory=True
    )
    with pytest.raises(ValueError):
        service.remove_plugin("pli")
    assert terms(service.blitz("sem", "slv", lemmatize=True)) == [("biti", 1)]


def test_lock_conflict_preserves_original(service, source):
    """Check a conflicting lock is reported and left untouched."""
    lock = service.plugins_dir / ".mutation.lock"
    lock.write_text("other writer")
    with pytest.raises(FileExistsError, match="locked"):
        service.build_plugin(source)
    assert lock.read_text() == "other writer"


def test_normalization_and_configured_exclusion_overrides(tmp_path, service):
    """Check explicit exclusions override configured lists."""
    known = tmp_path / "known.txt"
    known.write_text("sem")
    config = tmp_path / "user.toml"
    config.write_text(
        f'[locations]\nplugins_dir = "{service.plugins_dir}"\n'
        '[languages.slv]\nexclusions = ["known.txt"]\nfilter_by="forms"\n'
    )
    configured = BlitzerService(config)
    assert terms(configured.blitz("sem smo", "slv")) == [("smo", 1)]
    assert terms(configured.blitz("sem smo", "slv", exclusions=())) == [
        ("sem", 1),
        ("smo", 1),
    ]
    assert terms(configured.blitz("sem smo", "slv", no_exclusions=True)) == [
        ("sem", 1),
        ("smo", 1),
    ]


def test_invalid_frequency_input_rolls_back(tmp_path, source):
    """Check invalid corpus frequencies prevent pack publication."""
    (source / "frequencies.tsv").write_text("term\tfrequency\nbiti\tnan\n")
    service = BlitzerService(use_config=False, plugins_dir=tmp_path / "packs")
    with pytest.raises(ValueError):
        service.build_plugin(source)
    assert not list(service.plugins_dir.iterdir())


def test_invalid_row_is_not_an_unknown(service):
    """Check malformed lemma data fails rather than becoming unknown."""
    with closing(
        sqlite3.connect(service.plugins_dir / "slv" / "lemmas.db")
    ) as conn:
        conn.execute("UPDATE lemmas SET lemma='' WHERE lemma='biti'")
        conn.commit()
    with pytest.raises(ValueError, match="Invalid lemma"):
        service.blitz("sem", "slv", lemmatize=True)
    assert any(x.status == "fail" for x in service.check_plugin("slv"))


def test_bundled_english_is_available_offline(tmp_path):
    """Check fresh services provide real English without user files."""
    root = tmp_path / "absent"
    service = BlitzerService(use_config=False, plugins_dir=root)
    assert service.list_languages() == ["base", "eng"]
    assert service.language_name("eng") == "English"
    assert terms(service.blitz("dogs", "eng", lemmatize=True)) == [
        ("dog", 1)
    ]
    assert not root.exists()
    with pytest.raises(ValueError, match="bundled"):
        service.remove_plugin("eng")


def test_user_english_overrides_bundle(service, tmp_path):
    """Check local English overrides and restores bundled data."""
    root = tmp_path / "override"
    root.mkdir()
    pack = root / "eng"
    shutil.copytree(service.plugins_dir / "slv", pack)
    config = pack / "config.toml"
    config.write_text(
        config.read_text().replace('"slv"', '"eng"')
        .replace('"Slovenian"', '"Test English"')
    )
    selected = BlitzerService(use_config=False, plugins_dir=root)
    assert selected.language_name("eng") == "Test English"
    assert terms(selected.blitz("sem", "eng", lemmatize=True)) == [
        ("biti", 1)
    ]
    selected.remove_plugin("eng")
    assert selected.language_name("eng") == "English"


def test_symlinked_pack_root_is_readable(service, tmp_path):
    """Check linking a pack directory permits lookup and listing."""
    linked = tmp_path / "linked"
    linked.symlink_to(service.plugins_dir, target_is_directory=True)
    selected = BlitzerService(use_config=False, plugins_dir=linked)
    assert selected.language_name("slv") == "Slovenian"
    assert terms(selected.blitz("sem", "slv", lemmatize=True)) == [
        ("biti", 1)
    ]
