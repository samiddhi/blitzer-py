# Slovenian source preparation

Source: the local Slovenian form/lemma database, derived from SLOLEKS.
Data attribution: SLOLEKS / Centre for Language Resources and Technologies,
University of Ljubljana; the upstream pack identifies the data as CC BY-SA 4.0.
Source project: https://www.cjvt.si/raziskovalno-delo/projekti-cjvt/slovenski-oblikoslovni-leksikon-sloleks/
The application code is GPL-3.0-or-later; that does not replace the data's license.

Build from the source SQLite database, read-only:

    blitzer build-plugin examples/slv-source --database /path/to/source/lemmas.db --skip-unsupported --skip-orphans --plugins-dir ./language-packs --no-config

The explicit --skip-unsupported option omits multiword/symbol entries that the
current tokenizer cannot represent as one vocabulary item. The builder counts
those omissions and records them, duplicate pairs, self-forms, input hashes and
actual resulting counts in build-info.json. Missing/null data and orphan references
still fail. The original database is never written to.

Normalization: NFC, Unicode lowercase, no accent removal or substitutions.
Global corpus frequencies are not supplied by this source. Supply a genuine
frequencies.tsv with term/frequency columns to enable global-frequency sorting.

The supplied local source has 1,967,459 orphan form references out of
3,348,190 form rows. --skip-orphans explicitly counts/omits those rows.
The completed build contains 134,956 lemmas and 1,372,779 unique form mappings.
