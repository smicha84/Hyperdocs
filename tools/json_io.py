"""
Shared JSON I/O for the Hyperdocs pipeline.

HARD FAIL contract:
  load_json(path)  — raises FileNotFoundError if missing, json.JSONDecodeError if corrupt.
  save_json(path, data) — raises on any write failure. Creates parent dirs.

Callers who need optional files must check path.exists() first, then call load_json().
No silent fallbacks. No empty-dict returns. Corrupt data is a crash, not a default.
"""
import json
from pathlib import Path


def load_json(path):
    """Load and parse a JSON file. Crashes on missing or corrupt files.

    Args:
        path: str or Path to the JSON file.

    Returns:
        Parsed JSON data (dict, list, etc.).

    Raises:
        FileNotFoundError: if the file does not exist.
        json.JSONDecodeError: if the file contains invalid JSON.
    """
    path = Path(path)
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path, data):
    """Write data as JSON to a file. Creates parent directories if needed.

    Args:
        path: str or Path to the output file.
        data: JSON-serializable data.

    Raises:
        TypeError: if data is not JSON-serializable.
        OSError: if the file cannot be written.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
