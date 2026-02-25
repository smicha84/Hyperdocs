#!/usr/bin/env python3
"""
Positioning Analyzer — Data Flow Graph + Dead-End Detection + Phase Positioning
================================================================================

Analyzes the hyperdocs_3 pipeline code to determine:

A. DATA FLOW GRAPH: Which scripts produce which JSON files, which scripts consume
   them, and which outputs are dead ends (nothing reads them).

B. EARLIEST-POSSIBLE-PHASE: For each script, determines the earliest phase it
   could run based on what phase its input files come from. Compares to where
   it actually lives in the directory structure.

Pure Python. No API calls. No LLM. Standalone.

Output: positioning_analysis.json (same directory as this script)
        + human-readable summary to stdout

Usage:
    python3 positioning_analyzer.py
"""

import ast
import json
import os
import re
import sys
from pathlib import Path
from collections import defaultdict
from datetime import datetime


# ── Configuration ─────────────────────────────────────────────────────────
REPO = Path(__file__).resolve().parent.parent  # hyperdocs_3 root
EXCLUDED_DIRS = {"v5_compat", "output", "__pycache__", ".git", "commands", "obsolete", "archive_originals"}
OUTPUT_FILE = REPO / "positioning_analysis.json"


# ── Phase Assignment ──────────────────────────────────────────────────────

def get_phase_for_path(filepath: Path) -> tuple:
    """Determine which phase a file belongs to based on its directory.

    Returns (phase_number, phase_name) where phase_number is:
      0 for phase_0_prep/
      1 for phase_1_extraction/
      2 for phase_2_synthesis/
      3 for phase_3_hyperdoc_writing/
      4 for phase_4_hyperdoc_writing/ or phase_4_insertion/
      -1 for root-level (Meta/Orchestration)
    """
    rel = filepath.relative_to(REPO)
    parts = rel.parts

    if len(parts) == 1:
        # Root-level file
        return (-1, "Meta")

    dirname = parts[0]

    phase_map = {
        "phase_0_prep": (0, "Phase 0"),
        "phase_1_extraction": (1, "Phase 1"),
        "phase_2_synthesis": (2, "Phase 2"),
        "phase_3_hyperdoc_writing": (3, "Phase 3"),
        "phase_4_hyperdoc_writing": (4, "Phase 4"),
        "phase_4_insertion": (4, "Phase 4"),
        "product": (-1, "Product"),
        "tools": (-1, "Tools"),
    }

    if dirname in phase_map:
        return phase_map[dirname]

    return (-1, "Meta")


# ── I/O Pattern Extraction ───────────────────────────────────────────────

# Known JSON filenames that the pipeline produces/consumes (session-level)
# These are the data files that flow between phases.
KNOWN_SESSION_FILES = {
    # Phase 0 outputs
    "enriched_session.json",
    "enriched_session_v2.json",
    "session_metadata.json",
    "tier2plus_messages.json",
    "tier4_priority_messages.json",
    "conversation_condensed.json",
    "user_messages_tier2plus.json",
    "emergency_contexts.json",
    "safe_tier4.json",
    "safe_condensed.json",
    "opus_classifications.json",
    "opus_vs_python_comparison.json",
    "opus_priority_messages.json",
    "opus_extended_messages.json",
    "safe_opus_priority.json",
    "llm_pass1_content_ref.json",
    "llm_pass2_behaviors.json",
    "llm_pass3_intent.json",
    "llm_pass4_importance.json",
    "code_similarity_index.json",
    # Phase 1 outputs
    "thread_extractions.json",
    "geological_notes.json",
    "semantic_primitives.json",
    "explorer_notes.json",
    # Phase 2 outputs
    "idea_graph.json",
    "synthesis.json",
    "grounded_markers.json",
    "file_genealogy.json",
    # Phase 3 outputs
    "file_dossiers.json",
    "claude_md_analysis.json",
    # Phase 4 outputs
    "cross_session_file_index.json",
    # Legacy outputs (Phase 5 dissolved)
    "ground_truth_claims.json",
    "ground_truth_results.json",
    "ground_truth_summary.json",
    "gap_checklist.json",
    # Dashboard / pipeline
    "pipeline_status.json",
    "discovery.json",
    # Real-time
    "realtime_buffer.jsonl",
}


def extract_io_from_source(filepath: Path) -> dict:
    """Extract input and output file references from a Python source file.

    Uses multiple strategies:
    1. AST-based: Find json.load/json.dump/open/Path.read_text/Path.write_text calls
    2. Regex-based: Find string literals that look like JSON filenames
    3. Variable assignment: Track variables assigned to paths with known filenames

    Returns:
        {"inputs": set of filenames, "outputs": set of filenames}
    """
    try:
        source = filepath.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {"inputs": set(), "outputs": set()}

    inputs = set()
    outputs = set()

    # ── Strategy 1: Regex for quoted JSON filenames ──
    # Match string literals containing .json or .jsonl filenames
    json_file_pattern = re.compile(
        r"""['"]([a-zA-Z0-9_.-]+\.(?:json|jsonl))['"]"""
    )
    all_json_refs = set(json_file_pattern.findall(source))

    # ── Strategy 2: Detect read vs write context ──
    # Lines with json.load, read_text, open(...) without 'w' → input
    # Lines with json.dump, write_text, open(..., 'w') → output

    lines = source.split("\n")
    for line_num, line in enumerate(lines):
        stripped = line.strip()

        # Skip comments
        if stripped.startswith("#"):
            continue

        # Find all JSON filenames on this line
        filenames_on_line = json_file_pattern.findall(line)
        if not filenames_on_line:
            continue

        # Determine if this line is a read or write context
        is_read = False
        is_write = False

        # Read patterns
        read_patterns = [
            r"json\.load\s*\(",
            r"json\.loads\s*\(",
            r"\.read_text\s*\(",
            r"open\s*\([^)]*\)\s*$",          # open() without 'w'
            r"open\s*\([^)]*['\"]r['\"]",      # open(..., 'r')
            r"open\s*\([^)]*\)\s+as\s+\w+:",   # open() as f: (default read)
            r"load_json\s*\(",
            r"load\s*\(",
            r"Path\s*\(",
            r"\.exists\s*\(\s*\)",
            r"INPUT",
            r"TIER4_FILE",
            r"USER_FILE",
            r"DOSSIERS_PATH",
            r"MARKERS_PATH",
        ]

        write_patterns = [
            r"json\.dump\s*\(",
            r"json\.dumps\s*\(",
            r"\.write_text\s*\(",
            r"open\s*\([^)]*['\"]w['\"]",   # open(..., 'w')
            r"OUTPUT",
            r"output_file",
            r"out_path",
            r"out_priority",
            r"out_extended",
            r"out_safe",
        ]

        for pat in read_patterns:
            if re.search(pat, line):
                is_read = True
                break

        for pat in write_patterns:
            if re.search(pat, line):
                is_write = True
                break

        for fname in filenames_on_line:
            if is_write:
                outputs.add(fname)
            elif is_read:
                inputs.add(fname)
            # If neither read nor write context detected, we'll use
            # the broader assignment/variable analysis below

    # ── Strategy 3: Track variable assignments to known filenames ──
    # e.g. INPUT_PATH = str(_OUT / "tier4_priority_messages.json")
    #      OUTPUT_PATH = str(_OUT / "thread_extractions.json")

    input_var_pattern = re.compile(
        r"""(?:INPUT|input|TIER4_FILE|USER_FILE|DOSSIERS_PATH|MARKERS_PATH|IDEA_GRAPH_PATH|CLAUDE_MD_PATH|enriched_path|cls_path)\s*=.*['"]([\w.-]+\.json)['"]"""
    )
    output_var_pattern = re.compile(
        r"""(?:OUTPUT|output|OUTPUT_PATH|OUTPUT_FILE|output_file|out_path|out_priority|out_extended|out_safe|safe_t4_file|safe_cond_file|comp_path)\s*=.*['"]([\w.-]+\.json)['"]"""
    )

    for match in input_var_pattern.finditer(source):
        inputs.add(match.group(1))
    for match in output_var_pattern.finditer(source):
        outputs.add(match.group(1))

    # ── Strategy 4: Direct path construction patterns ──
    # e.g. session_dir / "enriched_session.json"
    #      OUT_DIR / "session_metadata.json"
    #      BASE_DIR / "grounded_markers.json"

    path_div_pattern = re.compile(
        r"""(?:\/|/)\s*['"]([\w.-]+\.(?:json|jsonl))['"]"""
    )
    for match in path_div_pattern.finditer(source):
        fname = match.group(1)
        # These are referenced but we need context to know if read or write
        # Check if this filename already classified
        if fname not in inputs and fname not in outputs:
            # Check surrounding context (within 8 lines forward, 3 lines back)
            pos = match.start()
            # Count newlines to find line number
            line_idx = source[:pos].count("\n")
            context_start = max(0, line_idx - 3)
            context_end = min(len(lines), line_idx + 8)
            context = "\n".join(lines[context_start:context_end])

            if re.search(r"json\.dump|write_text|open\([^)]*['\"]w|\.write\(", context):
                outputs.add(fname)
            elif re.search(r"json\.load|read_text|load_json|load\(|\.read\(|\.exists\(\)", context):
                inputs.add(fname)
            else:
                # Heuristic: check the variable name on the assignment line
                assign_line = lines[line_idx] if line_idx < len(lines) else ""
                if re.search(r"\b(?:out|OUTPUT|output|result)", assign_line, re.IGNORECASE):
                    outputs.add(fname)
                else:
                    # Default: path construction to a known file is usually a read
                    inputs.add(fname)

    # ── Strategy 5: Specific codebase patterns ──
    # The generate_dossiers.py and write_hyperdocs.py scripts use load_json("filename")
    load_json_pattern = re.compile(
        r"""load_json\s*\(\s*['"]([\w.-]+\.json)['"]"""
    )
    for match in load_json_pattern.finditer(source):
        inputs.add(match.group(1))

    # load_json(session_dir, "filename") pattern (claim_extractor, gap_reporter)
    load_json_2arg_pattern = re.compile(
        r"""load_json\s*\(\s*\w+\s*,\s*['"]([\w.-]+\.json)['"]"""
    )
    for match in load_json_2arg_pattern.finditer(source):
        inputs.add(match.group(1))

    # save_json("filename", ...) pattern
    save_json_pattern = re.compile(
        r"""save_json\s*\(\s*['"]([\w.-]+\.json)['"]"""
    )
    for match in save_json_pattern.finditer(source):
        outputs.add(match.group(1))

    # ── Strategy 6: Check for load("filename") pattern (generate_viewer.py) ──
    bare_load_pattern = re.compile(
        r"""\bload\s*\(\s*['"]([\w.-]+\.json)['"]"""
    )
    for match in bare_load_pattern.finditer(source):
        inputs.add(match.group(1))

    # ── Strategy 7: P1_FILES, P2_FILES lists (batch_orchestrator.py) ──
    list_file_pattern = re.compile(
        r"""['"]([\w.-]+\.json)['"]"""
    )
    # Check for list definitions that name pipeline files
    for match in re.finditer(r"P[12]_FILES\s*=\s*\[([^\]]+)\]", source):
        list_content = match.group(1)
        for fname_match in list_file_pattern.finditer(list_content):
            inputs.add(fname_match.group(1))

    # PASS_OUTPUT_FILES dict
    for match in re.finditer(r"PASS_OUTPUT_FILES\s*=\s*\{([^}]+)\}", source, re.DOTALL):
        dict_content = match.group(1)
        for fname_match in list_file_pattern.finditer(dict_content):
            # These are output files that the orchestrator checks for existence
            inputs.add(fname_match.group(1))

    # Filter to only known session files (remove config files, package.json, etc.)
    inputs = {f for f in inputs if f in KNOWN_SESSION_FILES}
    outputs = {f for f in outputs if f in KNOWN_SESSION_FILES}

    return {"inputs": inputs, "outputs": outputs}


# ── Known phase for each output file ─────────────────────────────────────

# Which phase produces each output file?
# This is used to determine the "earliest possible phase" for a consumer.

OUTPUT_PHASE_MAP = {
    # Phase 0 outputs
    "enriched_session.json": 0,
    "enriched_session_v2.json": 0,
    "session_metadata.json": 0,
    "tier2plus_messages.json": 0,
    "tier4_priority_messages.json": 0,
    "conversation_condensed.json": 0,
    "user_messages_tier2plus.json": 0,
    "emergency_contexts.json": 0,
    "safe_tier4.json": 0,
    "safe_condensed.json": 0,
    "opus_classifications.json": 0,
    "opus_vs_python_comparison.json": 0,
    "opus_priority_messages.json": 0,
    "opus_extended_messages.json": 0,
    "safe_opus_priority.json": 0,
    "llm_pass1_content_ref.json": 0,
    "llm_pass2_behaviors.json": 0,
    "llm_pass3_intent.json": 0,
    "llm_pass4_importance.json": 0,
    # Phase 1 outputs
    "thread_extractions.json": 1,
    "geological_notes.json": 1,
    "semantic_primitives.json": 1,
    "explorer_notes.json": 1,
    # Phase 2 outputs
    "idea_graph.json": 2,
    "synthesis.json": 2,
    "grounded_markers.json": 2,
    "file_genealogy.json": 2,
    "code_similarity_index.json": 0,
    # Phase 3 outputs
    "file_dossiers.json": 3,
    "claude_md_analysis.json": 3,
    # Phase 4 outputs
    "cross_session_file_index.json": 4,
    # Legacy outputs (Phase 5 dissolved)
    "ground_truth_claims.json": -1,
    "ground_truth_results.json": -1,
    "ground_truth_summary.json": -1,
    # Meta outputs (not phase-bound)
    "gap_checklist.json": -1,
    "pipeline_status.json": -1,
    "discovery.json": -1,
    "realtime_buffer.jsonl": -1,
}


# ── Main Analysis ─────────────────────────────────────────────────────────

def discover_python_files() -> list:
    """Find all .py files in hyperdocs_3, excluding output and non-source dirs."""
    result = []
    for root, dirs, files in os.walk(REPO):
        # Skip excluded directories
        dirs[:] = [d for d in dirs if d not in EXCLUDED_DIRS]

        for fname in sorted(files):
            if fname.endswith(".py") and fname != "positioning_analyzer.py":
                filepath = Path(root) / fname
                result.append(filepath)
    return result


def build_relative_name(filepath: Path) -> str:
    """Build a short relative name for display."""
    rel = filepath.relative_to(REPO)
    return str(rel)


def analyze():
    """Run the full positioning analysis."""

    print("=" * 70)
    print("POSITIONING ANALYZER — Data Flow Graph + Phase Positioning")
    print("=" * 70)
    print(f"Repository: {REPO}")
    print()

    # ── Step 1: Discover all Python files ──
    py_files = discover_python_files()
    print(f"Found {len(py_files)} Python files (excluding v5_compat/, output/)")
    print()

    # ── Step 2: Extract I/O patterns from each file ──
    scripts = {}
    for filepath in py_files:
        rel_name = build_relative_name(filepath)
        phase_num, phase_name = get_phase_for_path(filepath)
        io = extract_io_from_source(filepath)

        scripts[rel_name] = {
            "path": str(filepath),
            "current_phase": phase_num,
            "current_phase_name": phase_name,
            "inputs": sorted(io["inputs"]),
            "outputs": sorted(io["outputs"]),
        }

    # ── Step 3: Build data flow graph ──
    producers = {}   # output_file -> script that writes it
    consumers = defaultdict(list)  # output_file -> [scripts that read it]

    for script_name, info in scripts.items():
        for out_file in info["outputs"]:
            # If multiple scripts produce the same file, record the last one
            # (in practice, each file should have one primary producer)
            producers[out_file] = script_name
        for in_file in info["inputs"]:
            consumers[in_file].append(script_name)

    # Find dead ends: outputs that nothing reads
    all_outputs = set(producers.keys())
    all_inputs = set()
    for info in scripts.values():
        all_inputs.update(info["inputs"])

    dead_ends = sorted(all_outputs - all_inputs)

    # Build disconnected chains
    disconnected = []
    for out_file in sorted(all_outputs):
        if out_file not in all_inputs:
            disconnected.append({
                "from": producers[out_file],
                "output": out_file,
                "reason": "no consumer found in pipeline code"
            })

    # ── Step 4: Earliest-possible-phase analysis ──
    positioning = {}
    mispositioned = []

    for script_name, info in scripts.items():
        input_phases = []
        for in_file in info["inputs"]:
            if in_file in OUTPUT_PHASE_MAP:
                phase = OUTPUT_PHASE_MAP[in_file]
                if phase >= 0:
                    input_phases.append(phase)

        if input_phases:
            # The earliest phase this script can run is AFTER the latest input phase
            latest_input_phase = max(input_phases)
            earliest_possible = latest_input_phase + 1
        else:
            # No pipeline inputs found -> could be Phase 0 or Meta
            earliest_possible = 0

        current = info["current_phase"]
        could_run_earlier = current > earliest_possible and current >= 0

        positioning[script_name] = {
            "current_phase": current,
            "current_phase_name": info["current_phase_name"],
            "earliest_possible_phase": earliest_possible,
            "inputs_from_phases": sorted(set(input_phases)),
            "could_run_earlier": could_run_earlier,
            "inputs": info["inputs"],
            "outputs": info["outputs"],
        }

        if could_run_earlier:
            mispositioned.append({
                "script": script_name,
                "current": current,
                "earliest": earliest_possible,
                "reason": (
                    f"Lives in Phase {current} but its latest input comes from "
                    f"Phase {max(input_phases) if input_phases else 0}, "
                    f"so it could run as early as Phase {earliest_possible}"
                )
            })

    # ── Step 5: Build output JSON ──
    result = {
        "generated_at": datetime.now().isoformat(),
        "generator": "positioning_analyzer.py",
        "total_scripts": len(scripts),
        "data_flow": {
            "producers": {k: v for k, v in sorted(producers.items())},
            "consumers": {k: sorted(set(v)) for k, v in sorted(consumers.items())},
            "dead_ends": dead_ends,
            "disconnected_chains": disconnected,
        },
        "positioning": {
            "scripts": {k: v for k, v in sorted(positioning.items())},
            "mispositioned": mispositioned,
        }
    }

    # ── Step 6: Write output ──
    with open(OUTPUT_FILE, "w") as f:
        json.dump(result, f, indent=2)

    print(f"Output written: {OUTPUT_FILE}")
    print(f"  File size: {OUTPUT_FILE.stat().st_size:,} bytes")
    print()

    # ── Step 7: Print human-readable summary ──
    print("=" * 70)
    print("DATA FLOW SUMMARY")
    print("=" * 70)

    print(f"\nProducers ({len(producers)} output files tracked):")
    for out_file, script in sorted(producers.items()):
        consumer_count = len(consumers.get(out_file, []))
        status = "  DEAD END" if out_file in dead_ends else f"  -> {consumer_count} consumer(s)"
        print(f"  {script}")
        print(f"    writes: {out_file}{status}")

    print(f"\n{'=' * 70}")
    print(f"DEAD ENDS ({len(dead_ends)} output files with no consumers)")
    print("=" * 70)
    if dead_ends:
        for de in dead_ends:
            producer = producers.get(de, "unknown")
            print(f"  {de}")
            print(f"    produced by: {producer}")
    else:
        print("  None found.")

    print(f"\n{'=' * 70}")
    print(f"PHASE POSITIONING ({len(mispositioned)} potentially mispositioned scripts)")
    print("=" * 70)
    if mispositioned:
        for mp in mispositioned:
            print(f"  {mp['script']}")
            print(f"    Current: Phase {mp['current']}  |  Earliest possible: Phase {mp['earliest']}")
            print(f"    Reason: {mp['reason']}")
            print()
    else:
        print("  All scripts are in their earliest possible phase (or Meta).")

    print(f"\n{'=' * 70}")
    print("PER-SCRIPT I/O MAP")
    print("=" * 70)

    # Group by phase
    by_phase = defaultdict(list)
    for script_name, info in sorted(positioning.items()):
        by_phase[info["current_phase"]].append((script_name, info))

    phase_names = {
        -1: "Meta/Orchestration",
        0: "Phase 0 (Prep)",
        1: "Phase 1 (Extraction)",
        2: "Phase 2 (Synthesis)",
        3: "Phase 3 (Hyperdoc Writing)",
        4: "Phase 4 (Insertion/Aggregation)",
    }

    for phase_num in sorted(by_phase.keys()):
        phase_label = phase_names.get(phase_num, f"Phase {phase_num}")
        scripts_in_phase = by_phase[phase_num]
        print(f"\n--- {phase_label} ({len(scripts_in_phase)} scripts) ---")
        for script_name, info in scripts_in_phase:
            flag = " [MISPOSITIONED]" if info["could_run_earlier"] else ""
            print(f"\n  {script_name}{flag}")
            if info["inputs"]:
                for inp in info["inputs"]:
                    src_phase = OUTPUT_PHASE_MAP.get(inp, "?")
                    print(f"    <- {inp} (from Phase {src_phase})")
            else:
                print(f"    <- (no pipeline JSON inputs detected)")
            if info["outputs"]:
                for out in info["outputs"]:
                    is_dead = " [DEAD END]" if out in dead_ends else ""
                    print(f"    -> {out}{is_dead}")
            else:
                print(f"    -> (no pipeline JSON outputs detected)")

    print(f"\n{'=' * 70}")
    print("ANALYSIS STATS")
    print("=" * 70)
    print(f"  Total scripts analyzed: {len(scripts)}")
    print(f"  Total output files tracked: {len(producers)}")
    print(f"  Dead ends: {len(dead_ends)}")
    print(f"  Mispositioned scripts: {len(mispositioned)}")
    print(f"  Output: {OUTPUT_FILE}")


if __name__ == "__main__":
    analyze()
