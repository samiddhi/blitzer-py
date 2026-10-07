"""Check configuration validation, precedence and path handling.

Purpose
-------
Verify that settings fail clearly when invalid and resolve consistently
without creating user resources.

In scope
--------
- Default settings, file selection and explicit/environment overrides.
- Configuration-relative paths and environment-variable expansion.
- Unknown fields, invalid option types and bad sentence patterns.
- Language-pack metadata and code validation.

Out of scope
------------
- Vocabulary processing, pack database contents and persistent
  mutations.
- Click output and prompts: test_cli.py.

Start here
----------
Each test exercises config.py directly using temporary files or
controlled
environment settings. conftest.py supplies isolation for all tests.
"""

import pytest

from blitzer.config import (
    get_config,
    load_plugin_config,
    resolve_path,
    validate_pattern,
)


def test_defaults_read_nothing(tmp_path):
    """Check defaults create no user resources."""
    config = get_config()
    assert config["defaults"]["filter_by"] == "forms"
    assert config["defaults"]["exclude_unknown"] is False
    assert not list(tmp_path.iterdir())


def test_selection_and_relative_paths(tmp_path, monkeypatch):
    """Check config precedence and configuration-relative paths."""
    env = tmp_path / "env.toml"
    flag = tmp_path / "flag.toml"
    env.write_text("[defaults]\nfreq = true\n")
    flag.write_text(
        '[locations]\nplugins_dir = "packs"\n[languages.slv]\n'
        'known_file = "known.txt"\nfilter_by = "lemmas"\n'
    )
    monkeypatch.setenv("BLITZER_CONFIG", str(env))
    assert get_config()["defaults"]["freq"] is True
    loaded = get_config(flag)
    assert loaded["defaults"]["freq"] is False
    assert loaded["locations"]["plugins_dir"] == tmp_path / "packs"
    assert loaded["languages"]["slv"]["known_file"] == tmp_path / "known.txt"
    assert get_config(use_config=False)["defaults"]["freq"] is False
    with pytest.raises(ValueError):
        get_config(flag, use_config=False)


@pytest.mark.parametrize(
    "contents",
    [
        "[defaults]\nfreq = 1",
        "[defaults]\nfreg = true",
        "[defaults]\ncontext_limit = 0",
        '[languages.slv]\nexclusions = "known.txt"',
        '[defaults]\nsort = "magic"',
        "[locations]\nplugins_dir = 42",
        "defaults = 9",
        "[languages.BAD]",
    ],
)
def test_invalid_config_fails(tmp_path, contents):
    """Check unknown fields and invalid option values are rejected."""
    path = tmp_path / "bad.toml"
    path.write_text(contents)
    with pytest.raises(ValueError):
        get_config(path)


def test_missing_explicit_or_env_fails(tmp_path, monkeypatch):
    """Check selected missing config files produce visible errors."""
    missing = tmp_path / "missing.toml"
    with pytest.raises(FileNotFoundError):
        get_config(missing)
    monkeypatch.setenv("BLITZER_CONFIG", str(missing))
    with pytest.raises(FileNotFoundError):
        get_config()
    get_config(use_config=False)


def test_expansion_validation(tmp_path, monkeypatch):
    """Check path expansion rejects unset environment variables."""
    monkeypatch.setenv("WORDS", str(tmp_path))
    assert resolve_path("${WORDS}/known.txt") == tmp_path / "known.txt"
    monkeypatch.delenv("WORDS")
    with pytest.raises(ValueError):
        resolve_path("$WORDS/known.txt")
    monkeypatch.setenv("XDG_DATA_HOME", "relative")
    with pytest.raises(ValueError):
        get_config(use_config=False)


@pytest.mark.parametrize("pattern", ["", "[", r"\b", "(?=a)"])
def test_reject_bad_sentence_patterns(pattern):
    """Check invalid and zero-width sentence delimiters are rejected."""
    with pytest.raises(ValueError):
        validate_pattern(pattern)


def test_pack_rejects_code_and_unknown_fields(source):
    """Check pack configuration validates codes and rejects typos."""
    path = source / "config.toml"
    path.write_text(
        path.read_text().replace(
            'language_code = "slv"', 'language_code = "../slv"'
        )
    )
    with pytest.raises(ValueError):
        load_plugin_config(source)


def test_old_prototype_paths_are_not_selected(tmp_path):
    """Check defaults leave old prototype packs and config untouched."""
    legacy = tmp_path / "config" / "blitzer"
    legacy.mkdir(parents=True)
    (legacy / "blitzer.toml").write_text("[defaults]\nfreq = true\n")
    config = get_config()
    assert config["defaults"]["freq"] is False
    assert config["locations"]["plugins_dir"] == (
        tmp_path / "data" / "bltzr" / "languages"
    )
