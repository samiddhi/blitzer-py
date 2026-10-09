# Two simple word lists

Status: implemented. This replaces the earlier proposal. See the
[README](../README.md#choose-which-words-to-skip), [example config](../config.example.toml)
and [man page](bltzr.1) for usage and migration details.

- **Skip these exact words (word form):** `skip_exact_words_file`.
  For **to be**, listing **be** and **am** skips only those words.
  **Is**, **are**, **was**, **were**, **being**, and **been** remain counted.
  Listing **cat** leaves **cats** counted.
- **Skip these words and their other forms: word families (lexeme/lemma):**
  `skip_word_families_file`. Listing **be** (without “to”) skips **be**, **am**,
  **is**, **are**, **was**, **were**, **being**, and **been**, using the dictionary.
  Listing **cat** skips **cat** and **cats**.

Use either file or both. Each file has a fixed meaning, independent of whether
output shows words as written or their basic words. Skipped occurrences do not
contribute counts or examples.

Automatic additions stay off by default. Previews and updates require an
explicit choice of `exact-words` or `word-families` through `--update-list` or
language-level `update_list`. Only that file receives additions.

Old settings and CLI options retain their behavior for compatibility. New
language settings cannot be mixed with old file keys or language-level
`filter_by`; migration is explained with examples. User files are not changed
automatically.

Keep report instructions (`prompt_text`): they are exported for copying into
another tool and never sent to an API by bltzr.
