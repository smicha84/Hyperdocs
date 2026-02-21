#!/usr/bin/env python3
"""
Pipeline Health Check — All 10 test types for the Hyperdocs pipeline.

Runs every verification needed to confirm the pipeline is perfect:
  1. Schema Compatibility — output keys match consumer expectations
  2. End-to-End Run — full pipeline produces output at every stage
  3. Data Volume — no data loss between stages
  4. Empty Input Handling — graceful behavior on edge cases
  5. Idempotency — running twice produces same result
  6. Import Verification — every module imports without errors
  7. Path Resolution — all file references resolve to real files
  8. Backward Compatibility — old sessions still readable
  9. Cross-Stage Contracts — formal key requirements enforced
 10. Regression — test suite passes

Usage:
    python3 pipeline_health_check.py                    # Run all checks
    python3 pipeline_health_check.py --check schema     # Run one check
    python3 pipeline_health_check.py --session 1c9e0a77 # Use specific session
"""
import ast
import json
import os
import sys
import subprocess
import tempfile
import shutil
from pathlib import Path
from datetime import datetime
from collections import defaultdict

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

# ── Stage Contracts ───────────────────────────────────────────────────
# Formal definition: what each stage MUST produce.

STAGE_CONTRACTS = {
    "phase_0": {
        "enriched_session.json": {"required_keys": ["session_id", "messages", "session_stats"]},
        "session_metadata.json": {"required_keys": ["session_id", "session_stats"],
                                   "session_stats_keys": ["total_messages", "user_messages", "assistant_messages",
                                                          "tier_distribution", "frustration_peaks", "file_mention_counts"]},
        "safe_condensed.json": {"required_keys": ["messages"]},
        "safe_tier4.json": {"required_keys": ["messages"]},
    },
    "phase_1": {
        "thread_extractions.json": {
            "required_keys": ["session_id", "threads"],
            "threads_must_be": "dict",
            "threads_expected_keys": ["ideas", "reactions", "software", "code", "plans", "behavior"],
            "thread_entry_keys": ["description", "entries"],
        },
        "geological_notes.json": {
            "required_keys": ["session_id"],
            "expected_keys": ["micro", "meso", "macro", "observations", "geological_metaphor"],
        },
        "semantic_primitives.json": {
            "required_keys": ["tagged_messages"],
            "tagged_message_keys": ["msg_index", "action_vector", "confidence_signal",
                                     "emotional_tenor", "intent_marker"],
        },
        "explorer_notes.json": {
            "required_keys": ["session_id", "observations"],
            "expected_keys": ["verification", "explorer_summary"],
        },
    },
    "phase_2": {
        "idea_graph.json": {
            "required_keys": ["nodes", "edges"],
        },
        "synthesis.json": {
            "required_keys": ["passes"],
        },
        "grounded_markers.json": {
            "required_keys": ["markers"],
        },
    },
}

# ── Consumer Expectations ─────────────────────────────────────────────
# What each consumer file reads from which JSON file.

CONSUMER_EXPECTATIONS = {
    "output/batch_phase2_processor.py": {
        "thread_extractions.json": ["threads"],
        "semantic_primitives.json": ["tagged_messages"],
        "geological_notes.json": ["micro", "meso", "macro"],
        "explorer_notes.json": ["observations"],
        "session_metadata.json": ["session_stats"],
    },
    "output/batch_p2_generator.py": {
        "thread_extractions.json": ["threads"],
        "geological_notes.json": ["micro"],
        "session_metadata.json": ["session_stats"],
    },
    "phase_2_synthesis/file_genealogy.py": {
        "thread_extractions.json": ["threads"],
        "idea_graph.json": ["nodes", "edges"],
    },
    "phase_3_hyperdoc_writing/generate_viewer.py": {
        "thread_extractions.json": ["threads"],
        "geological_notes.json": ["micro", "meso", "macro"],
        "semantic_primitives.json": ["tagged_messages"],
        "explorer_notes.json": ["observations"],
        "idea_graph.json": ["nodes", "edges"],
        "synthesis.json": ["passes"],
        "grounded_markers.json": ["markers"],
    },
    "phase_3_hyperdoc_writing/generate_dossiers.py": {
        "thread_extractions.json": ["threads"],
        "session_metadata.json": ["session_stats"],
        "grounded_markers.json": ["markers"],
        "idea_graph.json": ["nodes", "edges"],
    },
    "phase_3_hyperdoc_writing/write_hyperdocs.py": {
        "grounded_markers.json": ["markers"],
    },
    "phase_3_hyperdoc_writing/generate_remaining_hyperdocs.py": {
        "grounded_markers.json": ["markers"],
    },
    "product/dashboard.py": {
        "session_metadata.json": ["session_stats"],
        "grounded_markers.json": ["markers"],
    },
    "phase_0_prep/completeness_scanner.py": {
        "thread_extractions.json": ["threads"],
        "semantic_primitives.json": ["tagged_messages"],
        "idea_graph.json": ["nodes", "edges"],
        "grounded_markers.json": ["markers"],
    },
    "phase_1_extraction/batch_orchestrator.py": {
        "session_metadata.json": ["session_stats"],
    },
}


class HealthCheck:
    def __init__(self, session_dir=None):
        self.results = {}
        self.session_dir = session_dir or self._find_session()
        self.total_pass = 0
        self.total_fail = 0
        self.total_skip = 0

    def _find_session(self):
        """Find a processed session to test against."""
        perm = Path.home() / "PERMANENT_HYPERDOCS" / "sessions"
        local = REPO / "output"
        for base in [local, perm]:
            if not base.exists():
                continue
            for d in sorted(base.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True):
                if d.is_dir() and d.name.startswith("session_"):
                    if (d / "thread_extractions.json").exists():
                        return d
        return None

    def _record(self, check_name, test_name, passed, detail=""):
        if check_name not in self.results:
            self.results[check_name] = []
        status = "PASS" if passed else "FAIL"
        if passed:
            self.total_pass += 1
        else:
            self.total_fail += 1
        self.results[check_name].append({"test": test_name, "status": status, "detail": detail})

    def _skip(self, check_name, test_name, reason):
        if check_name not in self.results:
            self.results[check_name] = []
        self.total_skip += 1
        self.results[check_name].append({"test": test_name, "status": "SKIP", "detail": reason})

    # ── 1. Schema Compatibility ───────────────────────────────────────
    def check_schema_compatibility(self):
        """Verify output keys match what consumers expect."""
        name = "1_schema_compatibility"
        if not self.session_dir:
            self._skip(name, "all", "No processed session found")
            return

        for consumer, expectations in CONSUMER_EXPECTATIONS.items():
            for json_file, expected_keys in expectations.items():
                fpath = self.session_dir / json_file
                if not fpath.exists():
                    self._skip(name, f"{consumer} <- {json_file}", "File not found")
                    continue
                try:
                    data = json.loads(fpath.read_text())
                    missing = [k for k in expected_keys if k not in data]
                    if missing:
                        self._record(name, f"{consumer} <- {json_file}",
                                     False, f"Missing keys: {missing}")
                    else:
                        self._record(name, f"{consumer} <- {json_file}", True)
                except json.JSONDecodeError as e:
                    self._record(name, f"{consumer} <- {json_file}", False, f"Invalid JSON: {e}")

    # ── 2. End-to-End Run ─────────────────────────────────────────────
    def check_end_to_end(self):
        """Verify all pipeline stages produced output."""
        name = "2_end_to_end"
        if not self.session_dir:
            self._skip(name, "all", "No processed session found")
            return

        for stage, files in STAGE_CONTRACTS.items():
            for fname in files:
                exists = (self.session_dir / fname).exists()
                self._record(name, f"{stage}/{fname}", exists,
                             "" if exists else "File missing")

    # ── 3. Data Volume ────────────────────────────────────────────────
    def check_data_volume(self):
        """Verify no data loss between stages."""
        name = "3_data_volume"
        if not self.session_dir:
            self._skip(name, "all", "No processed session found")
            return

        # Phase 0: message count
        meta_path = self.session_dir / "session_metadata.json"
        if meta_path.exists():
            meta = json.loads(meta_path.read_text())
            stats = meta.get("session_stats", meta)
            total = stats.get("total_messages", 0)
            self._record(name, "phase0_message_count", total > 0,
                         f"{total} messages" if total > 0 else "Zero messages")

            # Check tier distribution adds up
            tiers = stats.get("tier_distribution", {})
            tier_total = sum(tiers.values())
            self._record(name, "tier_distribution_sum", tier_total == total,
                         f"Tiers sum to {tier_total}, total is {total}")

        # Phase 1: thread entries > 0
        threads_path = self.session_dir / "thread_extractions.json"
        if threads_path.exists():
            threads = json.loads(threads_path.read_text())
            thread_data = threads.get("threads", {})
            if isinstance(thread_data, dict):
                total_entries = sum(
                    len(v.get("entries", [])) for v in thread_data.values()
                    if isinstance(v, dict)
                )
                self._record(name, "phase1_thread_entries", total_entries > 0,
                             f"{total_entries} entries across {len(thread_data)} categories")

        # Phase 1: tagged messages > 0
        prims_path = self.session_dir / "semantic_primitives.json"
        if prims_path.exists():
            prims = json.loads(prims_path.read_text())
            tagged = len(prims.get("tagged_messages", []))
            self._record(name, "phase1_tagged_messages", tagged > 0, f"{tagged} tagged")

        # Phase 2: nodes > 0
        ig_path = self.session_dir / "idea_graph.json"
        if ig_path.exists():
            ig = json.loads(ig_path.read_text())
            nodes = len(ig.get("nodes", []))
            self._record(name, "phase2_idea_nodes", nodes > 0, f"{nodes} nodes")

        # Phase 2: markers > 0 (with volume diagnostic)
        gm_path = self.session_dir / "grounded_markers.json"
        if gm_path.exists():
            gm = json.loads(gm_path.read_text())
            markers = gm.get("markers", [])
            marker_count = len(markers)
            # Minimum markers: should have at least 1 per top file + 1 per frustration peak
            meta_path2 = self.session_dir / "session_metadata.json"
            expected_min = 3  # bare minimum
            if meta_path2.exists():
                meta2 = json.loads(meta_path2.read_text())
                stats2 = meta2.get("session_stats", {})
                top_files = len(stats2.get("file_mention_counts", {}))
                frustration = len(stats2.get("frustration_peaks", []))
                expected_min = max(3, top_files // 2 + frustration)
            self._record(name, "phase2_marker_count", marker_count > 0, f"{marker_count} markers")
            self._record(name, "phase2_marker_volume", marker_count >= expected_min,
                         f"{marker_count} markers (expected >={expected_min} based on {top_files} files, {frustration} peaks)")
            # Check marker categories
            if markers:
                cats = defaultdict(int)
                for m in markers:
                    cats[m.get("category", "unknown")] += 1
                self._record(name, "phase2_marker_categories", len(cats) >= 2,
                             f"{len(cats)} categories: {dict(cats)}")

    # ── 4. Empty Input Handling ───────────────────────────────────────
    def check_empty_input(self):
        """Verify consumers don't crash on empty/minimal data."""
        name = "4_empty_input"

        # Create a minimal session directory
        with tempfile.TemporaryDirectory() as tmpdir:
            sd = Path(tmpdir)
            # Write minimal valid JSON files
            minimal = {
                "session_metadata.json": {"session_id": "test", "session_stats": {
                    "total_messages": 0, "user_messages": 0, "assistant_messages": 0,
                    "tier_distribution": {}, "frustration_peaks": [], "file_mention_counts": {},
                }},
                "thread_extractions.json": {"session_id": "test", "threads": {}},
                "geological_notes.json": {"session_id": "test", "micro": [], "meso": [], "macro": []},
                "semantic_primitives.json": {"tagged_messages": []},
                "explorer_notes.json": {"session_id": "test", "observations": [], "verification": {}},
                "idea_graph.json": {"nodes": [], "edges": []},
                "synthesis.json": {"passes": {}},
                "grounded_markers.json": {"markers": []},
            }
            for fname, data in minimal.items():
                (sd / fname).write_text(json.dumps(data))

            # Test batch_phase2_processor with empty data
            try:
                sys.path.insert(0, str(REPO / "output"))
                from batch_phase2_processor import build_idea_graph, build_synthesis, build_markers
                ig = build_idea_graph("test", {}, {}, {}, {}, minimal["session_metadata.json"])
                self._record(name, "phase2_empty_idea_graph", True, f"{len(ig.get('nodes', []))} nodes")
                syn = build_synthesis("test", {}, {}, {}, {}, minimal["session_metadata.json"])
                self._record(name, "phase2_empty_synthesis", True)
                mk = build_markers("test", {}, {}, {}, {}, minimal["session_metadata.json"])
                self._record(name, "phase2_empty_markers", True)
            except Exception as e:
                self._record(name, "phase2_empty_input", False, str(e)[:100])

    # ── 4b. Phase 3-4 Runtime ────────────────────────────────────────
    def check_phase3_4_runtime(self):
        """Test Phase 3 generate_viewer and Phase 4 insertion against real session data."""
        name = "4b_phase3_4_runtime"
        if not self.session_dir:
            self._skip(name, "all", "No processed session found")
            return

        p3_dir = REPO / "phase_3_hyperdoc_writing"

        # Test generate_viewer.py: symlink session data, run, check output, clean up
        json_files = ["session_metadata.json", "thread_extractions.json", "geological_notes.json",
                      "semantic_primitives.json", "explorer_notes.json", "idea_graph.json",
                      "synthesis.json", "grounded_markers.json"]
        links_created = []
        try:
            for fname in json_files:
                src = self.session_dir / fname
                dst = p3_dir / fname
                if src.exists() and not dst.exists():
                    os.symlink(str(src), str(dst))
                    links_created.append(dst)

            # Run generate_viewer.py
            result = subprocess.run(
                [sys.executable, str(p3_dir / "generate_viewer.py")],
                capture_output=True, text=True, timeout=30,
                cwd=str(p3_dir),
            )
            viewer_path = p3_dir / "pipeline_viewer.html"
            if result.returncode == 0 and viewer_path.exists():
                size = viewer_path.stat().st_size
                self._record(name, "phase3_generate_viewer", True, f"{size:,} bytes HTML")
                viewer_path.unlink()  # clean up
            else:
                err = result.stderr[:100] if result.stderr else "unknown error"
                self._record(name, "phase3_generate_viewer", False, err)
        except Exception as e:
            self._record(name, "phase3_generate_viewer", False, str(e)[:100])
        finally:
            for link in links_created:
                if link.is_symlink():
                    link.unlink()

        # Test Phase 4 insertion scripts parse without error
        for script in ["insert_hyperdocs.py", "insert_hyperdocs_v2.py", "insert_from_phase4b.py",
                        "hyperdoc_layers.py", "hyperdoc_store_init.py"]:
            spath = REPO / "phase_4_insertion" / script
            if spath.exists():
                try:
                    ast.parse(spath.read_text())
                    self._record(name, f"phase4_syntax:{script}", True)
                except SyntaxError as e:
                    self._record(name, f"phase4_syntax:{script}", False, str(e)[:80])

        # Test Phase 4 hyperdoc_layers.py can import and run
        result = subprocess.run(
            [sys.executable, "-c",
             "from phase_4_insertion.hyperdoc_layers import migrate_directory; print('OK')"],
            capture_output=True, text=True, timeout=10, cwd=str(REPO),
        )
        self._record(name, "phase4_import_hyperdoc_layers",
                     result.returncode == 0,
                     result.stdout.strip() if result.returncode == 0 else result.stderr[:80])

        # Test that existing hyperdoc JSONs in PERMANENT_HYPERDOCS are readable
        hd_dir = Path.home() / "PERMANENT_HYPERDOCS" / "hyperdocs"
        if hd_dir.exists():
            hd_files = list(hd_dir.glob("*_hyperdoc.json"))[:5]
            for hf in hd_files:
                try:
                    data = json.loads(hf.read_text())
                    has_layers = "layers" in data
                    has_header = any(l.get("header") for l in data.get("layers", []))
                    self._record(name, f"phase4_hyperdoc:{hf.name[:30]}",
                                 has_layers, f"layers={len(data.get('layers', []))}, has_header={has_header}")
                except Exception as e:
                    self._record(name, f"phase4_hyperdoc:{hf.name[:30]}", False, str(e)[:60])

    # ── 5. Idempotency ────────────────────────────────────────────────
    def check_idempotency(self):
        """Verify running Phase 2 twice produces same output."""
        name = "5_idempotency"
        if not self.session_dir:
            self._skip(name, "all", "No processed session found")
            return

        ig_path = self.session_dir / "idea_graph.json"
        if not ig_path.exists():
            self._skip(name, "idea_graph", "No idea_graph.json")
            return

        # Read current output
        original = ig_path.read_text()

        # Re-run Phase 2
        result = subprocess.run(
            [sys.executable, str(REPO / "output" / "batch_phase2_processor.py"),
             "--force", self.session_dir.name.replace("session_", "")],
            capture_output=True, text=True, timeout=30,
            cwd=str(REPO),
        )

        if result.returncode != 0:
            self._record(name, "phase2_rerun", False, f"Exit code {result.returncode}")
            return

        # Compare (ignoring timestamps)
        new = ig_path.read_text()
        orig_data = json.loads(original)
        new_data = json.loads(new)
        # Remove timestamp fields
        for d in [orig_data, new_data]:
            d.pop("generated_at", None)
        same = json.dumps(orig_data, sort_keys=True) == json.dumps(new_data, sort_keys=True)
        self._record(name, "phase2_idempotent", same,
                     "Same output" if same else "Output differs")

    # ── 6. Import Verification ────────────────────────────────────────
    def check_imports(self):
        """Verify every Python file compiles AND key modules import at runtime."""
        name = "6_imports"
        skip_dirs = {"output", "obsolete", "tests", "__pycache__", ".pytest_cache",
                     "archive_originals", "commands", "standby"}

        for py_file in REPO.rglob("*.py"):
            if any(sd in py_file.parts for sd in skip_dirs):
                continue
            rel = py_file.relative_to(REPO)

            # AST parse (syntax check)
            try:
                source = py_file.read_text()
                ast.parse(source)
                self._record(name, f"syntax:{rel}", True)
            except SyntaxError as e:
                self._record(name, f"syntax:{rel}", False, f"Line {e.lineno}: {e.msg}")

        # Runtime import check for critical modules
        runtime_imports = [
            ("phase_0_prep.claude_session_reader", "ClaudeSessionReader"),
            ("phase_0_prep.geological_reader", "GeologicalMessage"),
            ("phase_0_prep.metadata_extractor", "MetadataExtractor"),
            ("phase_0_prep.message_filter", "MessageFilter"),
            ("phase_0_prep.claude_behavior_analyzer", "ClaudeBehaviorAnalyzer"),
            ("phase_0_prep.schema_normalizer", "NORMALIZERS"),
        ]
        for mod_name, attr_name in runtime_imports:
            result = subprocess.run(
                [sys.executable, "-c",
                 f"from {mod_name} import {attr_name}; print('{attr_name} OK')"],
                capture_output=True, text=True, timeout=10,
                cwd=str(REPO),
            )
            passed = result.returncode == 0
            detail = result.stdout.strip() if passed else result.stderr.strip()[:80]
            self._record(name, f"runtime:{mod_name}.{attr_name}", passed, detail)

    # ── 7. Path Resolution ────────────────────────────────────────────
    def check_paths(self):
        """Verify all referenced paths resolve to actual files."""
        name = "7_paths"
        skip_dirs = {"output", "obsolete", "tests", "__pycache__",
                     "archive_originals", "commands", "standby"}

        import re
        path_pattern = re.compile(r'REPO\s*/\s*"([^"]+)"')

        for py_file in REPO.rglob("*.py"):
            if any(sd in py_file.parts for sd in skip_dirs):
                continue
            rel = py_file.relative_to(REPO)
            source = py_file.read_text()

            # Find REPO / "path/to/file" patterns
            for match in path_pattern.finditer(source):
                ref_path = match.group(1)
                full = REPO / ref_path
                # Only check if it looks like a specific file reference
                if "." in ref_path.split("/")[-1]:
                    if not full.exists():
                        # Check if it's a script being called (might be in a different location now)
                        self._record(name, f"{rel} -> {ref_path}", False, "Path not found")

        # Also check that key directories exist
        for d in ["phase_0_prep", "phase_1_extraction", "phase_2_synthesis",
                   "phase_3_hyperdoc_writing", "phase_4_insertion", "product", "tools", "tests"]:
            exists = (REPO / d).is_dir()
            self._record(name, f"dir:{d}/", exists)

    # ── 8. Backward Compatibility ─────────────────────────────────────
    def check_backward_compat(self):
        """Verify old-format sessions can still be read by current consumers."""
        name = "8_backward_compat"
        perm = Path.home() / "PERMANENT_HYPERDOCS" / "sessions"
        if not perm.exists():
            self._skip(name, "all", "PERMANENT_HYPERDOCS not found")
            return

        # Test 10 sessions spread across the archive
        all_sessions = sorted(d for d in perm.iterdir()
                              if d.is_dir() and d.name.startswith("session_")
                              and (d / "thread_extractions.json").exists())
        if not all_sessions:
            self._skip(name, "all", "No sessions with Phase 1 output found")
            return

        # Sample: first, middle, last, and 7 evenly spaced
        sample_indices = set([0, len(all_sessions) // 2, len(all_sessions) - 1])
        step = max(1, len(all_sessions) // 10)
        for i in range(0, len(all_sessions), step):
            sample_indices.add(i)
        sample = [all_sessions[i] for i in sorted(sample_indices)][:10]

        for sd in sample:
            sid = sd.name[:16]
            # Check thread_extractions readable (has threads or extractions)
            try:
                data = json.loads((sd / "thread_extractions.json").read_text())
                has_threads = bool(data.get("threads") or data.get("extractions"))
                fmt = "dict" if isinstance(data.get("threads"), dict) else (
                    "list" if isinstance(data.get("threads"), list) else (
                    "extractions" if data.get("extractions") else "unknown"))
                self._record(name, f"threads:{sid}", has_threads, f"format={fmt}")
            except Exception as e:
                self._record(name, f"threads:{sid}", False, str(e)[:60])

            # Check grounded_markers readable (has markers or structured)
            gm_path = sd / "grounded_markers.json"
            if gm_path.exists():
                try:
                    gm = json.loads(gm_path.read_text())
                    # Check format is readable (has known keys, even if empty)
                    readable = "markers" in gm or "warnings" in gm or "patterns" in gm
                    count = len(gm.get("markers", [])) + len(gm.get("warnings", [])) + len(gm.get("patterns", []))
                    fmt = "flat" if "markers" in gm else "structured"
                    self._record(name, f"markers:{sid}", readable, f"format={fmt}, {count} items")
                except Exception as e:
                    self._record(name, f"markers:{sid}", False, str(e)[:60])

            # Check semantic_primitives readable
            sp_path = sd / "semantic_primitives.json"
            if sp_path.exists():
                try:
                    sp = json.loads(sp_path.read_text())
                    has_data = bool(sp.get("tagged_messages") or sp.get("primitives"))
                    fmt = "canonical" if sp.get("tagged_messages") else (
                        "old" if sp.get("primitives") else "unknown")
                    self._record(name, f"primitives:{sid}", has_data, f"format={fmt}")
                except Exception as e:
                    self._record(name, f"primitives:{sid}", False, str(e)[:60])

    # ── 9. Cross-Stage Contracts ──────────────────────────────────────
    def check_contracts(self):
        """Enforce formal stage output contracts."""
        name = "9_contracts"
        if not self.session_dir:
            self._skip(name, "all", "No processed session found")
            return

        for stage, files in STAGE_CONTRACTS.items():
            for fname, contract in files.items():
                fpath = self.session_dir / fname
                if not fpath.exists():
                    self._record(name, f"{stage}/{fname}", False, "File missing")
                    continue

                try:
                    data = json.loads(fpath.read_text())
                except json.JSONDecodeError:
                    self._record(name, f"{stage}/{fname}", False, "Invalid JSON")
                    continue

                # Check required keys
                required = contract.get("required_keys", [])
                missing = [k for k in required if k not in data]
                if missing:
                    self._record(name, f"{stage}/{fname}/required_keys",
                                 False, f"Missing: {missing}")
                else:
                    self._record(name, f"{stage}/{fname}/required_keys", True)

                # Check type constraints
                if "threads_must_be" in contract:
                    threads = data.get("threads")
                    expected_type = contract["threads_must_be"]
                    actual_type = type(threads).__name__
                    self._record(name, f"{stage}/{fname}/threads_type",
                                 actual_type == expected_type,
                                 f"Expected {expected_type}, got {actual_type}")

                # Check nested keys
                if "session_stats_keys" in contract:
                    stats = data.get("session_stats", {})
                    missing_stats = [k for k in contract["session_stats_keys"] if k not in stats]
                    self._record(name, f"{stage}/{fname}/session_stats_keys",
                                 not missing_stats,
                                 f"Missing: {missing_stats}" if missing_stats else "All present")

                if "tagged_message_keys" in contract:
                    msgs = data.get("tagged_messages", [])
                    if msgs:
                        first = msgs[0]
                        missing_msg = [k for k in contract["tagged_message_keys"] if k not in first]
                        self._record(name, f"{stage}/{fname}/tagged_message_keys",
                                     not missing_msg,
                                     f"Missing: {missing_msg}" if missing_msg else "All present")

    # ── 10. Regression ────────────────────────────────────────────────
    def check_regression(self):
        """Run the test suite."""
        name = "10_regression"
        result = subprocess.run(
            [sys.executable, "-m", "pytest", str(REPO / "tests"), "-q", "--tb=line"],
            capture_output=True, text=True, timeout=60,
            cwd=str(REPO),
        )
        passed = result.returncode == 0
        # Extract summary line
        lines = result.stdout.strip().splitlines()
        summary = lines[-1] if lines else "No output"
        self._record(name, "pytest", passed, summary)

    # ── Runner ────────────────────────────────────────────────────────
    def run_all(self):
        """Run all 10 checks."""
        checks = [
            ("1. Schema Compatibility", self.check_schema_compatibility),
            ("2. End-to-End", self.check_end_to_end),
            ("3. Data Volume", self.check_data_volume),
            ("4a. Empty Input", self.check_empty_input),
            ("4b. Phase 3-4 Runtime", self.check_phase3_4_runtime),
            ("5. Idempotency", self.check_idempotency),
            ("6. Imports", self.check_imports),
            ("7. Paths", self.check_paths),
            ("8. Backward Compat", self.check_backward_compat),
            ("9. Contracts", self.check_contracts),
            ("10. Regression", self.check_regression),
        ]

        print("=" * 70)
        print("HYPERDOCS PIPELINE HEALTH CHECK")
        print(f"Session: {self.session_dir}")
        print(f"Time: {datetime.now().isoformat()}")
        print("=" * 70)

        for label, fn in checks:
            print(f"\n{label}...")
            try:
                fn()
            except Exception as e:
                self._record(label, "CRASH", False, str(e)[:100])

        # Print results
        print("\n" + "=" * 70)
        print("RESULTS")
        print("=" * 70)

        for check_name, tests in self.results.items():
            passes = sum(1 for t in tests if t["status"] == "PASS")
            fails = sum(1 for t in tests if t["status"] == "FAIL")
            skips = sum(1 for t in tests if t["status"] == "SKIP")
            icon = "PASS" if fails == 0 else "FAIL"
            print(f"\n  [{icon}] {check_name} ({passes}P {fails}F {skips}S)")
            for t in tests:
                if t["status"] == "FAIL":
                    print(f"    FAIL: {t['test']} — {t['detail']}")
                elif t["status"] == "SKIP":
                    print(f"    SKIP: {t['test']} — {t['detail']}")

        print(f"\n{'=' * 70}")
        print(f"TOTAL: {self.total_pass} passed, {self.total_fail} failed, {self.total_skip} skipped")
        total = self.total_pass + self.total_fail
        pct = self.total_pass / total * 100 if total > 0 else 0
        print(f"HEALTH: {pct:.0f}%")
        print("=" * 70)

        # Write report
        report_path = REPO / "output" / "health_check_report.json"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        with open(report_path, "w") as f:
            json.dump({
                "generated_at": datetime.now().isoformat(),
                "session_dir": str(self.session_dir),
                "total_pass": self.total_pass,
                "total_fail": self.total_fail,
                "total_skip": self.total_skip,
                "health_pct": round(pct, 1),
                "results": self.results,
            }, f, indent=2)
        print(f"\nReport: {report_path}")

        return self.total_fail == 0

    def run_check(self, check_name):
        """Run a single check by name."""
        check_map = {
            "schema": self.check_schema_compatibility,
            "e2e": self.check_end_to_end,
            "volume": self.check_data_volume,
            "empty": self.check_empty_input,
            "phase34": self.check_phase3_4_runtime,
            "idempotency": self.check_idempotency,
            "imports": self.check_imports,
            "paths": self.check_paths,
            "backward": self.check_backward_compat,
            "contracts": self.check_contracts,
            "regression": self.check_regression,
        }
        fn = check_map.get(check_name)
        if fn:
            fn()
            for tests in self.results.values():
                for t in tests:
                    icon = "PASS" if t["status"] == "PASS" else ("FAIL" if t["status"] == "FAIL" else "SKIP")
                    print(f"  [{icon}] {t['test']}" + (f" — {t['detail']}" if t["detail"] else ""))
        else:
            print(f"Unknown check: {check_name}. Available: {list(check_map.keys())}")


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Pipeline Health Check")
    parser.add_argument("--check", default="", help="Run single check (schema/e2e/volume/empty/idempotency/imports/paths/backward/contracts/regression)")
    parser.add_argument("--session", default="", help="Session directory or short ID")
    args = parser.parse_args()

    session_dir = None
    if args.session:
        candidates = [
            REPO / "output" / f"session_{args.session[:8]}",
            Path.home() / "PERMANENT_HYPERDOCS" / "sessions" / f"session_{args.session[:8]}",
        ]
        session_dir = next((c for c in candidates if c.exists()), None)

    hc = HealthCheck(session_dir)

    if args.check:
        hc.run_check(args.check)
    else:
        success = hc.run_all()
        sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
