"""Verify retained language repair and selective restoration.

Scope statement:
    Check explicit registered-pack replacement without losing previous bytes.
In scope:
    - Valid repair, restoration, malformed backups, and failed downloads.
Out of scope:
    - Real network access or noncooperating direct file writers.
Start here:
    The small built Slovenian pack stands in for a registered download.
"""

import shutil

import pytest

from blitzer import core


def _download_from_installed(monkeypatch, service, tmp_path):
    """Supply a distinct valid release without using the network."""
    original = service.language_packs_dir / "slv"
    release = tmp_path / "release"
    shutil.copytree(original, release)
    config = release / "config.toml"
    config.write_text(config.read_text().replace('version = "0.1.0"', 'version = "0.2.0"'))

    def download(code, parent):
        """Copy the test release into ordinary download staging."""
        assert code == "slv"
        target = parent / code
        shutil.copytree(release, target)
        return target

    monkeypatch.setattr(core, "download_pack", download)
    monkeypatch.setattr(core, "registry_entry", lambda code: {"name": "Slovenian"})
    return original


def test_repair_retains_old_bytes_and_restore_preserves_new_version(service, monkeypatch, tmp_path):
    """Both directions use a distinct backup and a validated live pack."""
    live = _download_from_installed(monkeypatch, service, tmp_path)
    before = (live / "config.toml").read_bytes()
    result = service.repair_registered_plugin("slv")
    backup = service.language_packs_dir / result["backup"]
    assert result["schema_version"] == 1 and backup.is_dir()
    assert (backup / "config.toml").read_bytes() == before
    assert b'0.2.0' in (live / "config.toml").read_bytes()
    listed = service.list_plugin_backups("slv")
    assert listed["backups"][0] == {"name": result["backup"], "ready": True}
    assert result["backup_ready"] is True
    restored = service.restore_plugin_backup("slv", result["backup"])
    assert restored["backup_ready"] is True
    assert (live / "config.toml").read_bytes() == before
    assert b'0.2.0' in (service.language_packs_dir / restored["backup"] / "config.toml").read_bytes()


def test_repair_preserves_damaged_old_pack_and_rejects_its_restore(service, monkeypatch, tmp_path):
    """A broken former pack is kept but cannot overwrite the healthy repair."""
    live = _download_from_installed(monkeypatch, service, tmp_path)
    (live / "config.toml").write_text("broken [toml")
    result = service.repair_registered_plugin("slv")
    assert (service.language_packs_dir / result["backup"] / "config.toml").read_text() == "broken [toml"
    assert result["backup_ready"] is False
    assert service.list_plugin_backups("slv")["backups"][0]["ready"] is False
    with pytest.raises(ValueError):
        service.restore_plugin_backup("slv", result["backup"])
    assert b'0.2.0' in (live / "config.toml").read_bytes()


def test_repair_failure_and_foreign_backup_leave_installed_bytes(service, monkeypatch, tmp_path):
    """No release or arbitrary sibling basename gains replacement authority."""
    live = _download_from_installed(monkeypatch, service, tmp_path)
    before = (live / "config.toml").read_bytes()
    monkeypatch.setattr(core, "download_pack", lambda code, parent: (_ for _ in ()).throw(OSError("offline")))
    with pytest.raises(OSError, match="offline"):
        service.repair_registered_plugin("slv")
    with pytest.raises(ValueError):
        service.restore_plugin_backup("slv", "../slv")
    assert (live / "config.toml").read_bytes() == before
