#!/usr/bin/env python3
"""
Schema Validator — Prevents schema variance in future agent runs.

Call after any agent writes a JSON file to ensure it conforms to canonical schema.
If it doesn't, normalizes it immediately. Logs all corrections.

Usage:
    # As a library (call from batch_orchestrator.py after each agent):
    from phase_0_prep.schema_validator import validate_and_normalize
    validate_and_normalize(session_dir / "thread_extractions.json")

    # CLI — validate all files in a session:
    python3 schema_validator.py session_0012ebed

    # CLI — validate a single file:
    python3 schema_validator.py --file /path/to/thread_extractions.json
"""

import json
import sys
from pathlib import Path

# Import normalizers from the normalizer module
sys.path.insert(0, str(Path(__file__).resolve().parent))
from schema_normalizer import NORMALIZERS


CANONICAL_DATA_KEYS = {
    "thread_extractions.json": ["threads"],
    "geological_notes.json": ["micro", "meso", "macro", "observations"],
    "semantic_primitives.json": ["tagged_messages", "distributions", "summary_statistics"],
    "explorer_notes.json": ["observations", "explorer_summary"],
    "idea_graph.json": ["nodes", "edges", "metadata"],
    "synthesis.json": ["passes", "key_findings", "session_character"],
    "grounded_markers.json": ["markers", "total_markers"],
    "file_dossiers.json": ["dossiers", "total_files_cataloged"],
    "claude_md_analysis.json": ["gate_activations", "overall_assessment"],
}


def validate_file(filepath):
    """Check if a file has canonical data keys. Returns (valid, missing_keys)."""
    filepath = Path(filepath)
    filename = filepath.name

    if filename not in CANONICAL_DATA_KEYS:
        return True, []

    try:
        with open(filepath) as f:
            data = json.load(f)
    except (json.JSONDecodeError, IOError):
        return False, ["PARSE_ERROR"]

    expected = CANONICAL_DATA_KEYS[filename]
    missing = [k for k in expected if k not in data]
    return len(missing) == 0, missing


def validate_and_normalize(filepath):
    """Validate a file. If invalid, normalize it. Returns (was_valid, action_taken)."""
    filepath = Path(filepath)
    filename = filepath.name

    if filename not in NORMALIZERS:
        return True, "not_an_agent_file"

    valid, missing = validate_file(filepath)
    if valid:
        return True, "valid"

    # Normalize it using the same normalizer from schema_normalizer.py
    from schema_normalizer import normalize_file
    status, log = normalize_file(filepath, NORMALIZERS[filename])
    return False, f"normalized ({status}): {'; '.join(log)}"


def validate_session(session_dir):
    """Validate all agent-produced files in a session."""
    session_dir = Path(session_dir)
    results = {}
    for filename in CANONICAL_DATA_KEYS:
        filepath = session_dir / filename
        if filepath.exists():
            valid, missing = validate_file(filepath)
            results[filename] = {"valid": valid, "missing_keys": missing}
    return results


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Schema Validator")
    parser.add_argument("session", nargs="?", help="Session directory name")
    parser.add_argument("--file", type=str, help="Validate a single file")
    args = parser.parse_args()

    if args.file:
        filepath = Path(args.file)
        valid, missing = validate_file(filepath)
        if valid:
            print(f"VALID: {filepath.name}")
        else:
            print(f"INVALID: {filepath.name} — missing keys: {missing}")
            print("Run schema_normalizer.py to fix.")
        sys.exit(0 if valid else 1)

    if args.session:
        sessions_dir = Path.home() / "PERMANENT_HYPERDOCS" / "sessions"
        session_dir = sessions_dir / args.session
        if not session_dir.exists():
            print(f"Session not found: {session_dir}")
            sys.exit(1)

        results = validate_session(session_dir)
        all_valid = True
        for filename, result in results.items():
            status = "VALID" if result["valid"] else f"INVALID (missing: {result['missing_keys']})"
            print(f"  {filename:<36s}  {status}")
            if not result["valid"]:
                all_valid = False

        if all_valid:
            print("\nAll files valid.")
        else:
            print("\nSome files invalid. Run schema_normalizer.py to fix.")
        sys.exit(0 if all_valid else 1)

    print("Usage: schema_validator.py <session_name> | --file <path>")
    sys.exit(1)


if __name__ == "__main__":
    main()
