"""Verify process-lifetime mutation guards and conservative legacy recovery.

Scope statement:
    Prove crashed writers cannot strand cooperative local mutations.
In scope:
    - Live/malformed marker preservation and real process termination.
    - Contending recovery owners and stable guard inode retention.
Out of scope:
    - Windows execution and network filesystem guarantees.
    - Noncooperating direct file writers.
Start here:
    Subprocesses use the copied package, not an installed personal dictionary.
"""

import os
import subprocess
import sys

import pytest

from blitzer.locking import mutation_lock, abandoned


@pytest.mark.parametrize("content", ["unknown", "0", "-1", str(os.getpid())])
def test_uncertain_or_live_owner_is_preserved(tmp_path, content):
    """Never remove malformed, invalid, or live owner evidence."""
    path = tmp_path / "mutation.lock"
    path.write_text(content)
    with pytest.raises(FileExistsError):
        with mutation_lock(path):
            pass
    assert path.read_text() == content


def test_crashed_owner_recovered_and_second_writer_excluded(tmp_path):
    """A killed real process releases its guard while its PID marker remains recoverable."""
    path = tmp_path / "mutation.lock"
    source = "from pathlib import Path; from blitzer.locking import mutation_lock; import time;\nwith mutation_lock(Path(__import__('sys').argv[1])):\n print('ready', flush=True); time.sleep(30)"
    process = subprocess.Popen(
        [sys.executable, "-c", source, str(path)], stdout=subprocess.PIPE, text=True
    )
    try:
        assert process.stdout.readline().strip() == "ready"
        with pytest.raises(FileExistsError):
            with mutation_lock(path):
                pass
        process.kill()
        process.wait(timeout=5)
        assert path.exists()
        with mutation_lock(path):
            inode = path.with_name(path.name + ".guard").stat().st_ino
            with pytest.raises(FileExistsError):
                with mutation_lock(path):
                    pass
        assert not path.exists()
        with mutation_lock(path):
            assert path.with_name(path.name + ".guard").stat().st_ino == inode
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)
        process.stdout.close()


@pytest.mark.parametrize("content", [b"9" * 4097, b"\xff", b'{"pid": 99999999}'])
def test_unsupported_marker_bytes_are_bounded_and_preserved(tmp_path, content):
    """Large, undecodable, and a different protocol's owner files grant no deletion authority."""
    path = tmp_path / "mutation.lock"
    path.write_bytes(content)
    assert not abandoned(path)
    with pytest.raises(FileExistsError):
        with mutation_lock(path):
            pass
    assert path.read_bytes() == content


@pytest.mark.skipif(os.name == "nt", reason="POSIX named pipe contract")
@pytest.mark.parametrize("member", ["marker", "guard"])
def test_named_pipe_owner_or_guard_is_refused_without_waiting_for_a_writer(tmp_path, member):
    """A local malformed protection path cannot block the specialist process waiting for pipe input."""
    path = tmp_path / "mutation.lock"
    protected = path if member == "marker" else path.with_name(path.name + ".guard")
    os.mkfifo(protected)
    source = (
        "from pathlib import Path; from blitzer.locking import mutation_lock; import sys;\n"
        "try:\n"
        " with mutation_lock(Path(sys.argv[1])): sys.exit(2)\n"
        "except (ValueError, FileExistsError): sys.exit(0)\n"
    )
    result = subprocess.run([sys.executable, "-c", source, str(path)], timeout=3)
    assert result.returncode == 0 and protected.exists()
