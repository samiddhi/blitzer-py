"""Find released language packs and download their validated archives.

Purpose
-------
Turn a registered language code into a downloaded, unpacked data folder
that core.py can validate and install through its normal staging flow.

In scope
--------
- The language registry, language catalog and fixed asset names.
- Finding the newest stable release that contains a requested pack.
- HTTPS requests, bounded streaming downloads and SHA-256 verification.
- Validating ZIP members and extracting only the supported pack files.

Out of scope
------------
- SQL checks, vocabulary processing and application configuration.
- Publishing releases, executing plugins or installing Python packages.
- Replacing installed packs, terminal output or interactive prompts.

Start here
----------
Read REGISTRY for supported languages and download_pack for the
sequence.
select_release_asset and validate_archive_members are pure validation
helpers. core.py owns final pack validation, installation and
replacement.
"""

import hashlib
import json
import re
import shutil
import stat
import zipfile
from contextlib import closing
from dataclasses import dataclass
from itertools import count
from pathlib import Path, PurePosixPath
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from blitzer.config import validate_code

REPOSITORY = "samiddhi/blitzer-py"


def load_language_registry(path: Path) -> dict:
    """Read the packaged catalog without downloading language data."""
    catalog = json.loads(path.read_text(encoding="utf-8"))
    entries = {}
    for code, metadata in catalog.items():
        validate_code(code, allow_base=False)
        if not isinstance(metadata.get("name"), str):
            raise ValueError(f"Invalid language registry name for {code}")
        entries[code] = {"name": metadata["name"], "repository": REPOSITORY}
    return entries


REGISTRY = {
    **load_language_registry(
        Path(__file__).with_name("language-registry.json")
    ),
    "slv": {"name": "Slovenian", "repository": REPOSITORY},
    "pol": {"name": "Polish", "repository": REPOSITORY},
    "pli": {"name": "Pali", "repository": REPOSITORY},
}
PACK_FILES = {
    "config.toml",
    "lemmas.db",
    "build-info.json",
    "README.md",
    "LICENSE",
}
REQUIRED_FILES = {"config.toml", "lemmas.db"}
MAX_DOWNLOAD_BYTES = 512 * 1024 * 1024
MAX_UNPACKED_BYTES = 2 * 1024 * 1024 * 1024
MAX_METADATA_BYTES = 8 * 1024 * 1024
TIMEOUT = 30


@dataclass(frozen=True)
class ReleaseAsset:
    """Describe one immutable release asset and its expected content."""

    url: str
    sha256: str
    size: int
    tag: str


class _HttpsRedirects(HTTPRedirectHandler):
    """Require HTTPS for every download redirect."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        """Require HTTPS before following a download redirect."""
        if urlsplit(newurl).scheme != "https":
            raise ValueError("Refusing a download redirect without HTTPS")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def asset_name(code: str) -> str:
    """Return a fixed filename for the version-one pack format."""
    validate_code(code, allow_base=False)
    return f"blitzer-{code}-v1.zip"


def registry_entry(code: str) -> dict:
    """Return the registry entry for a supported language."""
    validate_code(code, allow_base=False)
    if code not in REGISTRY:
        available = ", ".join(sorted(REGISTRY))
        raise ValueError(
            f"No registered download for {code}; available: {available}. "
            "Other packs can be installed from a local directory."
        )
    return dict(REGISTRY[code])


def select_release_asset(releases, code, repository) -> ReleaseAsset | None:
    """Select the first stable release containing the requested pack.

    GitHub supplies releases in newest-first order. Drafts and
    prereleases are ignored. A matching but invalid asset is an error,
    not a reason to silently install an older version. Inputs remain
    unchanged.
    """
    if not isinstance(releases, list):
        raise ValueError("GitHub returned invalid release metadata")
    for release in releases:
        asset = _stable_asset(release, asset_name(code))
        if asset is not None:
            return _release_descriptor(asset, release, repository)
    return None


def _stable_asset(release, filename):
    """Find an uploaded asset in one stable release."""
    if not isinstance(release, dict):
        raise ValueError("GitHub returned an invalid release")
    if release.get("draft") or release.get("prerelease"):
        return None
    assets = release.get("assets", [])
    if not isinstance(assets, list) or any(
        not isinstance(item, dict) for item in assets
    ):
        raise ValueError("GitHub returned an invalid asset list")
    return next(
        (
            item
            for item in assets
            if item.get("name") == filename and item.get("state") == "uploaded"
        ),
        None,
    )


def _release_descriptor(asset, release, repository) -> ReleaseAsset:
    """Validate a release URL, byte count and GitHub-provided digest."""
    url = asset.get("browser_download_url", "")
    if not isinstance(url, str):
        raise ValueError("GitHub returned an invalid pack download URL")
    parsed = urlsplit(url)
    prefix = f"/{repository}/releases/download/"
    if (
        parsed.scheme != "https"
        or parsed.netloc != "github.com"
        or not parsed.path.startswith(prefix)
    ):
        raise ValueError("GitHub returned an unexpected pack download URL")
    digest = asset.get("digest", "")
    if not isinstance(digest, str) or not re.fullmatch(
        r"sha256:[0-9a-fA-F]{64}", digest
    ):
        raise ValueError(
            "Pack asset has no SHA-256 digest; upload a new release asset"
        )
    size = asset.get("size")
    if type(size) is not int or not 0 < size <= MAX_DOWNLOAD_BYTES:
        raise ValueError(
            "Pack asset has an invalid or excessive download size"
        )
    tag = release.get("tag_name")
    if not isinstance(tag, str) or not tag:
        raise ValueError("GitHub returned an invalid release tag")
    return ReleaseAsset(url, digest[7:].lower(), size, tag)


def resolve_release(code: str) -> ReleaseAsset:
    """Find a pack across release pages, including independent updates.

    Unrelated language releases do not hide the latest pack for this
    code. Public repositories need no GitHub account or token. Errors
    from the API are reported without falling back to an unverified
    asset.
    """
    repository = registry_entry(code)["repository"]
    for page in count(1):
        url = (
            f"https://api.github.com/repos/{repository}/releases"
            f"?per_page=100&page={page}"
        )
        releases = _read_json(url)
        asset = select_release_asset(releases, code, repository)
        if asset is not None:
            return asset
        if len(releases) < 100:
            break
    raise ValueError(
        f"No stable release contains {asset_name(code)} in {repository}. "
        "The maintainer must publish a version-one pack archive first."
    )


def _open_response(url, accept):
    """Open an HTTPS response with headers and a timeout."""
    if urlsplit(url).scheme != "https":
        raise ValueError("Downloads require HTTPS")
    request = Request(url, headers={"User-Agent": "blitzer", "Accept": accept})
    try:
        return build_opener(_HttpsRedirects()).open(request, timeout=TIMEOUT)
    except HTTPError as error:
        error.close()
        raise ValueError(_http_error_message(error.code, url)) from error
    except URLError as error:
        raise OSError(f"Cannot contact GitHub: {error.reason}") from error


def _http_error_message(status, url) -> str:
    """Explain common HTTP failures without network access."""
    if status in (403, 429):
        return (
            "GitHub denied the request or its rate limit was reached; "
            "try again later"
        )
    if status == 404:
        return f"GitHub release or asset not found: {url}"
    return f"GitHub request failed with HTTP {status}: {url}"


def _read_json(url):
    """Read bounded, valid JSON release metadata."""
    with closing(
        _open_response(url, "application/vnd.github+json")
    ) as response:
        content = response.read(MAX_METADATA_BYTES + 1)
    if len(content) > MAX_METADATA_BYTES:
        raise ValueError("GitHub release metadata exceeds the size limit")
    try:
        return json.loads(content)
    except (ValueError, UnicodeError) as error:
        raise ValueError(
            "GitHub returned invalid JSON release metadata"
        ) from error


def _download_archive(asset: ReleaseAsset, path: Path) -> None:
    """Download an archive and verify its size and digest."""
    digest = hashlib.sha256()
    with (
        closing(
            _open_response(asset.url, "application/octet-stream")
        ) as response,
        path.open("wb") as stream,
    ):
        received = _copy_download(response, stream, digest, asset.size)
    if received != asset.size or digest.hexdigest() != asset.sha256:
        raise ValueError(
            "Pack download failed its size or SHA-256 verification"
        )


def _copy_download(response, stream, digest, expected_size) -> int:
    """Copy bounded chunks and update the download digest."""
    received = 0
    for chunk in iter(lambda: response.read(1024 * 1024), b""):
        received += len(chunk)
        if received > expected_size:
            raise ValueError("Pack download exceeded its advertised size")
        stream.write(chunk)
        digest.update(chunk)
    return received


def validate_archive_members(
    members, code
) -> list[tuple[zipfile.ZipInfo, str]]:
    """Return a safe extraction plan without writing files.

    Only a single language directory and known pack files are accepted.
    Reject duplicates, links, special files, encrypted entries,
    traversal and excessive expanded data before any extraction begins.
    """
    validate_code(code, allow_base=False)
    if len(members) > len(PACK_FILES) + 1:
        raise ValueError("Pack archive contains too many entries")
    plan = []
    seen = set()
    for member in members:
        filename = _member_filename(member, code)
        if member.filename in seen:
            raise ValueError("Pack archive contains duplicate paths")
        seen.add(member.filename)
        if filename is not None:
            plan.append((member, filename))
    if not REQUIRED_FILES <= {name for _, name in plan}:
        raise ValueError("Pack archive needs config.toml and lemmas.db")
    if sum(member.file_size for member, _ in plan) > MAX_UNPACKED_BYTES:
        raise ValueError("Pack archive exceeds the expanded size limit")
    return plan


def _member_filename(member, code) -> str | None:
    """Validate one ZIP path and file type."""
    mode = member.external_attr >> 16
    kind = stat.S_IFMT(mode)
    if member.flag_bits & 1 or kind not in (0, stat.S_IFREG, stat.S_IFDIR):
        raise ValueError("Pack archive contains encrypted or special entries")
    if member.is_dir() and member.filename == f"{code}/":
        return None
    parts = PurePosixPath(member.filename).parts
    if len(parts) != 2 or parts[0] != code or parts[1] not in PACK_FILES:
        raise ValueError(f"Unexpected pack archive path: {member.filename}")
    if (
        member.filename != f"{code}/{parts[1]}"
        or member.is_dir()
        or kind == stat.S_IFDIR
    ):
        raise ValueError(f"Invalid pack archive path: {member.filename}")
    return parts[1]


def _extract_member(archive, member, destination) -> None:
    """Copy one validated ZIP member with local permissions."""
    with archive.open(member) as source, destination.open("xb") as stream:
        shutil.copyfileobj(source, stream, length=1024 * 1024)


def extract_pack(path: Path, directory: Path, code: str) -> Path:
    """Extract supported files using a validated archive plan."""
    try:
        with zipfile.ZipFile(path) as archive:
            return _extract_archive(archive, directory, code)
    except (zipfile.BadZipFile, NotImplementedError, RuntimeError) as error:
        raise ValueError(f"Invalid pack ZIP archive: {error}") from error


def _extract_archive(archive, directory, code) -> Path:
    """Extract an open ZIP only after all members pass validation."""
    plan = validate_archive_members(archive.infolist(), code)
    pack = directory / code
    pack.mkdir()
    for member, filename in plan:
        _extract_member(archive, member, pack / filename)
    return pack


def download_pack(code: str, directory: Path) -> Path:
    """Resolve and unpack a verified pack into staging.

    The caller owns temporary-directory cleanup. Returned files are not
    installed yet; core.py must validate their metadata, schema and
    data.
    """
    asset = resolve_release(code)
    archive = directory / asset_name(code)
    _download_archive(asset, archive)
    return extract_pack(archive, directory, code)
