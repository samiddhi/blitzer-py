"""Verify direct exclusion checks for pipeline words and lemmas.

Purpose: make configured skip lists queryable without prose processing.
In scope: matching, legacy settings, list input/output and read-only behavior.
Out of scope: inflection resolution, downloads and real user data.
Start here: configured supplies small Slovenian lists and an isolated service.
"""

import json

import pytest

import blitzer.core as core
from blitzer.cli import cli
from blitzer.core import BlitzerService, ExclusionResult
from test_cli import make_runner


@pytest.fixture
def configured(service, tmp_path):
    (tmp_path / "exact.txt").write_text("# Exact spellings\nSEM\nmaček\nsem\n\n")
    (tmp_path / "families.txt").write_text("# Headwords\nBITI\nmaček\nnovobesedilo\n")
    config = tmp_path / "user.toml"
    config.write_text(
        '[languages.slv]\nskip_exact_words_file = "exact.txt"\n'
        'skip_word_families_file = "families.txt"\n'
    )
    return BlitzerService(config, language_packs_dir=service.plugins_dir), config


@pytest.mark.parametrize("match,expected", [
    ("lemma", [True, False, True, False, True]),
    ("form", [False, True, True, False, True]),
    ("both", [True, True, True, False, True]),
])
def test_modes_and_order(configured, match, expected):
    service, _ = configured
    words = ["BITI", "sem", "mac\u030cek", "jesti", "maček"]
    results = service.check_excluded(iter(words), "slv", match=match)
    assert [row.word for row in results] == words
    assert [row.excluded for row in results] == expected
    assert results[2].normalized == "maček"
    if match == "both":
        assert results[2].matched_lists == ("exact-words", "word-families")
    assert all(isinstance(row, ExclusionResult) for row in results)


def test_lemma_inputs_are_not_lemmatized_or_dictionary_checked(configured):
    service, _ = configured
    results = service.check_excluded(["biti", "sem", "smo", "novobesedilo"], "slv", match="lemma")
    assert [row.excluded for row in results] == [True, False, False, True]


def test_selected_lists_only_and_strict_missing_policy(configured):
    service, config = configured
    exact = config.parent / "exact.txt"
    exact.unlink()
    assert service.check_excluded(["biti"], "slv", match="lemma")[0].excluded
    for words in ([], ["biti"]):
        with pytest.raises(FileNotFoundError):
            service.check_excluded(words, "slv")
    exact.mkdir()
    with pytest.raises(OSError):
        service.check_excluded(["sem"], "slv", match="form")


def test_selected_malformed_file_and_unsupported_input(configured):
    service, config = configured
    (config.parent / "exact.txt").write_text("sem\ntwo words\n")
    with pytest.raises(ValueError, match=r"exact.txt:2:"):
        service.check_excluded([], "slv", match="form")
    assert service.check_excluded([], "slv", match="lemma") == []


def test_permission_errors_propagate_only_for_selected_lists(configured, monkeypatch):
    service, config = configured
    path_type = type(config)
    read_text = path_type.read_text

    def protected(path, *args, **kwargs):
        if path == config.parent / "exact.txt":
            raise PermissionError(f"Cannot read {path}")
        return read_text(path, *args, **kwargs)

    monkeypatch.setattr(path_type, "read_text", protected)
    assert service.check_excluded(["biti"], "slv", match="lemma")[0].excluded
    with pytest.raises(PermissionError):
        service.check_excluded(["sem"], "slv", match="form")


def test_substitutions_apply_to_inputs_and_exclusions(configured):
    service, _ = configured
    config = service.plugins_dir / "slv" / "config.toml"
    config.write_text(config.read_text().replace(
        "substitutions = []", 'substitutions = [{from="č", to="c"}]'
    ))
    result = service.check_excluded(["MAČEK", "macek"], "slv", match="lemma")
    assert [row.normalized for row in result] == ["macek", "macek"]
    assert all(row.excluded for row in result)


@pytest.mark.parametrize("filter_by,mode,expected", [
    ("forms", "lemma", [False, False, False]),
    ("forms", "form", [True, True, True]),
    ("lemmas", "lemma", [True, True, False]),
    ("lemmas", "form", [False, False, True]),
    ("lemmas", "both", [True, True, True]),
])
def test_legacy_category_mapping(service, tmp_path, filter_by, mode, expected):
    for filename, text in (("known", "biti"), ("exclude", "jesti"), ("forms", "sem")):
        (tmp_path / filename).write_text(text)
    config = tmp_path / "legacy.toml"
    config.write_text(
        f'[defaults]\nfilter_by="{filter_by}"\n[languages.slv]\n'
        'known_file="known"\nexclusions=["exclude"]\nforms_only=["forms"]\n'
    )
    selected = BlitzerService(config, language_packs_dir=service.plugins_dir)
    assert [row.excluded for row in selected.check_excluded(["biti", "jesti", "sem"], "slv", match=mode)] == expected


def test_empty_unset_lists_and_invalid_arguments(service):
    assert service.check_excluded([], "slv") == []
    assert not service.check_excluded(["biti"], "slv")[0].excluded
    for words in ("biti", b"biti", None, 42, [None], [""], [" "], ["two words"], ["sem!"]):
        with pytest.raises(ValueError):
            service.check_excluded(words, "slv")
    with pytest.raises(ValueError, match="match"):
        service.check_excluded([], "slv", match="unknown")
    with pytest.raises(ValueError):
        service.check_excluded([], "../slv")
    with pytest.raises(OSError):
        service.check_excluded([], "pol")


def test_base_and_hyphenated_list_entries(tmp_path):
    words = tmp_path / "exact.txt"
    words.write_text("sally-anne\n")
    config = tmp_path / "base.toml"
    config.write_text('[languages.base]\nskip_exact_words_file="exact.txt"\n')
    service = BlitzerService(config)
    assert service.check_excluded(["Sally-Anne"], "base")[0].excluded


def test_read_once_no_database_or_writes(configured, monkeypatch, capsys):
    service, config = configured
    config.write_text('[languages.slv]\nexclusions=["exact.txt", "exact.txt"]\nknown_file="exact.txt"\n')
    service = BlitzerService(config, language_packs_dir=service.plugins_dir)
    (service.plugins_dir / "slv" / "lemmas.db").unlink()
    service.config["defaults"].update({
        "lemmatize": True, "sort": "custom", "custom_order": "/missing/order",
        "auto_update_known": True, "save_context": "always",
    })
    before = {path: path.read_bytes() for path in config.parent.glob("*.txt")}
    calls = []
    read_terms = core._read_terms

    def track(path, normal, **kwargs):
        calls.append(path)
        return read_terms(path, normal, **kwargs)

    def forbidden(*args, **kwargs):
        pytest.fail("exclusion checks must only read configuration and selected lists")

    monkeypatch.setattr(core, "_read_terms", track)
    monkeypatch.setattr(core, "_read_only", forbidden)
    monkeypatch.setattr(core, "tokenize", forbidden)
    monkeypatch.setattr(core, "download_pack", forbidden)
    service.check_excluded(["sem", "sem"], "slv")
    assert calls == [config.parent / "exact.txt"]
    assert {path: path.read_bytes() for path in before} == before
    assert not service.config["locations"]["history_file"].exists()
    assert capsys.readouterr() == ("", "")


def test_modern_list_categories_ignore_legacy_default(configured):
    service, _ = configured
    service.config["defaults"]["filter_by"] = "lemmas"
    assert service.check_excluded(["sem"], "slv", match="form")[0].excluded
    assert not service.check_excluded(["sem"], "slv", match="lemma")[0].excluded


def invoke(configured, *args, **kwargs):
    service, config = configured
    return make_runner().invoke(cli, [
        "check-excluded", "-C", str(config), "-P", str(service.plugins_dir),
        "-l", "slv", *args,
    ], **kwargs)


def test_cli_status_and_filter_outputs(configured):
    result = invoke(configured, "biti", "sem", "jesti", "jesti", "--match", "lemma")
    assert result.exit_code == 0, result.output
    assert result.stdout == "biti\ttrue\nsem\tfalse\njesti\tfalse\njesti\tfalse\n"
    result = invoke(configured, "--match", "lemma", "--output", "remaining", input="biti\nsem\njesti\njesti\n")
    assert result.exit_code == 0, result.output
    assert result.stdout == "sem\njesti\njesti\n"
    result = invoke(configured, "biti", "sem", "--output", "excluded")
    assert result.exit_code == 0
    assert result.stdout == "biti\nsem\n"
    result = invoke(configured, "biti", "--output", "remaining")
    assert result.exit_code == 0 and result.stdout == ""


@pytest.mark.parametrize("output,expected", [("status", ["BITI", "jesti"]), ("excluded", ["BITI"]), ("remaining", ["jesti"])])
def test_cli_json(configured, output, expected):
    result = invoke(configured, "BITI", "jesti", "--format", "json", "--output", output)
    assert result.exit_code == 0, result.output
    value = json.loads(result.stdout)
    assert value["language"] == "slv" and value["match"] == "both" and value["output"] == output
    assert [row["word"] for row in value["results"]] == expected
    if output != "remaining":
        assert value["results"][0] == {"word": "BITI", "normalized": "biti", "excluded": True, "matched_lists": ["word-families"]}


def test_cli_file_stdin_precedence_and_empty_input(configured, tmp_path):
    source = tmp_path / "input.txt"
    source.write_text("\n  BITI  \n\n jesti\n")
    result = invoke(configured, "--file", str(source), input="sem\n")
    assert result.exit_code == 0
    assert result.stdout == "BITI\ttrue\njesti\tfalse\n"
    result = invoke(configured, "jesti", input="biti\n")
    assert result.exit_code == 0 and result.stdout == "jesti\tfalse\n"
    result = invoke(configured, input="\n  \n")
    assert result.exit_code == 0 and result.stdout == ""
    result = invoke(configured, "--format", "json", input="")
    assert result.exit_code == 0 and json.loads(result.stdout)["results"] == []
    assert invoke(configured, "biti", "--file", str(source)).exit_code == 2


def test_cli_errors_no_partial_output_and_source_lines(configured, tmp_path):
    source = tmp_path / "bad.txt"
    source.write_text("biti\n\ntwo words\n")
    for args, stdin, label in ((["--file", str(source)], None, str(source)), ([], source.read_text(), "stdin")):
        result = invoke(configured, *args, input=stdin)
        assert result.exit_code == 1
        assert result.stdout == ""
        assert f"{label}:3:" in result.stderr
    assert invoke(configured, "biti", "--match", "invalid").exit_code == 2
    _, config = configured
    (config.parent / "families.txt").unlink()
    result = invoke(configured, "biti")
    assert result.exit_code == 1 and result.stdout == ""


def test_cli_no_config_and_capability(configured):
    service, _ = configured
    result = make_runner().invoke(cli, [
        "check-excluded", "-n", "-P", str(service.plugins_dir), "-l", "slv", "biti",
    ])
    assert result.exit_code == 0 and result.stdout == "biti\tfalse\n"
    assert invoke(configured, "biti", "-n").exit_code == 1
    caps = make_runner().invoke(cli, ["capabilities"])
    assert json.loads(caps.stdout)["exclusion_checks"] == 1
