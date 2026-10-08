# Language packs

- Ready packs live in three-letter folders such as `slv/` and `pol/`.
- Unfinished packs belong in `dev/` and are excluded from releases.
- Pack databases and generated ZIPs are excluded from Git.

See the [word-boundary and display-name assessment](../maintenance/reports/language-boundaries-plan.md)
for dev-pack implementation queues, existing-pack limitations and proposed fixes.
The [current project status](../maintenance/reports/project-status-20261008.md)
records implemented profiles, promoted packs, remaining blockers and release commands.

## Reviewed boundaries and names

The application includes `blitzer/language-catalog.json`, a reviewed identity
and capability catalog covering ready and development languages. The separate
download registry includes only ready packs. Pack names are no longer inferred
from arbitrary upstream README headings.

Format 1 packs retain the original Unicode letter-run behavior. Format 2
packs explicitly select an application-owned profile:

```toml
format_version = 2

[metadata]
language_name = "Zenzontepec Chatino"
language_code = "czn"
version = "0.2.0"
author = "UniMorph contributors"

[tokenization]
profile = "tone-hyphen"

[normalization]
lowercase = true
substitutions = []
```

Profiles preserve source offsets and are used consistently for dictionary,
frequency and known-list validation. Nondefault profiles require the new
application release; update `bltzr` before installing these packs. Archive
filenames retain `-v1.zip` because their ZIP layout and database schema have
not changed; the configuration inside declares format 2.

To preview or reproduce the reviewed local refresh with full upstream data:

```sh
.venv/bin/python -m maintenance.language_refresh
.venv/bin/python -m maintenance.language_refresh --apply
```

The second command rebuilds profiles, validates and promotes eligible packs,
repairs metadata and regenerates the registries and the README's language list
in alphabetical order by name. It preserves prior packs in a fresh ignored
`maintenance/work/language-refresh-*` directory. It does not publish. The
upstream checkout must be available at `maintenance/unimorph-data`, or supplied
with `--source PATH`; use `--packs PATH` and `--work PATH` for alternate local
directories. Publication still uses `make release` below.

## Publish a release

Complete the [one-time GitHub/PyPI setup](../maintenance/RELEASING.md),
then run from the project root:

```sh
cd ~/dev/blitzer-py
git status
git diff
make release
```

Do not bump the application version, create a tag, or package each language
manually. `make release` handles these steps:

1. Check source changes and compare language-pack contents with published
   packs. If nothing changed, stop.
2. Test the application and validate and package only changed packs.
3. Increment the application's patch version, such as `0.2.4` to `0.2.5`.
4. Build and check the Python package, commit all non-ignored changes,
   and push `master` and the version tag.
5. Upload changed packs and a content manifest, then publish the GitHub
   release. GitHub Actions publishes the application to PyPI.

Unchanged packs remain on their earlier releases. The installer finds the
newest stable release for each language, so no download links need editing.
The first automated release compares existing published ZIPs; later ones
use the small manifest. Large dictionaries can take time to check.

The automatic version bump applies to the application and release tag.
Each pack's `config.toml` metadata version is retained; you can update it
when preparing changes to that dictionary.

## Check publication or retry

```sh
gh run list --workflow publish.yml
gh run watch RUN_ID --exit-status
```

Replace `RUN_ID` with the numeric ID from the list. A successful job means
the application reached PyPI. Check a released pack with:

```sh
bltzr install-plugin slv --replace
```

If `make release` stops, fix the reported error and run it again. Keep the
pending-release checkpoint: it resumes the same version. If only the PyPI
job fails, fix its error and use `gh run rerun RUN_ID --failed`.

## Use local packs while developing

Read directly from this folder without installing or downloading:

```sh
bltzr list-languages -n -P ./language-packs
bltzr blitz -l slv -t "Sem. Smo!" -n -P ./language-packs
```

To use these packs by default, add this to
`~/.config/bltzr/bltzr.toml`, which is loaded automatically:

```toml
[locations]
plugins_dir = "~/dev/blitzer-py/language-packs"
```

If your checkout is elsewhere, change that path. `-P PATH` overrides it;
`-n` ignores your config. An explicit config file or existing XDG config
can override the default home config; see the main README's config section.

To install a local pack as an independent copy instead:

```sh
bltzr install-plugin ./language-packs/slv -n
```

## Validate or package manually

These commands prepare files locally without publishing a release:

```sh
.venv/bin/bltzr dev check-plugin slv -n -P ./language-packs
.venv/bin/bltzr dev package-plugin slv -n -P ./language-packs -o release-assets
```

Packaging reads the current pack, validates it, and replaces its ZIP and
checksum in `release-assets/`. A filename such as `blitzer-slv-v1.zip`
keeps `v1` because that is the pack format, not the release version.

Before releasing a new language, add its code and name to
`blitzer/language-registry.json` and put its ready pack in this folder.
Retain the dictionary's license and attribution files.

Use `make release` for publication so the release manifest stays current.
Any separate manual pack-only release should use a `packs-` tag prefix,
such as `packs-v0.3.0`, to avoid triggering application publication.
