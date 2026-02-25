"""
I/O catalog for phase_0_prep/ modules.

Generated 2026-02-25 by reading every .py file (excluding __init__.py,
__pycache__/, v5_compat/, standby/) in phase_0_prep/. Every open(),
json.load(), json.dump(), write_text(), read_text(), Path.glob(),
and path template was recorded.

Format per file:
    "reads":        list of file patterns or names this module reads
    "writes":       list of file patterns or names this module writes
    "imports_from": list of pipeline modules imported (from phase_X, from tools, from config)

Path placeholders:
    {session}       = per-session output dir (e.g. SESSIONS_STORE_DIR/session_0012ebed/)
    {INDEXES_DIR}   = shared indexes directory
    {CHAT_DIR}      = CHAT_ARCHIVE_DIR/sessions/ (raw JSONL chat files)
    {REPO}          = repository root (hyperdocs_3/)
"""

PHASE0_IO = {
    # =========================================================================
    # Core enrichment pipeline (JSONL -> enriched_session.json)
    # =========================================================================

    "phase_0_prep/enrich_session.py": {
        "reads": [
            # Source JSONL chat history file (via ClaudeSessionReader.load_session_file)
            "{CHAT_DIR}/*.jsonl",
        ],
        "writes": [
            "{session}/enriched_session.json",
        ],
        "imports_from": [
            "phase_0_prep.claude_session_reader",   # ClaudeSessionReader
            "phase_0_prep.geological_reader",        # GeologicalReader
            "phase_0_prep.metadata_extractor",       # MetadataExtractor
            "phase_0_prep.message_filter",           # MessageFilter
            "phase_0_prep.claude_behavior_analyzer", # ClaudeBehaviorAnalyzer
            "config",                                # SESSION_ID, get_session_file, get_session_output_dir
            "tools.log_config",                      # get_logger
        ],
    },

    # =========================================================================
    # Sub-extractors used by enrich_session / deterministic_prep (library mode)
    # =========================================================================

    "phase_0_prep/claude_session_reader.py": {
        "reads": [
            # Claude Code session JSONL files (via Path.glob("*.jsonl"))
            "~/.claude/projects/**/*.jsonl",
        ],
        "writes": [],
        "imports_from": [
            "tools.log_config",  # get_logger
        ],
    },

    "phase_0_prep/geological_reader.py": {
        "reads": [
            # Chat history JSONL files (via discover_jsonl_files -> Path.glob)
            "**/*.jsonl",
            # .env file (via dotenv.load_dotenv)
            ".env",
            # api_call_log.json (code exists but function returns immediately — disabled)
            # "{session}/api_call_log.json",
        ],
        "writes": [
            # api_call_log.json (disabled — _save_api_log returns at line 54)
        ],
        "imports_from": [
            "tools.log_config",  # get_logger
        ],
    },

    "phase_0_prep/metadata_extractor.py": {
        "reads": [
            # Library mode: no file I/O (operates on in-memory message objects)
            # Standalone main(): uses HyperdocTracker / DisplayFormatAdapter (indirect reads)
        ],
        "writes": [
            # Standalone main() only: output JSON via --output arg
            # "{output_path}.json",
        ],
        "imports_from": [
            "tools.log_config",                       # get_logger
            "phase_0_prep.geological_reader",          # GeologicalMessage, GeologicalSession
        ],
    },

    "phase_0_prep/message_filter.py": {
        "reads": [
            # Library mode: no file I/O (operates on in-memory message dicts)
            # Standalone profile_archive mode: reads JSONL files
            # "*.jsonl",
        ],
        "writes": [],
        "imports_from": [
            "tools.log_config",  # get_logger
        ],
    },

    "phase_0_prep/claude_behavior_analyzer.py": {
        "reads": [
            # Pure in-memory analysis — no file I/O
            # Operates on ClaudeMessage objects passed by caller
        ],
        "writes": [],
        "imports_from": [
            "tools.log_config",                        # get_logger
            "phase_0_prep.claude_session_reader",       # ClaudeSessionReader, ClaudeSession, ClaudeMessage
        ],
    },

    # =========================================================================
    # LLM pass infrastructure (enriched_session.json -> enriched_session_v2.json)
    # =========================================================================

    "phase_0_prep/prompts.py": {
        "reads": [],
        "writes": [],
        "imports_from": [],
        # Pure utility: prompt templates + PASS_CONFIGS dict defining output_file names:
        #   llm_pass1_content_ref.json, llm_pass2_behaviors.json,
        #   llm_pass3_intent.json, llm_pass4_importance.json
    },

    "phase_0_prep/llm_pass_runner.py": {
        "reads": [
            # .env file (via dotenv.load_dotenv)
            ".env",
            # Per-session enriched data (via load_enriched_session)
            "{session}/safe_condensed.json",
            "{session}/enriched_session.json",
            # Pass 1 output needed as input for Pass 3 (intent assumptions)
            "{session}/llm_pass1_content_ref.json",
        ],
        "writes": [
            # Per-session LLM pass output files (one per pass)
            "{session}/llm_pass1_content_ref.json",
            "{session}/llm_pass2_behaviors.json",
            "{session}/llm_pass3_intent.json",
            "{session}/llm_pass4_importance.json",
        ],
        "imports_from": [
            "config",        # OUTPUT_DIR
            "phase_0_prep.prompts",  # PASS_CONFIGS, format_messages_for_prompt, format_messages_with_context
            "tools.log_config",      # get_logger
        ],
    },

    "phase_0_prep/merge_llm_results.py": {
        "reads": [
            "{session}/enriched_session.json",
            "{session}/llm_pass1_content_ref.json",
            "{session}/llm_pass2_behaviors.json",
            "{session}/llm_pass3_intent.json",
            "{session}/llm_pass4_importance.json",
        ],
        "writes": [
            "{session}/enriched_session_v2.json",
        ],
        "imports_from": [
            "config",               # OUTPUT_DIR
            "phase_0_prep.prompts", # PASS_CONFIGS
            "tools.log_config",     # get_logger
        ],
    },

    # =========================================================================
    # Batch orchestrators (run LLM passes across all sessions)
    # =========================================================================

    "phase_0_prep/batch_p0_llm.py": {
        "reads": [
            # Duplicate detection manifest
            "{INDEXES_DIR}/duplicate_manifest.json",
            # Per-session enriched data (existence check + load)
            "{session}/enriched_session.json",
            # Pass 1 output (checked for Pass 3 dependency)
            "{session}/llm_pass1_content_ref.json",
            # Batch status for resume capability
            "batch_llm_status.json",
        ],
        "writes": [
            "batch_llm_status.json",
        ],
        "imports_from": [
            "config",                          # OUTPUT_DIR, SESSIONS_STORE_DIR, INDEXES_DIR
            "phase_0_prep.prompts",            # PASS_CONFIGS
            "phase_0_prep.llm_pass_runner",    # find_session_dir, load_enriched_session, run_pass
            "phase_0_prep.merge_llm_results",  # merge_session
            "tools.log_config",                # get_logger
        ],
    },

    "phase_0_prep/batch_phase0_reprocess.py": {
        "reads": [
            # All JSONL files in chat archive (via iterdir to find source per session)
            "{CHAT_DIR}/*.jsonl",
            # Per-session existence check for enriched_session.json
            "{session}/enriched_session.json",
        ],
        "writes": [
            # Reprocess log (to INDEXES_DIR)
            "{INDEXES_DIR}/phase0_reprocess_log.json",
        ],
        "imports_from": [
            "config",           # CHAT_ARCHIVE_DIR, SESSIONS_STORE_DIR, INDEXES_DIR
            "tools.log_config", # get_logger
        ],
    },

    # =========================================================================
    # Opus classification (alternative to Python tier system)
    # =========================================================================

    "phase_0_prep/opus_classifier.py": {
        "reads": [
            # Per-session enriched data (prefers v2, falls back to v1)
            "{session}/enriched_session_v2.json",
            "{session}/enriched_session.json",
            # .env file (via dotenv.load_dotenv for ANTHROPIC_API_KEY)
            ".env",
        ],
        "writes": [
            "{session}/opus_classifications.json",
            "{session}/opus_vs_python_comparison.json",
        ],
        "imports_from": [
            "config",           # get_session_output_dir, SESSION_ID
            "tools.log_config", # get_logger
        ],
    },

    "phase_0_prep/build_opus_messages.py": {
        "reads": [
            # Opus classification results
            "{session}/opus_classifications.json",
            # Enriched session (prefers v2, falls back to v1)
            "{session}/enriched_session_v2.json",
            "{session}/enriched_session.json",
        ],
        "writes": [
            "{session}/opus_priority_messages.json",
        ],
        "imports_from": [
            "config",           # get_session_output_dir, SESSION_ID
            "tools.log_config", # get_logger
        ],
    },

    # =========================================================================
    # Agent data preparation (enriched_session -> split files for agents)
    # =========================================================================

    "phase_0_prep/prepare_agent_data.py": {
        "reads": [
            # Enriched session (prefers v2, falls back to v1)
            "{session}/enriched_session_v2.json",
            "{session}/enriched_session.json",
            # Opus classifications (existence check for build_opus_filtered call)
            "{session}/opus_classifications.json",
            # All JSON files in session dir (glob for profanity sanitization)
            "{session}/**/*.json",
        ],
        "writes": [
            "{session}/session_metadata.json",
            "{session}/tier2plus_messages.json",
            "{session}/tier4_priority_messages.json",
            "{session}/conversation_condensed.json",
            "{session}/user_messages_tier2plus.json",
            "{session}/emergency_contexts.json",
            "{session}/batches/batch_NNN.json",
            "{session}/safe_tier4.json",
            "{session}/safe_condensed.json",
            # Also sanitizes all {session}/**/*.json in-place (profanity filter)
        ],
        "imports_from": [
            "config",                              # get_session_output_dir
            "tools.log_config",                    # get_logger
            "phase_0_prep.build_opus_messages",    # build_opus_filtered (called as function)
        ],
    },

    # =========================================================================
    # Code analysis utility
    # =========================================================================

    "phase_0_prep/code_similarity.py": {
        "reads": [
            # All Python files in source directory (via Path.glob("*.py") + read_text)
            "{REPO}/**/*.py",
        ],
        "writes": [
            "{INDEXES_DIR}/code_similarity_index.json",
        ],
        "imports_from": [
            "tools.log_config",  # get_logger
            "config",            # INDEXES_DIR
        ],
    },
}
