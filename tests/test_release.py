"""Check release planning and retries without publishing anything.

Purpose
-------
Verify content comparisons and command ordering using temporary packs
and simulated GitHub and Git responses.

In scope
--------
- Patch bumps, stable asset selection and content fingerprints.
- Ignoring deferred packs and using verified historical archives.
- No-op decisions and resuming an existing publication checkpoint.
- Draft publication and retaining the checkpoint on upload failures.

Out of scope
------------
- Real commits, pushes, authentication or GitHub/PyPI publication.
- Runtime vocabulary behavior and production dictionary correctness.

Start here
----------
Tests call maintenance.release helpers with mocked subprocess results.
The maintenance module and this test are excluded from distributions.
"""

import json
import subprocess
import zipfile
from unittest.mock import Mock

import pytest

from maintenance import release


def test_patch_bump_preserves_major_and_minor():
    """Check patch versions continue correctly beyond a single digit."""
    assert release.next_patch("0.2.3") == "0.2.4"
    assert release.next_patch("0.2.9") == "0.2.10"
    with pytest.raises(ValueError):
        release.next_patch("0.2")


def test_fingerprints_ignore_timestamps_and_unrelated_files(tmp_path):
    """Check comparisons detect contents rather than metadata."""
    config = tmp_path / "config.toml"
    config.write_text("first")
    (tmp_path / "lemmas.db").write_bytes(b"dictionary")
    original = release.fingerprint_pack(tmp_path)
    config.touch()
    (tmp_path / ".DS_Store").write_bytes(b"unrelated")
    assert release.fingerprint_pack(tmp_path) == original
    config.write_text("second")
    assert release.fingerprint_pack(tmp_path) != original


def test_ready_packs_excludes_deferred_and_incomplete(tmp_path):
    """Check only complete three-letter packs are selected."""
    for code in ("eng", "dev", "slv"):
        path = tmp_path / code
        path.mkdir()
        (path / "config.toml").write_text("config")
    (tmp_path / "eng" / "lemmas.db").write_bytes(b"db")
    (tmp_path / "dev" / "slv").mkdir()
    assert release.ready_packs(tmp_path) == {"eng": tmp_path / "eng"}


def test_stable_assets_selects_newest_per_language():
    """Check draft assets do not hide older stable language packs."""
    asset = {"name": "pack.zip", "state": "uploaded"}
    releases = [
        {
            "draft": True,
            "prerelease": False,
            "tag_name": "draft",
            "assets": [asset],
        },
        {
            "draft": False,
            "prerelease": True,
            "tag_name": "pre",
            "assets": [asset],
        },
        {
            "draft": False,
            "prerelease": False,
            "tag_name": "new",
            "assets": [asset],
        },
        {
            "draft": False,
            "prerelease": False,
            "tag_name": "old",
            "assets": [asset],
        },
    ]
    assert release.stable_assets(releases)["pack.zip"] == ("new", asset)


def test_verified_existing_archive_bootstraps_baseline(tmp_path, monkeypatch):
    """Check verified local ZIPs avoid dictionary downloads."""
    assets = tmp_path / "release-assets"
    assets.mkdir()
    archive = assets / "blitzer-slv-v1.zip"
    with zipfile.ZipFile(archive, "w") as stream:
        stream.writestr("slv/config.toml", "config")
        stream.writestr("slv/lemmas.db", "database")
    descriptor = {
        "name": archive.name,
        "digest": "sha256:" + release.fingerprint_file(archive),
    }
    download = Mock(side_effect=AssertionError("Network not expected"))
    monkeypatch.setattr(release, "ROOT", tmp_path)
    monkeypatch.setattr(release, "download_asset", download)
    assert release.historical_fingerprint("v0.2.0", descriptor, "slv") == (
        release.fingerprint_archive(archive, "slv")
    )
    download.assert_not_called()


def test_unchanged_source_and_packs_skip_release(tmp_path, monkeypatch):
    """Check an unchanged checkout does not test, bump or publish."""
    monkeypatch.setattr(release, "ROOT", tmp_path)
    monkeypatch.setattr(release, "ready_packs", Mock(return_value={}))
    monkeypatch.setattr(release, "github_releases", Mock(return_value=[]))
    monkeypatch.setattr(release, "previous_packs", Mock(return_value={}))
    monkeypatch.setattr(release, "project_version", Mock(return_value="0.2.3"))
    monkeypatch.setattr(release, "source_changed", Mock(return_value=False))
    command = Mock(side_effect=AssertionError("No commands expected"))
    monkeypatch.setattr(release, "run", command)
    assert release.prepare_release() is None
    command.assert_not_called()


def test_changed_pack_is_packaged_and_checkpointed(tmp_path, monkeypatch):
    """Check a dictionary update releases even with unchanged source."""
    pack = tmp_path / "language-packs" / "slv"
    pack.mkdir(parents=True)
    (pack / "config.toml").write_text("changed")
    (pack / "lemmas.db").write_bytes(b"dictionary")
    monkeypatch.setattr(release, "ROOT", tmp_path)
    monkeypatch.setattr(release, "WORK", tmp_path / "work")
    monkeypatch.setattr(release, "PENDING", tmp_path / "work" / "pending.json")
    monkeypatch.setattr(release, "github_releases", Mock(return_value=[]))
    monkeypatch.setattr(release, "previous_packs", Mock(return_value={}))
    monkeypatch.setattr(release, "project_version", Mock(return_value="0.2.3"))
    command = Mock()
    monkeypatch.setattr(release, "run", command)
    package = Mock(return_value=[tmp_path / "slv.zip"])
    monkeypatch.setattr(release, "package_changes", package)
    state = release.prepare_release()
    assert state["version"] == "0.2.4"
    assert state["changed"] == ["slv"]
    assert json.loads(release.PENDING.read_text()) == state
    assert package.call_args.args[1] == ["slv"]
    assert command.call_args.args[1:3] == ("-m", "pytest")


def test_resumed_committed_release_does_not_bump_again(tmp_path, monkeypatch):
    """Check upload retries preserve the version and commit."""
    pending = tmp_path / "pending.json"
    pending.write_text("{}")
    monkeypatch.setattr(release, "PENDING", pending)
    commit = Mock(side_effect=AssertionError("Do not bump again"))
    monkeypatch.setattr(release, "commit_release", commit)
    push = Mock()
    publish = Mock()
    monkeypatch.setattr(release, "push_release", push)
    monkeypatch.setattr(release, "publish_github", publish)
    state = {"head": "commit", "version": "0.2.4"}
    release.finish_release(state)
    push.assert_called_once_with(state, "v0.2.4")
    publish.assert_called_once_with(state, "v0.2.4")
    assert not pending.exists()


def test_failed_upload_keeps_checkpoint(tmp_path, monkeypatch):
    """Check publication failures preserve enough state to retry."""
    pending = tmp_path / "pending.json"
    pending.write_text("{}")
    monkeypatch.setattr(release, "PENDING", pending)
    monkeypatch.setattr(release, "push_release", Mock())
    monkeypatch.setattr(
        release, "publish_github", Mock(side_effect=OSError("upload failed"))
    )
    with pytest.raises(OSError, match="upload failed"):
        release.finish_release({"head": "commit", "version": "0.2.4"})
    assert pending.exists()


def test_draft_assets_are_uploaded_before_publication(monkeypatch):
    """Check releases stay private until assets are uploaded."""
    view = subprocess.CompletedProcess([], 0, stdout='{"isDraft": true}')
    command = Mock(side_effect=[view, None, None])
    monkeypatch.setattr(release, "run", command)
    release.publish_github(
        {"assets": ["pack.zip"], "manifest": "manifest"}, "v0.2.4"
    )
    assert command.call_args_list[1].args[1:3] == ("release", "upload")
    assert command.call_args_list[2].args[1:3] == ("release", "edit")


def test_twine_ignores_finder_files_and_directories(tmp_path, monkeypatch):
    """Check resumed build validation ignores filesystem clutter."""
    output = tmp_path / "app-v0.2.4"
    output.mkdir()
    for name in ("app.whl", "app.tar.gz", ".DS_Store", "other.zip"):
        (output / name).write_bytes(b"fixture")
    (output / "directory.whl").mkdir()
    monkeypatch.setattr(release, "WORK", tmp_path)
    monkeypatch.setattr(release, "PENDING", tmp_path / "pending.json")
    monkeypatch.setattr(release, "project_version", Mock(return_value="0.2.4"))
    monkeypatch.setattr(release.shutil, "rmtree", Mock())
    staged = subprocess.CompletedProcess([], 1)
    command = Mock(side_effect=[None, None, None, staged, None, "commit"])
    monkeypatch.setattr(release, "run", command)
    state = {"previous_version": "0.2.3", "version": "0.2.4", "head": None}
    release.commit_release(state)
    assert command.call_args_list[1].args[1:] == (
        "-m",
        "twine",
        "check",
        str(output / "app.tar.gz"),
        str(output / "app.whl"),
    )
    assert state["head"] == "commit"
