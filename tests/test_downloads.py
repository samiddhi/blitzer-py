"""Check registered downloads, safe archives and staged pack updates.

Purpose
-------
Verify the complete installer with simulated GitHub responses, without
network access or changes to real installed language packs.

In scope
--------
- Registry codes, independent release selection and paginated metadata.
- HTTPS-only asset URLs, byte counts and SHA-256 verification.
- ZIP path, type, size and required-file validation before extraction.
- Successful remote and offline local installs through the public API.
- Explicit replacement, rollback and release archive preparation.

Out of scope
------------
- Publishing actual GitHub releases or requesting public downloads.
- Production dictionary quality or third-party data licensing.
- Vocabulary algorithms, configuration policy and performance testing.

Start here
----------
release_fixture makes a tiny archive and matching GitHub metadata.
mock_download provides in-memory responses. The remaining tests exercise
pure validation helpers and the API or CLI installation sequence.
"""

import hashlib
import io
import json
import shutil
import ssl
import stat
import zipfile
from copy import deepcopy
from pathlib import Path
from unittest.mock import Mock

import pytest
from click.testing import CliRunner

from blitzer import downloads
from blitzer.cli import cli
from blitzer.core import BlitzerService


def release_fixture(service, code, tmp_path):
    """Prepare a small archive and matching release metadata."""
    root = tmp_path / "published"
    directory = root / code
    shutil.copytree(service.plugins_dir / "slv", directory)
    config = directory / "config.toml"
    config.write_text(config.read_text().replace('"slv"', f'"{code}"'))
    publisher = BlitzerService(use_config=False, plugins_dir=root)
    archive = publisher.package_plugin(code, tmp_path / "assets")
    content = archive.read_bytes()
    asset = {
        "name": downloads.asset_name(code),
        "state": "uploaded",
        "browser_download_url": (
            f"https://github.com/{downloads.REPOSITORY}/releases/download/"
            f"{code}-v0.1.0/{archive.name}"
        ),
        "digest": "sha256:" + hashlib.sha256(content).hexdigest(),
        "size": len(content),
    }
    release = {
        "tag_name": f"{code}-v0.1.0",
        "draft": False,
        "prerelease": False,
        "assets": [asset],
    }
    return content, release


def mock_download(monkeypatch, content, releases):
    """Simulate metadata and archive responses in memory."""
    monkeypatch.setattr(downloads, "_read_json", lambda url: releases)
    monkeypatch.setattr(
        downloads, "_open_response", lambda url, accept: io.BytesIO(content)
    )


@pytest.mark.parametrize("code", ["slv", "pol", "pli"])
def test_registered_language_installs_via_cli(
    service, tmp_path, monkeypatch, code
):
    """Check each registry code installs through the CLI."""
    content, release = release_fixture(service, code, tmp_path)
    mock_download(monkeypatch, content, [release])
    root = tmp_path / "installed"
    result = CliRunner().invoke(
        cli,
        ["install-plugin", code, "--no-config", "--plugins-dir", str(root)],
    )
    assert result.exit_code == 0, result.output
    assert (root / code / "lemmas.db").is_file()
    installed = BlitzerService(use_config=False, plugins_dir=root)
    assert all(item.status == "pass" for item in installed.check_plugin(code))
    assert installed.blitz("sem", code, lemmatize=True)[0].term == "biti"


def test_registry_lookup_and_asset_names():
    """Check registry codes and version-independent filenames."""
    assert {"slv", "pol", "pli"} <= set(downloads.REGISTRY)
    assert downloads.asset_name("pol") == "blitzer-pol-v1.zip"
    with pytest.raises(ValueError, match="No registered"):
        downloads.registry_entry("zzz")
    with pytest.raises(ValueError):
        downloads.registry_entry("base")


def test_release_selection_is_independent_and_pure(service, tmp_path):
    """Check release selection ignores unrelated or unstable packs."""
    _, release = release_fixture(service, "slv", tmp_path)
    prerelease = deepcopy(release)
    prerelease["prerelease"] = True
    draft = deepcopy(release)
    draft["draft"] = True
    unrelated = {"tag_name": "pol-v9", "assets": []}
    releases = [prerelease, draft, unrelated, release]
    original = deepcopy(releases)
    selected = downloads.select_release_asset(
        releases, "slv", downloads.REPOSITORY
    )
    assert selected.tag == "slv-v0.1.0"
    assert releases == original


def test_release_selection_walks_pages(service, tmp_path, monkeypatch):
    """Check release lookup continues past unrelated pages."""
    _, release = release_fixture(service, "slv", tmp_path)
    calls = []
    pages = [[{"assets": []}] * 100, [release]]
    monkeypatch.setattr(
        downloads, "_read_json", lambda url: record_page(calls, pages, url)
    )
    assert downloads.resolve_release("slv").tag == "slv-v0.1.0"
    assert calls[0].endswith("page=1")
    assert calls[1].endswith("page=2")


def record_page(calls, pages, url):
    """Record a simulated request and return its response page."""
    calls.append(url)
    return pages.pop(0)


def test_missing_asset_explains_publication_step(monkeypatch):
    """Check missing releases explain the publication requirement."""
    monkeypatch.setattr(downloads, "_read_json", lambda url: [])
    with pytest.raises(ValueError, match="publish a version-one pack"):
        downloads.resolve_release("pli")


@pytest.mark.parametrize(
    "field,value",
    [
        ("digest", None),
        ("digest", "sha256:bad"),
        ("browser_download_url", "http://github.com/bad.zip"),
        ("browser_download_url", "https://example.com/bad.zip"),
        ("size", 0),
        ("size", True),
        ("size", downloads.MAX_DOWNLOAD_BYTES + 1),
    ],
)
def test_release_metadata_rejects_invalid_assets(
    service, tmp_path, field, value
):
    """Check asset metadata must be trustworthy and verifiable."""
    _, release = release_fixture(service, "slv", tmp_path)
    release["assets"][0][field] = value
    with pytest.raises(ValueError):
        downloads.select_release_asset([release], "slv", downloads.REPOSITORY)


@pytest.mark.parametrize("mutation", ["digest", "truncated", "extra"])
def test_bad_download_preserves_installed_pack(
    service, tmp_path, monkeypatch, mutation
):
    """Check failed downloads preserve existing pack bytes."""
    content, release = release_fixture(service, "slv", tmp_path)
    original = (service.plugins_dir / "slv" / "lemmas.db").read_bytes()
    if mutation == "digest":
        release["assets"][0]["digest"] = "sha256:" + "0" * 64
    if mutation == "truncated":
        content = content[:-1]
    if mutation == "extra":
        content += b"extra"
    mock_download(monkeypatch, content, [release])
    with pytest.raises(ValueError, match="verification|advertised size"):
        service.install_plugin("slv", replace=True)
    assert (service.plugins_dir / "slv" / "lemmas.db").read_bytes() == original
    assert not (service.plugins_dir / ".mutation.lock").exists()


def archive_members(extra):
    """Return required ZIP members plus a supplied candidate entry."""
    return [
        zipfile.ZipInfo("slv/config.toml"),
        zipfile.ZipInfo("slv/lemmas.db"),
        extra,
    ]


@pytest.mark.parametrize(
    "name",
    [
        "../escape",
        "/slv/README.md",
        "slv/../README.md",
        "pol/README.md",
        "slv/nested/README.md",
        "slv\\README.md",
        "slv/config.toml",
    ],
)
def test_archive_rejects_unsafe_or_duplicate_paths(name):
    """Check unsafe or duplicate archive paths fail validation."""
    with pytest.raises(ValueError):
        downloads.validate_archive_members(
            archive_members(zipfile.ZipInfo(name)), "slv"
        )


def test_archive_rejects_links_encryption_and_excessive_size():
    """Check ZIP files reject special entries and excessive data."""
    link = zipfile.ZipInfo("slv/README.md")
    link.external_attr = (stat.S_IFLNK | 0o777) << 16
    with pytest.raises(ValueError, match="special"):
        downloads.validate_archive_members(archive_members(link), "slv")
    encrypted = zipfile.ZipInfo("slv/README.md")
    encrypted.flag_bits = 1
    with pytest.raises(ValueError, match="encrypted"):
        downloads.validate_archive_members(archive_members(encrypted), "slv")
    enormous = zipfile.ZipInfo("slv/README.md")
    enormous.file_size = downloads.MAX_UNPACKED_BYTES + 1
    with pytest.raises(ValueError, match="expanded"):
        downloads.validate_archive_members(archive_members(enormous), "slv")


def test_archive_requires_pack_files():
    """Check archives require configuration and a database."""
    with pytest.raises(ValueError, match="needs config"):
        downloads.validate_archive_members(
            [zipfile.ZipInfo("slv/README.md")], "slv"
        )


def test_invalid_zip_is_a_readable_error(tmp_path):
    """Check malformed ZIP data produces a readable domain error."""
    archive = tmp_path / "bad.zip"
    archive.write_bytes(b"not a zip")
    with pytest.raises(ValueError, match="Invalid pack ZIP"):
        downloads.extract_pack(archive, tmp_path, "slv")


def test_local_path_install_and_replace_remain_offline(
    service, tmp_path, monkeypatch
):
    """Check local installation and replacement stay offline."""
    monkeypatch.setattr("blitzer.core.download_pack", reject_network)
    root = tmp_path / "local"
    target = BlitzerService(use_config=False, plugins_dir=root)
    target.install_plugin(service.plugins_dir / "slv")
    with pytest.raises(FileExistsError, match="--replace"):
        target.install_plugin(service.plugins_dir / "slv")
    known = tmp_path / "known.txt"
    known.write_text("sem\n")
    target.config["languages"]["slv"] = {"known_file": known}
    entries = target.blitz("Smo!", "slv", context=True)
    target.save_contexts("slv", entries)
    history = target.config["locations"]["history_file"]
    history_bytes = history.read_bytes()
    target.install_plugin(str(service.plugins_dir / "slv"), replace=True)
    assert known.read_text() == "sem\n"
    assert history.read_bytes() == history_bytes
    assert not (root / ".slv.previous").exists()
    result = CliRunner().invoke(
        cli,
        [
            "install-plugin",
            str(service.plugins_dir / "slv"),
            "--replace",
            "--no-config",
            "--plugins-dir",
            str(root),
        ],
    )
    assert result.exit_code == 0, result.output


def reject_network(*args, **kwargs):
    """Fail if a local installation attempts a registered download."""
    raise AssertionError("Local installation must remain offline")


def test_replacement_rolls_back_on_publish_failure(
    service, tmp_path, monkeypatch
):
    """Check failed publication restores the old pack directory."""
    target = BlitzerService(
        use_config=False, plugins_dir=tmp_path / "installed"
    )
    target.install_plugin(service.plugins_dir / "slv")
    database = target.plugins_dir / "slv" / "lemmas.db"
    original = database.read_bytes()
    rename = Path.rename
    monkeypatch.setattr(
        Path,
        "rename",
        lambda path, dest: fail_staging_rename(rename, path, dest),
    )
    with pytest.raises(OSError, match="simulated"):
        target.install_plugin(service.plugins_dir / "slv", replace=True)
    assert database.read_bytes() == original
    assert not (target.plugins_dir / ".slv.previous").exists()
    assert not (target.plugins_dir / ".mutation.lock").exists()


def fail_staging_rename(rename, path, destination):
    """Fail publication while allowing rollback to succeed."""
    if path.parent.name.startswith(".install-"):
        raise OSError("simulated publication failure")
    return rename(path, destination)


def test_remote_metadata_must_match_requested_code(
    service, tmp_path, monkeypatch
):
    """Check downloaded metadata matches the requested language."""
    root = tmp_path / "installed"
    target = BlitzerService(use_config=False, plugins_dir=root)
    monkeypatch.setattr(
        "blitzer.core.download_pack",
        lambda code, directory: service.plugins_dir / "slv",
    )
    with pytest.raises(ValueError, match="requested language"):
        target.install_plugin("pol")
    assert not root.exists()


def test_existing_install_does_not_download_without_replace(
    service, monkeypatch
):
    """Refuse implicit replacement before accessing the network."""
    monkeypatch.setattr("blitzer.core.download_pack", reject_network)
    with pytest.raises(FileExistsError, match="--replace"):
        service.install_plugin("slv")


def test_package_command_emits_installable_archive(service, tmp_path):
    """Check packaging emits the expected data-only archive."""
    output = tmp_path / "archives"
    result = CliRunner().invoke(
        cli,
        [
            "dev",
            "package-plugin",
            "slv",
            "--no-config",
            "--plugins-dir",
            str(service.plugins_dir),
            "--output-dir",
            str(output),
        ],
    )
    assert result.exit_code == 0, result.output
    archive = output / "blitzer-slv-v1.zip"
    assert archive.is_file()
    assert (
        archive.with_suffix(".zip.sha256")
        .read_text()
        .startswith(hashlib.sha256(archive.read_bytes()).hexdigest())
    )
    with zipfile.ZipFile(archive) as pack:
        assert set(pack.namelist()) == {
            "slv/config.toml",
            "slv/lemmas.db",
            "slv/build-info.json",
        }


def test_http_errors_are_actionable():
    """Check rate limits and missing releases have clear messages."""
    assert "rate limit" in downloads._http_error_message(403, "url")
    assert "not found" in downloads._http_error_message(404, "url")


def test_release_json_is_bounded_and_validated(monkeypatch):
    """Check API responses are bounded and valid JSON."""
    monkeypatch.setattr(
        downloads,
        "_open_response",
        lambda url, accept: io.BytesIO(b"not json"),
    )
    with pytest.raises(ValueError, match="invalid JSON"):
        downloads._read_json("https://api.github.com/test")
    monkeypatch.setattr(downloads, "MAX_METADATA_BYTES", 2)
    monkeypatch.setattr(
        downloads,
        "_open_response",
        lambda url, accept: io.BytesIO(json.dumps([]).encode() + b" "),
    )
    with pytest.raises(ValueError, match="size limit"):
        downloads._read_json("https://api.github.com/test")


def test_existing_code_directory_is_local(service, tmp_path, monkeypatch):
    """Check a local directory takes precedence over a registry code."""
    monkeypatch.chdir(service.plugins_dir)
    monkeypatch.setattr("blitzer.core.download_pack", reject_network)
    target = BlitzerService(use_config=False, plugins_dir=tmp_path / "copy")
    assert target.install_plugin("slv") == target.plugins_dir / "slv"


def test_missing_explicit_path_never_downloads(tmp_path, monkeypatch):
    """Check missing explicit paths never consult the registry."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("blitzer.core.download_pack", reject_network)
    target = BlitzerService(use_config=False, plugins_dir=tmp_path / "packs")
    with pytest.raises(FileNotFoundError):
        target.install_plugin("./slv")
    with pytest.raises(FileNotFoundError):
        target.install_plugin(Path("slv"))


def test_https_is_required_for_requests_and_redirects():
    """Check transport validation rejects HTTP before contacting it."""
    with pytest.raises(ValueError, match="HTTPS"):
        downloads._open_response("http://example.com/pack", "application/zip")
    with pytest.raises(ValueError, match="HTTPS"):
        downloads._HttpsRedirects().redirect_request(
            None, None, 302, "Found", {}, "http://example.com/pack"
        )


def test_https_uses_verified_bundled_and_system_roots(monkeypatch):
    """Check GitHub requests verify certificates using trusted roots."""
    opener = Mock()
    monkeypatch.setattr(downloads, "build_opener", opener)
    downloads._open_response("https://api.github.com/test", "text/plain")
    handlers = opener.call_args.args
    context = handlers[1]._context
    assert context.verify_mode == ssl.CERT_REQUIRED
    assert context.check_hostname is True
    assert context.cert_store_stats()["x509_ca"] > 0
