"""Handle commands, user input and presentation of results.

Purpose
-------
Turn terminal arguments into calls to the application API, then present
results and errors in a format the user selected.

In scope
--------
- Click commands, flags, help and command-line argument validation.
- Reading explicit text, UTF-8 files or piped standard input.
- Interactive confirmations and the decision to save or preview data.
- Local/registered installation, explicit updates and pack packaging.
- Grouping reusable pack development commands under blitzer dev.
- Text, TSV, JSON and report output, including escaped word
  highlighting.
- Sending vocabulary to stdout and diagnostics to stderr.

Out of scope
------------
- Tokenization, normalization, filtering, counting and sorting
  algorithms.
- SQL queries, pack construction, locks and persistent data changes.
- Finding config files, resolving configured paths and parsing TOML.

Start here
----------
Read blitz for the main command's sequence. Formatting helpers are above
it; pack and known-list commands follow it. core.py provides the API,
processing.py implements text rules, and config.py owns configuration.
"""

import csv
import html
import io
import json
import re
import sqlite3
import sys
from contextlib import contextmanager
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

import click

from blitzer.config import FORMATS, MARKUPS, SORTS
from blitzer.core import BlitzerService, Context
from blitzer.downloads import REGISTRY

CONTEXT_SETTINGS = {"help_option_names": ["-h", "--help"]}

try:
    VERSION = version("bltzr")
except PackageNotFoundError:
    VERSION = "0.1.0"


@contextmanager
def _errors():
    """Translate expected errors into readable CLI failures."""
    try:
        yield
    except (OSError, ValueError, sqlite3.Error) as error:
        raise click.ClickException(str(error)) from error


def _service(config, no_config, plugins_dir):
    """Create a service from CLI configuration selections."""
    return BlitzerService(
        config, use_config=not no_config, plugins_dir=plugins_dir
    )


def _escape_markup(text: str, style: str) -> str:
    """Escape original text for the requested markup."""
    if style == "html":
        return html.escape(text)
    if style == "markdown":
        return re.sub(r"([\\`*_{}\[\]<>#|])", r"\\\1", text)
    if style == "org":
        return text.replace("\\", "\\\\").replace("*", r"\*")
    return text


def _highlight(context: Context, style: str) -> str:
    """Emphasize the flagged occurrence in escaped context.

    Off returns the original text. Rendering changes neither the context
    nor its offsets and does not read any external state.
    """
    if style == "off":
        return context.text
    start, end = context.highlight_start, context.highlight_end
    left = _escape_markup(context.text[:start], style)
    word = _escape_markup(context.text[start:end], style)
    right = _escape_markup(context.text[end:], style)
    opening, closing = {
        "html": ("<b>", "</b>"),
        "markdown": ("**", "**"),
        "org": ("*", "*"),
    }[style]
    return left + opening + word + closing + right


def _json_entry(entry, include_context) -> dict:
    """Return a JSON record with optional plain contexts."""
    record = {"term": entry.term, "count": entry.count}
    if entry.global_frequency is not None:
        record["global_frequency"] = entry.global_frequency
    if include_context:
        record["contexts"] = [
            {
                "text": item.text,
                "highlight_start": item.highlight_start,
                "highlight_end": item.highlight_end,
            }
            for item in entry.contexts
        ]
    return record


def _report_preamble(source, prompt) -> str:
    """Return report sections in their display order."""
    sections = []
    if prompt is not None:
        sections.append("PROMPT\n" + prompt + "\n\n")
    if source is not None:
        sections.append("SOURCE\n" + source + "\n\n")
    return "".join(sections) + "VOCABULARY\n"


def _vocabulary_row(entry, freq, context, bold) -> list:
    """Build a TSV row without changing vocabulary entries."""
    row = [entry.term]
    if freq:
        row.append(entry.count)
    if context:
        joiner = "<br>" if bold == "html" else " | "
        row.append(
            joiner.join(
                " ".join(_highlight(item, bold).split())
                for item in entry.contexts
            )
        )
    return row


def _render(entries, *, output_format, freq, context, bold, source, prompt):
    """Return formatted output without external writes.

    JSON always includes counts and keeps contexts unformatted. Text and
    TSV quote cells through csv.writer; report adds explicit text
    sections.
    """
    if output_format == "json":
        records = [_json_entry(entry, context) for entry in entries]
        return json.dumps(records, ensure_ascii=False, indent=2) + "\n"
    stream = io.StringIO(newline="")
    if output_format == "report":
        stream.write(_report_preamble(source, prompt))
    writer = csv.writer(stream, delimiter="\t", lineterminator="\n")
    if output_format == "tsv":
        writer.writerow(
            [
                "term",
                *(["count"] if freq else []),
                *(["context"] if context else []),
            ]
        )
    writer.writerows(
        _vocabulary_row(entry, freq, context, bold) for entry in entries
    )
    return stream.getvalue()


def _read_input(text, input_file) -> str:
    """Read explicit text, a UTF-8 file or piped stdin in that order."""
    if text is not None:
        return text
    if input_file is not None:
        return input_file.read_text(encoding="utf-8")
    if sys.stdin.isatty():
        raise click.UsageError(
            "Provide --text, --file, or pipe UTF-8 text to stdin"
        )
    return click.get_text_stream(
        "stdin", encoding="utf-8", errors="strict"
    ).read()


def _presentation_options(settings, **overrides) -> dict:
    """Resolve and validate display flags.

    Explicit non-None values override the supplied language settings.
    Prompt text is required only when a report requests a prompt
    section.
    """
    options = {
        name: settings[name] if value is None else value
        for name, value in overrides.items()
    }
    if (options["prompt"] or options["src"]) and options["format"] != "report":
        raise click.UsageError("--prompt and --src require --format report")
    options["prompt_text"] = (
        settings.get("prompt_text") if options["prompt"] else None
    )
    return options


def _should_save_contexts(policy, explicit, test_known) -> bool:
    """Resolve saving policy and any required prompt.

    Test mode suppresses all history writes. A pipeline must explicitly
    accept or decline a prompt policy so stdin remains vocabulary input.
    """
    if test_known:
        return False
    if explicit is not None:
        return explicit
    if policy != "prompt":
        return policy == "always"
    if not sys.stdin.isatty():
        raise click.UsageError(
            "Context saving asks for a prompt: specify --save-context "
            "or --no-save-context in a pipeline"
        )
    return click.confirm(
        "Save surviving vocabulary contexts?", default=False, err=True
    )


def _handle_known_update(
    service, language, entries, path, update, test_known, list_kind=None
):
    """Update or preview known terms and report to stderr."""
    if not update and not test_known:
        return
    change = service.update_known(
        language, entries, path=path, dry_run=test_known, list_kind=list_kind
    )
    action = "Would add" if test_known else "Added"
    click.echo(
        f"{action} {len(change.additions)} matched terms to {change.path}: "
        f"{', '.join(change.additions)}",
        err=True,
    )
    if update and not test_known:
        click.echo(
            "Warning: matched words are not evidence of knowledge; "
            "automatic known updating is discouraged.",
            err=True,
        )


def _handle_context_saving(service, language, entries, saving):
    """Save requested history and report to stderr."""
    if not saving:
        return
    count = service.save_contexts(language, entries)
    click.echo(f"Saved {count} new contexts.", err=True)


def _known_update_destination(
    settings, legacy_path, exact_file, family_file, update_list
):
    """Select the explicitly named update list, independently of display."""
    modern = exact_file is not None or family_file is not None or any(
        key in settings for key in ("skip_exact_words_file", "skip_word_families_file")
    )
    if not modern:
        return legacy_path, None
    kind = update_list or settings.get("update_list")
    if kind == "exact-words":
        return exact_file or settings.get("skip_exact_words_file"), kind
    return family_file or settings.get("skip_word_families_file"), kind


@click.group(context_settings=CONTEXT_SETTINGS)
@click.version_option(VERSION, "--version", "-V")
def cli():
    """Extract vocabulary using local data-only language packs."""


@cli.group("dev", hidden=True)
def dev():
    """Build, inspect and package dictionaries for development."""


@cli.command()
@click.option(
    "--language", "-l", required=True, help="Three-letter pack code, or base."
)
@click.option(
    "--text", "-t", help="Explicit text, overriding unrelated piped input."
)
@click.option(
    "--file",
    "-i",
    "input_file",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
)
@click.option(
    "--lemmatize/--no-lemmatize",
    "-L",
    default=None,
    help="Show basic words (lexeme/lemma): 'are' becomes 'be'; does not change what is skipped.",
)
@click.option(
    "--filter-by",
    "-F",
    type=click.Choice(["forms", "lemmas"]),
    hidden=True,
    help="What the known list excludes; independent of display.",
)
@click.option("--exclude-unknown/--include-unknown", "-x", default=None)
@click.option("--freq/--no-freq", "-f", default=None)
@click.option("--context/--no-context", "-c", default=None)
@click.option(
    "--exclude",
    "-e",
    "exclusions",
    multiple=True,
    hidden=True,
    type=click.Path(dir_okay=False, path_type=Path),
)
@click.option(
    "--exclude-forms",
    "-E",
    "forms_only",
    multiple=True,
    hidden=True,
    type=click.Path(dir_okay=False, path_type=Path),
)
@click.option("--show-all-words", "--no-exclusions", "-N", "no_exclusions", is_flag=True,
              help="Count words without applying either skip list; does not disable updates.")
@click.option(
    "--known-file",
    "-k",
    type=click.Path(dir_okay=False, path_type=Path),
    hidden=True,
    help="Primary known list; missing means initially empty.",
)
@click.option("--skip-exact-words-file", type=click.Path(dir_okay=False, path_type=Path),
              help="Skip only listed words (word form): 'be' and 'am' leave 'is' and 'are' counted.")
@click.option("--skip-word-families-file", type=click.Path(dir_okay=False, path_type=Path),
              help="Skip listed word families (lexeme/lemma): 'be' skips 'am', 'is', 'are', 'was', etc.")
@click.option("--update-list", type=click.Choice(["exact-words", "word-families"]),
              help="Choose which skip file receives additions with --update-known or --test-known.")
@click.option("--sort", "-S", type=click.Choice(SORTS))
@click.option(
    "--custom-order",
    "-O",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
)
@click.option(
    "--sentence-pattern",
    "-d",
    help="Regex matching sentence-ending delimiters (not empty boundaries).",
)
@click.option("--context-limit", "-m", type=click.IntRange(1, 20))
@click.option("--bold", "-b", type=click.Choice(MARKUPS))
@click.option("--format", "-o", "output_format", type=click.Choice(FORMATS))
@click.option("--prompt/--no-prompt", "-p", default=None,
              help="Include configured instructions in a report for copying elsewhere; no API calls.")
@click.option("--src/--no-src", "-s", default=None,
              help="Include original input in report output.")
@click.option(
    "--save-context/--no-save-context",
    "-H",
    default=None,
    help="Explicitly save/decline surviving contexts.",
)
@click.option(
    "--update-known/--no-update-known",
    "-u",
    default=None,
    help="Add matched words to the chosen --update-list; reading a word does not mean learning it.",
)
@click.option(
    "--test-known",
    "-T",
    is_flag=True,
    help=(
        "Preview additions to the chosen --update-list; "
        "write neither skip list nor history."
    ),
)
@click.option(
    "--config", "-C", type=click.Path(dir_okay=False, path_type=Path)
)
@click.option("--no-config", "-n", is_flag=True)
@click.option(
    "--plugins-dir", "-P", type=click.Path(file_okay=False, path_type=Path)
)
def blitz(
    language,
    text,
    input_file,
    lemmatize,
    filter_by,
    exclude_unknown,
    freq,
    context,
    exclusions,
    forms_only,
    no_exclusions,
    known_file,
    skip_exact_words_file,
    skip_word_families_file,
    update_list,
    sort,
    custom_order,
    sentence_pattern,
    context_limit,
    bold,
    output_format,
    prompt,
    src,
    save_context,
    update_known,
    test_known,
    config,
    no_config,
    plugins_dir,
):
    """Extract filtered vocabulary from input text."""
    if text is not None and input_file is not None:
        raise click.UsageError("Use either --text or --file, not both")
    with _errors():
        service = _service(config, no_config, plugins_dir)
        settings = service.settings(language)
        display = _presentation_options(
            settings,
            freq=freq,
            context=context,
            prompt=prompt,
            src=src,
            bold=bold,
            format=output_format,
        )
        if display["prompt"] and not display["prompt_text"]:
            raise ValueError(f"No prompt_text configured for {language}")
        text = _read_input(text, input_file)
        saving = _should_save_contexts(
            settings["save_context"], save_context, test_known
        )
        update = (
            settings["auto_update_known"]
            if update_known is None
            else update_known
        )
        entries = service.blitz(
            text,
            language,
            lemmatize=lemmatize,
            filter_by=filter_by,
            context=display["context"] or saving,
            exclude_unknown=exclude_unknown,
            exclusions=exclusions or None,
            forms_only=forms_only or None,
            no_exclusions=no_exclusions,
            known_file=known_file,
            skip_exact_words_file=skip_exact_words_file,
            skip_word_families_file=skip_word_families_file,
            update_list=update_list,
            sort=sort,
            custom_order=custom_order,
            sentence_pattern=sentence_pattern,
            context_limit=context_limit,
            track_known=update or test_known,
        )
        output = _render(
            entries,
            output_format=display["format"],
            freq=display["freq"],
            context=display["context"],
            bold=display["bold"],
            source=text if display["src"] else None,
            prompt=display["prompt_text"],
        )
        update_path, list_kind = _known_update_destination(
            settings, known_file, skip_exact_words_file,
            skip_word_families_file, update_list
        )
        _handle_known_update(
            service, language, entries, update_path, update, test_known, list_kind
        )
        _handle_context_saving(service, language, entries, saving)
        click.echo(output, nl=False)


@cli.command("list-languages")
@click.option(
    "--config", "-C", type=click.Path(dir_okay=False, path_type=Path)
)
@click.option("--no-config", "-n", is_flag=True)
@click.option(
    "--plugins-dir", "-P", type=click.Path(file_okay=False, path_type=Path)
)
def list_languages(config, no_config, plugins_dir):
    """List installed languages available for text processing."""
    with _errors():
        service = _service(config, no_config, plugins_dir)
        click.echo(
            "\n".join(
                f"{service.language_name(code)} ({code})"
                for code in service.list_languages()
            )
        )


@dev.command("check-plugin")
@click.argument("code")
@click.option(
    "--config", "-C", type=click.Path(dir_okay=False, path_type=Path)
)
@click.option("--no-config", "-n", is_flag=True)
@click.option(
    "--plugins-dir", "-P", type=click.Path(file_okay=False, path_type=Path)
)
def check_plugin(code, config, no_config, plugins_dir):
    """Report all validation checks for an installed pack."""
    with _errors():
        report = _service(config, no_config, plugins_dir).check_plugin(code)
        for item in report:
            click.echo(f"[{item.status.upper()}] {item.name}: {item.detail}")
        if any(x.status == "fail" for x in report):
            raise click.ClickException(f"Pack {code} failed validation")


@dev.command("build-plugin")
@click.argument(
    "source_dir", type=click.Path(exists=True, file_okay=False, path_type=Path)
)
@click.option(
    "--database",
    "-D",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="Import a compatible SQLite database instead of forms.tsv.",
)
@click.option(
    "--skip-orphans",
    "-A",
    is_flag=True,
    help="Explicitly omit/count SQLite source forms with missing lemma IDs.",
)
@click.option(
    "--skip-unsupported",
    "-U",
    is_flag=True,
    help=(
        "Explicitly omit unsupported multiword/symbol entries; "
        "count them in build-info.json."
    ),
)
@click.option(
    "--config", "-C", type=click.Path(dir_okay=False, path_type=Path)
)
@click.option("--no-config", "-n", is_flag=True)
@click.option(
    "--plugins-dir", "-P", type=click.Path(file_okay=False, path_type=Path)
)
def build_plugin(
    source_dir,
    database,
    skip_unsupported,
    skip_orphans,
    config,
    no_config,
    plugins_dir,
):
    """Build and validate a pack before publishing it."""
    with _errors():
        path = _service(config, no_config, plugins_dir).build_plugin(
            source_dir,
            source_database=database,
            skip_unsupported=skip_unsupported,
            skip_orphans=skip_orphans,
        )
        click.echo(str(path))
        click.echo(
            (path / "build-info.json").read_text(encoding="utf-8"),
            err=True,
            nl=False,
        )


@dev.command("expand-plugin")
@click.argument("code")
@click.argument(
    "additional", type=click.Path(exists=True, file_okay=False, path_type=Path)
)
@click.option("--pack-version", "-v", default="0.2.0", show_default=True)
@click.option(
    "--config", "-C", type=click.Path(dir_okay=False, path_type=Path)
)
@click.option("--no-config", "-n", is_flag=True)
@click.option(
    "--plugins-dir", "-P", type=click.Path(file_okay=False, path_type=Path)
)
def expand_plugin(
    code, additional, pack_version, config, no_config, plugins_dir
):
    """Expand a pack while preserving all existing dictionary pairs."""
    with _errors():
        service = _service(config, no_config, plugins_dir)
        stats = service.expand_plugin(code, additional, version=pack_version)
        click.echo(json.dumps(stats, indent=2))


@cli.command("install-plugin")
@click.argument("source", metavar="CODE_OR_DIRECTORY")
@click.option(
    "--replace",
    "-R",
    is_flag=True,
    help="Replace an installed pack with the selected version.",
)
@click.option(
    "--config", "-C", type=click.Path(dir_okay=False, path_type=Path)
)
@click.option("--no-config", "-n", is_flag=True)
@click.option(
    "--plugins-dir", "-P", type=click.Path(file_okay=False, path_type=Path)
)
def install_plugin(source, replace, config, no_config, plugins_dir):
    """Install a registered language or a local directory."""
    with _errors():
        if source in REGISTRY and not Path(source).is_dir():
            name = REGISTRY[source]["name"]
            click.echo(
                f"Downloading and validating {name} from GitHub...", err=True
            )
        click.echo(
            str(
                _service(config, no_config, plugins_dir).install_plugin(
                    source, replace=replace
                )
            )
        )


@dev.command("package-plugin")
@click.argument("code")
@click.option(
    "--output-dir",
    "-o",
    type=click.Path(file_okay=False, path_type=Path),
    default="release-assets",
    show_default=True,
)
@click.option(
    "--config", "-C", type=click.Path(dir_okay=False, path_type=Path)
)
@click.option("--no-config", "-n", is_flag=True)
@click.option(
    "--plugins-dir", "-P", type=click.Path(file_okay=False, path_type=Path)
)
def package_plugin(code, output_dir, config, no_config, plugins_dir):
    """Prepare a validated pack archive for publication."""
    with _errors():
        service = _service(config, no_config, plugins_dir)
        click.echo(str(service.package_plugin(code, output_dir)))


@cli.command("remove-plugin")
@click.argument("code")
@click.option(
    "--yes", "-y", is_flag=True, help="Skip the removal confirmation."
)
@click.option(
    "--config", "-C", type=click.Path(dir_okay=False, path_type=Path)
)
@click.option("--no-config", "-n", is_flag=True)
@click.option(
    "--plugins-dir", "-P", type=click.Path(file_okay=False, path_type=Path)
)
def remove_plugin(code, yes, config, no_config, plugins_dir):
    """Remove an installed language pack."""
    with _errors():
        service = _service(config, no_config, plugins_dir)
        # Validate before constructing a path or asking to remove it.
        service.settings(code)
        if not yes:
            click.confirm(
                f"Remove pack {service.plugins_dir / code}?",
                abort=True,
                err=True,
            )
        service.remove_plugin(code)
        click.echo(f"Removed {code}")


@cli.command("cleanup-known")
@click.argument("code")
@click.argument(
    "path", type=click.Path(exists=True, dir_okay=False, path_type=Path)
)
@click.option(
    "--apply",
    "-a",
    is_flag=True,
    help="Normalize/deduplicate in place, preserving PATH.bak.",
)
@click.option(
    "--config", "-C", type=click.Path(dir_okay=False, path_type=Path)
)
@click.option("--no-config", "-n", is_flag=True)
@click.option(
    "--plugins-dir", "-P", type=click.Path(file_okay=False, path_type=Path)
)
def cleanup_known(code, path, apply, config, no_config, plugins_dir):
    """Preview or apply known-list deduplication."""
    with _errors():
        result = _service(config, no_config, plugins_dir).cleanup_known(
            code, path, apply=apply
        )
        click.echo(json.dumps(result, ensure_ascii=False, indent=2))


@cli.command()
@click.argument("code")
@click.argument("term", required=False)
@click.option(
    "--limit", "-m", type=click.IntRange(1), default=100, show_default=True
)
@click.option(
    "--config", "-C", type=click.Path(dir_okay=False, path_type=Path)
)
@click.option("--no-config", "-n", is_flag=True)
@click.option(
    "--plugins-dir", "-P", type=click.Path(file_okay=False, path_type=Path)
)
def history(code, term, limit, config, no_config, plugins_dir):
    """Show saved sentences containing encountered words."""
    with _errors():
        click.echo(
            json.dumps(
                _service(config, no_config, plugins_dir).history(
                    code, term, limit=limit
                ),
                ensure_ascii=False,
                indent=2,
            )
        )


if __name__ == "__main__":
    cli()
