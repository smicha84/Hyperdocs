#!/usr/bin/env python3
"""
Gap Reporter — Combine claims + verification into "Unfinished Business" reports.

Reads ground_truth_claims.json and ground_truth_results.json.
Produces ground_truth_summary.json (aggregate) in session output directory.

The four gap categories:
1. UNVERIFIED — claim exists, no independent confirmation
2. CONTRADICTED — claim exists, Python check contradicts it
3. UNMONITORED — fix was verified once, but no guard prevents regression
4. PREMATURE_VICTORY — Claude declared done, evidence says otherwise

Usage:
    python3 gap_reporter.py --session 0012ebed
    python3 gap_reporter.py --dir /path/to/session_output/
"""
import argparse
import json
import os
import sys
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
try:
    from config import get_session_output_dir, SESSION_ID
except ImportError:
    SESSION_ID = os.getenv("HYPERDOCS_SESSION_ID", "")
    _out = Path(os.getenv("HYPERDOCS_OUTPUT_DIR", str(Path(__file__).parent.parent / "output")))
    def get_session_output_dir():
        d = _out / f"session_{SESSION_ID[:8]}"
        d.mkdir(parents=True, exist_ok=True)
        return d


def load_json(session_dir, filename):
    path = session_dir / filename
    if not path.exists():
        print(f"  ERROR: {filename} not found")
        return {}
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, UnicodeDecodeError):
        return {}


def classify_gaps(filename, claims, results):
    """Classify each finding into one of 4 gap categories."""
    gaps = {
        "unverified": [],
        "contradicted": [],
        "unmonitored": [],
        "premature_victory": [],
    }

    file_results = results.get("files", {}).get(filename, {})
    details = file_results.get("details", [])
    file_claims = claims.get("claims", {}).get(filename, {})

    # CONTRADICTED: checks that returned FAILED
    for d in details:
        if d["result"] == "FAILED":
            gaps["contradicted"].append({
                "category": "CONTRADICTED",
                "claim": d["claim"],
                "check": d["check"],
                "expected": "VERIFIED",
                "actual": d["evidence"],
            })

    # UNMONITORED: checks that passed but have no automated guard
    for d in details:
        if d["result"] == "VERIFIED":
            claim_text = d["claim"]
            if "bare except" in claim_text.lower() or "unsafe" in claim_text.lower():
                gaps["unmonitored"].append({
                    "category": "UNMONITORED",
                    "claim": claim_text,
                    "current_state": "VERIFIED now",
                    "regression_risk": "No automated guard prevents re-introduction",
                    "guard": "none",
                })

    # UNVERIFIED: confidence and idea claims without runtime confirmation
    for conf_claim in file_claims.get("confidence_claims", []):
        gaps["unverified"].append({
            "category": "UNVERIFIED",
            "claim": conf_claim.get("claim", ""),
            "verification_method": "Would need runtime test or manual review",
            "msg_index": conf_claim.get("msg_index"),
        })

    for idea_claim in file_claims.get("idea_confidence_claims", []):
        gaps["unverified"].append({
            "category": "UNVERIFIED",
            "claim": idea_claim.get("claim", ""),
            "verification_method": "Would need functional test of the idea implementation",
        })

    # PREMATURE VICTORY: pattern claims
    for pv in file_claims.get("pattern_claims", file_claims.get("premature_victories", [])):
        if "B02" in str(pv.get("pattern", "")):
            gaps["premature_victory"].append({
                "category": "PREMATURE_VICTORY",
                "pattern": pv.get("pattern", ""),
                "claim": pv.get("claim", ""),
            })

    # Unresolved warnings
    for uw in file_claims.get("unresolved_warnings", []):
        already_caught = any(
            str(uw.get("warning_id", "")) in str(c.get("claim", ""))
            for c in gaps["contradicted"]
        )
        if not already_caught:
            gaps["unverified"].append({
                "category": "UNVERIFIED",
                "claim": f"{uw.get('warning_id', '')}: {uw.get('claim', 'UNRESOLVED')}",
                "severity": uw.get("severity", "unknown"),
            })

    return gaps


def compute_credibility(file_results):
    verified = file_results.get("verified", 0)
    failed = file_results.get("failed", 0)
    total = verified + failed
    if total == 0:
        return 0.0
    return round(verified / total, 2)


def main():
    parser = argparse.ArgumentParser(description="Gap Reporter — Unfinished Business")
    parser.add_argument("--session", default="", help="Session ID")
    parser.add_argument("--dir", default="", help="Session output directory path")
    args = parser.parse_args()

    if args.dir:
        session_dir = Path(args.dir)
    elif args.session:
        candidates = [
            Path(__file__).resolve().parent.parent / "output" / f"session_{args.session[:8]}",
            Path.home() / "PERMANENT_HYPERDOCS" / "sessions" / f"session_{args.session[:8]}",
        ]
        session_dir = next((c for c in candidates if c.exists()), candidates[0])
    else:
        session_dir = get_session_output_dir()

    print("=" * 60)
    print("Gap Reporter — Unfinished Business")
    print("=" * 60)
    print(f"Session dir: {session_dir}")
    print()

    claims = load_json(session_dir, "ground_truth_claims.json")
    results = load_json(session_dir, "ground_truth_results.json")

    if not claims or not results:
        print("ERROR: Missing input files. Run claim_extractor.py and ground_truth_verifier.py first.")
        sys.exit(1)

    summary_rows = []

    for filename in claims.get("claims", {}):
        gaps = classify_gaps(filename, claims, results)
        file_results = results.get("files", {}).get(filename, {})
        credibility = compute_credibility(file_results)

        total_items = sum(len(v) for v in gaps.values())
        contradicted = len(gaps["contradicted"])
        unverified = len(gaps["unverified"])
        unmonitored = len(gaps["unmonitored"])

        summary_rows.append({
            "file": filename,
            "credibility": credibility,
            "contradicted": contradicted,
            "unverified": unverified,
            "unmonitored": unmonitored,
            "total": total_items,
        })

        if total_items > 0:
            print(f"  {filename}: credibility={credibility:.0%}, "
                  f"{contradicted}C {unverified}U {unmonitored}M")

    # Aggregate
    total_contradicted = sum(r["contradicted"] for r in summary_rows)
    total_unverified = sum(r["unverified"] for r in summary_rows)
    total_unmonitored = sum(r["unmonitored"] for r in summary_rows)
    total_items = sum(r["total"] for r in summary_rows)
    avg_credibility = sum(r["credibility"] for r in summary_rows) / len(summary_rows) if summary_rows else 0

    session_id = args.session or SESSION_ID or session_dir.name.replace("session_", "")
    summary = {
        "session_id": session_id,
        "generated_at": datetime.now().isoformat(),
        "total_files": len(summary_rows),
        "average_credibility": round(avg_credibility, 2),
        "total_unfinished_items": total_items,
        "total_contradicted": total_contradicted,
        "total_unverified": total_unverified,
        "total_unmonitored": total_unmonitored,
        "per_file": summary_rows,
    }

    summary_path = session_dir / "ground_truth_summary.json"
    with open(summary_path, "w") as f:
        json.dump(summary, f, indent=2)

    # Also write a combined verification file for gap_checklist.py to consume
    verification = {
        "session_id": session_id,
        "generated_at": datetime.now().isoformat(),
        "claims": [],
    }
    for filename in claims.get("claims", {}):
        file_results_data = results.get("files", {}).get(filename, {})
        for check in file_results_data.get("details", []):
            verification["claims"].append({
                "file": filename,
                "claim": check["claim"],
                "verification_status": "verified" if check["result"] == "VERIFIED" else
                                       "failed" if check["result"] == "FAILED" else None,
                "evidence": check.get("evidence", ""),
            })

    verification_path = session_dir / "ground_truth_verification.json"
    with open(verification_path, "w") as f:
        json.dump(verification, f, indent=2)

    print()
    print(f"AGGREGATE: {total_items} unfinished items across {len(summary_rows)} files")
    print(f"  Contradicted:  {total_contradicted}")
    print(f"  Unverified:    {total_unverified}")
    print(f"  Unmonitored:   {total_unmonitored}")
    print(f"  Avg credibility: {avg_credibility:.0%}")
    print(f"\nSummary: {summary_path}")
    print(f"Verification: {verification_path}")


if __name__ == "__main__":
    main()
