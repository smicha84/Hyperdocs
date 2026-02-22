"""Atomic file writing with advisory locking for shared pipeline state files.

Usage:
    from tools.file_lock import atomic_json_write, locked_json_read

    # Write with lock (prevents concurrent corruption):
    atomic_json_write(path, data)

    # Read with lock (consistent reads during writes):
    data = locked_json_read(path)
"""
import fcntl
import json
import os
import tempfile
from pathlib import Path


def atomic_json_write(filepath, data, indent=2):
    """Write JSON atomically with advisory lock.

    1. Acquires exclusive lock on a .lock file
    2. Writes to a temp file
    3. Atomically renames temp → target
    4. Releases lock

    This prevents corruption when two processes write simultaneously.
    """
    filepath = Path(filepath)
    lock_path = filepath.with_suffix(filepath.suffix + ".lock")

    filepath.parent.mkdir(parents=True, exist_ok=True)

    with open(lock_path, "w") as lock_f:
        fcntl.flock(lock_f, fcntl.LOCK_EX)
        try:
            fd, tmp_path = tempfile.mkstemp(
                dir=filepath.parent, suffix=".tmp", prefix=filepath.stem
            )
            try:
                with os.fdopen(fd, "w") as f:
                    json.dump(data, f, indent=indent, default=str)
                os.replace(tmp_path, filepath)
            except Exception:
                os.unlink(tmp_path)
                raise
        finally:
            fcntl.flock(lock_f, fcntl.LOCK_UN)


def locked_json_read(filepath):
    """Read JSON with shared lock (blocks during concurrent writes).

    Returns parsed data, or empty dict if file doesn't exist.
    """
    filepath = Path(filepath)
    if not filepath.exists():
        return {}

    lock_path = filepath.with_suffix(filepath.suffix + ".lock")

    with open(lock_path, "w") as lock_f:
        fcntl.flock(lock_f, fcntl.LOCK_SH)
        try:
            with open(filepath) as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return {}
        finally:
            fcntl.flock(lock_f, fcntl.LOCK_UN)
