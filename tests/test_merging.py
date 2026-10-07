"""Verify dictionary expansion preserves data and unique lookup pairs.

Purpose
-------
Check pack union through the public API with small real SQLite packs.

In scope
--------
- Deduplication, ambiguous matches and exact addition counts.
- Base frequencies, source attribution and additional provenance.
- No-op merges and refusal of incompatible normalization settings.
- Metadata version editing and the expansion command.

Out of scope
------------
- UniMorph input parsing and script classification: test_unimorph.py.
- Repeating staged-install rollback tests or using full dictionaries.

Start here
----------
test_expand_preserves_base_data exercises the public expansion API.
The other tests isolate unchanged merges and incompatible settings.
"""

import json
import sqlite3

import pytest
from click.testing import CliRunner

from blitzer.cli import cli
from blitzer.core import BlitzerService
from blitzer.merging import change_version, pack_hash


def additional_pack(source, tmp_path):
    """Build overlapping data with a new lemma and an ambiguous form."""
    (source / "forms.tsv").write_text(
        "form\tlemma\nje\tbiti\nnov\tnov\nnovega\tnov\nnovega\tnov\n"
        "je\tnov\n",
        encoding="utf-8",
    )
    (source / "README.md").write_text(
        "Additional attribution", encoding="utf-8"
    )
    service = BlitzerService(use_config=False, plugins_dir=tmp_path / "extra")
    return service.build_plugin(source)


def test_expand_preserves_base_data(service, source, tmp_path):
    """Check pair union, existing frequencies and source isolation."""
    extra = additional_pack(source, tmp_path)
    original_hash = pack_hash(extra / "lemmas.db")
    stats = service.expand_plugin("slv", extra)
    assert stats["lemmas_added"] == 1
    assert stats["pairs_added"] == 3
    base = service.plugins_dir / "slv"
    with sqlite3.connect(base / "lemmas.db") as conn:
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM forms f JOIN lemmas l "
                "ON l.id=f.lemma_id "
                "WHERE f.form_representation='novega' AND l.lemma='nov'"
            ).fetchone()[0]
            == 1
        )
        assert (
            conn.execute(
                "SELECT frequency FROM frequencies WHERE term='biti'"
            ).fetchone()[0]
            == 20
        )
    assert {e.term for e in service.blitz("je", "slv", lemmatize=True)} == {
        "biti",
        "jesti",
        "on",
        "nov",
    }
    assert "Additional attribution" in (base / "README.md").read_text()
    info = json.loads((base / "build-info.json").read_text())
    assert info["additional_sha256"] == original_hash
    assert "base_build" in info
    assert pack_hash(extra / "lemmas.db") == original_hash
    assert all(check.status == "pass" for check in service.check_plugin("slv"))
    before = {p.name: p.read_bytes() for p in base.iterdir()}
    assert service.expand_plugin("slv", extra)["pairs_added"] == 0
    assert before == {p.name: p.read_bytes() for p in base.iterdir()}


def test_incompatible_normalization_is_rejected(service, source, tmp_path):
    """Reject incompatible normalization before replacing a pack."""
    extra = additional_pack(source, tmp_path)
    config = extra / "config.toml"
    config.write_text(
        config.read_text().replace("lowercase = true", "lowercase = false")
    )
    base = service.plugins_dir / "slv"
    before = pack_hash(base / "lemmas.db")
    with pytest.raises(ValueError, match="normalization"):
        service.expand_plugin("slv", extra)
    assert pack_hash(base / "lemmas.db") == before


def test_version_editing_and_cli(service, source, tmp_path):
    """Check version editing and the expansion command."""
    text = (source / "config.toml").read_text()
    assert 'version = "0.9.0"' in change_version(text, "0.9.0")
    with pytest.raises(ValueError):
        change_version(text, "")
    extra = additional_pack(source, tmp_path)
    result = CliRunner().invoke(
        cli,
        [
            "dev",
            "expand-plugin",
            "slv",
            str(extra),
            "--no-config",
            "--plugins-dir",
            str(service.plugins_dir),
        ],
    )
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["pairs_added"] == 3
