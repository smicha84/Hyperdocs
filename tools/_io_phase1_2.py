"""
I/O catalog for phase_1_extraction/ and phase_2_synthesis/ modules.

Fresh recount 2026-02-25. Every .py file (excluding __init__.py, __pycache__)
in both directories was read completely, line by line. No existing manifest
was referenced. Every open(), json.load(), json.dump(), write_text(),
read_text(), Path.glob(), Path.iterdir(), .exists() check, and path
construction was recorded from the source code.

Format per file:
    "reads":        list of file patterns or names this module reads
    "writes":       list of file patterns or names this module writes
    "imports_from": list of pipeline modules imported (from phase_X, from tools, from config)

Prefix conventions:
    {session_dir}/          per-session directory (SESSIONS_STORE_DIR or output/)
    {INDEXES_DIR}/          global indexes directory
    {CHAT_ARCHIVE_DIR}/     chat archive root
    ~/                      user home directory
"""

PHASE1_2_IO = {
    # =========================================================================
    # phase_1_extraction/
    # =========================================================================

    "phase_1_extraction/interactive_batch_runner.py": {
        # CLI tool that scans output/ for session progress.
        # Reads session_metadata.json (json.load at line 48-49).
        # Checks existence of P1 and P2 output files.
        # Iterates output/ directory (OUTPUT.iterdir() at line 36).
        # Writes nothing.
        "reads": [
            # Iterates output/ looking for session_* dirs (line 36)
            # Checks existence of enriched_session.json (line 39)
            "{session_dir}/enriched_session.json",
            # Checks existence of safe_tier4.json (line 41)
            "{session_dir}/safe_tier4.json",
            # Loads session_metadata.json with json.load (lines 48-49)
            "{session_dir}/session_metadata.json",
            # Checks existence of P1 output files (line 58)
            "{session_dir}/thread_extractions.json",
            "{session_dir}/geological_notes.json",
            "{session_dir}/semantic_primitives.json",
            "{session_dir}/explorer_notes.json",
            # Checks existence of P2 output files (line 59)
            "{session_dir}/idea_graph.json",
            "{session_dir}/synthesis.json",
            "{session_dir}/grounded_markers.json",
        ],
        "writes": [],
        "imports_from": [
            "tools.log_config",  # get_logger (line 22)
        ],
    },

    "phase_1_extraction/extract_threads.py": {
        # Deterministic thread extractor. Reads priority messages, writes
        # thread_extractions.json. Uses open()+json.load() for reads,
        # open()+json.dump() for writes.
        "reads": [
            # Prefers Opus-classified, falls back to Python tier-4
            # (lines 32-34: _OPUS_INPUT / _PYTHON_INPUT, chosen at import time)
            "{session_dir}/opus_priority_messages.json",
            "{session_dir}/tier4_priority_messages.json",
        ],
        "writes": [
            # json.dump at lines 747-748
            "{session_dir}/thread_extractions.json",
        ],
        "imports_from": [
            "config",           # get_session_output_dir (line 23)
            "tools.log_config", # get_logger (line 13)
        ],
    },

    "phase_1_extraction/tag_semantic_primitives.py": {
        # Deterministic semantic primitives tagger. Reads priority messages,
        # user messages, and enriched session. Writes semantic_primitives.json.
        "reads": [
            # Prefers Opus-classified, falls back to Python tier-4
            # (lines 39-41: _OPUS_PRIORITY / _PYTHON_TIER4)
            "{session_dir}/opus_priority_messages.json",
            "{session_dir}/tier4_priority_messages.json",
            # User messages supplementary context (line 42, loaded at line 551)
            "{session_dir}/user_messages_tier2plus.json",
            # Enriched session for high-intensity user messages (line 43, loaded at lines 569-571)
            "{session_dir}/enriched_session.json",
        ],
        "writes": [
            # json.dump at lines 633-634
            "{session_dir}/semantic_primitives.json",
        ],
        "imports_from": [
            "config",           # get_session_output_dir (line 32)
            "tools.log_config", # get_logger (line 19)
        ],
    },

    "phase_1_extraction/batch_p1_llm.py": {
        # Batch orchestrator for Phase 0 LLM passes. Discovers sessions,
        # manages checkpoints/cost logs, and spawns subprocesses for
        # llm_pass_runner.py and merge_llm_results.py. Does NOT read/write
        # session data files directly -- subprocess calls do that.
        "reads": [
            # Session discovery: iterdir checking enriched_session.json (lines 97-102)
            "{session_dir}/enriched_session.json",
            # Pass output existence checks (lines 108-109)
            "{session_dir}/llm_pass1_content_ref.json",
            "{session_dir}/llm_pass2_behaviors.json",
            "{session_dir}/llm_pass3_intent.json",
            "{session_dir}/llm_pass4_importance.json",
            # Merged file existence check (line 335)
            "{session_dir}/enriched_session_v2.json",
            # Checkpoint file (json.load at lines 117-118)
            "{INDEXES_DIR}/llm_pass_checkpoint.json",
            # Cost log file (json.load at lines 133-135, also line 341)
            "{INDEXES_DIR}/llm_pass_cost_log.json",
        ],
        "writes": [
            # Checkpoint file (json.dump at lines 125-126)
            "{INDEXES_DIR}/llm_pass_checkpoint.json",
            # Cost log file (json.dump at lines 143-144)
            "{INDEXES_DIR}/llm_pass_cost_log.json",
        ],
        "imports_from": [
            "config",           # SESSIONS_STORE_DIR, INDEXES_DIR (line 51)
            "tools.log_config", # get_logger (line 44)
        ],
    },

    "phase_1_extraction/opus_phase1.py": {
        # Runs 4 sequential Opus API calls per session (Thread Analyst,
        # Geological Reader, Primitives Tagger, Explorer). Reads 3 safe
        # input files per session, writes 4 output files per session,
        # plus a global progress file.
        "reads": [
            # Per-session input files via load_session_data (lines 470-477)
            "{session_dir}/safe_condensed.json",
            "{session_dir}/safe_tier4.json",
            "{session_dir}/session_metadata.json",
            # Session discovery: iterdir + .exists() check for safe_condensed.json (lines 824-828)
            # (same files as above, just used for directory scanning)
            # Commitments file read once at import time (lines 482-483, .read_text())
            "~/.claude/CLAUDE.md",
            # Chat archive sessions dir for duplicate detection (lines 121-125, iterdir for .jsonl files)
            "{CHAT_ARCHIVE_DIR}/sessions/*.jsonl",
        ],
        "writes": [
            # Per-session output files via process_session (lines 635-636, 668-669, 738-739, 763-764)
            "{session_dir}/thread_extractions.json",
            "{session_dir}/geological_notes.json",
            "{session_dir}/semantic_primitives.json",
            "{session_dir}/explorer_notes.json",
            # Global progress tracking (lines 803-804, 855-856, 876-877)
            "{INDEXES_DIR}/phase1_redo_progress.json",
        ],
        "imports_from": [
            "config",                    # SESSIONS_STORE_DIR, INDEXES_DIR, load_env, CHAT_ARCHIVE_DIR, INDEXES_DIR (lines 88-89, 98-99, 110-111)
            "tools.schema_normalizer",   # NORMALIZERS, normalize_file (line 104)
            "tools.log_config",          # get_logger (line 73)
        ],
    },

    # =========================================================================
    # phase_2_synthesis/
    # =========================================================================

    "phase_2_synthesis/file_genealogy.py": {
        # Detects file identity across renames/rewrites. Reads thread
        # extractions and idea graph, writes file_genealogy.json.
        "reads": [
            # Loaded via load_json -> tools.json_io.load_json (line 380)
            "{session_dir}/thread_extractions.json",
            # Loaded via load_json -> tools.json_io.load_json (line 381)
            "{session_dir}/idea_graph.json",
        ],
        "writes": [
            # json.dump at lines 429-430
            "{session_dir}/file_genealogy.json",
        ],
        "imports_from": [
            "config",           # get_session_output_dir, SESSION_ID (line 35)
            "tools.json_io",    # load_json (line 32)
            "tools.log_config", # get_logger (line 20)
        ],
    },

    "phase_2_synthesis/backfill_phase2.py": {
        # Batch Phase 2 generator. For each session in its SESSIONS list,
        # reads P1 outputs and session_metadata, builds and writes idea_graph,
        # synthesis, and grounded_markers if they don't already exist.
        # Uses os.path.exists() for existence checks and os.listdir() to
        # find session directories. read_json wraps tools.json_io.load_json.
        "reads": [
            # Phase 1 inputs (via read_json at lines 397-401)
            "{session_dir}/session_metadata.json",
            "{session_dir}/thread_extractions.json",
            "{session_dir}/geological_notes.json",
            "{session_dir}/semantic_primitives.json",
            "{session_dir}/explorer_notes.json",
            # Existence checks for already-existing P2 files (lines 389-391)
            # Also conditional reads if they exist (lines 407, 417)
            "{session_dir}/idea_graph.json",
            "{session_dir}/synthesis.json",
            "{session_dir}/grounded_markers.json",
        ],
        "writes": [
            # json.dump at lines 410-411
            "{session_dir}/idea_graph.json",
            # json.dump at lines 420-421
            "{session_dir}/synthesis.json",
            # json.dump at lines 427-428
            "{session_dir}/grounded_markers.json",
        ],
        "imports_from": [
            "tools.json_io",    # load_json (line 13)
            "tools.log_config", # get_logger (line 8)
        ],
    },

    "phase_2_synthesis/code_similarity.py": {
        # Import shim only. Re-exports everything from phase_0_prep/code_similarity.py.
        # No direct file I/O. All reads/writes happen in the canonical implementation.
        "reads": [],
        "writes": [],
        "imports_from": [
            "phase_0_prep.code_similarity",  # FileFingerprint, overlap_ratio, containment_ratio, compare_pair, classify_pattern, scan_directory, main (lines 24-31)
        ],
    },
}
