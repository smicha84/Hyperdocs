# Hyperdocs Gap Tracker — Definitive List

Generated: 2026-02-21
Round 1: Mechanical grep scans (categories A-K, 52 gaps) — exact line numbers, reproducible
Round 2: Deep logical reads by 3 parallel agents (categories L-M, 30 gaps) — every file read completely
Round 3: Infrastructure audit (category N, 11 gaps) — cron scripts, GitHub drift, dependencies
Round 4: Security + data integrity + dead code (categories P-R, 10 gaps) — .env exposure, partial sessions, orphan functions

Scope: 58 active Python files + 3 cron scripts + 285 session output dirs + git state

---

## CATEGORY A: CODE THAT WILL CRASH AT RUNTIME (5 gaps)

### A1. Duplicate `def main()` in deterministic_prep.py
- **File:** `phase_0_prep/deterministic_prep.py:279` and `:904`
- **Evidence:** `grep -n '^def main' deterministic_prep.py` → 2 hits
- **Impact:** Python uses the LAST definition. First main() (lines 279-510) is dead code. The two functions have different field initializations — first has `human_messages`, `protocol_messages`, `char_per_line_messages`, `tool_failure_count`; second does not.

### A2. Duplicate `def main()` in batch_orchestrator.py
- **File:** `phase_1_extraction/batch_orchestrator.py:156` and `:591`
- **Evidence:** `grep -n '^def main' batch_orchestrator.py` → 2 hits
- **Impact:** Same as A1 — first main() is dead code.

### A3. Missing `import os` in message_filter.py
- **File:** `phase_0_prep/message_filter.py:319`
- **Evidence:** `os.getenv()` used at line 319, no `import os` in file
- **Impact:** NameError if `__main__` block runs.

### A4. `assert len(files) == 15` in generate_dossiers.py
- **File:** `phase_3_hyperdoc_writing/generate_dossiers.py:980`
- **Evidence:** Hard assert crashes on any session that doesn't have exactly 15 TARGET_FILES
- **Impact:** Script crashes instead of degrading gracefully for non-reference sessions.

### A5. 17 hard asserts in generate_dossiers.py validation section
- **File:** `phase_3_hyperdoc_writing/generate_dossiers.py:972-999`
- **Evidence:** Lines 972-999 contain 17 assert statements checking reference-session-specific data (P25, P03, P11 gate names)
- **Impact:** Any session without those exact gate names crashes validation.

---

## CATEGORY B: BARE EXCEPTS (4 locations in active code)

### B1. geological_reader.py:834
- `except:` — catches KeyboardInterrupt, SystemExit

### B2. extract_viz_data.py:32
- `except:` — catches everything silently

### B3. extract_viz_data.py:144
- `except:` — catches everything silently

### B4. extract_viz_data.py:195
- `except:` — catches everything silently

---

## CATEGORY C: BROAD `except Exception` (13 locations in active code)

### C1. pipeline_health_check.py:326, 366, 405, 553, 566, 578, 679 (7 locations)
### C2. deterministic_prep.py:969, 983 (2 locations)
### C3. geological_reader.py:922 (1 location)
### C4. schema_normalizer.py:722 (1 location)
### C5. batch_p2_generator.py:22 (1 location)
### C6. batch_phase2_processor.py:17 (1 location)

---

## CATEGORY D: HARDCODED PATHS (1 location in active code)

### D1. batch_p2_generator.py:7
- **File:** `output/batch_p2_generator.py:7`
- **Evidence:** `BASE = "/Users/stefanmichaelcheck/PycharmProjects/pythonProject ARXIV4/pythonProjectartifact/.claude/hooks/hyperdoc/hyperdocs_3/output"`
- **Impact:** Not portable. Breaks on any other machine.

---

## CATEGORY E: CONTENT TRUNCATION (6 locations in active code)

### E1. geological_reader.py:737 — `self.content[:500] + "..."`
- Active data truncation violating iron rule 4

### E2. prompts.py:287 — `content[:3800] + "\n[... truncated for analysis ...]"`
- LLM prompt truncation (may be intentional for API limits)

### E3. prompts.py:328 — `c_content[:1800] + "\n[... truncated ...]"`
- LLM prompt truncation

### E4. prompts.py:334 — `content[:3800] + "\n[... truncated for analysis ...]"`
- LLM prompt truncation

### E5. opus_classifier.py:191 — `content[:500] + "..."`
- Data truncation before classification

### E6. tag_primitives.py:398-399 — NO-OP truncation guard
- `if len(readable) > 200: readable = readable` — does nothing

---

## CATEGORY F: MISSING `__init__.py` (9 directories)

### F1-F9:
- `phase_0_prep/` — MISSING
- `phase_1_extraction/` — MISSING
- `phase_2_synthesis/` — MISSING
- `phase_3_hyperdoc_writing/` — MISSING
- `phase_4_hyperdoc_writing/` — MISSING
- `phase_4_insertion/` — MISSING
- `product/` — MISSING
- `tools/` — MISSING
- `output/` — MISSING

---

## CATEGORY G: STALE/CONTRADICTORY HYPERDOC METADATA (3 files)

### G1. generate_viewer.py:835
- `@ctx:file_status=DELETED @ctx:exists_on_disk=false` — file EXISTS and is executable

### G2. geological_reader.py:318
- `@ctx:exists_on_disk=false` — file EXISTS

### G3. config.py:153, 156, 320, 368, 370
- Documents that aggregator marks `exists_on_disk=false` — the file exists

---

## CATEGORY H: REFERENCE-SESSION ASSUMPTIONS (4 locations)

### H1. extract_threads.py:199
- `REFERENCE_SESSION_ID = "3b7084d5"` — hand-annotated data only activates for this session (this is BY DESIGN, not a bug — annotations are ground truth for reference session)

### H2. generate_dossiers.py:78-94
- `TARGET_FILES` list of 15 hardcoded filenames from reference session

### H3. generate_dossiers.py:377-613
- `STORY_ARCS`, `BEHAVIOR_PROFILES`, `RELATED_FILES` dicts hardcoded for 15 reference files

### H4. generate_dossiers.py:749-939
- `claude_md_analysis` dict hardcoded for reference-session gate analysis (P25, P03, P11)

---

## CATEGORY I: BETA API DEPENDENCY (2 locations)

### I1. phase1_redo_orchestrator.py:386
- `client.beta.messages.stream()` — beta API, may change

### I2. hyperdoc_comparison.py:65
- `client.beta.messages.stream()` — beta API, may change

---

## CATEGORY J: DATA FLOW ISSUES (3 gaps)

### J1. insert_from_phase4b.py:26 references `output/enhanced_files`
- Directory was moved to `output/enhanced_files_archive/`
- Will recreate on next run (mkdir exists_ok=True) — but stale reference

### J2. code_similarity.py:443 references `enhanced_files`
- Same directory reference — may find nothing now

### J3. extract_viz_data.py:274 hardcodes `"enhanced_files": 412`
- Hardcoded count from Feb 8 — now 0 files in that location

---

## CATEGORY K: SCHEMA/VALIDATION (2 gaps)

### K1. No schema validation between phases
- Phase 1 output → Phase 2 input has no contract check
- Phase 2 output → Phase 3 input has no contract check
- Malformed data flows silently

### K2. Schema normalizer not in default pipeline
- `tools/run_pipeline.py` requires explicit `--normalize` flag
- Should run automatically after Phase 1 agents produce output

---

---

## CATEGORY L: LOGICAL BUGS (greps can't find these) — 22 gaps

### Phase 0 logic (10 gaps)

**L1.** `phase_0_prep/llm_pass_runner.py:69-73` — OPUS_CONTEXT_LIMIT set to 180K, docstring says 200K. Stale limit never validated against actual Opus 4.6 specs.

**L2.** `phase_0_prep/merge_llm_results.py:98-99` — References `PASS_CONFIGS[1]["model"]` imported from prompts.py. If prompts.py restructures PASS_CONFIGS, this silently breaks at runtime.

**L3.** `phase_0_prep/prompts.py:367` — Pass 3's message_filter is `None`. llm_pass_runner.py:151 checks `if filter_fn is None` defensively, but the design relies on this check existing — fragile coupling.

**L4.** `phase_0_prep/claude_behavior_analyzer.py:628-631` — Compares `m.timestamp < ...` but ClaudeMessage.timestamp can be None (optional field). None comparison raises TypeError at runtime.

**L5.** `phase_0_prep/metadata_extractor.py:815` — Inner loop variable `session` shadows outer `session` variable. After inner loop, all references to `session` point to LAST element, not the SessionMetadata object. Silent logic error producing wrong aggregates.

**L6.** `phase_0_prep/metadata_extractor.py:878` — `DisplayFormatAdapter()` used unconditionally in main() but imported conditionally (lines 40-45). Crashes if the conditional import failed.

**L7.** `phase_0_prep/build_opus_filtered.py:126-129` — Builds index assuming `m.get("index")` exists, but opus_classifications.json may use `"msg_index"` instead. dict.get() silently returns None, producing wrong lookups.

**L8.** `phase_0_prep/completeness_scanner.py:344-356` — Field completeness counts MISSING files as uniformly absent fields. A session with only Phase 1 complete gets inflated incompleteness scores for all Phase 2+3 fields.

**L9.** `phase_0_prep/opus_classifier.py:241-244` — JSON array extraction uses `re.search(r'\[.*\]', text, re.DOTALL)` which captures from FIRST `[` to LAST `]`. If LLM outputs multiple JSON fragments, captures invalid cross-fragment JSON.

**L10.** `phase_0_prep/schema_validator.py:57` — Accesses `CANONICAL_DATA_KEYS[filename]` without checking membership for all paths. If a file exists in FILE_CHECKERS but not CANONICAL_DATA_KEYS, raises KeyError.

### Phase 1-4 logic (12 gaps)

**L11.** `phase_1_extraction/phase1_redo_orchestrator.py:829-835` — DUPLICATE_SKIP_IDS built from chat history archive, but processes SESSIONS_DIR. Different directories with mismatched naming conventions. May skip non-duplicates or miss actual duplicates.

**L12.** `phase_1_extraction/phase1_redo_orchestrator.py:504-539` — Token budget calculation assumes commitments tokens are part of 872K limit, but `_prepend_commitments()` (lines 619, 652, 688, 717, 755) adds them OUTSIDE the budget. Large sessions may exceed actual token limit.

**L13.** `phase_1_extraction/phase1_redo_orchestrator.py:554-564` — `_merge_thread_results()` assumes results_list has ≥1 element (`merged = results_list[0]`). If all chunks fail, returns empty dict `{}`. Downstream expects `threads`, `micro`, `meso`, `macro` keys.

**L14.** `phase_1_extraction/phase1_redo_orchestrator.py:709-731` — Primitives continuation loop condition `while n_tagged < expected_count and n_tagged > 0`. If first call returns 0 tags, loop never runs. Should be `or` not `and`.

**L15.** `phase_3_hyperdoc_writing/write_hyperdocs.py:76` — Uses Python 3.10+ type hint syntax `dict | None`. Will SyntaxError on Python 3.9 (which is the system Python on macOS).

**L16.** `phase_4_insertion/hyperdoc_layers.py:137-141` — `append_layer()` never updates `total_sessions` in cumulative summary. Always reports 0 sessions regardless of layers added.

**L17.** `phase_1_extraction/batch_orchestrator.py:460` — `json.load(open(summary_f))` never closes file handle. In loop processing 260+ sessions, leaks file descriptors.

**L18.** `phase_2_synthesis/file_genealogy.py:196-199` — Temporal succession detection is unidirectional. Only checks if file_b starts after file_a ends. Never checks reverse. Asymmetric genealogy links.

**L19.** `phase_1_extraction/batch_llm_orchestrator.py:275-279` — Checkpoint tracking uses pass-level keys. A session processed in pass 1 AND pass 2 appears in both without deduplication. Incorrect progress counts.

**L20.** `output/batch_phase2_processor.py:164-168` — Primitives distribution building expects exact field names (`action_vector`, `confidence_signal`). If tagged_messages use different keys (e.g., `action`), distributions silently empty.

**L21.** `phase_4_insertion/insert_hyperdocs.py:170-194` — `insert_hyperdoc()` doesn't validate hyperdoc_text is non-empty. Empty/corrupt hyperdoc files insert blank comments into source code.

**L22.** `phase_4_insertion/insert_from_phase4b.py:102-111` — Docstring parsing counts quotes on first line. Multi-line docstrings with opening `"""` alone on first line may cause wrong insertion point.

---

## CATEGORY M: CROSS-FILE DATA FLOW ISSUES (8 gaps)

**M1.** `product/concierge.py:22` vs `config.py:21` — HYPERDOCS_ROOT resolved as `Path(__file__).parent.parent` in both, but they're at different depths. Produces different directory targets.

**M2.** `product/concierge.py:190` — Sets HYPERDOCS_SESSION_ID for subprocess but NOT HYPERDOCS_CHAT_HISTORY. Subprocess re-searches filesystem and may find DIFFERENT session than concierge.py found.

**M3.** `tools/run_pipeline.py:143` → `output/batch_p2_generator.py:7` — run_pipeline imports batch_p2_generator at runtime. batch_p2_generator has hardcoded absolute path (D1). Import fails on any other machine. Indirect dependency chain.

**M4.** `tools/run_pipeline.py:248` — Schema normalizer placed between Phase 1 and Phase 2 in --full mode. If normalizer fails, Phase 2 never runs. But Phase 2 has its OWN normalization. Unclear which should be authoritative.

**M5.** `tools/pipeline_health_check.py:39-80` — STAGE_CONTRACTS missing entries for Phase 3 and Phase 4. Health check cannot validate dossier/viewer/insertion output schemas.

**M6.** `tools/pipeline_health_check.py:326+` — 7 broad `except Exception` blocks catch and suppress validation failures. Final report may claim "passed" while 7 tests silently failed.

**M7.** `product/realtime_hook.py:31` vs `config.py:34` — Inconsistent HYPERDOCS_OUTPUT_DIR semantics. realtime_hook writes buffer to one dir, config.py resolves sessions to a different dir. dashboard.py reads from a third location.

**M8.** `product/dashboard.py:70-76` — Missing JSON files render as empty dashboard sections with no error. User cannot distinguish "no findings" from "findings file missing/corrupt."

---

## CATEGORY N: INFRASTRUCTURE & DEPLOYMENT (11 gaps)

### Cron / sync

**N1.** `sync_to_permanent.py:26` — CLAUDE_CODE_DIR hardcoded to ONE project directory. There are 4 project dirs under `~/.claude/projects/`. Sessions in the other 3 are never synced.

**N2.** `sync_hyperdocs.py:19-21` — SOURCE_DIR hardcoded to the full absolute path of hyperdocs_3/output. Not portable. Will break if repo moves.

**N3.** `sync_from_dev.sh:10` — SRC hardcoded to full absolute path. Same portability issue.

**N4.** `sync_from_dev.sh` — Does NOT exclude `obsolete/` or `archive_originals/`. These get synced to GitHub even though they contain dead code.

### GitHub repo drift

**N5.** GitHub repo has 20+ files that no longer exist in dev — flat copies (`batch_orchestrator.py`, `concierge.py`, `dashboard.py`, `install.py`, `gap_checklist.py`) from before the phase-folder reorganization. Also has `phase_0_prep/v5_compat/` (7 files) and `phase_5_ground_truth/` (4 files) that were dissolved.

**N6.** Dev has 8 files not in GitHub: `output/batch_p2_generator.py`, `output/batch_phase2_processor.py`, `output/extract_viz_data.py`, 4 new test files, `tools/run_pipeline.py`. These are excluded by `--exclude='output/'` in sync script.

**N7.** `sync_from_dev.sh` excludes `output/` entirely. This means `batch_p2_generator.py` (used by run_pipeline.py Phase 2) is NEVER synced to GitHub. Anyone cloning the repo cannot run Phase 2.

### Dependencies / environment

**N8.** `requirements.txt` lists 3 packages but `pytest` is not listed. Tests require pytest. Anyone running `pip install -r requirements.txt && pytest` will fail.

**N9.** No Python version specification anywhere. System runs on 3.9.6 (macOS default). `write_hyperdocs.py:76` uses `dict | None` syntax that works as annotation but would fail under `typing.get_type_hints()` on 3.9.

### Tests

**N10.** 4 of 10 test files (`test_claim_extractor.py`, `test_gap_checklist.py`, `test_ground_truth_verifier.py`, `test_iterate.py`) import from `obsolete/` — they test `claim_extractor`, `gap_checklist`, `ground_truth_verifier`, `iterate` which ALL live in `obsolete/` or `obsolete/phase_5_ground_truth/`. These tests pass but test dead code, not the active pipeline.

**N11.** `GAP_TRACKER.md` itself is NOT excluded by sync script, so it WILL be pushed to GitHub on next cron sync. This is fine if intentional, but the file contains detailed internal system analysis that may not belong in a public repo.

---

## CATEGORY P: SECURITY (4 gaps)

**P1.** ROOT `.env` FILE IS GIT-TRACKED
- `.env` containing `ANTHROPIC_API_KEY` is tracked in git (committed in `41ac3b6c` and `18a230c5`)
- `.env` is NOT in `.gitignore`
- Anyone with repo access has the API key
- The repo has been pushed to GitHub at some point (these are commit hashes)

**P2.** `.env` NOT IN `.gitignore`
- `.gitignore` has entries for `.venv/`, `venv/`, `*.venv/` but NOT `.env`
- Even if removed from tracking, new `.env` files could accidentally be committed

**P3.** 3 DOCX FILES WITH "API KEY" IN FILENAME
- `Claude gmail api key.docx` (13KB), `smichaelcheck gmail api key.docx` (14KB), `~$ichaelcheck gmail api key.docx` (162B) in hyperdocs_3/
- Not currently git-tracked but could be accidentally added
- The `~$` prefix file is a Word temp lock file that shouldn't exist

**P4.** 10 DOCX FILES GIT-TRACKED IN MAIN REPO
- Includes `~$STER_CODE_REVIEW.docx` and `~$TREMELY VERBOSE REPORT.docx` (Word temp files that contain partial content and should never be committed)
- Plan said "user said to keep for now" but temp files (`~$`) are never intentional

---

## CATEGORY Q: DATA INTEGRITY (5 gaps)

**Q1.** 18 PARTIAL SESSIONS — missing Phase 2/3 outputs
- 11 sessions have only Phase 0 output (9 files: enriched, condensed, emergency, safe, metadata, tiers)
- 4 sessions have Phase 1 but no Phase 2/3 (7 files: + explorer, geo, primitives, threads)
- 3 sessions have Phase 1 but missing session_metadata.json (4 files only)

**Q2.** 1 EMPTY SESSION DIRECTORY — `output/session_d64d39c7/` has 0 files

**Q3.** 3 FILES MASQUERADING AS DIRECTORIES
- `output/session_inventory.json` — is a JSON file, not a session directory
- `output/session_profile.html` — is an HTML file, not a session directory
- `output/session_profile.json` — is a JSON file, not a session directory
- These cause the session glob `output/session_*` to include non-session items, potentially confusing batch processors

**Q4.** SYNC_FROM_DEV EXCLUDES `output/` — batch_p2_generator.py never reaches GitHub
- `run_pipeline.py` Phase 2 imports `build_idea_graph` from `output/batch_p2_generator.py`
- sync_from_dev.sh excludes `output/` entirely
- GitHub clone cannot run Phase 2

**Q5.** SYNC_TO_PERMANENT ONLY COVERS 1 OF 4 PROJECT DIRECTORIES
- `CLAUDE_CODE_DIR` hardcoded to one specific project
- 3 other project directories under `~/.claude/projects/` are never synced

---

## CATEGORY R: DEAD CODE (1 gap, summary)

**R1.** 155 ORPHAN PUBLIC FUNCTIONS across all active files
- 54 in phase_0_prep/
- 101 in phase_1_extraction/ through tools/
- These are `def function_name()` (public, not `_private`) that are only referenced in the file where they're defined
- Many are internal helpers called by `main()` within the same file (NOT dead code — just not cross-referenced)
- Some are genuinely dead: never called even within their own file
- Need per-function audit to distinguish "internal helper" from "truly dead"
- NOT blocking — but inflates the codebase

---

## CATEGORY S: SCHEMA NORMALIZER NEVER RUN (1 gap, massive scope)

**S1.** SCHEMA NORMALIZER HAS NEVER BEEN EXECUTED ON THE 270 SESSIONS
- `_normalization_log` present in: **0 of 270** thread_extractions.json files
- Thread extractions schema distribution:
  - Canonical (threads dict): **20** sessions (7%)
  - Old (extractions list): **183** sessions (68%)
  - Threads-as-list: **62** sessions (23%)
  - Missing threads key: **5** sessions (2%)
- Grounded markers: **187** flat / **74** structured / **1** broken
- Idea graph: **258** canonical / **4** broken
- The schema_normalizer.py EXISTS and WORKS (tested in test_schema_normalizer.py) but has **never been run against the actual data**
- This means 93% of thread_extractions.json files are in non-canonical format
- All downstream consumers (generate_dossiers.py, generate_viewer.py, batch_p2_generator.py) must handle ALL variants

---

## CATEGORY T: CRON JOBS BROKEN (2 gaps)

**T1.** GITHUB SYNC CRON IS COMMITTING BUT FAILING TO PUSH
- `sync_from_dev.sh` commits succeed but `git push` fails with: `fatal: could not read Username for 'https://github.com': Device not configured`
- The local ~/Hyperdocs repo has accumulated unpushed commits since the cron was unpaused
- GitHub authentication (HTTPS credentials) is not configured for non-interactive use
- Needs SSH key or credential helper

**T2.** GITHUB SYNC COMMITS EVERY RUN EVEN WHEN PUSHING FAILS
- `sync_from_dev.sh` uses `set -e` but the push failure causes exit AFTER the commit
- Each failed push cycle adds another commit, creating a long chain of unpushed local commits
- When push eventually works, all accumulated commits flood GitHub at once

---

## CATEGORY U: STALE MEMORY.MD CLAIMS (4 gaps)

**U1.** MEMORY.md says "341 enhanced Python files" → actual: **368** (off by 27)
**U2.** MEMORY.md says "492 per-file input extracts" → actual: **497** (off by 5)
**U3.** MEMORY.md says "19 HTML visualizations" → actual: **2** in PERMANENT_HYPERDOCS (off by 17)
**U4.** MEMORY.md says "3 PDFs" → actual: **0** in PERMANENT_HYPERDOCS (all 3 missing)

---

## CATEGORY V: MISSING REFERENCED FILES (2 gaps)

**V1.** `operations_panel.html` — referenced in MEMORY.md Chapter 20, does not exist anywhere in the project tree or PERMANENT_HYPERDOCS

**V2.** wrecktangle.com product files — MEMORY.md Chapter 16 describes landing page, Stripe checkout, webhooks, billing portal. **Zero** files with "wrecktangle", "stripe", "landing", or "checkout" in the name exist anywhere in the project tree. Either deployed externally (Vercel) or never created.

---

## CATEGORY O: CORRECTED FALSE POSITIVES (from previous audits)

**O1.** ~~L15: write_hyperdocs.py:76 `dict | None` SyntaxError on Python 3.9~~ — VERIFIED FALSE. File compiles on Python 3.9.6. Return type annotations are stored as strings, not evaluated at import time. Only fails if `typing.get_type_hints()` is called (unlikely). Downgraded from "latent risk" in N9.

---

## TOTAL COUNT

| Category | Count | Resolved | Remaining | Description |
|----------|-------|----------|-----------|-------------|
| A: Runtime crashes | 5 | 5 | 0 | Duplicate mains, missing import, hard asserts |
| B: Bare excepts | 4 | 4 | 0 | `except:` with no type |
| C: Broad exceptions | 13 | 13 | 0 | `except Exception` → specific types |
| D: Hardcoded paths | 1 | 1 | 0 | Absolute path in batch_p2_generator |
| E: Truncation | 6 | 6 | 0 | All truncations removed (1 no-op deleted, 5 limits removed) |
| F: Missing __init__.py | 9 | 9 | 0 | All 9 created |
| G: Stale hyperdocs | 3 | 3 | 0 | Corrected to exists_on_disk=true |
| H: Reference-session | 4 | 3 | 1 | H1 by design; H2-H4 made conditional |
| I: Beta API | 2 | 2 | 0 | anthropic version pinned >=0.40.0,<1.0.0 |
| J: Data flow refs | 3 | 3 | 0 | Paths updated, count made dynamic |
| K: Schema validation | 2 | 2 | 0 | Normalizer auto-runs; Phase 2 entry check added |
| L: Logical bugs | 22 | 19 | 3 | 19 fixed; L9 N/A (no regex), L10+L12 already resolved |
| M: Cross-file data flow | 8 | 8 | 0 | Config imports, stage contracts, visible failures |
| N: Infrastructure | 11 | 11 | 0 | SSH, sync fixes, file moves, stale copies, deps, tests |
| O: Corrected false positives | -1 | — | — | L15 was wrong |
| P: Security | 4 | 4 | 0 | .gitignore, untrack .env, delete API key docs |
| Q: Data integrity | 5 | 4 | 1 | Q1 needs Opus API to run Phase 2 on 18 partial sessions |
| R: Dead code | 1 | 0 | 1 | 155 orphans — future cleanup |
| S: Schema normalizer | 1 | 1 | 0 | Ran on 286 sessions (2026-02-22) |
| T: Cron jobs broken | 2 | 2 | 0 | SSH remote + push error checking |
| U: Stale MEMORY.md | 4 | 4 | 0 | All numbers corrected |
| V: Missing referenced files | 2 | 0 | 2 | Out of scope (Vercel/external) |
| **TOTAL** | **111** | **103** | **8** | |

### Unresolved gaps (8):
- **H1**: REFERENCE_SESSION_ID — intentional, by design
- **L9**: No greedy regex found — code uses find/rfind, not regex
- **L10**: Guard already existed at line 47-48
- **L12**: Budget subtraction already implemented at line 536-538
- **Q1**: 18 partial sessions need Phase 2 — requires ANTHROPIC_API_KEY
- **R1**: 155 orphan functions — future cleanup task
- **V1**: operations_panel.html — exists in ~/Hyperdocs, not in dev tree
- **V2**: wrecktangle.com files — deployed on Vercel, not in Python project

### Resolution date: 2026-02-22

---

## WHAT IS NOT A GAP

These were flagged by previous audits but are NOT gaps:

1. **extract_threads.py REFERENCE_SESSION_ID** — BY DESIGN. Hand annotations only activate for that session. Other sessions use pattern extraction. This is documented in the file header.

2. **`session_id[:8]` patterns** — These are the session short ID convention, not truncation. Used consistently across all files.

3. **`[:15]`, `[:30]`, `[:100]` in pipeline_health_check.py** — Display truncation for error messages in test output. Not data truncation.

4. **`[:10]` in generate_viewer.py line 649** — Display limit for rendering HTML (shows first 10 items). Not data loss.

5. **Obsolete directory** — Contains Phase 5 code that tests still reference. Kept intentionally.
