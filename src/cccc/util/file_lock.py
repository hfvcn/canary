from __future__ import annotations

import logging
import os
import signal
from pathlib import Path
from typing import IO, Optional

_LOG = logging.getLogger("cccc.util.file_lock")


class LockUnavailableError(RuntimeError):
    """Raised when a non-blocking lock cannot be acquired."""


def _ensure_lock_region(f: IO[bytes]) -> None:
    """Ensure the lock file has at least 1 byte so region locks work on Windows."""
    try:
        f.seek(0, os.SEEK_END)
        if f.tell() <= 0:
            f.write(b"\0")
            f.flush()
        f.seek(0)
    except Exception as e:
        # Best-effort: even if this fails, locking may still work depending on platform.
        _LOG.debug("lockfile region init failed: %s", e)


def _lock_posix(fd: int, *, blocking: bool) -> None:
    import fcntl  # POSIX only

    flags = fcntl.LOCK_EX
    if not blocking:
        flags |= fcntl.LOCK_NB
    fcntl.flock(fd, flags)


def _unlock_posix(fd: int) -> None:
    import fcntl  # POSIX only

    fcntl.flock(fd, fcntl.LOCK_UN)


def _lock_windows(fd: int, *, blocking: bool) -> None:
    import msvcrt  # Windows only

    mode = msvcrt.LK_LOCK if blocking else msvcrt.LK_NBLCK
    msvcrt.locking(fd, mode, 1)


def _unlock_windows(fd: int) -> None:
    import msvcrt  # Windows only

    msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)


def _pid_is_alive(pid: int) -> bool:
    """Check whether *pid* refers to a running process (best-effort, POSIX+Windows)."""
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)  # signal 0: no signal sent, but error checking is performed
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        # Process exists but we don't have permission to signal it — still alive.
        return True
    except OSError:
        return False


def _read_pid_from_lockfile(path: Path) -> int:
    """Read a PID previously written into a lock file.  Returns 0 on failure."""
    try:
        raw = path.read_bytes().strip()
        return int(raw) if raw.isdigit() else 0
    except Exception:
        return 0


def _try_lock(f: IO[bytes], *, blocking: bool) -> None:
    """Platform-dispatched flock/locking."""
    if os.name == "nt":
        _lock_windows(f.fileno(), blocking=blocking)
    else:
        _lock_posix(f.fileno(), blocking=blocking)


def _open_and_lock(path: Path, *, blocking: bool) -> IO[bytes]:
    """Open *path* and acquire an exclusive lock.  Returns the open handle."""
    f = path.open("r+b") if path.exists() else path.open("w+b")
    _ensure_lock_region(f)
    try:
        _try_lock(f, blocking=blocking)
    except (BlockingIOError, OSError) as e:
        try:
            f.close()
        except Exception:
            pass
        if not blocking:
            raise LockUnavailableError(str(e)) from e
        raise
    except Exception:
        try:
            f.close()
        except Exception:
            pass
        raise
    return f


def acquire_lockfile(path: Path, *, blocking: bool = True) -> IO[bytes]:
    """Open + lock a lockfile.  Keep the returned handle open to hold the lock.

    When *blocking* is False and the lock is held by another **live** process,
    ``LockUnavailableError`` is raised.  If the recorded holder PID is no longer
    alive the stale lock file is removed and acquisition is retried once.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        return _open_and_lock(path, blocking=blocking)
    except LockUnavailableError:
        # Lock is held — check if the holder is still alive.
        holder_pid = _read_pid_from_lockfile(path)
        if holder_pid and _pid_is_alive(holder_pid):
            _LOG.debug("lockfile %s held by live pid %d", path, holder_pid)
            raise  # genuinely held
        # Holder is dead (or PID unknown) — break stale lock and retry.
        _LOG.info(
            "Breaking stale lockfile %s (recorded pid %d is not alive)",
            path,
            holder_pid,
        )
        try:
            path.unlink(missing_ok=True)
        except Exception as e:
            _LOG.warning("Failed to remove stale lockfile %s: %s", path, e)
            raise
        return _open_and_lock(path, blocking=blocking)


def write_pid_to_lockfile(f: IO[bytes], pid: Optional[int] = None) -> None:
    """Write *pid* (default: current process) into an already-locked file."""
    pid = pid or os.getpid()
    try:
        f.seek(0)
        f.truncate()
        f.write(str(pid).encode())
        f.flush()
    except Exception as e:
        _LOG.debug("failed to write pid to lockfile: %s", e)


def release_lockfile(f: IO[bytes], *, remove: bool = False) -> None:
    """Release a lockfile acquired via acquire_lockfile (best-effort).

    If *remove* is True the lock file is deleted after unlocking, which is the
    recommended behaviour for daemon-lifetime locks so that stale files don't
    accumulate.
    """
    lock_path: Optional[Path] = None
    try:
        lock_path = Path(f.name)
    except Exception:
        pass

    # On Windows, msvcrt.locking() locks/unlocks from the current file position.
    # Seek to 0 so we reliably unlock the 1-byte region we lock in acquire_lockfile().
    try:
        f.seek(0)
    except Exception:
        pass
    try:
        if os.name == "nt":
            _unlock_windows(f.fileno())
        else:
            _unlock_posix(f.fileno())
    except Exception as e:
        _LOG.debug("lockfile unlock failed: %s", e)
    try:
        f.close()
    except Exception as e:
        _LOG.debug("lockfile close failed: %s", e)
    if remove and lock_path:
        try:
            lock_path.unlink(missing_ok=True)
        except Exception as e:
            _LOG.debug("lockfile remove failed: %s", e)
