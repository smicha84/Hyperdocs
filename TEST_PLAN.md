# Hyperdocs Pipeline — Remaining Test Plan

Generated: 2026-02-11
Status: Phase 0 batch complete (279/279), Phase 1 tested on 5 sessions, Phase 2-4 have old data from prior batch

## Current State

| Phase | Status | Sessions | Notes |
|-------|--------|----------|-------|
| Phase 0 | COMPLETE | 279/279 | All fixes applied: skill injection, content-ref, protocol suppression, char-per-line |
| Phase 1 | 5 TESTED | 5/279 | 5 sessions reprocessed with fixed orchestrator, 274 have old batch data |
| Phase 2 | OLD DATA | 278 | idea_graph.json + synthesis.json from prior batch (pre-P0 fixes) |
| Phase 3 | OLD DATA | 278 | file_dossiers.json from prior batch |
| Phase 4 | OLD DATA | 456 hyperdocs | Written from old Phase 3 dossiers |
| Phase 5 | PARTIAL | Ground truth ran on 261 sessions (73% credibility) |

## Remaining Work — Ordered by Priority

### Step 1: Full Phase 1 Batch (HIGH PRIORITY)
- **What**: Reprocess all 279 sessions through phase1_redo_orchestrator.py
- **Why**: Old Phase 1 data was produced before the 14 P0 fixes + skill injection fix. All downstream phases depend on Phase 1 quality.
- **Estimated time**: ~10 min/session x 279 sessions = ~46 hours sequential
- **Verification**: Activity monitor at localhost:8800 tracks live progress. Explorer agent runs as pass 4 on every session and rates quality.
- **Success criteria**: All 279 sessions complete, 0 failed passes, no significant_issues quality ratings in Explorer verification

### Step 2: Phase 1 Quality Spot-Check (MEDIUM PRIORITY)
- **What**: After the batch, pick 10 random sessions and deep-inspect all 4 output files
- **Check for**:
  - Thread Analyst: 6 named threads present, entries reference valid message indices
  - Geological Reader: micro/meso/macro observations present, metaphor is session-specific
  - Primitives Tagger: 100% tag coverage (tagged == expected), all 7 primitives present per message
  - Explorer: quality rating, severity of flagged issues, no recurring systematic problems
- **Tools**: Reuse the validation script from today's testing
- **Success criteria**: No new systematic issues. Minor_issues acceptable. Any significant/high issues must be investigated.

### Step 3: Phase 2 Redo (MEDIUM PRIORITY)
- **What**: Reprocess all sessions through Phase 2 (Idea Graph + Synthesis)
- **Why**: Phase 2 reads Phase 1 outputs. New Phase 1 data = Phase 2 needs refresh.
- **Depends on**: Step 1 (all Phase 1 complete)
- **What Phase 2 produces**:
  - idea_graph.json: Nodes (idea-states) + edges (transitions)
  - synthesis.json: 6-pass temperature ramp analysis
  - grounded_markers.json: Practical developer guidance
- **Verification**: Check node/edge counts, verify grounded markers reference real Phase 1 data
- **NOTE**: Phase 2 may need its own orchestrator similar to phase1_redo_orchestrator.py

### Step 4: Phase 3 Redo (MEDIUM PRIORITY)
- **What**: Reprocess file_dossiers.json + claude_md_analysis.json
- **Why**: Phase 3 (File Mapper) reads Phase 1+2 outputs to build per-file dossiers
- **Depends on**: Step 3 (all Phase 2 complete)
- **Verification**: Check dossier schema consistency, file counts, session cross-references

### Step 5: Phase 4 Hyperdoc Regeneration (LOWER PRIORITY)
- **What**: Re-aggregate dossiers (aggregate_dossiers.py) and regenerate hyperdocs
- **Why**: Phase 4 writes hyperdocs from Phase 3 dossiers. New dossiers = new hyperdocs.
- **Depends on**: Step 4 (all Phase 3 complete)
- **Verification**: Compare new hyperdocs against old ones. Check layered format, completeness.

### Step 6: Phase 5 Ground Truth Revalidation (LOWER PRIORITY)
- **What**: Re-run claim extraction + ground truth verification on the new pipeline output
- **Why**: The 73% credibility score was computed on old data. New P0 fixes likely change the results.
- **Depends on**: Step 5 (new hyperdocs exist)
- **Verification**: Compare new credibility % against old 73%. Any drop needs investigation.

## Fixes Applied Today (Feb 11, 2026)

1. **Skill injection detection** — `detect_protocol_message()` now catches `.claude/skills/` content injected by slash commands. Marks as `protocol_type=skill_injection`, forces to tier 1.

2. **Content-referential signal inflation** — `detect_content_referential_signals()` now uses two strategies: (a) analytical indicators on assistant messages, (b) signal density anomaly detection on either role (failure>20 or frustration>10 on messages >1000 chars).

3. **Dead code cleanup in geological_reader.py** — `opus_parse_message()`, `opus_analyze_session()`, `load_all_sessions()`, and `opus_get_statistics()` replaced with guarded stubs that raise NotImplementedError with explanation.

4. **Hardcoded session data in extract_threads.py** — `USER_IDEA_ANNOTATIONS` and `NARRATIVE_ANNOTATIONS` now only activate when processing the reference session (3b7084d5). All other sessions use pure pattern-based extraction.

5. **Path fix in tag_primitives.py** — File paths now use config.py / env vars instead of `Path(__file__).parent` (which assumed the script lived in the session directory).

6. **Primitives Tagger continuation** — phase1_redo_orchestrator.py detects incomplete tagging and makes a second API call for remaining messages, achieving 100% coverage on all tested sessions.

7. **Content previews from safe_tier4** — Primitives Tagger now receives actual content previews (from safe_tier4.json) instead of empty strings, improving tagging accuracy.
