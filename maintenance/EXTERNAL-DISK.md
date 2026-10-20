# Development on Iddhibiddhi

The development checkout is at `/Volumes/Iddhibiddhi/dev/blitzer-py`.
Run `bltzr-dev --check` before working on it. The local launcher verifies the
disk's volume UUID and prints a reminder if it is disconnected. Use
`bltzr-dev ...` for development CLI commands, or
`bltzr-dev --run make release` for release maintenance. For another command,
use `bltzr-dev --run COMMAND [ARGS...]`; it starts in the external checkout.

The normal `bltzr` command comes from the published system Python installation and uses
real local copies of the Slovenian, Pali and Polish packs in
`~/.local/share/bltzr/languages`. English is bundled in the application.
The normal config at `~/.config/bltzr/bltzr.toml` selects that local pack
directory. This keeps day-to-day use available while the disk is unplugged.

`~/dev/blitzer-py` is a small local pointer directory. Open the external
path as the Codex workspace for development. Codex cannot use a symlink as
its writable workspace root, so the old path remains a real directory.
Older tools with hardcoded paths into the old checkout need their paths
updated. Use `bltzr-dev` for an explicit disk reminder. The UniMorph
source checkout is at `/Volumes/Iddhibiddhi/dev/unimorph`, with its previous
location retained as a compatibility link. The development `.venv` is
recreated on the disk because Python environments contain absolute paths.

Before unplugging the disk, exit shells and applications using the external
checkout, then eject the volume normally. To recover, reconnect the same
volume and run `bltzr-dev --check`.
