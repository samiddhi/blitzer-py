"""Expand packs without losing existing vocabulary or sources.

Purpose
-------
Prepare the union of packs sharing a language and normalization.
Keep each distinct form/lemma pair once and preserve ambiguous matches.

In scope
--------
- Pure version editing and the SQL union of compatible dictionaries.
- Copying a base pack into caller-owned staging, never changing inputs.
- Addition counts, source checksums and combined attribution.
- Keeping the base pack's frequency data and other configuration.

Out of scope
------------
- Locks, validation and atomic replacement: core.py owns those steps.
- UniMorph conversion and batch output: maintenance/unimorph.py.
- Terminal commands, downloads and publication of release archives.
- Replacing existing frequencies with estimates from inflection counts.

Start here
----------
merge_packs prepares staging. merge_database adds missing lemmas and
form/lemma pairs. BlitzerService.expand_plugin validates and commits it.
"""

import hashlib
import json
import re
import shutil
import sqlite3
from contextlib import closing
from pathlib import Path

from blitzer.config import load_plugin_config
from blitzer.downloads import PACK_FILES


def change_version(text: str, version: str) -> str:
    """Change metadata.version and preserve other TOML settings."""
    if not version.strip():
        raise ValueError("Pack version cannot be blank")
    section = re.search(r"(?ms)^\[metadata\]\s*\n(.*?)(?=^\[|\Z)", text)
    if section is None:
        raise ValueError("Missing metadata section")
    block = section[1]
    fields = list(re.finditer(r"(?m)^version\s*=.*$", block))
    if len(fields) != 1:
        raise ValueError("Expected one metadata.version setting")
    field = fields[0]
    value = "version = " + json.dumps(version)
    field_start, field_end = field.span()
    metadata = block[:field_start] + value + block[field_end:]
    start, end = section.span(1)
    return text[:start] + metadata + text[end:]


def pack_hash(path: Path) -> str:
    """Hash a source database without changing it."""
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def copy_pack(source: Path, stage: Path) -> None:
    """Copy supported files into a new private staging folder."""
    if source.is_symlink() or any(p.is_symlink() for p in source.iterdir()):
        raise ValueError("Merge self-contained packs without symlinks")
    stage.mkdir()
    for name in PACK_FILES:
        path = source / name
        if path.is_file():
            shutil.copy2(path, stage / name)


def merge_database(database: Path, additional: Path) -> dict:
    """Union pairs in staging, keeping additional data read-only."""
    with closing(sqlite3.connect(database, uri=True)) as conn:
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute(
            "ATTACH DATABASE ? AS extra",
            (additional.resolve().as_uri() + "?mode=ro",),
        )
        with conn:
            return insert_missing_pairs(conn)


def insert_missing_pairs(conn) -> dict:
    """Add missing spellings and pairs, returning addition counts."""
    cursor = conn.execute(
        "INSERT OR IGNORE INTO lemmas(lemma) SELECT lemma FROM extra.lemmas"
    )
    added_lemmas = cursor.rowcount
    cursor = conn.execute(
        "INSERT OR IGNORE INTO forms(form_representation,lemma_id) "
        "SELECT f.form_representation,b.id FROM extra.forms f "
        "JOIN extra.lemmas e ON e.id=f.lemma_id "
        "JOIN main.lemmas b ON b.lemma=e.lemma"
    )
    return {
        "lemmas_added": added_lemmas,
        "pairs_added": cursor.rowcount,
        "lemmas": conn.execute("SELECT COUNT(*) FROM lemmas").fetchone()[0],
        "forms": conn.execute("SELECT COUNT(*) FROM forms").fetchone()[0],
    }


def append_attribution(stage: Path, additional: Path) -> None:
    """Keep both upstream READMEs and all supplied license notices."""
    for name in ("README.md", "LICENSE"):
        source = additional / name
        if not source.is_file():
            continue
        target = stage / name
        original = (
            target.read_text(encoding="utf-8") if target.exists() else ""
        )
        target.write_text(
            original
            + "\n\n---\nAdditional dictionary source:\n\n"
            + source.read_text(encoding="utf-8"),
            encoding="utf-8",
        )


def read_build_info(directory: Path) -> dict:
    """Read provenance without inventing missing source details."""
    path = directory / "build-info.json"
    return (
        json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    )


def merge_packs(
    base: Path, additional: Path, stage: Path, version: str
) -> dict:
    """Prepare a compatible union and record both source histories."""
    primary, extra = load_plugin_config(base), load_plugin_config(additional)
    if (
        primary["metadata"]["language_code"]
        != extra["metadata"]["language_code"]
    ):
        raise ValueError("Merge packs for the same language")
    if primary["normalization"] != extra["normalization"]:
        raise ValueError("Merge packs with identical normalization settings")
    copy_pack(base, stage)
    stats = merge_database(stage / "lemmas.db", additional / "lemmas.db")
    metadata = stage / "config.toml"
    metadata.write_text(
        change_version(metadata.read_text(encoding="utf-8"), version),
        encoding="utf-8",
    )
    append_attribution(stage, additional)
    info = stats | {
        "format_version": 1,
        "base_sha256": pack_hash(base / "lemmas.db"),
        "additional_sha256": pack_hash(additional / "lemmas.db"),
        "base_build": read_build_info(base),
        "additional_build": read_build_info(additional),
    }
    (stage / "build-info.json").write_text(
        json.dumps(info, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return stats
