This directory contains repository maintenance tools. They are excluded
from the installed application and its wheel/source distributions.

For one-command GitHub and PyPI releases, follow
[RELEASING.md](RELEASING.md). The local command is `make release`; account
setup is required before its first use.

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
- `ready/packs/` contains validated Latin-script packs.
- `ready/assets/` contains their release ZIPs and checksum files.
- `deferred/` holds packs requiring script, segmentation or input work.
- `registry.json` lists technically ready additional download codes.

The converter detects non-Latin letters in lemma/form pairs. If at least
1% of source pairs contain them, the language is deferred. For isolated
foreign terms below that threshold, the converter excludes those pairs
from the Latin pack and records the count. Explicit segmentation exclusions
also apply to languages such as Chinese, Japanese and Thai, including
romanized datasets. This is a conservative automated first pass; review
mixed orthographies before publication.

Multiword, digit-bearing and symbol entries cannot fit the current
tokenizer. They are omitted and counted. Empty paradigm slots are ignored;
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
