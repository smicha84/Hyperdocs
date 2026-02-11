#!/usr/bin/env python3
"""
Phase 1 Full Redo Orchestrator — Reprocesses ALL sessions through Phase 1.

Uses the Anthropic API directly (one call at a time). For each session:
  1. Thread Analyst pass → thread_extractions.json
  2. Geological Reader pass → geological_notes.json
  3. Primitives Tagger pass → semantic_primitives.json
  4. Free Explorer VERIFICATION pass → explorer_notes.json
     (reads all 3 prior outputs + raw data, verifies + discovers)

The Explorer runs LAST deliberately — it verifies Phase 0 data quality
and the other 3 agents' outputs before adding its own discoveries.

Progress is written to ~/PERMANENT_HYPERDOCS/indexes/phase1_redo_progress.json
which the tracking HTML reads.

Usage:
    python3 phase1_redo_orchestrator.py                  # process all sessions
    python3 phase1_redo_orchestrator.py --start-from 50  # resume from session 50
    python3 phase1_redo_orchestrator.py --session session_0012ebed  # one session
"""

import json
import os
import sys
import time
from pathlib import Path
from datetime import datetime, timezone

import anthropic

# ── Config ──────────────────────────────────────────────────────────────
REPO = Path(__file__).resolve().parent
SESSIONS_DIR = Path.home() / "PERMANENT_HYPERDOCS" / "sessions"
PROGRESS_FILE = Path.home() / "PERMANENT_HYPERDOCS" / "indexes" / "phase1_redo_progress.json"
MODEL = "claude-opus-4-6"
MAX_TOKENS = 16000

client = anthropic.Anthropic()

# Add normalizer to path
sys.path.insert(0, str(REPO / "phase_5_ground_truth"))
from schema_normalizer import NORMALIZERS, normalize_file


# ── Agent Prompts ───────────────────────────────────────────────────────

def thread_analyst_prompt(session_id, safe_condensed, safe_tier4, session_summary):
    return f"""You are the Thread Analyst for the Hyperdocs pipeline. Extract 6 analytical threads from session {session_id}.

INPUT DATA:
=== session_summary.json ===
{json.dumps(session_summary, indent=2)[:8000]}

=== safe_tier4.json (priority messages, metadata only) ===
{json.dumps(safe_tier4, indent=2)[:30000]}

=== safe_condensed.json (all messages, metadata only) ===
{json.dumps(safe_condensed, indent=2)[:60000]}

OUTPUT: Return ONLY valid JSON with this EXACT structure (no markdown, no explanation):
{{
  "session_id": "{session_id}",
  "generated_at": "{datetime.now(timezone.utc).isoformat()}",
  "generator": "Phase 1 - Thread Analyst (Opus)",
  "_normalized_at": "{datetime.now(timezone.utc).isoformat()}",
  "threads": {{
    "ideas": {{"description": "Ideas that emerged, evolved, or were abandoned", "entries": [{{"msg_index": 0, "content": "...", "significance": "high|medium|low"}}]}},
    "reactions": {{"description": "Emotional reactions, frustration peaks, breakthroughs", "entries": []}},
    "software": {{"description": "Files created, modified, deleted", "entries": []}},
    "code": {{"description": "Code patterns, architecture decisions", "entries": []}},
    "plans": {{"description": "Plans made, followed, or abandoned", "entries": []}},
    "behavior": {{"description": "Claude behavioral patterns observed", "entries": []}}
  }}
}}

IMPORTANT: Return ONLY the JSON. No markdown code fences. No explanation text."""


def geological_reader_prompt(session_id, safe_condensed, safe_tier4, session_summary):
    return f"""You are the Geological Reader for the Hyperdocs pipeline. Perform multi-resolution analysis of session {session_id}.

INPUT DATA:
=== session_summary.json ===
{json.dumps(session_summary, indent=2)[:8000]}

=== safe_tier4.json ===
{json.dumps(safe_tier4, indent=2)[:30000]}

=== safe_condensed.json ===
{json.dumps(safe_condensed, indent=2)[:60000]}

OUTPUT: Return ONLY valid JSON with this EXACT structure:
{{
  "session_id": "{session_id}",
  "generated_at": "{datetime.now(timezone.utc).isoformat()}",
  "generator": "Phase 1 - Geological Reader (Opus)",
  "_normalized_at": "{datetime.now(timezone.utc).isoformat()}",
  "micro": [{{"observation": "...", "message_range": [0, 0], "evidence": "..."}}],
  "meso": [{{"observation": "...", "message_range": [0, 5], "pattern": "..."}}],
  "macro": [{{"observation": "...", "scope": "full session", "significance": "..."}}],
  "observations": [],
  "geological_metaphor": "..."
}}

Return ONLY the JSON. No markdown. No explanation."""


def primitives_tagger_prompt(session_id, safe_condensed, safe_tier4, session_summary):
    return f"""You are the Primitives Tagger for the Hyperdocs pipeline. Tag tier 2+ messages with the 7 semantic primitives for session {session_id}.

The 7 primitives:
1. action_vector: created|modified|debugged|refactored|discovered|decided|abandoned|reverted
2. confidence_signal: experimental|tentative|working|stable|proven|fragile
3. emotional_tenor: frustrated|uncertain|curious|cautious|confident|excited|relieved
4. intent_marker: correctness|performance|maintainability|feature|bugfix|exploration|cleanup
5. friction_log: single sentence or empty string
6. decision_trace: "chose X over Y because Z" or empty string
7. disclosure_pointer: "{session_id}:msgN"

INPUT DATA:
=== session_summary.json ===
{json.dumps(session_summary, indent=2)[:8000]}

=== safe_tier4.json ===
{json.dumps(safe_tier4, indent=2)[:30000]}

=== safe_condensed.json ===
{json.dumps(safe_condensed, indent=2)[:60000]}

OUTPUT: Return ONLY valid JSON:
{{
  "session_id": "{session_id}",
  "generated_at": "{datetime.now(timezone.utc).isoformat()}",
  "generator": "Phase 1 - Primitives Tagger (Opus)",
  "_normalized_at": "{datetime.now(timezone.utc).isoformat()}",
  "tagged_messages": [{{"msg_index": 0, "role": "user", "tier": 4, "timestamp": "...", "action_vector": "...", "confidence_signal": "...", "emotional_tenor": "...", "intent_marker": "...", "friction_log": "", "decision_trace": "", "disclosure_pointer": "{session_id}:msg0"}}],
  "distributions": {{}},
  "summary_statistics": {{}}
}}

Only tag tier 2+ messages. Return ONLY JSON."""


def explorer_verification_prompt(session_id, safe_condensed, safe_tier4, session_summary,
                                  thread_extractions, geological_notes, semantic_primitives):
    return f"""You are the Free Explorer AND Verification Agent for the Hyperdocs pipeline.

Your job has TWO parts for session {session_id}:

PART 1 — VERIFY: Check the Phase 0 enriched data and the other 3 agents' outputs for errors:
- Are protocol/system messages correctly identified? (is_protocol field)
- Did the char-per-line encoding collapse work? (was_char_encoded field)
- Are content_length values accurate after encoding fix?
- Did the Thread Analyst misidentify system boilerplate as human content?
- Did the Geological Reader build conclusions on measurement bugs?
- Did the Primitives Tagger tag protocol messages as if they were human?
- Are filter signals content-referential (describing analyzed code, not session dynamics)?
- Are error_types actually encountered or just mentioned in discussion?

PART 2 — DISCOVER: Find what the other agents missed:
- Abandoned ideas, surprising patterns, anomalies
- Cross-session connections
- Things that don't fit
- Questions nobody asked

INPUT DATA:
=== session_summary.json ===
{json.dumps(session_summary, indent=2)[:6000]}

=== safe_tier4.json ===
{json.dumps(safe_tier4, indent=2)[:20000]}

=== safe_condensed.json (first 40K chars) ===
{json.dumps(safe_condensed, indent=2)[:40000]}

=== thread_extractions.json (from Thread Analyst) ===
{json.dumps(thread_extractions, indent=2)[:15000]}

=== geological_notes.json (from Geological Reader) ===
{json.dumps(geological_notes, indent=2)[:10000]}

=== semantic_primitives.json (from Primitives Tagger) ===
{json.dumps(semantic_primitives, indent=2)[:10000]}

OUTPUT: Return ONLY valid JSON:
{{
  "session_id": "{session_id}",
  "generated_at": "{datetime.now(timezone.utc).isoformat()}",
  "generator": "Phase 1 - Free Explorer + Verification (Opus)",
  "_normalized_at": "{datetime.now(timezone.utc).isoformat()}",
  "observations": [
    {{"id": "obs-001", "observation": "...", "evidence": "...", "significance": "high|medium|low"}}
  ],
  "verification": {{
    "phase0_issues_found": [],
    "thread_analyst_issues": [],
    "geological_reader_issues": [],
    "primitives_tagger_issues": [],
    "overall_data_quality": "clean|minor_issues|significant_issues"
  }},
  "explorer_summary": "..."
}}

Return ONLY JSON. No markdown. No explanation."""


# ── Processing ──────────────────────────────────────────────────────────

def call_opus(prompt):
    """Make a single Opus API call. Returns parsed JSON or None."""
    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.content[0].text.strip()
        # Strip markdown code fences if present
        if text.startswith("```"):
            text = text.split("\n", 1)[1] if "\n" in text else text[3:]
            if text.endswith("```"):
                text = text[:-3]
            # Also handle ```json
            if text.startswith("json\n"):
                text = text[5:]
            text = text.strip()
        return json.loads(text)
    except json.JSONDecodeError as e:
        print(f"    JSON parse error: {e}")
        # Try to extract JSON from the response
        try:
            start = text.index("{")
            end = text.rindex("}") + 1
            return json.loads(text[start:end])
        except (ValueError, json.JSONDecodeError):
            return None
    except anthropic.APIError as e:
        print(f"    API error: {e}")
        return None
    except Exception as e:
        print(f"    Unexpected error: {e}")
        return None


def load_session_data(session_dir):
    """Load the safe input files for a session."""
    files = {}
    for fname in ["safe_condensed.json", "safe_tier4.json", "session_summary.json"]:
        fpath = session_dir / fname
        if fpath.exists():
            with open(fpath) as f:
                files[fname.replace(".json", "")] = json.load(f)
        else:
            files[fname.replace(".json", "")] = {}
    return files


def process_session(session_dir, progress):
    """Run all 4 Phase 1 passes on one session."""
    session_id = session_dir.name
    data = load_session_data(session_dir)

    results = {"session": session_id, "passes": {}, "errors": []}

    # ── Pass 1: Thread Analyst ──
    print(f"    Thread Analyst...", end="", flush=True)
    t0 = time.time()
    prompt = thread_analyst_prompt(
        session_id, data["safe_condensed"], data["safe_tier4"], data["session_summary"]
    )
    thread_result = call_opus(prompt)
    dt = time.time() - t0
    if thread_result:
        with open(session_dir / "thread_extractions.json", "w") as f:
            json.dump(thread_result, f, indent=2)
        threads = thread_result.get("threads", {})
        n_entries = sum(len(v.get("entries", [])) if isinstance(v, dict) else 0 for v in threads.values())
        results["passes"]["thread_analyst"] = {"status": "ok", "entries": n_entries, "time": round(dt)}
        print(f" {n_entries} entries ({dt:.0f}s)")
    else:
        results["passes"]["thread_analyst"] = {"status": "failed", "time": round(dt)}
        results["errors"].append("thread_analyst failed")
        print(f" FAILED ({dt:.0f}s)")

    # ── Pass 2: Geological Reader ──
    print(f"    Geological Reader...", end="", flush=True)
    t0 = time.time()
    prompt = geological_reader_prompt(
        session_id, data["safe_condensed"], data["safe_tier4"], data["session_summary"]
    )
    geo_result = call_opus(prompt)
    dt = time.time() - t0
    if geo_result:
        with open(session_dir / "geological_notes.json", "w") as f:
            json.dump(geo_result, f, indent=2)
        n_obs = len(geo_result.get("micro", [])) + len(geo_result.get("meso", [])) + len(geo_result.get("macro", []))
        results["passes"]["geological_reader"] = {"status": "ok", "observations": n_obs, "time": round(dt)}
        print(f" {n_obs} observations ({dt:.0f}s)")
    else:
        results["passes"]["geological_reader"] = {"status": "failed", "time": round(dt)}
        results["errors"].append("geological_reader failed")
        print(f" FAILED ({dt:.0f}s)")

    # ── Pass 3: Primitives Tagger ──
    print(f"    Primitives Tagger...", end="", flush=True)
    t0 = time.time()
    prompt = primitives_tagger_prompt(
        session_id, data["safe_condensed"], data["safe_tier4"], data["session_summary"]
    )
    prim_result = call_opus(prompt)
    dt = time.time() - t0
    if prim_result:
        with open(session_dir / "semantic_primitives.json", "w") as f:
            json.dump(prim_result, f, indent=2)
        n_tagged = len(prim_result.get("tagged_messages", []))
        results["passes"]["primitives_tagger"] = {"status": "ok", "tagged": n_tagged, "time": round(dt)}
        print(f" {n_tagged} tagged ({dt:.0f}s)")
    else:
        results["passes"]["primitives_tagger"] = {"status": "failed", "time": round(dt)}
        results["errors"].append("primitives_tagger failed")
        print(f" FAILED ({dt:.0f}s)")

    # ── Pass 4: Free Explorer + Verification (LAST) ──
    # Read the outputs from passes 1-3
    thread_data = thread_result or {}
    geo_data = geo_result or {}
    prim_data = prim_result or {}

    print(f"    Explorer + Verification...", end="", flush=True)
    t0 = time.time()
    prompt = explorer_verification_prompt(
        session_id, data["safe_condensed"], data["safe_tier4"], data["session_summary"],
        thread_data, geo_data, prim_data
    )
    explorer_result = call_opus(prompt)
    dt = time.time() - t0
    if explorer_result:
        with open(session_dir / "explorer_notes.json", "w") as f:
            json.dump(explorer_result, f, indent=2)
        n_obs = len(explorer_result.get("observations", []))
        verification = explorer_result.get("verification", {})
        quality = verification.get("overall_data_quality", "unknown")
        results["passes"]["explorer"] = {"status": "ok", "observations": n_obs, "quality": quality, "time": round(dt)}
        results["verification"] = verification
        print(f" {n_obs} obs, quality={quality} ({dt:.0f}s)")
    else:
        results["passes"]["explorer"] = {"status": "failed", "time": round(dt)}
        results["errors"].append("explorer failed")
        print(f" FAILED ({dt:.0f}s)")

    return results


def update_progress(progress, session_result, idx, total):
    """Update the progress JSON file."""
    progress["updated_at"] = datetime.now(timezone.utc).isoformat()
    progress["current_session"] = idx + 1
    progress["total_sessions"] = total
    progress["pct_complete"] = round((idx + 1) / total * 100, 1)

    if session_result["errors"]:
        progress["failed"].append(session_result)
    else:
        progress["completed"].append({
            "session": session_result["session"],
            "passes": session_result["passes"],
            "verification": session_result.get("verification", {}),
        })

    # Accumulate totals
    for pass_name, pass_result in session_result["passes"].items():
        if pass_result["status"] == "ok":
            progress["totals"]["successful_passes"] += 1
        else:
            progress["totals"]["failed_passes"] += 1

    # Write progress
    with open(PROGRESS_FILE, "w") as f:
        json.dump(progress, f, indent=2, default=str)


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--start-from", type=int, default=0)
    parser.add_argument("--session", type=str, default=None)
    args = parser.parse_args()

    print("=" * 70)
    print("Phase 1 Full Redo — All Sessions, Sequential")
    print(f"Model: {MODEL}")
    print(f"Started: {datetime.now(timezone.utc).isoformat()}")
    print("=" * 70)

    # Get sessions to process
    if args.session:
        session_dirs = [SESSIONS_DIR / args.session]
    else:
        session_dirs = sorted(
            d for d in SESSIONS_DIR.iterdir()
            if d.is_dir() and d.name.startswith("session_")
            and (d / "safe_condensed.json").exists()
        )

    total = len(session_dirs)
    print(f"Sessions to process: {total}")
    print(f"Starting from: {args.start_from}")
    print()

    # Initialize progress
    progress = {
        "operation": "Phase 1 Full Redo",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "current_session": 0,
        "total_sessions": total,
        "pct_complete": 0,
        "completed": [],
        "failed": [],
        "totals": {"successful_passes": 0, "failed_passes": 0},
    }
    with open(PROGRESS_FILE, "w") as f:
        json.dump(progress, f, indent=2)

    start_time = time.time()

    for idx, sd in enumerate(session_dirs):
        if idx < args.start_from:
            continue

        elapsed = time.time() - start_time
        rate = (idx - args.start_from + 1) / elapsed if elapsed > 0 and idx > args.start_from else 0.01
        remaining = (total - idx - 1) / rate if rate > 0 else 0

        print(f"\n[{idx+1}/{total}] {sd.name} (elapsed: {elapsed/60:.0f}m, remaining: ~{remaining/60:.0f}m)")

        result = process_session(sd, progress)
        update_progress(progress, result, idx, total)

    elapsed = time.time() - start_time
    progress["completed_at"] = datetime.now(timezone.utc).isoformat()
    progress["total_duration_seconds"] = round(elapsed)
    with open(PROGRESS_FILE, "w") as f:
        json.dump(progress, f, indent=2, default=str)

    print()
    print("=" * 70)
    print(f"Phase 1 Full Redo — Complete")
    print(f"  Sessions: {total}")
    print(f"  Successful passes: {progress['totals']['successful_passes']}")
    print(f"  Failed passes: {progress['totals']['failed_passes']}")
    print(f"  Duration: {elapsed/60:.0f} minutes")
    print(f"  Progress file: {PROGRESS_FILE}")
    print("=" * 70)


if __name__ == "__main__":
    main()
