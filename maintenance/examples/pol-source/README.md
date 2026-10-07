# Polish source preparation

Source: the existing Blitzer Polish form/lemma database derived from PoliMorf.
Source application: https://github.com/samiddhi/blitzer-language-plugins

Normalization uses Unicode NFC and lowercase while preserving Polish letters.
Use build-plugin with --database to convert the source explicitly. Unsupported
single-word mappings must be deliberately skipped and are counted in provenance.
Do not execute or package the previous Python plugin code.

The old pack identifies PoliMorf but does not include clear data-license terms.
Confirm the upstream redistribution requirements and include the corresponding
license and attribution before publicly publishing this data pack. The Blitzer
application's GPL license does not establish the dictionary data's license.
