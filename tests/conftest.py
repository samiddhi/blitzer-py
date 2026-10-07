"""Provide isolated environments and reusable small pack fixtures.

Purpose
-------
Give every test temporary user-data locations and provide a tiny,
predictable language pack when a test needs a real database.

In scope
--------
- Redirecting config/data roots and clearing config-file environment
  state.
- Creating synthetic Slovenian mappings with intentional ambiguity.
- Supplying synthetic frequencies and a service with a built test pack.

Out of scope
------------
- Test assertions about processing, commands or configuration behavior.
- Reading real user data, importing the large pack or using the network.
- Production defaults and application startup.

Start here
----------
Read isolated_environment for test isolation, source for fixture data,
and service for the populated API fixture. The test files contain
checks.
"""

import pytest

from blitzer.core import BlitzerService

PACK_CONFIG = """format_version = 1
[metadata]
language_name = "Slovenian"
language_code = "slv"
version = "0.1.0"
author = "Samiddhi"
[normalization]
lowercase = true
substitutions = []
"""


@pytest.fixture(autouse=True)
def isolated_environment(tmp_path, monkeypatch):
    """Isolate user config and data paths for each test."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.delenv("BLITZER_CONFIG", raising=False)


@pytest.fixture
def source(tmp_path):
    """Create a small pack with ambiguity and synthetic frequencies."""
    source = tmp_path / "source"
    source.mkdir()
    (source / "config.toml").write_text(PACK_CONFIG, encoding="utf-8")
    (source / "forms.tsv").write_text(
        "form\tlemma\nje\tbiti\nje\tjesti\nje\ton\nje\tbiti\n"
        "sem\tbiti\nsmo\tbiti\nmačka\tmaček\n",
        encoding="utf-8",
    )
    (source / "frequencies.tsv").write_text(
        "term\tfrequency\non\t100\njesti\t5\nbiti\t20\n", encoding="utf-8"
    )
    return source


@pytest.fixture
def service(tmp_path, source):
    """Build a test pack and return its configured API service."""
    result = BlitzerService(use_config=False, plugins_dir=tmp_path / "packs")
    result.build_plugin(source)
    return result
