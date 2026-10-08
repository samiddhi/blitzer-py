"""Refresh repository packs from reviewed language capabilities, offline.

Preview is the default. Applying uses a fresh work directory, retains the
previous packs as backups, and never commits, uploads or publishes anything.
Rebuilds read the upstream checkout without modifying it.
"""

import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

import click

from blitzer.config import load_plugin_config
from blitzer.core import BlitzerService, _lock, _require_valid
from blitzer.languages import CATALOG
from maintenance.unimorph import build_all, progress, write_json

ROOT = Path(__file__).resolve().parents[1]


def pack_directories(root):
    """Find configured packs at the ready and dev levels only."""
    return sorted([*root.glob("*/config.toml"), *root.glob("dev/*/config.toml")])


def rebuild_codes(root, source):
    """Rebuild nondefault profiles from complete source, preserving rich packs."""
    return sorted(
        code for code, entry in CATALOG.items()
        if entry["profile"] != "default" and code != "pli"
        and (source / code).is_dir()
        and ((root / code).is_dir() or (root / "dev" / code).is_dir())
    )


def refresh_metadata(directory):
    """Synchronize names, capability declarations and current provenance."""
    path = directory / "config.toml"
    config = load_plugin_config(directory)
    code = config["metadata"]["language_code"]
    entry = CATALOG.get(code)
    if entry is None:
        return
    old = config["metadata"]["language_name"]
    text = path.read_text(encoding="utf-8")
    text = text.replace("language_name = " + json.dumps(old, ensure_ascii=False),
                        "language_name = " + json.dumps(entry["name"], ensure_ascii=False))
    if entry["profile"] != "default" and config["format_version"] == 1:
        text = text.replace("format_version = 1", "format_version = 2", 1)
        text += '\n[tokenization]\nprofile = ' + json.dumps(entry["profile"]) + '\n'
    path.write_text(text, encoding="utf-8")
    info_path = directory / "build-info.json"
    if info_path.exists():
        info = json.loads(info_path.read_text(encoding="utf-8"))
        info["format_version"] = load_plugin_config(directory)["format_version"]
        info["config_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
        info["language_capability"] = entry
        if "unimorph" in info:
            info["unimorph"]["name"] = entry["name"]
        write_json(info_path, info)
    readme = directory / "README.md"
    original = readme.read_text(encoding="utf-8") if readme.exists() else ""
    if old != entry["name"]:
        original = original.replace(f"# {old} — UniMorph pack", f"# {entry['name']} — UniMorph pack", 1)
    marker = "\n## Blitzer input scope\n"
    original = original.split(marker)[0]
    readme.write_text(original.rstrip() + marker + "\n" + entry["scope"] + "\n\n"
                      + f"Tokenization profile: `{entry['profile']}`. "
                      + "Nondefault profiles require the current application and pack format 2.\n",
                      encoding="utf-8")


def publish_local_pack(staged, destination, backup):
    """Replace a validated local pack while preserving the previous version."""
    _require_valid(staged, destination.name)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        backup.parent.mkdir(parents=True, exist_ok=True)
        destination.rename(backup)
    try:
        staged.rename(destination)
    except OSError:
        if backup.exists():
            backup.rename(destination)
        raise


def refresh(root, source, work):
    """Rebuild profiles and apply validated replacements/promotion locally."""
    work.mkdir(parents=True, exist_ok=False)
    codes = rebuild_codes(root, source)
    rebuilt = (build_all(source, work / "rebuilt", version="0.2.0",
                         languages=tuple(codes), progress=progress) if codes else [])
    if any(record["status"] == "error" for record in rebuilt):
        raise ValueError(f"Rebuild errors; inspect {work / 'rebuilt/report.json'}")
    replacement = {record["code"]: record for record in rebuilt if "pack" in record}
    result = {"work": str(work), "promoted": [], "rebuilt": [],
              "metadata_updated": [], "retained_dev": [], "checks": {}}
    all_codes = sorted({p.parent.name for p in pack_directories(root)} | set(replacement))
    for code in all_codes:
        apply_language(code, root, work, replacement, result)
        write_json(work / "status.json", result)
    for record in rebuilt:
        if record["status"] != "ready" and "pack" not in record:
            notice = root / "dev" / record["code"] / "DEFERRED.md"
            notice.parent.mkdir(parents=True, exist_ok=True)
            notice.write_text(f"# {record['name']} ({record['code']}) — {record['status']}\n\n"
                              + '\n'.join('- ' + reason for reason in record["reasons"]) + '\n')
    synchronize_registries(root)
    update_readme(root)
    return result


def apply_language(code, root, work, replacement, result):
    """Choose a reviewed destination and validate before any replacement."""
    current = root / code
    development = root / "dev" / code
    ready = current.is_dir()
    entry = CATALOG.get(code, {"status": "review"})
    promote = not ready and entry["status"] == "ready"
    if not ready and code not in replacement and not (development / "lemmas.db").exists():
        return
    destination = current if ready or promote else development
    if code in replacement:
        record = replacement[code]
        staged = work / "rebuilt" / record["pack"]
        # A newly rebuilt deferred language stays in dev, even if its
        # catalog is nominally ready (e.g. a malformed/oversized source).
        if not ready and record["status"] != "ready":
            destination, promote = development, False
        if ready and record["status"] != "ready":
            raise ValueError(f"Refusing to replace ready {code} with deferred data")
        result["rebuilt"].append(code)
    else:
        staged = work / "staged" / code
        staged.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(current if ready else development, staged)
    refresh_metadata(staged)
    backup = work / "backups" / ("ready" if ready else "dev") / code
    publish_local_pack(staged, destination, backup)
    if promote and development.exists():
        dev_backup = work / "backups/dev" / code
        dev_backup.parent.mkdir(parents=True, exist_ok=True)
        development.rename(dev_backup)
    result["promoted" if promote else "metadata_updated"].append(code)
    if destination.parent == root / "dev":
        result["retained_dev"].append(code)
    result["checks"][code] = "passed staged pack validation"


def synchronize_registries(root):
    """Keep only locally ready packs in the published download registry."""
    catalog = {
        config.parent.name: {"name": CATALOG[config.parent.name]["name"]}
        for config in sorted(root.glob("*/config.toml"))
        if config.parent.name in CATALOG and (config.parent / "lemmas.db").exists()
    }
    write_json(ROOT / "blitzer/language-registry.json", catalog)
    write_json(ROOT / "maintenance/reports/language-registry.json", catalog)


def name_sort_key(item):
    """Sort English display names alphabetically, ignoring diacritics."""
    import unicodedata
    name, code = item
    plain = ''.join(c for c in unicodedata.normalize("NFKD", name)
                    if not unicodedata.combining(c))
    return plain.casefold(), code


def update_readme(root):
    """Regenerate the complete supported list by name rather than pack code."""
    languages = [("Basic", "base")]
    languages.extend(
        (CATALOG[path.parent.name]["name"], path.parent.name)
        for path in root.glob("*/config.toml")
        if path.parent.name in CATALOG and (path.parent / "lemmas.db").exists()
    )
    listing = '\n'.join(f"- {name} ({code})" for name, code in sorted(languages, key=name_sort_key))
    path = ROOT / "README.org"
    text = path.read_text(encoding="utf-8")
    start = text.index("** Supported Languages")
    end = text.index("** Install", start)
    intro = (
        "** Supported Languages\n\n"
        "The ready packs below support the orthographies documented in each pack.\n"
        "Word boundaries use Unicode letters plus reviewed language-specific rules;\n"
        "support is not limited to Latin script. Multiword paradigm entries are\n"
        "omitted, and dictionary coverage varies. Development packs are excluded\n"
        "from this list and from releases. The list describes this checkout's\n"
        "next release; newly promoted packs become downloadable after publication.\n\n"
        "If your target language is not on this list, see\n"
        "[[file:language-packs/UNSUPPORTED-LANGUAGES.md][languages without a release-ready pack]]\n"
        "for an explanation of what is needed to implement it. If your language is\n"
        "not listed in that document either, open a pull request, ideally with a\n"
        "source of inflectional data for that language.\n\n"
    )
    path.write_text(text[:start] + intro + listing + "\n\n" + text[end:], encoding="utf-8")


@click.command()
@click.option("--packs", type=click.Path(path_type=Path), default=ROOT / "language-packs")
@click.option("--source", type=click.Path(path_type=Path), default=ROOT / "maintenance/unimorph-data")
@click.option("--work", type=click.Path(path_type=Path), default=None)
@click.option("--apply", is_flag=True, help="Rebuild and apply locally; preserve backups.")
def main(packs, source, work, apply):
    """Preview or apply language-name, boundary and readiness changes."""
    codes = rebuild_codes(packs, source)
    development = list((packs / "dev").iterdir()) if (packs / "dev").is_dir() else []
    promotions = sorted(p.name for p in development
                        if p.name in CATALOG and CATALOG[p.name]["status"] == "ready"
                        and ((p / "lemmas.db").exists() or p.name in codes))
    click.echo("Rebuild profiles: " + ", ".join(codes))
    click.echo("Promotion candidates: " + ", ".join(promotions))
    if not apply:
        click.echo("Preview only. Use --apply to rebuild and validate changes locally.")
        return
    work = work or ROOT / "maintenance/work" / datetime.now(timezone.utc).strftime("language-refresh-%Y%m%d-%H%M%S")
    try:
        with _lock(packs / ".mutation.lock"):
            result = refresh(packs, source, work)
    except (OSError, ValueError) as error:
        raise click.ClickException(str(error)) from error
    write_json(ROOT / "maintenance/reports/language-refresh.json", result)
    click.echo(str(work / "status.json"))


if __name__ == "__main__":
    main()
