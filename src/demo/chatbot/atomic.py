"""Crash-safe file writes.

``atomic_write_bytes`` writes to a temp file in the same directory, fsyncs it, then
``os.replace``s it over the target: readers see either the old file or the new one, never a
torn write. ``atomic_create_exclusive`` publishes a fully written file with ``os.link``,
which fails if the target exists, so concurrent processes agree on exactly one winner.
Both work on Windows (NTFS) and POSIX.
"""

from __future__ import annotations

import contextlib
import os
import tempfile
from pathlib import Path


def _fsync_dir(directory: Path) -> None:
    if os.name != "posix":  # Windows has no directory fsync; NTFS metadata journaling covers it.
        return
    fd = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _write_temp(directory: Path, name: str, data: bytes, mode: int) -> Path:
    fd, tmp_name = tempfile.mkstemp(dir=directory, prefix=f".{name}.", suffix=".tmp")
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        with contextlib.suppress(OSError):
            os.chmod(tmp, mode)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            tmp.unlink()
        raise
    return tmp


def atomic_write_bytes(path: Path, data: bytes, *, mode: int = 0o600) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = _write_temp(path.parent, path.name, data, mode)
    try:
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            tmp.unlink()
        raise
    _fsync_dir(path.parent)


def atomic_create_exclusive(path: Path, data: bytes, *, mode: int = 0o600) -> bool:
    """Create ``path`` with ``data`` only if it does not exist. Returns True if we created it."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = _write_temp(path.parent, path.name, data, mode)
    try:
        os.link(tmp, path)
        created = True
    except FileExistsError:
        created = False
    finally:
        with contextlib.suppress(FileNotFoundError):
            tmp.unlink()
    if created:
        _fsync_dir(path.parent)
    return created
