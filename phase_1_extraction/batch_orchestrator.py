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

H3 = Path(__file__).resolve().parent.parent  # hyperdocs_3 root
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

# ======================================================================
# @ctx HYPERDOC — HISTORICAL (generated 2026-02-08, requires realtime update)
# These annotations are from the Phase 4b bulk processing run across 284
# sessions. The code below may have changed since these markers were
# generated. Markers reflect the state of the codebase as of Feb 8, 2026.
# ======================================================================

# --- HEADER ---
# ======================================================================
# @ctx HYPERDOC — Phase 4b Generated
# ======================================================================

# --- FOOTER ---
# ======================================================================
# @ctx HYPERDOC — Phase 4b Generated
# ======================================================================
# # ===========================================================================
# # HYPERDOC HEADER: batch_orchestrator.py
# # @ctx:version=1 @ctx:source_sessions=4901d024,5255f985,54451960,636caafa
# # @ctx:generated=2026-02-08T22:45:00Z
# # @ctx:state=stale @ctx:confidence=0.65 @ctx:emotion=neutral
# # @ctx:intent=pipeline_infrastructure @ctx:edits=0 @ctx:mentions=4_sessions
# # @ctx:failed_approaches=0
# # ===========================================================================
# #
# # --- STORY ARC ---
# #
# # batch_orchestrator.py was created during the historical bulk processing
# # campaign (Feb 7-8, 2026, MEMORY.md Chapter 16) to solve an operational
# # tracking problem: 261 sessions needed to flow through Phases 1-3, with
# # dozens of concurrent agent launches, and there was no way to know which
# # sessions had been processed and which still needed work. The file is a
# # 178-line CLI tool designed to be run inside a Claude Code session. It
# # scans the output/ directory, checks for the existence of expected Phase 1
# # and Phase 2 output files per session, and prints instructions for Claude
# # to follow (which agents to launch next, progress counts, queue sizes).
# # The tool worked as intended during the bulk run -- all 261 sessions
# # completed Phases 1-3 by Feb 8. But the pipeline has since grown: Phase 3
# # (file mapper) and Phase 4 (hyperdoc writer) now exist, and
# # batch_orchestrator.py tracks neither. More significantly, 4 separate
# # analysis sessions independently identified that it wastes agent-spawning
# # cost by treating all sessions identically -- warmup sessions, memory agent
# # sessions, and 10-message sessions all trigger the same 4-agent Phase 1
# # launch. The file is functional but stale: it solved the Feb 7-8 bulk run
# # but has not been updated to reflect the current pipeline topology or the
# # optimization insights gathered from processing those 261 sessions.
# #
# # --- FRICTION: WHAT WENT WRONG AND WHY ---
# #
# # @ctx:friction="80% of sessions in a 10-transcript batch were idle warmups, meaning 80% of Phase 1 agent launches produced near-zero analytical value"
# # @ctx:trace=conv_636caafa:grounded_markers_warnings_1
# #   Session 636caafa analyzed transcripts 91-100 and found 8 of 10 were idle
# #   warmup sessions with no substantive content. batch_orchestrator.py has no
# #   warmup detection -- it launches 4 Phase 1 agents per session regardless.
# #   The grounded_markers recommended adding a pre-check: if tier_1_skip > 90%
# #   AND total_messages < 100 AND session_type is spawned_analysis_agent AND
# #   error_count is 0, classify as lightweight and run reduced extraction.
# #   The synthesis pass_5 estimated this could save hundreds of dollars across
# #   the full archive. This remains UNRESOLVED.
# #
# # @ctx:friction="Short sessions with only 10 substantive messages still trigger 4 separate Phase 1 agents, wasting 75% of API cost on redundant parallel analysis"
# # @ctx:trace=conv_5255f985:grounded_markers_R05
# #   Session 5255f985 had 86 total messages but only 10 with substantive content
# #   (1 tier-2, 6 tier-3, 3 tier-4). Four Phase 1 agents (thread, geological,
# #   primitives, explorer) each analyzed the same 10 messages independently.
# #   The grounded_markers recommended a threshold check: sessions with fewer
# #   than 15 tier-2+ messages should launch a single combined agent instead
# #   of 4, reducing cost by approximately 75%. Estimated effort: 40-60 lines.
# #   Risk: medium, because a combined prompt may produce lower-quality
# #   extractions than specialized agents. This remains UNRESOLVED.
# #
# # @ctx:friction="No session type classification causes the pipeline to apply identical analysis expectations to fundamentally different session types (memory agent, primary coding, debugging)"
# # @ctx:trace=conv_4901d024:grounded_markers_recommendation_batch_orchestrator
# #   Session 4901d024 was a memory agent meta-session with a 145:1 input-to-output
# #   token ratio. The file dossier found that batch_orchestrator.py treats all
# #   sessions identically despite sessions varying significantly by type.
# #   Memory agent sessions produce infrastructure insights, not code documentation.
# #   The recommendation was to add automatic session type classification using
# #   the input-to-output token ratio: >100:1 = memory agent, 5:1-20:1 = primary
# #   coding, 20:1-100:1 = debugging/exploration. This remains UNRESOLVED.
# #
# # @ctx:friction="Low-signal sessions (fewer than 5 tier 2+ messages out of 46 total) receive full 6-pass Phase 2 synthesis treatment identical to high-signal sessions"
# # @ctx:trace=conv_54451960:grounded_markers_R5
# #   Session 54451960 had only 2 tier-2+ messages out of 46 total. The grounded
# #   markers recommended that sessions with fewer than 5 tier-2+ messages be
# #   tagged as 'low-signal' and given lighter-weight Phase 2 treatment (skip
# #   the 6-pass synthesis, produce only grounded markers). Effort: low (add a
# #   threshold check in batch_orchestrator.py). This remains UNRESOLVED.
# #
# # @ctx:friction="batch_orchestrator.py only tracks Phases 1 and 2 but the pipeline now includes Phase 3 (file mapper) and Phase 4 (hyperdoc writer), making the tool's status output incomplete"
# # @ctx:trace=conv_636caafa:file_dossiers_D03
# #   The P1_FILES and P2_FILES constants on lines 23-24 define what the tool
# #   checks. There are no P3_FILES or P4_FILES constants. When all 261 sessions
# #   completed Phase 2 and processing moved to Phase 3, the tool's --status and
# #   --next commands stopped being useful. Phase 3 tracking was handled manually
# #   by counting file_dossiers.json files in session directories. This was not
# #   explicitly flagged in session data but is observable from the source code.
# #
# # --- DECISIONS: CHOSE X OVER Y BECAUSE Z ---
# #
# # @ctx:decision="chose CLI instruction printer over automated agent launcher because the tool runs inside a Claude Code session where Claude reads the output and follows the instructions to launch agents via the Task tool"
# # @ctx:trace=conv_636caafa:file_dossiers_D03
# #   Alternatives considered: automated subprocess-based agent launcher, API-driven
# #   orchestrator with retry logic, database-backed job queue
# #   Why rejected: Claude Code's Task tool is the agent spawning mechanism. The
# #   orchestrator cannot spawn agents directly -- it must tell Claude what to do,
# #   and Claude uses Task to do it. An instruction printer is the correct interface
# #   for this constraint. The MEMORY.md confirms this pattern: 'launch remaining
# #   in batches of 15' was done by Claude reading orchestrator output.
# #
# # @ctx:decision="chose file-existence checks (does thread_extractions.json exist?) over a status database or checkpoint file because the output files themselves serve as completion markers"
# # @ctx:trace=conv_636caafa:file_dossiers_D03
# #   Alternatives considered: SQLite database, JSON checkpoint file, Redis queue
# #   Why rejected: file-existence checks are idempotent, require no additional
# #   infrastructure, and survive process crashes. If an agent writes its output
# #   file, the session is done. If it crashes before writing, the file is missing
# #   and the session remains in the queue. Lines 51-52 implement this:
# #   p1_done = all((d / f).exists() for f in P1_FILES).
# #
# # @ctx:decision="chose minimum 20-message threshold for session inclusion over processing all sessions regardless of size because sessions under 20 messages contain insufficient content for meaningful extraction"
# # @ctx:trace=conv_5255f985:grounded_markers_R05
# #   Alternatives considered: no minimum threshold, tier-based filtering, message
# #   content length threshold
# #   Why rejected: No threshold would process empty/trivial sessions. Tier-based
# #   filtering was proposed later (R05) as an enhancement. Line 46 implements the
# #   current 20-message minimum: if total < 20: continue.
# #
# # --- WARNINGS ---
# #
# # @ctx:warning="[W1] [high] No warmup detection pre-check: 80% of agent-spawning cost may be wasted on sessions that contain only initialization messages and no analytical value"
# # @ctx:trace=conv_636caafa:grounded_markers_warnings_1
# #   Resolution: UNRESOLVED
# #   Evidence: Session 636caafa grounded_markers warning[1]: '80% warmup rate
# #   observed in transcripts 91-100. Running full Phase 1 (4 agents) on warmup
# #   sessions wastes agent-spawning cost with near-zero return.' Synthesis pass_5:
# #   'If batch processing spawns 10 agents and 8 produce nothing, then 80% of
# #   agent-spawning cost is wasted.'
# #
# # @ctx:warning="[W2] [medium] No session type classification: memory agent sessions, primary coding sessions, debugging sessions, and security audit sessions all receive identical 4-agent Phase 1 treatment despite having fundamentally different signal profiles"
# # @ctx:trace=conv_4901d024:grounded_markers_recommendation_batch_orchestrator
# #   Resolution: UNRESOLVED
# #   Evidence: Session 4901d024 file_dossiers: 'Without session type
# #   classification, the pipeline applies the same analysis expectations to
# #   memory agent sessions and primary coding sessions. This leads to
# #   false-negative quality assessments.' Proposed token ratio thresholds:
# #   >100:1 = memory agent, 5:1-20:1 = primary coding.
# #
# # @ctx:warning="[W3] [medium] No short-session optimization: sessions with fewer than 15 substantive messages launch 4 agents that each independently analyze the same small message set"
# # @ctx:trace=conv_5255f985:grounded_markers_R05
# #   Resolution: UNRESOLVED
# #   Evidence: Session 5255f985 grounded_markers R05: 'This session had only
# #   10 substantive messages. Four separate Phase 1 agents each analyzed the
# #   same 10 messages independently. A single combined agent could produce
# #   equivalent output at 25% of the API cost.'
# #
# # @ctx:warning="[W4] [medium] Phase tracking is incomplete: only Phases 1-2 are tracked but the pipeline now has 4 phases (Phase 0 prep, Phase 1 extraction, Phase 2 synthesis, Phase 3 file mapping, Phase 4 hyperdoc writing)"
# # @ctx:trace=conv_636caafa:file_dossiers_D03
# #   Resolution: UNRESOLVED
# #   Evidence: Source code lines 23-24 define only P1_FILES and P2_FILES.
# #   No P3_FILES (file_dossiers.json, claude_md_analysis.json) or P4_FILES
# #   (hyperdoc output) constants exist. MEMORY.md Chapter 16 confirms Phase 3
# #   and Phase 4 were tracked outside this tool.
# #
# # --- IRON RULES ---
# #
# # 1. This file must remain a CLI tool that prints instructions. It must not
# #    attempt to spawn agents directly or call the Anthropic API. The agent
# #    spawning mechanism is Claude Code's Task tool, which Claude invokes
# #    after reading the orchestrator's output.
# # 2. Session completion must be determined by file-existence checks, not by
# #    self-reported status from agents. An agent that claims success but did
# #    not write its output file is not done.
# #
# # --- CLAUDE BEHAVIOR ON THIS FILE ---
# #
# # @ctx:claude_pattern="impulse_control: high -- this file was created once and
# #   never modified. No feature creep despite 4 sessions identifying improvements.
# #   The improvements were documented as recommendations, not implemented."
# # @ctx:claude_pattern="authority_response: high -- the file implements a minimal
# #   CLI that follows the user's batch processing workflow. It does not attempt to
# #   automate what the user wants to control."
# # @ctx:claude_pattern="overconfidence: low -- no claims about this tool's
# #   capabilities appear in session data. It is treated as infrastructure, not
# #   as a feature to be celebrated."
# # @ctx:claude_pattern="context_damage: low -- no instances of Claude losing track
# #   of this file's role. All 4 sessions correctly identified it as pipeline
# #   infrastructure and recommendation target."
# #
# # --- EMOTIONAL CONTEXT ---
# #
# # No direct user frustration was directed at this file. It was created during
# # the high-energy bulk processing campaign (Feb 7-8) when the user was focused
# # on getting 261 sessions through the pipeline. The user's emotional state
# # during this period was determined and progress-oriented. The 80% warmup rate
# # finding (session 636caafa) generated intellectual interest (classified as
# # 'curious' in semantic primitives) rather than frustration -- it was a
# # discovery about efficiency, not a failure of the tool. The $48/session cost
# # warning (session 5255f985 W04) was a concern but not directed at
# # batch_orchestrator.py specifically. No user quotes reference this file by name.
# #
# # --- FAILED APPROACHES ---
# #
# # @ctx:failed_approaches=0
# # No failed approaches specific to this file. It was created for the bulk
# # processing run and served its purpose. The 4 identified improvements
# # (warmup detection, session type classification, short-session threshold,
# # phase tracking) are unimplemented recommendations, not failed approaches.
# # The tool was not iterated on -- it was built once and used as-is.
# #
# # --- RECOMMENDATIONS ---
# #
# # [R01] (priority: high)
# #   Add warmup detection pre-check to get_all_sessions(). After reading
# #   session_summary.json, check: if tier_1_skip > 90% AND total_messages < 100
# #   AND session_type is spawned_analysis_agent AND error_count is 0, flag as
# #   'lightweight'. show_next() should recommend 1 agent instead of 4 for
# #   lightweight sessions. Validate the 80% warmup rate against the full 261
# #   session archive before deploying automated skipping.
# #   Evidence: session 636caafa grounded_markers recommendations[1].
# #
# # [R02] (priority: medium)
# #   Add session type classification using input-to-output token ratio from
# #   session_summary.json. Thresholds: >100:1 = memory_agent, 5:1-20:1 =
# #   primary_coding, 20:1-100:1 = debugging_or_exploration. Adjust pipeline
# #   recommendations per type: skip code-focused Phase 1 agents for memory
# #   agent sessions.
# #   Evidence: session 4901d024 grounded_markers.
# #
# # [R03] (priority: medium)
# #   Add short-session threshold: if a session has fewer than 15 tier-2+
# #   messages, recommend launching 1 combined agent instead of 4 for Phase 1.
# #   Estimated savings: 75% API cost per short session. Risk: combined prompt
# #   quality needs A/B testing.
# #   Evidence: session 5255f985 grounded_markers R05.
# #
# # [R04] (priority: medium)
# #   Add P3_FILES and P4_FILES constants to track Phase 3 (file_dossiers.json,
# #   claude_md_analysis.json) and Phase 4 (hyperdoc output) completion. Update
# #   show_status() and show_next() to display Phase 3 and Phase 4 progress.
# #   Evidence: source code inspection (lines 23-24 only define P1 and P2).
# #
# # [R05] (priority: low)
# #   Add low-signal session tagging: sessions with fewer than 5 tier-2+
# #   messages should be tagged for lighter-weight Phase 2 (skip 6-pass
# #   synthesis, produce only grounded markers). This reduces Phase 2 cost
# #   for the many sessions in the archive with minimal content.
# #   Evidence: session 54451960 grounded_markers R5.
# #
# # ===========================================================================
# ======================================================================



# @ctx:inline ----
# # @ctx:function=get_all_sessions @ctx:added=2026-02-07 @ctx:hyperdoc_updated=2026-02-08
# # @ctx:warning="No warmup detection: returns all sessions with Phase 0 complete regardless of whether they contain substantive content"
# # @ctx:warning="No session type classification: memory agent sessions, coding sessions, and audit sessions are returned identically"
# # @ctx:friction="80% of sessions in a tested batch were idle warmups -- this function returns them all for full 4-agent Phase 1 processing"
# # Scans output/ for session directories with enriched_session.json and
# # safe_tier4.json present. Filters out sessions under 20 messages (line 46).
# # Checks file existence for P1_FILES and P2_FILES to determine completion.
# # Returns a list of dicts with short ID, message count, tier4 count, file
# # count, and completion flags. Does not check Phase 3 or Phase 4 output.
# # The 20-message minimum threshold (line 46) was a design choice to exclude
# # trivial sessions, but no tier-based or ratio-based filtering exists.
# ----
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


# @ctx:inline ----
# # @ctx:function=show_next @ctx:added=2026-02-07 @ctx:hyperdoc_updated=2026-02-08
# # @ctx:decision="chose instruction printing over automated launching because agent spawning requires Claude Code's Task tool"
# # Prints the next sessions to process, prioritizing Phase 2 (sessions with
# # P1 done but P2 not done) over Phase 1 (sessions needing P1). Shows top 5
# # of each category with message counts and tier4 counts. Prints specific
# # agent launch instructions for the first session in each queue.
# # Does not include Phase 3 or Phase 4 in its recommendations.
# ----
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


# @ctx:inline ----
# # @ctx:function=show_queue @ctx:added=2026-02-07 @ctx:hyperdoc_updated=2026-02-08
# # @ctx:friction="Groups sessions by message count (small/medium/large) but the actual cost driver is tier-2+ message count and session type, not raw total"
# # Groups sessions needing Phase 1 into LARGE (500+), MEDIUM (100-500), and
# # SMALL (<100) buckets. Shows top 10 per group. The size buckets are based
# # on total_messages, but sessions 5255f985 and 54451960 showed that
# # substantive message count is a better predictor of processing cost.
# ----
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


# ======================================================================
# @ctx HYPERDOC FOOTER
# ======================================================================

# --- INLINE ---
# @ctx:inline ----
# # @ctx:function=get_all_sessions @ctx:added=2026-02-07 @ctx:hyperdoc_updated=2026-02-08
# # @ctx:warning="No warmup detection: returns all sessions with Phase 0 complete regardless of whether they contain substantive content"
# # @ctx:warning="No session type classification: memory agent sessions, coding sessions, and audit sessions are returned identically"
# # @ctx:friction="80% of sessions in a tested batch were idle warmups -- this function returns them all for full 4-agent Phase 1 processing"
# # Scans output/ for session directories with enriched_session.json and
# # safe_tier4.json present. Filters out sessions under 20 messages (line 46).
# # Checks file existence for P1_FILES and P2_FILES to determine completion.
# # Returns a list of dicts with short ID, message count, tier4 count, file
# # count, and completion flags. Does not check Phase 3 or Phase 4 output.
# # The 20-message minimum threshold (line 46) was a design choice to exclude
# # trivial sessions, but no tier-based or ratio-based filtering exists.
# ----

# --- INLINE ---
# @ctx:inline ----
# # @ctx:function=show_next @ctx:added=2026-02-07 @ctx:hyperdoc_updated=2026-02-08
# # @ctx:decision="chose instruction printing over automated launching because agent spawning requires Claude Code's Task tool"
# # Prints the next sessions to process, prioritizing Phase 2 (sessions with
# # P1 done but P2 not done) over Phase 1 (sessions needing P1). Shows top 5
# # of each category with message counts and tier4 counts. Prints specific
# # agent launch instructions for the first session in each queue.
# # Does not include Phase 3 or Phase 4 in its recommendations.
# ----

# --- INLINE ---
# @ctx:inline ----
# # @ctx:function=show_queue @ctx:added=2026-02-07 @ctx:hyperdoc_updated=2026-02-08
# # @ctx:friction="Groups sessions by message count (small/medium/large) but the actual cost driver is tier-2+ message count and session type, not raw total"
# # Groups sessions needing Phase 1 into LARGE (500+), MEDIUM (100-500), and
# # SMALL (<100) buckets. Shows top 10 per group. The size buckets are based
# # on total_messages, but sessions 5255f985 and 54451960 showed that
# # substantive message count is a better predictor of processing cost.
# ----

