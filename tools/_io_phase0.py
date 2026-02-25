"""
I/O catalog for phase_0_prep/ — fresh recount 2026-02-25.
Every file read line by line. No heuristics. No prior manifest consulted.

Format per entry:
    "reads":        every file/pattern this module reads
    "writes":       every file/pattern this module writes
    "imports_from": pipeline modules imported (phase_X, tools, config)

Path placeholders:
    {session}       per-session output dir  (SESSIONS_STORE_DIR/session_XXXXXXXX/)
    {INDEXES_DIR}   shared indexes dir      (PERMANENT_HYPERDOCS/indexes/)
    {CHAT_DIR}      raw JSONL source files  (CHAT_ARCHIVE_DIR/sessions/)
    {session_jsonl} single source JSONL     (one file, resolved via config or env var)
"""

PHASE0_IO = {

    # ── batch_p0_llm.py ───────────────────────────────────────────────────────
    # Orchestrates all 4 LLM passes across every unique session.
    # Reads the duplicate manifest to determine which sessions to skip.
    # Checks enriched_session.json existence to discover processable sessions.
    # Reads llm_pass1_content_ref.json to decide whether pass 3 applies.
    # Reads/writes batch_llm_status.json for resume support.
    # All per-session pass writes and enriched_session_v2.json are produced
    # by llm_pass_runner.run_pass() and merge_llm_results.merge_session().
    "phase_0_prep/batch_p0_llm.py": {
        "reads": [
            "{INDEXES_DIR}/duplicate_manifest.json",     # load_skip_ids()
            "{INDEXES_DIR}/batch_llm_status.json",       # show_status()
            "{session}/enriched_session.json",           # get_unique_sessions() — existence check
            "{session}/llm_pass1_content_ref.json",      # run_batch_pass() — pass 3 prerequisite check
            "{session}/llm_pass2_behaviors.json",        # pass_output_exists() checks
            "{session}/llm_pass3_intent.json",           # pass_output_exists() checks
            "{session}/llm_pass4_importance.json",       # pass_output_exists() checks
            "{session}/enriched_session_v2.json",        # merge_output_exists() check
        ],
        "writes": [
            "{INDEXES_DIR}/batch_llm_status.json",       # save_status() — written after every pass
            # Per-session pass files + enriched_session_v2.json are written by
            # llm_pass_runner and merge_llm_results (see those entries below).
        ],
        "imports_from": [
            "config",
            "phase_0_prep.prompts",
            "phase_0_prep.llm_pass_runner",
            "phase_0_prep.merge_llm_results",
            "tools.log_config",
        ],
    },

    # ── batch_phase0_reprocess.py ─────────────────────────────────────────────
    # Batch reprocessor: iterates all sessions with enriched_session.json,
    # finds the source JSONL for each, and spawns enrich_session.py +
    # prepare_agent_data.py as subprocesses. Also spawns schema_normalizer
    # and completeness_scanner. Writes a completion log.
    "phase_0_prep/batch_phase0_reprocess.py": {
        "reads": [
            "{CHAT_DIR}/*.jsonl",                        # _build_duplicate_set() + find_jsonl_for_session()
            "{session}/enriched_session.json",           # main() — existence check to find sessions
        ],
        "writes": [
            "{INDEXES_DIR}/phase0_reprocess_log.json",   # main() — written at end
        ],
        "imports_from": [
            "config",
            "tools.log_config",
        ],
    },

    # ── build_opus_messages.py ────────────────────────────────────────────────
    # Reads Opus classifications + enriched session, writes opus_priority_messages.json.
    # Prefers enriched_session_v2.json (has LLM pass data); falls back to v1.
    "phase_0_prep/build_opus_messages.py": {
        "reads": [
            "{session}/opus_classifications.json",       # build_opus_filtered() — required
            "{session}/enriched_session_v2.json",        # build_opus_filtered() — preferred
            "{session}/enriched_session.json",           # build_opus_filtered() — fallback
        ],
        "writes": [
            "{session}/opus_priority_messages.json",     # build_opus_filtered()
        ],
        "imports_from": [
            "config",
            "tools.log_config",
        ],
    },

    # ── claude_behavior_analyzer.py ───────────────────────────────────────────
    # Pure in-memory library. Provides ClaudeBehaviorAnalyzer and PreventionSystem.
    # All analysis operates on ClaudeMessage objects passed by callers.
    # No file I/O anywhere in the module.
    "phase_0_prep/claude_behavior_analyzer.py": {
        "reads": [],
        "writes": [],
        "imports_from": [
            "phase_0_prep.claude_session_reader",
            "tools.log_config",
        ],
    },

    # ── claude_session_reader.py ──────────────────────────────────────────────
    # Reads Claude Code session JSONL files from ~/.claude/projects/.
    # discover_session_files() uses Path.glob("*.jsonl").
    # All file I/O is driven by callers via load_session_file() / load_project_sessions().
    "phase_0_prep/claude_session_reader.py": {
        "reads": [
            "~/.claude/projects/{project}/*.jsonl",      # discover_session_files() / load_session_file()
        ],
        "writes": [],
        "imports_from": [
            "tools.log_config",
        ],
    },

    # ── code_similarity.py ────────────────────────────────────────────────────
    # Standalone analysis tool. Reads every *.py file in a source directory,
    # fingerprints all of them, compares all pairs, writes a similarity index.
    # Default source dir: hardcoded PycharmProjects path in main().
    # Default output: {INDEXES_DIR}/code_similarity_index.json via config.INDEXES_DIR.
    "phase_0_prep/code_similarity.py": {
        "reads": [
            "{source_dir}/*.py",                         # scan_directory() — FileFingerprint reads each file
        ],
        "writes": [
            "{INDEXES_DIR}/code_similarity_index.json",  # main() default output
        ],
        "imports_from": [
            "config",
            "tools.log_config",
        ],
    },

    # ── enrich_session.py ─────────────────────────────────────────────────────
    # Core Phase 0 worker. Reads one session JSONL, runs all Python extractors
    # (ClaudeSessionReader, MetadataExtractor, MessageFilter, ClaudeBehaviorAnalyzer),
    # and writes enriched_session.json.
    # Input path: config.get_session_file() or HYPERDOCS_CHAT_HISTORY env var.
    # Output dir: config.get_session_output_dir() or HYPERDOCS_OUTPUT_DIR env var.
    "phase_0_prep/enrich_session.py": {
        "reads": [
            "{session_jsonl}",                           # SESSION_FILE — the single source JSONL
        ],
        "writes": [
            "{session}/enriched_session.json",           # main() — primary output
        ],
        "imports_from": [
            "config",
            "phase_0_prep.claude_session_reader",
            "phase_0_prep.geological_reader",
            "phase_0_prep.metadata_extractor",
            "phase_0_prep.message_filter",
            "phase_0_prep.claude_behavior_analyzer",
            "tools.log_config",
        ],
    },

    # ── geological_reader.py ──────────────────────────────────────────────────
    # Provides GeologicalMessage, GeologicalSession, and GeologicalReader dataclasses.
    # The Opus-per-line methods (opus_parse_message, opus_analyze_session,
    # load_all_sessions, opus_get_statistics) are DEPRECATED stubs that raise
    # NotImplementedError. Active method: deterministic_parse_message() (pure Python).
    # GeologicalReader.discover_jsonl_files() uses Path.glob("**/*.jsonl") on
    # self.chat_dir passed by the caller.
    # log_api_call() (writes api_call_log.json) is DISABLED — returns immediately at line 54.
    # The standalone main() opens files[0] directly for reading as a test.
    "phase_0_prep/geological_reader.py": {
        "reads": [
            "{chat_dir}/**/*.jsonl",                     # discover_jsonl_files() + standalone main()
            ".env",                                      # dotenv.load_dotenv() — walks up from file location
        ],
        "writes": [
            # api_call_log.json write is DISABLED — log_api_call() returns at line 54
        ],
        "imports_from": [
            "tools.log_config",
        ],
    },

    # ── llm_pass_runner.py ────────────────────────────────────────────────────
    # Core infrastructure for running one LLM pass on one session.
    # load_enriched_session() prefers safe_condensed.json, falls back to enriched_session.json.
    # run_all_passes() and the CLI main() load llm_pass1_content_ref.json from disk
    # when pass 3 is requested without having run pass 1 in the same invocation.
    # run_pass() writes one output file per pass per session (defined in PASS_CONFIGS).
    # ENV loading: reads .env files from up to 3 candidate paths (REPO/.env, etc.).
    "phase_0_prep/llm_pass_runner.py": {
        "reads": [
            "{session}/safe_condensed.json",             # load_enriched_session() — preferred
            "{session}/enriched_session.json",           # load_enriched_session() — fallback
            "{session}/llm_pass1_content_ref.json",      # run_all_passes() / CLI main() — pass 3 prerequisite
            ".env",                                      # ENV_CANDIDATES loader at module level
        ],
        "writes": [
            "{session}/llm_pass1_content_ref.json",      # run_pass() pass 1
            "{session}/llm_pass2_behaviors.json",        # run_pass() pass 2
            "{session}/llm_pass3_intent.json",           # run_pass() pass 3
            "{session}/llm_pass4_importance.json",       # run_pass() pass 4
        ],
        "imports_from": [
            "config",
            "phase_0_prep.prompts",
            "tools.log_config",
        ],
    },

    # ── merge_llm_results.py ──────────────────────────────────────────────────
    # Merges all 4 per-pass output files into enriched_session_v2.json.
    # merge_session() always reads enriched_session.json (not v2 — v2 is the output).
    "phase_0_prep/merge_llm_results.py": {
        "reads": [
            "{session}/enriched_session.json",           # merge_session() — base document
            "{session}/llm_pass1_content_ref.json",      # load_pass_results()
            "{session}/llm_pass2_behaviors.json",        # load_pass_results()
            "{session}/llm_pass3_intent.json",           # load_pass_results()
            "{session}/llm_pass4_importance.json",       # load_pass_results()
        ],
        "writes": [
            "{session}/enriched_session_v2.json",        # merge_session()
        ],
        "imports_from": [
            "config",
            "phase_0_prep.prompts",
            "tools.log_config",
        ],
    },

    # ── message_filter.py ─────────────────────────────────────────────────────
    # Pure in-memory library. MessageFilter.classify() operates entirely on
    # text strings passed by callers. No file I/O in the class itself.
    # The standalone __main__ block calls profile_archive() which reads
    # JSONL files — but this code path is not invoked by the pipeline.
    "phase_0_prep/message_filter.py": {
        "reads": [
            # profile_archive() standalone only — not called by pipeline:
            # "{archive_path}/*.jsonl",
        ],
        "writes": [],
        "imports_from": [
            "tools.log_config",
        ],
    },

    # ── metadata_extractor.py ─────────────────────────────────────────────────
    # Pure in-memory library. MetadataExtractor.extract_message_metadata() and
    # extract_session_metadata() operate entirely on GeologicalMessage objects
    # passed by callers. No file I/O in the class.
    # The standalone main() can write to --output if provided, but this is not
    # called by the pipeline.
    "phase_0_prep/metadata_extractor.py": {
        "reads": [],
        "writes": [
            # standalone main() only, user-specified --output path:
            # "{args.output}",
        ],
        "imports_from": [
            "phase_0_prep.geological_reader",
            "tools.log_config",
        ],
    },

    # ── opus_classifier.py ────────────────────────────────────────────────────
    # Classifies messages via Opus API. Reads enriched session (v2 preferred, v1 fallback).
    # Writes opus_classifications.json and optionally opus_vs_python_comparison.json.
    # The classify_with_opus() function loads .env from up to 2 candidate paths.
    "phase_0_prep/opus_classifier.py": {
        "reads": [
            "{session}/enriched_session_v2.json",        # main() — preferred
            "{session}/enriched_session.json",           # main() — fallback
            ".env",                                      # classify_with_opus() API key loader
        ],
        "writes": [
            "{session}/opus_classifications.json",       # main()
            "{session}/opus_vs_python_comparison.json",  # main() — only when --compare flag is set
        ],
        "imports_from": [
            "config",
            "tools.log_config",
        ],
    },

    # ── prepare_agent_data.py ─────────────────────────────────────────────────
    # Splits enriched session into 9 smaller agent-readable files.
    # Reads enriched_session_v2.json (preferred) or enriched_session.json.
    # Step 8 (profanity sanitization) reads ALL *.json under {session}/ via glob,
    # sanitizes each one in-place, and rewrites them.
    # If opus_classifications.json exists, calls build_opus_messages.build_opus_filtered()
    # which adds opus_priority_messages.json to the output set.
    "phase_0_prep/prepare_agent_data.py": {
        "reads": [
            "{session}/enriched_session_v2.json",        # INPUT_V2 — preferred
            "{session}/enriched_session.json",           # INPUT_V1 — fallback
            "{session}/opus_classifications.json",       # existence check for optional Opus step
            "{session}/**/*.json",                       # Step 8 sanitization glob
        ],
        "writes": [
            "{session}/session_metadata.json",           # step 1
            "{session}/tier2plus_messages.json",         # step 2
            "{session}/tier4_priority_messages.json",    # step 3
            "{session}/conversation_condensed.json",     # step 4
            "{session}/user_messages_tier2plus.json",    # step 5
            "{session}/emergency_contexts.json",         # step 6
            "{session}/batches/batch_NNN.json",          # step 7 — batch_001.json … batch_NNN.json
            # Step 8: all {session}/**/*.json rewritten in-place (profanity filter)
            "{session}/safe_tier4.json",                 # step 9
            "{session}/safe_condensed.json",             # step 9
            # Optional step 10 (when opus_classifications.json exists):
            "{session}/opus_priority_messages.json",     # via build_opus_messages.build_opus_filtered()
        ],
        "imports_from": [
            "config",
            "tools.log_config",
            "phase_0_prep.build_opus_messages",          # optional, imported inline in step 10
        ],
    },

    # ── prompts.py ────────────────────────────────────────────────────────────
    # Pure library: prompt strings (PASS1_SYSTEM … PASS4_USER_TEMPLATE) and
    # PASS_CONFIGS registry. format_messages_for_prompt() and
    # format_messages_with_context() operate entirely on in-memory dicts.
    # No file I/O. No pipeline imports.
    "phase_0_prep/prompts.py": {
        "reads": [],
        "writes": [],
        "imports_from": [],
    },
}
