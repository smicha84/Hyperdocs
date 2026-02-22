#!/usr/bin/env python3
"""
End-to-end pipeline runner for Hyperdocs.

Runs a session through all deterministic phases (free, no API calls):
  Phase 0: deterministic_prep.py → enriched_session.json
  Phase 0b: prepare_agent_data.py → session_metadata.json, tier files, safe files
  Phase 2: batch_p2_generator.py (deterministic) → idea_graph.json, synthesis.json, grounded_markers.json

Optional (requires ANTHROPIC_API_KEY):
  --full: Also runs Phase 1 (Opus extraction agents) and Phase 3 (dossiers, viewer)
  --phase N: Run only phase N

Usage:
    python3 tools/run_pipeline.py SESSION_ID                    # Phase 0 + 2 (free)
    python3 tools/run_pipeline.py SESSION_ID --full             # All phases
    python3 tools/run_pipeline.py SESSION_ID --phase 1          # Just Phase 1
    python3 tools/run_pipeline.py SESSION_ID --normalize        # Run schema normalizer
"""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PHASE_0_DIR = REPO_ROOT / "phase_0_prep"
PHASE_1_DIR = REPO_ROOT / "phase_1_extraction"
PHASE_3_DIR = REPO_ROOT / "phase_3_hyperdoc_writing"
OUTPUT_DIR = REPO_ROOT / "output"


def run_script(script_path, session_id, extra_env=None, description="", pass_session_arg=False):
    """Run a Python script with HYPERDOCS_SESSION_ID set."""
    env = {
        **os.environ,
        "HYPERDOCS_SESSION_ID": session_id,
        "HYPERDOCS_OUTPUT_DIR": str(OUTPUT_DIR),
    }
    if extra_env:
        env.update(extra_env)

    print(f"\n{'='*60}")
    print(f"  Running: {description or script_path.name}")
    print(f"  Script:  {script_path}")
    print(f"  Session: {session_id}")
    print(f"{'='*60}")

    cmd = [sys.executable, str(script_path)]
    if pass_session_arg:
        cmd.extend(["--session", session_id])

    result = subprocess.run(
        cmd,
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
    )

    if result.stdout:
        # Print last 20 lines of output to keep it readable
        lines = result.stdout.strip().split('\n')
        if len(lines) > 20:
            print(f"  ... ({len(lines) - 20} lines omitted)")
        for line in lines[-20:]:
            print(f"  {line}")

    if result.returncode != 0:
        print(f"\n  ERROR (exit code {result.returncode}):")
        if result.stderr:
            for line in result.stderr.strip().split('\n')[-10:]:
                print(f"  {line}")
        return False

    return True


def run_phase_0(session_id):
    """Phase 0: Deterministic prep (free, pure Python)."""
    session_dir = OUTPUT_DIR / f"session_{session_id[:8]}"
    session_dir.mkdir(parents=True, exist_ok=True)

    # Step 1: deterministic_prep.py
    ok = run_script(
        PHASE_0_DIR / "deterministic_prep.py",
        session_id,
        description="Phase 0: Deterministic Prep (metadata extraction)",
    )
    if not ok:
        return False

    # Step 2: prepare_agent_data.py
    ok = run_script(
        PHASE_0_DIR / "prepare_agent_data.py",
        session_id,
        description="Phase 0b: Prepare Agent Data (split enriched session)",
    )
    if not ok:
        return False

    return True


def run_schema_normalizer(session_id):
    """Run schema normalizer on the session directory."""
    return run_script(
        PHASE_0_DIR / "schema_normalizer.py",
        session_id,
        extra_env={"HYPERDOCS_NORMALIZE_SESSION": f"session_{session_id[:8]}"},
        description="Schema Normalizer (fix agent JSON schemas)",
    )


def run_phase_1(session_id):
    """Phase 1: Thread extraction (requires Opus API key)."""
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("\n  WARNING: ANTHROPIC_API_KEY not set. Phase 1 requires Opus API calls.")
        print("  Set ANTHROPIC_API_KEY to run Phase 1.")
        return False

    return run_script(
        PHASE_1_DIR / "extract_threads.py",
        session_id,
        description="Phase 1: Thread Extraction (deterministic pattern matching)",
    )


def run_phase_2(session_id):
    """Phase 2: Build idea graph + synthesis (deterministic from Phase 1 output)."""
    session_dir = OUTPUT_DIR / f"session_{session_id[:8]}"

    # Check if Phase 1 outputs exist
    required_files = ["thread_extractions.json"]
    missing = [f for f in required_files if not (session_dir / f).exists()]
    if missing:
        print(f"\n  Phase 2 requires Phase 1 outputs. Missing: {', '.join(missing)}")
        print(f"  Run: python3 tools/run_pipeline.py {session_id} --phase 1")
        return False

    # The batch_p2_generator.py is designed for bulk processing.
    # For a single session, we run its build functions directly.
    sys.path.insert(0, str(REPO_ROOT / "phase_2_synthesis"))
    sys.path.insert(0, str(REPO_ROOT / "output"))  # fallback for legacy location
    try:
        from batch_p2_generator import build_idea_graph, build_synthesis, build_grounded_markers, read_json
    except ImportError:
        print("  ERROR: Cannot import batch_p2_generator.py")
        print("  Expected at phase_2_synthesis/batch_p2_generator.py or output/batch_p2_generator.py")
        return False

    sdir = str(session_dir)
    summary = read_json(os.path.join(sdir, "session_metadata.json"))
    threads = read_json(os.path.join(sdir, "thread_extractions.json"))
    geo = read_json(os.path.join(sdir, "geological_notes.json"))
    prims = read_json(os.path.join(sdir, "semantic_primitives.json"))
    explorer = read_json(os.path.join(sdir, "explorer_notes.json"))

    # K2: Validate Phase 1 output has expected keys before proceeding
    if threads and not (threads.get("threads") or threads.get("extractions")):
        print(f"\n  ERROR: thread_extractions.json exists but has no 'threads' or 'extractions' key.")
        print(f"  Schema may be invalid. Run: python3 tools/run_pipeline.py {session_id} --normalize")
        return False

    print(f"\n{'='*60}")
    print(f"  Running: Phase 2: Build Idea Graph + Synthesis")
    print(f"  Session: {session_id}")
    print(f"{'='*60}")

    # Build idea graph
    ig = build_idea_graph(session_id[:8], sdir, summary, threads, geo, prims, explorer)
    ig_path = os.path.join(sdir, "idea_graph.json")
    with open(ig_path, 'w') as f:
        json.dump(ig, f, indent=2)
    print(f"  idea_graph.json: {os.path.getsize(ig_path):,} bytes")

    # Build synthesis
    syn = build_synthesis(session_id[:8], sdir, summary, threads, geo, prims, explorer, ig)
    syn_path = os.path.join(sdir, "synthesis.json")
    with open(syn_path, 'w') as f:
        json.dump(syn, f, indent=2)
    print(f"  synthesis.json: {os.path.getsize(syn_path):,} bytes")

    # Build grounded markers
    gm = build_grounded_markers(session_id[:8], sdir, summary, threads, geo, prims, explorer, ig, syn)
    gm_path = os.path.join(sdir, "grounded_markers.json")
    with open(gm_path, 'w') as f:
        json.dump(gm, f, indent=2)
    print(f"  grounded_markers.json: {os.path.getsize(gm_path):,} bytes")

    return True


def run_phase_3(session_id):
    """Phase 3: Collect evidence, generate dossiers, and viewer."""
    session_dir = OUTPUT_DIR / f"session_{session_id[:8]}"

    # Check prerequisites
    required = ["idea_graph.json", "grounded_markers.json", "thread_extractions.json", "session_metadata.json"]
    missing = [f for f in required if not (session_dir / f).exists()]
    if missing:
        print(f"\n  Phase 3 requires Phase 2 outputs. Missing: {', '.join(missing)}")
        return False

    # Step 1: Collect per-file evidence (time-window correlated)
    ok = run_script(
        PHASE_3_DIR / "collect_file_evidence.py",
        session_id,
        description="Phase 3a: Collect Per-File Evidence",
        pass_session_arg=True,
    )

    # Step 2: Generate file dossiers
    if ok:
        ok = run_script(
            PHASE_3_DIR / "generate_dossiers.py",
            session_id,
            description="Phase 3b: Generate File Dossiers",
            pass_session_arg=True,
        )

    # Step 3: Generate HTML viewer
    if ok:
        ok = run_script(
            PHASE_3_DIR / "generate_viewer.py",
            session_id,
            description="Phase 3c: Generate HTML Viewer",
            pass_session_arg=True,
        )

    return ok


def main():
    parser = argparse.ArgumentParser(
        description="Run the Hyperdocs pipeline on a session.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python3 tools/run_pipeline.py 1c9e0a77              # Free phases (0 + 2)
  python3 tools/run_pipeline.py 1c9e0a77 --full       # All phases
  python3 tools/run_pipeline.py 1c9e0a77 --phase 1    # Just Phase 1
  python3 tools/run_pipeline.py 1c9e0a77 --normalize   # Schema normalizer
        """,
    )
    parser.add_argument("session_id", help="Session UUID (full or first 8 chars)")
    parser.add_argument("--full", action="store_true", help="Run all phases including Opus agents")
    parser.add_argument("--phase", type=int, choices=[0, 1, 2, 3], help="Run only this phase")
    parser.add_argument("--normalize", action="store_true", help="Run schema normalizer after processing")

    args = parser.parse_args()
    session_id = args.session_id

    print(f"Hyperdocs Pipeline Runner")
    print(f"Session: {session_id}")
    print(f"Output:  {OUTPUT_DIR / f'session_{session_id[:8]}'}")

    if args.phase is not None:
        # Run a single phase
        phase_runners = {0: run_phase_0, 1: run_phase_1, 2: run_phase_2, 3: run_phase_3}
        ok = phase_runners[args.phase](session_id)
    elif args.normalize:
        ok = run_schema_normalizer(session_id)
    elif args.full:
        # Full pipeline: 0 → 1 → normalize → 2 → 3
        ok = run_phase_0(session_id)
        if ok:
            ok = run_phase_1(session_id)
        if ok:
            ok = run_schema_normalizer(session_id)
        if ok:
            ok = run_phase_2(session_id)
        if ok:
            ok = run_phase_3(session_id)
    else:
        # Default: free phases only (0 → normalize → 2 if Phase 1 output exists)
        ok = run_phase_0(session_id)
        session_dir = OUTPUT_DIR / f"session_{session_id[:8]}"
        if ok:
            run_schema_normalizer(session_id)  # Always normalize after Phase 0
        if ok and (session_dir / "thread_extractions.json").exists():
            ok = run_phase_2(session_id)
        elif ok:
            print(f"\n  Phase 1 outputs not found. Run --phase 1 first for Phase 2.")
            print(f"  Phase 0 outputs written to: {session_dir}")

    if ok:
        print(f"\n{'='*60}")
        print(f"  Pipeline run succeeded.")
        session_dir = OUTPUT_DIR / f"session_{session_id[:8]}"
        if session_dir.exists():
            files = list(session_dir.glob("*.json"))
            print(f"  Output: {len(files)} JSON files in {session_dir}")
        print(f"{'='*60}")
    else:
        print(f"\n  Pipeline run had errors. Check output above.")
        sys.exit(1)


if __name__ == "__main__":
    main()
