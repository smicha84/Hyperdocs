#!/usr/bin/env python3
"""
Batch Orchestrator — Runs Phases 1-2 across all sessions automatically.

This script is meant to be run INSIDE a Claude Code session. It prints
instructions that Claude should follow — launching agents via the Task tool,
checking outputs, and moving to the next session.

Usage:
    python3 batch_orchestrator.py --next       Show the next session to process
    python3 batch_orchestrator.py --status     Show overall progress
    python3 batch_orchestrator.py --queue      Show full queue with sizes
"""
import argparse
import json
import os
from pathlib import Path
from datetime import datetime

H3 = Path(__file__).resolve().parent
OUTPUT = H3 / "output"

P1_FILES = ["thread_extractions.json", "geological_notes.json", "semantic_primitives.json", "explorer_notes.json"]
P2_FILES = ["idea_graph.json", "synthesis.json", "grounded_markers.json"]


def get_all_sessions():
    """Get all sessions with Phase 0 complete, sorted by directory name."""
    sessions = []
    for d in sorted(OUTPUT.iterdir()):
        if not d.is_dir() or not d.name.startswith("session_"):
            continue
        if not (d / "enriched_session.json").exists():
            continue
        if not (d / "safe_tier4.json").exists():
            continue

        summary_f = d / "session_metadata.json"
        if not summary_f.exists():
            continue

        summary = json.load(open(summary_f))
        stats = summary.get("session_stats", summary)
        total = stats.get("total_messages", 0)
        if total < 20:
            continue

        tier4 = stats.get("tier_distribution", {}).get("4_priority", 0)
        files = len(stats.get("file_mention_counts", {}))

        p1_done = all((d / f).exists() for f in P1_FILES)
        p2_done = all((d / f).exists() for f in P2_FILES)

        sessions.append({
            "dir": d.name,
            "short": d.name.replace("session_", ""),
            "total": total,
            "tier4": tier4,
            "files": files,
            "p1_done": p1_done,
            "p2_done": p2_done,
            "path": str(d),
        })

    return sessions


def show_status():
    sessions = get_all_sessions()
    p0 = len(sessions)
    p1 = sum(1 for s in sessions if s["p1_done"])
    p2 = sum(1 for s in sessions if s["p2_done"])

    print("=" * 60)
    print("Hyperdocs Batch Orchestrator — Status")
    print("=" * 60)
    print(f"Phase 0 complete: {p0}")
    print(f"Phase 1 complete: {p1}/{p0} ({p0-p1} remaining)")
    print(f"Phase 2 complete: {p2}/{p0} ({p0-p2} remaining)")
    print()

    # Estimate remaining work
    need_p1 = p0 - p1
    need_p2 = p0 - p2
    print(f"Estimated remaining agent launches:")
    print(f"  Phase 1: {need_p1} sessions x 4 agents = {need_p1 * 4}")
    print(f"  Phase 2: {need_p2} sessions x 2 agents = {need_p2 * 2}")
    print(f"  Total: {need_p1 * 4 + need_p2 * 2}")


def show_next():
    sessions = get_all_sessions()

    # Find sessions needing Phase 1
    need_p1 = [s for s in sessions if not s["p1_done"]]
    # Find sessions needing Phase 2 (Phase 1 done)
    need_p2 = [s for s in sessions if s["p1_done"] and not s["p2_done"]]

    print("=" * 60)
    print("Next Sessions to Process")
    print("=" * 60)

    if need_p2:
        print(f"\n--- PHASE 2 READY ({len(need_p2)} sessions have P1 done, need P2) ---")
        for s in need_p2[:5]:
            print(f"  {s['short']}  {s['total']} msgs  {s['tier4']} tier4  {s['files']} files")
        print()
        s = need_p2[0]
        print(f"LAUNCH PHASE 2 for {s['short']}:")
        print(f"  Agent 1: Idea Graph Builder — read P1 outputs from {s['path']}/")
        print(f"  Agent 2: Synthesizer — read P1 outputs, write synthesis.json + grounded_markers.json")
        print()

    if need_p1:
        print(f"\n--- PHASE 1 NEEDED ({len(need_p1)} sessions) ---")
        for s in need_p1[:5]:
            print(f"  {s['short']}  {s['total']} msgs  {s['tier4']} tier4  {s['files']} files")
        print()
        s = need_p1[0]
        base = s['path']
        print(f"LAUNCH PHASE 1 for {s['short']}:")
        print(f"  Agent 1: Thread Analyst — read safe files from {base}/")
        print(f"  Agent 2: Geological Reader")
        print(f"  Agent 3: Primitives Tagger")
        print(f"  Agent 4: Free Explorer")
        print(f"  All agents read: session_metadata.json, safe_tier4.json, safe_condensed.json")
        print()

    if not need_p1 and not need_p2:
        print("ALL SESSIONS COMPLETE through Phase 2!")


def show_queue():
    sessions = get_all_sessions()
    need_p1 = [s for s in sessions if not s["p1_done"]]

    print(f"Full queue — {len(need_p1)} sessions needing Phase 1:")
    print()
    print(f"{'Session':<16} {'Msgs':>6} {'T4':>5} {'Files':>6} {'Size':>8}")
    print("-" * 45)

    # Group by size
    small = [s for s in need_p1 if s["total"] < 100]
    medium = [s for s in need_p1 if 100 <= s["total"] < 500]
    large = [s for s in need_p1 if s["total"] >= 500]

    for label, group in [("LARGE (500+)", large), ("MEDIUM (100-500)", medium), ("SMALL (<100)", small)]:
        if group:
            print(f"\n  {label}: {len(group)} sessions")
            for s in group[:10]:
                print(f"  {s['short']:<16} {s['total']:>6} {s['tier4']:>5} {s['files']:>6}")
            if len(group) > 10:
                print(f"  ... and {len(group) - 10} more")


def main():
    parser = argparse.ArgumentParser(description="Hyperdocs Batch Orchestrator")
    parser.add_argument("--status", action="store_true", help="Show overall progress")
    parser.add_argument("--next", action="store_true", help="Show next session to process")
    parser.add_argument("--queue", action="store_true", help="Show full queue")

    args = parser.parse_args()

    if args.status:
        show_status()
    elif args.next:
        show_next()
    elif args.queue:
        show_queue()
    else:
        show_status()
        print()
        show_next()


if __name__ == "__main__":
    main()
