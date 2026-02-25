"""
I/O catalog for tools/*.py and config.py.

Generated 2026-02-25 by reading every file line-by-line.
Every open(), json.load(), read_text(), write_text(), json.dump(),
Path.glob(), Path.rglob(), load_json(), save_json(), Workbook.save()
call is cataloged here. Glob patterns included as-is.

Files with no data I/O (pure utility) have empty lists.
"""

TOOLS_IO = {
    # ── config.py ─────────────────────────────────────────────────
    "config.py": {
        "reads": [
            # _find_jsonl: directory.glob("{session_id}*.jsonl")
            "{session_id}*.jsonl",
            "*_{session_id}*.jsonl",
        ],
        "writes": [],
        "imports_from": [],
    },

    # ── tools/json_io.py ──────────────────────────────────────────
    "tools/json_io.py": {
        "reads": [
            # load_json(path): open(path, 'r') -> json.load(f)
            # (arbitrary .json path passed by caller)
        ],
        "writes": [
            # save_json(path, data): open(path, 'w') -> json.dump(data, f)
            # (arbitrary .json path passed by caller)
        ],
        "imports_from": [],
    },

    # ── tools/log_config.py ───────────────────────────────────────
    "tools/log_config.py": {
        "reads": [],
        "writes": [
            # setup_pipeline_logging: FileHandler(log_dir / "pipeline_run.log", mode="a")
            "{log_dir}/pipeline_run.log",
        ],
        "imports_from": [],
    },

    # ── tools/file_lock.py ────────────────────────────────────────
    "tools/file_lock.py": {
        "reads": [
            # locked_json_read(filepath): open(filepath) -> json.load(f)
            # (arbitrary filepath passed by caller)
        ],
        "writes": [
            # atomic_json_write(filepath, data): tempfile -> json.dump -> os.replace
            # (arbitrary filepath passed by caller)
        ],
        "imports_from": [],
    },

    # ── tools/run_pipeline.py ─────────────────────────────────────
    "tools/run_pipeline.py": {
        "reads": [
            # validate_phase_output: path.read_text() -> json.loads()
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
            # run_phase_2: read_json() for 5 files
            # (via backfill_phase2.read_json)
        ],
        "writes": [
            # run_phase_2: open(ig_path, 'w') -> json.dump
            "output/session_{id}/idea_graph.json",
            "output/session_{id}/synthesis.json",
            "output/session_{id}/grounded_markers.json",
        ],
        "imports_from": [
            "tools.log_config",
            # dynamic: from backfill_phase2 import ...
        ],
    },

    # ── tools/pipeline_status.py ──────────────────────────────────
    "tools/pipeline_status.py": {
        "reads": [
            # scan_sessions: d.glob("*.json"), read_text() -> json.loads
            "~/PERMANENT_HYPERDOCS/sessions/session_*/enriched_session.json",
            "~/PERMANENT_HYPERDOCS/sessions/session_*/session_metadata.json",
            "~/PERMANENT_HYPERDOCS/sessions/session_*/thread_extractions.json",
            "~/PERMANENT_HYPERDOCS/sessions/session_*/geological_notes.json",
            "~/PERMANENT_HYPERDOCS/sessions/session_*/semantic_primitives.json",
            "~/PERMANENT_HYPERDOCS/sessions/session_*/explorer_notes.json",
            "~/PERMANENT_HYPERDOCS/sessions/session_*/idea_graph.json",
            "~/PERMANENT_HYPERDOCS/sessions/session_*/synthesis.json",
            "~/PERMANENT_HYPERDOCS/sessions/session_*/grounded_markers.json",
            "~/PERMANENT_HYPERDOCS/sessions/session_*/file_dossiers.json",
            "~/PERMANENT_HYPERDOCS/sessions/session_*/claude_md_analysis.json",
            # scan_sessions: d.glob("*.json") then (d / f).read_text() for schema check
            "~/PERMANENT_HYPERDOCS/sessions/session_*/*.json",
            # scan_logs: log_file.read_text() per session dir
            "output/session_*/pipeline_run.log",
            "~/PERMANENT_HYPERDOCS/sessions/session_*/pipeline_run.log",
            # scan_checkpoints
            "~/PERMANENT_HYPERDOCS/indexes/batch_runner_checkpoint.json",
        ],
        "writes": [],
        "imports_from": [
            "config",
            "tools.log_config",
        ],
    },

    # ── tools/batch_runner.py ─────────────────────────────────────
    "tools/batch_runner.py": {
        "reads": [
            # load_checkpoint: CHECKPOINT_FILE.read_text() -> json.loads
            "~/PERMANENT_HYPERDOCS/indexes/batch_runner_checkpoint.json",
            # discover_sessions: d.glob("*.json") on SESSIONS_STORE_DIR
            "~/PERMANENT_HYPERDOCS/sessions/session_*/*.json",
        ],
        "writes": [
            # save_checkpoint: atomic_json_write or open(..., 'w') -> json.dump
            "~/PERMANENT_HYPERDOCS/indexes/batch_runner_checkpoint.json",
        ],
        "imports_from": [
            "config",
            "tools.log_config",
            "tools.file_lock",
        ],
    },

    # ── tools/batch_phase3a.py ────────────────────────────────────
    "tools/batch_phase3a.py": {
        "reads": [
            # find_eligible_sessions: checks existence of .json files + file_evidence dir
            "~/PERMANENT_HYPERDOCS/sessions/session_*/session_metadata.json",
            "~/PERMANENT_HYPERDOCS/sessions/session_*/thread_extractions.json",
            "~/PERMANENT_HYPERDOCS/sessions/session_*/idea_graph.json",
            "~/PERMANENT_HYPERDOCS/sessions/session_*/grounded_markers.json",
            # run_phase3a: evidence_dir.glob("*_evidence.json")
            "output/session_{id}/file_evidence/*_evidence.json",
        ],
        "writes": [],
        "imports_from": [
            "tools.log_config",
        ],
    },

    # ── tools/schema_contracts.py ─────────────────────────────────
    "tools/schema_contracts.py": {
        "reads": [
            # validate_file: open(filepath) -> json.load(f)
            # All contracted session JSON files:
            "enriched_session.json",
            "session_metadata.json",
            "thread_extractions.json",
            "geological_notes.json",
            "semantic_primitives.json",
            "explorer_notes.json",
            "idea_graph.json",
            "synthesis.json",
            "grounded_markers.json",
            "file_dossiers.json",
            "claude_md_analysis.json",
        ],
        "writes": [],
        "imports_from": [
            "config",
        ],
    },

    # ── tools/extract_viz_data.py ─────────────────────────────────
    "tools/extract_viz_data.py": {
        "reads": [
            # extract_file_data: HYPERDOCS.glob("*_hyperdoc.json") -> f.read_text() -> json.loads
            "tools/hyperdocs/*_hyperdoc.json",
            # extract_session_data: session dirs -> (sd / "session_metadata.json").read_text() -> json.loads
            "tools/session_*/session_metadata.json",
            # checks existence of 11 phase output files per session dir
            "tools/session_*/enriched_session.json",
            "tools/session_*/thread_extractions.json",
            "tools/session_*/geological_notes.json",
            "tools/session_*/semantic_primitives.json",
            "tools/session_*/explorer_notes.json",
            "tools/session_*/idea_graph.json",
            "tools/session_*/synthesis.json",
            "tools/session_*/grounded_markers.json",
            "tools/session_*/file_dossiers.json",
            "tools/session_*/claude_md_analysis.json",
            # extract_idea_graphs: (sd / "idea_graph.json").read_text() -> json.loads
            # compute_aggregates: (BASE / "enhanced_files").glob("*.py") for count
            "tools/enhanced_files/*.py",
        ],
        "writes": [
            # main: out_path.write_text(json.dumps(dashboard_data))
            "tools/dashboard_data.json",
        ],
        "imports_from": [],
    },

    # ── tools/extract_dashboard_data.py ───────────────────────────
    "tools/extract_dashboard_data.py": {
        "reads": [
            # extract_file_data: HYPERDOCS.glob("*_hyperdoc.json") -> f.read_text() -> json.loads
            "tools/hyperdocs/*_hyperdoc.json",
            # extract_session_data: session dirs -> (sd / "session_metadata.json").read_text()
            "tools/session_*/session_metadata.json",
            # checks existence of 11 phase output files per session dir
            "tools/session_*/enriched_session.json",
            "tools/session_*/thread_extractions.json",
            "tools/session_*/geological_notes.json",
            "tools/session_*/semantic_primitives.json",
            "tools/session_*/explorer_notes.json",
            "tools/session_*/idea_graph.json",
            "tools/session_*/synthesis.json",
            "tools/session_*/grounded_markers.json",
            "tools/session_*/file_dossiers.json",
            "tools/session_*/claude_md_analysis.json",
            # extract_idea_graphs: (sd / "idea_graph.json").read_text()
            # compute_aggregates: (BASE / "enhanced_files").glob("*.py") for count
            "tools/enhanced_files/*.py",
        ],
        "writes": [
            # main: out_path.write_text(json.dumps(dashboard_data))
            "tools/dashboard_data.json",
        ],
        "imports_from": [
            "tools.log_config",
        ],
    },

    # ── tools/hyperdoc_comparison.py ──────────────────────────────
    "tools/hyperdoc_comparison.py": {
        "reads": [
            # .env file: ENV_FILE.read_text()
            ".env",
            # run_comparison: filepath.read_text() — arbitrary .py file passed as arg
            # --all mode reads 5 specific files:
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
    "tools/generate_pipeline_excel.py": {
        "reads": [
            # build_sheet_2_file_schemas: load_json_safe on 12 session JSON files
            "enriched_session.json",
            "session_metadata.json",
            "tier4_priority_messages.json",
            "safe_tier4.json",
            "safe_condensed.json",
            "thread_extractions.json",
            "geological_notes.json",
            "semantic_primitives.json",
            "explorer_notes.json",
            "idea_graph.json",
            "synthesis.json",
            "grounded_markers.json",
            "file_dossiers.json",
            "claude_md_analysis.json",
            # build_sheet_2: ev_dir.glob("*_evidence.json")
            "file_evidence/*_evidence.json",
            # build_sheet_3_session_inventory: scans PERM_SESSIONS and OUTPUT_DIR session dirs
            # checks existence of 16+ files per session, plus:
            "session_*/file_evidence/*_evidence.json",
            "session_*/*viewer*.html",
            # build_sheet_4: cross_session_file_index.json
            "output/cross_session_file_index.json",
            "~/PERMANENT_HYPERDOCS/indexes/cross_session_file_index.json",
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
    "tools/add_data_trace_sheets.py": {
        "reads": [
            # main: openpyxl.load_workbook(xlsx_path)
            "experiment/feedback_loop/output/pipeline_complete_anatomy.xlsx",
            # build_sheet_6: load_safe on session_0012ebed data files
            "~/PERMANENT_HYPERDOCS/sessions/session_0012ebed/enriched_session.json",
            "output/session_0012ebed/enriched_session.json",
            "~/PERMANENT_HYPERDOCS/sessions/session_0012ebed/thread_extractions.json",
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
            # Phase 4a cross-session index
            "output/cross_session_file_index.json",
            # file_evidence: per-file evidence JSON
            "output/session_0012ebed/file_evidence/{safe_name}_evidence.json",
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

    # ── tools/positioning_analyzer.py ─────────────────────────────
    "tools/positioning_analyzer.py": {
        "reads": [
            # discover_python_files: os.walk(REPO) scanning all .py files
            # extract_io_from_source: filepath.read_text() for each .py file
            "**/*.py",
        ],
        "writes": [
            # analyze: open(OUTPUT_FILE, 'w') -> json.dump
            "positioning_analysis.json",
        ],
        "imports_from": [],
    },

    # ── tools/analyze_data_flow.py ────────────────────────────────
    "tools/analyze_data_flow.py": {
        "reads": [
            # discover_python_files: os.walk(REPO) scanning all .py files
            # extract_io_from_source: filepath.read_text() for each .py file
            "**/*.py",
        ],
        "writes": [
            # analyze: open(OUTPUT_FILE, 'w') -> json.dump
            "positioning_analysis.json",
        ],
        "imports_from": [
            "tools.log_config",
        ],
    },

    # ── tools/data_lifecycle.py ───────────────────────────────────
    "tools/data_lifecycle.py": {
        "reads": [
            # scan_backups: SESSIONS_STORE_DIR dirs -> backup_dir.rglob("*")
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
            "config",
            "tools.log_config",
        ],
    },

    # ── tools/verify_data_locations.py ────────────────────────────
    "tools/verify_data_locations.py": {
        "reads": [
            # get_session_dirs: base.iterdir() counting .json files
            "output/session_*/*.json",
            "~/PERMANENT_HYPERDOCS/sessions/session_*/*.json",
        ],
        "writes": [],
        "imports_from": [
            "config",
            "tools.log_config",
        ],
    },

    # ── tools/pipeline_health_check.py ────────────────────────────
    "tools/pipeline_health_check.py": {
        "reads": [
            # check_schema_compatibility: fpath.read_text() -> json.loads for each contracted file
            "session_metadata.json",
            "thread_extractions.json",
            "geological_notes.json",
            "semantic_primitives.json",
            "explorer_notes.json",
            "idea_graph.json",
            "synthesis.json",
            "grounded_markers.json",
            "file_dossiers.json",
            "claude_md_analysis.json",
            # check_data_volume: reads multiple session JSON files
            "enriched_session.json",
            # check_idempotency: ig_path.read_text()
            # check_imports: REPO.rglob("*.py") -> read_text() + ast.parse
            "**/*.py",
            # check_paths: REPO.rglob("*.py") -> read_text()
            # check_backward_compat: reads thread_extractions, grounded_markers, semantic_primitives
            # from 10 sampled PERMANENT_HYPERDOCS session dirs
            "~/PERMANENT_HYPERDOCS/sessions/session_*/thread_extractions.json",
            "~/PERMANENT_HYPERDOCS/sessions/session_*/grounded_markers.json",
            "~/PERMANENT_HYPERDOCS/sessions/session_*/semantic_primitives.json",
            # check_contracts: reads all contracted JSON files from session dir
            # check_phase3_4_runtime: reads *_hyperdoc.json from PERMANENT_HYPERDOCS
            "~/PERMANENT_HYPERDOCS/hyperdocs/*_hyperdoc.json",
            # Phase 4 syntax check: reads .py files from phase_4_insertion
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
    "tools/generate_schematic.py": {
        "reads": [],
        "writes": [
            # main: out_path.write_text(html)
            "hyperdocs-pipeline-schematic.html",
        ],
        "imports_from": [],
    },

    # ── tools/collect_visualizations.py ───────────────────────────
    "tools/collect_visualizations.py": {
        "reads": [
            # collect_files: glob.glob on 7 source patterns
            "~/.agent/diagrams/*.html",
            "~/Hyperdocs/*.html",
            "~/Hyperdocs/completed/*.html",
            "~/Hyperdocs/output/*.html",
            "~/Hyperdocs/tools/**/*.html",
            "~/PERMANENT_HYPERDOCS/genealogy_dashboard.html",
            "~/PERMANENT_HYPERDOCS/sessions/*/pipeline_viewer.html",
        ],
        "writes": [
            # main: shutil.copy2 to DEST, then open(manifest_path, 'w') -> json.dump
            "~/wrecktangle-site/public/viz-gallery/*.html",
            "~/wrecktangle-site/public/viz-gallery/manifest.json",
        ],
        "imports_from": [],
    },

    # ── tools/generate_pipeline_canvas_data.py ────────────────────
    "tools/generate_pipeline_canvas_data.py": {
        "reads": [
            # discover_py_files: os.walk scanning phase dirs, tools/, config.py
            # Each .py file: filepath.read_text()
            "phase_*/**/*.py",
            "tools/**/*.py",
            "config.py",
        ],
        "writes": [
            # generate: open(OUTPUT_FILE, 'w') -> f.write(json_str)
            "~/wrecktangle-site/public/pipeline-canvas/pipeline-data.json",
            # generate: open(OUTPUT_JS, 'w') -> f.write("window.PIPELINE_DATA = " + json_str)
            "~/wrecktangle-site/public/pipeline-canvas/pipeline-data.js",
        ],
        "imports_from": [
            "tools.generate_schematic",
            "tools.analyze_data_flow",
        ],
    },
}
