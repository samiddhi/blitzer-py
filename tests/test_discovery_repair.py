"""Verify isolated discovery of healthy and damaged installed languages.

Scope statement:
    Test metadata failure isolation using synthetic packs in temporary directories.
Purpose:
    Keep a damaged pack discoverable without blocking independent working languages.
In scope:
    - API discovery status and specialist CLI list output.
    - Strict failure when a damaged language is selected for processing.
Out of scope:
    - Download dictionaries, guess damaged metadata, or modify personal packs.
Start here:
    The existing service fixture supplies a valid synthetic Slovenian pack.
"""

import json
import hashlib

from click.testing import CliRunner
import pytest

from blitzer.cli import cli


def test_damaged_pack_does_not_hide_healthy_languages(service):
    """A malformed neighbouring pack yields a repair status while working packs remain selectable."""
    broken = service.language_packs_dir / "fra"
    broken.mkdir()
    (broken / "config.toml").write_text("broken [toml")
    (broken / "lemmas.db").write_bytes(b"not a dictionary")
    assert {"base", "eng", "slv", "fra"} <= set(service.list_languages())
    rows = {row["code"]: row for row in service.discover_languages()}
    assert rows["fra"]["status"] == "needs-repair" and rows["fra"]["error"]
    assert rows["slv"]["status"] == "available"
    result = CliRunner().invoke(
        cli,
        [
            "list-languages",
            "--no-config",
            "--plugins-dir",
            str(service.language_packs_dir),
        ],
    )
    assert (
        result.exit_code == 0
        and "fra" in result.output
        and "needs repair" in result.output
    )
    assert "slv" in result.output and "English" in result.output
    with pytest.raises(ValueError):
        service.blitz("bonjour", "fra")


def test_read_only_public_configuration_and_capability_contract(service):
    """Effective pack paths/hashes are authoritative and inspection leaves bytes unchanged."""
    root = service.language_packs_dir / "slv"
    paths = [root / "config.toml", root / "lemmas.db"]
    before = {str(path): path.read_bytes() for path in paths}
    value = service.inspect_configuration("slv")
    assert value["schema_version"] == 1 and value["pack_directory"] == str(root)
    assert value["files"] == {
        name: hashlib.sha256(data).hexdigest() for name, data in before.items()
    }
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "inspect",
            "--no-config",
            "--language",
            "slv",
            "--plugins-dir",
            str(service.language_packs_dir),
        ],
    )
    assert result.exit_code == 0 and json.loads(result.output) == value
    caps = runner.invoke(cli, ["capabilities"])
    assert (
        caps.exit_code == 0 and json.loads(caps.output)["configuration_inspection"] == 1
    )
    assert {str(path): path.read_bytes() for path in paths} == before
