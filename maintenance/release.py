"""Release the application and changed packs from this checkout.

Purpose
-------
Provide the one-command local half of publication. GitHub Actions owns
PyPI publication after this helper publishes the GitHub release.

In scope
--------
- Patch bumps, tests, build checks, commits, tags and pushes.
- Comparing pack contents with stable releases, including old ZIPs.
- Uploading changed packs and a cumulative content manifest.
- Keeping a local checkpoint to resume interrupted publication.

Out of scope
------------
- Runtime commands, converting dictionary sources or changing pack data.
- PyPI credentials, account setup and executing the remote workflow.
- Choosing release notes, deleting packs or rewriting existing releases.

Start here
----------
Read main, prepare_release and finish_release for the sequence.
Fingerprint helpers compare bytes rather than timestamps. This module is
repository maintenance code and is excluded from Python distributions.
"""

import hashlib
import json
import re
import shutil
import subprocess
import sys
import tomllib
import zipfile
from pathlib import Path

from blitzer.core import BlitzerService
from blitzer.downloads import PACK_FILES, REGISTRY, REPOSITORY, asset_name

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / "maintenance" / "work"
PENDING = WORK / "pending-release.json"
MANIFEST = "pack-manifest.json"


def run(*arguments, capture=False, check=True):
    """Run an argument list in the checkout without a shell."""
    result = subprocess.run(
        list(arguments),
        cwd=ROOT,
        text=True,
        capture_output=capture,
        check=check,
    )
    return result.stdout.strip() if capture and check else result


def write_json(path, value):
    """Atomically write a JSON checkpoint or pack manifest."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    temporary.replace(path)


def fingerprint_stream(stream):
    """Stream a SHA-256 digest without loading a dictionary."""
    return hashlib.file_digest(stream, "sha256").hexdigest()


def fingerprint_file(path):
    """Hash one file using a bounded amount of memory."""
    with path.open("rb") as stream:
        return fingerprint_stream(stream)


def fingerprint_pack(directory):
    """Hash pack files, ignoring caches and modification times."""
    return {
        name: fingerprint_file(directory / name)
        for name in sorted(PACK_FILES)
        if (directory / name).is_file()
    }


def fingerprint_archive(path, code):
    """Hash pack contents inside a previously published ZIP."""
    with zipfile.ZipFile(path) as archive:
        return archive_fingerprints(archive, code)


def archive_fingerprints(archive, code):
    """Read supported members without extracting a historical pack."""
    result = {}
    for name in sorted(PACK_FILES):
        member = f"{code}/{name}"
        if member not in archive.namelist():
            continue
        with archive.open(member) as stream:
            result[name] = fingerprint_stream(stream)
    return result


def ready_packs(root):
    """Find ready packs, excluding the deferred dev folder."""
    return {
        path.name: path
        for path in sorted(root.iterdir())
        if re.fullmatch("[a-z]{3}", path.name)
        and (path / "config.toml").is_file()
        and (path / "lemmas.db").is_file()
    }


def stable_assets(releases):
    """Select the newest asset of each name from stable releases."""
    result = {}
    for release in releases:
        if release["draft"] or release["prerelease"]:
            continue
        add_assets(result, release)
    return result


def add_assets(result, release):
    """Keep earlier selections while adding assets from one release."""
    for asset in release.get("assets", []):
        if asset.get("state") != "uploaded":
            continue
        result.setdefault(asset["name"], (release["tag_name"], asset))


def github_releases():
    """Read release metadata, stopping on authentication failures."""
    output = run(
        "gh",
        "api",
        "--paginate",
        "--slurp",
        f"repos/{REPOSITORY}/releases?per_page=100",
        capture=True,
    )
    return [release for page in json.loads(output) for release in page]


def download_asset(tag, name, directory):
    """Fetch a GitHub asset into an ignored cache directory."""
    directory.mkdir(parents=True, exist_ok=True)
    run(
        "gh",
        "release",
        "download",
        tag,
        "--repo",
        REPOSITORY,
        "--pattern",
        name,
        "--dir",
        str(directory),
        "--clobber",
    )
    return directory / name


def previous_packs(assets, packs):
    """Read published fingerprints or recover them from old ZIPs."""
    if MANIFEST in assets:
        tag, _ = assets[MANIFEST]
        path = download_asset(tag, MANIFEST, WORK / "previous-manifest")
        return json.loads(path.read_text())
    previous = {}
    for code in packs:
        name = asset_name(code)
        if name not in assets:
            continue
        tag, asset = assets[name]
        previous[code] = historical_fingerprint(tag, asset, code)
    return previous


def historical_fingerprint(tag, asset, code):
    """Verify an archive or fetch it before hashing contents."""
    digest = asset.get("digest", "")
    if not re.fullmatch("sha256:[0-9a-fA-F]{64}", digest):
        raise ValueError(f"Published {asset['name']} has no SHA-256 digest")
    expected = digest[7:].lower()
    path = ROOT / "release-assets" / asset["name"]
    if not path.is_file() or fingerprint_file(path) != expected:
        path = download_asset(tag, asset["name"], WORK / "previous-assets")
    if fingerprint_file(path) != expected:
        raise ValueError(f"Checksum mismatch for {path.name}")
    print(f"Comparing published {code}... ", flush=True)
    return fingerprint_archive(path, code)


def project_version():
    """Read the application version from project metadata."""
    config = tomllib.loads((ROOT / "pyproject.toml").read_text())
    return config["project"]["version"]


def next_patch(version):
    """Increment only the final component of a three-part version."""
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        raise ValueError("Release versions must have the form 0.2.3")
    major, minor, patch = version.split(".")
    return f"{major}.{minor}.{int(patch) + 1}"


def source_changed(version):
    """Compare source with its tag, including uncommitted files."""
    if run("git", "status", "--porcelain", capture=True):
        return True
    tag = run(
        "git",
        "rev-parse",
        "--verify",
        f"refs/tags/v{version}",
        capture=True,
        check=False,
    )
    if tag.returncode:
        return True
    result = run("git", "diff", "--quiet", f"v{version}", "HEAD", check=False)
    if result.returncode not in (0, 1):
        result.check_returncode()
    return result.returncode == 1


def preflight():
    """Check branch, tools, identity and remote before preparation."""
    if run("git", "branch", "--show-current", capture=True) != "master":
        raise ValueError("Run releases from master")
    if not shutil.which("gh"):
        raise ValueError("Install GitHub CLI first: brew install gh")
    run("gh", "auth", "status")
    run("git", "fetch", "origin", "master", "--tags")
    run("git", "merge-base", "--is-ancestor", "origin/master", "HEAD")
    if run("git", "diff", "--name-only", "--diff-filter=U", capture=True):
        raise ValueError("Resolve merge conflicts before releasing")
    for key in ("user.name", "user.email"):
        run("git", "config", "--get", key, capture=True)
    tool = Path(sys.executable).parent / "bump-my-version"
    if not tool.is_file():
        raise ValueError(
            "Install tools: .venv/bin/python -m pip install -e '.[dev]'"
        )


def prepare_release():
    """Test and package changes, then save a resumable checkpoint."""
    packs = ready_packs(ROOT / "language-packs")
    unregistered = packs.keys() - REGISTRY.keys()
    if unregistered:
        raise ValueError(f"Add these codes to the registry: {unregistered}")
    previous = previous_packs(stable_assets(github_releases()), packs)
    print(
        "Hashing local packs; large dictionaries may take a while...",
        flush=True,
    )
    current = {code: fingerprint_pack(path) for code, path in packs.items()}
    changed = [code for code in packs if current[code] != previous.get(code)]
    old_version = project_version()
    if not changed and not source_changed(old_version):
        print("No source or language-pack changes; nothing to release.")
        return None
    run(sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider")
    version = next_patch(old_version)
    output = WORK / f"release-v{version}"
    service = BlitzerService(
        use_config=False, plugins_dir=ROOT / "language-packs"
    )
    archives = package_changes(service, changed, output)
    manifest = output / MANIFEST
    write_json(manifest, previous | current)
    state = {
        "version": version,
        "previous_version": old_version,
        "head": None,
        "assets": [str(path) for path in archives],
        "manifest": str(manifest),
        "changed": changed,
    }
    write_json(PENDING, state)
    return state


def package_changes(service, codes, output):
    """Validate and package dictionaries with changed contents."""
    archives = []
    for code in codes:
        print(f"Validating and packaging {code}...", flush=True)
        archives.append(service.package_plugin(code, output))
    return archives


def commit_release(state):
    """Bump once, check distributions and commit non-ignored changes."""
    if project_version() == state["previous_version"]:
        run(
            str(Path(sys.executable).parent / "bump-my-version"),
            "bump",
            "patch",
        )
    if project_version() != state["version"]:
        raise ValueError("Project version no longer matches pending release")
    output = WORK / f"app-v{state['version']}"
    if output.exists():
        shutil.rmtree(output)
    run(sys.executable, "-m", "build", "--outdir", str(output))
    distributions = [
        str(path)
        for path in sorted(output.iterdir())
        if path.is_file() and path.name.endswith((".whl", ".tar.gz"))
    ]
    if not distributions:
        raise ValueError(f"Build produced no distributions in {output}")
    run(
        sys.executable,
        "-m",
        "twine",
        "check",
        *distributions,
    )
    run("git", "add", "-A")
    staged = run("git", "diff", "--cached", "--quiet", check=False)
    if staged.returncode not in (0, 1):
        staged.check_returncode()
    if staged.returncode == 1:
        run("git", "commit", "-m", f"Release {state['version']}")
    state["head"] = run("git", "rev-parse", "HEAD", capture=True)
    write_json(PENDING, state)


def push_release(state, tag):
    """Create or verify the tag and push it atomically with master."""
    if run("git", "rev-parse", "HEAD", capture=True) != state["head"]:
        raise ValueError("HEAD changed; restore the pending release commit")
    existing = run(
        "git",
        "rev-parse",
        "--verify",
        f"{tag}^{{commit}}",
        capture=True,
        check=False,
    )
    if existing.returncode and existing.returncode != 128:
        existing.check_returncode()
    if existing.returncode:
        run("git", "tag", "-a", tag, "-m", f"Release {state['version']}")
    if not existing.returncode and existing.stdout.strip() != state["head"]:
        raise ValueError(f"{tag} already names a different commit")
    run("git", "push", "--atomic", "origin", "master", f"refs/tags/{tag}")


def publish_github(state, tag):
    """Stage assets in a draft and publish after all uploads succeed."""
    view = run(
        "gh",
        "release",
        "view",
        tag,
        "--repo",
        REPOSITORY,
        "--json",
        "isDraft",
        capture=True,
        check=False,
    )
    if view.returncode:
        notes = "Application release. Updated packs: " + (
            ", ".join(state["changed"]) or "none"
        )
        run(
            "gh",
            "release",
            "create",
            tag,
            "--repo",
            REPOSITORY,
            "--draft",
            "--verify-tag",
            "--title",
            f'bltzr {state["version"]}',
            "--notes",
            notes,
        )
    if not view.returncode and not json.loads(view.stdout)["isDraft"]:
        return
    run(
        "gh",
        "release",
        "upload",
        tag,
        "--repo",
        REPOSITORY,
        *state["assets"],
        state["manifest"],
        "--clobber",
    )
    run(
        "gh",
        "release",
        "edit",
        tag,
        "--repo",
        REPOSITORY,
        "--draft=false",
        "--latest",
    )


def finish_release(state):
    """Resume versioning, Git and asset publication in order."""
    if state["head"] is None:
        commit_release(state)
    tag = f"v{state['version']}"
    push_release(state, tag)
    publish_github(state, tag)
    PENDING.unlink()
    print(f"{tag} published on GitHub. PyPI publication runs in Actions.")
    print("Follow it with: gh run list --workflow publish.yml")


def main():
    """Release this checkout, keeping checkpoints on failure."""
    try:
        preflight()
        state = (
            json.loads(PENDING.read_text())
            if PENDING.exists()
            else (prepare_release())
        )
        if state is not None:
            finish_release(state)
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        print(f"Release stopped: {error}", file=sys.stderr)
        if PENDING.exists():
            print(
                "Run make release again to resume this version.",
                file=sys.stderr,
            )
        raise SystemExit(1) from error


if __name__ == "__main__":
    main()
