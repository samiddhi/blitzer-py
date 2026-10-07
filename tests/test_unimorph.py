"""Verify UniMorph conversion and release eligibility.

Purpose
-------
Check that batch conversion preserves vocabulary relationships while
keeping unsupported languages and malformed input out of release assets.

In scope
--------
- Pure parsing, script detection and source-file selection.
- Compressed input, ambiguous forms, attribution and source checksums.
- Pack validation, deferred output, error reports and source isolation.
- CLI execution and downloadable-language catalog selection.

Out of scope
------------
- GitHub publishing, real dictionary completeness or language expertise.
- Repeating core database validation and HTTP download safety tests.

Start here
----------
test_batch_classification builds a miniature checkout end to end. The
remaining tests isolate input selection, errors and command behavior.
"""

import json
import lzma
import sqlite3

import pytest
from click.testing import CliRunner

from blitzer.core import BlitzerService
from blitzer.downloads import load_language_registry
from maintenance.unimorph import (
    main,
    build_all,
    deferred_reasons,
    parse_row,
    release_size_reasons,
    registry_catalog,
    script_names,
    source_files,
    source_row,
)


def make_language(root, code, text):
    """Create a miniature upstream language folder for a test."""
    directory = root / code
    directory.mkdir(parents=True)
    (directory / code).write_text(text, encoding="utf-8")
    (directory / "README.md").write_text(
        f"# Test language ({code})\n\nOriginal attribution.\n",
        encoding="utf-8",
    )
    return directory


def test_batch_classification(tmp_path):
    """Check pack classification, missing data and provenance."""
    source = tmp_path / "source"
    directory = make_language(
        source,
        "eng",
        "# comment\nbe\tis\tV;SG\nbelong\tis\tV\nbe\tis\tV\n"
        "go\tgo away\tV\n",
    )
    (directory / "LICENSE").write_text("Original license", encoding="utf-8")
    make_language(source, "rus", "быть\tесть\tV\n")
    make_language(source, "tha", "pai\tpai\tV\n")
    (source / "epo").mkdir()
    before = {p: p.read_bytes() for p in source.rglob("*") if p.is_file()}
    output = tmp_path / "output"
    records = build_all(source, output)
    statuses = {row["code"]: row["status"] for row in records}
    assert statuses == {
        "eng": "ready",
        "rus": "deferred",
        "tha": "deferred",
        "epo": "missing-data",
    }
    assert before == {p: p.read_bytes() for p in before}
    assert {p.name for p in (output / "ready/assets").glob("*.zip")} == {
        "blitzer-eng-v1.zip"
    }
    assert (output / "deferred/assets/blitzer-rus-v1.zip").exists()
    service = BlitzerService(
        use_config=False, plugins_dir=output / "ready/packs"
    )
    assert all(check.status == "pass" for check in service.check_plugin("eng"))
    pack = output / "ready/packs/eng"
    with sqlite3.connect(pack / "lemmas.db") as conn:
        matches = conn.execute(
            "SELECT lemma FROM lemmas JOIN forms ON lemmas.id=forms.lemma_id "
            "WHERE form_representation='is' ORDER BY lemma"
        ).fetchall()
    assert matches == [("be",), ("belong",)]
    info = json.loads((pack / "build-info.json").read_text())
    assert info["unimorph"]["unsupported_rows"] == 1
    assert info["duplicate_pairs"] == 1
    assert info["unimorph"]["duplicate_pairs_removed"] == 1
    assert len(info["unimorph"]["sources"][0]["sha256"]) == 64
    assert "Original attribution" in (pack / "README.md").read_text()
    assert "Original license" in (pack / "LICENSE").read_text()
    catalog = load_language_registry(output / "registry.json")
    assert set(catalog) == {"eng"}


def test_source_selection_and_compressed_data(tmp_path):
    """Check source selection and XZ fallback."""
    root = tmp_path / "source"
    directory = make_language(root, "fra", "old\tolds\tN\n")
    for name in ("fra.um4", "fra-dialect", "fra.derivations", "fra.args"):
        (directory / name).write_text("new\tnews\tN\n", encoding="utf-8")
    (directory / "fra.xz").write_bytes(lzma.compress(b"old\tolds\tN\n"))
    assert [p.name for p in source_files(directory)] == [
        "fra-dialect",
        "fra.um4",
    ]
    slovak = root / "slk"
    slovak.mkdir()
    (slovak / "slk.xz").write_bytes(lzma.compress(b"word\twords\tN\tPL\n"))
    records = build_all(root, tmp_path / "output", languages=("slk",))
    assert records[0]["status"] == "ready"
    assert records[0]["accepted_rows"] == 1


def test_malformed_and_csv_inputs_are_reported(tmp_path):
    """Check BOM CSV support and exclusion of malformed datasets."""
    root = tmp_path / "source"
    make_language(root, "eng", "word\twords\tN\nbroken\n")
    directory = root / "pbs"
    directory.mkdir()
    (directory / "pbs.csv").write_text(
        "\ufeffword,words,N;PL\n", encoding="utf-8"
    )
    records = build_all(root, tmp_path / "output")
    assert records[0]["status"] == "deferred"
    assert records[0]["malformed_rows"] == 1
    assert records[1]["status"] == "ready"


def test_failure_isolation_and_destination_protection(tmp_path):
    """Check failure isolation and destination protection."""
    root = tmp_path / "source"
    make_language(root, "eng", "word\twords\tN\n")
    directory = root / "slk"
    directory.mkdir()
    (directory / "slk.xz").write_bytes(b"not XZ")
    output = tmp_path / "output"
    records = build_all(root, output)
    assert [row["status"] for row in records] == ["ready", "error"]
    assert json.loads((output / "report.json").read_text()) == records
    with pytest.raises(FileExistsError):
        build_all(root, output)
    with pytest.raises(ValueError, match="outside"):
        build_all(root, root / "generated")


def test_pure_classification():
    """Check scripts, comments and segmentation overrides."""
    assert script_names("café na\u0308ive nʼa") == set()
    assert script_names("LatinЖ") == {"CYRILLIC"}
    assert deferred_reasons("tha", set())
    assert not deferred_reasons("eng", set())
    assert parse_row(["# ignore"]) is None
    assert parse_row(["word", "words", "N", "extra"]) == ("word", "words")
    with pytest.raises(ValueError):
        parse_row(["", "form", "N"])
    assert parse_row(["word", "", "N"]) is None
    assert parse_row(["word", "words", ""]) == ("word", "words")
    row = ["", "word", "words", "N"]
    assert source_row(row, "sdh") == ["word", "words", "N"]
    assert source_row(row, "eng") is row
    records = [
        {"code": "eng", "name": "English", "status": "ready"},
        {"code": "slv", "name": "Slovenian", "status": "ready"},
        {"code": "rus", "name": "Russian", "status": "deferred"},
    ]
    assert registry_catalog(records) == {"eng": {"name": "English"}}


def test_batch_cli(tmp_path):
    """Check the maintainer command exposes its output report."""
    source = tmp_path / "source"
    make_language(source, "eng", "word\twords\tN\n")
    result = CliRunner().invoke(
        main, [str(source), "--output", str(tmp_path / "out")]
    )
    assert result.exit_code == 0, result.output
    assert "eng: ready" in result.output
    assert "REPORT.md" in result.output


def test_isolated_foreign_spellings_are_omitted(tmp_path):
    """Keep a Latin pack and count isolated foreign-script rows."""
    source = tmp_path / "source"
    make_language(source, "eng", "word\twords\tN\n" * 101 + "βeta\tβetas\tN\n")
    output = tmp_path / "output"
    records = build_all(source, output)
    assert records[0]["status"] == "ready"
    assert records[0]["excluded_non_latin_rows"] == 1
    with sqlite3.connect(output / "ready/packs/eng/lemmas.db") as conn:
        assert conn.execute("SELECT lemma FROM lemmas").fetchall() == [
            ("word",)
        ]


def test_oversized_pack_is_deferred(tmp_path, monkeypatch):
    """Keep oversized archives out of release assets."""
    monkeypatch.setattr("maintenance.unimorph.MAX_DOWNLOAD_BYTES", 1)
    source = tmp_path / "source"
    make_language(source, "eng", "word\twords\tN\n")
    output = tmp_path / "output"
    records = build_all(source, output)
    assert records[0]["status"] == "deferred"
    assert not list((output / "ready/assets").glob("*.zip"))
    assert (output / records[0]["archive"]).exists()
    assert not registry_catalog(records)
    assert release_size_reasons(3 * 1024**3, 1024**3)
