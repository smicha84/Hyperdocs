#!/usr/bin/env python3
"""
End-to-end pipeline runner for Hyperdocs.

Runs a session through ALL phases in order. No fallbacks. Every step must succeed.

  Phase 0a: enrich_session.py → enriched_session.json
  Phase 0b: llm_pass_runner.py (4 passes) → llm_pass{1-4}_*.json
  Phase 0c: merge_llm_results.py → enriched_session_v2.json
  Phase 0d: opus_classifier.py → opus_classifications.json
  Phase 0e: build_opus_messages.py → opus_priority_messages.json
  Phase 0f: prepare_agent_data.py → 9 agent-readable files
  Phase 0g: schema_normalizer.py → normalize schemas
  Phase 1:  opus_phase1.py → thread_extractions, geological_notes, semantic_primitives, explorer_notes
  Phase 2:  backfill_phase2.py → idea_graph, synthesis, grounded_markers
  Phase 2b: file_genealogy.py → file_genealogy.json
  Phase 3a: collect_file_evidence.py → file_evidence/*.json
  Phase 3b: generate_dossiers.py → file_dossiers.json, claude_md_analysis.json
  Phase 3c: generate_viewer.py → pipeline_viewer.html
  Phase 4a: aggregate_dossiers.py → cross_session_file_index.json
  Phase 4b: insert_hyperdocs_v2.py → enhanced source files
  Phase 4c: hyperdoc_layers.py → layered hyperdoc JSON

Usage:
    python3 tools/run_pipeline.py SESSION_ID              # Full pipeline
    python3 tools/run_pipeline.py SESSION_ID --phase 0    # Just Phase 0
    python3 tools/run_pipeline.py SESSION_ID --force      # Re-run even if complete
    python3 tools/run_pipeline.py --batch 100             # 100 most recent sessions
"""

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PHASE_0_DIR = REPO_ROOT / "phase_0_prep"
PHASE_1_DIR = REPO_ROOT / "phase_1_extraction"
PHASE_2_DIR = REPO_ROOT / "phase_2_synthesis"
PHASE_3_DIR = REPO_ROOT / "phase_3_hyperdoc_writing"
PHASE_4A_DIR = REPO_ROOT / "phase_4a_aggregation"
PHASE_4B_DIR = REPO_ROOT / "phase_4_insertion"
OUTPUT_DIR = REPO_ROOT / "output"

sys.path.insert(0, str(REPO_ROOT))
from tools.log_config import get_logger, setup_pipeline_logging

logger = get_logger("tools.run_pipeline")


def run_script(script_path, session_id, extra_env=None, description="",
               pass_session_arg=False, extra_args=None, timeout=600):
    """Run a Python script. Returns True on success, False on failure."""
    env = {
        **os.environ,
        "HYPERDOCS_SESSION_ID": session_id,
        "HYPERDOCS_OUTPUT_DIR": str(OUTPUT_DIR),
        "PYTHONPATH": str(REPO_ROOT) + os.pathsep + os.environ.get("PYTHONPATH", ""),
    }
    if extra_env:
        env.update(extra_env)

    desc = description or script_path.name
    print(f"\n{'='*60}")
    print(f"  Running: {desc}")
    print(f"  Script:  {script_path}")
    print(f"  Session: {session_id}")
    print(f"{'='*60}")

    cmd = [sys.executable, str(script_path)]
    if pass_session_arg:
        cmd.extend(["--session", session_id])
    if extra_args:
        cmd.extend(extra_args)

    t0 = time.time()
    result = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=timeout)
    elapsed = time.time() - t0

    if result.stdout:
        lines = result.stdout.strip().split('\n')
        if len(lines) > 20:
            print(f"  ... ({len(lines) - 20} lines omitted)")
        for line in lines[-20:]:
            print(f"  {line}")

    if result.returncode != 0:
        print(f"\n  ERROR (exit code {result.returncode}) after {elapsed:.1f}s:")
        if result.stderr:
            for line in result.stderr.strip().split('\n')[-10:]:
                print(f"  {line}")
        logger.info(f"FAILED: {desc} — {elapsed:.1f}s")
        return False

    logger.info(f"OK: {desc} — {elapsed:.1f}s")
    print(f"  [{elapsed:.1f}s]")
    return True


def run_full_pipeline(session_id, force=False):
    """Run the complete pipeline. No fallbacks. Every step must succeed."""
    session_dir = OUTPUT_DIR / f"session_{session_id[:8]}"
    session_dir.mkdir(parents=True, exist_ok=True)

    session_dir_name = f"session_{session_id[:8]}"
    steps = [
        # Phase 0 — order matters: clean BEFORE Opus sees anything
        (PHASE_0_DIR / "enrich_session.py",
         "Phase 0a: Enrich Session", False, None, 300),
        (PHASE_0_DIR / "llm_pass_runner.py",
         "Phase 0b: LLM Pass Runner (4 passes)",
         False, ["--pass", "all", "--session", session_dir_name], 600),
        (PHASE_0_DIR / "merge_llm_results.py",
         "Phase 0c: Merge LLM Results",
         False, ["--session", session_dir_name], 120),
        (PHASE_0_DIR / "prepare_agent_data.py",
         "Phase 0d: Prepare + Clean Agent Data (7 rules)", False, None, 120),
        (REPO_ROOT / "tools" / "schema_normalizer.py",
         "Phase 0e: Schema Normalizer", False, None, 120),
        (PHASE_0_DIR / "opus_classifier.py",
         "Phase 0f: Opus Classification (reads cleaned data)", True, None, 300),
        (PHASE_0_DIR / "build_opus_messages.py",
         "Phase 0g: Build Opus Messages", True, None, 120),
        # Phase 1 — opus_phase1.py expects --session as directory name (session_XXXX)
        (PHASE_1_DIR / "opus_phase1.py",
         "Phase 1: Opus Extraction (threads, geology, primitives, explorer)",
         False, ["--session", session_dir_name], 600),
        # Phase 3
        (PHASE_3_DIR / "collect_file_evidence.py",
         "Phase 3a: Collect Per-File Evidence", True, None, 300),
        (PHASE_3_DIR / "generate_dossiers.py",
         "Phase 3b: Generate File Dossiers", True, None, 300),
        (PHASE_3_DIR / "generate_viewer.py",
         "Phase 3c: Generate HTML Viewer", True, None, 120),
    ]

    for script_path, desc, pass_arg, extra, tout in steps:
        ok = run_script(script_path, session_id, description=desc,
                        pass_session_arg=pass_arg, extra_args=extra, timeout=tout)
        if not ok:
            print(f"\n  PIPELINE STOPPED: {desc} failed.")
            return False

    # Phase 2: Run in-process (deterministic, no API calls)
    ok = run_phase_2_inprocess(session_id)
    if not ok:
        return False

    # Phase 2b: File genealogy
    ok = run_script(PHASE_2_DIR / "file_genealogy.py", session_id,
                    description="Phase 2b: File Genealogy", pass_session_arg=True)
    if not ok:
        return False

    return True


def run_phase_2_inprocess(session_id):
    """Phase 2: Build idea graph + synthesis (deterministic, in-process)."""
    session_dir = OUTPUT_DIR / f"session_{session_id[:8]}"

    sys.path.insert(0, str(REPO_ROOT / "phase_2_synthesis"))
    try:
        from backfill_phase2 import (build_idea_graph, build_synthesis,
                                     build_grounded_markers, read_json)
    except ImportError as e:
        print(f"  ERROR: Cannot import backfill_phase2: {e}")
        return False

    sdir = str(session_dir)
    summary = read_json(os.path.join(sdir, "session_metadata.json"))
    threads = read_json(os.path.join(sdir, "thread_extractions.json"))
    geo = read_json(os.path.join(sdir, "geological_notes.json"))
    prims = read_json(os.path.join(sdir, "semantic_primitives.json"))
    explorer = read_json(os.path.join(sdir, "explorer_notes.json"))

    if threads and "threads" not in threads and "extractions" not in threads:
        print(f"  ERROR: thread_extractions.json missing both 'threads' and 'extractions' keys.")
        return False

    print(f"\n{'='*60}")
    print(f"  Running: Phase 2: Synthesis (deterministic)")
    print(f"  Session: {session_id}")
    print(f"{'='*60}")

    ig = build_idea_graph(session_id[:8], sdir, summary, threads, geo, prims, explorer)
    with open(os.path.join(sdir, "idea_graph.json"), 'w') as f:
        json.dump(ig, f, indent=2)

    syn = build_synthesis(session_id[:8], sdir, summary, threads, geo, prims, explorer, ig)
    with open(os.path.join(sdir, "synthesis.json"), 'w') as f:
        json.dump(syn, f, indent=2)

    gm = build_grounded_markers(session_id[:8], sdir, summary, threads, geo, prims, explorer, ig, syn)
    with open(os.path.join(sdir, "grounded_markers.json"), 'w') as f:
        json.dump(gm, f, indent=2)

    print(f"  Phase 2 complete: idea_graph + synthesis + grounded_markers")
    return True


def archive_run(session_ids, run_timestamp):
    """Copy enhanced files to timestamped immutable archive directory."""
    import shutil
    archive_dir = Path.home() / "PERMANENT_HYPERDOCS" / "archive" / run_timestamp
    archive_dir.mkdir(parents=True, exist_ok=True)

    sessions_dir = archive_dir / "sessions"
    sessions_dir.mkdir(exist_ok=True)
    for sid in session_ids:
        src = OUTPUT_DIR / f"session_{sid[:8]}"
        if src.exists():
            dst = sessions_dir / f"session_{sid[:8]}"
            shutil.copytree(src, dst, dirs_exist_ok=True)

    enhanced_src = OUTPUT_DIR / "enhanced_files_archive"
    if enhanced_src.exists():
        shutil.copytree(enhanced_src, archive_dir / "enhanced_files", dirs_exist_ok=True)

    indexes_src = Path.home() / "PERMANENT_HYPERDOCS" / "indexes"
    if indexes_src.exists():
        shutil.copytree(indexes_src, archive_dir / "indexes", dirs_exist_ok=True)

    manifest = {
        "run_timestamp": run_timestamp,
        "processed_at": datetime.now(timezone.utc).isoformat(),
        "session_count": len(session_ids),
        "session_ids": session_ids,
        "first_session": session_ids[0] if session_ids else None,
        "last_session": session_ids[-1] if session_ids else None,
    }
    (archive_dir / "run_manifest.json").write_text(json.dumps(manifest, indent=2))

    for f in archive_dir.rglob("*"):
        if f.is_file():
            f.chmod(0o444)

    print(f"\n  Archive: {archive_dir}")
    print(f"  Sessions: {len(session_ids)}, files set read-only")
    return archive_dir


def generate_metadata_header(session_ids, run_timestamp):
    """Generate metadata comment block for enhanced source files."""
    earliest_msg = None
    latest_msg = None
    perm_dir = Path.home() / "PERMANENT_HYPERDOCS" / "sessions"

    for sid in session_ids:
        meta_path = perm_dir / f"session_{sid[:8]}" / "session_metadata.json"
        if not meta_path.exists():
            meta_path = OUTPUT_DIR / f"session_{sid[:8]}" / "session_metadata.json"
        if not meta_path.exists():
            continue
        try:
            meta = json.loads(meta_path.read_text())
            stats = meta.get("session_stats", {})
            start = stats.get("start_time") or stats.get("first_message_time")
            end = stats.get("end_time") or stats.get("last_message_time")
            if start and (earliest_msg is None or start < earliest_msg):
                earliest_msg = start
            if end and (latest_msg is None or end > latest_msg):
                latest_msg = end
        except (json.JSONDecodeError, IOError):
            continue

    return f"""\
# ═══════════════════════════════════════════════════════════════
# HYPERDOC — Auto-generated documentation from chat history analysis
#
# Sessions analyzed:    {len(session_ids)}
# First session ID:     {session_ids[0][:8] if session_ids else 'N/A'}
# Last session ID:      {session_ids[-1][:8] if session_ids else 'N/A'}
# Chat history from:    {earliest_msg or 'unknown'}
# Chat history to:      {latest_msg or 'unknown'}
# Processed at:         {run_timestamp}
# Pipeline version:     hyperdocs_3
#
# This file was enhanced by the Hyperdocs pipeline. The original
# source is unchanged — this is a copy with documentation inserted.
# ═══════════════════════════════════════════════════════════════
"""


def run_batch(n, force=False):
    """Run the pipeline on the N most recent sessions."""
    from config import SESSIONS_STORE_DIR

    run_timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")

    if not SESSIONS_STORE_DIR.exists():
        print(f"ERROR: {SESSIONS_STORE_DIR} does not exist")
        sys.exit(1)

    session_dirs = sorted(
        [d for d in SESSIONS_STORE_DIR.iterdir()
         if d.is_dir() and d.name.startswith("session_")],
        key=lambda d: d.stat().st_mtime, reverse=True,
    )[:n]

    session_ids = [d.name.replace("session_", "") for d in session_dirs]
    print(f"Batch: {len(session_ids)} sessions, timestamp: {run_timestamp}")

    completed, failed = [], []
    for i, sid in enumerate(session_ids):
        print(f"\n{'#'*60}")
        print(f"  SESSION {i+1}/{len(session_ids)}: {sid[:8]}")
        print(f"{'#'*60}")
        try:
            ok = run_full_pipeline(sid, force=force)
            (completed if ok else failed).append(sid)
        except Exception as e:
            print(f"  EXCEPTION: {e}")
            failed.append(sid)

    print(f"\n{'='*60}")
    print(f"  BATCH COMPLETE: {len(completed)}/{len(session_ids)} succeeded, {len(failed)} failed")
    print(f"{'='*60}")

    if completed:
        header = generate_metadata_header(completed, run_timestamp)
        (OUTPUT_DIR / "hyperdoc_metadata_header.txt").write_text(header)
        archive_run(completed, run_timestamp)

    if failed:
        print(f"\n  Failed sessions:")
        for sid in failed:
            print(f"    {sid[:8]}")


def main():
    parser = argparse.ArgumentParser(description="Hyperdocs pipeline. No fallbacks.")
    parser.add_argument("session_id", nargs="?", help="Session UUID")
    parser.add_argument("--phase", type=int, choices=[0, 1, 2, 3])
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--batch", type=int, metavar="N")
    args = parser.parse_args()

    if args.batch:
        run_batch(args.batch, force=args.force)
        return

    if not args.session_id:
        parser.print_help()
        sys.exit(1)

    session_id = args.session_id
    log_dir = OUTPUT_DIR / f"session_{session_id[:8]}"
    log_dir.mkdir(parents=True, exist_ok=True)
    setup_pipeline_logging(session_id=session_id, log_dir=log_dir)

    t0 = time.time()
    ok = run_full_pipeline(session_id, force=args.force)
    elapsed = time.time() - t0

    if ok:
        print(f"\n  Pipeline succeeded in {elapsed:.1f}s.")
    else:
        print(f"\n  Pipeline FAILED after {elapsed:.1f}s.")
        sys.exit(1)


if __name__ == "__main__":
    main()
