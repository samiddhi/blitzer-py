# Language-pack word boundaries and display names: assessment and plan

Date: 2026-10-08. This is the original assessment and inventory snapshot.
Implementation results and remaining work are recorded in the
[project status report](project-status-20261008.md).

## Decisions

Script is not a reliable release criterion. Most non-Latin dev packs use
word spacing and do not need a dictionary segmenter. Conversely, Latin
orthographies can need rules for apostrophes, dots, tone digits or clitics.
Replace the converter's Latin-only readiness gate with explicit reviewed
input-orthography and tokenization profiles.

The present inventory contains **119 implemented pack directories** and
**68 dev directories**. Of the dev directories, 51 have configurations and
databases; 17 contain only a deferral notice. `base` is a built-in mode,
not a pack. The requested CLI lists 119 packs plus `base`; it does not
recurse into `dev`. A dev directory is not necessarily a usable pack.

Recommended dev queues (every directory is assigned in the inventory below):

| Queue | Count | Decision |
| --- | ---: | --- |
| A | 35 | Existing space/punctuation boundaries are suitable for an initial release; validate data and real text before promotion. |
| B | 13 | Space-delimited languages needing shared character/format handling or a reviewed orthography profile. No dictionary segmenter required for the stated initial scope. |
| C | 8 | Space-delimited datasets needing custom token acceptance for tone notation and sometimes morpheme notation. Rebuild from source; currently no usable database. |
| D | 4 | Dedicated segmentation/analysis needed for ordinary text: Japanese, Tibetan, Urdu and Sanskrit. |
| E | 8 | Missing/empty data or invalid language identity; data/identity work precedes release. |

“Suitable” here means boundary-ready, not approved for publication. Dictionary
coverage, omitted multiword forms, malformed rows, names and normalizations
remain separate acceptance checks. No pack was moved, rebuilt or published.

## What the code actually does

`blitzer/processing.py:tokenize` is **not** a plain `split()` on spaces. It
starts on any Unicode letter, continues through letters and combining
marks, and permits internal ASCII/curly apostrophes followed by a letter.
Digits, most punctuation, hyphens and format controls terminate a token.
It already accepts Cyrillic, Greek, Arabic, Hebrew, Indic, Ethiopic,
Georgian, Armenian, Gothic and Hangul letters. It does not implement UAX #29.

The same universal tokenizer influences multiple paths:

- `core.py:Blitzer.blitz` extracts the keys used to query the database.
- `processing.py:collect_vocabulary` tokenizes again for counts and contexts.
- `_word` validates source mappings, known lists, frequencies and pack rows.
- `maintenance/unimorph.py` uses `_word` before it builds packs.
- Pack format 1 permits metadata and normalization only; there is no tokenizer
  setting. Substitutions happen **after** tokenization and cannot restore a
  character or boundary already discarded.

The converter's `deferred_reasons` rejects datasets with at least 1% non-Latin
rows regardless of their actual boundaries. `SEGMENTATION_CODES` correctly
flags several unspaced languages but misses Urdu and Sanskrit. Of its listed
codes, only `bod` and `jpn` occur in this dev inventory; Chinese, Thai, Lao,
Khmer, Myanmar and Dzongkha are future cases, not existing dev packs.

Reproduced with the current tokenizer (illustrative inputs, not gold fixtures):

| Input | Current tokens | Implication |
| --- | --- | --- |
| `東京都に行く` | one entire run | Japanese lexical words are not recovered. |
| `བོད་སྐད་` | `བོད`, `སྐད` | Tibetan syllable delimiters do not establish lexical word boundaries. |
| `한국어를 배운다` | `한국어를`, `배운다` | Korean whitespace units are recovered; particles still affect dictionary lookup. |
| `می‌روم` (U+200C) | `می`, `روم` | Persian ZWNJ wrongly splits an orthographic word. |
| `क्‍ष` (U+200D) | `क्`, `ष` | Indic joiner wrongly splits a letter cluster. |
| `col·legi` | `col`, `legi` | Catalan middle dot wrongly splits a word. |
| `l’homme` | `l’homme` | French elision may hide the dictionary headword `homme`. |
| `'o'odham` | `o'odham` | Initial glottal apostrophe is lost. |
| `sqan¹` | `sqan` | Tone suffix is lost. |
| `toho1ʔo` | `toho`, `ʔo` | Internal numeric tone notation breaks a lexical form. |

## Dev implementation queues

### A: normal boundaries; promote in reviewed batches

The full code list is in the inventory. Most are Cyrillic languages,
Arabic varieties, Greek, Armenian, Georgian, Gothic or Amharic. Their
non-Latin scripts alone do not call for a segmenter.

Special conditions within this queue:

- `afb`, `ara`, `arz`: keep whitespace words as the first unit. Assess
  vocalized/unvocalized lookup and attached clitics using representative text.
  Clitic analysis is optional additional coverage, not evidence of an
  unspaced writing system. `ara` source scope is Modern Standard Arabic;
  distinguish that from the broader ISO Arabic macrolanguage.
- `amh`: Ethiopic wordspace U+1361 is punctuation and already separates
  runs. Add a real-text fixture; do not replace it with a requirement for
  ASCII spaces.
- `hbs`: retain and document both Latin and Cyrillic data. A mixed-script
  inventory is not a segmentation failure. Do not transliterate the entire
  pack silently.
- `evn`, `itl`, `kca`, `kir`, `tgk`: inspect transcription/mixed-script
  conventions. Example Kyrgyz source strings mix Latin and Cyrillic
  lookalikes; successful tokenization does not guarantee useful matching.
- `ckt`: one malformed source row still blocks promotion until inspected.
  Modifier-letter apostrophe U+02BC is already accepted as a Unicode letter.
- `chu`, `got`, `grc`, `xcl`: initial scope is edited text with explicit
  boundaries. Unspaced historical manuscripts require separate analysis.
  Ancient Greek source rows also contain articles and multiword forms.
- `kor`: standard modern Korean whitespace units (eojeol) need no mandatory
  dictionary segmenter. Particle-bearing nouns and fused endings can fail
  UniMorph lookup; measure coverage before describing it as full lexical
  extraction. Add a Korean analyzer only if lexical subunits or badly spaced
  text are in scope. This distinction follows [Korean UD's tokenization
  documentation](https://universaldependencies.org/ko/index.html).

### B: space-delimited; fix shared character handling first

| Codes | Needed work |
| --- | --- |
| `asm ben bra guj hin kan mag tel` | Keep internal ZWJ/ZWNJ in Indic clusters; retain combining signs. Review punctuation/sentence boundaries and normalization. Existing simple source rows already tokenize. |
| `fas ckb` | Preserve internal ZWNJ; review Arabic/Persian letter variants and diacritics. Persian has many multiword predicates; Sorani source also has `+` notation requiring source interpretation. |
| `heb yid` | Handle geresh/gershayim and orthographic apostrophe/quote variants contextually; retain marks. Do not treat every quote as word-internal. |
| `sjo` | Review Mongolian-script format characters and narrow no-break spacing/suffix conventions; variation selectors are marks and already survive, but format controls may split words. |

These are shared, constrained profiles, not thirteen new segmentation engines.
Preserve joiners in source spans; define lookup-key behavior separately.
Unicode describes ZWNJ inside Persian words in [chapter 9](https://unicode.org/versions/Unicode17.0.0/core-spec/chapter-9/).
The source samples reviewed for Xibe had no tokenizer rejection; its broader
format-character requirements are a review item, not a demonstrated source defect.

### C: tone/notation profiles; do not strip tones to make rows pass

These eight datasets all have zero accepted mappings in the conversion report.
They generally use spaces between orthographic units; they do not need
Japanese-style segmentation. They need the tokenizer and builder to agree
on what constitutes an intact lexical form.

| Code | Language | Observed source evidence | Action |
| --- | --- | --- | --- |
| `azg` | San Pedro Amuzgos Amuzgo | `m⁵mà¹`, `toanʔ⁵³` | Permit bounded tone digits internally/at the end; preserve glottal letters. |
| `cly` | Eastern Highland Chatino | `sqan¹`, `nsqan¹ wa⁴²` | Preserve tone suffixes; separately decide how multiword paradigms are represented. |
| `cpa` | Tlatepuzco Chinantec | `ɁḗɁ²`, `mi³-ɁḗɁ²` | Preserve tones; decide whether hyphen is orthographic or morphological source notation. |
| `ctp` | Yaitepec Chatino | `nkinu²¹`, `nkinu³ᐟ` | Preserve tones and review superscript-like U+141F. The converter's “CANADIAN” label does not prove the language uses Canadian syllabics. |
| `otm` | Sierra Otomi | `bẹ¹nt’i`, `dí-n bẹnt’i` | Preserve internal tones and apostrophes; audit hyphens and multiword analyses. |
| `pbs` | Central Pame | `toho1ʔo`, `toho1ʔomʔ` | Internal ASCII tone digits require a language-specific rule. |
| `pei` | Chichimec / Chichimeca-Jonaz | `–nu`, `e¹nu²` | Preserve tone digits; interpret the initial dash as source notation before choosing a token rule. |
| `xty` | Yoloxóchitl Mixtec | `chi³chin⁴`, `chi¹⁴chi⁴` | Preserve internal and final tone digits. |

Use documented source conventions and reviewed text to specify these profiles.
If a dataset is a phonological/morphological transcription rather than a
normal reader orthography, label that scope explicitly. Do not indiscriminately
allow all digits or symbols in every language. Multiword analyses cannot
be recovered merely by accepting tone digits.

### D: dedicated segmentation/analysis

| Code | Language | Decision and first implementation milestone |
| --- | --- | --- |
| `jpn` | Japanese | Use a maintained Japanese tokenizer/analyzer; verify segmentation granularity and dictionary form alignment with this pack. Its 12,687 accepted rows show only that isolated forms validate, not that prose works. |
| `bod` | Tibetan | Segment lexical words across tsheg-delimited units. Audit source punctuation such as final shad (`ཀུམ།`) before rebuilding. Simply splitting at tsheg produces subword units. |
| `urd` | Urdu | Ordinary digital text can omit word spaces and insert spaces within words. Use an evaluated Urdu segmenter, with a documented limited mode for already segmented text if useful. Fixing ZWNJ alone is insufficient. |
| `san` | Sanskrit | Use sandhi-aware lexical analysis for joined text. A whitespace-only mode is acceptable only for explicitly presegmented/unsandhied input. Reconstructed lexical forms need a separate lookup key because they may differ from the source substring. |

Tibetan syllable punctuation and spaces are described in [Unicode chapter
13](https://unicode.org/versions/Unicode17.0.0/core-spec/chapter-13/).
Urdu's insertion/omission problems are documented by [the Urdu segmentation
research paper](https://aclanthology.org/2020.winlp-1.41/).
Sanskrit's boundary transformations are documented by [the Sanskrit
segmentation paper](https://aclanthology.org/C16-1048/).
These are language-specific reasons for queue D, not deductions from script.

### E: source/identity work before tokenization

| Code | Intended identity | Decision |
| --- | --- | --- |
| `epo` | Esperanto | Normal spaces; obtain inflection data first. |
| `grn` | Guarani | Normal spaces with a reviewed apostrophe/glottal profile; obtain data first. |
| `mon` | Mongolian | Obtain data and specify Cyrillic versus traditional script; Cyrillic baseline, traditional script requires format/suffix review. |
| `oss` | Ossetian | Normal spaces; obtain data first. |
| `pnb` | Western Punjabi | Obtain data and review Shahmukhi spacing on real text. Do not automatically transfer either English or Urdu segmentation assumptions. |
| `pqm` | Passamaquoddy-Maliseet | Space-delimited; obtain data and review orthographic punctuation. |
| `pib` | Yine | Source file is empty (zero source rows). Its “No mappings fit” notice is misleading; classify as empty/missing data. No evidence of a segmentation blocker. |
| `zxx` | No linguistic content | ISO special code, not a language. Exclude from language-pack development and release candidates. |

## Existing packs: where the Latin assumption fails

No implemented pack in this inventory is demonstrated to require an unspaced
prose segmenter as a mandatory default. Several are nevertheless insufficient
for their full advertised orthography or lexical coverage. Space-delimited
is not synonymous with compatible with the current character loop.

| Priority | Packs | Failure/review requirement |
| --- | --- | --- |
| Highest | `czn`, `ote` | Zenzontepec Chatino retains 13 rows and excludes 1,554; Mezquital Otomi accepts 572 and excludes 32,590. Tone notation is a demonstrated blocker. Put under limited-support review and rebuild after queue C's rules. |
| High | `cat` (and review `oci`) | Keep orthographic middle dot inside words. Catalan hyphenated clitics also occur in source (`acostumar-se`). Decide lookup/clitic policy separately. |
| High | `ood`, `see`, `hai` | O'odham source has internal colons (`ba:b`); Seneca has final glottal apostrophes (`gatgëhjista'`); Haida has internal periods (`gatáa.ang`). These are demonstrated tokenizer rejections. Review initial/final apostrophes and orthographic punctuation with source documentation. |
| High | `fra frm fro ita`; review `cat oci vec nap` | Elisions/clitics can remain attached to a whole token and hide the lookup headword. Preserve lexical apostrophe words (e.g. `aujourd’hui`); use documented clitic rules or dictionary fallback, not an unconditional apostrophe split. |
| High | `gle cym gla cor bre` | Mutation prefixes, apostrophe particles and hyphens need reviewed lookup/boundary behavior. Many rejected source rows are multiword paradigms, not proof that these languages lack spaces. |
| High | `pli` | Pack substitutions delete `'`, `’`, `”` after tokenization. A boundary already created by a leading/trailing apostrophe or double quote cannot be repaired. Review elision/quote conventions and joined/sandhied text. Default scope can remain space-delimited Roman Pali; do not claim general sandhi decomposition. |
| High | `slp zpv` | Lamaholot `laŋoʔ=kə̃` and Zapotec `a+bann` show `=`/`+` source notation. Decide whether to convert notation into orthography, preserve a lexical unit, or represent multiple units. A global symbol whitelist would be unjustified. |
| Review | `nav mlt orm uzb` | Glottal/apostrophe variants and quote-like letters must match source and reader orthography. U+02BC and U+02BB are letters and already survive; test punctuation variants and boundary positions. Do not conflate apostrophe normalization with segmentation. |
| Review | `cre uig tat aze sdh kmr` | Current packs may cover a Latin orthography/transcription while normal reader text uses another script or multiple scripts. Retain the supported orthography label and measure native-script coverage; script recognition does not add missing dictionary entries. |
| Review | Historical packs `ang frm fro gmh gml goh lat non osx sga xno` | Default is edited, spaced text. Historical scriptio continua and manuscript notation need an explicit additional mode if desired. |

Unicode's [UAX #29](https://www.unicode.org/reports/tr29/) explains why generic
word boundaries need tailoring; it covers apostrophe ambiguity, internal
punctuation and languages requiring dictionary segmentation. Its word-boundary
algorithm is a reference, not an automatic choice of learner vocabulary units.

### Loss of source coverage is a separate release criterion

Large `unsupported_rows` counts are a signal to inspect reasons, not a
measurement of prose segmentation accuracy. Samples show multiword paradigms
in Turkish, Albanian, Akan, Hiligaynon, Kongo, Irish and Welsh, among others.
Do not split a multiword form into components and map every component to the
phrase lemma; that would create false mappings. Decide between supported
phrase lookup, a reviewed extraction rule, or explicit documented omission.

The appendix lists all ready UniMorph datasets with unsupported-row counts
greater than 25% of accepted rows. This is a triage threshold, not a quality
score. Recompute rejection counts by reason (multiword, numeric tone,
punctuation, formatting, malformed, script exclusion) on the full source
before choosing each rebuild. Top-level `build-info.json` counts can describe
only already-filtered input; use its `unimorph` section and the maintenance
conversion report to see original losses.

Other implemented packs remain suitable candidates for normal boundaries;
the complete implemented inventory below records that default and the
specific review queues. None receives an unconditional “all text supported”
endorsement based solely on Latin script.

## Display-name audit

Reproduced the exact requested command:

```sh
.venv/bin/bltzr list-languages --plugins-dir ~/dev/blitzer-py/language-packs
```

`Blitzer.language_name` reads installed `config.toml` metadata; it does **not**
use the downloadable-language registry for this listing. Correcting only
`blitzer/language-registry.json` will not fix these local display names.

### Definite faults currently visible (11 packs)

| Code | Current display | Required name |
| --- | --- | --- |
| `ces` | `• ces.xz` | Czech |
| `cym` | `CYM` | Welsh |
| `fry` | `FRY` | Western Frisian |
| `gla` | `GLA` | Scottish Gaelic |
| `kmr` | `KMR` | Northern Kurdish (Kurmanji) |
| `oci` | `OCI` | Occitan |
| `slk` | `Data` | Slovak |
| `tat` | `TAT` | Tatar |
| `tuk` | `TUK` | Turkmen |
| `vec` | `VEC` | Venetian |
| `vot` | `VOT` | Votic |

### Definite faults in configured dev packs (8 additional packs)

| Code | Current metadata | Required name |
| --- | --- | --- |
| `ket` | `Data` | Ket |
| `san` | `Non-UniMorph labels used:` | Sanskrit |
| `syc` | `Caveats` | Classical Syriac |
| `tel` | `TEL` | Telugu |
| `tgk` | `TGK` | Tajik |
| `ukr` | `• ukr.xz` | Ukrainian |
| `urd` | `URD` | Urdu |
| `yid` | `YID` | Yiddish |

Recommended precision improvements, not corrupt-label failures: `ell`
“(Modern) Greek” → “Modern Greek”; `sot` “Sotho” → “Southern Sotho (Sesotho)”;
`swc` “Swahili” → “Congo Swahili”; `xno` “Norman” → “Anglo-Norman”;
`olo` “Livvi” → “Livvi-Karelian”; `ame` “Yanesha” → “Yanesha’” if following
the chosen English naming reference. Adopt one naming convention and retain
recognized aliases rather than insisting that only one exonym is proper.
Review `ara` against its Modern Standard Arabic source scope and `cre`/`que`
against their macrolanguage/dialect scope. These are identity checks, not
automatic changes to code or dictionary content.

The parser in `maintenance/unimorph.py:language_name` takes the first
plausible README line. This explains headings (`Data`, `Caveats`), bullet
filenames and uppercase-code fallbacks becoming names. Use an explicit
reviewed catalog keyed by pack code; upstream READMEs should provide
attribution, not the authoritative display name. [UniMorph's inventory](https://unimorph.github.io/)
is a useful identity reference. Validate exceptional legacy/source codes
such as `mao` and `gal` against the actual dataset; do not silently rename
folders or replace source-specific identities using ISO codes alone.

Synchronize the catalog with pack metadata, application registry and
`maintenance/reports/language-registry.json` (currently a ready-only export).
Keep the complete dev identity catalog separate from the published download
registry until a pack is approved. Update generated README/build provenance
names deliberately and rebuild archives through normal maintenance tooling;
do not edit published artifacts in place. The other currently displayed
names contain no obvious heading/filename/code corruption on this audit,
but dialect scope remains subject to the documented identity review.

## Implementation sequence and acceptance criteria

1. **Fix names and classification first.** Establish the reviewed complete
   catalog, repair the 19 definite metadata faults and review the precision
   list. Add regression coverage for all named failures and ensure both
   installed listing and download listing use correct names. Correct the
   empty `pib` diagnosis and exclude `zxx`. Do not expand the downloadable
   registry just to make dev names available.
2. **Specify tokenization profiles.** Keep the current default compatible.
   Add declarative, validated profile IDs owned by the application, with
   explicit orthography/scope documentation. Packs remain data-only: no
   imported Python or executable tokenizer code from a downloaded pack.
   Decide a pack-format version bump or negotiated capability before adding
   fields: the current strict format-1 reader rejects unknown fields.
3. **Unify processing and validation.** Resolve one profile per language and
   use its output for both database query keys and occurrence aggregation.
   Preserve Python string offsets and original substrings. Give lexemes a
   separate lookup form when an analyzer reconstructs text (especially
   Sanskrit). Revisit known-list, lemma, frequency and builder validation:
   an isolated lemma is not necessarily one surface token in ordinary text.
   Define how phrases and reconstructed forms are represented before relaxing
   `_word`; consistency must cover exclusions, tracking and frequency data.
4. **Implement shared orthographic rules.** Handle selected format controls,
   quote variants, internal middle dot/colon and approved tone notation.
   Keep punctuation interpretation contextual and profile-specific. Add
   focused tests with original offsets, NFC/NFD, surrounding quotation marks,
   numeric noise, real prose and ambiguous apostrophes. Ordinary English
   behavior must remain stable.
5. **Promote queue A in small batches.** Start with clean Cyrillic/Georgian
   examples (`ady`, `bak`, `kat`, `mkd`, `ukr` after its name fix), then the
   other boundary-ready scripts. Remove script-only deferral through an
   explicit reviewed capability decision. Run pack checks, source-loss
   reports and representative prose lookups; inspect all remaining source
   errors. Address Korean dictionary alignment explicitly before promotion.
6. **Rebuild B/C and affected implemented packs.** Use full upstream data,
   not the already-truncated pack databases. Prioritize `czn`, `ote`, `cat`,
   `ood`, `see`, `hai` and the tone-bearing dev datasets. Quantify recovered
   rows and residual losses by reason. Record supported script/transcription
   and limitations in each pack README and generated report.
7. **Prototype D behind explicit capabilities.** Evaluate maintained
   analyzers against small, reviewed language-specific gold corpora and the
   current dictionaries. Compare token boundaries, dictionary lookup recall,
   speed, memory, install size and licensing. Pin/test the selected version
   and return a clear missing-capability error when unavailable. Never
   silently process an unspaced language as one large letter run.
8. **Finish release qualification.** Validate sentences separately: default
   `[.!?]` plus whitespace/newline behavior misses punctuation such as Arabic
   question mark, danda, Tibetan shad and Japanese full stop. Add reviewed
   sentence handling using existing overrides or supported profiles so
   context highlighting works. Package/install round-trip, verify CLI names
   against the complete expected inventory, run the project's tests, and
   only then propose publication under the normal release process.

Do not promise perfect decomposition of compounds for German, Finnish,
Greenlandic or other polysynthetic/agglutinative languages. An orthographic
word can validly contain many morphemes. Morphological decomposition is a
separate product decision unless required to align a chosen analyzer and
dictionary (as for Korean or Sanskrit).

## Evidence and limits

Local evidence: requested CLI output; every implemented/dev config or
deferral notice; `maintenance/reports/unimorph.json`; selected `build-info`
provenance; tokenizer demonstrations; and upstream rows read through the
existing converter from `maintenance/unimorph-data` (read-only symlink).
Source examples were sampled, with targeted rejection searches bounded to
the first 4,000 rows of the first recognized table. This is an inventory and
architecture audit, not a full corpus evaluation or linguistic certification.
The dev classifications are recommendations with the explicit conditions
above; unusual scripts/transcriptions require source and reader review.

No application tests were needed for this documentation-only change.
Future implementation must run the checks described above. The next action
is for the user to select/authorize an implementation phase.

## Complete inventories

The following tables are generated from the current local inventory and
conversion report, with the reviewed queue assignments above. Counts refer
to accepted/unsupported source rows, not final database size or accuracy.

### All 68 dev directories

| Code | Reviewed language name | Queue | Database | Accepted | Unsupported |
| --- | --- | --- | --- | ---: | ---: |
| `ady` | Adyghe | A | yes | 20,091 | 384 |
| `afb` | Gulf Arabic | A | yes | 32,221 | 15 |
| `amh` | Amharic | A | yes | 46,224 | 0 |
| `ara` | Modern Standard Arabic | A | yes | 1,115,468 | 1,708 |
| `arz` | Egyptian Arabic | A | yes | 25,394 | 0 |
| `asm` | Assamese | B | yes | 75,946 | 18,201 |
| `azg` | San Pedro Amuzgos Amuzgo | C | no | 0 | 12,204 |
| `bak` | Bashkir | A | yes | 11,856 | 312 |
| `bel` | Belarusian | A | yes | 15,044 | 1,069 |
| `ben` | Bengali | B | yes | 3,293 | 1,150 |
| `bod` | Tibetan | D | no | 0 | 5,067 |
| `bra` | Braj | B | yes | 1,814 | 7 |
| `bul` | Bulgarian | A | yes | 44,810 | 10,920 |
| `chu` | Old Church Slavic | A | yes | 4,148 | 0 |
| `ckb` | Central Kurdish | B | yes | 997 | 4 |
| `ckt` | Chukchi | A | yes | 242 | 0 |
| `cly` | Eastern Highland Chatino | C | no | 0 | 4,716 |
| `cpa` | Tlatepuzco Chinantec | C | no | 0 | 7,893 |
| `ctp` | Yaitepec Chatino | C | no | 0 | 3,796 |
| `ell` | (Modern) Greek | A | yes | 148,078 | 51,679 |
| `epo` | Esperanto | E | no | 0 | 0 |
| `evn` | Evenki | A | yes | 11,367 | 4 |
| `fas` | Persian | B | yes | 5,589 | 31,539 |
| `got` | Gothic | A | yes | 203,922 | 244 |
| `grc` | Ancient Greek | A | yes | 19,575 | 22,018 |
| `grn` | Guarani | E | no | 0 | 0 |
| `guj` | Gujarati | B | yes | 16,135 | 7,892 |
| `hbs` | Serbo-Croatian | A | yes | 685,431 | 155,368 |
| `heb` | Hebrew | B | yes | 66,353 | 2 |
| `hin` | Hindi | B | yes | 2,249 | 52,189 |
| `hye` | Armenian | A | yes | 253,599 | 80,271 |
| `itl` | Itelmen | A | yes | 2,686 | 15 |
| `jpn` | Japanese | D | yes | 12,687 | 0 |
| `kan` | Kannada | B | yes | 6,402 | 0 |
| `kat` | Georgian | A | yes | 92,000 | 95 |
| `kaz` | Kazakh | A | yes | 37,093 | 3,547 |
| `kbd` | Kabardian | A | yes | 3,080 | 12 |
| `kca` | Khanty | A | yes | 2,055 | 0 |
| `ket` | Ket | A | yes | 972 | 212 |
| `khk` | Khalkha Mongolian | A | yes | 30,143 | 0 |
| `kir` | Kyrgyz | A | yes | 3,066 | 2,478 |
| `kjh` | Khakas | A | yes | 1,184 | 16 |
| `kor` | Korean | A | yes | 233,716 | 7,607 |
| `mag` | Magahi | B | yes | 1,355 | 3 |
| `mkd` | Macedonian | A | yes | 155,036 | 13,021 |
| `mon` | Mongolian | E | no | 0 | 0 |
| `oss` | Ossetian | E | no | 0 | 0 |
| `otm` | Sierra (Eastern Highland) Otomi | C | no | 0 | 31,380 |
| `pbs` | Central Pame | C | no | 0 | 12,528 |
| `pei` | Chichimec | C | no | 0 | 15,120 |
| `pib` | Yine | E | no | 0 | 0 |
| `pnb` | Western Punjabi | E | no | 0 | 0 |
| `pqm` | Passamaquoddy-Maliseet | E | no | 0 | 0 |
| `pus` | Pashto | A | yes | 5,253 | 1,692 |
| `rus` | Russian | A | yes | 433,772 | 39,709 |
| `sah` | Sakha | A | yes | 577,373 | 13,392 |
| `san` | Sanskrit | D | yes | 33,847 | 0 |
| `sjo` | Xibe | B | yes | 3,054 | 0 |
| `syc` | Classical Syriac | A | yes | 31,871 | 101 |
| `tel` | Telugu | B | yes | 1,548 | 0 |
| `tgk` | Tajik | A | yes | 77 | 0 |
| `tyv` | Tuvan | A | yes | 494,280 | 91,900 |
| `ukr` | Ukrainian | A | yes | 20,556 | 348 |
| `urd` | Urdu | D | yes | 1,264 | 11,308 |
| `xcl` | Classical Armenian | A | yes | 90,688 | 6,493 |
| `xty` | Yoloxóchitl Mixtec | C | no | 0 | 3,057 |
| `yid` | Yiddish | B | yes | 7,923 | 63 |
| `zxx` | No linguistic content | E | no | 0 | 0 |

### All 119 implemented packs

“Normal baseline” means no custom segmentation requirement identified in
this audit; all packs still require coverage and representative-text checks.

| Code | Current metadata name | Boundary assessment |
| --- | --- | --- |
| `afr` | Afrikaans | Normal baseline |
| `ail` | Eibela | Normal baseline |
| `aka` | Akan | Normal baseline |
| `ame` | Yanesha | Normal baseline |
| `ang` | Old English | Edited historical text only |
| `arn` | Mapudungun | Normal baseline |
| `ast` | Asturian | Normal baseline |
| `aym` | Aymara | Normal baseline |
| `aze` | Azerbaijani | Script / dialect scope |
| `bre` | Breton | Mutation / particles / hyphens |
| `cat` | Catalan | Internal punctuation / glottal boundaries |
| `ceb` | Cebuano | Normal baseline |
| `ces` | • ces.xz | Normal baseline; fix display name |
| `cni` | Ashaninka | Normal baseline |
| `cor` | Cornish | Mutation / particles / hyphens |
| `cre` | Cree | Script / dialect scope |
| `crh` | Crimean Tatar | Normal baseline |
| `csb` | Kashubian | Normal baseline |
| `cym` | CYM | Mutation / particles / hyphens; fix display name |
| `czn` | Zenzontepec Chatino | Tone profile / major loss |
| `dak` | Dakota | Normal baseline |
| `dan` | Danish | Normal baseline |
| `deu` | German | Normal baseline |
| `dje` | Zarma | Normal baseline |
| `dsb` | Lower Sorbian | Normal baseline |
| `eng` | English | Normal baseline |
| `est` | Estonian | Normal baseline |
| `eus` | Basque | Normal baseline |
| `fao` | Faroese | Normal baseline |
| `fra` | French | Elision / clitics |
| `frm` | Middle French | Elision / clitics |
| `fro` | Old French | Elision / clitics |
| `frr` | North Frisian | Normal baseline |
| `fry` | FRY | Normal baseline; fix display name |
| `fur` | Friulian | Normal baseline |
| `gaa` | Gã | Normal baseline |
| `gal` | Galician | Normal baseline |
| `gla` | GLA | Mutation / particles / hyphens; fix display name |
| `gle` | Irish | Mutation / particles / hyphens |
| `glv` | Manx | Normal baseline |
| `gmh` | Middle High German | Edited historical text only |
| `gml` | Middle Low German | Edited historical text only |
| `goh` | Old High German | Edited historical text only |
| `gsw` | Swiss German | Normal baseline |
| `gup` | Kunwinjku | Normal baseline |
| `hai` | Haida | Internal punctuation / glottal boundaries |
| `hil` | Hiligaynon | Normal baseline |
| `hsb` | Upper Sorbian | Normal baseline |
| `hsi` | Kholosi | Normal baseline |
| `hun` | Hungarian | Normal baseline |
| `ind` | Indonesian | Normal baseline |
| `isl` | Icelandic | Normal baseline |
| `ita` | Italian | Elision / clitics |
| `izh` | Ingrian | Normal baseline |
| `kal` | Greenlandic | Normal baseline |
| `klr` | Khaling | Normal baseline |
| `kmr` | KMR | Script / dialect scope; fix display name |
| `kod` | Kodi | Normal baseline |
| `kon` | Kongo | Normal baseline |
| `krl` | Karelian | Normal baseline |
| `lat` | Latin | Edited historical text only |
| `lav` | Latvian | Normal baseline |
| `lin` | Lingala | Normal baseline |
| `lit` | Lithuanian | Normal baseline |
| `liv` | Livonian | Normal baseline |
| `lld` | Ladin | Normal baseline |
| `lud` | Ludian | Normal baseline |
| `lug` | Luganda | Normal baseline |
| `mao` | Māori | Normal baseline |
| `mlg` | Malagasy | Normal baseline |
| `mlt` | Maltese | Apostrophe / orthography review |
| `mwf` | Murrinhpatha | Normal baseline |
| `nap` | Neapolitan | Elision / clitics |
| `nav` | Navajo | Apostrophe / orthography review |
| `nds` | Low German | Normal baseline |
| `nld` | Dutch | Normal baseline |
| `nno` | Norwegian Nynorsk | Normal baseline |
| `nob` | Norwegian Bokmål | Normal baseline |
| `non` | Old Norse | Edited historical text only |
| `nya` | Chewa | Normal baseline |
| `oci` | OCI | Elision / clitics; fix display name |
| `olo` | Livvi | Normal baseline |
| `ood` | O'odham | Internal punctuation / glottal boundaries |
| `orm` | Oromo | Apostrophe / orthography review |
| `osx` | Old Saxon | Edited historical text only |
| `ote` | Mezquital Otomi | Tone profile / major loss |
| `pli` | Pali | Pali elision / scope |
| `pol` | Polish | Normal baseline |
| `por` | Portuguese | Normal baseline |
| `que` | Quechua | Normal baseline |
| `ron` | Romanian | Normal baseline |
| `sdh` | Southern Kurdish | Script / dialect scope |
| `see` | Seneca | Internal punctuation / glottal boundaries |
| `sga` | Old Irish | Edited historical text only |
| `shp` | Shipibo-Konibo | Normal baseline |
| `slk` | Data | Normal baseline; fix display name |
| `slp` | Lamaholot | Source morpheme notation |
| `slv` | Slovenian | Normal baseline |
| `sme` | Northern Sami | Normal baseline |
| `sna` | Shona | Normal baseline |
| `sot` | Sotho | Normal baseline |
| `spa` | Spanish | Normal baseline |
| `sqi` | Albanian | Normal baseline |
| `swc` | Swahili | Normal baseline |
| `swe` | Swedish | Normal baseline |
| `tat` | TAT | Script / dialect scope; fix display name |
| `tgl` | Tagalog | Normal baseline |
| `tuk` | TUK | Normal baseline; fix display name |
| `tur` | Turkish | Normal baseline |
| `uig` | Uyghur | Script / dialect scope |
| `uzb` | Uzbek | Apostrophe / orthography review |
| `vec` | VEC | Elision / clitics; fix display name |
| `vep` | Veps | Normal baseline |
| `vot` | VOT | Normal baseline; fix display name |
| `vro` | Võro | Normal baseline |
| `wmt` | Walmajarri | Normal baseline |
| `xno` | Norman | Edited historical text only |
| `zpv` | Chichicapan Zapotec | Source morpheme notation |
| `zul` | Zulu | Normal baseline |

### Implemented UniMorph packs needing source-loss triage

Threshold: unsupported rows > 25% of accepted rows. Pali uses a separate
source and is not in this conversion report.

| Code | Accepted rows | Unsupported rows |
| --- | ---: | ---: |
| `aka` | 2,295 | 1,887 |
| `cor` | 207 | 262 |
| `cre` | 1,527 | 8,050 |
| `cym` | 7,564 | 3,077 |
| `czn` | 13 | 1,554 |
| `est` | 27,454 | 10,761 |
| `frr` | 1,267 | 1,937 |
| `gle` | 43,577 | 63,721 |
| `hai` | 4,699 | 2,341 |
| `hil` | 561 | 695 |
| `kon` | 400 | 428 |
| `krl` | 178,804 | 217,605 |
| `nds` | 5,762 | 4,032 |
| `olo` | 834,827 | 337,307 |
| `ood` | 958 | 670 |
| `orm` | 688 | 1,358 |
| `ote` | 572 | 32,590 |
| `ron` | 59,783 | 20,483 |
| `see` | 891 | 4,569 |
| `slk` | 21,292,927 | 7,135,685 |
| `slp` | 85 | 288 |
| `sqi` | 14,732 | 18,751 |
| `tgl` | 2,304 | 608 |
| `tur` | 248,925 | 321,495 |
| `uzb` | 9,842 | 27,449 |
| `vep` | 544,726 | 217,393 |
| `vro` | 343 | 169 |
| `zpv` | 630 | 534 |
