"""
I/O catalog for phase_1_extraction/ and phase_2_synthesis/ modules.

Generated 2026-02-25 by reading every .py file (excluding __init__.py)
in both directories. Every open(), json.load(), json.dump(), write_text(),
read_text(), Path.glob(), and path template was recorded.

Format per file:
    "reads":        list of file patterns or names this module reads
    "writes":       list of file patterns or names this module writes
    "imports_from": list of pipeline modules imported (from phase_X, from tools, from config)
"""

PHASE1_2_IO = {
    # =========================================================================
    # phase_1_extraction/
    # =========================================================================

    "phase_1_extraction/opus_phase1.py": {
        "reads": [
            # Per-session input files (via load_session_data)
            "{session_dir}/safe_condensed.json",
            "{session_dir}/safe_tier4.json",
            "{session_dir}/session_metadata.json",
            # Commitments file (read once at import)
            "~/.claude/CLAUDE.md",
            # Session measurements index (for duplicate detection)
            "{INDEXES_DIR}/session_measurements.json",
            # Chat archive sessions dir (iterdir for duplicate detection)
            "{CHAT_ARCHIVE_DIR}/sessions/*.jsonl",
            # Progress file (read implicitly via overwrite pattern)
            "{INDEXES_DIR}/phase1_redo_progress.json",
        ],
        "writes": [
            # Per-session output files (via process_session)
            "{session_dir}/thread_extractions.json",
            "{session_dir}/geological_notes.json",
            "{session_dir}/semantic_primitives.json",
            "{session_dir}/explorer_notes.json",
            # Progress tracking
            "{INDEXES_DIR}/phase1_redo_progress.json",
        ],
        "imports_from": [
            "config",                       # SESSIONS_STORE_DIR, INDEXES_DIR, load_env, CHAT_ARCHIVE_DIR
            "phase_0_prep.schema_normalizer",  # NORMALIZERS, normalize_file
            "tools.log_config",             # get_logger
        ],
    },

    "phase_1_extraction/extract_threads.py": {
        "reads": [
            # Prefers Opus-classified, falls back to Python tier-4
            "{session_output_dir}/opus_priority_messages.json",
            "{session_output_dir}/tier4_priority_messages.json",
        ],
        "writes": [
            "{session_output_dir}/thread_extractions.json",
        ],
        "imports_from": [
            "config",           # get_session_output_dir
            "tools.log_config", # get_logger
        ],
    },

    "phase_1_extraction/batch_orchestrator.py": {
        "reads": [
            # Scans output/ for session dirs; checks file existence
            "{output_dir}/session_*/enriched_session.json",
            "{output_dir}/session_*/safe_tier4.json",
            "{output_dir}/session_*/session_metadata.json",
            # Phase 1 existence checks
            "{output_dir}/session_*/thread_extractions.json",
            "{output_dir}/session_*/geological_notes.json",
            "{output_dir}/session_*/semantic_primitives.json",
            "{output_dir}/session_*/explorer_notes.json",
            # Phase 2 existence checks
            "{output_dir}/session_*/idea_graph.json",
            "{output_dir}/session_*/synthesis.json",
            "{output_dir}/session_*/grounded_markers.json",
        ],
        "writes": [],
        "imports_from": [],
    },

    "phase_1_extraction/batch_llm_orchestrator.py": {
        "reads": [
            # Session discovery: iterdir checking enriched_session.json
            "{SESSIONS_STORE_DIR}/session_*/enriched_session.json",
            # Pass output existence checks
            "{SESSIONS_STORE_DIR}/session_*/llm_pass1_content_ref.json",
            "{SESSIONS_STORE_DIR}/session_*/llm_pass2_behaviors.json",
            "{SESSIONS_STORE_DIR}/session_*/llm_pass3_intent.json",
            "{SESSIONS_STORE_DIR}/session_*/llm_pass4_importance.json",
            # Merged file existence check
            "{SESSIONS_STORE_DIR}/session_*/enriched_session_v2.json",
            # Checkpoint and cost log
            "{INDEXES_DIR}/llm_pass_checkpoint.json",
            "{INDEXES_DIR}/llm_pass_cost_log.json",
        ],
        "writes": [
            "{INDEXES_DIR}/llm_pass_checkpoint.json",
            "{INDEXES_DIR}/llm_pass_cost_log.json",
        ],
        "imports_from": [
            "config",  # SESSIONS_STORE_DIR, INDEXES_DIR
        ],
    },

    "phase_1_extraction/interactive_batch_runner.py": {
        "reads": [
            # Same scan pattern as batch_orchestrator.py
            "{output_dir}/session_*/enriched_session.json",
            "{output_dir}/session_*/safe_tier4.json",
            "{output_dir}/session_*/session_metadata.json",
            # Phase 1 existence checks
            "{output_dir}/session_*/thread_extractions.json",
            "{output_dir}/session_*/geological_notes.json",
            "{output_dir}/session_*/semantic_primitives.json",
            "{output_dir}/session_*/explorer_notes.json",
            # Phase 2 existence checks
            "{output_dir}/session_*/idea_graph.json",
            "{output_dir}/session_*/synthesis.json",
            "{output_dir}/session_*/grounded_markers.json",
        ],
        "writes": [],
        "imports_from": [
            "tools.log_config",  # get_logger
        ],
    },

    "phase_1_extraction/tag_semantic_primitives.py": {
        "reads": [
            # Prefers Opus-classified, falls back to Python tier-4
            "{session_dir}/opus_priority_messages.json",
            "{session_dir}/tier4_priority_messages.json",
            # User messages supplementary context
            "{session_dir}/user_messages_tier2plus.json",
            # Enriched session for high-intensity user messages
            "{session_dir}/enriched_session.json",
        ],
        "writes": [
            "{session_dir}/semantic_primitives.json",
        ],
        "imports_from": [
            "config",           # get_session_output_dir
            "tools.log_config", # get_logger
        ],
    },

    "phase_1_extraction/batch_p1_llm.py": {
        "reads": [
            # Session discovery: iterdir checking enriched_session.json
            "{SESSIONS_STORE_DIR}/session_*/enriched_session.json",
            # Pass output existence checks
            "{SESSIONS_STORE_DIR}/session_*/llm_pass1_content_ref.json",
            "{SESSIONS_STORE_DIR}/session_*/llm_pass2_behaviors.json",
            "{SESSIONS_STORE_DIR}/session_*/llm_pass3_intent.json",
            "{SESSIONS_STORE_DIR}/session_*/llm_pass4_importance.json",
            # Merged file existence check
            "{SESSIONS_STORE_DIR}/session_*/enriched_session_v2.json",
            # Checkpoint and cost log
            "{INDEXES_DIR}/llm_pass_checkpoint.json",
            "{INDEXES_DIR}/llm_pass_cost_log.json",
        ],
        "writes": [
            "{INDEXES_DIR}/llm_pass_checkpoint.json",
            "{INDEXES_DIR}/llm_pass_cost_log.json",
        ],
        "imports_from": [
            "config",           # SESSIONS_STORE_DIR, INDEXES_DIR
            "tools.log_config", # get_logger
        ],
    },

    "phase_1_extraction/tag_primitives.py": {
        "reads": [
            # Prefers Opus-classified, falls back to Python tier-4
            "{session_dir}/opus_priority_messages.json",
            "{session_dir}/tier4_priority_messages.json",
            # User messages supplementary context
            "{session_dir}/user_messages_tier2plus.json",
            # Enriched session for high-intensity user messages
            "{session_dir}/enriched_session.json",
        ],
        "writes": [
            "{session_dir}/semantic_primitives.json",
        ],
        "imports_from": [
            "config",  # get_session_output_dir
        ],
    },

    # =========================================================================
    # phase_2_synthesis/
    # =========================================================================

    "phase_2_synthesis/batch_phase2_processor.py": {
        "reads": [
            # Per-session Phase 1 inputs
            "{session_dir}/thread_extractions.json",
            "{session_dir}/geological_notes.json",
            "{session_dir}/semantic_primitives.json",
            "{session_dir}/explorer_notes.json",
            "{session_dir}/session_metadata.json",
            # Existence checks for skip logic
            "{session_dir}/idea_graph.json",
            "{session_dir}/synthesis.json",
            "{session_dir}/grounded_markers.json",
        ],
        "writes": [
            "{session_dir}/idea_graph.json",
            "{session_dir}/synthesis.json",
            "{session_dir}/grounded_markers.json",
        ],
        "imports_from": [],
    },

    "phase_2_synthesis/batch_p2_generator.py": {
        "reads": [
            # Per-session Phase 1 inputs (via read_json)
            "{session_dir}/session_metadata.json",
            "{session_dir}/thread_extractions.json",
            "{session_dir}/geological_notes.json",
            "{session_dir}/semantic_primitives.json",
            "{session_dir}/explorer_notes.json",
            # Existence checks / conditional reads for already-existing P2 files
            "{session_dir}/idea_graph.json",
            "{session_dir}/synthesis.json",
            "{session_dir}/grounded_markers.json",
        ],
        "writes": [
            "{session_dir}/idea_graph.json",
            "{session_dir}/synthesis.json",
            "{session_dir}/grounded_markers.json",
        ],
        "imports_from": [],
    },

    "phase_2_synthesis/file_genealogy.py": {
        "reads": [
            "{session_output_dir}/thread_extractions.json",
            "{session_output_dir}/idea_graph.json",
        ],
        "writes": [
            "{session_output_dir}/file_genealogy.json",
        ],
        "imports_from": [
            "config",           # get_session_output_dir, SESSION_ID
            "tools.json_io",    # load_json
            "tools.log_config", # get_logger
        ],
    },

    "phase_2_synthesis/backfill_phase2.py": {
        "reads": [
            # Per-session Phase 1 inputs (via read_json -> tools.json_io.load_json)
            "{session_dir}/session_metadata.json",
            "{session_dir}/thread_extractions.json",
            "{session_dir}/geological_notes.json",
            "{session_dir}/semantic_primitives.json",
            "{session_dir}/explorer_notes.json",
            # Existence checks / conditional reads for already-existing P2 files
            "{session_dir}/idea_graph.json",
            "{session_dir}/synthesis.json",
            "{session_dir}/grounded_markers.json",
        ],
        "writes": [
            "{session_dir}/idea_graph.json",
            "{session_dir}/synthesis.json",
            "{session_dir}/grounded_markers.json",
        ],
        "imports_from": [
            "tools.json_io",    # load_json
            "tools.log_config", # get_logger
        ],
    },

    "phase_2_synthesis/build_phase2_outputs.py": {
        "reads": [
            # Per-session Phase 1 inputs (via load_json -> tools.json_io.load_json)
            "{session_dir}/thread_extractions.json",
            "{session_dir}/geological_notes.json",
            "{session_dir}/semantic_primitives.json",
            "{session_dir}/explorer_notes.json",
            "{session_dir}/session_metadata.json",
            # Existence checks for skip logic
            "{session_dir}/idea_graph.json",
            "{session_dir}/synthesis.json",
            "{session_dir}/grounded_markers.json",
        ],
        "writes": [
            "{session_dir}/idea_graph.json",
            "{session_dir}/synthesis.json",
            "{session_dir}/grounded_markers.json",
        ],
        "imports_from": [
            "tools.json_io",    # load_json
            "tools.log_config", # get_logger
        ],
    },

    "phase_2_synthesis/code_similarity.py": {
        "reads": [],
        "writes": [],
        "imports_from": [
            "phase_0_prep.code_similarity",  # FileFingerprint, overlap_ratio, containment_ratio, compare_pair, classify_pattern, scan_directory, main
        ],
    },
}
