"""
tools/_io_tools.py — File I/O catalog for tools/ and config.py
Fresh recount: 2026-02-25. Every entry derived from reading the full source of
each file. No reference to any prior manifest.

Methodology: read every qualifying .py file in full and recorded every
open(), json.load(), json.loads(), read_text(), write_text(), json.dump(),
Path.glob(), Path.rglob(), load_json(), save_json(), Workbook.save(),
shutil.copy2(), and FileHandler instantiation found in the source.

Files cataloged (24 qualifying files):
  config.py
  tools/add_data_trace_sheets.py
  tools/analyze_data_flow.py
  tools/batch_phase3a.py
  tools/batch_runner.py
  tools/collect_visualizations.py
  tools/completeness_scanner.py
  tools/data_lifecycle.py
  tools/extract_dashboard_data.py
  tools/file_lock.py
  tools/generate_pipeline_canvas_data.py
  tools/generate_pipeline_excel.py
  tools/generate_schematic.py
  tools/hyperdoc_comparison.py
  tools/json_io.py
  tools/log_config.py
  tools/normalize_agent_output.py
  tools/pipeline_health_check.py
  tools/pipeline_status.py
  tools/run_pipeline.py
  tools/schema_contracts.py
  tools/schema_normalizer.py
  tools/schema_validator.py
  tools/verify_data_locations.py

Excluded per instructions:
  __init__.py
  __pycache__/
  tools/idea_graph_explorer/  (entire subdir)
  tools/system_file_report/   (entire subdir)
  tools/_io_*.py files themselves

Path notation:
  {session}/      = per-session dir (output/session_{id}/ or
                    ~/PERMANENT_HYPERDOCS/sessions/session_{id}/)
  {PERM}/         = ~/PERMANENT_HYPERDOCS/
  {INDEXES_DIR}/  = ~/PERMANENT_HYPERDOCS/indexes/
  {OUTPUT}/       = {repo}/output/
  {REPO}/         = hyperdocs_3 repo root
  {HOME}/         = ~/

Generic utilities (file_lock.py, json_io.py, log_config.py) take all
paths from callers at runtime — their read/write lists are empty.
"""

TOOLS_IO = {

    # ── config.py ─────────────────────────────────────────────────
    # No file I/O of its own; defines path constants used by importers.
    # _find_jsonl() performs glob searches to locate session JSONL files.
    "config.py": {
        "reads": [
            # _find_jsonl: directory.glob("{session_id}*.jsonl")
            "~/.claude/projects/{project_id}/{session_id}*.jsonl",
            "~/PERMANENT_CHAT_HISTORY/sessions/{session_id}*.jsonl",
        ],
        "writes": [],
        "imports_from": [],
    },

    # ── tools/json_io.py ──────────────────────────────────────────
    # Generic utility — load_json(path) and save_json(path, data).
    # All paths supplied by callers at runtime.
    "tools/json_io.py": {
        "reads": [],    # paths from callers
        "writes": [],   # paths from callers
        "imports_from": [],
    },

    # ── tools/log_config.py ───────────────────────────────────────
    # Generic utility — get_logger() and setup_pipeline_logging().
    # setup_pipeline_logging opens {log_dir}/pipeline_run.log for append;
    # log_dir is supplied by the caller.
    "tools/log_config.py": {
        "reads": [],
        "writes": [],   # {log_dir}/pipeline_run.log — path from caller
        "imports_from": [],
    },

    # ── tools/file_lock.py ────────────────────────────────────────
    # Generic utility — atomic_json_write(filepath, data) and
    # locked_json_read(filepath). All paths supplied by callers.
    "tools/file_lock.py": {
        "reads": [],    # paths from callers
        "writes": [],   # paths from callers
        "imports_from": [],
    },

    # ── tools/run_pipeline.py ─────────────────────────────────────
    # Orchestrates pipeline phases. Calls phase scripts via subprocess.
    # Directly imports backfill_phase2 and writes Phase 2 outputs in-process.
    # validate_phase_output reads session JSON files to check schema keys.
    # setup_pipeline_logging writes pipeline_run.log.
    "tools/run_pipeline.py": {
        "reads": [
            # validate_phase_output + phase_already_complete: existence + json.loads
            "output/session_{id}/enriched_session.json",
            "output/session_{id}/session_metadata.json",
            "output/session_{id}/thread_extractions.json",
            "output/session_{id}/geological_notes.json",
            "output/session_{id}/semantic_primitives.json",
            "output/session_{id}/explorer_notes.json",
            "output/session_{id}/idea_graph.json",
            "output/session_{id}/synthesis.json",
            "output/session_{id}/grounded_markers.json",
            "output/session_{id}/file_dossiers.json",
            "output/session_{id}/claude_md_analysis.json",
            "output/session_{id}/opus_classifications.json",
        ],
        "writes": [
            # run_phase_2: open(..., 'w') -> json.dump for 3 files
            "output/session_{id}/idea_graph.json",
            "output/session_{id}/synthesis.json",
            "output/session_{id}/grounded_markers.json",
            # setup_pipeline_logging: FileHandler writes structured log
            "output/session_{id}/pipeline_run.log",
        ],
        "imports_from": [
            "tools.log_config",
            "phase_2_synthesis.backfill_phase2",  # dynamic import in run_phase_2
        ],
    },

    # ── tools/pipeline_status.py ──────────────────────────────────
    # Read-only observability report. Reads session JSON files (existence +
    # schema_version check), pipeline_run.log files, and checkpoint.
    "tools/pipeline_status.py": {
        "reads": [
            # scan_sessions: d.glob("*.json"), then (d/f).read_text() -> json.loads
            "~/PERMANENT_HYPERDOCS/sessions/session_*/*.json",
            # scan_logs: log_file.read_text() per session dir in OUTPUT_DIR and SESSIONS_STORE_DIR
            "output/session_*/pipeline_run.log",
            "~/PERMANENT_HYPERDOCS/sessions/session_*/pipeline_run.log",
            # scan_checkpoints: cp_file.read_text()
            "~/PERMANENT_HYPERDOCS/indexes/batch_runner_checkpoint.json",
        ],
        "writes": [],
        "imports_from": [
            "config",           # SESSIONS_STORE_DIR, INDEXES_DIR, OUTPUT_DIR
            "tools.log_config",
        ],
    },

    # ── tools/batch_runner.py ─────────────────────────────────────
    # Checkpoint-based batch runner. Reads checkpoint and discovers sessions
    # by scanning SESSIONS_STORE_DIR. Delegates actual pipeline work to
    # tools/run_pipeline.py via subprocess.
    "tools/batch_runner.py": {
        "reads": [
            # load_checkpoint: CHECKPOINT_FILE.read_text() -> json.loads
            "~/PERMANENT_HYPERDOCS/indexes/batch_runner_checkpoint.json",
            # discover_sessions: d.glob("*.json") to confirm session has data
            "~/PERMANENT_HYPERDOCS/sessions/session_*/*.json",
        ],
        "writes": [
            # save_checkpoint: atomic_json_write or open(..., 'w') -> json.dump
            "~/PERMANENT_HYPERDOCS/indexes/batch_runner_checkpoint.json",
        ],
        "imports_from": [
            "config",           # SESSIONS_STORE_DIR, INDEXES_DIR
            "tools.log_config",
            "tools.file_lock",  # atomic_json_write (conditional import)
        ],
    },

    # ── tools/batch_phase3a.py ────────────────────────────────────
    # Finds sessions eligible for Phase 3a (have Phase 2 output, no
    # file_evidence/ dir) and runs collect_file_evidence.py via subprocess.
    # No direct JSON I/O — delegates to subprocess entirely.
    "tools/batch_phase3a.py": {
        "reads": [
            # find_eligible_sessions: existence checks on Phase 2 prerequisite files
            "~/PERMANENT_HYPERDOCS/sessions/session_*/session_metadata.json",
            "~/PERMANENT_HYPERDOCS/sessions/session_*/thread_extractions.json",
            "~/PERMANENT_HYPERDOCS/sessions/session_*/idea_graph.json",
            "~/PERMANENT_HYPERDOCS/sessions/session_*/grounded_markers.json",
            # run_phase3a: evidence_dir.glob("*_evidence.json") — count after subprocess
            "output/session_{id}/file_evidence/*_evidence.json",
        ],
        "writes": [],   # subprocess (collect_file_evidence.py) does all writes
        "imports_from": [
            "tools.log_config",
        ],
    },

    # ── tools/schema_contracts.py ─────────────────────────────────
    # Read-only validator. Opens session JSON files, checks required keys
    # and types against CONTRACTS dict. No writes.
    "tools/schema_contracts.py": {
        "reads": [
            # validate_file: open(filepath) -> json.load(f)
            "{session}/enriched_session.json",
            "{session}/session_metadata.json",
            "{session}/thread_extractions.json",
            "{session}/geological_notes.json",
            "{session}/semantic_primitives.json",
            "{session}/explorer_notes.json",
            "{session}/idea_graph.json",
            "{session}/synthesis.json",
            "{session}/grounded_markers.json",
            "{session}/file_dossiers.json",
            "{session}/claude_md_analysis.json",
        ],
        "writes": [],
        "imports_from": [
            "config",   # SESSIONS_STORE_DIR (in main())
        ],
    },

    # ── tools/extract_dashboard_data.py ───────────────────────────
    # BASE = Path(__file__).parent (script must be placed alongside the
    # hyperdocs/ dir and session_* dirs it reads). Reads all *_hyperdoc.json
    # files and session directories; writes dashboard_data.json.
    "tools/extract_dashboard_data.py": {
        "reads": [
            # extract_file_data: HYPERDOCS.glob("*_hyperdoc.json") -> f.read_text()
            "{BASE}/hyperdocs/*_hyperdoc.json",
            # extract_session_data: (sd / "session_metadata.json").read_text()
            "{BASE}/session_*/session_metadata.json",
            # existence checks for 11 phase output files
            "{BASE}/session_*/enriched_session.json",
            "{BASE}/session_*/thread_extractions.json",
            "{BASE}/session_*/geological_notes.json",
            "{BASE}/session_*/semantic_primitives.json",
            "{BASE}/session_*/explorer_notes.json",
            "{BASE}/session_*/idea_graph.json",
            "{BASE}/session_*/synthesis.json",
            "{BASE}/session_*/grounded_markers.json",
            "{BASE}/session_*/file_dossiers.json",
            "{BASE}/session_*/claude_md_analysis.json",
            # extract_idea_graphs: (sd / "idea_graph.json").read_text()
            # compute_aggregates: (BASE / "enhanced_files").glob("*.py") for count
            "{BASE}/enhanced_files/*.py",
        ],
        "writes": [
            # main: out_path.write_text(json.dumps(dashboard_data))
            "{BASE}/dashboard_data.json",
        ],
        "imports_from": [
            "tools.log_config",
        ],
    },

    # ── tools/hyperdoc_comparison.py ──────────────────────────────
    # Reads a .py source file (with or without @ctx markers), calls Opus
    # API twice, writes HTML comparison and raw JSON responses.
    # Also reads .env for ANTHROPIC_API_KEY if present.
    "tools/hyperdoc_comparison.py": {
        "reads": [
            # ENV_FILE.read_text() — optional API key source
            ".env",
            # run_comparison: filepath.read_text() — target .py file (CLI arg or --all list)
            # --all mode reads these 5 specific files:
            "config.py",
            "phase_1_extraction/interactive_batch_runner.py",
            "phase_0_prep/enrich_session.py",
            "phase_3_hyperdoc_writing/generate_viewer.py",
            "phase_0_prep/geological_reader.py",
        ],
        "writes": [
            # run_comparison: out_path.write_text(html)
            "output/comparison_{stem}.html",
            # run_comparison: raw_path.write_text(json.dumps(...))
            "output/comparison_{stem}.json",
        ],
        "imports_from": [
            "tools.log_config",
        ],
    },

    # ── tools/generate_pipeline_excel.py ──────────────────────────
    # Reads session JSON files from PERM_SESSIONS and OUTPUT_DIR.
    # Reads cross_session_file_index.json from INDEXES_DIR.
    # Writes pipeline_complete_anatomy.xlsx via Workbook.save().
    "tools/generate_pipeline_excel.py": {
        "reads": [
            # Per-session JSON files (both PERM_SESSIONS and OUTPUT_DIR dirs scanned)
            "{session}/enriched_session.json",
            "{session}/session_metadata.json",
            "{session}/tier4_priority_messages.json",
            "{session}/safe_tier4.json",
            "{session}/safe_condensed.json",
            "{session}/thread_extractions.json",
            "{session}/geological_notes.json",
            "{session}/semantic_primitives.json",
            "{session}/explorer_notes.json",
            "{session}/idea_graph.json",
            "{session}/synthesis.json",
            "{session}/grounded_markers.json",
            "{session}/file_dossiers.json",
            "{session}/claude_md_analysis.json",
            # Evidence files glob
            "{session}/file_evidence/*_evidence.json",
            # HTML viewer existence check
            "{session}/*viewer*.html",
            # Cross-session index
            "~/PERMANENT_HYPERDOCS/indexes/cross_session_file_index.json",
            "output/cross_session_file_index.json",
        ],
        "writes": [
            # main: wb.save(out_path)
            "experiment/feedback_loop/output/pipeline_complete_anatomy.xlsx",
        ],
        "imports_from": [
            "tools.log_config",
            "tools.json_io",
        ],
    },

    # ── tools/add_data_trace_sheets.py ────────────────────────────
    # Loads existing pipeline Excel workbook, appends a live-data trace
    # sheet showing actual data at every pipeline stage, saves it back.
    # Reads session data from hardcoded session 0012ebed in PERM and OUTPUT.
    "tools/add_data_trace_sheets.py": {
        "reads": [
            # main: openpyxl.load_workbook(xlsx_path)
            "experiment/feedback_loop/output/pipeline_complete_anatomy.xlsx",
            # build_sheet_6: load_safe on session_0012ebed — tries PERM first, then local OUTPUT
            "~/PERMANENT_HYPERDOCS/sessions/session_0012ebed/enriched_session.json",
            "output/session_0012ebed/enriched_session.json",
            "~/PERMANENT_HYPERDOCS/sessions/session_0012ebed/thread_extractions.json",
            "output/session_0012ebed/thread_extractions.json",
            "~/PERMANENT_HYPERDOCS/sessions/session_0012ebed/semantic_primitives.json",
            "~/PERMANENT_HYPERDOCS/sessions/session_0012ebed/geological_notes.json",
            "~/PERMANENT_HYPERDOCS/sessions/session_0012ebed/idea_graph.json",
            "output/session_0012ebed/idea_graph.json",
            "~/PERMANENT_HYPERDOCS/sessions/session_0012ebed/synthesis.json",
            "output/session_0012ebed/synthesis.json",
            "~/PERMANENT_HYPERDOCS/sessions/session_0012ebed/grounded_markers.json",
            "output/session_0012ebed/grounded_markers.json",
            "~/PERMANENT_HYPERDOCS/sessions/session_0012ebed/file_dossiers.json",
            "output/session_0012ebed/file_dossiers.json",
            # Per-file evidence for first file mentioned in msg 30
            "output/session_0012ebed/file_evidence/{safe_name}_evidence.json",
            # Phase 4a cross-session index
            "output/cross_session_file_index.json",
        ],
        "writes": [
            # main: wb.save(xlsx_path)
            "experiment/feedback_loop/output/pipeline_complete_anatomy.xlsx",
        ],
        "imports_from": [
            "tools.log_config",
            "tools.json_io",
        ],
    },

    # ── tools/analyze_data_flow.py ────────────────────────────────
    # Walks the entire repo, reads every .py source file to extract I/O
    # patterns via regex + AST, then writes positioning_analysis.json.
    "tools/analyze_data_flow.py": {
        "reads": [
            # discover_python_files + extract_io_from_source: filepath.read_text()
            "{REPO}/**/*.py",
        ],
        "writes": [
            # analyze: open(OUTPUT_FILE, 'w') -> json.dump (OUTPUT_FILE = REPO root)
            "positioning_analysis.json",
        ],
        "imports_from": [
            "tools.log_config",
        ],
    },

    # ── tools/data_lifecycle.py ───────────────────────────────────
    # Read-only scanner. Reports backup dirs, orphan files, large files,
    # empty sessions, stale lock files. Never writes anything.
    "tools/data_lifecycle.py": {
        "reads": [
            # scan_backups: backup_dir.rglob("*")
            "~/PERMANENT_HYPERDOCS/sessions/session_*/backups/*",
            # scan_orphan_files: d.glob("*.json")
            "~/PERMANENT_HYPERDOCS/sessions/session_*/*.json",
            # scan_large_files: STORE_DIR.rglob("*.json")
            "~/PERMANENT_HYPERDOCS/**/*.json",
            # scan_lock_files: STORE_DIR.rglob("*.lock")
            "~/PERMANENT_HYPERDOCS/**/*.lock",
        ],
        "writes": [],
        "imports_from": [
            "config",           # SESSIONS_STORE_DIR, INDEXES_DIR, STORE_DIR
            "tools.log_config",
        ],
    },

    # ── tools/verify_data_locations.py ────────────────────────────
    # Read-only consistency check. Counts .json files in session dirs
    # across both output/ and PERMANENT_HYPERDOCS/sessions/. No writes.
    "tools/verify_data_locations.py": {
        "reads": [
            # get_session_dirs: base.iterdir() -> f.suffix == ".json" count
            "output/session_*/*.json",
            "~/PERMANENT_HYPERDOCS/sessions/session_*/*.json",
        ],
        "writes": [],
        "imports_from": [
            "config",           # OUTPUT_DIR, SESSIONS_STORE_DIR
            "tools.log_config",
        ],
    },

    # ── tools/pipeline_health_check.py ────────────────────────────
    # Runs 10 health check types. Reads session JSON files, all .py files
    # in the repo (syntax check + runtime import), and hyperdoc JSONs.
    # Writes health_check_report.json.
    "tools/pipeline_health_check.py": {
        "reads": [
            # check_schema_compatibility + check_end_to_end + check_contracts:
            # fpath.read_text() -> json.loads on all contracted session files
            "{session}/session_metadata.json",
            "{session}/enriched_session.json",
            "{session}/thread_extractions.json",
            "{session}/geological_notes.json",
            "{session}/semantic_primitives.json",
            "{session}/explorer_notes.json",
            "{session}/idea_graph.json",
            "{session}/synthesis.json",
            "{session}/grounded_markers.json",
            "{session}/file_dossiers.json",
            "{session}/claude_md_analysis.json",
            # check_imports + check_paths: REPO.rglob("*.py") -> read_text() + ast.parse
            "{REPO}/**/*.py",
            # check_backward_compat: 10 sampled sessions from PERMANENT_HYPERDOCS
            "~/PERMANENT_HYPERDOCS/sessions/session_*/thread_extractions.json",
            "~/PERMANENT_HYPERDOCS/sessions/session_*/grounded_markers.json",
            "~/PERMANENT_HYPERDOCS/sessions/session_*/semantic_primitives.json",
            # check_phase3_4_runtime: reads *_hyperdoc.json from PERMANENT_HYPERDOCS
            "~/PERMANENT_HYPERDOCS/hyperdocs/*_hyperdoc.json",
            # Phase 4 syntax check: ast.parse on these scripts
            "phase_4_insertion/insert_hyperdocs.py",
            "phase_4_insertion/insert_hyperdocs_3part.py",
            "phase_4_insertion/insert_from_json.py",
            "phase_4_insertion/hyperdoc_layers.py",
            "phase_4_insertion/init_hyperdoc_store.py",
        ],
        "writes": [
            # run_all: open(report_path, 'w') -> json.dump
            "output/health_check_report.json",
        ],
        "imports_from": [
            "tools.log_config",
        ],
    },

    # ── tools/generate_schematic.py ───────────────────────────────
    # Pure data + HTML generation. VERIFIED_IO dict is hardcoded inline.
    # No file reads. Writes HTML schematic to repo root (or --output path).
    "tools/generate_schematic.py": {
        "reads": [],
        "writes": [
            # main: out_path.write_text(html)
            "hyperdocs-pipeline-schematic.html",
        ],
        "imports_from": [],
    },

    # ── tools/collect_visualizations.py ───────────────────────────
    # Collects HTML files from 7 source glob patterns, deduplicates by
    # mtime, copies to wrecktangle viz-gallery, writes manifest.json.
    "tools/collect_visualizations.py": {
        "reads": [
            # collect_files: glob.glob on SOURCES list
            "~/.agent/diagrams/*.html",
            "~/Hyperdocs/*.html",
            "~/Hyperdocs/completed/*.html",
            "~/Hyperdocs/output/*.html",
            "~/Hyperdocs/tools/**/*.html",
            "~/PERMANENT_HYPERDOCS/genealogy_dashboard.html",
            "~/PERMANENT_HYPERDOCS/sessions/*/pipeline_viewer.html",
        ],
        "writes": [
            # main: shutil.copy2(src_path, dest_path) per file
            "~/wrecktangle-site/public/viz-gallery/*.html",
            # main: open(manifest_path, 'w') -> json.dump
            "~/wrecktangle-site/public/viz-gallery/manifest.json",
        ],
        "imports_from": [],
    },

    # ── tools/generate_pipeline_canvas_data.py ────────────────────
    # Reads all .py source files in repo for source_code embedding and
    # highlight line extraction. Imports hand-curated I/O manifests from
    # _io_*.py files. Writes pipeline-data.json and pipeline-data.js.
    "tools/generate_pipeline_canvas_data.py": {
        "reads": [
            # discover_py_files: os.walk -> filepath.read_text() for each .py
            "{REPO}/config.py",
            "{REPO}/phase_*/**/*.py",
            "{REPO}/tools/**/*.py",
        ],
        "writes": [
            # generate: open(OUTPUT_FILE, 'w') -> f.write(json_str)
            "~/wrecktangle-site/public/pipeline-canvas/pipeline-data.json",
            # generate: open(OUTPUT_JS, 'w') -> f.write("window.PIPELINE_DATA = ...")
            "~/wrecktangle-site/public/pipeline-canvas/pipeline-data.js",
        ],
        "imports_from": [
            "tools.generate_schematic",   # PHASE_MAP, PHASE_LABELS, PIPELINE_SCRIPTS, OPTIONAL_SCRIPTS
            "tools.analyze_data_flow",    # OUTPUT_PHASE_MAP
            "tools._io_phase0",           # PHASE0_IO
            "tools._io_phase1_2",         # PHASE1_2_IO
            "tools._io_phase3_4",         # PHASE3_4_IO
            "tools._io_tools",            # TOOLS_IO (this file)
        ],
    },

    # ── tools/schema_normalizer.py ────────────────────────────────
    # Reads 9 agent-produced JSON files per session, normalizes each to
    # canonical schema using type-specific strategies, backs up originals,
    # atomically rewrites in-place, writes a normalization log.
    "tools/schema_normalizer.py": {
        "reads": [
            # normalize_file: open(filepath) -> json.load(f) for each of 9 types
            "{session}/thread_extractions.json",
            "{session}/geological_notes.json",
            "{session}/semantic_primitives.json",
            "{session}/explorer_notes.json",
            "{session}/idea_graph.json",
            "{session}/synthesis.json",
            "{session}/grounded_markers.json",
            "{session}/file_dossiers.json",
            "{session}/claude_md_analysis.json",
        ],
        "writes": [
            # normalize_file: tempfile -> json.dump -> os.replace (atomic)
            "{session}/thread_extractions.json",
            "{session}/geological_notes.json",
            "{session}/semantic_primitives.json",
            "{session}/explorer_notes.json",
            "{session}/idea_graph.json",
            "{session}/synthesis.json",
            "{session}/grounded_markers.json",
            "{session}/file_dossiers.json",
            "{session}/claude_md_analysis.json",
            # shutil.copy2 backup before first normalization
            "{session}/backups/{filename}",
            # main: open(log_path, 'w') -> json.dump
            "{INDEXES_DIR}/normalization_log.json",
        ],
        "imports_from": [
            "tools.log_config",
        ],
    },

    # ── tools/schema_validator.py ─────────────────────────────────
    # Checks session JSON files for canonical data keys. If invalid,
    # calls schema_normalizer.normalize_file() which writes in-place.
    "tools/schema_validator.py": {
        "reads": [
            # validate_file: open(filepath) -> json.load(f)
            "{session}/thread_extractions.json",
            "{session}/geological_notes.json",
            "{session}/semantic_primitives.json",
            "{session}/explorer_notes.json",
            "{session}/idea_graph.json",
            "{session}/synthesis.json",
            "{session}/grounded_markers.json",
            "{session}/file_dossiers.json",
            "{session}/claude_md_analysis.json",
        ],
        "writes": [
            # validate_and_normalize triggers normalize_file when keys missing
            # same 9 files normalized in-place via schema_normalizer
            "{session}/thread_extractions.json",
            "{session}/geological_notes.json",
            "{session}/semantic_primitives.json",
            "{session}/explorer_notes.json",
            "{session}/idea_graph.json",
            "{session}/synthesis.json",
            "{session}/grounded_markers.json",
            "{session}/file_dossiers.json",
            "{session}/claude_md_analysis.json",
            "{session}/backups/{filename}",   # backup created by normalize_file
        ],
        "imports_from": [
            "tools.schema_normalizer",  # NORMALIZERS, normalize_file
            "tools.log_config",
        ],
    },

    # ── tools/normalize_agent_output.py ───────────────────────────
    # Post-agent orchestrator: calls schema_normalizer.normalize_file()
    # then schema_validator.validate_file() for each of the 9 agent files.
    # Reads and conditionally rewrites all 9 session JSON files.
    "tools/normalize_agent_output.py": {
        "reads": [
            # normalize_session_output: open(filepath) -> json.load(f) for each existing file
            "{session}/thread_extractions.json",
            "{session}/geological_notes.json",
            "{session}/semantic_primitives.json",
            "{session}/explorer_notes.json",
            "{session}/idea_graph.json",
            "{session}/synthesis.json",
            "{session}/grounded_markers.json",
            "{session}/file_dossiers.json",
            "{session}/claude_md_analysis.json",
        ],
        "writes": [
            # normalize_file (via schema_normalizer): same 9 files normalized in-place
            "{session}/thread_extractions.json",
            "{session}/geological_notes.json",
            "{session}/semantic_primitives.json",
            "{session}/explorer_notes.json",
            "{session}/idea_graph.json",
            "{session}/synthesis.json",
            "{session}/grounded_markers.json",
            "{session}/file_dossiers.json",
            "{session}/claude_md_analysis.json",
            "{session}/backups/{filename}",   # shutil.copy2 backup
        ],
        "imports_from": [
            "tools.schema_normalizer",  # NORMALIZERS, normalize_file
            "tools.schema_validator",   # CANONICAL_DATA_KEYS, validate_file
            "tools.log_config",
        ],
    },

    # ── tools/completeness_scanner.py ─────────────────────────────
    # Scans every session directory in PERMANENT_HYPERDOCS/sessions/ and
    # does field-level completeness checks on all 20 expected pipeline files.
    # Writes completeness_report.json.
    "tools/completeness_scanner.py": {
        "reads": [
            # scan_session: open(filepath) -> json.load(f) for each expected file
            "{session}/enriched_session.json",
            "{session}/session_metadata.json",
            "{session}/safe_condensed.json",
            "{session}/safe_tier4.json",
            "{session}/tier2plus_messages.json",
            "{session}/tier4_priority_messages.json",
            "{session}/user_messages_tier2plus.json",
            "{session}/conversation_condensed.json",
            "{session}/emergency_contexts.json",
            "{session}/thread_extractions.json",
            "{session}/geological_notes.json",
            "{session}/semantic_primitives.json",
            "{session}/explorer_notes.json",
            "{session}/idea_graph.json",
            "{session}/synthesis.json",
            "{session}/grounded_markers.json",
            "{session}/file_dossiers.json",
            "{session}/claude_md_analysis.json",
            "{session}/ground_truth_verification.json",
            "{session}/file_genealogy.json",
        ],
        "writes": [
            # main: open(output_path, 'w') -> json.dump
            "{INDEXES_DIR}/completeness_report.json",
        ],
        "imports_from": [
            "tools.log_config",
        ],
    },
}
