"""
Phase 3 / Phase 4 I/O Catalog
Fresh recount: 2026-02-25

Every .py file (excluding __init__.py, __pycache__) in:
  - phase_3_hyperdoc_writing/   (including evidence/ subdir)
  - phase_4a_aggregation/
  - phase_4_insertion/
  - phase_4_hyperdoc_writing/   (no .py files present)

Path tokens used in this catalog:
  {session_dir}     output/session_XXXX/
  {perm_dir}        ~/PERMANENT_HYPERDOCS/sessions/session_XXXX/
  {base_dir}        resolved at runtime: session output dir (--session) or script parent dir
  {hyperdocs_dir}   ~/PERMANENT_HYPERDOCS/hyperdocs/  (or HYPERDOCS_STORE_DIR env)
  {V5_SOURCE_DIR}   from config.V5_SOURCE_DIR or fallback to phase_0_prep/
  {safe_filename}   filepath with / . \\ space replaced by _
  {stem}            filename without .py extension

Key conventions:
  - collect_file_evidence.py searches [perm_dir, session_dir] in that order (PERM preferred)
  - evidence/base.py lazy-loads data via properties; all subclass reads flow through it
  - generate_dossiers.py, generate_viewer.py, write_more_hyperdocs.py resolve {base_dir}
    at import time using --session arg or env var; without --session they default to the
    script's own directory
  - insert_from_phase4b.py searches many candidate locations for source files (see entry)
"""

PHASE3_4_IO = {

    # =========================================================================
    # phase_3_hyperdoc_writing/collect_file_evidence.py
    # =========================================================================
    "phase_3_hyperdoc_writing/collect_file_evidence.py": {
        "READS": [
            # All 11 sources searched in [perm_dir, session_dir] order
            "{perm_dir}/session_metadata.json",
            "{session_dir}/session_metadata.json",
            "{perm_dir}/geological_notes.json",
            "{session_dir}/geological_notes.json",
            "{perm_dir}/semantic_primitives.json",
            "{session_dir}/semantic_primitives.json",
            "{perm_dir}/explorer_notes.json",
            "{session_dir}/explorer_notes.json",
            "{perm_dir}/file_genealogy.json",
            "{session_dir}/file_genealogy.json",
            "{perm_dir}/thread_extractions.json",
            "{session_dir}/thread_extractions.json",
            "{perm_dir}/idea_graph.json",
            "{session_dir}/idea_graph.json",
            "{perm_dir}/grounded_markers.json",
            "{session_dir}/grounded_markers.json",
            "{perm_dir}/synthesis.json",
            "{session_dir}/synthesis.json",
            "{perm_dir}/claude_md_analysis.json",
            "{session_dir}/claude_md_analysis.json",
            # file_dossiers.json explicitly searches [perm_dir, session_dir]
            "{perm_dir}/file_dossiers.json",
            "{session_dir}/file_dossiers.json",
        ],
        "WRITES": [
            # One JSON per file tracked in session_metadata (top_files / file_mention_counts)
            "{session_dir}/file_evidence/{safe_filename}_evidence.json",
        ],
        "IMPORTS_FROM": [
            "tools.json_io",
            "tools.log_config",
        ],
    },

    # =========================================================================
    # phase_3_hyperdoc_writing/evidence_resolver.py
    # =========================================================================
    "phase_3_hyperdoc_writing/evidence_resolver.py": {
        "READS": [
            # No direct file I/O. All reading is delegated to EvidenceRenderer
            # subclasses which are instantiated lazily via RENDERER_REGISTRY.
        ],
        "WRITES": [],
        "IMPORTS_FROM": [
            "tools.log_config",
            "phase_3_hyperdoc_writing.evidence",   # RENDERER_REGISTRY
        ],
    },

    # =========================================================================
    # phase_3_hyperdoc_writing/evidence/base.py
    # =========================================================================
    "phase_3_hyperdoc_writing/evidence/base.py": {
        "READS": [
            # Lazy-loaded on first property access. Search order: [perm_dir, session_dir]
            "{perm_dir}/enriched_session.json",
            "{session_dir}/enriched_session.json",
            "{perm_dir}/semantic_primitives.json",
            "{session_dir}/semantic_primitives.json",
            "{perm_dir}/idea_graph.json",
            "{session_dir}/idea_graph.json",
            "{perm_dir}/thread_extractions.json",
            "{session_dir}/thread_extractions.json",
            "{perm_dir}/geological_notes.json",
            "{session_dir}/geological_notes.json",
            "{perm_dir}/grounded_markers.json",
            "{session_dir}/grounded_markers.json",
            "{perm_dir}/file_dossiers.json",
            "{session_dir}/file_dossiers.json",
        ],
        "WRITES": [],
        "IMPORTS_FROM": [
            "tools.json_io",
            "tools.log_config",
        ],
    },

    # =========================================================================
    # phase_3_hyperdoc_writing/evidence/debug_sequence.py
    # =========================================================================
    "phase_3_hyperdoc_writing/evidence/debug_sequence.py": {
        "READS": [
            # Via inherited EvidenceRenderer.get_messages -> enriched_session property
            "{session_dir}/enriched_session.json",
        ],
        "WRITES": [],
        "IMPORTS_FROM": [
            "phase_3_hyperdoc_writing.evidence.base",
        ],
    },

    # =========================================================================
    # phase_3_hyperdoc_writing/evidence/decision_trace.py
    # =========================================================================
    "phase_3_hyperdoc_writing/evidence/decision_trace.py": {
        "READS": [
            # Via self.grounded_markers -> base._load("grounded_markers.json")
            "{session_dir}/grounded_markers.json",
            # Via self.idea_graph -> base._load("idea_graph.json")
            "{session_dir}/idea_graph.json",
        ],
        "WRITES": [],
        "IMPORTS_FROM": [
            "phase_3_hyperdoc_writing.evidence.base",
        ],
    },

    # =========================================================================
    # phase_3_hyperdoc_writing/evidence/emotional_arc.py
    # =========================================================================
    "phase_3_hyperdoc_writing/evidence/emotional_arc.py": {
        "READS": [
            # Via self.semantic_primitives -> base._load("semantic_primitives.json")
            "{session_dir}/semantic_primitives.json",
        ],
        "WRITES": [],
        "IMPORTS_FROM": [
            "phase_3_hyperdoc_writing.evidence.base",
        ],
    },

    # =========================================================================
    # phase_3_hyperdoc_writing/evidence/file_timeline.py
    # =========================================================================
    "phase_3_hyperdoc_writing/evidence/file_timeline.py": {
        "READS": [
            # Direct open for pre-computed evidence
            "{perm_dir}/file_evidence/{safe_filename}_evidence.json",
            "{session_dir}/file_evidence/{safe_filename}_evidence.json",
            # Via self.thread_extractions -> base._load("thread_extractions.json")
            "{session_dir}/thread_extractions.json",
            # Via self.get_message -> self.enriched_session
            "{session_dir}/enriched_session.json",
        ],
        "WRITES": [],
        "IMPORTS_FROM": [
            "phase_3_hyperdoc_writing.evidence.base",
        ],
    },

    # =========================================================================
    # phase_3_hyperdoc_writing/evidence/geological_event.py
    # =========================================================================
    "phase_3_hyperdoc_writing/evidence/geological_event.py": {
        "READS": [
            # Via self.geological_notes -> base._load("geological_notes.json")
            "{session_dir}/geological_notes.json",
            # Via self.get_message -> self.enriched_session
            "{session_dir}/enriched_session.json",
        ],
        "WRITES": [],
        "IMPORTS_FROM": [
            "phase_3_hyperdoc_writing.evidence.base",
        ],
    },

    # =========================================================================
    # phase_3_hyperdoc_writing/evidence/idea_transition.py
    # =========================================================================
    "phase_3_hyperdoc_writing/evidence/idea_transition.py": {
        "READS": [
            # Via self.idea_graph -> base._load("idea_graph.json")
            "{session_dir}/idea_graph.json",
        ],
        "WRITES": [],
        "IMPORTS_FROM": [
            "phase_3_hyperdoc_writing.evidence.base",
        ],
    },

    # =========================================================================
    # phase_3_hyperdoc_writing/evidence/reaction_log.py
    # =========================================================================
    "phase_3_hyperdoc_writing/evidence/reaction_log.py": {
        "READS": [
            # Via self.thread_extractions -> base._load("thread_extractions.json")
            "{session_dir}/thread_extractions.json",
            # Via self.get_message -> self.enriched_session
            "{session_dir}/enriched_session.json",
        ],
        "WRITES": [],
        "IMPORTS_FROM": [
            "phase_3_hyperdoc_writing.evidence.base",
        ],
    },

    # =========================================================================
    # phase_3_hyperdoc_writing/generate_dossiers.py
    # =========================================================================
    "phase_3_hyperdoc_writing/generate_dossiers.py": {
        "READS": [
            # All loaded from {base_dir}
            # (= session output dir with --session flag, else script's own directory)
            "{base_dir}/session_metadata.json",
            "{base_dir}/grounded_markers.json",
            "{base_dir}/idea_graph.json",
            "{base_dir}/thread_extractions.json",
            # If @evidence directives appear in story_arc / key_decisions text,
            # evidence_resolver -> EvidenceRenderer reads additional session files
            # indirectly (enriched_session.json, semantic_primitives.json, etc.)
        ],
        "WRITES": [
            "{base_dir}/file_dossiers.json",
            "{base_dir}/claude_md_analysis.json",
        ],
        "IMPORTS_FROM": [
            "tools.json_io",
            "tools.log_config",
            "phase_3_hyperdoc_writing.evidence_resolver",   # optional; used if @evidence directives found
        ],
    },

    # =========================================================================
    # phase_3_hyperdoc_writing/generate_viewer.py
    # =========================================================================
    "phase_3_hyperdoc_writing/generate_viewer.py": {
        "READS": [
            # All loaded from {base_dir} via load() helper (open + json.load)
            "{base_dir}/session_metadata.json",
            "{base_dir}/thread_extractions.json",
            "{base_dir}/geological_notes.json",
            "{base_dir}/semantic_primitives.json",
            "{base_dir}/explorer_notes.json",
            "{base_dir}/idea_graph.json",
            "{base_dir}/synthesis.json",
            "{base_dir}/grounded_markers.json",
            "{base_dir}/file_dossiers.json",
            "{base_dir}/claude_md_analysis.json",
            # Plain text hyperdoc blocks via load_text() helper
            "{base_dir}/hyperdoc_blocks/*.txt",
        ],
        "WRITES": [
            # Single HTML viewer written to {base_dir} (script writes to stdout or a .html file)
            "{base_dir}/pipeline_viewer.html",
        ],
        "IMPORTS_FROM": [
            "tools.log_config",
            "config",    # optional: OUTPUT_DIR
        ],
    },

    # =========================================================================
    # phase_3_hyperdoc_writing/write_hyperdocs.py
    # =========================================================================
    "phase_3_hyperdoc_writing/write_hyperdocs.py": {
        "READS": [
            # Paths are hardcoded relative to script directory (no --session support)
            "phase_3_hyperdoc_writing/file_dossiers.json",
            "phase_3_hyperdoc_writing/grounded_markers.json",
            "phase_3_hyperdoc_writing/idea_graph.json",
            "phase_3_hyperdoc_writing/claude_md_analysis.json",
            # Verification pass re-reads each written .txt file (open 'r')
            "phase_3_hyperdoc_writing/hyperdoc_blocks/{stem}_hyperdoc.txt",
        ],
        "WRITES": [
            # One .txt block per file in TOP_5_FILES
            "phase_3_hyperdoc_writing/hyperdoc_blocks/{stem}_hyperdoc.txt",
        ],
        "IMPORTS_FROM": [
            "tools.json_io",
            "tools.log_config",
        ],
    },

    # =========================================================================
    # phase_3_hyperdoc_writing/write_more_hyperdocs.py
    # =========================================================================
    "phase_3_hyperdoc_writing/write_more_hyperdocs.py": {
        "READS": [
            # Loaded from {base_dir} at module-level (json.load on open())
            "{base_dir}/file_dossiers.json",
            "{base_dir}/grounded_markers.json",
            # Source code files for the remaining dossier entries (not in ALREADY_DONE)
            "{V5_SOURCE_DIR}/{filename}.py",
            # Special-path override for one file:
            "~/.claude/hooks/hyperdoc/opus_struggle_analyzer.py",
        ],
        "WRITES": [
            # Hyperdoc comment block as plain text
            "{base_dir}/hyperdoc_blocks/{stem}_hyperdoc.txt",
            # Source + inserted block — preview copy (original untouched)
            "{base_dir}/hyperdoc_previews/{filename}.py",
            # Final destination copy
            "{base_dir}/hyperdoc_code_files/{filename}.py",
            # Existing ALREADY_DONE files copied from hyperdoc_previews/ to hyperdoc_code_files/
            # if not already present there (shutil.copy2)
        ],
        "IMPORTS_FROM": [
            "tools.log_config",
            "config",    # optional: OUTPUT_DIR, V5_SOURCE_DIR
        ],
    },

    # =========================================================================
    # phase_4a_aggregation/aggregate_dossiers.py
    # =========================================================================
    "phase_4a_aggregation/aggregate_dossiers.py": {
        "READS": [
            # Per-session dossiers (iterates output/session_*/):
            "output/session_*/file_dossiers.json",
            # Per-file evidence from Phase 3a (two search roots):
            "output/session_*/file_evidence/*_evidence.json",
            "~/PERMANENT_HYPERDOCS/sessions/session_*/file_evidence/*_evidence.json",
            # Code similarity index (two candidate locations):
            "output/code_similarity_index.json",
            "~/PERMANENT_HYPERDOCS/indexes/code_similarity_index.json",
            # File genealogy (two search roots):
            "output/session_*/file_genealogy.json",
            "~/PERMANENT_HYPERDOCS/sessions/session_*/file_genealogy.json",
            # Session metadata for frustration peaks:
            "output/session_*/session_metadata.json",
            "~/PERMANENT_HYPERDOCS/sessions/session_*/session_metadata.json",
            # Enriched session for per-message file mentions near frustration peaks:
            "output/session_*/enriched_session.json",
            "output/session_*/enriched_session_v2.json",   # preferred if present
        ],
        "WRITES": [
            # Main cross-session aggregated index:
            "output/cross_session_file_index.json",
            # Per-file extracts for Phase 4b agents (files with 3+ sessions only):
            "output/hyperdoc_inputs/{safe_filepath}.json",
            "~/PERMANENT_HYPERDOCS/hyperdoc_inputs/{safe_filepath}.json",
        ],
        "IMPORTS_FROM": [
            "tools.log_config",
            "tools.file_lock",   # optional: atomic_json_write
        ],
    },

    # =========================================================================
    # phase_4_insertion/hyperdoc_layers.py
    # =========================================================================
    "phase_4_insertion/hyperdoc_layers.py": {
        "READS": [
            # Individual hyperdoc JSON (load / append_layer / create_seed / get_layer_summary)
            "{hyperdocs_dir}/{stem}_hyperdoc.json",
            # Glob during --stats and migrate_directory()
            "{hyperdocs_dir}/*_hyperdoc.json",
        ],
        "WRITES": [
            # Saves layered hyperdoc (new file or in-place update)
            "{hyperdocs_dir}/{stem}_hyperdoc.json",
        ],
        "IMPORTS_FROM": [
            "config",   # optional: HYPERDOCS_STORE_DIR
        ],
    },

    # =========================================================================
    # phase_4_insertion/insert_from_phase4b.py
    # =========================================================================
    "phase_4_insertion/insert_from_phase4b.py": {
        "READS": [
            # Iterates all hyperdoc JSON files:
            "output/hyperdocs/*_hyperdoc.json",
            # Source files located via find_source_file() — candidates searched in order:
            #   ~/{file_path_field}
            #   ~/.claude/hooks/{filename}
            #   ~/.claude/hooks/{file_path_field}
            #   ~/.claude/hooks/docs/{filename}
            #   ~/apps/**/{filename}
            #   ~/archive/**/{filename}
            #   ~/.claude/hooks/hyperdoc/archive/**/{filename}
            #   ~/.claude/hooks/hyperdoc/hyperdocs_2/V1/code/**/{filename}
            #   ~/.claude/hooks/hyperdoc/hyperdocs_2/V2/code/**/{filename}
            #   ~/.claude/hooks/hyperdoc/hyperdocs_2/V5/code/**/{filename}
            #   ~/.claude/hooks/hyperdoc/hyperdocs_3/**/{filename}
            #   ~/output/**/{filename}
        ],
        "WRITES": [
            # Enhanced copies — originals are never modified
            "output/enhanced_files_archive/{filename}.py",
            "output/enhanced_files_archive/{parent}__{filename}.py",  # duplicate name fallback
            # Non-Python source types:
            "output/enhanced_files_archive/{filename}.md",
            "output/enhanced_files_archive/{filename}.html",
            "output/enhanced_files_archive/{filename}.js",
            "output/enhanced_files_archive/{filename}.toml",
            # JSON sources get a companion markdown file (JSON cannot have comments):
            "output/enhanced_files_archive/{filename}.json.hyperdoc.md",
        ],
        "IMPORTS_FROM": [],
    },

    # =========================================================================
    # phase_4_insertion/insert_hyperdocs_v2.py
    # =========================================================================
    "phase_4_insertion/insert_hyperdocs_v2.py": {
        "READS": [
            # Source code files from V5 code dir:
            "{V5_SOURCE_DIR}/{filename}.py",
            # Three-part hyperdoc content (adjacent to script in hyperdoc_v2/ subdir):
            "{script_dir}/hyperdoc_v2/{filename}_header.txt",
            "{script_dir}/hyperdoc_v2/{filename}_inline.json",
            "{script_dir}/hyperdoc_v2/{filename}_footer.txt",
        ],
        "WRITES": [
            # Preview copies with header + inline + footer inserted (originals untouched)
            "{script_dir}/hyperdoc_previews_v2/{filename}.py",
        ],
        "IMPORTS_FROM": [
            "config",   # optional: V5_SOURCE_DIR
        ],
    },

    # =========================================================================
    # phase_4_insertion/insert_hyperdocs.py
    # =========================================================================
    "phase_4_insertion/insert_hyperdocs.py": {
        "READS": [
            # Hyperdoc block .txt files from hyperdoc_blocks/ subdir (5 hardcoded files):
            "{script_dir}/hyperdoc_blocks/{stem}_hyperdoc.txt",
            # Source code files from V5 code dir:
            "{V5_SOURCE_DIR}/{filename}.py",
        ],
        "WRITES": [
            # Preview copies with hyperdoc block inserted (originals untouched)
            "{script_dir}/hyperdoc_previews/{filename}.py",
        ],
        "IMPORTS_FROM": [
            "config",   # optional: V5_SOURCE_DIR
        ],
    },

    # =========================================================================
    # phase_4_hyperdoc_writing/   — no .py files found in this directory
    # =========================================================================
}
