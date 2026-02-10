#!/usr/bin/env python3
"""
Post-Agent Schema Normalizer — Run after ANY agent completes.

Automatically normalizes agent output to canonical schema and validates it.
Designed to be called from batch_orchestrator, concierge, or any pipeline runner.

Usage:
    # After Phase 1 agents finish a session:
    python3 post_agent_normalize.py session_0012ebed

    # After Phase 2 agents finish:
    python3 post_agent_normalize.py session_0012ebed

    # Validate only (no changes):
    python3 post_agent_normalize.py session_0012ebed --validate-only

    # As a library:
    from phase_5_ground_truth.post_agent_normalize import normalize_session_output
    results = normalize_session_output("/path/to/session_dir")
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from schema_normalizer import NORMALIZERS, normalize_file
from schema_validator import CANONICAL_DATA_KEYS, validate_file


def normalize_session_output(session_dir, validate_only=False):
    """Normalize and validate all agent-produced files in a session.

    Returns dict of {filename: {status, valid, log}}.
    """
    session_dir = Path(session_dir)
    results = {}

    for filename, normalizer_fn in NORMALIZERS.items():
        filepath = session_dir / filename
        if not filepath.exists():
            continue

        # Check if already normalized
        with open(filepath) as f:
            data = json.load(f)

        if "_normalized_at" in data:
            # Already normalized — just validate
            valid, missing = validate_file(filepath)
            results[filename] = {
                "status": "already_normalized",
                "valid": valid,
                "missing_keys": missing,
            }
            continue

        if validate_only:
            valid, missing = validate_file(filepath)
            results[filename] = {
                "status": "needs_normalization",
                "valid": valid,
                "missing_keys": missing,
            }
            continue

        # Normalize it
        status, log = normalize_file(filepath, normalizer_fn)

        # Validate the result
        valid, missing = validate_file(filepath)

        results[filename] = {
            "status": status,
            "valid": valid,
            "missing_keys": missing,
            "log": log,
        }

    return results


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Post-Agent Schema Normalizer")
    parser.add_argument("session", help="Session directory name (e.g., session_0012ebed)")
    parser.add_argument("--validate-only", action="store_true", help="Check without modifying")
    args = parser.parse_args()

    sessions_dir = Path.home() / "PERMANENT_HYPERDOCS" / "sessions"
    session_dir = sessions_dir / args.session
    if not session_dir.exists():
        print(f"Session not found: {session_dir}")
        sys.exit(1)

    results = normalize_session_output(session_dir, validate_only=args.validate_only)

    all_valid = True
    for filename, result in sorted(results.items()):
        status = result["status"]
        valid = result["valid"]
        mark = "OK" if valid else "FAIL"
        extra = ""
        if "log" in result:
            extra = f" — {'; '.join(result['log'][:3])}"
        print(f"  [{mark}] {filename:<36s}  {status}{extra}")
        if not valid:
            all_valid = False

    if all_valid:
        print(f"\nAll {len(results)} files valid.")
    else:
        failed = sum(1 for r in results.values() if not r["valid"])
        print(f"\n{failed} file(s) have issues.")

    sys.exit(0 if all_valid else 1)


if __name__ == "__main__":
    main()
