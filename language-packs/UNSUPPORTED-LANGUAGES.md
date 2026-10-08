# Languages without a release-ready pack

This table explains what is needed to implement or finish the languages
currently absent from the supported-language list. Status as of 2026-10-08.
Some have development packs; others have no local source dataset yet.

If your language is absent from this table too, open a pull request, ideally
with a source of inflectional data for that language. Include its license,
attribution, language code and supported script or orthography where available.
Useful data associates inflected forms with their dictionary forms (lemmas).

| Language | What is needed |
| --- | --- |
| Chinese (`zho`), Mandarin Chinese (`cmn`) | Obtain an inflectional or other suitable lexical dataset and implement lexical word segmentation. Neither has a local source dataset or pack. `zho` is the broader Chinese code. |
| Cantonese (`yue`) | Obtain a suitable lexical dataset and implement Cantonese-appropriate lexical segmentation. No local source dataset or pack exists. |
| Wu Chinese (`wuu`) | Obtain a suitable lexical dataset and implement lexical segmentation. No local source dataset or pack exists. |
| Japanese (`jpn`) | Evaluate dictionary alignment and representative prose coverage before release. A development pack and optional Sudachi adapter exist and pass integration tests. |
| Tibetan (`bod`) | Implement lexical segmentation across syllable delimiters and clean up source punctuation. |
| Urdu (`urd`) | Implement segmentation that handles spaces omitted between words and inserted within words. |
| Sanskrit (`san`) | Implement sandhi-aware analysis to recover joined words and align them with original text spans. |
| Korean (`kor`) | Align particle-bearing forms with the dictionary or an analyzer. Whitespace boundaries already work. |
| Chukchi (`ckt`) | Repair one malformed source row that combines the lemma and form into one column. |
| Evenki (`evn`) | Review mixed transcription against reader text. |
| Itelmen (`itl`) | Review mixed transcription against reader text. |
| Khanty (`kca`) | Review mixed transcription against reader text. |
| Kyrgyz (`kir`) | Review matching: the source mixes Latin/Cyrillic lookalike characters. |
| Tajik (`tgk`) | Review mixed-script source coverage. |
| Tlatepuzco Chinantec (`cpa`) | Resolve source morpheme/alternative notation. A partial development database exists. |
| Chichimec (`pei`) | Resolve source notation; no mappings currently pass validation. |
| Sierra Otomi (`otm`) | Implement deliberate multiword lookup or obtain suitable single-unit data. All 31,380 source mappings have multiword forms. |
| Esperanto (`epo`) | Obtain inflectional data; no recognized inflection tables are available locally. |
| Guarani (`grn`) | Obtain inflectional data; no recognized inflection tables are available locally. |
| Mongolian (`mon`) | Obtain inflectional data and specify the supported script. No recognized inflection tables are available locally. |
| Ossetian (`oss`) | Obtain inflectional data; no recognized inflection tables are available locally. |
| Western Punjabi (`pnb`) | Obtain inflectional data and review Shahmukhi spacing. No recognized inflection tables are available locally. |
| Passamaquoddy-Maliseet (`pqm`) | Obtain inflectional data; no recognized inflection tables are available locally. |
| Yine (`pib`) | Obtain data: the recognized local source file is empty. |
| Dzongkha (`dzo`) | Obtain data and implement lexical segmentation. No local source dataset or pack exists. |
| Khmer (`khm`) | Obtain data and implement lexical segmentation. No local source dataset or pack exists. |
| Lao (`lao`) | Obtain data and implement lexical segmentation. No local source dataset or pack exists. |
| Burmese (`mya`) | Obtain data and implement lexical segmentation. No local source dataset or pack exists. |
| Thai (`tha`) | Obtain data and implement lexical segmentation. No local source dataset or pack exists. |

The special code `zxx` means “no linguistic content” and is excluded because
it is not a language.

See the [project status report](../maintenance/reports/project-status-20261008.md)
for implementation details, validation results and release instructions.
