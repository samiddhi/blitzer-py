"""Verify dictionary membership through the public service and CLI.

Purpose: distinguish headwords from forms using small offline packs.
In scope: normalization, batch behavior, failures and read-only resources.
Out of scope: prose processing, downloads and real user dictionaries.
Start here: the shared service fixture provides ambiguous Slovenian forms.
"""

import json
import sqlite3
from contextlib import closing

import pytest
from click.testing import CliRunner

import blitzer.core as core
from blitzer.cli import cli
from blitzer.core import BlitzerService


@pytest.mark.parametrize("match,expected", [
    ("lemma", [False, True, False, False, True]),
    ("form", [True, True, True, False, True]),
    ("both", [True, True, True, False, True]),
])
def test_membership_modes(service, match, expected):
    words = ["sem", "biti", "je", "xyzzy", "BITI"]
    assert service.contains_many(iter(words), "slv", match=match) == expected
    assert [service.contains(word, "slv", match=match) for word in words] == expected


def test_normalized_lemma_collisions(service):
    database = service.plugins_dir / "slv" / "lemmas.db"
    with closing(sqlite3.connect(database)) as conn:
        conn.execute("INSERT INTO lemmas(lemma) VALUES ('MAČEK')")
        lemma_id = conn.execute("SELECT id FROM lemmas WHERE lemma='MAČEK'").fetchone()[0]
        conn.execute("INSERT INTO forms(form_representation,lemma_id) VALUES ('maček', ?)", (lemma_id,))
        conn.commit()
    assert service.contains("MAC\u030cEK", "slv", match="lemma")
    assert service.contains("mac\u030cka", "slv", match="form")
    assert not service.contains("mačka", "slv", match="lemma")


def test_pack_substitutions_and_case_sensitive_lemmas(service):
    config = service.plugins_dir / "slv" / "config.toml"
    config.write_text(config.read_text().replace(
        "substitutions = []", 'substitutions = [{from = "č", to = "c"}]'
    ))
    database = service.plugins_dir / "slv" / "lemmas.db"
    with closing(sqlite3.connect(database)) as conn:
        conn.execute("UPDATE forms SET form_representation=replace(form_representation, 'č', 'c')")
        conn.commit()
    assert service.contains("MAČEK", "slv", match="lemma")
    assert service.contains("macek", "slv", match="lemma")
    config.write_text(config.read_text().replace("lowercase = true", "lowercase = false"))
    assert service.contains("macek", "slv", match="lemma")
    assert not service.contains("MACEK", "slv", match="lemma")


@pytest.mark.parametrize("profile,word", [("tone-hyphen", "ka²-na³"), ("sudachi", "日本語"), ("unavailable", "日本語")])
def test_direct_lookup_uses_pack_profile_without_analyzer(service, monkeypatch, profile, word):
    config = service.plugins_dir / "slv" / "config.toml"
    config.write_text(config.read_text().replace("format_version = 1", "format_version = 2")
                      + f'\n[tokenization]\nprofile = "{profile}"\n')
    database = service.plugins_dir / "slv" / "lemmas.db"
    with closing(sqlite3.connect(database)) as conn:
        conn.execute("INSERT INTO lemmas(lemma) VALUES (?)", (word,))
        lemma_id = conn.execute("SELECT id FROM lemmas WHERE lemma=?", (word,)).fetchone()[0]
        conn.execute("INSERT INTO forms(form_representation,lemma_id) VALUES (?,?)", (word, lemma_id))
        conn.commit()

    def forbidden(*args, **kwargs):
        pytest.fail("direct lookup must not initialize a prose analyzer")

    import blitzer.tokenization as tokenization
    monkeypatch.setattr(tokenization, "_japanese_tokenizer", forbidden)
    assert service.contains(word, "slv", match="lemma")


def test_batch_reuses_queries_and_closes_connection(service, monkeypatch, capsys):
    opened, queries = [], []
    original = core._read_only

    def track(path):
        conn = original(path)
        conn.set_trace_callback(queries.append)
        opened.append(conn)
        return conn

    monkeypatch.setattr(core, "_read_only", track)
    database = service.plugins_dir / "slv" / "lemmas.db"
    before = database.read_bytes()
    assert service.contains_many(["sem", "xyzzy", "SEM", "sem"], "slv") == [True, False, True, True]
    assert len(opened) == 1
    assert sum("SELECT DISTINCT l.lemma" in query for query in queries) == 2
    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        opened[0].execute("SELECT 1")
    assert database.read_bytes() == before
    assert capsys.readouterr() == ("", "")


@pytest.mark.parametrize("word", ["", " ", "sem smo", "sem!", None, 12])
def test_invalid_words_raise(service, word):
    with pytest.raises(ValueError):
        service.contains(word, "slv")


def test_invalid_batch_and_language(service):
    for words in ("sem", b"sem", None, 12):
        with pytest.raises(ValueError):
            service.contains_many(words, "slv")
    with pytest.raises(ValueError, match="match"):
        service.contains("sem", "slv", match="invalid")
    for code in ("base", "../slv", "SLV"):
        with pytest.raises(ValueError):
            service.contains("sem", code)
    with pytest.raises(OSError):
        service.contains("sem", "pol")
    assert service.contains_many([], "slv") == []


def test_missing_and_corrupt_databases_raise_even_for_empty_batch(service):
    database = service.plugins_dir / "slv" / "lemmas.db"
    database.write_bytes(b"not sqlite")
    with pytest.raises(sqlite3.Error):
        service.contains_many([], "slv")
    database.unlink()
    with pytest.raises(sqlite3.Error):
        service.contains("sem", "slv")
    assert not database.exists()


def test_failure_closes_connection(service, monkeypatch):
    opened = []
    original = core._read_only

    def track(path):
        conn = original(path)
        opened.append(conn)
        return conn

    with closing(sqlite3.connect(service.plugins_dir / "slv" / "lemmas.db")) as conn:
        conn.execute("PRAGMA user_version=99")
    monkeypatch.setattr(core, "_read_only", track)
    with pytest.raises(ValueError, match="version"):
        service.contains("sem", "slv")
    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        opened[0].execute("SELECT 1")


def test_membership_ignores_vocabulary_settings(service, monkeypatch):
    service.config["languages"]["slv"] = {
        "skip_exact_words_file": "/missing/words.txt",
        "exclusions": ["/missing/exclusions.txt"],
        "lemmatize": True,
        "sort": "global-frequency",
    }

    def forbidden(*args, **kwargs):
        pytest.fail("membership must not process prose or download data")

    monkeypatch.setattr(core, "tokenize", forbidden)
    monkeypatch.setattr(core, "download_pack", forbidden)
    assert service.contains("sem", "slv")


def test_bundled_english_and_override(service, tmp_path):
    root = tmp_path / "absent"
    fresh = BlitzerService(use_config=False, language_packs_dir=root)
    assert fresh.contains("dogs", "eng", match="form")
    assert fresh.contains("dog", "eng", match="lemma")
    assert not root.exists()
    pack = service.plugins_dir / "slv"
    pack.rename(service.plugins_dir / "eng")
    config = service.plugins_dir / "eng" / "config.toml"
    config.write_text(config.read_text().replace('"slv"', '"eng"'))
    assert service.contains("sem", "eng")
    assert not service.contains("dogs", "eng")


def test_membership_cli(service):
    runner = CliRunner()
    args = ["check-word", "-n", "-P", str(service.plugins_dir), "-l", "slv"]
    result = runner.invoke(cli, [*args, "sem", "biti", "xyzzy"])
    assert result.exit_code == 0
    assert result.output == "sem\ttrue\nbiti\ttrue\nxyzzy\tfalse\n"
    result = runner.invoke(cli, [*args, "sem", "biti", "biti", "--match", "lemma", "--format", "json"])
    assert result.exit_code == 0
    assert json.loads(result.output) == {
        "language": "slv", "match": "lemma",
        "results": [{"word": "sem", "found": False}, {"word": "biti", "found": True}, {"word": "biti", "found": True}],
    }
    result = runner.invoke(cli, [*args, "xyzzy"])
    assert result.exit_code == 0
    for suffix in ([], ["sem", "--match", "invalid"]):
        assert runner.invoke(cli, [*args, *suffix]).exit_code == 2
    result = runner.invoke(cli, [*args, "sem", "two words"])
    assert result.exit_code == 1
    assert "sem\ttrue" not in result.output
    assert runner.invoke(cli, ["check-word", "-n", "-l", "base", "sem"]).exit_code == 1
    assert json.loads(runner.invoke(cli, ["capabilities"]).output)["dictionary_membership"] == 1
