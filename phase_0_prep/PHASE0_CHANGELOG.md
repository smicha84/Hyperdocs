# Phase 0 Data Quality Fix Log

## deterministic_prep.py — Fix Iterations

### Round 1 (Feb 10, commit 3dafbda)
- FIX 1: Protocol message detection (XML wrappers, /clear boilerplate)
- FIX 2: Output token counter bug (upstream in ClaudeSessionReader — noted)
- FIX 3: Mentioned vs encountered errors (error_context field)
- FIX 4: Tool failure detection (<synthetic> model errors)
- FIX 5: Subagent session detection (_agent- suffix)
- FIX 6: Character-per-line encoding collapse
- FIX 7: Content-referential signal tagging

### Round 2 (Feb 11)
- FIX 8: Frustration peaks restricted to user messages only
- FIX 9: Profanity validation against collapsed content

### Round 3 (Feb 11)
- FIX 10: Content-referential threshold lowered (2 indicators + 500 chars)
- FIX 11: Primitives Tagger prompt warning (in orchestrator)

### Round 4 (Feb 11)
- FIX 12: Session continuation profanity leak detection
- FIX 13: Tool_result wrapper detection for human_messages (not yet impl)
- FIX 14: Content-referential fallback using signal counts (not yet impl)
- NOTE: Multiple edit cycles lost helper functions due to not reading file first.
  Commitment #1 violation caused 3+ wasted Opus API runs (~$60-90).

### Round 5 (Feb 11)
- JSON parse 3-strategy recovery in orchestrator
- Primitives Tagger: explicit WRONG/CORRECT examples for content-ref
- Geological Reader: verifiable-data-only rules
- Thread Analyst: fabrication warning for round-number indices
- MAX_TOKENS raised to 128K

## Test Iterations on session_0012ebed (1317 msgs)
| Iter | Quality | P0 Issues | Thread | Geo | Prims | Notes |
|------|---------|-----------|--------|-----|-------|-------|
| 1 | significant | 6 high | 4 | 4 | 4 | First run with fixes |
| 2 | significant | 4 high | 3 | 2 | 5 | 206 tagged (was 23) |
| 3 | significant | 4 high | 3 | 3 | 3 | Fixes weren't in loop |
| 4 | significant | 3 minor | 1 critical | 3 minor | 3 moderate | Thread JSON crash |
| 5 | **minor** | 4 (1 sig) | 2 minor | 3 minor | 3 minor | Breakthrough |

## Cross-Validation on session_d8367f49 (149 msgs, medium)
| Iter | Quality | P0 | Thread | Geo | Prims | Notes |
|------|---------|-----|--------|-----|-------|-------|
| 1 | **minor** | 4 (1 high upstream) | 2 low | 2 low | 4 low-med | Geo correctly handled content-ref signals |

## Remaining Issues (not in deterministic_prep.py)
- total_output_tokens bug: upstream in ClaudeSessionReader
- False file detection ("mentioned.py"): upstream in MetadataExtractor regex
- Tier-4 excludes user frustration peaks: upstream in MessageFilter
- Protocol msg not visible in safe_condensed: needs prepare_agent_data.py update
