#!/usr/bin/env python3
"""
Iterate — Gap-Driven Refinement Loop

Each pass:
1. Run gap_checklist.py — measure current state
2. If ground_truth is a gap, run Phase 5 (claim_extractor → verifier → gap_reporter)
3. Re-run gap_checklist.py — measure new state
4. Compare: if no improvement (stall) or all gaps structural → stop

The key: Phase 5 is the only $0 operation that changes data between passes.
Extraction gaps (missing Phase 1/2/3 files) require LLM agent runs — iterate.py
logs these as "needs_agent_run" and stops, rather than pretending to fix them.

Based on:
- ITERX's MDP termination: stop when no new information
- RefineBench's hard cap: max 4 passes
- FAIR-RAG: gap-driven sub-queries

Usage:
    python3 iterate.py --session 0012ebed
    python3 iterate.py --session 0012ebed --max-passes 4
    python3 iterate.py --dir /path/to/session/

Output: iteration_log.json in the session output directory
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path
from datetime import datetime

# Import gap_checklist's analyze function directly
sys.path.insert(0, str(Path(__file__).resolve().parent))
from gap_checklist import analyze_session, load_json

PHASE_5_DIR = Path(__file__).resolve().parent / "phase_5_ground_truth"
CLAIM_EXTRACTOR = PHASE_5_DIR / "claim_extractor.py"
GROUND_TRUTH_VERIFIER = PHASE_5_DIR / "ground_truth_verifier.py"
GAP_REPORTER = PHASE_5_DIR / "gap_reporter.py"


def find_session_dir(session_id):
    """Find session directory from session ID."""
    candidates = [
        Path(__file__).resolve().parent / "output" / f"session_{session_id[:8]}",
        Path.home() / "PERMANENT_HYPERDOCS" / "sessions" / f"session_{session_id[:8]}",
    ]
    return next((c for c in candidates if c.exists()), candidates[0])


def classify_gaps(gaps):
    """Separate gaps into fixable, structural, and needs_agent categories."""
    fixable_by_phase5 = []  # ground_truth gaps — we can run Phase 5
    needs_agent = []        # missing Phase 1/2/3 files — need LLM agents
    structural = []         # data_absent — not fixable

    for g in gaps:
        if g.get("gap_type") == "data_absent" or g.get("priority") == "structural":
            structural.append(g)
        elif g.get("field") == "ground_truth" or g.get("priority") == "medium":
            # Medium-priority gaps from populated ratio checks or ground_truth
            if g.get("field") == "ground_truth":
                fixable_by_phase5.append(g)
            else:
                needs_agent.append(g)
        elif g.get("priority") == "critical":
            needs_agent.append(g)
        elif g.get("priority") == "high":
            needs_agent.append(g)
        else:
            needs_agent.append(g)

    return fixable_by_phase5, needs_agent, structural


def run_phase5(session_dir):
    """Run the full Phase 5 pipeline (claim_extractor → verifier → gap_reporter)."""
    steps = [
        ("claim_extractor", CLAIM_EXTRACTOR),
        ("ground_truth_verifier", GROUND_TRUTH_VERIFIER),
        ("gap_reporter", GAP_REPORTER),
    ]
    for name, script in steps:
        result = subprocess.run(
            [sys.executable, str(script), "--dir", str(session_dir)],
            capture_output=True, text=True, timeout=120,
        )
        if result.returncode != 0:
            return False, f"{name} failed: {result.stderr[:100]}"
    return True, "Phase 5 complete"


def main():
    parser = argparse.ArgumentParser(description="Iterate — Gap-Driven Refinement Loop")
    parser.add_argument("--session", default="", help="Session ID")
    parser.add_argument("--dir", default="", help="Session output directory path")
    parser.add_argument("--max-passes", type=int, default=4, help="Maximum iteration passes (default: 4)")
    args = parser.parse_args()

    if args.dir:
        session_dir = Path(args.dir)
    elif args.session:
        session_dir = find_session_dir(args.session)
    else:
        print("ERROR: Provide --session or --dir")
        sys.exit(1)

    if not session_dir.exists():
        print(f"ERROR: Session directory not found: {session_dir}")
        sys.exit(1)

    print("=" * 60)
    print("Iterate — Gap-Driven Refinement Loop")
    print("=" * 60)
    print(f"Session dir: {session_dir}")
    print(f"Max passes: {args.max_passes}")
    print()

    iteration_log = {
        "session_dir": str(session_dir),
        "started_at": datetime.now().isoformat(),
        "max_passes": args.max_passes,
        "passes": [],
        "actions_taken": [],
    }

    previous = None
    checklist = None

    for pass_num in range(1, args.max_passes + 1):
        print(f"\n--- Pass {pass_num} ---")

        # Step 1: Measure current state
        checklist = analyze_session(session_dir, previous)

        # Classify gaps
        fixable_by_phase5, needs_agent, structural = classify_gaps(checklist.get("gaps", []))
        conv = checklist.get("convergence", {})
        summ = checklist.get("summary", {})

        pass_record = {
            "pass_number": checklist.get("pass_number", pass_num),
            "timestamp": datetime.now().isoformat(),
            "total_confirmed": conv.get("total_confirmed", 0),
            "total_gaps": conv.get("total_gaps", 0),
            "structural_gaps": len(structural),
            "fixable_by_phase5": len(fixable_by_phase5),
            "needs_agent": len(needs_agent),
            "coverage_score": summ.get("coverage_score", 0),
            "adjusted_coverage_score": summ.get("adjusted_coverage_score", 0),
            "recommendation": conv.get("recommendation", "unknown"),
        }
        iteration_log["passes"].append(pass_record)

        print(f"  Confirmed: {conv.get('total_confirmed', 0)}")
        print(f"  Gaps: {conv.get('total_gaps', 0)} (structural: {len(structural)}, "
              f"fixable: {len(fixable_by_phase5)}, needs_agent: {len(needs_agent)})")
        print(f"  Coverage: {summ.get('coverage_score', 0):.0%} (adjusted: {summ.get('adjusted_coverage_score', 0):.0%})")

        # Check termination: converged
        if conv.get("recommendation") == "converged":
            print(f"\n  CONVERGED at pass {pass_num}")
            iteration_log["outcome"] = "converged"
            break

        # Check termination: only structural gaps remain
        if len(fixable_by_phase5) == 0 and len(needs_agent) == 0:
            print(f"\n  NO FIXABLE GAPS — only structural gaps remain")
            iteration_log["outcome"] = "structural_only"
            break

        # Check termination: stall (no improvement between passes)
        missing_delta = conv.get("missing_values_delta")
        if missing_delta is not None and abs(missing_delta) < 0.02 and pass_num > 1:
            print(f"\n  STALLED — no improvement (delta: {missing_delta:+.1%})")
            iteration_log["outcome"] = "stalled"
            break

        # Step 2: Take action on fixable gaps
        action_taken = False

        # Run Phase 5 if ground_truth is missing or stale
        gt_missing = "ground_truth_verification.json" in [
            fname for fname, status in checklist.get("file_status", {}).items()
            if status == "MISSING"
        ]
        has_gt_gap = len(fixable_by_phase5) > 0
        has_dossiers = (session_dir / "file_dossiers.json").exists()

        if (gt_missing or has_gt_gap) and has_dossiers:
            print(f"\n  ACTION: Running Phase 5 (ground truth verification)...")
            ok, msg = run_phase5(session_dir)
            if ok:
                print(f"    Phase 5 succeeded")
                iteration_log["actions_taken"].append({
                    "pass": pass_num,
                    "action": "phase_5",
                    "result": "success",
                })
                action_taken = True
            else:
                print(f"    Phase 5 failed: {msg}")
                iteration_log["actions_taken"].append({
                    "pass": pass_num,
                    "action": "phase_5",
                    "result": "failed",
                    "error": msg,
                })

        # Log gaps that need agent runs (can't fix automatically)
        if needs_agent:
            print(f"\n  NEEDS AGENT RUN ({len(needs_agent)} gaps):")
            for g in needs_agent:
                print(f"    [{g.get('priority', '?').upper():8s}] {g['field']}: {g.get('reason', '')[:70]}")
            iteration_log["actions_taken"].append({
                "pass": pass_num,
                "action": "logged_agent_needs",
                "gaps": [g["field"] for g in needs_agent],
            })

        if structural:
            print(f"\n  Structural gaps (data_absent — session characteristic):")
            for g in structural:
                print(f"    {g['field']}: missing {g.get('missing_values', [])}")

        # If no action was taken (nothing fixable by Phase 5, only agent gaps), stop
        if not action_taken and len(needs_agent) > 0:
            print(f"\n  BLOCKED — remaining gaps need LLM agent runs")
            iteration_log["outcome"] = "blocked_needs_agents"
            break

        if not action_taken:
            print(f"\n  NO ACTION AVAILABLE")
            iteration_log["outcome"] = "no_action_available"
            break

        # Save checklist for next pass comparison
        previous = checklist
        with open(session_dir / "gap_checklist.json", "w") as f:
            json.dump(checklist, f, indent=2, default=str)

    else:
        # Reached max passes
        print(f"\n  MAX PASSES ({args.max_passes}) reached")
        iteration_log["outcome"] = "max_passes"

    # Write final checklist
    if checklist:
        with open(session_dir / "gap_checklist.json", "w") as f:
            json.dump(checklist, f, indent=2, default=str)

    # Write iteration log
    iteration_log["finished_at"] = datetime.now().isoformat()
    iteration_log["final_coverage"] = summ.get("coverage_score", 0) if checklist else 0
    iteration_log["final_adjusted_coverage"] = summ.get("adjusted_coverage_score", 0) if checklist else 0
    iteration_log["total_passes"] = len(iteration_log["passes"])

    log_path = session_dir / "iteration_log.json"
    with open(log_path, "w") as f:
        json.dump(iteration_log, f, indent=2)

    print()
    print("=" * 60)
    print(f"Outcome: {iteration_log.get('outcome', 'unknown')}")
    print(f"Total passes: {iteration_log['total_passes']}")
    print(f"Actions taken: {len(iteration_log['actions_taken'])}")
    if checklist:
        print(f"Final coverage: {iteration_log['final_coverage']:.0%} (adjusted: {iteration_log['final_adjusted_coverage']:.0%})")
    print(f"Log: {log_path}")


if __name__ == "__main__":
    main()
