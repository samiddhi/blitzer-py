# Publishing language packs

For automated patch bumps, Git pushes, changed-pack uploads and PyPI
publication, use the [one-command release guide](../maintenance/RELEASING.md).
After its one-time setup, run `make release` from the project root.

Run these commands from the project root (`~/dev/blitzer-py`). This
repository uses **`master`**, so release commands must target `master`.

Usable packs live here in three-letter folders such as `slv/` and `pol/`.
Unfinished packs live in `dev/` and must stay out of releases. This README
does not affect language discovery.

## 1. Prepare the changed packs

Update each changed pack's `config.toml` metadata version. Leave unchanged
packs at their existing versions. Then validate and package the changed
packs, for example Slovenian:

```sh
.venv/bin/bltzr dev package-plugin slv \
  --no-config --plugins-dir language-packs --output-dir release-assets
```

Repeat for other changed codes. Packaging validates the database and
replaces that pack's ZIP and checksum in `release-assets/`.

Keep filenames like `blitzer-slv-v1.zip` unchanged. **`v1` is the pack
format**, not the dictionary version. Existing archives for unchanged
packs can be included again.

## 2. Push the source changes

If there are uncommitted source or documentation changes:

```sh
git add -A
git commit -m "Prepare the next language-pack release"
```

Then push:

```sh
git push origin master
```

The databases and release archives are deliberately excluded from Git.
The README is tracked; the ZIPs are uploaded separately below.

## 3. Publish the release

For manual pack-only releases, use a tag with a **`packs-`** prefix so it
does not trigger application publication to PyPI:

```sh
gh release create packs-v0.3.0 release-assets/*.zip \
  --repo samiddhi/blitzer-py \
  --target master \
  --latest=false \
  --title "Blitzer language packs 0.3.0" \
  --notes "Describe the updated dictionaries and added languages."
```

This uploads every prepared ZIP. `--latest=false` keeps a pack-only release
from becoming the headline application release. Publish a regular release;
the installer ignores drafts and prereleases.

## 4. Check it

```sh
gh release view packs-v0.3.0 --repo samiddhi/blitzer-py
bltzr install-plugin slv --replace
```

The installer finds the newest stable release containing each language's
ZIP. No download links need updating.

If a release already exists and an upload was interrupted, finish it with:

```sh
gh release upload packs-v0.3.0 release-assets/*.zip \
  --repo samiddhi/blitzer-py --clobber
```

`--clobber` replaces same-named assets. Use it to finish or correct that
release; normally publish changed dictionaries under a new tag.

Adding new language codes also requires shipping the updated application
catalog. Publishing pack ZIPs does not publish the application to PyPI.
See [the full release guide](../PLUGIN-RELEASES.org) for details.
