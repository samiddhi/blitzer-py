"""Convert a local UniMorph checkout into classified language packs.

Purpose
-------
Give maintainers a repeatable batch builder without altering upstream
data or existing packs. Inspect every language, then separate usable
Latin-script packs from data needing future tokenization work.

In scope
--------
- Pure source-file selection, row parsing and script classification.
- Streaming plain, CSV and XZ tables into the existing pack builder.
- Source checksums, attribution, per-language reports and progress.
- Separate ready/deferred packs and release archives; registry export.
- A standalone repository command with progress and failure reporting.

Out of scope
------------
- Downloading UniMorph, publishing releases or changing upstream files.
- New tokenizers, transliteration or retaining morphological features.
- Inferring permission to redistribute a dictionary from its contents.
- Replacing existing output, installed packs or user vocabulary lists.

Start here
----------
build_all coordinates the batch. convert_language handles one folder;
parse_row and script_names explain the data decisions. main runs this
standalone checkout tool; core.py builds and validates the databases.
"""

import csv
import hashlib
import json
import lzma
import re
import sqlite3
import tempfile
import unicodedata
from pathlib import Path

import click

from blitzer.config import validate_code
from blitzer.core import BlitzerService
from blitzer.downloads import MAX_DOWNLOAD_BYTES, MAX_UNPACKED_BYTES
from blitzer.processing import _word, normalize

SEGMENTATION_CODES = {
    "bod",
    "cmn",
    "dzo",
    "jpn",
    "khm",
    "lao",
    "mya",
    "tha",
    "wuu",
    "yue",
    "zho",
}
NORMALIZATION = {"lowercase": True, "substitutions": []}


def source_files(directory: Path) -> list[Path]:
    """Select inflection tables, excluding redundant compressed copies.

    Prefer an explicit .um4 table over the older canonical table.
    Include dialect tables and recognized supplemental inflections.
    Ignore features, glosses, derivations and segmentations.
    """
    code = directory.name
    pattern = rf"{code}(?:[-_][^.]+|\.um4|\.4|\.noun\.tsv|\.sm|\.csv)?"
    selected = []
    for path in sorted(directory.iterdir()):
        name = path.name.removesuffix(".xz")
        if not path.is_file() or not re.fullmatch(pattern, name):
            continue
        if path.suffix == ".xz" and (directory / name).is_file():
            continue
        if name == code and (directory / f"{code}.um4").is_file():
            continue
        selected.append(path)
    special = directory / "ckb-context-complete.tsv"
    if code == "ckb" and special.is_file():
        selected.append(special)
    return selected


def parse_row(row: list[str]) -> tuple[str, str] | None:
    """Return lemma and form from an inflection row, or ignore comments.

    Extra feature columns are allowed. An empty form with a lemma and
    features is an unavailable paradigm slot, not a spelling to import.
    Blank lemmas and missing feature columns are errors; empty feature
    values do not affect form/lemma lookup.
    """
    if not row or not any(row) or row[0].lstrip().startswith("#"):
        return None
    if len(row) < 3 or not row[0].strip():
        raise ValueError("Expected lemma, form and a feature column")
    if not row[1].strip():
        return None
    return row[0].strip(), row[1].strip()


def script_names(text: str) -> set[str]:
    """Return non-Latin letter families observed in original spellings.

    Combining marks and modifier letters are allowed with Latin letters.
    Conservative mixed-script detection also catches isolated non-Latin
    letters; it never silently transliterates a dataset.
    """
    letters = {
        unicodedata.name(char, "UNNAMED").split()[0]
        for char in text
        if unicodedata.category(char).startswith("L")
        and unicodedata.category(char) != "Lm"
    }
    return letters - {"LATIN"}


def deferred_reasons(
    code: str, scripts: set[str], foreign_ratio: float = 1.0
) -> list[str]:
    """Explain why a dataset must stay out of the next release.

    Defer when at least one percent of source pairs contain non-Latin
    letters. Below that threshold, omit those pairs from a Latin pack.
    This heuristic needs human review for mixed orthographies.
    """
    reasons = []
    if scripts and foreign_ratio >= 0.01:
        reasons.append("Non-Latin letters: " + ", ".join(sorted(scripts)))
    if code in SEGMENTATION_CODES:
        reasons.append("Language requires a dedicated word segmenter")
    return reasons


def table_rows(path: Path):
    """Stream numbered UTF-8 rows from plain or XZ input."""
    opener = lzma.open if path.suffix == ".xz" else Path.open
    delimiter = (
        ","
        if path.name.removesuffix(".xz").endswith(".csv")
        or path.name.startswith("ckb-context-")
        else "\t"
    )
    with opener(path, "rt", encoding="utf-8-sig", newline="") as stream:
        quoting = csv.QUOTE_MINIMAL if delimiter == "," else csv.QUOTE_NONE
        rows = csv.reader(stream, delimiter=delimiter, quoting=quoting)
        for number, row in enumerate(rows, 1):
            yield number, source_row(row, path.name)


def source_row(row: list[str], filename: str) -> list[str]:
    """Remove the empty index column in Southern Kurdish exports."""
    if filename == "sdh" and len(row) >= 4 and row[0] == "":
        return row[1:]
    return row


def checksum(path: Path) -> str:
    """Hash source bytes with bounded memory and no source writes."""
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def language_name(directory: Path) -> str:
    """Read an upstream name, falling back to its language code."""
    path = directory / "README.md"
    if not path.is_file():
        return directory.name.upper()
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        if line.startswith(("!", "[", "|", "```", "-", ">")):
            continue
        name = re.sub(r"\s*\([^)]*\)\s*$", "", line.lstrip("# ")).strip()
        if not name or name.lower() == directory.name or len(name) > 70:
            continue
        if name.startswith(("Source", "License", "Contains", "http", "<")):
            continue
        return name
    return directory.name.upper()


def write_json(path: Path, value) -> None:
    """Atomically save a readable report or registry snapshot."""
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def record_row(row, writers, stats, scripts, location) -> None:
    """Classify one row and write only supported form/lemma mappings."""
    try:
        pair = parse_row(row)
    except ValueError as error:
        stats["malformed_rows"] += 1
        if len(stats["malformed_examples"]) < 5:
            stats["malformed_examples"].append(f"{location}: {error}")
        return
    if pair is None:
        stats["ignored_rows"] += 1
        return
    lemma, form = pair
    stats["source_rows"] += 1
    observed = script_names(lemma + form)
    scripts.update(observed)
    stats["non_latin_rows"] += bool(observed)
    if not _word(normalize(form, NORMALIZATION)) or not _word(lemma):
        stats["unsupported_rows"] += 1
        return
    writers[0].writerow((form, lemma))
    stats["accepted_rows"] += 1
    if not observed:
        writers[1].writerow((form, lemma))
        stats["latin_rows"] += 1


def convert_tables(paths, destination: Path) -> tuple[dict, set[str]]:
    """Stream selected tables into TSV files and count omissions."""
    stats = dict.fromkeys(
        (
            "source_rows",
            "accepted_rows",
            "unsupported_rows",
            "malformed_rows",
            "ignored_rows",
            "non_latin_rows",
            "latin_rows",
        ),
        0,
    )
    stats["malformed_examples"] = []
    scripts = set()
    latin = destination.with_name("latin.tsv")
    with (
        destination.open("w", encoding="utf-8", newline="") as stream,
        latin.open("w", encoding="utf-8", newline="") as latin_stream,
    ):
        writers = (
            csv.writer(stream, delimiter="\t"),
            csv.writer(latin_stream, delimiter="\t"),
        )
        writers[0].writerow(("form", "lemma"))
        writers[1].writerow(("form", "lemma"))
        for path in paths:
            convert_table(path, writers, stats, scripts)
    return stats, scripts


def convert_table(path, writers, stats, scripts) -> None:
    """Process one source table without retaining its rows in memory."""
    for number, row in table_rows(path):
        record_row(row, writers, stats, scripts, f"{path.name}:{number}")


def prepare_source(directory, stage, version, paths) -> None:
    """Write metadata and preserve upstream attribution."""
    metadata = {
        "language_name": language_name(directory),
        "language_code": directory.name,
        "version": version,
        "author": "UniMorph contributors",
    }
    fields = "\n".join(
        f"{key} = {json.dumps(value, ensure_ascii=False)}"
        for key, value in metadata.items()
    )
    (stage / "config.toml").write_text(
        "format_version = 1\n\n[metadata]\n"
        + fields
        + "\n\n[normalization]\nlowercase = true\nsubstitutions = []\n",
        encoding="utf-8",
    )
    upstream = directory / "README.md"
    attribution = (
        upstream.read_text(encoding="utf-8-sig")
        if (upstream.is_file())
        else "No upstream README was supplied.\n"
    )
    names = ", ".join(path.name for path in paths)
    (stage / "README.md").write_text(
        f"# {metadata['language_name']} — UniMorph pack\n\n"
        f"Source: https://github.com/unimorph/{directory.name}\n\n"
        f"Input tables: {names}\n\n"
        "Features are omitted; form/lemma pairs are deduplicated. "
        "Unsupported multiword/symbol entries are counted and omitted. "
        "Lemma spellings are also added as lookup forms. Dialect tables "
        "share one language code; ambiguous matches are retained.\n\n"
        "Isolated non-Latin entries are excluded from ready packs. "
        "See build-info.json for checksums and conversion counts. "
        "Review the upstream terms before redistribution; conversion "
        "does not change the data license.\n\n"
        "## Original upstream README\n\n" + attribution,
        encoding="utf-8",
    )


def finish_pack(pack, directory, record) -> None:
    """Attach original licenses and conversion provenance."""
    licenses = [
        path
        for path in directory.iterdir()
        if path.is_file()
        and path.name.upper().startswith(("LICENSE", "COPYING"))
    ]
    if licenses:
        text = "\n\n".join(
            f"Original {path.name}\n\n{path.read_text(encoding='utf-8')}"
            for path in sorted(licenses)
        )
        (pack / "LICENSE").write_text(text, encoding="utf-8")
    path = pack / "build-info.json"
    info = json.loads(path.read_text(encoding="utf-8"))
    info["unimorph"] = record
    write_json(path, info)


def pack_statistics(pack: Path) -> dict:
    """Read deduplication totals from the shared database builder."""
    info = json.loads((pack / "build-info.json").read_text(encoding="utf-8"))
    return {
        "duplicate_pairs_removed": info["duplicate_pairs"],
        "unique_lemmas": info["lemmas"],
        "unique_forms": info["forms"],
        "self_forms_added": info["self_forms_added"],
    }


def convert_language(directory: Path, output: Path, version: str) -> dict:
    """Build one classified pack without changing its source."""
    paths = source_files(directory)
    record = {
        "code": directory.name,
        "name": language_name(directory),
        "status": "missing-data",
        "reasons": [],
        "sources": [{"file": p.name, "sha256": checksum(p)} for p in paths],
    }
    if not paths:
        record["reasons"] = ["No recognized inflection table in checkout"]
        return record
    with tempfile.TemporaryDirectory(dir=output) as temporary:
        return build_language(
            directory, paths, Path(temporary), output, version, record
        )


def build_language(directory, paths, stage, output, version, record) -> dict:
    """Convert, classify and validate one language pack."""
    stats, scripts = convert_tables(paths, stage / "forms.tsv")
    foreign_ratio = stats["non_latin_rows"] / max(stats["source_rows"], 1)
    reasons = deferred_reasons(directory.name, scripts, foreign_ratio)
    record.update(stats, scripts=sorted(scripts), reasons=reasons)
    if not stats["accepted_rows"]:
        record["status"] = "deferred"
        record["reasons"].append("No mappings fit the current word tokenizer")
        return record
    if stats["malformed_rows"]:
        reasons.append("Malformed input rows require inspection")
    record["status"] = "deferred" if reasons else "ready"
    record["excluded_non_latin_rows"] = 0
    if not reasons:
        (stage / "latin.tsv").replace(stage / "forms.tsv")
        record["excluded_non_latin_rows"] = (
            stats["accepted_rows"] - stats["latin_rows"]
        )
    area = output / record["status"]
    prepare_source(directory, stage, version, paths)
    service = BlitzerService(use_config=False, plugins_dir=area / "packs")
    pack = service.build_plugin(stage)
    record.update(pack_statistics(pack))
    finish_pack(pack, directory, record)
    archive = service.package_plugin(directory.name, area / "assets")
    record["pack"] = str(pack.relative_to(output))
    record["archive"] = str(archive.relative_to(output))
    defer_oversized_pack(directory, output, record)
    return record


def release_size_reasons(unpacked: int, compressed: int) -> list[str]:
    """Explain which installer byte limits a generated pack exceeds."""
    reasons = []
    if unpacked > MAX_UNPACKED_BYTES:
        reasons.append("Expanded pack exceeds the 2 GiB installer limit")
    if compressed > MAX_DOWNLOAD_BYTES:
        reasons.append("Archive exceeds the 512 MiB download limit")
    return reasons


def defer_oversized_pack(directory, output, record) -> None:
    """Move an oversized ready pack out of the publication directory."""
    if record["status"] != "ready":
        return
    pack, archive = output / record["pack"], output / record["archive"]
    unpacked = sum(p.stat().st_size for p in pack.iterdir() if p.is_file())
    reasons = release_size_reasons(unpacked, archive.stat().st_size)
    if not reasons:
        return
    record["status"] = "deferred"
    record["reasons"].extend(reasons)
    area = output / "deferred"
    destination = area / "packs" / directory.name
    destination.parent.mkdir(parents=True, exist_ok=True)
    pack.rename(destination)
    archive.unlink()
    archive.with_suffix(".zip.sha256").unlink()
    record["pack"] = str(destination.relative_to(output))
    record["archive"] = str(
        (area / "assets" / archive.name).relative_to(output)
    )
    finish_pack(destination, directory, record)
    service = BlitzerService(use_config=False, plugins_dir=area / "packs")
    archive = service.package_plugin(directory.name, area / "assets")
    record["pack"] = str(destination.relative_to(output))
    record["archive"] = str(archive.relative_to(output))


def try_language(directory, output, version) -> dict:
    """Record failures so other languages can still be built."""
    try:
        return convert_language(directory, output, version)
    except (
        OSError,
        ValueError,
        sqlite3.Error,
        csv.Error,
        EOFError,
        lzma.LZMAError,
    ) as error:
        return {
            "code": directory.name,
            "status": "error",
            "reasons": [str(error)],
        }


def registry_catalog(records) -> dict:
    """Export ready languages, preserving existing richer packs."""
    return {
        row["code"]: {"name": row["name"]}
        for row in records
        if row["status"] == "ready"
        and row["code"] not in {"slv", "pol", "pli"}
    }


def write_summary(output, records) -> None:
    """Save the readable inventory and registry export."""
    lines = [
        "# UniMorph conversion report",
        "",
        "Only ready/assets belongs in the next release. Deferred data",
        "needs script, segmentation or source-format work. A ready",
        "pack passes technical checks; review upstream licensing and",
        "language-specific behavior before publication.",
        "",
        "| Code | Status | Accepted rows | Duplicate pairs removed | "
        "Stored forms | Omitted rows | Reasons |",
        "| --- | --- | ---: | ---: | ---: | ---: | --- |",
    ]
    for row in records:
        reasons = "; ".join(row["reasons"]).replace("|", "\\|")
        omitted = sum(
            row.get(key, 0)
            for key in (
                "unsupported_rows",
                "malformed_rows",
                "excluded_non_latin_rows",
            )
        )
        lines.append(
            f"| {row['code']} | {row['status']} | "
            f"{row.get('accepted_rows', 0)} | "
            f"{row.get('duplicate_pairs_removed', 0)} | "
            f"{row.get('unique_forms', 0)} | "
            f"{omitted} | {reasons} |"
        )
    (output / "REPORT.md").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )
    write_json(output / "registry.json", registry_catalog(records))


def build_all(
    source: Path, output: Path, *, version="0.1.0", languages=(), progress=None
) -> list[dict]:
    """Build each language into a fresh directory and save progress.

    Optional language selection supports small development runs. A fresh
    output directory prevents accidental replacement of previous packs.
    Failures are recorded per language; callers can report an error.
    """
    source, output = source.resolve(), output.absolute()
    if not source.is_dir():
        raise ValueError(f"Not a UniMorph directory: {source}")
    if output.resolve().is_relative_to(source):
        raise ValueError("Output must be outside the UniMorph checkout")
    directories = sorted(
        p
        for p in source.iterdir()
        if p.is_dir() and re.fullmatch(r"[a-z]{3}", p.name)
    )
    for code in languages:
        validate_code(code, allow_base=False)
        if code not in {p.name for p in directories}:
            raise ValueError(f"Language not found in checkout: {code}")
    if languages:
        directories = [p for p in directories if p.name in languages]
    if not directories:
        raise ValueError("No language directories found")
    output.mkdir(parents=True, exist_ok=False)
    records = []
    for directory in directories:
        if progress is not None:
            progress(
                {"code": directory.name, "status": "building", "reasons": []}
            )
        record = try_language(directory, output, version)
        records.append(record)
        write_json(output / "report.json", records)
        write_summary(output, records)
        if progress is not None:
            progress(record)
    return records


def progress(record):
    """Print the current language and its conversion classification."""
    detail = "; ".join(record["reasons"])
    click.echo(f"{record['code']}: {record['status']} {detail}", err=True)


@click.command()
@click.argument(
    "source", type=click.Path(exists=True, file_okay=False, path_type=Path)
)
@click.option(
    "--output",
    required=True,
    type=click.Path(file_okay=False, path_type=Path),
    help="New directory for reports, ready packs and deferred packs.",
)
@click.option("--pack-version", default="0.1.0", show_default=True)
@click.option("--language", multiple=True, help="Build selected codes only.")
def main(source, output, pack_version, language):
    """Convert a local UniMorph checkout without publishing anything."""
    try:
        records = build_all(
            source,
            output,
            version=pack_version,
            languages=language,
            progress=progress,
        )
    except (OSError, ValueError, sqlite3.Error) as error:
        raise click.ClickException(str(error)) from error
    click.echo(str(output / "REPORT.md"))
    if any(row["status"] == "error" for row in records):
        raise click.ClickException(
            "Some languages failed; inspect report.json"
        )


if __name__ == "__main__":
    main()
