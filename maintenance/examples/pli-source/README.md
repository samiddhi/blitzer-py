# Pali source preparation

Source: the existing Blitzer Pali form/lemma database derived from the Digital
Pali Dictionary: https://github.com/digitalpalidictionary/digitalpalidictionary
The previous pack identifies its data as CC BY-NC 4.0 and credits that project.
Preserve upstream attribution and the applicable data license when publishing.
The Blitzer application code license does not replace the data license.

Normalization uses NFC and lowercase, maps niggahita ṁ to ṃ, and removes the
apostrophe characters handled by the original Pali normalizer. Build-plugin
imports the source database read-only and records explicit skipped rows.

If SQLite cannot read an archival WAL-mode database in a read-only source
folder, copy the closed source database into writable scratch space and build
from that copy. Never copy an actively changing database without a consistent
SQLite backup that includes any committed WAL data.
