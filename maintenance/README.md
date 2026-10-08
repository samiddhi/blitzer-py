This directory contains repository maintenance tools. They are excluded
from the installed application and its wheel/source distributions.

See the [current project status](reports/project-status-20261008.md) for
the word-boundary implementation, full pack inventory, remaining development
work and exact release commands. `maintenance.language_refresh` previews or
applies the reviewed local pack refresh; it never publishes.

## Publish a new release

Complete the [one-time GitHub/PyPI setup](RELEASING.md) first. After that,
run these commands from the project root:

```sh
cd ~/dev/blitzer-py
.venv/bin/python -m pip install -e '.[dev]'
git status
git diff
make release
```

Do not manually change the version. The command increments the final
number (`0.2.4` becomes `0.2.5`), runs tests, builds and checks the package,
commits all non-ignored changes, and pushes the commit and tag. It uploads
only changed language packs and publishes the GitHub release. GitHub
Actions then publishes the application to PyPI automatically. If nothing
changed, the command does nothing.

Check the PyPI job:

```sh
gh run list --workflow publish.yml
gh run watch RUN_ID --exit-status
```

Replace `RUN_ID` with the numeric ID from the list. A successful job means
the new version was published to PyPI.

If `make release` stops, fix the reported error and run it again; the
checkpoint resumes the same version. If only the PyPI job fails, fix its
error and run `gh run rerun RUN_ID --failed` instead of creating another
release.

## Convert UniMorph data

Run the one-time UniMorph conversion from the project root with the
project environment installed:

```sh
.venv/bin/python -m maintenance.unimorph ./maintenance/unimorph-data \
  --output ./maintenance/work/unimorph-next --pack-version 0.2.0
```

Use a fresh output directory. Add repeated `--language CODE` options for
small development runs. The tool preserves its source checkout and writes
classified packs, archives, counts and a language registry export.

Reusable pack development stays in `blitzer dev`: `build-plugin`,
`check-plugin`, `expand-plugin` and `package-plugin`. Ordinary users install
published packs with `blitzer install-plugin CODE`.

## UniMorph conversion details

This one-time maintenance tool lives outside the application in
`maintenance/unimorph.py`. It is excluded from installed distributions.
Run it from the repository root using the project environment. Use the
linked checkout without modifying it:

```sh
.venv/bin/python -m maintenance.unimorph ./maintenance/unimorph-data --output ./maintenance/work/unimorph-output
```

The output directory must be new. For a later run choose another directory
and set `--pack-version 0.2.0`. For development, repeat `--language eng`
and `--language fra` to build only selected languages.

- `REPORT.md` gives the full language inventory and deferral reasons.
- `report.json` records counts, source checksums and output paths.
- `ready/packs/` contains validated packs with reviewed input capabilities.
- `ready/assets/` contains their release ZIPs and checksum files.
- `deferred/` holds packs requiring segmentation, orthography or input work.
- `registry.json` lists technically ready additional download codes.

The converter uses the reviewed `blitzer/language-catalog.json` capability
catalog rather than a Latin-only gate. Known spaced orthographies can be
released in any supported Unicode script. Unreviewed non-Latin codes,
unresolved source conventions and unsupported lexical segmenters remain
deferred. Japanese has an optional Sudachi adapter but its pack remains in
dev pending dictionary-coverage review. Sanskrit, Tibetan and Urdu remain
deferred; generic letter runs do not provide their lexical segmentation.
The `zxx` special code is excluded, and empty source tables are reported as
missing data. Scripts are still recorded for provenance; foreign-script
lexical rows are preserved when a reviewed profile accepts them.

Multiword and unsupported symbol entries are omitted and counted. Reviewed
tone profiles accept numeric tone notation without stripping it, and scoped
profiles preserve internal punctuation or joiners. Rejections are counted by
cause with bounded source examples. Empty paradigm slots are ignored;
other malformed rows defer a dataset for inspection. Empty repositories
are reported as `missing-data`; they cannot supply a pack. Deferred
datasets with no supported rows have a report entry without a database.
Packs exceeding the installer's 512 MiB download or 2 GiB expanded-file
limits are also deferred; they need a smaller dataset or format changes.

The tool streams plain TSV, XZ and recognized CSV tables, combines dialect
and supplemental inflections, prefers `.um4` over the older canonical
table, and avoids redundant compressed copies. It excludes glosses,
derivations and segmentations. Full upstream attribution and supplied
license files accompany packs. Features are not part of Blitzer's lookup
schema; ambiguous form/lemma relationships are retained.
Repeated grammatical analyses of the same form and lemma become one
database row. For example, Slovenian `brata -> brat` is stored once even
when several feature bundles describe it. The report includes duplicate
pairs removed and the final number of stored form/lemma pairs.

Only publish ZIPs in `ready/assets/`. Review upstream licenses first:
passing technical checks does not establish redistribution permission.
The existing Slovenian, Polish and Pali registry entries retain their
original sources. See `PLUGIN-RELEASES.org` for registry and release steps.
