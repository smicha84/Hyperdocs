#!/usr/bin/env python3
"""Formal schema contracts for all pipeline output files.

Each phase's output must conform to these contracts. The validate_session()
function checks all files in a session directory against these contracts.

Usage:
    # Validate a session:
    python3 tools/schema_contracts.py session_513d4807

    # Validate all sessions:
    python3 tools/schema_contracts.py --all

    # As a library:
    from tools.schema_contracts import validate_session
    errors = validate_session("/path/to/session_dir")
"""
import argparse
import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

# ── Schema Contracts ─────────────────────────────────────────────────
# Each contract: {required_keys: [...], key_types: {key: type_name}, min_length: {key: N}}
# type_name: "str", "int", "float", "list", "dict", "bool"

CONTRACTS = {
    # Phase 0
    "enriched_session.json": {
        "required_keys": ["session_id", "messages"],
        "key_types": {"session_id": "str", "messages": "list"},
        "min_length": {"messages": 1},
    },
    "session_metadata.json": {
        "required_keys": ["session_id", "session_stats"],
        "key_types": {"session_id": "str", "session_stats": "dict"},
    },

    # Phase 1
    "thread_extractions.json": {
        "required_keys": ["threads"],
        "key_types": {"threads": "dict"},
    },
    "geological_notes.json": {
        "required_keys": ["micro", "meso", "macro"],
        "key_types": {"micro": "list", "meso": "list", "macro": "list"},
    },
    "semantic_primitives.json": {
        "required_keys": ["tagged_messages"],
        "key_types": {"tagged_messages": "list"},
    },
    "explorer_notes.json": {
        "required_keys": ["observations"],
        "key_types": {"observations": "list"},
    },

    # Phase 2
    "idea_graph.json": {
        "required_keys": ["nodes", "edges"],
        "key_types": {"nodes": "list", "edges": "list"},
    },
    "synthesis.json": {
        "required_keys": ["session_id"],
        "key_types": {"session_id": "str"},
    },
    "grounded_markers.json": {
        "required_keys": ["markers"],
        "key_types": {"markers": "list"},
    },

    # Phase 3 (accepts both raw "files" key and normalized "dossiers" key)
    "file_dossiers.json": {
        "required_keys": [],
        "any_of_keys": [["dossiers"], ["files"]],  # at least one group must be present
        "key_types": {},
    },
    "claude_md_analysis.json": {
        "required_keys": [],
        "key_types": {},
    },
}

TYPE_MAP = {
    "str": str, "int": int, "float": (int, float),
    "list": list, "dict": dict, "bool": bool,
}


def validate_file(filepath):
    """Validate a single JSON file against its contract.
    Returns list of error strings (empty = valid)."""
    errors = []
    filename = filepath.name

    contract = CONTRACTS.get(filename)
    if not contract:
        return []  # No contract for this file — skip

    try:
        with open(filepath) as f:
            data = json.load(f)
    except FileNotFoundError:
        return [f"MISSING: {filename}"]
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        return [f"CORRUPT: {filename}: {e}"]

    if not isinstance(data, dict):
        return [f"WRONG_TYPE: {filename} is {type(data).__name__}, expected dict"]

    # Required keys
    for key in contract.get("required_keys", []):
        if key not in data:
            errors.append(f"MISSING_KEY: {filename}.{key}")

    # Any-of keys: at least one group of keys must be present
    any_of = contract.get("any_of_keys", [])
    if any_of:
        found = any(all(k in data for k in group) for group in any_of)
        if not found:
            options = " or ".join(str(g) for g in any_of)
            errors.append(f"MISSING_KEY: {filename} needs one of: {options}")

    # Key types
    for key, expected_type in contract.get("key_types", {}).items():
        if key in data:
            py_type = TYPE_MAP.get(expected_type)
            if py_type and not isinstance(data[key], py_type):
                errors.append(
                    f"WRONG_TYPE: {filename}.{key} is {type(data[key]).__name__}, "
                    f"expected {expected_type}"
                )

    # Min length
    for key, min_len in contract.get("min_length", {}).items():
        if key in data and isinstance(data[key], (list, dict, str)):
            if len(data[key]) < min_len:
                errors.append(
                    f"TOO_SHORT: {filename}.{key} has {len(data[key])} items, "
                    f"expected >= {min_len}"
                )

    return errors


def validate_session(session_dir):
    """Validate all JSON files in a session directory.
    Returns {filename: [errors]} for files with errors."""
    session_dir = Path(session_dir)
    results = {}

    for filename in CONTRACTS:
        filepath = session_dir / filename
        if filepath.exists():
            errors = validate_file(filepath)
            if errors:
                results[filename] = errors

    return results


def main():
    parser = argparse.ArgumentParser(description="Validate pipeline output schemas")
    parser.add_argument("session", nargs="?", help="Session directory name")
    parser.add_argument("--all", action="store_true", help="Validate all sessions")
    args = parser.parse_args()

    from config import SESSIONS_STORE_DIR

    if args.all:
        sessions_dir = SESSIONS_STORE_DIR
        total_errors = 0
        total_sessions = 0
        for d in sorted(sessions_dir.iterdir()):
            if not d.is_dir() or not d.name.startswith("session_"):
                continue
            total_sessions += 1
            errors = validate_session(d)
            if errors:
                total_errors += sum(len(e) for e in errors.values())
                print(f"  {d.name}: {sum(len(e) for e in errors.values())} errors")
                for fn, errs in errors.items():
                    for e in errs:
                        print(f"    {e}")
        print(f"\n{total_sessions} sessions, {total_errors} total errors")
    elif args.session:
        session_dir = SESSIONS_STORE_DIR / args.session
        if not session_dir.exists():
            session_dir = SESSIONS_STORE_DIR / f"session_{args.session[:8]}"
        if not session_dir.exists():
            print(f"Session not found: {args.session}")
            sys.exit(1)

        errors = validate_session(session_dir)
        if not errors:
            print(f"{session_dir.name}: all files valid")
        else:
            for fn, errs in errors.items():
                for e in errs:
                    print(f"  {e}")
            sys.exit(1)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
