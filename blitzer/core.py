"""Provide the application API and manage local data operations.

Purpose
-------
Give both CLI commands and Python callers one place to run vocabulary,
language-pack and user-data operations. Coordinate pure processing with
explicit file and database access.

In scope
--------
- BlitzerService methods for processing, packs, known lists and history.
- Loading dictionary candidates, exclusions, ranks and corpus
  frequencies.
- SQLite schema checks and full language-pack readiness reports.
- Read-only bundled English with user-installed pack overrides.
- Pack building, provenance, staged installation and selected removal.
- Staged expansion with compatible dictionaries and addition counts.
- Registered downloads, explicit pack updates and release packaging.
- Known-list cleanup, update previews, backups and atomic replacements.
- Context-history reads, deduplicated writes and per-operation
  resources.
- Mutation locks and read-only access to source databases.
- Re-exporting processing records and functions for existing API
  callers.

Out of scope
------------
- Click commands, confirmations, terminal output and display markup.
- TOML parsing, default selection and configuration-path policy:
  config.py.
- Text algorithms and pure value parsing: processing.py.
- HTTP requests, release discovery and ZIP extraction: downloads.py.
- Downloads during ordinary text processing or executable plugins.

Start here
----------
Read BlitzerService and blitz for the public API. build_plugin lists the
pack-building sequence; its import and validation helpers are above it.
User-data methods follow the pack methods. processing.py computes the
vocabulary, config.py supplies settings, and cli.py presents results.
downloads.py handles the registry and verified release archives.
"""

import csv
import hashlib
import json
import math
import os
import re
import shutil
import sqlite3
import tempfile
import unicodedata
from blitzer.languages import display_name, language_entry
from blitzer.tokenization import elision_parts
import zipfile
from contextlib import closing, contextmanager
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path

from blitzer.config import (
    get_config,
    load_plugin_config,
    resolve_path,
    validate_code,
)

from blitzer.downloads import (
    PACK_FILES,
    asset_name,
    download_pack,
    registry_entry,
)
from blitzer.processing import (
    Context,
    Token,
    VocabularyEntry,
    _word,
    add_occurrence,
    collect_vocabulary,
    context_for_token,
    context_rows,
    filter_occurrence,
    normalize,
    normalize_mapping,
    parse_frequency,
    parse_terms,
    processing_options,
    sort_vocabulary,
    tokenize,
    validate_processing,
)

# Preserve the public imports after moving processing into its own file.
__all__ = [
    "BASE_NORMALIZATION",
    "BlitzerService",
    "CheckResult",
    "Context",
    "KnownListChange",
    "Token",
    "VocabularyEntry",
    "add_occurrence",
    "collect_vocabulary",
    "context_for_token",
    "context_rows",
    "filter_occurrence",
    "normalize",
    "normalize_mapping",
    "parse_frequency",
    "parse_terms",
    "processing_options",
    "sort_vocabulary",
    "tokenize",
    "validate_processing",
]

SCHEMA = """
CREATE TABLE lemmas (id INTEGER PRIMARY KEY, lemma TEXT NOT NULL UNIQUE);
CREATE TABLE forms (
    id INTEGER PRIMARY KEY,
    form_representation TEXT NOT NULL,
    lemma_id INTEGER NOT NULL REFERENCES lemmas(id),
    UNIQUE(form_representation, lemma_id)
);
CREATE INDEX idx_forms_repr ON forms(form_representation);
CREATE TABLE frequencies (
    term TEXT PRIMARY KEY,
    frequency REAL NOT NULL CHECK(frequency >= 0)
);
PRAGMA user_version = 1;
"""
LOOKUP = """
SELECT DISTINCT l.lemma FROM forms f JOIN lemmas l ON l.id = f.lemma_id
WHERE f.form_representation = ? ORDER BY l.lemma
"""
BASE_NORMALIZATION = {"lowercase": True, "substitutions": []}


@dataclass(frozen=True)
class CheckResult:
    """Describe one pack validation check and its outcome."""

    name: str
    status: str
    detail: str


@dataclass(frozen=True)
class KnownListChange:
    """Describe proposed or applied known-list additions."""

    path: Path
    additions: tuple[str, ...]
    applied: bool


def _read_terms(path: Path, normal: dict, *, missing_ok: bool = False):
    """Read normalized terms, duplicates and comments in order.

    A missing primary known list may be treated as empty. Other read or
    validation failures propagate without changing the source file.
    """
    if missing_ok and not path.exists():
        return [], [], []
    return parse_terms(path.read_text(encoding="utf-8"), normal, str(path))


def _read_only(path: Path) -> sqlite3.Connection:
    """Open an existing database with writes disabled.

    The caller must close the returned connection, including on errors.
    """
    return sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)


def _schema_check(conn: sqlite3.Connection) -> None:
    """Require database version one and the columns used by lookups.

    Read schema metadata only. Raise ValueError for unsupported packs.
    """
    if conn.execute("PRAGMA user_version").fetchone()[0] != 1:
        raise ValueError(
            "Unsupported database version; rebuild with build-plugin"
        )
    for table, required in (
        ("forms", {"form_representation", "lemma_id"}),
        ("lemmas", {"id", "lemma"}),
    ):
        actual = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
        if not required <= actual:
            raise ValueError(
                f"Missing columns in {table}: "
                f"{', '.join(sorted(required - actual))}"
            )


@contextmanager
def _lock(path: Path):
    """Hold and reliably release an exclusive mutation lock."""
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        stream = path.open("x", encoding="utf-8")
    except FileExistsError as error:
        raise FileExistsError(
            f"Operation locked by {path}; "
            "check its PID before removing a stale lock"
        ) from error
    try:
        with stream:
            stream.write(str(os.getpid()) + "\n")
        yield
    finally:
        path.unlink()


def _atomic_text(path: Path, text: str, *, backup: bool = False) -> None:
    """Replace a file atomically, optionally making a backup."""
    if path.is_symlink():
        raise ValueError(f"Refusing to replace a symlink: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, delete=False
        ) as stream:
            temporary = Path(stream.name)
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        _preserve_previous_file(path, temporary, backup)
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _preserve_previous_file(path, temporary, backup) -> None:
    """Preserve permissions and the requested backup."""
    if not path.exists():
        return
    temporary.chmod(path.stat().st_mode & 0o777)
    if not backup:
        return
    backup_path = path.with_name(path.name + ".bak")
    if backup_path.is_symlink():
        raise ValueError(f"Refusing symlink backup: {backup_path}")
    shutil.copy2(path, backup_path)


def _check_pack(
    directory: Path, expected_code: str | None = None
) -> list[CheckResult]:
    """Report pack readiness and prerequisite failures.

    Read files and database data without changing them. A failed load
    becomes a failed result followed by an explicit skipped-check
    result.
    """
    report = []
    try:
        config = _check_pack_files(directory, expected_code, report)
        with closing(_read_only(directory / "lemmas.db")) as conn:
            _check_database(conn, config["normalization"], report)
    except (OSError, ValueError, sqlite3.Error) as error:
        report.append(CheckResult("load/check", "fail", str(error)))
        report.append(
            CheckResult("remaining checks", "skip", "prerequisite failed")
        )
    return report


def _check_pack_files(directory, expected_code, report) -> dict:
    """Validate required files and metadata, adding completed checks."""
    if (
        not (directory / "config.toml").is_file()
        or not (directory / "lemmas.db").is_file()
    ):
        raise FileNotFoundError(
            f"Need config.toml and lemmas.db in {directory}"
        )
    report.append(CheckResult("files", "pass", str(directory)))
    config = load_plugin_config(directory)
    if (
        expected_code is not None
        and config["metadata"]["language_code"] != expected_code
    ):
        raise ValueError("Metadata code does not match installed directory")
    report.append(
        CheckResult("config", "pass", config["metadata"]["language_name"])
    )
    return config


def _check_database(conn, normal, report) -> None:
    """Append schema, relation, lookup and integrity checks in order."""
    _schema_check(conn)
    report.append(
        CheckResult("schema", "pass", "version 1 and required columns")
    )
    counts = [
        conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        for table in ("lemmas", "forms")
    ]
    report.append(
        _check_result(
            "rows", all(counts), f"{counts[0]} lemmas, {counts[1]} forms"
        )
    )
    report.append(
        _check_result(
            "lookup index",
            _has_lookup_index(conn),
            "form_representation leading column",
        )
    )
    orphan = conn.execute(
        "SELECT 1 FROM forms f LEFT JOIN lemmas l ON l.id=f.lemma_id "
        "WHERE l.id IS NULL LIMIT 1"
    ).fetchone()
    report.append(
        _check_result("relations", not orphan, "no orphan form references")
    )
    report.append(
        _check_result(
            "duplicates",
            not _has_duplicates(conn),
            "unique spellings and pairs",
        )
    )
    report.append(_check_text(conn, normal))
    report.append(_check_self_forms(conn, normal))
    integrity = [row[0] for row in conn.execute("PRAGMA integrity_check")]
    report.append(
        _check_result("integrity", integrity == ["ok"], "; ".join(integrity))
    )
    row = conn.execute(
        "SELECT form_representation FROM forms LIMIT 1"
    ).fetchone()
    matches = conn.execute(LOOKUP, (row[0],)).fetchall() if row else []
    report.append(
        _check_result(
            "known lookup", bool(matches), f"{len(matches)} candidates"
        )
    )
    report.extend(_check_frequencies(conn, normal.get("_profile", "default")))


def _check_result(name, passed, detail) -> CheckResult:
    """Build a pass/fail record from a check's Boolean outcome."""
    return CheckResult(name, "pass" if passed else "fail", detail)


def _has_lookup_index(conn) -> bool:
    """Check for a usable index beginning with the form key."""
    for row in conn.execute("PRAGMA index_list(forms)"):
        name = row[1].replace('"', '""')
        columns = list(conn.execute(f'PRAGMA index_info("{name}")'))
        if columns and columns[0][2] == "form_representation" and not row[4]:
            return True
    return False


def _has_duplicates(conn) -> bool:
    """Detect repeated lemma spellings or form/lemma pairs."""
    pair = conn.execute(
        "SELECT 1 FROM forms GROUP BY form_representation,lemma_id "
        "HAVING COUNT(*)>1 LIMIT 1"
    ).fetchone()
    lemma = conn.execute(
        "SELECT 1 FROM lemmas GROUP BY lemma HAVING COUNT(*)>1 LIMIT 1"
    ).fetchone()
    return bool(pair or lemma)


def _valid_pack_word(value, normal=None, profile="default") -> bool:
    """Check a word and its canonical representation."""
    profile = normal.get("_profile", profile) if normal is not None else profile
    if not isinstance(value, str) or not _word(value, profile):
        return False
    canonical = (
        normalize(value, normal)
        if normal is not None
        else unicodedata.normalize("NFC", value)
    )
    return canonical == value


def _check_text(conn, normal) -> CheckResult:
    """Validate stored words without retaining all rows."""
    invalid_form = next(
        (
            repr(value)
            for (value,) in conn.execute(
                "SELECT form_representation FROM forms"
            )
            if not _valid_pack_word(value, normal)
        ),
        None,
    )
    invalid_lemma = next(
        (
            repr(value)
            for (value,) in conn.execute("SELECT lemma FROM lemmas")
            if not _valid_pack_word(value, profile=normal.get("_profile", "default"))
        ),
        None,
    )
    invalid = invalid_form or invalid_lemma
    detail = (
        f"invalid value {invalid}"
        if invalid
        else "normalized single-word data"
    )
    return _check_result("text", invalid is None, detail)


def _check_self_forms(conn, normal) -> CheckResult:
    """Check each lemma has its normalized lookup form."""
    missing = next(
        (
            repr(lemma)
            for lemma_id, lemma in conn.execute("SELECT id,lemma FROM lemmas")
            if not _has_self_form(conn, lemma_id, lemma, normal)
        ),
        None,
    )
    detail = (
        f"missing {missing}" if missing else "all lemmas have lookup forms"
    )
    return _check_result("self forms", missing is None, detail)


def _has_self_form(conn, lemma_id, lemma, normal) -> bool:
    """Look up one lemma's own form, rejecting non-text lemma values."""
    if not isinstance(lemma, str):
        return False
    row = conn.execute(
        "SELECT 1 FROM forms WHERE lemma_id=? AND form_representation=?",
        (lemma_id, normalize(lemma, normal)),
    ).fetchone()
    return bool(row)


def _check_frequencies(conn, profile="default") -> list[CheckResult]:
    """Validate frequency data when the table exists."""
    table = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='frequencies'"
    ).fetchone()
    if not table:
        return []
    bad = any(
        not isinstance(term, str)
        or not _word(term, profile)
        or not _valid_frequency(value)
        for term, value in conn.execute(
            "SELECT term,frequency FROM frequencies"
        )
    )
    return [
        _check_result(
            "frequencies", not bad, "optional nonnegative corpus frequencies"
        )
    ]


def _require_valid(directory: Path, code: str | None = None) -> None:
    """Require all readiness checks to pass before publishing.

    Read the staged pack and raise ValueError listing failed checks.
    """
    failures = [
        item for item in _check_pack(directory, code) if item.status == "fail"
    ]
    if failures:
        raise ValueError(
            "Invalid pack: "
            + "; ".join(f"{x.name}: {x.detail}" for x in failures)
        )


def _hash_file(path: Path) -> str:
    """Compute a file digest by reading fixed-size chunks."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_exclusions(
    settings, normal, exclusions, forms_only, known_file, no_exclusions
) -> tuple[set[str], set[str]]:
    """Read selected known lists and exact-form exclusions."""
    if no_exclusions:
        return set(), set()
    known_paths = (
        settings.get("exclusions", []) if exclusions is None else exclusions
    )
    exact_paths = (
        settings.get("forms_only", []) if forms_only is None else forms_only
    )
    known = _load_term_set(known_paths, normal)
    exact = _load_term_set(exact_paths, normal)
    selected = known_file or (
        settings.get("known_file") if exclusions is None else None
    )
    if selected is not None:
        known.update(
            _read_terms(resolve_path(selected), normal, missing_ok=True)[0]
        )
    return known, exact


def _load_term_set(paths, normal) -> set[str]:
    """Read and union normalized terms from required exclusion files."""
    result = set()
    for path in paths:
        result.update(_read_terms(resolve_path(path), normal)[0])
    return result


def _skip_file_settings(settings, exact_file, family_file):
    """Select the two fixed-purpose files independently of display settings."""
    if exact_file is None and family_file is None:
        return {key: settings[key] for key in (
            "skip_exact_words_file", "skip_word_families_file"
        ) if key in settings}
    return {
        "skip_exact_words_file": exact_file or settings.get("skip_exact_words_file"),
        "skip_word_families_file": family_file or settings.get("skip_word_families_file"),
    }


def _validate_skip_overrides(
    filter_by, exclusions, forms_only, known_file, disabled, exact_file, family_file
):
    """Reject ambiguous legacy overrides and contradictory file selections."""
    if any(value is not None for value in (filter_by, exclusions, forms_only, known_file)):
        raise ValueError(
            "Use the two skip-file options without legacy known/exclusion "
            "options or --filter-by"
        )
    if disabled and (exact_file is not None or family_file is not None):
        raise ValueError("--show-all-words cannot be combined with explicit skip files")


def _load_skip_files(files, normal, disabled):
    """Read exact words and dictionary word families from their own files."""
    if disabled:
        return set(), set()
    exact = _optional_skip_terms(files.get("skip_exact_words_file"), normal)
    families = _optional_skip_terms(files.get("skip_word_families_file"), normal)
    return families, exact


def _optional_skip_terms(path, normal):
    """Treat an omitted or missing skip file as an empty list."""
    if path is None:
        return set()
    return set(_read_terms(resolve_path(path), normal, missing_ok=True)[0])


def _update_file_key(update_list):
    """Map an explicit update choice to its fixed-purpose file setting."""
    return {
        "exact-words": "skip_exact_words_file",
        "word-families": "skip_word_families_file",
    }.get(update_list)


def _skip_update_mode(files, update_list, track_known):
    """Require an explicit destination before proposing automatic additions."""
    if update_list is not None and update_list not in {"exact-words", "word-families"}:
        raise ValueError("update_list must be exact-words or word-families")
    if not track_known:
        return None
    key = _update_file_key(update_list)
    if key is None or not files.get(key):
        raise ValueError(
            "Choose --update-list exact-words or word-families and specify "
            "the corresponding skip file before previewing or adding words"
        )
    return "forms" if update_list == "exact-words" else "lemmas"


def _load_vocabulary_data(root, code, keys, needs_lookup, needs_frequency):
    """Read lookup and frequency data for one call.

    Validate the pack schema even when form display needs no lookup.
    Base processing returns empty resources without opening a database.
    """
    if code == "base":
        return {}, {}
    with closing(_read_only(root / code / "lemmas.db")) as conn:
        _schema_check(conn)
        candidates = _lookup_candidates(conn, keys) if needs_lookup else {}
        terms = keys | {
            term for matches in candidates.values() for term in matches
        }
        frequencies = _load_frequencies(conn, terms) if needs_frequency else {}
    return candidates, frequencies


def _lookup_candidates(conn, keys) -> dict[str, list[str]]:
    """Look up distinct keys and validate their candidates."""
    result = {}
    for key in keys:
        candidates = [row[0] for row in conn.execute(LOOKUP, (key,))]
        if any(not isinstance(term, str) or not term for term in candidates):
            raise ValueError(f"Invalid lemma data for {key!r}")
        result[key] = candidates
    return result


def _load_frequencies(conn, terms) -> dict[str, float]:
    """Read corpus frequencies for the required terms.

    Query only terms encountered in this call rather than loading the
    entire frequency table. Missing terms retain an unmeasured ranking.
    """
    table = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE name='frequencies' AND type='table'"
    ).fetchone()
    if (
        not table
        or not conn.execute("SELECT 1 FROM frequencies LIMIT 1").fetchone()
    ):
        raise ValueError(
            "Pack has no global frequency data; "
            "supply frequencies.tsv when building"
        )
    values = {}
    for term in terms:
        row = conn.execute(
            "SELECT frequency FROM frequencies WHERE term=?", (term,)
        ).fetchone()
        if row is None:
            continue
        if not _valid_frequency(row[0]):
            raise ValueError(f"Invalid global frequency for {term}")
        values[term] = row[0]
    return values


def _valid_frequency(value) -> bool:
    """Check for a finite, nonnegative numeric frequency."""
    return (
        isinstance(value, (int, float)) and math.isfinite(value) and value >= 0
    )


def _load_custom_order(sort, path, normal) -> list[str]:
    """Read custom ranks only when the selected sort requires them."""
    if sort != "custom":
        return []
    if path is None:
        raise ValueError(
            "Custom sorting needs --custom-order or custom_order in config"
        )
    return _read_terms(resolve_path(path), normal)[0]


def _validate_build_source(input_path, database, skip_orphans) -> None:
    """Reject missing build input or SQLite-only flags used with TSV."""
    if not input_path.is_file():
        raise FileNotFoundError(input_path)
    if skip_orphans and database is None:
        raise ValueError("skip_orphans requires a SQLite source database")


def _require_absent(path: Path) -> None:
    """Refuse existing destinations and dangling symlinks."""
    if path.exists() or path.is_symlink():
        raise FileExistsError(path)


def _copy_build_metadata(source: Path, stage: Path) -> None:
    """Copy config and attribution into new staging."""
    stage.mkdir()
    shutil.copy2(source / "config.toml", stage / "config.toml")
    if (source / "README.md").is_file():
        shutil.copy2(source / "README.md", stage / "README.md")


@contextmanager
def _build_connection(path: Path):
    """Create and manage a transactional build connection."""
    with closing(sqlite3.connect(path)) as conn:
        conn.execute("PRAGMA foreign_keys=ON")
        conn.executescript(SCHEMA)
        with conn:
            yield conn


def _source_orphans(path, database, skip_orphans) -> int:
    """Count or reject missing SQLite lemma references."""
    if not database:
        return 0
    query = (
        "SELECT COUNT(*) FROM forms f LEFT JOIN lemmas l "
        "ON l.id=f.lemma_id WHERE l.id IS NULL"
    )
    with closing(_read_only(path)) as source:
        count = source.execute(query).fetchone()[0]
    if count and not skip_orphans:
        raise ValueError(
            f"{path}: {count} orphan form references; inspect the source "
            "or explicitly use --skip-orphans"
        )
    return count


def _build_database(
    path,
    input_path,
    normal,
    frequencies,
    database,
    skip_unsupported,
    skip_orphans,
) -> dict:
    """Import all pack data in one staging transaction.

    Return counts for provenance. Row validation is pure; only insertion
    helpers write to the staging database. The source remains read-only.
    """
    orphan_count = _source_orphans(input_path, database, skip_orphans)
    with _build_connection(path) as conn:
        stats, lemma_ids = _import_mappings(
            conn,
            input_path,
            database,
            normal,
            skip_unsupported,
        )
        stats["orphan_source_rows"] = orphan_count
        stats["source_rows"] += orphan_count
        stats["self_forms_added"] = _insert_self_forms(conn, lemma_ids, normal)
        if frequencies.exists():
            _import_frequencies(conn, frequencies, normal.get("_profile", "default"))
        stats["lemmas"] = conn.execute(
            "SELECT COUNT(*) FROM lemmas"
        ).fetchone()[0]
        stats["forms"] = conn.execute("SELECT COUNT(*) FROM forms").fetchone()[
            0
        ]
    return stats


def _import_mappings(conn, path, database, normal, skip_unsupported):
    """Stream validated source pairs into a private staging database.

    Return row counters and the local lemma-ID cache. Keeping this cache
    avoids repeated database lookups without retaining all source forms.
    """
    stats = {"source_rows": 0, "duplicate_pairs": 0, "unsupported_rows": 0}
    lemma_ids = {}
    for number, form, lemma in _source_rows(path, database):
        stats["source_rows"] += 1
        pair = _parse_mapping_row(
            number, form, lemma, path, normal, skip_unsupported
        )
        if pair is None:
            stats["unsupported_rows"] += 1
            continue
        inserted = _insert_mapping(conn, pair, lemma_ids)
        stats["duplicate_pairs"] += not inserted
    return stats, lemma_ids


def _parse_mapping_row(number, form, lemma, path, normal, skip_unsupported):
    """Attach source location to errors from pure mapping validation."""
    try:
        return normalize_mapping(
            form, lemma, normal, skip_unsupported=skip_unsupported
        )
    except ValueError as error:
        raise ValueError(f"{path}:{number}: {error}") from error


def _insert_mapping(conn, pair, lemma_ids) -> bool:
    """Insert one pair and cache newly allocated lemma IDs."""
    key, lemma = pair
    if lemma not in lemma_ids:
        cursor = conn.execute("INSERT INTO lemmas(lemma) VALUES(?)", (lemma,))
        lemma_ids[lemma] = cursor.lastrowid
    return bool(_insert_form(conn, key, lemma_ids[lemma]))


def _insert_form(conn, key, lemma_id) -> int:
    """Insert a form pair and report whether it was new."""
    cursor = conn.execute(
        "INSERT INTO forms(form_representation,lemma_id) VALUES(?,?) "
        "ON CONFLICT DO NOTHING",
        (key, lemma_id),
    )
    return cursor.rowcount


def _insert_self_forms(conn, lemma_ids, normal) -> int:
    """Add normalized lemma lookup forms and count new relations."""
    added = 0
    for lemma, lemma_id in lemma_ids.items():
        key = normalize(lemma, normal)
        if not _word(key, normal.get("_profile", "default")) or normalize(key, normal) != key:
            raise ValueError(f"Invalid normalized self form for {lemma!r}")
        added += _insert_form(conn, key, lemma_id)
    return added


def _write_build_info(stage, source, input_path, stats) -> None:
    """Write provenance for a validated staging pack."""
    info = stats | {
        "format_version": load_plugin_config(source)["format_version"],
        "source_sha256": _hash_file(input_path),
        "source": str(input_path),
        "config_sha256": _hash_file(source / "config.toml"),
    }
    frequencies = source / "frequencies.tsv"
    if frequencies.exists():
        info["frequencies_sha256"] = _hash_file(frequencies)
    serialized = json.dumps(info, ensure_ascii=False, indent=2) + "\n"
    (stage / "build-info.json").write_text(serialized, encoding="utf-8")


class BlitzerService:
    """Provide vocabulary, pack and user-data operations."""

    def __init__(
        self,
        config_path: Path | None = None,
        *,
        use_config: bool = True,
        language_packs_dir: Path | None = None,
        plugins_dir: Path | None = None,
    ):
        """Load settings and retain the selected pack directory.

        Read configuration only; do not open databases or create user
        data.
        """
        self.config = get_config(
            config_path, use_config=use_config, language_packs_dir=language_packs_dir,
            plugins_dir=plugins_dir
        )
        self.language_packs_dir = self.config["locations"]["language_packs_dir"]

    @property
    def plugins_dir(self) -> Path:
        """Compatibility alias for language_packs_dir."""
        return self.language_packs_dir

    def settings(self, code: str) -> dict:
        """Return merged defaults and language overrides.

        The service configuration remains unchanged.
        """
        validate_code(code)
        return self.config["defaults"] | self.config["languages"].get(code, {})

    def _pack(self, code: str) -> tuple[Path, dict]:
        """Read a pack location and its validated configuration.

        Reject mismatched directory and metadata codes without modifying
        files.
        """
        validate_code(code, allow_base=False)
        directory = self._pack_directory(code)
        config = load_plugin_config(directory)
        if config["metadata"]["language_code"] != code:
            raise ValueError(
                f"{directory}: metadata language code does not match directory"
            )
        return directory, config

    def _pack_directory(self, code: str) -> Path:
        """Prefer a user pack and otherwise use bundled English data."""
        directory = self.language_packs_dir / code
        if code == "eng" and not directory.exists():
            return Path(__file__).with_name("language-packs") / code
        return directory

    def language_name(self, code: str) -> str:
        """Return the display name from installed pack metadata."""
        if code == "base":
            return "Basic"
        return display_name(code, self._pack(code)[1]["metadata"]["language_name"])

    def _normalization(self, code: str) -> dict:
        """Return normalization rules for the chosen language."""
        return (
            BASE_NORMALIZATION
            if code == "base"
            else self._pack(code)[1]["normalization"]
        )

    def blitz(
        self,
        text: str,
        language_code: str,
        *,
        lemmatize: bool | None = None,
        filter_by: str | None = None,
        context: bool | None = None,
        exclude_unknown: bool | None = None,
        exclusions: tuple[Path, ...] | None = None,
        forms_only: tuple[Path, ...] | None = None,
        no_exclusions: bool = False,
        known_file: Path | None = None,
        skip_exact_words_file: Path | None = None,
        skip_word_families_file: Path | None = None,
        update_list: str | None = None,
        sort: str | None = None,
        custom_order: Path | None = None,
        sentence_pattern: str | None = None,
        context_limit: int | None = None,
        track_known: bool = False,
    ) -> list[VocabularyEntry]:
        """Extract filtered vocabulary from input text.

        Explicit options override language settings. Known-list and
        history writes remain separate operations; this method only
        reads files.
        """
        settings = self.settings(language_code)
        options = processing_options(
            settings,
            lemmatize=lemmatize,
            filter_by=filter_by,
            context=context,
            exclude_unknown=exclude_unknown,
            sort=sort,
            sentence_pattern=sentence_pattern,
            context_limit=context_limit,
        )
        skip_files = _skip_file_settings(
            settings, skip_exact_words_file, skip_word_families_file
        )
        if update_list is not None and not skip_files:
            raise ValueError(
                "--update-list requires a skip_exact_words_file or skip_word_families_file"
            )
        if skip_files:
            _validate_skip_overrides(
                filter_by, exclusions, forms_only, known_file,
                no_exclusions, skip_exact_words_file, skip_word_families_file
            )
            family_filter = skip_files.get("skip_word_families_file") and not no_exclusions
            options["filter_by"] = "lemmas" if family_filter else "forms"
            options["known_update_mode"] = _skip_update_mode(
                skip_files, update_list or settings.get("update_list"), track_known
            )
        validate_processing(
            text,
            language_code,
            options,
            no_exclusions,
            track_known,
            exclusions,
            forms_only,
        )
        normal = self._normalization(language_code)
        profile = normal.get("_profile", "default")
        # Legacy data for unspaced languages must not silently tokenize prose
        # as one run. Format 2 explicitly declares even a limited local mode.
        if language_code != "base":
            pack_config = self._pack(language_code)[1]
            if (pack_config["format_version"] == 1
                    and language_entry(language_code)["profile"] in {"unavailable", "sudachi"}):
                raise ValueError(
                    f"{language_code} requires lexical segmentation; rebuild "
                    "with a format-2 pack declaring its tokenization profile"
                )
        known, exact = _load_exclusions(
            settings,
            normal,
            exclusions,
            forms_only,
            known_file,
            no_exclusions,
        ) if not skip_files else _load_skip_files(skip_files, normal, no_exclusions)
        needs_lookup = (
            track_known
            or options["lemmatize"]
            or options["exclude_unknown"]
            or (options["filter_by"] == "lemmas" and bool(known))
        )
        tokens = list(tokenize(text, profile))
        full_keys = {normalize(token.text, normal) for token in tokens}
        alternatives = {
            normalize(token.lookup, normal)
            for token in tokens if token.lookup is not None
        }
        alternatives.update(
            normalize(part.text, normal)
            for token in tokens if len(elision_parts(token, profile)) > 1
            for part in elision_parts(token, profile)
        )
        needs_lookup = needs_lookup or profile.startswith("elision-")
        keys = alternatives | {
            key
            for key in full_keys
            if key and key not in known and key not in exact
        }
        candidates, frequencies = _load_vocabulary_data(
            self.language_packs_dir
            if language_code == "base"
            else self._pack_directory(language_code).parent,
            language_code,
            keys,
            needs_lookup,
            options["sort"] == "global-frequency",
        )
        resolved_tokens = []
        for token in tokens:
            key = normalize(token.text, normal)
            if not candidates.get(key) and token.lookup is not None:
                candidates[key] = candidates.get(normalize(token.lookup, normal), [])
            parts = elision_parts(token, profile)
            if (not candidates.get(key) and len(parts) > 1
                    and key not in known and key not in exact
                    and (candidates.get(normalize(parts[-1].text, normal))
                         or normalize(parts[-1].text, normal) in known | exact)):
                resolved_tokens.extend(parts)
            else:
                resolved_tokens.append(token)
        entries = collect_vocabulary(
            text,
            normal,
            known,
            exact,
            candidates,
            options,
            tokens=resolved_tokens,
        )
        entries = [
            replace(entry, global_frequency=frequencies.get(entry.term))
            for entry in entries
        ]
        order = _load_custom_order(
            options["sort"],
            custom_order or settings.get("custom_order"),
            normal,
        )
        return sort_vocabulary(entries, options["sort"], order, normal)

    def list_languages(self) -> list[str]:
        """Return user pack codes plus base and English, sorted by display name.

        This checks required file presence and reads pack metadata. Use check_plugin to
        validate metadata, schema and data before relying on an
        installed pack.
        """
        if not self.language_packs_dir.exists():
            return ["base", "eng"]
        codes = []
        for path in self.language_packs_dir.iterdir():
            if not re.fullmatch(r"[a-z]{3}", path.name) or not path.is_dir():
                continue
            if (path / "config.toml").is_file() and (
                path / "lemmas.db"
            ).is_file():
                codes.append(path.name)
        return sorted({"base", "eng", *codes},
                      key=lambda code: (self.language_name(code).casefold(), code))

    def check_plugin(self, code: str) -> list[CheckResult]:
        """Report all validation checks for an installed pack.

        Failed checks remain report entries rather than triggering
        publication or changing files. Invalid language codes raise
        ValueError.
        """
        validate_code(code, allow_base=False)
        return _check_pack(self._pack_directory(code), code)

    def build_plugin(
        self,
        source_dir: Path,
        *,
        source_database: Path | None = None,
        skip_unsupported: bool = False,
        skip_orphans: bool = False,
    ) -> Path:
        """Build and validate a pack before publishing it.

        Import TSV by default, or a compatible SQLite source when
        supplied. Unsupported rows and orphan references require
        explicit opt-in to skip. Failed builds discard staging and leave
        no installed pack.
        """
        source = resolve_path(source_dir)
        config = load_plugin_config(source)
        code = config["metadata"]["language_code"]
        destination = self.language_packs_dir / code
        input_path = (
            resolve_path(source_database)
            if source_database is not None
            else source / "forms.tsv"
        )
        _validate_build_source(input_path, source_database, skip_orphans)
        with (
            _lock(self.language_packs_dir / ".mutation.lock"),
            tempfile.TemporaryDirectory(
                prefix=".build-",
                dir=self.language_packs_dir,
            ) as temporary,
        ):
            _require_absent(destination)
            stage = Path(temporary) / code
            _copy_build_metadata(source, stage)
            stats = _build_database(
                stage / "lemmas.db",
                input_path,
                config["normalization"],
                source / "frequencies.tsv",
                source_database is not None,
                skip_unsupported,
                skip_orphans,
            )
            _require_valid(stage, code)
            _write_build_info(stage, source, input_path, stats)
            _require_absent(destination)
            stage.rename(destination)
        return destination

    def install_plugin(
        self, source_dir: str | Path, *, replace: bool = False
    ) -> Path:
        """Install a registered language or a local directory.

        A bare code downloads its newest stable GitHub pack. An existing
        directory uses local files. Explicit replace allows a staged
        update and rollback; known lists and context history remain
        untouched.
        """
        if type(replace) is not bool:
            raise ValueError("replace must be a boolean")
        source = resolve_path(source_dir)
        is_code = isinstance(source_dir, str) and re.fullmatch(
            r"[a-z]{3}|base", source_dir
        )
        if is_code and not source.is_dir():
            return self._install_download(str(source_dir), replace)
        return self._install_local(source, replace)

    def expand_plugin(
        self, code: str, additional: Path, *, version: str = "0.2.0"
    ) -> dict:
        """Add missing pairs and atomically replace a validated pack.

        Preserve existing pairs, frequencies, settings and attribution.
        A merge adding no pairs leaves the installed pack unchanged.
        Validation failures discard staging before touching the base.
        """
        from blitzer.merging import merge_packs

        validate_code(code, allow_base=False)
        destination = self.language_packs_dir / code
        additional = resolve_path(additional)
        with (
            _lock(self.language_packs_dir / ".mutation.lock"),
            tempfile.TemporaryDirectory(dir=self.language_packs_dir) as temporary,
        ):
            _require_valid(destination, code)
            _require_valid(additional, code)
            stage = Path(temporary) / code
            stats = merge_packs(destination, additional, stage, version)
            if not stats["pairs_added"]:
                return stats
            _require_valid(stage, code)
            _publish_install(stage, destination, True)
        return stats

    def _install_download(self, code: str, replace: bool) -> Path:
        """Download staging before normal pack installation."""
        registry_entry(code)
        _check_install_destination(self.language_packs_dir / code, replace)
        with tempfile.TemporaryDirectory(
            prefix="blitzer-download-"
        ) as temporary:
            source = download_pack(code, Path(temporary))
            return self._install_local(source, replace, expected_code=code)

    def _install_local(
        self, source: Path, replace: bool, expected_code=None
    ) -> Path:
        """Validate and publish a local copy under the lock.

        Remote packs must match the requested code. Reject links,
        overlapping source/destination directories and implicit
        replacement. Revalidate the staged copy before modifying the
        installed pack.
        """
        if source.is_symlink() or any(
            path.is_symlink() for path in source.rglob("*")
        ):
            raise ValueError("Install a self-contained pack without symlinks")
        code = load_plugin_config(source)["metadata"]["language_code"]
        if expected_code is not None and code != expected_code:
            raise ValueError(
                "Downloaded pack metadata does not match "
                "the requested language"
            )
        destination = self.language_packs_dir / code
        a, b = source.resolve(), destination.resolve()
        if a == b or a in b.parents or b in a.parents:
            raise ValueError(
                "Source and destination directories "
                "must not contain each other"
            )
        _check_install_destination(destination, replace)
        _require_valid(source)
        with (
            _lock(self.language_packs_dir / ".mutation.lock"),
            tempfile.TemporaryDirectory(
                prefix=".install-",
                dir=self.language_packs_dir,
            ) as temporary,
        ):
            _check_install_destination(destination, replace)
            stage = Path(temporary) / code
            shutil.copytree(source, stage)
            _require_valid(stage, code)
            _publish_install(stage, destination, replace)
        return destination

    def package_plugin(self, code: str, output_dir: Path) -> Path:
        """Prepare a validated pack archive for publication.

        Keep version numbers in config.toml and release tags, not
        filenames. Write an adjacent checksum file for publisher
        inspection. The source pack remains unchanged; completed output
        replaces an earlier archive.
        """
        directory, _ = self._pack(code)
        if directory.is_symlink() or any(
            path.is_symlink() for path in directory.rglob("*")
        ):
            raise ValueError("Package a self-contained pack without symlinks")
        _require_valid(directory, code)
        output = resolve_path(output_dir)
        output.mkdir(parents=True, exist_ok=True)
        target = output / asset_name(code)
        _write_release_archive(directory, target, code)
        checksum = f"{_hash_file(target)}  {target.name}\n"
        _atomic_text(target.with_suffix(".zip.sha256"), checksum)
        return target

    def remove_plugin(self, code: str) -> None:
        """Remove one pack while holding the mutation lock.

        Reject base, malformed codes, symlinks and missing packs. Other
        language packs and user-maintained data are untouched.
        """
        validate_code(code, allow_base=False)
        path = self.language_packs_dir / code
        if code == "eng" and not path.exists():
            raise ValueError(
                "English is bundled with bltzr; there is no user pack "
                "to remove"
            )
        with _lock(self.language_packs_dir / ".mutation.lock"):
            if path.is_symlink():
                raise ValueError(
                    f"Refusing to remove a symlinked pack: {path}"
                )
            if not path.is_dir():
                raise FileNotFoundError(path)
            shutil.rmtree(path)

    def cleanup_known(
        self, code: str, path: Path, *, apply: bool = False
    ) -> dict:
        """Preview or apply known-list deduplication.

        Preview leaves file contents unchanged. Apply preserves comments
        and first-seen term order, normalizes spelling and saves a
        backup.
        """
        path = resolve_path(path)
        normal = self._normalization(code)
        with _lock(path.with_name(path.name + ".lock")):
            terms, duplicates, comments = _read_terms(path, normal)
            result = {
                "path": str(path),
                "unique_terms": len(terms),
                "duplicates": duplicates,
                "applied": apply,
            }
            if apply:
                _atomic_text(
                    path, "\n".join([*comments, *terms]) + "\n", backup=True
                )
        return result

    def update_known(
        self,
        code: str,
        entries: list[VocabularyEntry],
        *,
        path: Path | None = None,
        dry_run: bool = True,
        list_kind: str | None = None,
    ) -> KnownListChange:
        """Preview or write matched terms to the known list.

        Dry runs read existing terms and create no files. Real updates
        use a lock and atomic replacement with a backup. Matching a word
        does not establish that the user has learned it.
        """
        settings = self.settings(code)
        files = _skip_file_settings(settings, None, None)
        selected = path or settings.get("known_file")
        if files or list_kind is not None:
            kind = list_kind or settings.get("update_list")
            key = _update_file_key(kind)
            if key is None:
                raise ValueError("Choose update_list: exact-words or word-families")
            selected = path or files.get(key)
        if selected is None:
            if files or list_kind is not None:
                raise ValueError("Specify the skip file selected by update_list")
            raise ValueError(
                "Known updating needs --known-file "
                "or languages.CODE.known_file"
            )
        path = resolve_path(selected)
        normal = self._normalization(code)
        proposed = set().union(*(entry.known_terms for entry in entries))
        if dry_run:
            old, _, _ = _read_terms(path, normal, missing_ok=True)
            return KnownListChange(
                path, tuple(sorted(proposed - set(old))), False
            )
        with _lock(path.with_name(path.name + ".lock")):
            old, _, comments = _read_terms(path, normal, missing_ok=True)
            additions = tuple(sorted(proposed - set(old)))
            if additions:
                _atomic_text(
                    path,
                    "\n".join([*comments, *old, *additions]) + "\n",
                    backup=True,
                )
        return KnownListChange(path, additions, bool(additions))

    def save_contexts(self, code: str, entries: list[VocabularyEntry]) -> int:
        """Save surviving contexts and return the new row count.

        Repeated calls deduplicate the same language, term and
        highlighted sentence. Vocabulary entries and their contexts
        remain unchanged.
        """
        validate_code(code)
        path = self.config["locations"]["history_file"]
        path.parent.mkdir(parents=True, exist_ok=True)
        with _history_connection(path) as conn:
            now = datetime.now(timezone.utc).isoformat()
            before = conn.total_changes
            conn.executemany(
                "INSERT INTO contexts VALUES(?,?,?,?,?,?) "
                "ON CONFLICT DO NOTHING",
                context_rows(code, entries, now),
            )
            return conn.total_changes - before

    def history(
        self, code: str, term: str | None = None, *, limit: int = 100
    ) -> list[dict]:
        """Read saved original contexts in deterministic order.

        Filter by exact stored term when supplied. Missing history
        returns an empty list without creating a database; invalid
        limits raise ValueError.
        """
        validate_code(code)
        if type(limit) is not int or limit < 1:
            raise ValueError("limit must be positive")
        path = self.config["locations"]["history_file"]
        if not path.exists():
            return []
        query = (
            "SELECT term,text,highlight_start,highlight_end,first_seen "
            "FROM contexts WHERE language=?"
        )
        values = [code]
        if term is not None:
            query += " AND term=?"
            values.append(term)
        query += " ORDER BY first_seen,term,text LIMIT ?"
        values.append(limit)
        with closing(_read_only(path)) as conn:
            return [
                dict(
                    zip(
                        (
                            "term",
                            "text",
                            "highlight_start",
                            "highlight_end",
                            "first_seen",
                        ),
                        row,
                    )
                )
                for row in conn.execute(query, values)
            ]


def _source_rows(path: Path, database: bool):
    """Yield numbered form/lemma pairs without modifying the source."""
    if database:
        yield from _database_rows(path)
        return
    yield from _tsv_rows(path, ("form", "lemma"))


def _database_rows(path: Path):
    """Stream form/lemma pairs from a read-only database."""
    query = (
        "SELECT f.form_representation,l.lemma FROM forms f "
        "JOIN lemmas l ON l.id=f.lemma_id"
    )
    with closing(_read_only(path)) as source:
        for number, (form, lemma) in enumerate(source.execute(query), 1):
            yield number, form, lemma


def _tsv_rows(path: Path, header: tuple[str, str]):
    """Yield numbered rows from a validated two-column TSV."""
    with path.open(encoding="utf-8", newline="") as stream:
        reader = csv.reader(stream, delimiter="\t")
        if next(reader, None) != list(header):
            raise ValueError(f"{path}: header must be {'<TAB>'.join(header)}")
        yield from _validated_tsv_rows(reader, path)


def _validated_tsv_rows(reader, path: Path):
    """Attach physical line numbers to validated two-column CSV rows."""
    for row in reader:
        if len(row) != 2:
            raise ValueError(f"{path}:{reader.line_num}: expected two columns")
        yield reader.line_num, row[0], row[1]


def _import_frequencies(conn: sqlite3.Connection, path: Path, profile="default") -> None:
    """Insert validated frequencies into the transaction."""
    for number, term, value in _tsv_rows(path, ("term", "frequency")):
        parsed = _parse_frequency_row(number, term, value, path, profile)
        conn.execute("INSERT INTO frequencies VALUES(?,?)", parsed)


def _parse_frequency_row(number, term, value, path, profile="default"):
    """Add source location to errors from pure frequency validation."""
    try:
        return parse_frequency(term, value, profile)
    except ValueError as error:
        raise ValueError(f"{path}:{number}: {error}") from error


@contextmanager
def _history_connection(path):
    """Prepare history and manage one write transaction."""
    with closing(sqlite3.connect(path)) as conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS contexts (
            language TEXT NOT NULL, term TEXT NOT NULL, text TEXT NOT NULL,
            highlight_start INTEGER NOT NULL, highlight_end INTEGER NOT NULL,
            first_seen TEXT NOT NULL,
            UNIQUE(language,term,text,highlight_start,highlight_end))"""
        )
        with conn:
            yield conn


def _check_install_destination(destination: Path, replace: bool) -> None:
    """Require a fresh pack or explicit replacement."""
    if destination.is_symlink():
        raise ValueError(
            f"Refusing a symlinked pack destination: {destination}"
        )
    if not destination.exists():
        return
    if not replace or not destination.is_dir():
        raise FileExistsError(
            f"{destination} already exists; use --replace to update a pack"
        )


def _publish_install(stage: Path, destination: Path, replace: bool) -> None:
    """Publish staging, preserving the old pack if replacement fails.

    Hold the caller's mutation lock. A backup stays outside temporary
    staging so a failed rollback cannot cause automatic deletion of it.
    """
    _check_install_destination(destination, replace)
    if not destination.exists():
        stage.rename(destination)
        return
    previous = destination.with_name(f".{destination.name}.previous")
    _require_absent(previous)
    destination.rename(previous)
    try:
        stage.rename(destination)
    except OSError:
        previous.rename(destination)
        raise
    shutil.rmtree(previous)


def _write_release_archive(directory: Path, target: Path, code: str) -> None:
    """Atomically write the supported pack data files."""
    if target.is_symlink():
        raise ValueError(f"Refusing a symlinked release archive: {target}")
    with tempfile.TemporaryDirectory(
        prefix=".package-", dir=target.parent
    ) as temporary:
        archive = Path(temporary) / target.name
        _zip_pack_files(directory, archive, code)
        os.replace(archive, target)


def _zip_pack_files(directory: Path, target: Path, code: str) -> None:
    """Write pack data under one language directory."""
    paths = [
        directory / name
        for name in sorted(PACK_FILES)
        if (directory / name).is_file()
    ]
    with zipfile.ZipFile(
        target, "w", compression=zipfile.ZIP_DEFLATED
    ) as archive:
        for path in paths:
            archive.write(path, f"{code}/{path.name}")
