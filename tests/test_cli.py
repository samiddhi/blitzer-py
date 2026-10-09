"""Check commands, terminal output and explicit user decisions.

Purpose
-------
Verify what a user experiences when running Blitzer through Click,
including its input rules, output formats and mutation flags.

In scope
--------
- Help, explicit text, UTF-8 files, piped input and usage errors.
- Vocabulary stdout, diagnostic stderr, exit codes and empty results.
- Escaped highlighting, TSV/JSON output and report sections.
- Config overrides, saving policies, dry runs and confirmation behavior.
- Pack and known-list command integration with temporary data.

Out of scope
------------
- Implementing processing rules or production formatting helpers.
- Testing algorithms independently: test_functions.py.
- Exhaustive database and storage behavior: test_core.py.
- Using real user data, large source packs or network services.

Start here
----------
make_runner handles Click-version differences in captured stderr.
invoke runs commands against the temporary service from conftest.py.
The remaining functions exercise user-facing command behavior.
"""

import csv
import io
import inspect
import pytest

import json

from click.testing import CliRunner

from blitzer.cli import cli


def make_runner():
    # Click 8.1 needs separate stderr enabled explicitly.
    # Newer versions separate it automatically.
    """Create a Click runner with separately captured diagnostics."""
    options = (
        {"mix_stderr": False}
        if "mix_stderr" in inspect.signature(CliRunner).parameters
        else {}
    )
    return CliRunner(**options)


def invoke(service, *args, **kwargs):
    """Run the CLI against the supplied test service and options."""
    return make_runner().invoke(
        cli,
        [
            "blitz",
            "--no-config",
            "--plugins-dir",
            str(service.plugins_dir),
            "-l",
            "slv",
            *args,
        ],
        **kwargs,
    )


def test_help_and_input_rules():
    """Check help, piped input and explicit text selection."""
    runner = make_runner()
    result = runner.invoke(cli, ["--help"])
    assert result.exit_code == 0
    assert set(cli.commands) == {
        "blitz",
        "cleanup-known",
        "dev",
        "history",
        "install-plugin",
        "list-languages",
        "list-available-languages",
        "config",
        "conf",
        "remove-plugin",
    }
    assert "build-unimorph" not in result.output
    assert "  dev " not in result.output
    result = runner.invoke(cli, ["dev", "--help"])
    assert result.exit_code == 0
    assert set(cli.commands["dev"].commands) == {
        "build-plugin",
        "check-plugin",
        "expand-plugin",
        "package-plugin",
    }
    result = runner.invoke(
        cli,
        ["blitz", "--no-config", "-l", "base", "--freq"],
        input="Cat cat dog",
    )
    assert result.exit_code == 0
    assert result.stdout == "cat\t2\ndog\t1\n"
    result = runner.invoke(
        cli, ["blitz", "--no-config", "-l", "base", "-t", ""]
    )
    assert result.exit_code == 1
    assert result.stdout == ""


def test_forms_lemma_filter_context_highlights(service, tmp_path):
    """Check CLI markup highlights only surviving unknown forms."""
    known = tmp_path / "known.txt"
    known.write_text("sem")
    for style, marker in (
        ("html", "<b>Smo</b>"),
        ("markdown", "**Smo**"),
        ("org", "*Smo*"),
        ("off", "Smo"),
    ):
        result = invoke(
            service,
            "-t",
            "Sem. Smo!",
            "--lemmatize",
            "--context",
            "--known-file",
            str(known),
            "--bold",
            style,
        )
        assert result.exit_code == 0, result.output
        assert marker in result.stdout
        assert "Sem" not in result.stdout
    known.write_text("biti")
    result = invoke(
        service,
        "-t",
        "Sem smo",
        "--filter-by",
        "lemmas",
        "--known-file",
        str(known),
    )
    assert result.exit_code == 0
    assert result.stdout == ""


def test_html_escape_and_tsv_json_roundtrip(service):
    """Check HTML escaping and structured output preserve context."""
    result = invoke(
        service,
        "-t",
        "<script>Je</script>.",
        "--lemmatize",
        "--context",
        "--format",
        "tsv",
    )
    assert result.exit_code == 0, result.output
    rows = list(csv.reader(io.StringIO(result.stdout), delimiter="\t"))
    assert rows[0] == ["term", "context"]
    assert "&lt;script&gt;" in result.stdout
    assert "<script>" not in result.stdout
    result = invoke(
        service, "-t", "Je je.", "--lemmatize", "--freq", "--format", "json"
    )
    assert [x["count"] for x in json.loads(result.stdout)] == [2, 2, 2]
    assert result.stderr == ""


def test_report_only_headers_and_negative_config(tmp_path):
    """Check report headers and explicit negative flag overrides."""
    config = tmp_path / "config.toml"
    config.write_text(
        '[defaults]\nfreq=true\nprompt=true\nformat="report"\n'
        '[languages.base]\nprompt_text="Learn these"\n'
    )
    runner = make_runner()
    result = runner.invoke(
        cli,
        [
            "blitz",
            "--config",
            str(config),
            "-l",
            "base",
            "-t",
            "CAT",
            "--no-freq",
            "--src",
        ],
    )
    assert result.exit_code == 0, result.output
    assert (
        result.stdout
        == "PROMPT\nLearn these\n\nSOURCE\nCAT\n\nVOCABULARY\ncat\n"
    )
    result = runner.invoke(
        cli,
        [
            "blitz",
            "--config",
            str(config),
            "-l",
            "base",
            "-t",
            "CAT",
            "--format",
            "json",
        ],
    )
    assert result.exit_code == 2
    assert result.stdout == ""


def test_known_test_has_no_side_effects(service, tmp_path):
    """Check known-list test mode suppresses all persistent writes."""
    known = tmp_path / "new" / "known.txt"
    result = invoke(
        service,
        "-t",
        "Sem Smo xyzzy",
        "--known-file",
        str(known),
        "--test-known",
        "--save-context",
    )
    assert result.exit_code == 0, result.output
    assert "Would add 2" in result.stderr
    assert not known.parent.exists()
    assert not service.config["locations"]["history_file"].exists()


def test_explicit_known_update_and_history(service, tmp_path):
    """Check explicit updates and context saving report to stderr."""
    known = tmp_path / "known.txt"
    result = invoke(
        service,
        "-t",
        "Smo!",
        "--known-file",
        str(known),
        "--update-known",
        "--save-context",
    )
    assert result.exit_code == 0, result.output
    assert known.read_text() == "smo\n"
    assert "discouraged" in result.stderr
    assert service.history("slv", "smo")[0]["text"] == "Smo!"


def test_history_prompt_requires_explicit_pipe_decision(service, tmp_path):
    """Check pipelines cannot consume vocabulary input as a prompt."""
    config = tmp_path / "config.toml"
    config.write_text('[defaults]\nsave_context="prompt"\n')
    result = make_runner().invoke(
        cli,
        [
            "blitz",
            "--config",
            str(config),
            "--plugins-dir",
            str(service.plugins_dir),
            "-l",
            "slv",
        ],
        input="Smo!",
    )
    assert result.exit_code == 2
    assert result.stdout == ""


def test_no_partial_output_on_failure(service):
    """Check processing failures leave vocabulary stdout empty."""
    (service.plugins_dir / "slv" / "lemmas.db").write_bytes(b"not sqlite")
    result = invoke(service, "-t", "Je", "--lemmatize")
    assert result.exit_code == 1
    assert result.stdout == ""
    assert "Error:" in result.stderr


def test_management_commands(service, source, tmp_path):
    """Check build, list, validate and remove CLI operations."""
    runner = make_runner()
    root = str(tmp_path / "installed")
    result = runner.invoke(
        cli,
        [
            "install-plugin",
            str(service.plugins_dir / "slv"),
            "--no-config",
            "--plugins-dir",
            root,
        ],
    )
    assert result.exit_code == 0, result.output
    result = runner.invoke(
        cli,
        ["dev", "check-plugin", "slv", "--no-config", "--plugins-dir", root],
    )
    assert result.exit_code == 0, result.output
    result = runner.invoke(
        cli,
        [
            "remove-plugin",
            "slv",
            "--yes",
            "--no-config",
            "--plugins-dir",
            root,
        ],
    )
    assert result.exit_code == 0, result.output
    result = runner.invoke(
        cli, ["list-languages", "--no-config", "--plugins-dir", root]
    )
    assert result.stdout == "Basic (base)\nEnglish (eng)\n"


def test_configured_saving_policies_and_override(service, tmp_path):
    """Check saving policy and explicit overrides across invocations."""
    config = tmp_path / "user.toml"
    config.write_text(
        f'[locations]\nplugins_dir="{service.plugins_dir}"\n'
        'history_file="history.db"\n[defaults]\nsave_context="always"\n'
    )
    runner = make_runner()
    result = runner.invoke(
        cli,
        [
            "blitz",
            "--config",
            str(config),
            "-l",
            "slv",
            "-t",
            "Smo!",
            "--no-save-context",
        ],
    )
    assert result.exit_code == 0
    assert not (tmp_path / "history.db").exists()
    result = runner.invoke(
        cli, ["blitz", "--config", str(config), "-l", "slv", "-t", "Smo!"]
    )
    assert result.exit_code == 0
    assert "Saved 1" in result.stderr
    assert (tmp_path / "history.db").exists()
    assert "<b>" not in result.stdout


def test_invalid_utf8_file_and_input_conflict(service, tmp_path):
    """Check invalid UTF-8 and conflicting input flags fail clearly."""
    path = tmp_path / "bad.txt"
    path.write_bytes(b"\xff")
    result = invoke(service, "--file", str(path))
    assert result.exit_code == 1
    assert result.stdout == ""
    result = invoke(service, "--file", str(path), "-t", "Je")
    assert result.exit_code == 2


def test_empty_results_all_formats(service):
    """Check each output format handles empty vocabulary."""
    for fmt, expected in (
        ("text", ""),
        ("tsv", "term\n"),
        ("json", "[]\n"),
        ("report", "VOCABULARY\n"),
    ):
        result = invoke(service, "-t", "...!", "--format", fmt)
        assert result.exit_code == 0, result.output
        assert result.stdout == expected


def test_language_listing_uses_metadata_names(service):
    """Check installed and bundled packs display names with codes."""
    result = make_runner().invoke(
        cli,
        [
            "list-languages", "--no-config", "--plugins-dir",
            str(service.plugins_dir),
        ],
    )
    assert result.exit_code == 0, result.output
    assert result.stdout == (
        "Basic (base)\nEnglish (eng)\nSlovenian (slv)\n"
    )



def test_available_languages_offline_and_sorted(monkeypatch, tmp_path):
    """The bundled registry works without config, installed packs or HTTP."""
    from blitzer.downloads import REGISTRY
    import urllib.request
    def reject_network(*args, **kwargs):
        raise AssertionError("Network access during offline listing")
    monkeypatch.setattr(urllib.request.OpenerDirector, "open", reject_network)
    monkeypatch.setenv("BLITZER_CONFIG", str(tmp_path / "missing.toml"))
    result = make_runner().invoke(cli, ["list-available-languages"])
    assert result.exit_code == 0, result.output
    lines = result.stdout.splitlines()
    assert lines == sorted(lines, key=str.casefold)
    assert set(lines) == {"Basic (base)", "English (eng)"} | {
        f'{entry["name"]} ({code})' for code, entry in REGISTRY.items()
    }
    assert not list(tmp_path.iterdir())


def test_installed_languages_sorted_by_pack_name(service, monkeypatch):
    """Sort displayed pack names, including user metadata overrides."""
    path = service.language_packs_dir / "slv/config.toml"
    path.write_text(path.read_text().replace('language_name = "Slovenian"',
                                             'language_name = "Aardvark"'))
    assert service.list_languages() == ["slv", "base", "eng"]
    result = make_runner().invoke(cli, [
        "list-languages", "-n", "--language-packs-dir", str(service.language_packs_dir)
    ])
    assert result.exit_code == 0, result.output
    assert result.stdout == "Aardvark (slv)\nBasic (base)\nEnglish (eng)\n"


@pytest.mark.parametrize("command", ["config", "conf"])
def test_config_editor_creates_then_preserves_config(command, monkeypatch):
    from blitzer.config import config_path, get_config
    path = config_path()
    opened = []
    monkeypatch.setattr("blitzer.cli.click.edit", lambda **kwargs: opened.append(kwargs))
    runner = make_runner()
    result = runner.invoke(cli, [command])
    assert result.exit_code == 0, result.output
    assert opened == [{"filename": str(path)}]
    assert get_config()["defaults"]["lemmatize"] is False
    path.write_text("# preserve comments\n[defaults]\nfreq=true\n")
    result = runner.invoke(cli, [command])
    assert result.exit_code == 0
    assert path.read_text() == "# preserve comments\n[defaults]\nfreq=true\n"


def test_config_editor_selection_and_failure(tmp_path, monkeypatch):
    env = tmp_path / "env.toml"
    explicit = tmp_path / "nested/explicit.toml"
    monkeypatch.setenv("BLITZER_CONFIG", str(env))
    opened = []
    monkeypatch.setattr("blitzer.cli.click.edit", lambda **kwargs: opened.append(kwargs))
    runner = make_runner()
    assert runner.invoke(cli, ["conf"]).exit_code == 0
    assert runner.invoke(cli, ["config", "-C", str(explicit)]).exit_code == 0
    assert opened == [{"filename": str(env)}, {"filename": str(explicit)}]
    def fail_editor(**kwargs):
        raise OSError("Editor failed")
    monkeypatch.setattr("blitzer.cli.click.edit", fail_editor)
    result = runner.invoke(cli, ["config"])
    assert result.exit_code == 1
    assert "Editor failed" in result.stderr
