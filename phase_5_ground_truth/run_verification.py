#!/usr/bin/env python3
"""
Ground Truth Verification Runner
=================================

Runs all 3 Phase 5 scripts against a specific session's output data.

Adapts the hardcoded paths in claim_extractor.py, ground_truth_verifier.py,
and gap_reporter.py to work with the actual session directory structure.

Usage:
    python3 run_verification.py                          # Uses first complete session
    python3 run_verification.py --session session_0012ebed
    python3 run_verification.py --all                    # Run on all complete sessions
"""

import json
import ast
import re
import os
import sys
from pathlib import Path
from datetime import datetime
from collections import defaultdict

PERMANENT = Path.home() / "PERMANENT_HYPERDOCS"
SESSIONS_DIR = PERMANENT / "sessions"

# Source code locations to check (in priority order)
SOURCE_DIRS = [
    Path.home() / "PycharmProjects" / "pythonProject ARXIV4" / "pythonProjectartifact" / ".claude" / "hooks" / "hyperdoc" / "hyperdocs_3",
    Path.home() / "PycharmProjects" / "pythonProject ARXIV4" / "pythonProjectartifact" / ".claude" / "hooks",
    Path.home() / "PycharmProjects" / "pythonProject ARXIV4" / "pythonProjectartifact" / ".claude" / "hooks" / "hyperdoc" / "hyperdocs_2" / "V5" / "code",
    Path.home() / "Hyperdocs",
]

# Enhanced files (where the hyperdoc-annotated versions live)
ENHANCED_DIR = (
    Path.home() / "PycharmProjects" / "pythonProject ARXIV4" / "pythonProjectartifact"
    / ".claude" / "hooks" / "hyperdoc" / "hyperdocs_3" / "output" / "enhanced_files"
)


def find_source_file(filename: str) -> Path:
    """Find a source file across known directories."""
    # Check enhanced files first
    candidate = ENHANCED_DIR / filename
    if candidate.exists():
        return candidate

    # Check source directories
    for d in SOURCE_DIRS:
        for p in d.rglob(filename):
            if p.is_file():
                return p

    return None


def load_session_json(session_dir: Path, filename: str) -> dict:
    path = session_dir / filename
    if not path.exists():
        return {}
    with open(path) as f:
        return json.load(f)


# ── STEP 1: Extract Claims ───────────────────────────────────────────────

def extract_claims(session_dir: Path) -> dict:
    """Extract verifiable claims from a session's pipeline outputs."""
    markers = load_session_json(session_dir, "grounded_markers.json")
    primitives = load_session_json(session_dir, "semantic_primitives.json")
    idea_graph = load_session_json(session_dir, "idea_graph.json")
    dossiers = load_session_json(session_dir, "file_dossiers.json")

    claims = []

    # Extract from grounded markers
    for marker in markers.get("markers", markers.get("warnings", [])):
        claim_text = marker.get("claim", marker.get("warning", ""))
        confidence = marker.get("confidence", 0)
        category = marker.get("category", "unknown")
        evidence = marker.get("evidence", "")
        target = marker.get("target", "")

        if claim_text:
            claims.append({
                "source": "grounded_markers",
                "claim": claim_text,
                "confidence": confidence,
                "category": category,
                "evidence": evidence,
                "target": target,
            })

    # Extract confidence claims from semantic primitives
    messages = primitives.get("messages", primitives.get("tagged_messages", []))
    for msg in messages:
        conf = msg.get("confidence_signal", msg.get("confidence", ""))
        if conf in ("proven", "stable"):
            friction = msg.get("friction_log", msg.get("friction", ""))
            decision = msg.get("decision_trace", msg.get("decision", ""))
            idx = msg.get("index", msg.get("message_index", 0))
            if friction or decision:
                claims.append({
                    "source": "semantic_primitives",
                    "claim": f"Confidence={conf} at msg {idx}: {friction or decision}",
                    "confidence": 0.7 if conf == "stable" else 0.9,
                    "category": "confidence",
                    "target": "",
                })

    # Extract from idea graph nodes
    for node in idea_graph.get("nodes", []):
        node_conf = node.get("confidence", node.get("state", ""))
        if node_conf in ("proven", "stable", "working"):
            claims.append({
                "source": "idea_graph",
                "claim": f"Idea '{node.get('name', '?')}' rated {node_conf}",
                "confidence": {"proven": 0.9, "stable": 0.7, "working": 0.5}.get(node_conf, 0.5),
                "category": "idea_confidence",
                "target": "",
            })

    return {
        "session_id": session_dir.name,
        "extracted_at": datetime.now().isoformat(),
        "total_claims": len(claims),
        "claims": claims,
    }


# ── STEP 2: Verify Claims Against Source Code ─────────────────────────────

def check_bare_excepts(filepath: Path) -> dict:
    """Check for bare except: blocks."""
    try:
        source = filepath.read_text()
        tree = ast.parse(source)
    except (SyntaxError, UnicodeDecodeError, IOError):
        return {"check": "bare_excepts", "result": "UNABLE_TO_VERIFY", "evidence": "Could not parse"}

    bare = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ExceptHandler) and node.type is None:
            bare.append(node.lineno)

    if bare:
        return {"check": "bare_excepts", "result": "FAILED", "evidence": f"Bare except at lines: {bare}", "count": len(bare)}
    return {"check": "bare_excepts", "result": "VERIFIED", "evidence": "No bare except blocks found"}


def check_model_strings(filepath: Path) -> dict:
    """Check for non-Opus model strings (Sonnet/Haiku where Opus should be)."""
    try:
        source = filepath.read_text()
    except (IOError, UnicodeDecodeError):
        return {"check": "model_strings", "result": "UNABLE_TO_VERIFY", "evidence": "Could not read"}

    violations = []
    for i, line in enumerate(source.splitlines(), 1):
        if "sonnet" in line.lower() and not line.strip().startswith("#"):
            violations.append(f"Line {i}: {line.strip()[:80]}")
        if "haiku" in line.lower() and not line.strip().startswith("#") and "# haiku" not in line.lower():
            violations.append(f"Line {i}: {line.strip()[:80]}")

    if violations:
        return {"check": "model_strings", "result": "FAILED", "evidence": f"Non-Opus models: {violations[:5]}", "count": len(violations)}
    return {"check": "model_strings", "result": "VERIFIED", "evidence": "Only Opus model strings found"}


def check_truncation_limits(filepath: Path) -> dict:
    """Check for hardcoded truncation like [:10] or [:100]."""
    try:
        source = filepath.read_text()
    except (IOError, UnicodeDecodeError):
        return {"check": "truncation", "result": "UNABLE_TO_VERIFY", "evidence": "Could not read"}

    truncations = []
    for i, line in enumerate(source.splitlines(), 1):
        if re.search(r'\[:\d{1,3}\]', line) and not line.strip().startswith("#"):
            truncations.append(f"Line {i}: {line.strip()[:80]}")

    if truncations:
        return {"check": "truncation", "result": "FAILED", "evidence": f"Truncation limits: {truncations[:5]}", "count": len(truncations)}
    return {"check": "truncation", "result": "VERIFIED", "evidence": "No suspicious truncation limits"}


def check_function_exists(filepath: Path, func_name: str) -> dict:
    """Check if a specific function exists in the file."""
    try:
        source = filepath.read_text()
        tree = ast.parse(source)
    except (SyntaxError, UnicodeDecodeError, IOError):
        return {"check": f"function_{func_name}", "result": "UNABLE_TO_VERIFY", "evidence": "Could not parse"}

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == func_name:
            return {"check": f"function_{func_name}", "result": "VERIFIED", "evidence": f"Found at line {node.lineno}"}

    return {"check": f"function_{func_name}", "result": "FAILED", "evidence": f"Function '{func_name}' not found"}


def verify_session(session_dir: Path, claims: dict) -> dict:
    """Run verification checks against source files."""
    results = {"checks": [], "files_checked": 0, "files_found": 0, "files_missing": 0}

    # Find all files mentioned in dossiers
    dossiers = load_session_json(session_dir, "file_dossiers.json")
    dossier_data = dossiers.get("dossiers", dossiers)
    if isinstance(dossier_data, list):
        file_list = [d.get("file", d.get("filename", "")) for d in dossier_data if isinstance(d, dict)]
    elif isinstance(dossier_data, dict):
        file_list = list(dossier_data.keys())
    else:
        file_list = []

    # Also check enhanced files directory
    if ENHANCED_DIR.exists():
        for py_file in sorted(ENHANCED_DIR.glob("*.py"))[:50]:  # Check first 50
            file_list.append(py_file.name)

    file_list = list(set(f for f in file_list if f.endswith(".py")))[:30]  # Cap at 30

    for filename in file_list:
        filepath = find_source_file(filename)
        if filepath is None:
            results["files_missing"] += 1
            results["checks"].append({
                "file": filename,
                "result": "FILE_NOT_FOUND",
                "checks": [],
            })
            continue

        results["files_found"] += 1
        results["files_checked"] += 1

        file_checks = []
        file_checks.append(check_bare_excepts(filepath))
        file_checks.append(check_model_strings(filepath))
        file_checks.append(check_truncation_limits(filepath))

        # Check for key functions if mentioned in claims
        for claim in claims.get("claims", []):
            claim_text = claim.get("claim", "").lower()
            if "deterministic_parse_message" in claim_text:
                file_checks.append(check_function_exists(filepath, "deterministic_parse_message"))
            if "extract_metadata" in claim_text:
                file_checks.append(check_function_exists(filepath, "extract_metadata"))

        verified = sum(1 for c in file_checks if c["result"] == "VERIFIED")
        failed = sum(1 for c in file_checks if c["result"] == "FAILED")
        unable = sum(1 for c in file_checks if c["result"] == "UNABLE_TO_VERIFY")

        results["checks"].append({
            "file": filename,
            "path": str(filepath),
            "verified": verified,
            "failed": failed,
            "unable_to_verify": unable,
            "credibility": round(verified / max(verified + failed, 1), 2),
            "details": file_checks,
        })

    return results


# ── STEP 3: Generate Gap Report ───────────────────────────────────────────

def generate_gap_report(claims: dict, verification: dict) -> dict:
    """Classify findings into gap categories."""
    gaps = {
        "contradicted": [],     # Claim exists, Python check says otherwise
        "unverified": [],       # Claim exists, no way to check
        "verified": [],         # Claim exists, Python confirms
        "file_not_found": [],   # Can't even find the file
    }

    for check in verification.get("checks", []):
        filename = check["file"]

        if check.get("result") == "FILE_NOT_FOUND":
            gaps["file_not_found"].append({"file": filename})
            continue

        for detail in check.get("details", []):
            entry = {"file": filename, "check": detail["check"], "evidence": detail.get("evidence", "")}
            if detail["result"] == "VERIFIED":
                gaps["verified"].append(entry)
            elif detail["result"] == "FAILED":
                gaps["contradicted"].append(entry)
            else:
                gaps["unverified"].append(entry)

    total = len(gaps["verified"]) + len(gaps["contradicted"]) + len(gaps["unverified"])
    credibility = round(len(gaps["verified"]) / max(total, 1), 2)

    return {
        "generated_at": datetime.now().isoformat(),
        "summary": {
            "total_checks": total,
            "verified": len(gaps["verified"]),
            "contradicted": len(gaps["contradicted"]),
            "unverified": len(gaps["unverified"]),
            "files_not_found": len(gaps["file_not_found"]),
            "credibility_score": credibility,
        },
        "gaps": gaps,
    }


# ── Main ──────────────────────────────────────────────────────────────────

def run_session(session_dir: Path) -> dict:
    """Run full Phase 5 on one session."""
    session_name = session_dir.name

    print(f"\n{'='*60}")
    print(f"  Ground Truth Verification: {session_name}")
    print(f"{'='*60}")

    # Step 1: Extract claims
    print("\n[1/3] Extracting claims...")
    claims = extract_claims(session_dir)
    print(f"  Claims extracted: {claims['total_claims']}")

    # Step 2: Verify against source code
    print("\n[2/3] Running verification checks...")
    verification = verify_session(session_dir, claims)
    print(f"  Files checked: {verification['files_checked']}")
    print(f"  Files found: {verification['files_found']}")
    print(f"  Files missing: {verification['files_missing']}")

    # Step 3: Generate gap report
    print("\n[3/3] Generating gap report...")
    gap_report = generate_gap_report(claims, verification)
    s = gap_report["summary"]
    print(f"  Verified:     {s['verified']}")
    print(f"  Contradicted: {s['contradicted']}")
    print(f"  Unverified:   {s['unverified']}")
    print(f"  Credibility:  {s['credibility_score']:.0%}")

    # Write outputs to session directory
    output = {
        "session_id": session_name,
        "generated_at": datetime.now().isoformat(),
        "claims": claims,
        "verification": verification,
        "gap_report": gap_report,
    }

    out_path = session_dir / "ground_truth_verification.json"
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2, default=str)

    print(f"\n  Output: {out_path}")
    return output


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Ground Truth Verification Runner")
    parser.add_argument("--session", type=str, help="Session directory name (e.g. session_0012ebed)")
    parser.add_argument("--all", action="store_true", help="Run on all complete sessions")
    parser.add_argument("--limit", type=int, default=5, help="Max sessions for --all mode")
    args = parser.parse_args()

    if args.all:
        # Find complete sessions (those with grounded_markers.json)
        sessions = []
        for d in sorted(SESSIONS_DIR.iterdir()):
            if d.is_dir() and (d / "grounded_markers.json").exists():
                sessions.append(d)

        print(f"Found {len(sessions)} sessions with grounded markers")
        sessions = sessions[:args.limit]
        print(f"Running on {len(sessions)} sessions")

        all_results = []
        for session_dir in sessions:
            result = run_session(session_dir)
            all_results.append(result["gap_report"]["summary"])

        # Aggregate
        print(f"\n{'='*60}")
        print(f"  AGGREGATE RESULTS ({len(all_results)} sessions)")
        print(f"{'='*60}")
        total_v = sum(r["verified"] for r in all_results)
        total_c = sum(r["contradicted"] for r in all_results)
        total_u = sum(r["unverified"] for r in all_results)
        total = total_v + total_c + total_u
        print(f"  Total checks:  {total}")
        print(f"  Verified:      {total_v} ({total_v/max(total,1):.0%})")
        print(f"  Contradicted:  {total_c} ({total_c/max(total,1):.0%})")
        print(f"  Unverified:    {total_u} ({total_u/max(total,1):.0%})")
        print(f"  Credibility:   {total_v/max(total_v+total_c,1):.0%}")

    elif args.session:
        session_dir = SESSIONS_DIR / args.session
        if not session_dir.exists():
            print(f"ERROR: Session not found: {session_dir}")
            sys.exit(1)
        run_session(session_dir)

    else:
        # Default: pick first complete session
        for d in sorted(SESSIONS_DIR.iterdir()):
            if d.is_dir() and (d / "grounded_markers.json").exists():
                run_session(d)
                break
        else:
            print("ERROR: No sessions with grounded markers found")
            sys.exit(1)


if __name__ == "__main__":
    main()
