# Project status and GitHub release instructions

Date: 2026-10-08. Implementation and local pack preparation are complete for
the releaseable capabilities described below. Dedicated segmentation and
the remaining source-quality cases are explicitly deferred, not presented
as finished language support. No commit, tag, push or publication was made.

## Current inventory

| Item | Before | After |
| --- | ---: | ---: |
| Ready language packs | 119 | 165 |
| Built-in Basic mode | 1 | 1 |
| Dev directories, including special-code notice | 68 | 22 |
| Ready packs using explicit format-2 profiles | 0 | 31 |

The main [README](../../README.org) contains all **165 ready languages plus
Basic**, sorted alphabetically by display name, with codes in parentheses.
It was checked against installed CLI names and both download registries.
The CLI itself retains its existing code ordering; the README uses name
ordering, as requested. Its list describes the next release: new packs are
available locally now and become downloadable after publication.

The 46 promoted packs are:

`ady afb amh ara arz asm azg bak bel ben bra bul chu ckb cly ctp ell fas
got grc guj hbs heb hin hye kan kat kaz kbd ket khk kjh mag mkd pbs pus
rus sah sjo syc tel tyv ukr xcl xty yid`.

The original plan's 47 promotion candidates became 46: **Sierra Otomi
(`otm`) has no usable single-unit form/lemma mappings even after tone
support**. All 31,380 source mappings have multiword forms. Mapping each
component to the phrase lemma would be wrong, so it remains in dev.

## Implemented behavior

- Added a complete reviewed identity/capability catalog, separate from
  download eligibility. Corrected all 19 definite generated-name faults
  from the assessment, including Czech, Slovak and the dev names, plus
  precision improvements such as Congo Swahili and Anglo-Norman. Meaningful
  custom local pack titles remain usable. The converter no longer extracts
  arbitrary headings, bullet filenames or uppercase codes from READMEs.
- Added pack configuration **format 2** with validated, application-owned
  profile IDs. Format 1 retains its original boundary behavior. Pack code
  remains data-only: it cannot import a downloaded tokenizer function.
- Implemented profiles for internal joiners, Hebrew punctuation, Xibe
  format handling, tone digits, preserved transcription hyphens, Catalan/
  Occitan middle dot, O'odham colon/glottal punctuation, Seneca/Navajo final
  apostrophes, Haida internal periods and Pali's internal quote substitution.
- French and Italian use a conservative dictionary-first elision fallback.
  A full dictionary entry wins; otherwise a recognized suffix can be
  extracted with its original offsets. This is not a universal clitic or
  mutation analyzer. Celtic mutations/hyphenation and less common elision
  patterns remain dictionary-coverage work.
- The query and occurrence paths now share the same tokens and offsets.
  Profile-aware validation also covers mappings, lemma self forms,
  frequencies, known/exclusion lists, installation, merging and packaging.
- Added Unicode sentence delimiters for contexts, including Japanese full
  stops, Arabic question marks, Indic danda and Tibetan shad. Explicit
  user sentence-pattern overrides still apply.
- Replaced script-only deferral with reviewed capability decisions. Mixed
  scripts are retained rather than automatically discarded. Empty source
  files receive a missing-data diagnosis, and `zxx` is classified as a
  non-language special code.
- Added the optional **Sudachi Japanese adapter**, pinned to SudachiPy
  0.6.11 and SudachiDict-core 20250515. It uses original source spans and
  can fall back to the analyzer's dictionary form when a surface form is
  absent from UniMorph. Dependencies are installed explicitly, and the
  adapter performs no model downloads at runtime. The Japanese pack stays
  in dev pending broader dictionary alignment/coverage evaluation. The
  maintained Python implementation is described in [Sudachi.rs](https://github.com/WorksApplications/sudachi.rs).
- Legacy unspaced-language packs now fail explicitly when ordinary lexical
  segmentation is unavailable, instead of treating a whole run as one word.
  A local format-2 pack can explicitly declare a limited presegmented mode;
  that does not make the ordinary-prose dev pack releaseable.

## Dictionary recovery and remaining omissions

Thirty-seven profile-dependent datasets were rebuilt from complete upstream
sources. Thirty-four produced databases; thirty rebuilt datasets are ready
and four databases remain in dev. Three datasets still have no supported
mappings. The three hyphen profiles were then rebuilt again with the
reviewed internal-hyphen behavior.

Representative conversion results (source rows, not vocabulary accuracy):

| Pack | Previously accepted | Now accepted | Still omitted | Main remaining issue |
| --- | ---: | ---: | ---: | --- |
| Zenzontepec Chatino (`czn`) | 13 | 1,538 | 29 | Multiword forms and unsupported notation |
| Mezquital Otomi (`ote`) | 572 | 2,072 | 31,090 | 31,085 multiword rows; smaller notation residue |
| Yoloxóchitl Mixtec (`xty`) | 0 | 2,975 | 82 | Mostly multiword rows |
| San Pedro Amuzgos Amuzgo (`azg`) | 0 | 9,487 | 2,717 | Mostly multiword lemmas/forms |
| Eastern Highland Chatino (`cly`) | 0 | 2,835 | 1,881 | Mostly multiword rows |
| Yaitepec Chatino (`ctp`) | 0 | 3,585 | 211 | Alternative/symbol notation and multiword rows |
| Central Pame (`pbs`) | 0 | 12,528 | 0 | Transcription scope still applies |
| Sierra Otomi (`otm`) | 0 | 0 | 31,380 | All source mappings have multiword forms |

Tone marks and internal morpheme hyphens are preserved in the documented
transcription profiles, not stripped or converted into guessed orthography.
The source converter records rejected rows by cause with bounded examples.
Full-source results are in [language-boundary-conversion.json](language-boundary-conversion.json).
Those counts also appear in the rebuilt packs' UniMorph provenance.

Ready means technically validated for the documented input scope. It does
not mean every native text or common word appears in the dictionary. Smoke
checks found that Russian `дом`/`дома`, Catalan `col·legi` and Persian
`می‌روم` are absent from these particular datasets; boundary support does
not supply missing entries. `--exclude-unknown` can therefore remove real
words. Dictionary enrichment, vocalized/unvocalized Arabic matching,
phrase lookup and dialect/transcription alignment remain distinct work.

## Remaining development work

There are **21 actual language candidates plus the excluded `zxx` notice**
under `language-packs/dev/`:

| Codes | Current blocker / next action |
| --- | --- |
| `jpn` | Optional analyzer works and has integration coverage; evaluate UniMorph alignment and representative prose before promotion. |
| `bod` | Add a Tibetan lexical segmenter and clean source terminal punctuation; tsheg splitting alone is insufficient. Botok is a candidate to evaluate, not an installed runtime capability. |
| `urd` | Add an Urdu segmenter that handles inserted/omitted spaces. The inspected [Urduhack documentation](https://github.com/urduhack/urduhack/blob/master/README.md) targets Python 3.6–3.7, so it was not added to this Python ≥3.11 application. |
| `san` | Add sandhi-aware analysis and source alignment. The [Sanskrit parser API](https://kmadathil.github.io/sanskrit_parser/build/html/sanskrit_parser_code.html) produces lexical analyses; reconstructing trustworthy highlight spans requires additional integration and evaluation. |
| `ckt` | One malformed row (67) combines lemma and form in a single column. Source was preserved; choose an explicit, attributable repair. |
| `evn itl kca kir tgk` | Review mixed transcription/lookalike characters and normal reader-text alignment. |
| `kor` | Whitespace eojeol boundaries work, but particle-bearing forms require dictionary/analyzer alignment before promotion. |
| `cpa pei` | Unresolved morpheme/alternative notation; Chinantec has a partial rebuilt database, Chichimec still has no accepted mappings. |
| `otm` | Implement a deliberate phrase-entry/multiword-lookup design, or obtain suitable single-unit data. |
| `epo grn mon oss pnb pqm` | Obtain inflection data; review script/orthography before release. |
| `pib` | The recognized Yine source file is empty; obtain data. |
| `zxx` | Excluded: “no linguistic content” is not a language pack. |

Further tests should use reviewed real-language corpora and publish lookup
coverage, segmentation precision and recall, speed and memory measurements.
The present tests demonstrate implementation behavior and source preservation;
they are not a corpus-quality benchmark. The dedicated Tibetan, Urdu and
Sanskrit analyzers were **not implemented or declared complete** in this work.

## Verification and artifacts

- Full application suite: **173 passed**, including the installed optional
  Japanese adapter (no skipped tests in the final run).
- All **176 configured packs** in the refresh were validated before local
  replacement, including 165 ready packs and 11 retained configured dev
  packs. The three later hyphen rebuilds also passed validation. No user
  known lists or history files were changed.
- Tested tone-bearing vocabulary through frequency sorting, contexts,
  known-list updates, local installation and packaging. Tested dictionary-
  first elision, unavailable capability errors, and Japanese inflection
  fallback with an emoji preceding the highlighted token. Refresh tests also
  verify promotion backups and preservation of the destination on a failed
  staging validation.
- Built the wheel and source distribution in an isolated environment;
  `twine check` passed for both. Confirmed that the catalog and tokenizer
  modules are packaged and maintenance tools remain outside distributions.
- Confirmed README name ordering and exact agreement of the 166 displayed
  entries with CLI names and the 165-code registries. `git diff --check`
  passed. `make -n release` resolves to the existing maintenance helper.
- CLI smoke checks passed for Russian, tone-bearing Chatino/Pame and the
  Japanese dev adapter. Upstream source files were only read.

Previous local packs are retained in ignored backups:

```text
maintenance/work/language-refresh-20261008/backups/
maintenance/work/language-hyphens-20261008/backups/
```

The original phase summary is [language-refresh.json](language-refresh.json);
the later three-profile rebuild is [language-hyphen-refresh.json](language-hyphen-refresh.json).
Missing/empty source classifications are in [language-data-status.json](language-data-status.json).
The [original assessment](language-boundaries-plan.md) remains a dated
pre-implementation snapshot; use this report for current counts.

Pack files remain Git-ignored. Their local changes are real inputs to the
release helper even though they do not appear in `git diff`. The catalogs,
converter, refresh tool, tests, documentation and summary reports are tracked
source changes. Reproduce the local preparation with full upstream data using:

```sh
cd ~/dev/blitzer-py
.venv/bin/python -m maintenance.language_refresh          # preview
.venv/bin/python -m maintenance.language_refresh --apply  # local rebuild/apply
```

No repeat refresh is required before releasing this already prepared checkout.
Keep ignored packs/backups/work reports available until publication succeeds.
The work-directory archives were generated during preparation; release from
the current packs through `make release`, which regenerates publication assets.

## Make a new GitHub release

The application version remains **0.2.5**. If unchanged before publication,
the existing helper will release **0.2.6**. Do not bump it manually.
The development languages above are excluded from release assets.

From the prepared checkout:

```sh
cd ~/dev/blitzer-py
.venv/bin/python -m pip install -e '.[dev]'
git branch --show-current
git status --short
git diff
git diff --check
.venv/bin/python -m pytest -q -p no:cacheprovider
make -n release
make release
```

Run on `master`, as required by the helper. Inspect new/untracked reports and
modules as well as the diff: the release commit includes all non-ignored
changes. To include the optional Japanese integration check in a fresh
environment, install `'.[dev,japanese]'` instead of `'.[dev]'` before testing.
That extra is not needed to publish the ready packs.

`make release` is the real publication step. It:

1. Checks GitHub authentication, branch, Git identity and remote ancestry.
2. Compares local pack contents with stable releases, validates/packages
   changed or new packs, and runs the tests.
3. Increments the application's patch version once and checks distributions.
4. Commits all non-ignored changes, pushes `master` and the version tag.
5. Uploads assets and a cumulative manifest to a draft, then publishes the
   GitHub release. GitHub Actions handles PyPI publication afterward.

Scope/readme/provenance changes affect existing pack fingerprints too, so
expect uploads for existing packs as well as the 46 additions. Initial
manifest/bootstrap comparison and large-pack uploads can take time. Configuration
format 2 is new; users should upgrade the application before those packs.

If GitHub CLI or authentication is not already configured:

```sh
brew install gh
gh auth login --hostname github.com --git-protocol https --web --scopes workflow
gh auth setup-git
gh auth status
```

The one-time GitHub `pypi` environment and PyPI Trusted Publisher setup is
documented in [RELEASING.md](../RELEASING.md). The local checks above do not
verify those external account settings; configure them before publication if
they are not already in place. No new token should be put in repository files.

After publication:

```sh
gh release list --repo samiddhi/blitzer-py --limit 5
gh run list --repo samiddhi/blitzer-py --workflow publish.yml
gh run watch RUN_ID --repo samiddhi/blitzer-py --exit-status
```

Replace `RUN_ID` with the numeric Actions ID. If the local helper fails, fix
the reported error and rerun `make release`; keep its ignored
`maintenance/work/pending-release.json` checkpoint. If GitHub publication
succeeded but the PyPI workflow failed, retry that workflow instead:

```sh
gh run rerun RUN_ID --repo samiddhi/blitzer-py --failed
```

After the new application is published, a user can upgrade it and test a new
pack through the normal installer:

```sh
python -m pip install --upgrade bltzr
bltzr install-plugin pbs --replace
bltzr blitz -l pbs -t 'toho1ʔo.' --lemmatize --context
```
