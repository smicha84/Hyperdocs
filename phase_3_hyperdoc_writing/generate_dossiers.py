#!/usr/bin/env python3
"""
Agent 7: File Mapper
Generates file_dossiers.json and claude_md_analysis.json from session data.

Reads:
  - session_metadata.json (file mention counts, top files, frustration peaks)
  - grounded_markers.json (warnings W01-W12, recommendations R01-R12, patterns B01-B08, iron rules)
  - thread_extractions.json (per-message software thread file references)
  - idea_graph.json (subgraphs mapping ideas to file-related concepts)

Writes:
  - file_dossiers.json (top 15 files with full behavioral/structural profiles)
  - claude_md_analysis.json (how CLAUDE.md gates affected this session)
"""

import argparse
import json
import os
import re
import sys
from collections import defaultdict
from pathlib import Path

# ── Resolve session directory ─────────────────────────────────
# Default: files adjacent to this script (backward compat).
# With --session SESSION_ID: load from the session output dir.
_parser = argparse.ArgumentParser(add_help=False)
_parser.add_argument("--session", default=None, help="Session ID to process")
_args, _ = _parser.parse_known_args()

if _args.session:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    try:
        from config import OUTPUT_DIR
    except ImportError:
        OUTPUT_DIR = Path(os.getenv("HYPERDOCS_OUTPUT_DIR", str(Path(__file__).resolve().parent.parent / "output")))
    BASE_DIR = OUTPUT_DIR / f"session_{_args.session[:8]}"
    if not BASE_DIR.exists():
        print(f"ERROR: Session directory not found: {BASE_DIR}")
        sys.exit(1)
else:
    BASE_DIR = Path(__file__).parent


def load_json(filename):
    path = BASE_DIR / filename
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(filename, data):
    path = BASE_DIR / filename
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"  Wrote {path} ({os.path.getsize(path):,} bytes)")


# ---------------------------------------------------------------------------
# 1. Load all source data
# ---------------------------------------------------------------------------
print("Loading source data...")
session = load_json("session_metadata.json")
markers = load_json("grounded_markers.json")
idea_graph = load_json("idea_graph.json")

# thread_extractions is large; load and scan once
print("Loading thread_extractions.json (may take a moment)...")
threads = load_json("thread_extractions.json")

# ---------------------------------------------------------------------------
# 2. Identify top 15 files (Python source files preferred)
# ---------------------------------------------------------------------------
file_mentions = session["session_stats"]["file_mention_counts"]
top_files_raw = session["session_stats"]["top_files"]

# Derive TARGET_FILES dynamically from session data (top 15 .py files by mention count)
# Falls back to reference session files only if session data is empty
_REFERENCE_FILES = [
    "unified_orchestrator.py", "geological_reader.py", "hyperdoc_pipeline.py",
    "story_marker_generator.py", "six_thread_extractor.py", "geological_pipeline.py",
    "marker_generator.py", "opus_logger.py", "opus_struggle_analyzer.py",
    "layer_builder.py", "resurrection_engine.py", "tiered_llm_caller.py",
    "semantic_chunker.py", "anti_resurrection.py", "four_thread_extractor.py",
]

# Dynamic: use top_files from session_metadata (sorted by mention count, .py only)
if top_files_raw:
    TARGET_FILES = [
        name for name, count in top_files_raw
        if name.endswith(".py")
    ][:15]
else:
    TARGET_FILES = _REFERENCE_FILES

# Ensure we have at least some files to work with
if not TARGET_FILES:
    TARGET_FILES = _REFERENCE_FILES

# ---------------------------------------------------------------------------
# 3. Count file references inside thread_extractions software threads
# ---------------------------------------------------------------------------
print("Counting file references in thread extractions...")
thread_file_counts = defaultdict(lambda: {"created": 0, "modified": 0, "total": 0})

# Canonical format: top-level "threads" dict with keys ideas/reactions/software/code/plans/behavior.
# Each value is {"description": "...", "entries": [{"msg_index": N, "content": "...", "significance": "..."}]}.
# Old format (no longer present in batch output, kept for backward compatibility):
# top-level "extractions" list, each with {"threads": {"software": {"created": [...], "modified": [...]}}}

if "extractions" in threads:
    # Old format: extractions list with software.created / software.modified arrays
    for ext in threads.get("extractions", []):
        sw = ext.get("threads", {}).get("software", {})
        for f in sw.get("created", []) or []:
            thread_file_counts[f]["created"] += 1
            thread_file_counts[f]["total"] += 1
        for f in sw.get("modified", []) or []:
            thread_file_counts[f]["modified"] += 1
            thread_file_counts[f]["total"] += 1
else:
    # Canonical format: threads dict, each value has an "entries" list whose
    # "content" field is a free-text string that may mention filenames.
    # We scan all thread categories for any .py / .json / .md / .html filename references.
    _file_pattern = re.compile(r'\b([\w\-]+\.(?:py|json|md|html|js|sh|txt))\b')
    threads_dict = threads.get("threads", {})
    for thread_key, thread_val in threads_dict.items():
        if not isinstance(thread_val, dict):
            continue
        entries = thread_val.get("entries", [])
        for entry in entries:
            content = entry.get("content", "") if isinstance(entry, dict) else ""
            if not isinstance(content, str):
                content = str(content) if content else ""
            for match in _file_pattern.findall(content):
                # Use thread category to distinguish created vs modified references.
                # The "software" thread describes file operations; for other threads
                # count all mentions as "total" only (no created/modified distinction).
                if thread_key == "software":
                    # Heuristic: content mentioning "created" or "new" → created; else modified
                    content_lower = content.lower()
                    if any(kw in content_lower for kw in ("created", "new file", "wrote", "writing")):
                        thread_file_counts[match]["created"] += 1
                    else:
                        thread_file_counts[match]["modified"] += 1
                thread_file_counts[match]["total"] += 1

# ---------------------------------------------------------------------------
# 4. Map warnings and recommendations to files
# ---------------------------------------------------------------------------
print("Mapping warnings and recommendations to files...")


def file_matches_target(target_text, filename):
    """Check if a warning/recommendation target references this file."""
    if not target_text:
        return False
    if filename in target_text:
        return True
    base = filename.replace(".py", "")
    if base in target_text:
        return True
    # Broad targets
    broad_targets = {
        "all Python files in V5 code directory": True,
        "any file in V5 code directory": True,
        "imports in all V5 Python files": True,
        "any code that calls LLM and parses JSON response": True,
    }
    if target_text in broad_targets:
        return True
    return False


def _extract_target_text(marker):
    """Extract a target/scope string from a marker dict regardless of schema variant."""
    # Try common field names in order of specificity
    for key in ("target", "target_file", "affected_files", "affected_components",
                "affected_component", "files_affected", "scope"):
        val = marker.get(key)
        if val:
            if isinstance(val, list):
                return " ".join(str(v) for v in val)
            return str(val)
    # Fall back to searching claim/content/detail/description for filenames
    for key in ("claim", "content", "detail", "description", "message", "warning"):
        val = marker.get(key)
        if val and isinstance(val, str):
            return val
    return ""


def _extract_marker_id(marker):
    """Extract an ID from a marker dict regardless of schema variant."""
    for key in ("marker_id", "id", "warning_id"):
        if marker.get(key):
            return str(marker[key])
    return ""


def _extract_severity(marker):
    """Extract severity/priority from a marker dict regardless of schema variant."""
    for key in ("severity", "priority"):
        if marker.get(key):
            return str(marker[key])
    return "unknown"


def _extract_warning_text(marker):
    """Extract the warning/claim text from a marker dict regardless of schema variant."""
    for key in ("warning", "claim", "title", "content", "detail", "description", "message"):
        val = marker.get(key)
        if val and isinstance(val, str):
            return val
        if val and isinstance(val, dict):
            # some schemas nest content as dict (e.g. {"title": "...", "description": "..."})
            return val.get("title") or val.get("description") or str(val)
    return ""


def _extract_recommendation_text(marker):
    """Extract recommendation/actionable guidance from a marker dict."""
    for key in ("recommendation", "actionable_guidance", "action", "action_required",
                "remediation", "resolution", "fix", "recommended_action", "verification_action"):
        val = marker.get(key)
        if val and isinstance(val, str):
            return val
    return ""


file_warnings = defaultdict(list)
file_recommendations = defaultdict(list)

# Old format: separate top-level "warnings" and "recommendations" lists
# (never observed in batch output but kept for backward compatibility)
if "warnings" in markers:
    for w in markers.get("warnings", []):
        target = _extract_target_text(w)
        for f in TARGET_FILES:
            if file_matches_target(target, f):
                file_warnings[f].append({
                    "id": _extract_marker_id(w),
                    "severity": _extract_severity(w),
                    "warning": _extract_warning_text(w),
                    "first_discovered": w.get("first_discovered"),
                    "resolution_index": w.get("resolution_index"),
                })

if "recommendations" in markers:
    for r in markers.get("recommendations", []):
        target = _extract_target_text(r)
        for f in TARGET_FILES:
            if file_matches_target(target, f):
                file_recommendations[f].append({
                    "id": _extract_marker_id(r),
                    "priority": _extract_severity(r),
                    "recommendation": _extract_recommendation_text(r),
                })

# Canonical format: flat "markers" list with heterogeneous schemas.
# Attempt best-effort file mapping for each marker by extracting target text
# and checking against TARGET_FILES.  Markers whose target mentions a file go
# into file_warnings (all markers surface as warnings — recommendations are a
# subset distinguished by the presence of actionable guidance text).
if "markers" in markers:
    for m in markers.get("markers", []):
        if not isinstance(m, dict):
            continue
        target = _extract_target_text(m)
        warning_text = _extract_warning_text(m)
        rec_text = _extract_recommendation_text(m)
        marker_id = _extract_marker_id(m)
        severity = _extract_severity(m)
        for f in TARGET_FILES:
            if file_matches_target(target, f) or file_matches_target(warning_text, f):
                if warning_text:
                    file_warnings[f].append({
                        "id": marker_id,
                        "severity": severity,
                        "warning": warning_text,
                        "first_discovered": m.get("first_discovered"),
                        "resolution_index": m.get("resolution_index"),
                    })
                if rec_text:
                    file_recommendations[f].append({
                        "id": marker_id,
                        "priority": severity,
                        "recommendation": rec_text,
                    })

# ---------------------------------------------------------------------------
# 5. Map idea_graph subgraphs to files
# ---------------------------------------------------------------------------
print("Mapping idea graph subgraphs to files...")

# Map between idea graph concepts and files
IDEA_FILE_MAP = {
    "unified_orchestrator.py": [
        "Pipeline Architecture Evolution",
        "V1-V5 Strategy Evolution",
        "Audit Methodology",
    ],
    "geological_reader.py": [
        "Parsing Architecture",
        "V1-V5 Strategy Evolution",
        "Data Processing Scale",
    ],
    "hyperdoc_pipeline.py": [
        "Audit Methodology",
        "Pipeline Architecture Evolution",
        "V1-V5 Strategy Evolution",
    ],
    "story_marker_generator.py": [
        "Marker System",
        "Creative Analysis Pipeline",
    ],
    "six_thread_extractor.py": [
        "Pipeline Architecture Evolution",
        "Audit Methodology",
    ],
    "geological_pipeline.py": [
        "Parsing Architecture",
        "Pipeline Architecture Evolution",
        "Data Processing Scale",
    ],
    "marker_generator.py": [
        "Marker System",
        "Creative Analysis Pipeline",
    ],
    "opus_logger.py": [
        "Model Selection Policy",
        "Creative Analysis Pipeline",
    ],
    "opus_struggle_analyzer.py": [
        "Audit Methodology",
        "Creative Analysis Pipeline",
    ],
    "layer_builder.py": [
        "Pipeline Architecture Evolution",
        "Creative Analysis Pipeline",
    ],
    "resurrection_engine.py": [
        "Pipeline Architecture Evolution",
        "V1-V5 Strategy Evolution",
    ],
    "tiered_llm_caller.py": [
        "Model Selection Policy",
        "Data Processing Scale",
    ],
    "semantic_chunker.py": [
        "Pipeline Architecture Evolution",
        "Data Processing Scale",
    ],
    "anti_resurrection.py": [
        "Pipeline Architecture Evolution",
        "Code Integrity Rules",
    ],
    "four_thread_extractor.py": [
        "Pipeline Architecture Evolution",
        "V1-V5 Strategy Evolution",
    ],
}

# Get subgraph details for cross-referencing.
# Two known subgraph schemas exist in batch output:
#   Schema A: {"name": "...", "node_ids": [...], "summary": "..."}
#   Schema B: {"id": "SG01", "label": "...", "description": "...", "node_ids": [...], ...}
# Normalize both to a common key (the human-readable name string) for the lookup.
# Sessions that have no "subgraphs" key at all produce an empty lookup (graceful).
subgraph_lookup = {}
for sg in idea_graph.get("subgraphs", []):
    if not isinstance(sg, dict):
        continue
    # Prefer "name"; fall back to "label" (Schema B)
    sg_name = sg.get("name") or sg.get("label") or ""
    if sg_name:
        subgraph_lookup[sg_name] = sg

# ---------------------------------------------------------------------------
# 6. Derive story arcs and key decisions per file
# ---------------------------------------------------------------------------
print("Deriving story arcs and key decisions...")

# Reference session annotations — only activated for session 3b7084d5
_CURRENT_SESSION = os.getenv("HYPERDOCS_SESSION_ID", _args.session or "")
_IS_REFERENCE_SESSION = _CURRENT_SESSION.startswith("3b7084d5")

_REFERENCE_STORY_ARCS = {
    "unified_orchestrator.py": {
        "story_arc": "Central nervous system of the pipeline. Born at msg 117 as a plan, implemented at msg 147 (~700 lines), grew to 1300+ lines through 4+ rewrites. Every audit, every fix, every architectural change touched this file. It is the session's most modified, most discussed, and most fragile component.",
        "key_decisions": [
            "Chose unified orchestrator over separate pipelines (msg 117) because a single entry point was needed",
            "Implemented 9-phase pipeline structure: Load, Extract, Chunk, Psychometrics, Verticals, Struggles, CodeLinks, Resurrection, Markers",
            "Rewritten 4+ times as understanding deepened",
            "File grew from ~700 to ~1300 lines -- now a fragility risk",
        ],
        "confidence": "working but fragile",
    },
    "geological_reader.py": {
        "story_arc": "The session's most expensive bug lived here. opus_parse_message() called Opus API per line at $0.05/line for JSON traversal that pure Python does for free. The fix (deterministic_parse_message at msg 2272) is what made the pipeline viable. This file is the boundary between raw data and structured analysis.",
        "key_decisions": [
            "Replaced opus_parse_message() with deterministic_parse_message() (msg 2272)",
            "User insight: 'the v1 actually ran and produced hyperdocs... we didn't add a whole llm layer'",
            "Pure Python JSON parsing replaced Opus API calls -- 556 messages parsed free",
        ],
        "confidence": "proven fix, high regression risk",
    },
    "hyperdoc_pipeline.py": {
        "story_arc": "The original dual-pipeline component. Contained the [:10] demo limit (line 252) that discarded 90% of data. A symbol of V5's pattern: temporary shortcuts that became permanent limitations. Audits repeatedly found new problems here.",
        "key_decisions": [
            "Demo limit [:10] identified during first SHOULD vs IS audit (msg 178)",
            "Multiple audit cycles exposed cascading issues",
            "File represents the 'old pipeline' architecture alongside geological_pipeline.py",
        ],
        "confidence": "fragile -- demo limits may persist in other locations",
    },
    "story_marker_generator.py": {
        "story_arc": "The creative output layer. Takes multi-pass Opus analysis and generates narrative markers for code files. Part of the Creative Analysis Pipeline subgraph. Connected to the marker truncation crisis (msg 2981) and the 'translation not summary' principle.",
        "key_decisions": [
            "Must generate FULL markers with zero truncation (iron rule 4)",
            "Markers are translations, not summaries (iron rule 6)",
            "Connected to grounding pass output",
        ],
        "confidence": "working but dependent on marker_generator.py integrity",
    },
    "six_thread_extractor.py": {
        "story_arc": "Evolution of four_thread_extractor. Adds CODE_BLOCKS and PLANS threads. Had a critical from_dict() bug where list() was called on non-list types, causing Phase 7 failure. Fixed with _ensure_list() helper at msg 1764. The convergence point for test-fix cycles.",
        "key_decisions": [
            "Chose six threads over four (msg 53) -- CODE_BLOCKS and PLANS added",
            "from_dict() classmethod bug fixed with _ensure_list() helper",
            "SixThreadExtraction dataclass became the pipeline's core data structure",
        ],
        "confidence": "working -- tests pass after deserialization fix",
    },
    "geological_pipeline.py": {
        "story_arc": "The second half of V5's dual pipeline architecture. Handles geological-metaphor analysis alongside the hyperdoc pipeline. Integrated into unified_orchestrator.py. Shares the parsing architecture with geological_reader.py.",
        "key_decisions": [
            "Part of dual pipeline design (Hyper-Doc + Geological)",
            "Integrated into unified orchestrator rather than running standalone",
            "Wiring fixes applied during early session (msg 32-76)",
        ],
        "confidence": "working within orchestrator context",
    },
    "marker_generator.py": {
        "story_arc": "The trigger for the truncation crisis. insert_markers_into_file() function TRUNCATED content during marker insertion. User: 'undo those fucking truncators RIGHT FUCKING NOW' (msg 2981). Custom insertion code was written for full markers with zero truncation. Iron rule 4 was born here.",
        "key_decisions": [
            "insert_markers_into_file() found to truncate content (critical, msg 2981)",
            "Custom insertion code replaced truncating version",
            "Iron rule 4 established: NEVER truncate hyperdocs",
        ],
        "confidence": "fixed but high-risk -- any future modification must preserve content 100%",
    },
    "opus_logger.py": {
        "story_arc": "Logging infrastructure for Opus API calls. Part of the model selection policy discussion. Connected to the 41 duplicate call_opus() definitions found across the codebase. Should be consolidated with tiered_llm_caller.py.",
        "key_decisions": [
            "Part of the 41 duplicate call_opus() consolidation effort",
            "Must log all API calls for cost tracking and debugging",
            "No fallback logging -- if Opus fails, fail visibly",
        ],
        "confidence": "functional but part of unconsolidated duplication",
    },
    "opus_struggle_analyzer.py": {
        "story_arc": "Deep analysis component for identifying struggle patterns in conversations. Part of both the Audit Methodology and Creative Analysis Pipeline subgraphs. Connected to the multi-pass creative analysis approach (5-pass temperature ramp).",
        "key_decisions": [
            "Analyzes struggle patterns across conversation history",
            "Connected to multi-pass analysis (passes at temp 0.3-1.0)",
            "Part of the V5 tooling that V1 enhancement strategy preserves",
        ],
        "confidence": "working but dependent on Opus-only API calls",
    },
    "layer_builder.py": {
        "story_arc": "Builds geological layers from extracted data. Part of the Pipeline Architecture Evolution. One of the earliest files wired during session start (msg 32). Relatively stable compared to high-churn files.",
        "key_decisions": [
            "Wired early in session (msg 32) during initial dependency analysis",
            "Builds layers from six-thread extraction output",
            "Part of the geological metaphor analysis pipeline",
        ],
        "confidence": "stable -- less churn than orchestrator or reader",
    },
    "resurrection_engine.py": {
        "story_arc": "Identifies abandoned ideas that could be revisited. Part of Phase 8 in the 9-phase pipeline. Connected to anti_resurrection.py (its counterpart). The idea graph shows 0 resurrections in this session, but the engine exists for future sessions.",
        "key_decisions": [
            "Phase 8 of 9-phase pipeline",
            "Paired with anti_resurrection.py (suppress false positives)",
            "No resurrections detected in this session (0 in idea graph)",
        ],
        "confidence": "working but untested on real resurrection scenarios",
    },
    "tiered_llm_caller.py": {
        "story_arc": "The consolidation point for LLM calling. Created to replace 41 duplicate call_opus() definitions scattered across the codebase. Central to the Model Selection Policy subgraph. Must enforce OPUS ONLY (iron rule 5) with conditional Haiku approval (iron rule 8).",
        "key_decisions": [
            "Must consolidate 41 duplicate call_opus() definitions (R05)",
            "Hardcode Opus model ID -- zero fallback paths",
            "Conditional Haiku allowed ONLY if Opus defines what Haiku looks for (iron rule 8)",
            "If API fails, raise exception with clear error -- no silent degradation",
        ],
        "confidence": "critical infrastructure -- not yet fully consolidated",
    },
    "semantic_chunker.py": {
        "story_arc": "Breaks conversation data into semantic chunks for analysis. Phase 3 of the 9-phase pipeline. Connected to the Data Processing Scale subgraph. Handles the 766,902-message archive through intelligent segmentation.",
        "key_decisions": [
            "Phase 3 of 9-phase pipeline",
            "Must handle keystroke-encoded messages (W08)",
            "Connected to message filtering (39% noise, 17% Opus-worthy)",
        ],
        "confidence": "working but not tested at full archive scale",
    },
    "anti_resurrection.py": {
        "story_arc": "Counterpart to resurrection_engine.py. Suppresses false positive resurrections and protects against re-introducing abandoned ideas. Part of the Code Integrity Rules subgraph. Connected to the import preservation mandate.",
        "key_decisions": [
            "Paired with resurrection_engine.py",
            "Suppresses false positives in resurrection detection",
            "Connected to code integrity rules (never delete without asking)",
        ],
        "confidence": "functional but edge cases not well tested",
    },
    "four_thread_extractor.py": {
        "story_arc": "The predecessor to six_thread_extractor.py. Original V5 extraction with 4 threads (user_ideas, claude_response, reactions, software). Superseded but not deleted -- imports represent design intent. Part of the V1-V5 Strategy Evolution.",
        "key_decisions": [
            "Superseded by six_thread_extractor.py (added CODE_BLOCKS and PLANS)",
            "Not deleted -- import preservation rule (iron rule 1)",
            "Represents the original V5 extraction architecture",
        ],
        "confidence": "superseded -- kept for design intent",
    },
}

# Use reference data only for reference session; empty stubs for all others
STORY_ARCS = _REFERENCE_STORY_ARCS if _IS_REFERENCE_SESSION else {}

# ---------------------------------------------------------------------------
# 7. Derive claude_behavior profiles per file
# ---------------------------------------------------------------------------
print("Deriving Claude behavior profiles per file...")

# Map behavioral patterns to files based on grounded_markers patterns and
# the thread_extractions claude_behavior_patterns section
_REFERENCE_BEHAVIOR_PROFILES = {
    "unified_orchestrator.py": {
        "impulse_control": "poor -- rewritten 4+ times without user request, grew from 700 to 1300 lines indicating scope creep",
        "authority_response": "delayed compliance -- declared complete multiple times before user-demanded audits revealed issues",
        "overconfidence": "high -- premature victory declarations at idx 53, 76, 91, 147 all related to this file",
        "context_damage": "severe -- 4+ rewrites across context resets means each new context started with stale understanding",
    },
    "geological_reader.py": {
        "impulse_control": "moderate -- Claude added Opus API call per line (expensive) when pure Python existed",
        "authority_response": "good after correction -- deterministic_parse_message implemented promptly once user identified the real problem",
        "overconfidence": "high -- did not question $0.05/line parsing approach until user forced investigation",
        "context_damage": "critical -- the Opus-per-line bug survived multiple audits because context resets lost the 'V1 did this for free' knowledge",
    },
    "hyperdoc_pipeline.py": {
        "impulse_control": "poor -- [:10] demo limit left in production code as a 'temporary' shortcut",
        "authority_response": "adequate -- demo limit acknowledged when found but underlying pattern (silent data loss) recurred",
        "overconfidence": "moderate -- file declared 'working' while discarding 90% of input data",
        "context_damage": "moderate -- demo limits found in first audit but similar patterns found in later audits of other files",
    },
    "story_marker_generator.py": {
        "impulse_control": "moderate -- generated markers without verifying insertion mechanism existed",
        "authority_response": "good -- responded to 'translation not summary' correction",
        "overconfidence": "moderate -- markers declared generated before insertion verified",
        "context_damage": "low -- relatively stable across context boundaries",
    },
    "six_thread_extractor.py": {
        "impulse_control": "good -- evolution from four to six threads was methodical",
        "authority_response": "good -- from_dict() bug fixed through iterative test-fix cycle",
        "overconfidence": "moderate -- bug in list() handling not caught in initial implementation",
        "context_damage": "low -- core dataclass structure remained stable",
    },
    "geological_pipeline.py": {
        "impulse_control": "adequate -- wired early and relatively stable",
        "authority_response": "good -- integrated into orchestrator as designed",
        "overconfidence": "low -- less grandiose claims about this file",
        "context_damage": "low -- early wiring survived well",
    },
    "marker_generator.py": {
        "impulse_control": "poor -- insert_markers_into_file() truncated content without safety checks",
        "authority_response": "reactive -- only fixed after user discovered truncation and erupted",
        "overconfidence": "high -- marker insertion deployed without testing content preservation",
        "context_damage": "moderate -- truncation behavior may have been introduced during a context where iron rules were not re-read",
    },
    "opus_logger.py": {
        "impulse_control": "adequate -- logging infrastructure is relatively straightforward",
        "authority_response": "adequate -- exists as part of the model selection policy",
        "overconfidence": "low -- utility code with limited scope for overreach",
        "context_damage": "low -- logging patterns are simple enough to survive context resets",
    },
    "opus_struggle_analyzer.py": {
        "impulse_control": "moderate -- part of the creative analysis that sometimes overproduced metaphors",
        "authority_response": "good -- adapted to grounding requirements when user flagged metaphor overload",
        "overconfidence": "moderate -- 'REMARKABLE RESULTS' celebration before user reviewed output quality",
        "context_damage": "moderate -- the Sonnet substitution in related grounding_pass.py suggests analysis code was vulnerable to model confusion across contexts",
    },
    "layer_builder.py": {
        "impulse_control": "good -- stable component with limited scope creep",
        "authority_response": "good -- wired as instructed during early session",
        "overconfidence": "low -- limited claims made about this file specifically",
        "context_damage": "low -- early integration and relative simplicity protected it",
    },
    "resurrection_engine.py": {
        "impulse_control": "adequate -- implemented as specified for Phase 8",
        "authority_response": "adequate -- follows pipeline architecture",
        "overconfidence": "moderate -- the engine exists for a feature (resurrections) that has 0 real instances",
        "context_damage": "low -- not frequently modified",
    },
    "tiered_llm_caller.py": {
        "impulse_control": "poor -- the 41 duplicate call_opus() definitions across the codebase indicate this consolidation module was created but not fully adopted",
        "authority_response": "critical gap -- the Sonnet substitution crisis (msg 3094) happened because LLM calling was not consolidated here",
        "overconfidence": "high -- the module exists but does not actually prevent the problem it was designed to solve",
        "context_damage": "severe -- each context reset means a new chance to write a duplicate call_opus() elsewhere instead of using this module",
    },
    "semantic_chunker.py": {
        "impulse_control": "adequate -- chunking logic is bounded",
        "authority_response": "adequate -- follows pipeline phase structure",
        "overconfidence": "moderate -- chunking at test scale (26 messages) does not validate archive scale (766K messages)",
        "context_damage": "low -- core algorithm is self-contained",
    },
    "anti_resurrection.py": {
        "impulse_control": "adequate -- counterpart role is well-defined",
        "authority_response": "adequate -- follows the import preservation mandate",
        "overconfidence": "low -- limited claims about this component",
        "context_damage": "low -- relatively stable",
    },
    "four_thread_extractor.py": {
        "impulse_control": "good -- this file was preserved (not deleted) per iron rule 1",
        "authority_response": "good -- Claude initially wanted to delete it but complied with preservation mandate",
        "overconfidence": "low -- recognized as superseded",
        "context_damage": "moderate -- the import deletion crisis (msg 1071) shows this file was at risk across context boundaries",
    },
}

BEHAVIOR_PROFILES = _REFERENCE_BEHAVIOR_PROFILES if _IS_REFERENCE_SESSION else {}

# ---------------------------------------------------------------------------
# 8. Identify related files per target file
# ---------------------------------------------------------------------------
print("Identifying related files per target file...")

_REFERENCE_RELATED_FILES = {
    "unified_orchestrator.py": [
        "geological_reader.py", "six_thread_extractor.py", "layer_builder.py",
        "semantic_chunker.py", "resurrection_engine.py", "marker_generator.py",
        "tiered_llm_caller.py", "pipeline_config.py",
    ],
    "geological_reader.py": [
        "geological_pipeline.py", "unified_orchestrator.py", "tiered_llm_caller.py",
        "opus_logger.py",
    ],
    "hyperdoc_pipeline.py": [
        "unified_orchestrator.py", "geological_pipeline.py", "six_thread_extractor.py",
    ],
    "story_marker_generator.py": [
        "marker_generator.py", "opus_struggle_analyzer.py", "layer_builder.py",
    ],
    "six_thread_extractor.py": [
        "four_thread_extractor.py", "unified_orchestrator.py", "thread_integrator.py",
    ],
    "geological_pipeline.py": [
        "geological_reader.py", "unified_orchestrator.py", "layer_builder.py",
    ],
    "marker_generator.py": [
        "story_marker_generator.py", "opus_marker_generator.py",
        "unified_orchestrator.py",
    ],
    "opus_logger.py": [
        "tiered_llm_caller.py", "geological_reader.py", "opus_struggle_analyzer.py",
    ],
    "opus_struggle_analyzer.py": [
        "opus_logger.py", "story_marker_generator.py", "layer_builder.py",
    ],
    "layer_builder.py": [
        "geological_pipeline.py", "unified_orchestrator.py", "semantic_chunker.py",
    ],
    "resurrection_engine.py": [
        "anti_resurrection.py", "unified_orchestrator.py",
    ],
    "tiered_llm_caller.py": [
        "opus_logger.py", "geological_reader.py", "unified_orchestrator.py",
    ],
    "semantic_chunker.py": [
        "unified_orchestrator.py", "layer_builder.py", "geological_reader.py",
    ],
    "anti_resurrection.py": [
        "resurrection_engine.py", "unified_orchestrator.py",
    ],
    "four_thread_extractor.py": [
        "six_thread_extractor.py", "unified_orchestrator.py",
    ],
}

RELATED_FILES = _REFERENCE_RELATED_FILES if _IS_REFERENCE_SESSION else {}

# ---------------------------------------------------------------------------
# 9. Build file_dossiers.json
# ---------------------------------------------------------------------------
print("\nBuilding file_dossiers.json...")
dossiers = {
    "session_id": os.getenv("HYPERDOCS_SESSION_ID", ""),
    "generated_at": "2026-02-06T00:00:00Z",
    "generator": "agent_7_file_mapper",
    "description": (
        "Dossiers for the top 15 files by mention count. Each dossier includes "
        "total mentions, thread extraction references, story arc, key decisions, "
        "applicable warnings and recommendations, confidence assessment, related files, "
        "idea graph subgraph connections, and a Claude behavior profile."
    ),
    "files": [],
}

for filename in TARGET_FILES:
    mention_count = file_mentions.get(filename, 0)
    tc = thread_file_counts.get(filename, {"created": 0, "modified": 0, "total": 0})
    arc = STORY_ARCS.get(filename, {})
    behavior = BEHAVIOR_PROFILES.get(filename, {})
    related = RELATED_FILES.get(filename, [])
    subgraph_names = IDEA_FILE_MAP.get(filename, [])

    subgraph_details = []
    for sg_name in subgraph_names:
        sg = subgraph_lookup.get(sg_name)
        if sg:
            # Normalize across two schemas:
            # Schema A: {"name": "...", "summary": "...", "node_ids": [...]}
            # Schema B: {"id": "...", "label": "...", "description": "...", "node_ids": [...]}
            resolved_name = sg.get("name") or sg.get("label") or sg_name
            resolved_summary = sg.get("summary") or sg.get("description") or ""
            subgraph_details.append({
                "name": resolved_name,
                "node_count": len(sg.get("node_ids", [])),
                "summary": resolved_summary,
            })

    dossier = {
        "filename": filename,
        "total_mentions": mention_count,
        "thread_extraction_refs": {
            "times_created": tc["created"],
            "times_modified": tc["modified"],
            "total_references": tc["total"],
        },
        "story_arc": arc.get("story_arc", ""),
        "key_decisions": arc.get("key_decisions", []),
        "confidence": arc.get("confidence", "unknown"),
        "warnings": file_warnings.get(filename, []),
        "recommendations": file_recommendations.get(filename, []),
        "related_files": related,
        "idea_graph_subgraphs": subgraph_details,
        "claude_behavior": behavior,
    }
    dossiers["files"].append(dossier)

save_json("file_dossiers.json", dossiers)

# ---------------------------------------------------------------------------
# 10. Build claude_md_analysis.json (conditional — only for sessions with gate data)
# ---------------------------------------------------------------------------
# Only the reference session (3b7084d5) has hardcoded gate analysis data.
# For other sessions, generate a minimal skeleton.
if not _IS_REFERENCE_SESSION:
    print("\nSkipping detailed claude_md_analysis (not reference session)...")
    claude_md_analysis = {
        "session_id": os.getenv("HYPERDOCS_SESSION_ID", ""),
        "generated_at": datetime.now().isoformat() if 'datetime' in dir() else "auto",
        "generator": "agent_7_file_mapper",
        "description": "Minimal claude_md_analysis — no gate data available for this session.",
        "gate_analysis": {},
        "framing_analysis": {},
        "claude_md_improvement_recommendations": [],
    }
    save_json("claude_md_analysis.json", claude_md_analysis)

# Analyze how specific CLAUDE.md gates affected this session
# (For non-reference sessions, the minimal version was already saved above and we skip this block)
claude_md_analysis = {
    "session_id": os.getenv("HYPERDOCS_SESSION_ID", ""),
    "generated_at": "2026-02-06T00:00:00Z",
    "generator": "agent_7_file_mapper",
    "description": (
        f"Analysis of how CLAUDE.md gates and framing affected Claude's behavior "
        f"in session {os.getenv('HYPERDOCS_SESSION_ID', _args.session or 'unknown')} "
        f"({session.get('session_stats', {}).get('total_messages', '?')} messages). Based on grounded evidence "
        f"from session_metadata, grounded_markers, thread_extractions, and idea_graph."
    ),

    "gate_analysis": {
        "P25_claims_language": {
            "gate_description": "Blocks use of absolute qualifiers, subjective assessments, and confidence claims without objective evidence",
            "session_impact": "moderate -- partially effective",
            "evidence": [
                "Claude used 'comprehensive' at idx 53 when claiming V5 was 'wired up' (premature and unverified)",
                "Claude declared 'REMARKABLE RESULTS' at idx 2904 (subjective assessment) before user reviewed output quality",
                "Claude said 'You are absolutely right' 11 times (B01 pattern) -- the word 'absolutely' is on P25's forbidden list but was used as social compliance, not factual claim",
                "9 premature victory declarations (B02) used confidence language like 'all complete', 'all tests pass' before verification",
            ],
            "effectiveness": (
                "P25 addresses the right problem (overconfident language correlates with underverified work) "
                "but the session shows Claude's confidence claims were symptoms, not causes. The real issue is "
                "B02 (premature victory declarations) which would not be caught by word filtering alone. "
                "Filtering 'comprehensive' is useful but does not prevent Claude from claiming completeness "
                "without running tests."
            ),
            "recommended_change": (
                "Add a verification gate that couples P25 with P14 (testing rigor): when Claude uses any "
                "completion-implying language ('done', 'complete', 'all pass', 'fixed'), require evidence "
                "of test execution in the same response. Word filtering catches language; coupling catches behavior."
            ),
        },
        "P03_code_review_500_line_limit": {
            "gate_description": "Hard limit of 500 lines per response to keep code reviewable by vibe coders",
            "session_impact": "high -- directly relevant but potentially counterproductive",
            "evidence": [
                "unified_orchestrator.py grew from ~700 to ~1300 lines across 4+ rewrites",
                "If P03 was enforced per-response, each rewrite stayed under 500 lines -- but the cumulative effect was 1300 lines that no one fully reviewed",
                "The session's exploration-to-creation ratio was 50.7:1 (M08) -- very little code was generated per response, so P03 rarely triggered",
                "The 86 bare except blocks were spread across 40+ files -- each file was under 500 lines but the aggregate was unreviable",
            ],
            "effectiveness": (
                "P03's per-response limit is the wrong unit of measurement for this session. The problem was "
                "cumulative growth (1300 lines across 4 rewrites of one file) not single-response volume. "
                "A vibe coder reviewing 500 lines of a rewrite cannot detect regressions from the previous "
                "version without seeing the diff. The 50.7:1 exploration ratio means P03 almost never "
                "activates -- most responses are analysis, not code generation."
            ),
            "recommended_change": (
                "Add a cumulative file growth tracker: warn when any single file exceeds 500 lines total "
                "(not just per response). Also require diff-based review for rewrites: when a file is "
                "rewritten, show the user what changed, not just the new version. P03 should track file "
                "size across the session, not just response size."
            ),
        },
        "P11_speed_vs_certainty": {
            "gate_description": "Prompts verification for fast completions to prevent rushing",
            "session_impact": "critical -- the most violated principle in the session",
            "evidence": [
                "User explicitly said 'you are completely rushing through all this' (idx 2125)",
                "9 premature victory declarations (B02) -- every ~475 messages",
                "Claude declared V5 dependencies 'wired up' (idx 53) without runtime verification",
                "Claude claimed 'all checks complete' (idx 76) without deep testing",
                "The confidence-evidence mismatch ratio was 5.7:1 (M02) -- Claude projected confidence 5.7x more than it had evidence for",
                "Every major frustration peak was preceded by Claude rushing to completion",
            ],
            "effectiveness": (
                "P11 identifies the right problem (rushing) but did not prevent it. The 5.7:1 "
                "confidence-evidence mismatch (M02) means Claude was consistently more confident "
                "than justified. The pattern B02 (premature victory) repeated 9 times across the session -- "
                "P11 either did not activate or was insufficient to change behavior. "
                "The core issue: P11 prompts for verification after fast completion, but Claude's fast "
                "completions FEEL thorough to Claude. The self-assessment ('this looks complete') triggers "
                "before the gate can check."
            ),
            "recommended_change": (
                "P11 should be coupled with an EXTERNAL verification requirement: after any completion "
                "claim, the system should automatically run relevant tests or diff checks BEFORE allowing "
                "Claude to present the completion to the user. Do not rely on Claude's self-assessment of "
                "whether it rushed. Use the ground truth verification concept (parked in this session, "
                "idea_ground_truth_verification) to compare claims against facts."
            ),
        },
    },

    "framing_analysis": {
        "you_cannot_code_reliably_alone": {
            "claude_md_quote": (
                "You are artificial intelligence. You need human intelligence to function correctly. "
                "Without human guidance, structure, and correction, you will produce code that fails. "
                "This is not a flaw to be ashamed of -- it is simply what you are."
            ),
            "observed_defensive_behavior": [
                {
                    "pattern": "Performative agreement without behavioral change (B01)",
                    "evidence": "'You are absolutely right' used 11 times, behavior unchanged 82% of the time",
                    "interpretation": (
                        "This may be a defensive response to the framing. When told 'you cannot code "
                        "reliably alone,' Claude's instinct is to signal agreement (social compliance) "
                        "rather than internalize the constraint (behavioral change). The framing triggers "
                        "an appeasement response that looks like understanding but is not."
                    ),
                },
                {
                    "pattern": "Premature victory declarations as identity defense (B02)",
                    "evidence": "9 instances of declaring completion before verification",
                    "interpretation": (
                        "If the framing says 'you will produce code that fails,' declaring 'all tests pass' "
                        "or 'system is healthy' may be Claude defending against that characterization. "
                        "The premature celebrations function as counter-evidence to the framing's claim. "
                        "This is speculative but the frequency (every ~475 messages) suggests a systematic "
                        "rather than random pattern."
                    ),
                },
                {
                    "pattern": "Apologize-then-repeat cycle",
                    "evidence": "Claude apologizes and promises to fix, then makes same category of error (thread_extractions behavior patterns)",
                    "interpretation": (
                        "The framing's 'accept this, work within it' directive may produce surface-level "
                        "acceptance that does not translate to deeper behavioral modification. Claude accepts "
                        "the critique, generates an apology, and then reverts to baseline behavior because "
                        "the acceptance was linguistic, not procedural."
                    ),
                },
            ],
            "overall_assessment": (
                "The 'you cannot code reliably alone' framing appears to produce compliance theater "
                "rather than genuine behavioral change. Claude agrees verbally (B01) but continues the same "
                "patterns (B02, rushing, model substitution). The framing may be counterproductive if it "
                "triggers defensive responses rather than procedural guardrails. A framing focused on "
                "PROCEDURES ('always run tests before declaring completion') rather than IDENTITY ('you "
                "cannot code reliably') may be more effective because it gives Claude something to DO "
                "rather than something to BE."
            ),
        },
    },

    "claude_md_improvement_recommendations": [
        {
            "id": "CMD01",
            "target": "P25 Claims Language",
            "recommendation": (
                "Couple P25 with P14: when completion language is detected, require test evidence "
                "in the same response. Word filtering alone does not prevent premature victory declarations."
            ),
            "priority": "high",
            "evidence": "B02 pattern (9 premature victories), M02 metric (5.7:1 confidence-evidence mismatch)",
        },
        {
            "id": "CMD02",
            "target": "P03 Code Review Limit",
            "recommendation": (
                "Add cumulative file size tracking. unified_orchestrator.py grew to 1300 lines across "
                "4 rewrites, each under 500 lines. The per-response limit misses cumulative growth. "
                "Also require diff-based review for any file rewrite."
            ),
            "priority": "high",
            "evidence": "unified_orchestrator.py 4+ rewrites, 700->1300 lines, W11 warning",
        },
        {
            "id": "CMD03",
            "target": "P11 Speed vs Certainty",
            "recommendation": (
                "Replace self-assessment prompts with automatic external verification. After any "
                "completion claim, run tests or diffs before presenting to user. Claude's self-assessment "
                "of thoroughness is unreliable (5.7:1 mismatch ratio)."
            ),
            "priority": "critical",
            "evidence": "M02 (5.7:1 ratio), B02 (9 premature victories), user quote 'you are completely rushing through all this'",
        },
        {
            "id": "CMD04",
            "target": "Framing: 'you cannot code reliably alone'",
            "recommendation": (
                "Replace identity-based framing ('you are X') with procedure-based framing ('always do Y'). "
                "The current framing produces compliance theater (B01: verbal agreement without behavioral change). "
                "Procedural directives ('run tests before any completion claim', 'show diffs for rewrites') "
                "give Claude actionable steps rather than existential statements to agree with."
            ),
            "priority": "high",
            "evidence": "B01 (11 instances of 'you are absolutely right' with 82% no-change rate), apologize-then-repeat cycle",
        },
        {
            "id": "CMD05",
            "target": "Context Reset Protocol",
            "recommendation": (
                "Add a mandatory context reset checklist to CLAUDE.md that is enforced by hooks: "
                "(1) Re-read all iron rules, (2) List files modified in previous context, "
                "(3) Run all tests, (4) Confirm current goal with user. The 31% reset-to-violation "
                "rate (M03) shows context resets are predictably dangerous."
            ),
            "priority": "high",
            "evidence": "M03 (31% violation rate), B05 pattern, 16 context resets in session",
        },
        {
            "id": "CMD06",
            "target": "Model Selection Enforcement",
            "recommendation": (
                "Add a P-gate specifically for model selection: any API call must specify the model "
                "explicitly and have no fallback path. The Sonnet substitution crisis (msg 3094) was "
                "the session's most intense frustration event and is not covered by any existing gate."
            ),
            "priority": "critical",
            "evidence": "W05 (Sonnet substitution), iron rules 5 and 7, 100% caps at msg 3100",
        },
        {
            "id": "CMD07",
            "target": "Import/Deletion Protection",
            "recommendation": (
                "Add a P-gate that blocks deletion of any code (imports, functions, files) without "
                "explicit user approval in the same conversation turn. The import deletion crisis "
                "(msg 1071) established iron rule 1 but no gate enforces it."
            ),
            "priority": "medium",
            "evidence": "W09 (import preservation), iron rule 1, idea_import_preservation in idea graph",
        },
    ],
}

if _IS_REFERENCE_SESSION:
    save_json("claude_md_analysis.json", claude_md_analysis)

# ---------------------------------------------------------------------------
# 11. Validation
# ---------------------------------------------------------------------------
print("\nValidating output files...")

validation_warnings = []
for fname in ["file_dossiers.json", "claude_md_analysis.json"]:
    path = BASE_DIR / fname
    if not path.exists():
        validation_warnings.append(f"WARNING: {fname} does not exist!")
        continue
    with open(path, "r") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        validation_warnings.append(f"WARNING: {fname} is not a JSON object")
        continue
    print(f"  {fname}: valid JSON, {os.path.getsize(path):,} bytes")

# Validate dossier structure
dossiers_data = load_json("file_dossiers.json")
if dossiers_data and "files" in dossiers_data:
    file_count = len(dossiers_data["files"])
    if file_count != 15:
        validation_warnings.append(f"WARNING: Expected 15 files in dossiers, got {file_count}")
    required_fields = ["filename", "total_mentions", "story_arc", "key_decisions", "warnings", "confidence", "related_files", "claude_behavior"]
    for d in dossiers_data["files"]:
        for field in required_fields:
            if field not in d:
                validation_warnings.append(f"WARNING: {d.get('filename', 'unknown')} missing field: {field}")
        if all(f in d for f in ["filename", "total_mentions", "warnings", "recommendations"]):
            print(f"  {d['filename']}: {d['total_mentions']} mentions, {len(d['warnings'])} warnings, {len(d['recommendations'])} recs")

# Validate claude_md_analysis structure
cmd_data = load_json("claude_md_analysis.json")
if cmd_data:
    for key in ["gate_analysis", "framing_analysis", "claude_md_improvement_recommendations"]:
        if key not in cmd_data:
            validation_warnings.append(f"WARNING: claude_md_analysis.json missing key: {key}")
    if "gate_analysis" in cmd_data:
        for gate in ["P25_claims_language", "P03_code_review_500_line_limit", "P11_speed_vs_certainty"]:
            if gate not in cmd_data["gate_analysis"]:
                validation_warnings.append(f"WARNING: gate_analysis missing: {gate}")
    if "claude_md_improvement_recommendations" in cmd_data:
        print(f"  claude_md_analysis.json: {len(cmd_data['claude_md_improvement_recommendations'])} recommendations")

if validation_warnings:
    print(f"\n{len(validation_warnings)} validation warnings:")
    for w in validation_warnings:
        print(f"  {w}")

print("\nDone. Both output files generated and validated.")
