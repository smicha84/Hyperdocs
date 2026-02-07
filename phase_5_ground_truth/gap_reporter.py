#!/usr/bin/env python3
"""
Gap Reporter — Combine claims + verification into "Unfinished Business" reports.

Reads ground_truth_claims.json and ground_truth_results.json.
Produces per-file _unfinished_business.json and aggregate ground_truth_summary.json.

The four gap categories:
1. UNVERIFIED — claim exists, no independent confirmation
2. CONTRADICTED — claim exists, Python check contradicts it
3. UNMONITORED — fix was verified once, but no guard prevents regression
4. PREMATURE_VICTORY — Claude declared done, evidence says otherwise
"""
import json
from pathlib import Path
from datetime import datetime

GT_DIR = Path(__file__).parent
SESSION_ID = "3b7084d5"


def load_json(filename):
    path = GT_DIR / filename
    if not path.exists():
        print(f"  ERROR: {filename} not found")
        return {}
    with open(path) as f:
        return json.load(f)


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

    # Build a lookup of check results
    check_map = {}
    for d in details:
        check_map[d["check"]] = d

    file_claims = claims.get("claims", {}).get(filename, {})

    # --- CONTRADICTED: checks that returned FAILED ---
    for d in details:
        if d["result"] == "FAILED":
            gaps["contradicted"].append({
                "category": "CONTRADICTED",
                "claim": d["claim"],
                "check": d["check"],
                "expected": "VERIFIED (claim says this was fixed or doesn't apply)",
                "actual": d["evidence"],
            })

    # --- UNMONITORED: checks that passed but have no automated guard ---
    for d in details:
        if d["result"] == "VERIFIED":
            # These are verified NOW but nothing prevents regression
            claim_text = d["claim"]
            # W03 bare excepts — no automated linter prevents re-introduction
            if "bare except" in claim_text.lower():
                gaps["unmonitored"].append({
                    "category": "UNMONITORED",
                    "claim": claim_text,
                    "current_state": "VERIFIED — no bare excepts found now",
                    "regression_risk": "No pre-commit hook or CI check prevents bare excepts from being re-added",
                    "guard": "none",
                })
            # W12 unsafe API — verified now but no guard
            if "unsafe" in claim_text.lower() and "api" in claim_text.lower():
                gaps["unmonitored"].append({
                    "category": "UNMONITORED",
                    "claim": claim_text,
                    "current_state": "VERIFIED — no unsafe access found now",
                    "regression_risk": "No automated check prevents new response.content[0].text access",
                    "guard": "none",
                })

    # --- UNVERIFIED: claims that have no corresponding check ---
    # Confidence claims, iron rule claims, idea confidence claims
    for conf_claim in file_claims.get("confidence_claims", []):
        gaps["unverified"].append({
            "category": "UNVERIFIED",
            "claim": conf_claim.get("claim", ""),
            "verification_method": "Would need runtime test or manual review",
            "msg_index": conf_claim.get("msg_index"),
            "context": conf_claim.get("friction", conf_claim.get("decision", "")),
        })

    for idea_claim in file_claims.get("idea_confidence_claims", []):
        gaps["unverified"].append({
            "category": "UNVERIFIED",
            "claim": idea_claim.get("claim", ""),
            "verification_method": "Would need functional test of the idea implementation",
            "idea_name": idea_claim.get("idea_name", ""),
        })

    # --- PREMATURE VICTORY: B02 pattern instances ---
    for pv in file_claims.get("premature_victories", []):
        gaps["premature_victory"].append({
            "category": "PREMATURE_VICTORY",
            "pattern": pv.get("pattern", "B02"),
            "claim": pv.get("claim", ""),
            "description": pv.get("description", ""),
            "session_wide": pv.get("session_wide", True),
        })

    # --- Unresolved warnings are also unfinished business ---
    for uw in file_claims.get("unresolved_warnings", []):
        # Check if our verifier already caught this as CONTRADICTED
        already_caught = any(
            uw["warning_id"] in c["claim"]
            for c in gaps["contradicted"]
        )
        if not already_caught:
            gaps["unverified"].append({
                "category": "UNVERIFIED",
                "claim": f"{uw['warning_id']}: {uw.get('claim', 'UNRESOLVED')}",
                "warning": uw.get("warning", "")[:200],
                "severity": uw.get("severity", "unknown"),
                "verification_method": "Manual code review needed",
            })

    return gaps


def compute_credibility(file_results):
    """Compute credibility score: verified / (verified + failed)."""
    verified = file_results.get("verified", 0)
    failed = file_results.get("failed", 0)
    total = verified + failed
    if total == 0:
        return 0.0
    return round(verified / total, 2)


def main():
    print("=" * 60)
    print("Gap Reporter — Unfinished Business")
    print("=" * 60)
    print(f"Session: conv_{SESSION_ID}")
    print(f"Timestamp: {datetime.now().isoformat()}")
    print()

    claims = load_json("ground_truth_claims.json")
    results = load_json("ground_truth_results.json")

    if not claims or not results:
        print("ERROR: Missing input files.")
        return

    all_gaps = {}
    summary_rows = []

    for filename in claims.get("claims", {}):
        gaps = classify_gaps(filename, claims, results)
        all_gaps[filename] = gaps

        # Write per-file report
        file_results = results.get("files", {}).get(filename, {})
        credibility = compute_credibility(file_results)

        report = {
            "file": filename,
            "session": f"conv_{SESSION_ID}",
            "generated_at": datetime.now().isoformat(),
            "credibility_score": credibility,
            "checks_verified": file_results.get("verified", 0),
            "checks_failed": file_results.get("failed", 0),
            "checks_unable": file_results.get("unable_to_verify", 0),
            "gaps": gaps,
            "total_unfinished_items": sum(len(v) for v in gaps.values()),
        }

        report_path = GT_DIR / f"{filename}_unfinished_business.json"
        with open(report_path, "w") as f:
            json.dump(report, f, indent=2)

        total_items = report["total_unfinished_items"]
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

        print(f"  {filename}: credibility={credibility:.0%}, "
              f"{contradicted} contradicted, {unverified} unverified, "
              f"{unmonitored} unmonitored")

    # Aggregate summary
    total_contradicted = sum(r["contradicted"] for r in summary_rows)
    total_unverified = sum(r["unverified"] for r in summary_rows)
    total_unmonitored = sum(r["unmonitored"] for r in summary_rows)
    total_items = sum(r["total"] for r in summary_rows)
    avg_credibility = sum(r["credibility"] for r in summary_rows) / len(summary_rows) if summary_rows else 0

    summary = {
        "session_id": SESSION_ID,
        "generated_at": datetime.now().isoformat(),
        "total_files": len(summary_rows),
        "average_credibility": round(avg_credibility, 2),
        "total_unfinished_items": total_items,
        "total_contradicted": total_contradicted,
        "total_unverified": total_unverified,
        "total_unmonitored": total_unmonitored,
        "confidence_evidence_gap": "5.7:1 (119 confident emotional tenors vs 21 proven confidence signals)",
        "per_file": summary_rows,
    }

    summary_path = GT_DIR / "ground_truth_summary.json"
    with open(summary_path, "w") as f:
        json.dump(summary, f, indent=2)

    print()
    print("=" * 60)
    print(f"AGGREGATE: {total_items} unfinished items across {len(summary_rows)} files")
    print(f"  Contradicted:  {total_contradicted} (Python found evidence against the claim)")
    print(f"  Unverified:    {total_unverified} (no independent confirmation)")
    print(f"  Unmonitored:   {total_unmonitored} (verified now but no guard prevents regression)")
    print(f"  Avg credibility: {avg_credibility:.0%}")
    print(f"  Confidence gap:  5.7:1")
    print(f"\nSummary: {summary_path}")
    print(f"Per-file reports: {GT_DIR}/*_unfinished_business.json")


if __name__ == "__main__":
    main()
