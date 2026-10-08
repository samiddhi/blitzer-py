# One-command releases

The [2026-10-08 project status report](reports/project-status-20261008.md)
records the prepared language refresh, remaining development cases and
commands for releasing this checkout. Format-2 packs require the accompanying
new application; the release helper rebuilds assets from the current local
packs. No extra pack refresh is needed before publication.

After the one-time setup below, run `make release` from the project root.
The helper increments only the application's patch version, commits all
non-ignored changes, pushes `master` and its tag, uploads changed language
packs, and publishes a GitHub release. That publication triggers the
GitHub Actions workflow that builds and uploads `bltzr` to PyPI.

Git-ignored dictionaries stay out of Git. Deferred dictionaries under
`language-packs/dev/` stay out of releases. Pack configuration versions
are retained; the automatically incremented version is the application
and release version.

## 1. Install the local tools

```sh
cd ~/dev/blitzer-py
brew install gh
.venv/bin/python -m pip install -e '.[dev]'
```

Skip `brew install gh` if GitHub CLI is already installed. The Python
command installs Bump My Version, pytest, build and twine in the existing
project environment.

## 2. Authenticate GitHub and enable workflow pushes

```sh
gh auth login --hostname github.com --git-protocol https --web --scopes workflow
gh auth setup-git
gh auth status
```

Log in as `samiddhi`. Authenticate for both repository writes and workflow
files. If an existing token lacks workflow permission, use
`gh auth refresh --hostname github.com --scopes workflow`.

Keep your normal Git identity. If Git says it is missing, configure it
using your own name and GitHub-verified email before running a release.

## 3. Create the GitHub publishing environment

```sh
gh api --method PUT repos/samiddhi/blitzer-py/environments/pypi \
  --input - <<<'{}'
```

This creates the environment named `pypi`, which the workflow uses. The
repository must allow GitHub Actions. Its default Actions settings are
sufficient for the official checkout, Python setup and PyPI actions.

If GitHub CLI reports `unexpected end of JSON input`, check whether the
environment was created before retrying the write:

```sh
gh api --include repos/samiddhi/blitzer-py/environments/pypi
```

A successful response containing `"name": "pypi"` means this step is
complete. Otherwise, inspect the HTTP status and error output. You can
also create it at https://github.com/samiddhi/blitzer-py/settings/environments
by selecting **New environment**, entering `pypi`, and selecting
**Configure environment**.

## 4. Connect the existing PyPI project

Open https://pypi.org/manage/project/bltzr/settings/publishing/ while
logged in to the account that owns `bltzr`.

Under **Add a new publisher**, select **GitHub** and enter exactly:

| Field | Value |
| --- | --- |
| Owner | `samiddhi` |
| Repository name | `blitzer-py` |
| Workflow name | `publish.yml` |
| Environment name | `pypi` |

Add the publisher. The workflow uses PyPI Trusted Publishing, so do not
add a PyPI token or password to the repository or GitHub secrets.

See [PyPI's publisher setup instructions](https://docs.pypi.org/trusted-publishers/adding-a-publisher/)
for the corresponding form.

## 5. Check the command before publishing

```sh
make -n release
.venv/bin/bump-my-version bump --dry-run patch
.venv/bin/python -m pytest -q -p no:cacheprovider
```

These commands do not commit, push, or publish. The first prints the
release command; the second previews the version bump.

The workflow and helper files can be included in the first release's
commit. There is no separate initial commit/push step required.

## 6. Publish

Review the checkout's changes with `git status` and `git diff`, then run:

```sh
make release
```

This is a real publication command. It includes all non-ignored files in
its release commit, including new files and deletions. From version
`0.2.3`, it releases `0.2.4`; after `0.2.9`, it releases `0.2.10`.

Do not manually bump the application version first. The helper reads
`project.version`, and Bump My Version changes that value exactly once.

Before changing the version, the helper tests the project and validates
changed packs. Before pushing, it also builds the distributions and runs
`twine check`. It stops if `master` does not include the remote branch.
Resolve that Git synchronization problem before trying again.

## What happens to the language packs

Every pack's supported files are hashed by contents, not timestamps. The
helper compares these fingerprints with the cumulative
`pack-manifest.json` attached to the previous automated GitHub release.
Only changed or new packs are validated, packaged and uploaded. Unchanged
packs remain available from earlier stable releases; the installer
already discovers the newest release for each language independently.

On the first automated run, there is no manifest yet. The helper verifies
existing `release-assets/` ZIPs against GitHub's published SHA-256 digests
and compares their contents with the current packs. If a verified local
ZIP is unavailable, it downloads that historical asset. This initial
comparison may take several minutes for large dictionaries. It does not
blindly republish every pack. Later runs use the small manifest.

If neither source nor pack content has changed since the current version's
Git tag, the command stops without bumping or publishing. A changed
non-ignored document also counts as a source change.

Use this helper for subsequent combined releases so manifests remain
current. If publishing a pack-only release manually, give its tag a
`packs-` prefix; the PyPI workflow responds only to tags starting with `v`.

## Check publication and recover failures

After GitHub publication, PyPI uploading runs asynchronously in Actions:

```sh
gh run list --repo samiddhi/blitzer-py --workflow publish.yml
```

To follow a specific run, use the numeric ID printed in that list:

```sh
gh run watch RUN_ID --repo samiddhi/blitzer-py --exit-status
```

If the local command stops during building, committing, pushing or
uploading, fix the reported issue and run `make release` again. Its ignored
`maintenance/work/pending-release.json` checkpoint preserves the intended
version and archives. Do not delete that checkpoint or change the release
commit while resuming. Assets are uploaded into a draft; the release
becomes public only after all uploads succeed.

If the GitHub release succeeded but the PyPI workflow failed, fix the
workflow/account problem and rerun the same failed job:

```sh
gh run rerun RUN_ID --repo samiddhi/blitzer-py --failed
```

Do not run another release just to retry PyPI. The workflow skips already
uploaded distribution files when retrying a partially completed upload.
No-op detection describes Git and pack publication; it does not imply the
asynchronous PyPI job has succeeded. Check that job's result.

The helper belongs in `maintenance/`, and no release command is added to
the application CLI. Authentication and publication are never run merely
by installing the application or running its tests.
