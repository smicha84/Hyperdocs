"""
I/O catalog for phase_1_extraction/ and phase_2_synthesis/ modules.

Fresh recount 2026-02-25. Every .py file (excluding __init__.py, __pycache__)
in both directories was read completely from source. No existing manifest
was referenced. Every open(), json.load(), json.dump(), write_text(),
read_text(), Path.glob(), Path.iterdir(), .exists() check, and path
construction was recorded from the actual source code.

Files cataloged (8 total):
  phase_1_extraction/batch_p1_llm.py
  phase_1_extraction/extract_threads.py
  phase_1_extraction/interactive_batch_runner.py
  phase_1_extraction/opus_phase1.py
  phase_1_extraction/tag_semantic_primitives.py
  phase_2_synthesis/backfill_phase2.py
  phase_2_synthesis/code_similarity.py
  phase_2_synthesis/file_genealogy.py

Format per file:
    "reads":        list of file patterns or names this module reads
    "writes":       list of file patterns or names this module writes
    "imports_from": list of pipeline modules imported (from phase_X, from tools, from config)

Prefix conventions:
    {session_dir}/          per-session directory (SESSIONS_STORE_DIR or output/)
    {INDEXES_DIR}/          global indexes directory (~/PERMANENT_HYPERDOCS/indexes/)
    {CHAT_ARCHIVE_DIR}/     chat archive sessions root
    ~/                      user home directory
"""

PHASE1_2_IO = {
    # =========================================================================
    # phase_1_extraction/
    # =========================================================================

    "phase_1_extraction/batch_p1_llm.py": {
        # Batch LLM orchestrator: runs 4 LLM passes (pass1-pass4) across all
        # sessions. Delegates actual API calls to phase_0_prep/llm_pass_runner.py
        # and phase_0_prep/merge_llm_results.py via subprocess.  Does NOT read or
        # write session payload files directly; the subprocesses do that.
        "reads": [
            # Session discovery: OUTPUT_DIR.iterdir(), checks .exists() (lines 97-102)
            "{session_dir}/enriched_session.json",
            # Pass completion marker checks: (s / output_file).exists() (lines 108-109)
            "{session_dir}/llm_pass1_content_ref.json",
            "{session_dir}/llm_pass2_behaviors.json",
            "{session_dir}/llm_pass3_intent.json",
            "{session_dir}/llm_pass4_importance.json",
            # Merged output existence check in show_status (line 335)
            "{session_dir}/enriched_session_v2.json",
            # Checkpoint: open(CHECKPOINT_FILE) + json.load (lines 117-118)
            "{INDEXES_DIR}/llm_pass_checkpoint.json",
            # Cost log: open(COST_LOG_FILE) + json.load (lines 133-135, line 341)
            "{INDEXES_DIR}/llm_pass_cost_log.json",
        ],
        "writes": [
            # Checkpoint: open(CHECKPOINT_FILE, 'w') + json.dump (lines 125-126)
            "{INDEXES_DIR}/llm_pass_checkpoint.json",
            # Cost log: open(COST_LOG_FILE, 'w') + json.dump (lines 143-144)
            "{INDEXES_DIR}/llm_pass_cost_log.json",
        ],
        "imports_from": [
            "config",           # SESSIONS_STORE_DIR, INDEXES_DIR (lines 51-57)
            "tools.log_config", # get_logger (line 44)
        ],
    },

    "phase_1_extraction/extract_threads.py": {
        # Deterministic 6-thread + 6-marker extractor. Reads priority messages
        # (Opus-classified preferred, Python tier-4 fallback). Writes
        # thread_extractions.json with canonical thread categories + per-message
        # extractions. Contains hard-coded reference annotations for session 3b7084d5.
        "reads": [
            # _OPUS_INPUT = _OUT / "opus_priority_messages.json" (line 32)
            # _PYTHON_INPUT = _OUT / "tier4_priority_messages.json" (line 33)
            # INPUT_PATH chosen at import time: Opus if it .exists(), else Python (line 34)
            "{session_dir}/opus_priority_messages.json",
            "{session_dir}/tier4_priority_messages.json",
        ],
        "writes": [
            # OUTPUT_PATH = str(_OUT / "thread_extractions.json") (line 35)
            # open(OUTPUT_PATH, 'w') + json.dump (lines 747-748)
            "{session_dir}/thread_extractions.json",
        ],
        "imports_from": [
            "config",           # get_session_output_dir (lines 23-27)
            "tools.log_config", # get_logger (line 11)
        ],
    },

    "phase_1_extraction/interactive_batch_runner.py": {
        # Read-only CLI status/queue tool. Scans output/ for session progress,
        # prints instructions for human or Claude to follow. No API calls.
        "reads": [
            # OUTPUT.iterdir() scanning for session_* dirs (line 36)
            # (d / "enriched_session.json").exists() (line 39)
            "{session_dir}/enriched_session.json",
            # (d / "safe_tier4.json").exists() (line 41)
            "{session_dir}/safe_tier4.json",
            # open(summary_f) + json.load (lines 48-49)
            "{session_dir}/session_metadata.json",
            # P1 completion checks — all 4 must exist (line 58)
            "{session_dir}/thread_extractions.json",
            "{session_dir}/geological_notes.json",
            "{session_dir}/semantic_primitives.json",
            "{session_dir}/explorer_notes.json",
            # P2 completion checks — all 3 must exist (line 59)
            "{session_dir}/idea_graph.json",
            "{session_dir}/synthesis.json",
            "{session_dir}/grounded_markers.json",
        ],
        "writes": [],  # pure status reporter — no writes
        "imports_from": [
            "tools.log_config", # get_logger (line 22)
        ],
    },

    "phase_1_extraction/opus_phase1.py": {
        # Primary Phase 1 pipeline: runs 4 sequential Opus API calls per
        # session (Thread Analyst, Geological Reader, Primitives Tagger, Free
        # Explorer + Verification). Supports token-based chunking for large
        # sessions. Reads CLAUDE.md once at import time to prepend commitments
        # to every prompt. Scans chat archive for duplicate detection.
        "reads": [
            # load_session_data: open(fpath) + json.load for each (lines 470-477)
            "{session_dir}/safe_condensed.json",
            "{session_dir}/safe_tier4.json",
            "{session_dir}/session_metadata.json",
            # CLAUDE_MD.read_text() at import time (lines 482-483)
            "~/.claude/CLAUDE.md",
            # _build_duplicate_skip_ids: CHAT_DIR.iterdir() scanning *.jsonl (lines 121-125)
            "{CHAT_ARCHIVE_DIR}/sessions/*.jsonl",
            # PROGRESS_FILE read when resuming (referenced path; written more than read)
            "{INDEXES_DIR}/phase1_redo_progress.json",
        ],
        "writes": [
            # Pass 1 output: open(session_dir / "thread_extractions.json", 'w') + json.dump (lines 635-636)
            "{session_dir}/thread_extractions.json",
            # Pass 2 output: open(session_dir / "geological_notes.json", 'w') + json.dump (lines 668-669)
            "{session_dir}/geological_notes.json",
            # Pass 3 output: open(session_dir / "semantic_primitives.json", 'w') + json.dump (lines 738-739)
            "{session_dir}/semantic_primitives.json",
            # Pass 4 output: open(session_dir / "explorer_notes.json", 'w') + json.dump (lines 763-764)
            "{session_dir}/explorer_notes.json",
            # Progress tracking: open(PROGRESS_FILE, 'w') + json.dump (lines 803-804, 855-856, 876-877)
            "{INDEXES_DIR}/phase1_redo_progress.json",
        ],
        "imports_from": [
            "config",                   # SESSIONS_STORE_DIR, INDEXES_DIR, load_env,
                                        # CHAT_ARCHIVE_DIR (lines 88-99, 110-115)
            "tools.schema_normalizer",  # NORMALIZERS, normalize_file (line 104)
            "tools.log_config",         # get_logger (line 73)
        ],
    },

    "phase_1_extraction/tag_semantic_primitives.py": {
        # Standalone deterministic Semantic Primitives tagger (single-session,
        # no API calls). Reads priority messages + user tier-2+ + full enriched
        # data. Tags each message with 7 primitives using keyword/regex rules.
        # Kept as single-session reference; opus_phase1.py is the batch path.
        "reads": [
            # _OPUS_PRIORITY = SESSION_DIR / "opus_priority_messages.json" (line 39)
            # _PYTHON_TIER4 = SESSION_DIR / "tier4_priority_messages.json" (line 40)
            # TIER4_FILE chosen via .exists() (line 41)
            "{session_dir}/opus_priority_messages.json",
            "{session_dir}/tier4_priority_messages.json",
            # USER_FILE = SESSION_DIR / "user_messages_tier2plus.json" (line 42)
            # open(USER_FILE, 'r') + json.load (lines 551-552)
            "{session_dir}/user_messages_tier2plus.json",
            # ENRICHED_FILE = SESSION_DIR / "enriched_session.json" (line 43)
            # open(ENRICHED_FILE, 'r') + json.load (lines 570-571) — only if .exists()
            "{session_dir}/enriched_session.json",
        ],
        "writes": [
            # OUTPUT_FILE = SESSION_DIR / "semantic_primitives.json" (line 44)
            # open(OUTPUT_FILE, 'w') + json.dump (lines 633-634)
            "{session_dir}/semantic_primitives.json",
        ],
        "imports_from": [
            "config",           # get_session_output_dir (lines 32-36)
            "tools.log_config", # get_logger (line 19)
        ],
    },

    # =========================================================================
    # phase_2_synthesis/
    # =========================================================================

    "phase_2_synthesis/backfill_phase2.py": {
        # Batch Phase 2 generator for sessions missing idea_graph.json,
        # synthesis.json, or grounded_markers.json. Hardcoded list of 20
        # session IDs. Uses deterministic logic — no API calls. Scans for
        # session dirs via os.listdir(BASE). read_json wraps tools.json_io.
        "reads": [
            # Existence checks via os.path.exists (lines 389-391)
            # Then read_json (= tools.json_io.load_json) if file exists (lines 397-401, 407, 417)
            "{session_dir}/session_metadata.json",
            "{session_dir}/thread_extractions.json",
            "{session_dir}/geological_notes.json",
            "{session_dir}/semantic_primitives.json",
            "{session_dir}/explorer_notes.json",
            # Conditionally read if already present; otherwise built and written
            "{session_dir}/idea_graph.json",
            "{session_dir}/synthesis.json",
            # grounded_markers.json: existence checked (line 393); never read, only written
            "{session_dir}/grounded_markers.json",
        ],
        "writes": [
            # open(os.path.join(sdir, "idea_graph.json"), 'w') + json.dump (lines 410-411)
            "{session_dir}/idea_graph.json",
            # open(os.path.join(sdir, "synthesis.json"), 'w') + json.dump (lines 420-421)
            "{session_dir}/synthesis.json",
            # open(os.path.join(sdir, "grounded_markers.json"), 'w') + json.dump (lines 427-428)
            "{session_dir}/grounded_markers.json",
        ],
        "imports_from": [
            "tools.json_io",    # load_json aliased as _load_json (line 13)
            "tools.log_config", # get_logger (line 8)
        ],
    },

    "phase_2_synthesis/code_similarity.py": {
        # Import shim only. Re-exports the full public API from
        # phase_0_prep/code_similarity.py. Has no file I/O of its own;
        # all reads/writes live in the canonical implementation.
        "reads": [],
        "writes": [],
        "imports_from": [
            # from phase_0_prep.code_similarity import ... (lines 24-31)
            "phase_0_prep.code_similarity",  # FileFingerprint, overlap_ratio, containment_ratio,
                                              # compare_pair, classify_pattern, scan_directory, main
        ],
    },

    "phase_2_synthesis/file_genealogy.py": {
        # Detects file identity across renames, rewrites, and duplications.
        # Reads thread extractions and idea graph; writes file_genealogy.json.
        # Uses three detection signals: idea graph lineage, temporal succession,
        # and name similarity. Clusters into families via union-find.
        "reads": [
            # load_json(OUT_DIR / "thread_extractions.json") at line 380
            "{session_dir}/thread_extractions.json",
            # load_json(OUT_DIR / "idea_graph.json") at line 381
            "{session_dir}/idea_graph.json",
        ],
        "writes": [
            # out_path = OUT_DIR / "file_genealogy.json"; open + json.dump (lines 429-430)
            "{session_dir}/file_genealogy.json",
        ],
        "imports_from": [
            "config",           # get_session_output_dir, SESSION_ID (lines 35-41)
            "tools.json_io",    # load_json aliased as _load_json (line 32)
            "tools.log_config", # get_logger (line 20)
        ],
    },
}
