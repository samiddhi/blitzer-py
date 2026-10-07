"""Load, validate and resolve application and pack configuration.

Purpose
-------
Translate user TOML files, explicit overrides and environment settings
into validated dictionaries and paths that the application can use.

In scope
--------
- Built-in defaults and supported option values.
- Config-file selection and flag/environment/platform precedence.
- XDG or platform locations and expansion of user-supplied paths.
- TOML field and type validation for user settings and language packs.
- Sentence-pattern validation before text processing begins.

Out of scope
------------
- Click commands, terminal output and interactive decisions.
- Word processing, SQL queries and language-pack data validation.
- Creating directories, changing configuration files or writing user
  data.

Start here
----------
Read get_config for user settings and load_plugin_config for pack
metadata.
The helpers above them validate values and resolve locations. core.py
uses
these settings; processing.py uses the supported processing choices.
"""

import os
import re
import tomllib
from pathlib import Path

from platformdirs import user_config_dir, user_data_dir

APP = "blitzer"
CONFIG_ENV_VAR = "BLITZER_CONFIG"
CONFIG_FILE_NAME = "blitzer.toml"
SORTS = (
    "textual-frequency",
    "alphabetical",
    "appearance",
    "global-frequency",
    "custom",
)
MARKUPS = ("off", "html", "markdown", "org")
FORMATS = ("text", "tsv", "json", "report")
SAVE_CONTEXT = ("never", "always", "prompt", "flag-only")


def resolve_path(value: str | Path, base: Path | None = None) -> Path:
    """Resolve a user path without creating resources."""
    value = str(value)
    if not value:
        raise ValueError("A path must not be empty")
    for match in re.finditer(
        r"\$(?:\{([A-Za-z_][A-Za-z_0-9]*)\}|([A-Za-z_][A-Za-z_0-9]*))", value
    ):
        name = match.group(1) or match.group(2)
        if name not in os.environ:
            raise ValueError(f"Unset environment variable in path: {name}")
    path = Path(os.path.expandvars(value)).expanduser()
    if not path.is_absolute():
        path = (base or Path.cwd()) / path
    return path.absolute()


def _platform_dir(kind: str) -> Path:
    """Return the XDG or platform application directory.

    Read the environment without creating directories. Reject relative
    XDG roots so storage locations cannot depend on the working
    directory.
    """
    variable = "XDG_CONFIG_HOME" if kind == "config" else "XDG_DATA_HOME"
    value = os.environ.get(variable)
    if not value:
        return Path(
            user_config_dir(APP) if kind == "config" else user_data_dir(APP)
        )
    root = Path(value)
    if not root.is_absolute():
        raise ValueError(f"{variable} must be an absolute path")
    return root / APP


def _default_config() -> dict:
    """Return fresh defaults for the current platform.

    Every call builds independent dictionaries and creates no resources.
    """
    data = _platform_dir("data")
    return {
        "locations": {
            "plugins_dir": data / "languages",
            "history_file": data / "contexts.db",
        },
        "defaults": {
            "lemmatize": False,
            "filter_by": "forms",
            "exclude_unknown": False,
            "freq": False,
            "context": False,
            "prompt": False,
            "src": False,
            "format": "text",
            "sort": "textual-frequency",
            "bold": "html",
            "sentence_pattern": r"(?:[.!?]+(?=\s|$)|\n+)",
            "context_limit": 2,
            "save_context": "flag-only",
            "auto_update_known": False,
        },
        "languages": {},
    }


def validate_code(code: str, *, allow_base: bool = True) -> str:
    """Validate a language code, optionally allowing base.

    Raise ValueError for malformed codes or base when packs are
    required.
    """
    if (allow_base and code == "base") or re.fullmatch(r"[a-z]{3}", code):
        return code
    raise ValueError(
        f"Invalid language code {code!r}; use three lowercase letters or base"
    )


def _table(value, label: str, allowed: set) -> dict:
    """Validate a TOML table and its allowed fields.

    Return the original table unchanged; raise ValueError for invalid
    input.
    """
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a TOML table")
    unknown = value.keys() - allowed
    if unknown:
        raise ValueError(
            f"Unknown {label} field: {', '.join(sorted(unknown))}"
        )
    return value


def validate_pattern(pattern: str) -> str:
    """Require a sentence delimiter that consumes text."""
    if not isinstance(pattern, str) or not pattern:
        raise ValueError(
            "sentence_pattern must be a nonempty regular expression"
        )
    try:
        compiled = re.compile(pattern)
    except re.error as error:
        raise ValueError(f"Invalid sentence_pattern: {error}") from error
    for sample in ("", "Word. Another!\nEnd", "abc xyz", "č sem smo"):
        if any(m.start() == m.end() for m in compiled.finditer(sample)):
            raise ValueError("sentence_pattern must not match empty text")
    return pattern


def _validate_options(options: dict, label: str) -> None:
    """Validate option types and supported values.

    Raise ValueError with the setting's label for invalid values.
    """
    bools = {
        "lemmatize",
        "freq",
        "context",
        "exclude_unknown",
        "prompt",
        "src",
        "auto_update_known",
    }
    choices = {
        "filter_by": ("forms", "lemmas"),
        "format": FORMATS,
        "sort": SORTS,
        "bold": MARKUPS,
        "save_context": SAVE_CONTEXT,
    }
    for key, value in options.items():
        if key in bools and type(value) is not bool:
            raise ValueError(f"{label}.{key} must be a boolean")
        if key in choices and value not in choices[key]:
            raise ValueError(
                f"{label}.{key} must be one of {', '.join(choices[key])}"
            )
        if key == "context_limit" and (
            type(value) is not int or not 1 <= value <= 20
        ):
            raise ValueError(
                f"{label}.context_limit must be an integer from 1 to 20"
            )
        if key == "sentence_pattern":
            validate_pattern(value)


def _paths(settings: dict, base: Path, label: str) -> dict:
    """Return settings with configuration-relative paths.

    Validate path field types and prompt text without changing settings.
    Environment expansion is delegated to resolve_path.
    """
    result = dict(settings)
    for key in ("exclusions", "forms_only"):
        if key not in result:
            continue
        value = result[key]
        if not isinstance(value, list) or not all(
            isinstance(x, str) for x in value
        ):
            raise ValueError(f"{label}.{key} must be a list of paths")
        result[key] = [resolve_path(x, base) for x in value]
    for key in ("known_file", "custom_order"):
        if key not in result:
            continue
        result[key] = _path_setting(result[key], base, f"{label}.{key}")
    if "prompt_text" in result and not isinstance(result["prompt_text"], str):
        raise ValueError(f"{label}.prompt_text must be text")
    return result


def _path_setting(value, base, label) -> Path:
    """Validate and resolve one path setting."""
    if not isinstance(value, str):
        raise ValueError(f"{label} must be a path string")
    return resolve_path(value, base)


def _select_config_path(override, use_config) -> Path | None:
    """Select the configuration file using precedence."""
    if not use_config and override is not None:
        raise ValueError("--config and --no-config cannot be combined")
    if not use_config:
        return None
    selected = override or os.environ.get(CONFIG_ENV_VAR)
    path = (
        resolve_path(selected)
        if selected
        else _platform_dir("config") / CONFIG_FILE_NAME
    )
    if selected or path.exists():
        return path
    return None


def _read_toml(path: Path) -> dict:
    """Read UTF-8 TOML, propagating missing-file and parsing errors."""
    with path.open("rb") as stream:
        return tomllib.load(stream)


def _merge_config(raw, defaults, base) -> dict:
    """Validate and merge settings into fresh dictionaries.

    Caller-owned dictionaries stay unchanged. Relative paths use base;
    path expansion may read the environment but creates no resources.
    """
    _table(raw, "config", {"locations", "defaults", "languages"})
    locations = _table(
        raw.get("locations", {}), "locations", set(defaults["locations"])
    )
    locations = defaults["locations"] | {
        key: _path_setting(value, base, f"locations.{key}")
        for key, value in locations.items()
    }
    allowed = set(defaults["defaults"]) | {"custom_order"}
    options = _table(raw.get("defaults", {}), "defaults", allowed)
    _validate_options(options, "defaults")
    options = defaults["defaults"] | _paths(options, base, "defaults")
    languages = raw.get("languages", {})
    if not isinstance(languages, dict):
        raise ValueError("languages must be a table")
    return {
        "locations": locations,
        "defaults": options,
        "languages": {
            code: _language_settings(code, values, allowed, base)
            for code, values in languages.items()
        },
    }


def _language_settings(code, values, allowed, base) -> dict:
    """Validate and resolve one language override."""
    validate_code(code)
    label = f"languages.{code}"
    extra = {"exclusions", "forms_only", "known_file", "prompt_text"}
    _table(values, label, allowed | extra)
    _validate_options(values, label)
    return _paths(values, base, label)


def get_config(
    override_config_file: Path | None = None,
    *,
    use_config: bool = True,
    plugins_dir: Path | None = None,
) -> dict:
    """Return validated settings without creating resources.

    Selection uses an explicit file, then BLITZER_CONFIG, then the
    platform file. Missing optional platform files use defaults; missing
    explicit files raise an error. An explicit plugin directory
    overrides the file.
    """
    path = _select_config_path(override_config_file, use_config)
    config = _default_config()
    if path is not None:
        config = _merge_config(_read_toml(path), config, path.parent)
    if plugins_dir is not None:
        config["locations"]["plugins_dir"] = resolve_path(plugins_dir)
    return config


def load_plugin_config(plugin_dir: Path) -> dict:
    """Read and validate a versioned data-only pack config."""
    path = plugin_dir / "config.toml"
    data = _read_toml(path)
    _table(data, str(path), {"format_version", "metadata", "normalization"})
    if (
        type(data.get("format_version")) is not int
        or data["format_version"] != 1
    ):
        raise ValueError(
            f"{path}: expected format_version = 1; "
            "convert unversioned packs explicitly"
        )
    metadata = _table(
        data.get("metadata"),
        "metadata",
        {"language_name", "language_code", "version", "author"},
    )
    for key in ("language_name", "language_code", "version", "author"):
        if not isinstance(metadata.get(key), str) or not metadata[key].strip():
            raise ValueError(f"{path}: metadata.{key} must be nonempty text")
    validate_code(metadata["language_code"], allow_base=False)
    normal = _table(
        data.get("normalization"),
        "normalization",
        {"lowercase", "substitutions"},
    )
    if type(normal.get("lowercase")) is not bool or not isinstance(
        normal.get("substitutions"), list
    ):
        raise ValueError(
            f"{path}: normalization needs lowercase and a substitutions array"
        )
    for rule in normal["substitutions"]:
        _table(rule, "substitution", {"from", "to"})
        if (
            not isinstance(rule.get("from"), str)
            or not rule["from"]
            or not isinstance(rule.get("to"), str)
        ):
            raise ValueError(
                f"{path}: each substitution needs "
                "a nonempty from and a string to"
            )
        if any(c.isspace() or ord(c) < 32 for c in rule["from"] + rule["to"]):
            raise ValueError(
                f"{path}: substitutions cannot introduce "
                "whitespace or control characters"
            )
    return data
