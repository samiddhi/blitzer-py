# Blitzer Python implementation plan

Reviewed against the local projects on 2026-10-07.

Build a readable vocabulary-extraction tool using Python and Click, with
Anchor's package structure and public-service pattern. A reader should be
able to follow a command into one service method and then into a few
ordinary functions. The priority is understandable, correct behavior.

The project is implemented. This file retains the original design sequence;
README.org documents the delivered commands and configuration. The additions
below incorporate the later requested vision and supersede conflicting parts
of the initial plan (especially the default exclusion policy).

Implemented additions:

- Display forms/lemmas independently from filtering forms/lemmas. Filtering
  defaults to exact forms; lemma filtering is an explicit option.
- All five sort orders: textual frequency, alphabetical, appearance, measured
  global frequency, and a custom one-term-per-line ranking.
- A primary known file, normalized duplicate cleanup with preview/apply,
  discouraged opt-in automatic updates and a side-effect-free test mode.
- Optional deduplicated context history with always/prompt/flag-only settings,
  explicit save/decline overrides, and JSON export.
- Original-context highlighting in off/HTML/Markdown/Org styles, customizable
  consuming sentence-delimiter regexes and per-language overrides.
- Contexts/counts supplied only by surviving flagged occurrences, including
  the known sem / unknown smo case while displaying the lemma biti.
- A streaming SQLite-source build option alongside TSV. Source orphans and
  unsupported word mappings fail by default. Explicit --skip-orphans and
  --skip-unsupported count deliberate omissions in build-info.json.
- One concrete scope extraction: `processing.py` owns pure text algorithms
  and vocabulary records; `core.py` remains the public API and owns local
  data operations. Existing imports from `core.py` remain available.
- `downloads.py` contains the GitHub registry, bounded SHA-256-verified
  downloads and archive validation. Registered install codes support slv,
  pol and pli alongside offline local paths and explicit replacement.
  `package-plugin` emits fixed-name release archives; PLUGIN-RELEASES.org
  documents independent stable releases without version-link updates.
- Every Python source and test file has a purpose, separate in/out-of-scope
  lists, and a short navigation guide in its header docstring.

The real local Slovenian pack has 134,956 lemmas and 1,372,779 form mappings.
Its source contains 1,967,459 orphan form references out of 3,348,190 rows;
those omissions and 2,969 unsupported mappings are explicitly accounted for.
Global frequency is supported when measured data is provided; the source
has none. The teaching pack's synthetic values are clearly labeled.

The project author has moved the completed standalone Rust guide
revision into the sibling Rust project.

## 1. Source of the design

The reference is the current working tree of `../anchor`, particularly
`anchor/cli.py`, `anchor/config.py`, `anchor/core.py`, and
`pyproject.toml`. The requested `config.cli` and `core.cli` are
interpreted as Anchor's actual `config.py` and `core.py`.

Follow these concrete Anchor conventions:

- One flat application package, beside `pyproject.toml`.
- `cli.py` contains Click command functions and user interaction.
- `config.py` contains defaults, TOML loading and path configuration.
- `core.py` exposes a service class usable independently of the CLI.
- Each module begins with a scope statement, inclusions and exclusions.
- Descriptive function names, ordinary Python control flow, type hints
  where they clarify inputs/results, and short useful docstrings.
- A setuptools console script points directly at `package.cli:cli`.
- Commands instantiate the service and catch expected exceptions.

Anchor's implementation is a style reference, not a requirement to copy
unfinished behavior. For example, its config loader does not use all of
its declared defaults, and its declared Python minimum precedes the
availability of its `tomllib` import. Blitzer will use Python 3.11+,
which includes `tomllib`, and will explicitly merge defaults.

The Blitzer requirements come from `../blitzer-cli` and its language
pack guide, `../blitzer-rust/_ai/blitzer-rust-guide 2.org`, and
`../blitzer-rust/todos.org`. The latter refines exclusions into a
normal known-word list plus a separate forms-only list.

## 2. The result we are building

The first finished version must:

1. Accept UTF-8 text through an explicit option, a file, or stdin.
2. Produce a stable vocabulary list, optionally using dictionary lemmas.
3. Count repeated forms and all distinct candidate lemmas correctly.
4. Exclude known vocabulary with understandable form/lemma rules.
5. Retain original spelling and punctuation in sample context.
6. Include unknown words by default and actually support excluding them.
7. Support plugin-free `base` mode and one complete Slovenian pack.
8. Build, check, install, list and remove local data-only language packs.
9. Work as an imported Python API without Click, printing, or shared state.
10. Explain bad config, missing files and broken databases through useful
    errors and unsuccessful command exits.

Slovenian is the first real pack because its database is already available
at `../blitzer-language-plugins/blitzer-language-slv/lemmas.db`.
The Rust fixture points there. A read-only query during this review
confirmed `je -> biti, jesti, on`. We have not validated that entire
dataset or implemented a converted pack.

## 3. Problems in the prototype that this design addresses

These are observations of the current local source, not assumptions that
every published version has the same behavior.

| Prototype finding | Required replacement |
| --- | --- |
| The install branch also accepts `uninstall`, making the real uninstall branch unreachable | Separate, directly testable operations |
| `exclude_unknown_flag` is passed but never used | Unknown filtering is part of the processing algorithm |
| Global config, exclusion overrides and database cache | Per-service configuration and per-call resources |
| Prompt lookup reloads default config | Use the already selected configuration |
| Broad exceptions silently return empty config | Missing optional config gets defaults; invalid config fails |
| Normalization changes the entire source before context extraction | Tokenize original text and normalize lookup keys |
| Fallback tokenizer is a selection of Latin ranges | An explicit Unicode-category tokenizer |
| Processing, filtering, context, SQL and output formatting are intertwined | A short API operation composed of named steps |
| Connection helper leaves cached connections open | Close one operation's connection deterministically |
| Entry-point registration can download data and print to stdout | Runtime pack loading reads local data only |
| Warning branches reference `sys.stderr` without importing `sys` | CLI owns terminal messages |
| There are two definitions of `get_exclusion_terms` | One implementation with explicit parameters |
| Semicolon output and handcrafted context quoting | Defined text/TSV/JSON/report formats |
| Tests sometimes assert substrings or colored output rather than behavior | Exact small fixtures and API/CLI acceptance cases |

Do not port `processor.py` line for line or preserve its globals behind
a service-shaped wrapper.

## 4. Exact project layout

The application package layout is:

```text
blitzer-py/
├── .gitignore
├── PLAN.md
├── pyproject.toml
└── blitzer/
    ├── __init__.py
    ├── cli.py
    ├── config.py
    ├── core.py
    ├── processing.py
    └── downloads.py
```

During implementation, add `README.org` and `config.example.toml` at
the root, matching Anchor, the full application `LICENSE`, and a small
`tests/` directory with
`test_config.py`, `test_core.py`, `test_cli.py`, `test_functions.py`,
`test_downloads.py`, and
fixture helpers.
Tiny fixture data belongs under `tests/fixtures/` if files improve
readability; SQLite test databases should be generated in temporary
directories. Large language datasets stay outside the application package.

The initial three-module structure has two focused extensions:
`processing.py` separates pure language-learning rules from persistent data
operations. It accepts supplied data, performs no I/O and does not mutate
caller-owned inputs. `downloads.py` owns the newly requested registry
and HTTP/archive boundary. Keep this flat structure; do not add `utils.py`, service
or repository hierarchies, a model package, or a generic pipeline framework.
Any further extraction must make a concrete responsibility easier to find.

The distribution is `blitzer-py`, the import package is `blitzer`,
and the command is `blitzer`. This follows Anchor's console-script
arrangement. Develop in a dedicated virtual environment so the old
prototype's `blitzer` executable does not mask the new one.

Runtime dependencies are Click and platformdirs. The standard library
provides TOML reading, SQLite, paths, Unicode normalization, CSV/TSV,
JSON, temporary directories and HTML escaping. Add pytest as a development
dependency when tests are implemented. No HTTP client, ORM, dataframe
library, dependency-injection library, NLP model or logger is needed.

## 5. Module responsibilities and the public API

### cli.py

Define a plain Click group with Anchor's `-h/--help` settings.
Each command has explicit decorators and a small body:
read arguments, construct `BlitzerService`, call the API, format output,
translate expected failures into a Click error.

Keep `--config`, `--no-config` and `--plugins-dir` on each command
that uses the service, as Anchor places config options on commands.
A little visible decorator repetition is preferable to a custom command
base class or hidden decorators. There is no custom Click alias group.

Input streams, stdout/stderr, confirmation before removal and formatting
belong here. File/database/plugin business operations belong in core.
CLI path types return `Path`; config resolves configured paths.

Catch the documented expected error types for each operation. Do not
catch every `Exception` and turn programming bugs into “unknown word.”
Output errors through `click.ClickException`; usage mistakes through
`click.UsageError` or `BadParameter`.

### config.py

Keep plain dictionaries, matching Anchor. No configuration service class.
Plan these functions:

```python
def _default_config() -> dict: ...
def _get_config_file_path() -> Path: ...
def get_config(
    override_config_file: Path | None = None,
    *,
    use_config: bool = True,
    plugins_dir: Path | None = None,
) -> dict: ...
def load_plugin_config(plugin_dir: Path) -> dict: ...
```

Use a small private path-expansion function in this same file for all
configured paths. `get_config` returns a new validated dictionary with
resolved `Path` values. Nothing is loaded or created at import time.
Loading config does not create directories or write default files.

### core.py

Use one straightforward `BlitzerService`, matching `AnchorService`.
Its constructor loads/resolves config and stores it; it does not open a
database, scan packs, download anything or create directories.

Proposed public surface, to be implemented in order:

```python
class BlitzerService:
    def __init__(
        self,
        config_path: Path | None = None,
        *,
        use_config: bool = True,
        plugins_dir: Path | None = None,
    ): ...

    def blitz(
        self,
        text: str,
        language_code: str,
        *,
        lemmatize: bool | None = None,
        context: bool | None = None,
        exclude_unknown: bool | None = None,
        exclusions: tuple[Path, ...] | None = None,
        forms_only: tuple[Path, ...] | None = None,
        no_exclusions: bool = False,
    ) -> list[VocabularyEntry]: ...

    def list_languages(self) -> list[str]: ...
    def check_plugin(self, code: str) -> list[CheckResult]: ...
    def build_plugin(self, source_dir: Path) -> Path: ...
    def install_plugin(self, source_dir: Path) -> Path: ...
    def remove_plugin(self, code: str) -> None: ...
```

Keep four small dataclasses in core, beside the code that uses them:

- `Token(text, start, end)`: original substring and Python string offsets.
- `Context(start, end, token_start, token_end)`: original-text bounds and
  the first surviving occurrence to highlight within that context.
- `VocabularyEntry(term, count, contexts)`: one output item; contexts is
  empty when not requested.
- `CheckResult(name, status, detail)`: one ordered check, with status
  `"pass"`, `"fail"` or `"skip"`.

Use actual field type hints. Each record exists because a caller needs
those fields; do not add inheritance or methods just to decorate records.
Results do not contain terminal styling or HTML.

Core must validate domain inputs too, because an API caller can bypass
Click. Raise `ValueError` for bad options/data, `FileNotFoundError`,
`FileExistsError` and other `OSError` subclasses for file operations,
and `sqlite3.Error` for database failures. Include path/code context
when wrapping an error, preserving its cause. Add a custom exception only
if a real caller needs a distinction those types cannot express.

## 6. Configuration contract

Config-file selection is:

1. Explicit command/API config path.
2. `BLITZER_CONFIG`.
3. `<config-directory>/blitzer.toml`.

For the default config directory, honor a nonempty absolute
`XDG_CONFIG_HOME` as `<value>/blitzer`; otherwise use
`platformdirs.user_config_dir("blitzer")`. For the data directory,
honor nonempty absolute `XDG_DATA_HOME` as `<value>/blitzer`;
otherwise use `platformdirs.user_data_dir("blitzer")`.
This makes the explicit XDG data override agree with the Rust plan even
on macOS. Empty environment values count as unset. Reject nonempty
relative XDG roots with a useful error.

A missing default config means use built-in defaults. A missing explicit
or environment-selected config is an error. Malformed, unreadable or
invalid existing config is always an error. `--no-config` bypasses all
file selection, including `BLITZER_CONFIG`; it can still use platform
path defaults and explicit flags. Reject `--config` with `--no-config`.

Merge defaults and the selected file by these known sections, not via a
generic recursive configuration framework:

```toml
[locations]
# Optional. Default is the platform data directory plus /languages.
plugins_dir = "~/my-blitzer-languages"

[defaults]
lemmatize = false
freq = false
context = false
exclude_unknown = false
prompt = false
src = false
format = "text"

[languages.slv]
exclusions = ["known/slv.txt"]
forms_only = ["known/slv-forms.txt"]
prompt = "Create tab-separated Anki cards from this vocabulary."

[languages.base]
exclusions = []
forms_only = []
prompt = "Create study cards from this vocabulary."
```

Reject unknown keys, wrong section types, wrong booleans, unsupported
format names and wrong path-list types with a message naming the field.
In Python, check actual booleans rather than accepting integers as
booleans accidentally.

Path rules: expand `~` and explicit `$NAME`/`${NAME}` references,
error on an unset referenced variable, resolve file-config paths relative
to that config file, and resolve command/API relative paths against the
current working directory. Do not interpret shell commands or arbitrary
Python. A normalized config contains `Path` objects, not strings that
each later function expands differently.

Processing precedence is explicit option, selected config, built-in
default. For boolean Click switches, `None` means “not supplied”;
`False` means an explicit negative override. Use paired switches such
as `--lemmatize/--no-lemmatize`. This is supported by
[Click's option handling](https://click.palletsprojects.com/en/stable/options/).

Repeated exclusion options replace the selected language's configured
list for that category. `None` in the API means inherit; an empty tuple
means explicitly none. The CLI converts absence to `None`.
`--no-exclusions` clears both categories and conflicts with explicit
exclusion file options. Exclusion files are not created automatically.

Frequency, prompt, source and format are presentation settings resolved
in the CLI from `service.config`. Core resolves its own processing
options. A prompt uses the already selected language table; it never
reloads a second config file. An explicitly requested missing prompt
is an actionable error.

## 7. Language packs: files and schema, with no executable plugin code

A runtime pack is:

```text
<plugins_dir>/slv/
├── config.toml
├── lemmas.db
├── README.md          # source, build instructions and attribution
└── build-info.json    # builder provenance; not needed for lookup
```

Only config and database are required by the runtime. Builder-created
packs also carry the human-readable source README and a small build
record. Extra documentation does not change loading behavior.

A valid code is exactly three lowercase ASCII letters. `base` is
reserved and has no on-disk pack. The metadata code must match an
installed directory name. Never derive an installation target from an
arbitrary path fragment supplied as a “language code.”

The planned version-1 TOML is shared with the Rust checklist:

```toml
format_version = 1

[metadata]
language_name = "Slovenian"
language_code = "slv"
version = "0.1.0"
author = "Samiddhi"

[normalization]
lowercase = true
substitutions = []
```

An ordered replacement example is
`substitutions = [{ from = "ṁ", to = "ṃ" }, { from = "ŋ", to = "ṃ" }]`.
These are literal replacements, applied once each in array order.
Use an array because ordering is part of the behavior; ordinary TOML
tables do not define it. See the
[TOML table specification](https://toml.io/en/v1.0.0#table).
Require nonempty search strings and string replacements.

Reject unknown pack fields and unsupported format versions. Normalizing
substitutions operate within tokens, never across whitespace. They may
remove a character, but a resulting empty lookup key is dropped. Reject
rules introducing whitespace or control characters into keys. For the
first Slovenian pack, the list is empty.

Use this schema for new packs:

```sql
CREATE TABLE lemmas (
    id INTEGER PRIMARY KEY,
    lemma TEXT NOT NULL UNIQUE
);
CREATE TABLE forms (
    id INTEGER PRIMARY KEY,
    form_representation TEXT NOT NULL,
    lemma_id INTEGER NOT NULL REFERENCES lemmas(id),
    UNIQUE(form_representation, lemma_id)
);
CREATE INDEX idx_forms_repr ON forms(form_representation);
PRAGMA user_version = 1;
```

The tuple uniqueness preserves different lemmas for one form. Identical
lemma spellings are one displayed vocabulary item in this version;
there are no sense IDs or part-of-speech distinctions in the output.
Display lemmas are NFC text. Form keys use the pack's complete
normalization routine, and every lemma gets a normalized self-form.

New readers require the new version. Legacy unversioned packs are
explicit conversion inputs. This is a shared target contract with the
Rust plan, not a claim that the current Rust code can already read it.

The prototype's pip packages and entry-point functions do not execute in
this application. A local pack can be shared as a folder or downloaded
and unpacked manually. Automated network downloads, registries and
custom Python tokenizer plugins are deferred until there is a concrete
need. Pali's apostrophe handling needs its own tokenizer cases before
claiming support; the first release promises Slovenian and base mode.

## 8. Processing algorithm and exact vocabulary behavior

Keep `BlitzerService.blitz` short enough to read as the following sequence.
Use named private helpers rather than nested closures or a configurable
graph of pipeline stages.

1. Validate the code and options. Whitespace-only input is a `ValueError`.
   Punctuation-only input is valid and may yield no vocabulary.
2. Load only the requested pack config. Open its database only if lookup
   is needed. Check file presence/version and lightweight schema
   compatibility; reserve full integrity scans for `check-plugin`.
3. Read and normalize the two selected exclusion lists.
4. Tokenize the original text, retaining start/end positions.
5. Normalize each token into a lookup key.
6. Look up candidate lemmas when lemmatization, unknown filtering or
   lemma-based exclusions require them.
7. Apply exact-form exclusions, then candidate-lemma exclusions and
   the unknown policy.
8. Aggregate surviving output terms and their counts.
9. Retain context for surviving occurrences if requested.
10. Sort by descending count, then ascending term, and return entries.

### Tokenization and normalization

Use a short character loop with `unicodedata.category`: words start with
a Unicode letter and continue through letters and combining marks.
Permit straight or curly apostrophes inside a word only when followed by
a letter. Leading/trailing apostrophes, hyphens, underscores, digits and
other punctuation separate tokens. Thus `don't` is one token,
`well-known` is two, `abc123def` is two, and `123` yields none.
An unattached combining mark is ignored. Make these examples tests.

Offsets are Python string indexes, not Rust UTF-8 byte positions. Never
mix the two conventions when comparing fixtures. Generic letter runs do
not provide dictionary-based segmentation for languages without word
separators; do not advertise that capability.

Normalize each original token: NFC, lowercase if enabled, literal
substitutions in array order, then NFC again. Use `lower()`, not
`casefold()`; accent deletion is never a default. Preserve the original
source untouched. Builder keys and exclusion comparisons use the same
helper. NFC composition is available in
[Python's Unicode library](https://docs.python.org/3/library/unicodedata.html).

### Database lifetime and lookup

Open SQLite using a resolved file URI and `?mode=ro`, with `uri=True`.
Bind values using parameters. Query distinct lemmas in sorted order:

```sql
SELECT DISTINCT l.lemma
FROM forms AS f
JOIN lemmas AS l ON l.id = f.lemma_id
WHERE f.form_representation = ?
ORDER BY l.lemma;
```

Normalize in Python and use exact key comparison. Do not rely on
SQLite's default `NOCASE` for general Unicode matching.
Close the connection in `finally` or `contextlib.closing`.
The SQLite connection's own `with` handles transactions but does not
close it, as described in
[Python's SQLite documentation](https://docs.python.org/3/library/sqlite3.html#how-to-use-the-connection-context-manager).

One local dictionary per call can remember lookups for repeated keys.
No global cache or temporary SQL table is needed. Database errors
propagate; an empty query result alone means unknown.

### Counts, ambiguity and exclusions

Form mode emits normalized forms. Lemma mode emits each distinct
candidate lemma. Each candidate receives one count for each surviving
token occurrence. Candidate totals may exceed the source-token count.
This program offers vocabulary candidates, not contextual disambiguation.

The ordinary exclusion list means “known lemma or exact known form.”
The forms-only list means “this spelling only.” Read one term per UTF-8
line, strip outer whitespace, ignore blanks and full-line `#` comments,
and normalize consistently. Validate that each entry is one supported
word token rather than silently splitting phrases.

Do not lemmatize exclusion terms and mark all their candidates as known.
If an exclusion is an inflected form, exclude that exact form only unless
it also matches a normalized lemma spelling.

Apply this truth table, assuming `je -> biti, jesti, on`:

| Mode and exclusions | Result for one occurrence of `je` |
| --- | --- |
| Lemma mode, none | `biti`, `jesti`, `on`, each +1 |
| Lemma mode, ordinary `biti` | `jesti`, `on`, each +1 |
| Form mode, ordinary `biti` | Keep `je`: some candidates remain unknown |
| Either mode, ordinary `je` | Drop the occurrence by exact form |
| Either mode, forms-only `je` | Drop the occurrence; other inflections survive |
| Either mode, forms-only `biti` | Keep `je`; only literal `biti` is excluded |
| Form mode, all three lemmas known | Drop `je` |
| Unmatched `xyzzy`, default | Keep normalized `xyzzy` |
| Unmatched `xyzzy`, exclude unknown | Drop it |

If all known candidates are filtered out, do not reintroduce the form as
an unknown word. Unknown status is decided by the original lookup.
Unknown filtering also works in form mode, where it still needs a lookup.

In `base` mode all vocabulary is forms. Exclusions use exact normalized
forms; `--lemmatize` and `--exclude-unknown` fail clearly because
there is no lexicon. Negative switches allow a user to override a global
lemmatization default when choosing base mode.

### Context

Build sentence-like source spans once: newline boundaries, or a run of
`. ! ?` followed by whitespace/end of text. The last unfinished span
is also a context. Document that abbreviations are a limitation.

Retain the first two distinct spans containing surviving occurrences per
entry, in source order. Within each span, highlight the first surviving
token that contributed that entry. Filtered occurrences must not provide
context or inflate counts. Use token offsets; do not search the entire
source again for every word.

Return original spans in API records. CLI report rendering can add
`<b>` around the selected original substring, using `html.escape`
on source pieces first. JSON contains plain source context and offsets.
TSV context cells contain escaped HTML with internal tabs/newlines
converted to spaces; two contexts are joined with `<br>`.

## 9. CLI contract and output

Use explicit, flat commands, following Anchor:

| Command | Inputs and effect |
| --- | --- |
| `blitz` | `-l/--language CODE`, text/file/stdin, processing and output options |
| `list-languages` | Sorted installed pack codes plus `base` |
| `build-plugin SOURCE_DIR` | Build and validate a new populated pack in the selected root |
| `check-plugin CODE` | Ordered complete validation report; failure exits unsuccessfully |
| `install-plugin SOURCE_DIR` | Validate and copy an existing self-contained pack into the root |
| `remove-plugin CODE` | Remove exactly that installed pack; CLI asks unless `--yes` |

All accept `--config PATH`, `--no-config`, and `--plugins-dir DIR`.
The group also provides help/version; derive the version from installed
package metadata once that command is added.

For `blitz`, provide:

- `--text/-t TEXT` or `--file/-i PATH`, mutually exclusive. If neither
  is supplied, read stdin; if stdin is a terminal, raise a usage error.
  Supplied text/file takes precedence over an unrelated pipe and does
  not also consume it. An explicitly empty text is an error.
- `--language/-l CODE`, required; `base` is an explicit choice.
- Paired `--lemmatize/--no-lemmatize`, `--freq/--no-freq`,
  `--context/--no-context`, `--exclude-unknown/--include-unknown`,
  `--prompt/--no-prompt`, and `--src/--no-src`.
- Repeatable `--exclude PATH` and `--exclude-forms PATH`, plus
  `--no-exclusions`.
- `--format text|tsv|json|report`; default `text`.

Do not recreate every historical underscore spelling or every short
alias. Document the new spellings with a migration table.
Use the selected encoding strictly: invalid UTF-8 input is an error,
not silently replaced text.

Output formats:

| Format | Contract |
| --- | --- |
| text | One term per line; optional count then context fields, tab-separated, no header |
| tsv | Same selected fields with a header; use `csv.writer(delimiter="\t", lineterminator="\n")` |
| json | Array of records; always `term` and `count`, plus contexts if requested; valid Unicode JSON |
| report | Optional PROMPT and SOURCE sections followed by vocabulary rows |

The basic text format uses the same TSV field escaping when fields are
added; avoid handcrafted delimiter concatenation. JSON is structured and
always includes counts; `--freq` only controls text/TSV/report display.
Do not imply that a missing `--freq` stops frequency computation.

Prompt/source additions require report format. Reject the combination
with text, TSV or JSON instead of prepending prose to data output.
The source section contains the original text, not normalized text.
All formats use the same ordering.

For no surviving vocabulary: text emits nothing, TSV emits its header,
JSON emits `[]`, and report may still show requested source/prompt.
Successful empty results exit 0. Usage errors exit 2; operational failures
and failed pack checks exit 1. Diagnostics belong on stderr. Finish
processing before writing vocabulary output so lookup failures cannot
produce a misleading partial result. Handle broken pipes cleanly.

Target examples (these are future commands):

```sh
blitzer blitz -l base -t "Cats, cats. Dogs!" --freq
blitzer blitz -l slv -t "Je je." --lemmatize --freq
blitzer blitz -l slv --file chapter.txt --lemmatize --exclude known/slv.txt
blitzer blitz -l slv --file chapter.txt --context --format tsv
blitzer blitz -l slv --file chapter.txt --prompt --src --format report
printf '%s\n' 'Je je.' | blitzer blitz -l slv --lemmatize --format json
```

The base example returns `cats<TAB>2` then `dogs<TAB>1`.
The `Je je.` fixture returns `biti<TAB>2`, `jesti<TAB>2`,
`on<TAB>2` in that order.

## 10. Build and maintain the first real plugin

### One source format and one builder

A build source directory contains:

```text
slv-source/
├── config.toml      # the supported pack config
├── forms.tsv        # UTF-8; header exactly form<TAB>lemma
└── README.md        # source identification, preparation steps, attribution
```

Use `csv.DictReader` with a tab delimiter. One row is one form/lemma
mapping; repeat a form on several rows for ambiguity. Validate exactly
two columns, nonempty values, well-formed UTF-8 and values suitable for
the single-word tokenization contract. Report filename and row number.
Do not silently discard unsupported multiword entries; the source
preparation step must account for them and document any exclusion.

Builder sequence in core:

1. Load/validate source config and infer the destination from its code.
2. Refuse any existing destination, including dangling symlinks. There
   is no overwrite flag in v1.
3. Make a temporary staging directory under the destination's parent.
4. Copy the validated source config and README. Copying config preserves
   comments and avoids a TOML-writing dependency.
5. Create the schema, enable foreign keys, and start one transaction.
6. Stream TSV rows, normalize forms, NFC-normalize displayed lemmas,
   insert a lemma if absent and retrieve its ID, then insert the pair.
   Keep parameterized statements and an optional local lemma-ID map.
   Memory must not grow with every inflected-form row.
7. Add normalized self-forms for the distinct lemmas. Deduplicate these
   just like source rows. Blank normalized keys are a source error.
8. Commit, close the writer, and run the complete pack checker.
9. Write `build-info.json`: application/format version, source file
   SHA-256 hashes, counts of source rows, unique lemmas/pairs, duplicate
   pairs, and inserted self-forms. “Reproducible” means the same logical
   contents and counts, not an identical SQLite file hash.
10. Move the validated staging directory to the unused final path. Check
    the destination again before publication and preserve it on conflict.
    On error, remove only this operation's staging directory.

Use a simple single-writer policy for pack mutations: create one exclusive
lock file in the plugin root, release it in `finally`, and have a
second Blitzer mutation fail with a useful message. Document recovery of
a stale lock after verifying no writer remains. This prevents two
Blitzer builds/removals from publishing over each other without adding
background services or a locking dependency.

This is a populated build, unlike the Rust checklist's initial scaffold
command. The runtime pack contract is shared; CLI pack-author workflows
do not need identical intermediate steps.

### Prepare Slovenian data

Start with a tiny hand-authored source containing the mappings used in
section 8. Build and check it first. Then prepare the real source:

1. Read the existing Slovenian source database using a read-only URI;
   do not import its Python plugin, which may download files.
2. Inspect its columns, blank/null rows and orphan forms. Its current
   relevant tables are `Forms(id, lemma_id, form_representation)` and
   `Lemmas(id, lemma)`; `idx_form_rep` indexes form representation.
3. Export the join below to TSV with Python's `csv.writer`, streaming
   rows and retaining ambiguity. Source validation must separately check
   orphan forms because an inner join would conceal them.
4. Write correct Slovenian metadata and empty substitutions. The current
   Rust fixture's Pali metadata is not a template to copy.
5. Record any intentionally excluded unsupported entries with counts and
   reasons. Never make invalid rows disappear silently.
6. Run the normal builder; validate lookups, normalized self-forms,
   counts and source attribution against the source.

```sql
SELECT f.form_representation, l.lemma
FROM Forms AS f
JOIN Lemmas AS l ON l.id = f.lemma_id;
```

The one-time export can be a documented short Python recipe in the
pack's README using `sqlite3` and `csv`. It does not justify a new
application module or a source-adapter framework. Its destination must
be a new explicit file; close both resources even on failure.

The existing Slovenian README identifies SLOLEKS as the data source.
Carry its source/license attribution into the new pack and record the
actual input used. Preserve source and code-license information
separately; do not claim that the Python application license replaces
the dataset's terms.

Do not assert the old tests' 138904 lemmas and 3348190 forms as new-build
requirements. Deduplication, normalization and self-forms can change the
counts. Report and reconcile actual numbers.

### Pack checks, listing, installation and removal

`check_plugin` returns all independent checks it can perform, in order:
files; TOML/types/version; code match; read-only opening; schema version;
tables/columns; nonempty counts; no blank/null/invalid keys; no duplicate
pairs or orphan references; appropriate leading-column lookup index;
SQLite integrity; known-form query; and normalized self-form coverage.
Skip dependent checks after a prerequisite fails. Include enough detail
to fix each failure.

Detect indexes by their actual columns, not a hard-coded index name.
An empty pack, missing index, unsupported version or broken relation
fails release readiness. A dummy unknown query alone cannot prove that
the data join works. Full normalization checks can stream the rows;
they must not load the complete database into memory.

`list_languages` performs a sorted structural directory scan, adds
`base`, and opens no database. A missing root returns just `base`.
Skip unrelated/incomplete directories; propagate actual permission and
directory-read errors. Tell users that listing is not a validation result.

`install_plugin` validates a supplied local pack, stages a copy,
validates that copy, and publishes it under its metadata code. Refuse
existing destinations and reject symlinks inside the source pack so the
installed result is self-contained. Reject source equal to, inside, or
containing the destination to avoid recursive copies. Copy optional
documentation as ordinary files. Use the same mutation lock and cleanup
rules as building.

`remove_plugin` validates the code, refuses `base`, resolves one
immediate child of the plugin root, rejects a symlinked pack directory,
and removes only that directory. A missing code errors. Refuse a root
or traversal target. The API does not prompt; the CLI confirms the
selected path, with `--yes` for scripts. Removal must be tested to
leave adjacent languages intact.

## 11. Ordered implementation sequence

Each step is a small reviewable change. Implement its API before its CLI
wrapper, and stop adding behavior when that step's acceptance cases pass.

1. **Make the skeleton installable and document boundaries.**
   Confirm the flat package, entry point and supported Python version.
   Add README setup and the config example when the loader is introduced.
   Help must work without reading config or opening a database.
   Done when editable installation provides the expected help/version.

2. **Implement config.py completely.**
   Defaults, selection, explicit section merges, typed validation,
   relative paths, environment expansion and no-config behavior.
   Done when temporary-directory tests cover precedence and errors,
   and loading defaults writes nothing.

3. **Implement pure tokenization and normalization in core.py.**
   Add Token and the source-preserving helper functions. Test Unicode,
   case, combining marks, punctuation and apostrophes.
   Done when raw spans and normalized keys are independently correct.

4. **Implement base-mode API and counts.**
   Introduce BlitzerService, VocabularyEntry and deterministic sorting.
   Add exact-form exclusions and validate unsupported base options.
   Done when two consecutive service calls do not affect each other and
   the base example produces exact expected records.

5. **Implement the first blitz CLI wrapper.**
   Add explicit input rules, flag/default precedence and text/TSV output.
   Done when text, file and stdin paths behave identically, no-input
   terminal use errors clearly, and diagnostics do not pollute stdout.

6. **Implement pack config, SQLite loading and checking.**
   Use a generated tiny database and the version-1 contract. Keep reads
   read-only and explicitly closed.
   Done when known/unknown/ambiguous queries work and corrupted data fails.

7. **Implement build-plugin and the tiny Slovenian pack.**
   Stream the specified TSV, insert self-forms, record provenance, check
   before publication and handle conflicts/failure cleanup.
   Done when a source directory becomes a complete portable pack and a
   failed/repeated build preserves existing files.

8. **Add full lemmatization and both exclusion categories.**
   Implement the truth table, unknown filtering and local lookup reuse.
   Done when every table row is covered in form and lemma modes,
   including candidate counts and unknowns after filtering.

9. **Add context and the remaining presentation formats.**
   Build spans once, preserve case, escape HTML, add JSON/report,
   prompt/source settings and empty-result behavior.
   Done when exact output is correct for tabs, quotes, Unicode and
   markup-like input, and data formats stay parseable.

10. **Finish pack management commands.**
    Add list/check/install/remove wrappers and their API operations.
    Done when copying a pack makes it independent of its source and
    removal only removes the specified pack.

11. **Build and evaluate the full Slovenian pack.**
    Export the existing source through the documented recipe; build,
    reconcile counts and validate `je` and representative sentences.
    Measure a chapter-sized input and inspect the query plan.
    Done when the real pack meets correctness and practical usability
    checks without needing any legacy package.

12. **Finish documentation and installation verification.**
    Explain configuration paths, commands, formats, exclusions, ambiguity,
    plugin source preparation and old/new migration.
    Test a clean wheel installation outside the checkout with a copied
    pack. Done when another person can repeat setup and the first build.

## 12. Required verification

Use pytest with real temporary files and SQLite databases. Use
[Click's CliRunner](https://click.palletsprojects.com/en/stable/testing/)
for argument, stream and exit-status tests. Do not run those CLI tests
in concurrent threads. Ordinary tests require no downloads, installed
language package, real user config or multi-million-row data file.

| Area | Acceptance cases |
| --- | --- |
| Config | absent default, bad explicit/env path, malformed TOML, unknown keys, negative flags overriding true defaults, no-config bypass, config-relative paths |
| Input | text/file/stdin, explicit empty text, no-input terminal, whitespace, invalid UTF-8, punctuation-only text |
| Unicode | uppercase Slovenian, composed/decomposed forms, combining marks, apostrophes, hyphens, non-Latin letters, digits |
| Lookup | one/multiple/no matches, duplicate candidates, broken schema/rows, absent DB not created, connection closed on failure |
| Exclusions | every truth-table row, both modes, unknown forms, two files, explicit replacement/empty override, no state leakage |
| Counts | duplicate source rows never inflate counts, repeated tokens do, sorted ties, ambiguity totals documented |
| Context | original case and punctuation, repeated forms, two distinct spans, excluded occurrences absent, HTML escaped |
| Formats | exact plain output, TSV round-trip through csv.reader, JSON parsing, report-only headers, empty results |
| Plugins | build/check/install/remove end to end, unsupported versions, code mismatch, failed build cleanup, conflicts, source independence |
| Paths | traversal-like codes rejected, symlink rules, neighboring pack preserved, spaces and Unicode in paths |
| API | no Click import or terminal output from core/config, repeated calls independent, per-operation resources released |
| CLI | help without config, runtime/usage/check exit statuses, stdin pipe, no partial output after database failure |

For the real pack, record source file hashes, actual counts, input size,
distinct lookup keys, runtime and peak memory on a representative text.
Check that the indexed query is used. Set a performance target from an
actual measurement; this planning task supplies no invented benchmark.
Only optimize a measured bottleneck, first through one connection,
indexed lookup and per-call duplicate-key reuse.

## 13. Migration and scope limits

Existing prototype configuration is not silently imported. Document this
small explicit mapping:

| Old prototype | New version |
| --- | --- |
| `default_lemmatize`, `default_freq`, etc. | `[defaults]` fields |
| `[exclusions].slv = "path"` | `[languages.slv].exclusions = ["path"]` |
| `[prompts].slv` | `[languages.slv].prompt` |
| `--language_code` | `--language` |
| `--exclude_unknown` | `--exclude-unknown` |
| `-e slv:path` | `--exclude path` for the selected language |
| `languages install slv` through pip | `install-plugin /path/to/slv` |
| Entry-point plugin with download behavior | Local versioned TOML + SQLite pack |
| `~/.config/blitzer/config.toml` | Platform/XDG `blitzer.toml`, or explicit `--config` |
| Semicolon output | Defined text/TSV/JSON/report |

Keep old config and data untouched. Convert a pack explicitly and copy
user-maintained exclusions only when requested during implementation.
One-word-per-line exclusion files can generally be reused after checking
normalization. Explain executable-name collisions through the dedicated
virtual environment in the README.

Deferred: online pack catalog, automated downloads, arbitrary Python
plugins, contextual disambiguation, language-specific NLP segmentation,
exclusion-list editors, automatic Anki/LLM integration, multiprocessing,
async execution, daemons and persistent caches.

The first release is complete only when all required behavior above is
implemented, the fixture and real Slovenian pack both work, the public
API and CLI agree, the ordinary tests pass, and a clean installation
works outside this checkout. A scaffold or successful help command is
only the starting point.
