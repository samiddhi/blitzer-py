"""Serialize mutations and recover only provably abandoned PID markers.

Scope statement:
    Keep the existing PID marker protocol while serializing stale-marker recovery.
In scope:
    - Process-lifetime advisory guards on POSIX and Windows.
    - Preserve live, malformed, and uninspectable legacy lock owners.
Out of scope:
    - Time-based lock expiry, forced process termination, and network filesystems.
    - Coordinate external writers that do not honor either lock protocol.
Start here:
    mutation_lock holds the guard across acquisition, work, and marker removal.
"""

import os
import stat
from contextlib import contextmanager

if os.name == "nt":
    import ctypes
    import msvcrt
    from ctypes import wintypes
else:
    import fcntl


def windows_dead(pid):
    """Use a process handle to inspect liveness without sending any Windows signal."""
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel.WaitForSingleObject.restype = wintypes.DWORD
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    handle = kernel.OpenProcess(0x00100000, False, pid)
    if not handle:
        return ctypes.get_last_error() == 87
    try:
        return kernel.WaitForSingleObject(handle, 0) == 0
    finally:
        kernel.CloseHandle(handle)


def marker_content(path):
    """Read only bounded regular legacy marker bytes without following links or waiting for pipes."""
    descriptor = os.open(
        path,
        os.O_RDONLY
        | getattr(os, "O_NONBLOCK", 0)
        | getattr(os, "O_BINARY", 0)
        | getattr(os, "O_NOFOLLOW", 0),
    )
    try:
        facts = os.fstat(descriptor)
        if not stat.S_ISREG(facts.st_mode) or facts.st_size > 4096:
            return ""
        raw = os.read(descriptor, 4097)
        if len(raw) > 4096:
            return ""
        return raw.decode("utf-8").strip()
    finally:
        os.close(descriptor)


def abandoned(path):
    """Return true only for a valid positive PID whose process is confirmed dead."""
    try:
        content = marker_content(path)
        pid = int(content) if content.isascii() and content.isdecimal() else 0
    except (OSError, ValueError):
        return False
    if not 0 < pid <= 0xFFFFFFFF:
        return False
    if os.name == "nt":
        return windows_dead(pid)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    except (PermissionError, OverflowError, OSError):
        return False
    return False


def guard_acquire(stream):
    """Hold one nonblocking guard, never unlinking its process-lifetime inode."""
    if os.name == "nt":
        stream.seek(0)
        msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
    else:
        fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)


def guard_release(stream):
    """Release the same locked byte or advisory file after marker cleanup."""
    if os.name == "nt":
        stream.seek(0)
        msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        fcntl.flock(stream, fcntl.LOCK_UN)


def create_marker(path):
    """Recover a dead owner under the guard and preserve every uncertain marker."""
    if path.is_symlink():
        raise ValueError(f"Refusing a symlink mutation lock: {path}")
    if path.exists() and abandoned(path):
        path.unlink()
    try:
        stream = path.open("x", encoding="utf-8")
    except FileExistsError as error:
        raise FileExistsError(f"Operation locked by {path}") from error
    with stream:
        stream.write(str(os.getpid()) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


@contextmanager
def guard_lock(path):
    """Acquire a persistent guard and close its descriptor on every exit."""
    guard = path.with_name(path.name + ".guard")
    if guard.is_symlink():
        raise ValueError(f"Refusing a symlink mutation guard: {guard}")
    descriptor = os.open(
        guard,
        os.O_RDWR
        | os.O_CREAT
        | os.O_APPEND
        | getattr(os, "O_NONBLOCK", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_BINARY", 0),
        0o600,
    )
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise ValueError(f"Refusing a nonregular mutation guard: {guard}")
        stream = os.fdopen(descriptor, "a+b")
        descriptor = None
    finally:
        if descriptor is not None:
            os.close(descriptor)
    with stream:
        try:
            guard_acquire(stream)
        except OSError as error:
            raise FileExistsError(f"Operation locked by {path}") from error
        try:
            yield
        finally:
            guard_release(stream)


@contextmanager
def mutation_lock(path):
    """Retain legacy exclusion and prevent two recoverers from deleting a new owner."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with guard_lock(path):
        create_marker(path)
        try:
            yield
        finally:
            path.unlink()
