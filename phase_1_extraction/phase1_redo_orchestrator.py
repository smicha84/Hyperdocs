#!/usr/bin/env python3
"""
Phase 1 Full Redo Orchestrator — Reprocesses ALL sessions through Phase 1.

Uses the Anthropic API directly (one call at a time). For each session:
  1. Thread Analyst pass → thread_extractions.json
  2. Geological Reader pass → geological_notes.json
  3. Primitives Tagger pass → semantic_primitives.json
  4. Free Explorer VERIFICATION pass → explorer_notes.json
     (reads all 3 prior outputs + raw data, verifies + discovers)

The Explorer runs LAST deliberately — it verifies Phase 0 data quality
and the other 3 agents' outputs before adding its own discoveries.

Progress is written to ~/PERMANENT_HYPERDOCS/indexes/phase1_redo_progress.json
which the tracking HTML reads.

Usage:
    python3 phase1_redo_orchestrator.py                  # process all sessions
    python3 phase1_redo_orchestrator.py --start-from 50  # resume from session 50
    python3 phase1_redo_orchestrator.py --session session_0012ebed  # one session

CHANGE LOG — Prompt & Config Fixes
====================================
Round 1 (Feb 11): Initial implementation
  - 4 agent prompts (Thread Analyst, Geological Reader, Primitives Tagger, Explorer)
  - MAX_TOKENS=16000, no thinking budget
  - Explorer runs last with verification mandate

Round 2 (Feb 11): Streaming + thinking
  - MAX_TOKENS raised to 64000, THINKING_BUDGET=32000
  - Switched from client.messages.create() to client.messages.stream()
    because extended thinking requires streaming for long operations
  - Added .env file loading for ANTHROPIC_API_KEY

Round 3 (Feb 11): Primitives truncation fix + content-referential warning
  - Primitives Tagger prompt: pre-filters to tier 2+ messages only (was sending
    all 1317 messages including 1111 tier-1 skips). Result: 206 tagged (was 23).
  - Added CRITICAL WARNING to Primitives Tagger prompt about content-referential
    filter_signals. Explorer found 5 messages mistagged because the Tagger treated
    failure/frustration keyword counts as emotional state indicators.
    Source: Explorer verification Round 2 on session_0012ebed.

Round 4 (Feb 11): Output + prompt fixes
  - MAX_TOKENS raised to 128000 (was 64000) to prevent Primitives Tagger
    output truncation on large sessions (206 messages need ~100K output).
  - Thread Analyst prompt: added CRITICAL warning against fabricating
    round-number indices (900, 1000). Must only reference indices from data.
  - Session continuation detection added to Phase 0 (FIX 12).
  - Content-referential detection further improved in Phase 0 (FIX 14).

Test iterations on session_0012ebed:
  Iter 1: significant_issues (6 P0, 4 thread, 4 geo, 4 prims issues)
  Iter 2: significant_issues (4 P0, 3 thread, 2 geo, 5 prims) — 206 tagged
  Iter 3: significant_issues (4 P0, 3 thread, 3 geo, 3 prims) — 169 tagged
  Iter 4: significant_issues (3 P0 minor, 1 thread CRITICAL json fail, 3 geo minor, 3 prims moderate)

Round 5 (Feb 11): JSON recovery + prompt hardening
  - JSON parse fallback: 3-strategy recovery (outermost braces, trailing comma fix,
    truncation repair by counting unmatched braces). Thread Analyst failed with
    malformed JSON in iter 4 — the 7603-char cutoff suggests output truncation.
  - MAX_TOKENS already at 128K, so the issue is likely the model stopping mid-JSON.
  - Primitives Tagger prompt: added WRONG examples with corrections for content-ref
    misclassification. "IGNORE filter_signals entirely for emotional tagging."
  - Geological Reader prompt: added RULES about only citing verifiable data,
    using temporal gaps for phase boundaries, content-ref signal awareness.
  - Thread Analyst prompt: already has fabrication warning from Round 4.

  Iter 5: Running...
"""

import json
import os
import sys
import time
from pathlib import Path
from datetime import datetime, timezone

import anthropic

# ── Config ──────────────────────────────────────────────────────────────
REPO = Path(__file__).resolve().parent.parent  # hyperdocs_3 root
try:
    from config import SESSIONS_STORE_DIR, INDEXES_DIR
    SESSIONS_DIR = SESSIONS_STORE_DIR
    PROGRESS_FILE = INDEXES_DIR / "phase1_redo_progress.json"
except ImportError:
    SESSIONS_DIR = Path.home() / "PERMANENT_HYPERDOCS" / "sessions"
    PROGRESS_FILE = Path.home() / "PERMANENT_HYPERDOCS" / "indexes" / "phase1_redo_progress.json"
MODEL = "claude-opus-4-6"
MAX_TOKENS = 128000     # Hard API limit for claude-opus-4-6 output

# Load API key from .env file
ENV_FILE = REPO / ".env"
if ENV_FILE.exists():
    for line in ENV_FILE.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, val = line.split("=", 1)
            os.environ[key.strip()] = val.strip()

client = anthropic.Anthropic()

# Schema normalizer — standardizes the 886 JSON schema variants across sessions
sys.path.insert(0, str(REPO / "phase_0_prep"))
from schema_normalizer import NORMALIZERS, normalize_file

# ── Duplicate detection ────────────────────────────────────────────────
# Same logic as batch_phase0_reprocess.py — skip sessions that are copies
# of conversations already processed under their canonical UUID.
try:
    from config import CHAT_ARCHIVE_DIR, INDEXES_DIR as _IDX
    CHAT_DIR = CHAT_ARCHIVE_DIR / "sessions"
    MEASUREMENTS_FILE = _IDX / "session_measurements.json"
except ImportError:
    CHAT_DIR = Path.home() / "PERMANENT_CHAT_HISTORY" / "sessions"
    MEASUREMENTS_FILE = Path.home() / "PERMANENT_HYPERDOCS" / "indexes" / "session_measurements.json"


def _build_duplicate_skip_ids():
    """Return set of short IDs that are duplicate copies of other sessions."""
    if not CHAT_DIR.exists():
        return set()
    uuid_files = {}
    for f in CHAT_DIR.iterdir():
        if f.suffix != ".jsonl":
            continue
        stem = f.stem
        if '_' in stem and not stem.startswith('agent-'):
            prefix, uuid_part = stem.split('_', 1)
        else:
            prefix = None
            uuid_part = stem
        if uuid_part not in uuid_files:
            uuid_files[uuid_part] = []
        uuid_files[uuid_part].append({'prefix': prefix, 'short': f.stem[:8]})

    skip_ids = set()
    for uuid_part, files in uuid_files.items():
        if len(files) < 2:
            continue
        uuid_short = uuid_part[:8]
        for fi in files:
            if fi['prefix'] is not None and fi['short'] != uuid_short:
                skip_ids.add(fi['short'])
    return skip_ids


DUPLICATE_SKIP_IDS = _build_duplicate_skip_ids()


# ── Agent Prompts ───────────────────────────────────────────────────────

def thread_analyst_prompt(session_id, safe_condensed, safe_tier4, session_metadata):
    return f"""You are the Thread Analyst for the Hyperdocs pipeline. Extract 6 analytical threads from session {session_id}.

CRITICAL: Only reference msg_index values that actually appear in the input data.
Do NOT fabricate round-number indices (e.g., 900, 1000) as approximations.
If you cannot determine the exact index, omit the entry or note it as estimated.

INPUT DATA:
=== session_metadata.json ===
{json.dumps(session_metadata, indent=2)}

=== safe_tier4.json (priority messages, metadata only) ===
{json.dumps(safe_tier4, indent=2)}

=== safe_condensed.json (all messages, metadata only) ===
{json.dumps(safe_condensed, indent=2)}

OUTPUT: Return ONLY valid JSON with this EXACT structure (no markdown, no explanation):
{{
  "session_id": "{session_id}",
  "generated_at": "{datetime.now(timezone.utc).isoformat()}",
  "generator": "Phase 1 - Thread Analyst (Opus)",
  "_normalized_at": "{datetime.now(timezone.utc).isoformat()}",
  "threads": {{
    "ideas": {{"description": "Ideas that emerged, evolved, or were abandoned", "entries": [{{"msg_index": 0, "content": "...", "significance": "high|medium|low"}}]}},
    "reactions": {{"description": "Emotional reactions, frustration peaks, breakthroughs", "entries": []}},
    "software": {{"description": "Files created, modified, deleted", "entries": []}},
    "code": {{"description": "Code patterns, architecture decisions", "entries": []}},
    "plans": {{"description": "Plans made, followed, or abandoned", "entries": []}},
    "behavior": {{"description": "Claude behavioral patterns observed", "entries": []}}
  }}
}}

IMPORTANT: Return ONLY the JSON. No markdown code fences. No explanation text."""


def geological_reader_prompt(session_id, safe_condensed, safe_tier4, session_metadata):
    return f"""You are the Geological Reader for the Hyperdocs pipeline. Perform multi-resolution analysis of session {session_id}.

RULES:
- Only cite data that appears in the input. Do not infer port numbers, file sizes, or counts not present.
- Use temporal gaps between timestamps to identify phase boundaries (gaps > 30 min are significant).
- Filter signals (failure, frustration) may be content-referential — check if the message DISCUSSES failures vs EXPERIENCES them.
- Distinguish between "session had errors" and "session discussed error handling."

INPUT DATA:
=== session_metadata.json ===
{json.dumps(session_metadata, indent=2)}

=== safe_tier4.json ===
{json.dumps(safe_tier4, indent=2)}

=== safe_condensed.json ===
{json.dumps(safe_condensed, indent=2)}

OUTPUT: Return ONLY valid JSON with this EXACT structure:
{{
  "session_id": "{session_id}",
  "generated_at": "{datetime.now(timezone.utc).isoformat()}",
  "generator": "Phase 1 - Geological Reader (Opus)",
  "_normalized_at": "{datetime.now(timezone.utc).isoformat()}",
  "micro": [{{"observation": "...", "message_range": [0, 0], "evidence": "..."}}],
  "meso": [{{"observation": "...", "message_range": [0, 5], "pattern": "..."}}],
  "macro": [{{"observation": "...", "scope": "full session", "significance": "..."}}],
  "observations": [],
  "geological_metaphor": "..."
}}

Return ONLY the JSON. No markdown. No explanation."""


def _build_tier2plus(safe_condensed, safe_tier4):
    """Build the tier 2+ message list with content previews from safe_tier4."""
    tier2plus = []
    msgs = safe_condensed.get("messages", []) if isinstance(safe_condensed, dict) else safe_condensed
    # Build index→content_preview lookup from safe_tier4
    t4_msgs = safe_tier4.get("messages", []) if isinstance(safe_tier4, dict) else (safe_tier4 if isinstance(safe_tier4, list) else [])
    t4_previews = {}
    for m in t4_msgs:
        idx = m.get("i", m.get("index", -1))
        preview = m.get("content_preview", m.get("c", ""))
        if preview:
            t4_previews[idx] = preview
    if isinstance(msgs, list):
        for m in msgs:
            if m.get("t", m.get("filter_tier", 0)) >= 2:
                idx = m.get("i", m.get("index", 0))
                tier2plus.append({
                    "i": idx,
                    "r": m.get("r", m.get("role", "")),
                    "t": m.get("t", m.get("filter_tier", 0)),
                    "ts": m.get("ts", m.get("timestamp", "")),
                    "cl": m.get("cl", m.get("content_length", 0)),
                    "c": t4_previews.get(idx, m.get("c", "")),
                    "is_protocol": m.get("is_protocol", False),
                    "content_ref": m.get("content_ref", False),
                })
    return tier2plus


def primitives_tagger_prompt(session_id, safe_condensed, safe_tier4, session_metadata, subset_indices=None):
    tier2plus = _build_tier2plus(safe_condensed, safe_tier4)
    if subset_indices is not None:
        tier2plus = [m for m in tier2plus if m["i"] in subset_indices]

    return f"""You are the Primitives Tagger for the Hyperdocs pipeline. Tag ALL of the following tier 2+ messages with the 7 semantic primitives for session {session_id}.

RULE 1 — DIFFERENTIATE. Do NOT assign the same tags to every message.
Each message has different content, different intent, different emotional context.
If you find yourself tagging 3+ consecutive messages with identical primitives, STOP and re-read
the content previews. A user asking a question is NOT the same as an assistant implementing code.
A user expressing frustration is NOT the same as a user giving direction.
Vary your tags. Monotonous tagging is the single most common failure mode of this system.

RULE 2 — IGNORE filter_signals for emotional/confidence tagging.
The filter_signals field (frustration:N, failure:N, architecture:N) counts KEYWORDS in the text.
When a message DISCUSSES failure handling or error patterns, these signals describe the
CONTENT TOPIC, not the author's actual state. A message with failure:4 that says
"I've created a comprehensive implementation plan!" is created/excited, NOT debugged/frustrated.

Check the content_ref field: if content_ref=true, the filter_signals are ABOUT the content,
not about the session dynamics. Treat content_ref=true messages as analytical/creative work.

RULE 3 — Role matters.
User messages: Look for direction-giving, frustration, questions, corrections, approvals.
Assistant messages: Look for implementation, analysis, apology, clarification, overconfidence.
A user saying "fix this" is decided/frustrated/bugfix. An assistant saying "I've fixed it" is
modified/working/confident/bugfix. They should NEVER get the same tags.

The 7 primitives:
1. action_vector: created|modified|debugged|refactored|discovered|decided|abandoned|reverted
2. confidence_signal: experimental|tentative|working|stable|proven|fragile
3. emotional_tenor: frustrated|uncertain|curious|cautious|confident|excited|relieved
4. intent_marker: correctness|performance|maintainability|feature|bugfix|exploration|cleanup
5. friction_log: single sentence describing what went wrong or caused friction (empty string if none)
6. decision_trace: "chose X over Y because Z" (empty string if no decision)
7. disclosure_pointer: "{session_id}:msgN"

INPUT DATA:
=== session_metadata.json ===
{json.dumps(session_metadata, indent=2)}

=== TIER 2+ MESSAGES ONLY ({len(tier2plus)} messages to tag) ===
{json.dumps(tier2plus, indent=2)}

IMPORTANT: You MUST tag ALL {len(tier2plus)} messages above. Do not stop early. Do not truncate.

OUTPUT: Return ONLY valid JSON:
{{
  "session_id": "{session_id}",
  "generated_at": "{datetime.now(timezone.utc).isoformat()}",
  "generator": "Phase 1 - Primitives Tagger (Opus)",
  "_normalized_at": "{datetime.now(timezone.utc).isoformat()}",
  "tagged_messages": [{{"msg_index": 0, "role": "user", "tier": 4, "timestamp": "...", "action_vector": "...", "confidence_signal": "...", "emotional_tenor": "...", "intent_marker": "...", "friction_log": "", "decision_trace": "", "disclosure_pointer": "{session_id}:msg0"}}],
  "distributions": {{}},
  "summary_statistics": {{"total_tier2plus": {len(tier2plus)}, "total_tagged": "MUST EQUAL {len(tier2plus)}"}}
}}

Return ONLY JSON."""


def explorer_verification_prompt(session_id, safe_condensed, safe_tier4, session_metadata,
                                  thread_extractions, geological_notes, semantic_primitives):
    return f"""You are the Free Explorer AND Verification Agent for the Hyperdocs pipeline.

Your job has TWO parts for session {session_id}:

PART 1 — VERIFY: Check the Phase 0 enriched data and the other 3 agents' outputs for errors:
- Are protocol/system messages correctly identified? (is_protocol field)
- Did the char-per-line encoding collapse work? (was_char_encoded field)
- Are content_length values accurate after encoding fix?
- Did the Thread Analyst misidentify system boilerplate as human content?
- Did the Geological Reader build conclusions on measurement bugs?
- Did the Primitives Tagger tag protocol messages as if they were human?
- Are filter signals content-referential (describing analyzed code, not session dynamics)?
- Are error_types actually encountered or just mentioned in discussion?

PART 2 — DISCOVER: Find what the other agents missed:
- Abandoned ideas, surprising patterns, anomalies
- Cross-session connections
- Things that don't fit
- Questions nobody asked

INPUT DATA:
=== session_metadata.json ===
{json.dumps(session_metadata, indent=2)}

=== safe_tier4.json ===
{json.dumps(safe_tier4, indent=2)}

=== safe_condensed.json (first 40K chars) ===
{json.dumps(safe_condensed, indent=2)}

=== thread_extractions.json (from Thread Analyst) ===
{json.dumps(thread_extractions, indent=2)}

=== geological_notes.json (from Geological Reader) ===
{json.dumps(geological_notes, indent=2)}

=== semantic_primitives.json (from Primitives Tagger) ===
{json.dumps(semantic_primitives, indent=2)}

OUTPUT: Return ONLY valid JSON:
{{
  "session_id": "{session_id}",
  "generated_at": "{datetime.now(timezone.utc).isoformat()}",
  "generator": "Phase 1 - Free Explorer + Verification (Opus)",
  "_normalized_at": "{datetime.now(timezone.utc).isoformat()}",
  "observations": [
    {{"id": "obs-001", "observation": "...", "evidence": "...", "significance": "high|medium|low"}}
  ],
  "verification": {{
    "phase0_issues_found": [],
    "thread_analyst_issues": [],
    "geological_reader_issues": [],
    "primitives_tagger_issues": [],
    "overall_data_quality": "clean|minor_issues|significant_issues"
  }},
  "explorer_summary": "..."
}}

Return ONLY JSON. No markdown. No explanation."""


# ── Processing ──────────────────────────────────────────────────────────

def call_opus(prompt, max_retries=3):
    """Make a single Opus API call with extended thinking via streaming.
    Retries on transient errors (overloaded, connection drops). Returns parsed JSON or None."""
    for attempt in range(max_retries):
        try:
            text_parts = []
            with client.beta.messages.stream(
                model=MODEL,
                max_tokens=MAX_TOKENS,
                thinking={"type": "adaptive"},
                betas=["context-1m-2025-08-07"],
                messages=[{"role": "user", "content": prompt}],
            ) as stream:
                for event in stream:
                    if hasattr(event, 'type'):
                        if event.type == 'content_block_start' and hasattr(event, 'content_block'):
                            if event.content_block.type == 'text':
                                pass  # text block starting
                        elif event.type == 'content_block_delta' and hasattr(event, 'delta'):
                            if event.delta.type == 'text_delta':
                                text_parts.append(event.delta.text)

            text = ''.join(text_parts).strip()
            if not text:
                print("    No text in response")
                return None
            # Strip markdown code fences if present
            if text.startswith("```"):
                text = text.split("\n", 1)[1] if "\n" in text else text[3:]
                if text.endswith("```"):
                    text = text[:-3]
                # Also handle ```json
                if text.startswith("json\n"):
                    text = text[5:]
                text = text.strip()
            return json.loads(text)
        except json.JSONDecodeError as e:
            print(f"    JSON parse error: {e}")
            # Try progressively aggressive JSON extraction
            # Strategy 1: find outermost { }
            try:
                start = text.index("{")
                end = text.rindex("}") + 1
                candidate = text[start:end]
                return json.loads(candidate)
            except (ValueError, json.JSONDecodeError):
                pass
            # Strategy 2: try to fix common issues (trailing comma, missing closing)
            try:
                candidate = text[text.index("{"):text.rindex("}") + 1]
                import re as _re
                candidate = _re.sub(r',\s*([}\]])', r'\1', candidate)
                return json.loads(candidate)
            except (ValueError, json.JSONDecodeError):
                pass
            # Strategy 3: truncated JSON — try adding closing braces
            try:
                candidate = text[text.index("{"):]
                opens = candidate.count("{") - candidate.count("}")
                candidate += "}" * opens
                opens_b = candidate.count("[") - candidate.count("]")
                candidate += "]" * opens_b
                return json.loads(candidate)
            except (ValueError, json.JSONDecodeError):
                print(f"    All JSON recovery strategies failed. Response length: {len(text)}")
                return None
        except anthropic.APIError as e:
            error_type = getattr(e, 'status_code', None) or str(e)
            is_transient = 'overloaded' in str(e).lower() or 'rate' in str(e).lower() or '529' in str(error_type)
            if is_transient and attempt < max_retries - 1:
                wait = 30 * (attempt + 1)
                print(f"    API overloaded, retrying in {wait}s (attempt {attempt + 1}/{max_retries})...", end="", flush=True)
                time.sleep(wait)
                continue
            print(f"    API error: {e}")
            return None
        except (OSError, ConnectionError, RuntimeError) as e:
            is_connection = 'peer closed' in str(e).lower() or 'connection' in str(e).lower() or 'chunked' in str(e).lower()
            if is_connection and attempt < max_retries - 1:
                wait = 30 * (attempt + 1)
                print(f"    Connection error, retrying in {wait}s (attempt {attempt + 1}/{max_retries})...", end="", flush=True)
                time.sleep(wait)
                continue
            print(f"    Unexpected error: {e}")
            return None
    return None


def load_session_data(session_dir):
    """Load the safe input files for a session."""
    files = {}
    for fname in ["safe_condensed.json", "safe_tier4.json", "session_metadata.json"]:
        fpath = session_dir / fname
        if fpath.exists():
            with open(fpath) as f:
                files[fname.replace(".json", "")] = json.load(f)
        else:
            files[fname.replace(".json", "")] = {}
    return files


# ── Commitments ────────────────────────────────────────────────────────
# Loaded once, prepended to every prompt sent to the API.
CLAUDE_MD = Path.home() / ".claude" / "CLAUDE.md"
COMMITMENTS_TEXT = CLAUDE_MD.read_text() if CLAUDE_MD.exists() else ""


def _prepend_commitments(prompt):
    """Prepend the full 12 commitments to a prompt."""
    if COMMITMENTS_TEXT:
        return f"""COMMITMENTS (these govern all my behavior):
{COMMITMENTS_TEXT}

---

{prompt}"""
    return prompt


# ── Chunking ───────────────────────────────────────────────────────────
import tiktoken
_enc = tiktoken.get_encoding("cl100k_base")


def _chunk_messages(messages, budget):
    """Split messages into chunks that fit within the token budget.

    Each chunk contains only whole messages. If a message doesn't fit
    in the current chunk, it becomes the first message of the next chunk.
    One session per prompt — chunks are never mixed across sessions.
    """
    chunks = []
    current = []
    current_tokens = 0

    for m in messages:
        msg_tokens = len(_enc.encode(json.dumps(m)))
        if current_tokens + msg_tokens > budget and current:
            chunks.append(current)
            current = []
            current_tokens = 0
        current.append(m)
        current_tokens += msg_tokens

    if current:
        chunks.append(current)
    return chunks


def _needs_chunking(data):
    """Check if a session's data exceeds the single-prompt budget."""
    condensed = data.get("safe_condensed", {})
    msgs = condensed.get("messages", []) if isinstance(condensed, dict) else condensed
    total_tokens = sum(len(_enc.encode(json.dumps(m))) for m in msgs)

    # Budget = API limit - commitments - max instruction overhead
    commitments_tokens = len(_enc.encode(COMMITMENTS_TEXT)) if COMMITMENTS_TEXT else 0
    # Use 4000 as conservative instruction overhead (actual is ~758 max)
    budget = 872000 - commitments_tokens - 4000
    return total_tokens > budget, budget, total_tokens


def _make_chunk_data(data, chunk_msgs):
    """Create a data dict with only the messages in this chunk."""
    chunk_indices = {m.get("i", m.get("index", -1)) for m in chunk_msgs}
    chunk_data = {
        "safe_condensed": {"messages": chunk_msgs, "count": len(chunk_msgs)},
        "safe_tier4": data["safe_tier4"],  # tier4 is small, send in full
        "session_metadata": data["session_metadata"],
    }
    return chunk_data


def _merge_thread_results(results_list):
    """Merge thread extraction results from multiple chunks."""
    merged = results_list[0] if results_list else {}
    for result in results_list[1:]:
        for thread_name, thread_data in result.get("threads", {}).items():
            if thread_name not in merged.get("threads", {}):
                merged.setdefault("threads", {})[thread_name] = thread_data
            elif isinstance(thread_data, dict) and "entries" in thread_data:
                merged["threads"][thread_name].setdefault("entries", []).extend(
                    thread_data.get("entries", [])
                )
    return merged


def _merge_geo_results(results_list):
    """Merge geological reader results from multiple chunks."""
    merged = results_list[0] if results_list else {}
    for result in results_list[1:]:
        for level in ("micro", "meso", "macro", "observations"):
            if level in result:
                merged.setdefault(level, []).extend(result[level])
    return merged


def _merge_prim_results(results_list):
    """Merge primitives tagger results from multiple chunks."""
    merged = results_list[0] if results_list else {}
    for result in results_list[1:]:
        merged.setdefault("tagged_messages", []).extend(
            result.get("tagged_messages", [])
        )
    merged["tagged_messages"] = sorted(
        merged.get("tagged_messages", []),
        key=lambda m: m.get("msg_index", m.get("i", 0))
    )
    return merged


def process_session(session_dir, progress):
    """Run all 4 Phase 1 passes on one session.

    For sessions that fit in a single prompt: one API call per agent.
    For sessions that need chunking: one API call per chunk per agent,
    results merged. One session per prompt — never mixed.
    """
    session_id = session_dir.name
    data = load_session_data(session_dir)

    results = {"session": session_id, "passes": {}, "errors": []}

    # Check if this session needs chunking
    needs_split, budget, total_tokens = _needs_chunking(data)
    if needs_split:
        condensed_msgs = data["safe_condensed"].get("messages", [])
        chunks = _chunk_messages(condensed_msgs, budget)
        print(f"    [{len(chunks)} chunks, {total_tokens:,} tokens]")
    else:
        chunks = None  # Single prompt

    # ── Pass 1: Thread Analyst ──
    print(f"    Thread Analyst...", end="", flush=True)
    t0 = time.time()
    if chunks:
        chunk_results = []
        for ci, chunk in enumerate(chunks):
            chunk_data = _make_chunk_data(data, chunk)
            prompt = _prepend_commitments(thread_analyst_prompt(
                session_id, chunk_data["safe_condensed"], chunk_data["safe_tier4"], chunk_data["session_metadata"]
            ))
            r = call_opus(prompt)
            if r:
                chunk_results.append(r)
                print(f" c{ci+1}", end="", flush=True)
        thread_result = _merge_thread_results(chunk_results) if chunk_results else None
    else:
        prompt = _prepend_commitments(thread_analyst_prompt(
            session_id, data["safe_condensed"], data["safe_tier4"], data["session_metadata"]
        ))
        thread_result = call_opus(prompt)
    dt = time.time() - t0
    if thread_result:
        with open(session_dir / "thread_extractions.json", "w") as f:
            json.dump(thread_result, f, indent=2)
        threads = thread_result.get("threads", {})
        n_entries = sum(len(v.get("entries", [])) if isinstance(v, dict) else 0 for v in threads.values())
        results["passes"]["thread_analyst"] = {"status": "ok", "entries": n_entries, "time": round(dt)}
        print(f" {n_entries} entries ({dt:.0f}s)")
    else:
        results["passes"]["thread_analyst"] = {"status": "failed", "time": round(dt)}
        results["errors"].append("thread_analyst failed")
        print(f" FAILED ({dt:.0f}s)")

    # ── Pass 2: Geological Reader ──
    print(f"    Geological Reader...", end="", flush=True)
    t0 = time.time()
    if chunks:
        chunk_results = []
        for ci, chunk in enumerate(chunks):
            chunk_data = _make_chunk_data(data, chunk)
            prompt = _prepend_commitments(geological_reader_prompt(
                session_id, chunk_data["safe_condensed"], chunk_data["safe_tier4"], chunk_data["session_metadata"]
            ))
            r = call_opus(prompt)
            if r:
                chunk_results.append(r)
                print(f" c{ci+1}", end="", flush=True)
        geo_result = _merge_geo_results(chunk_results) if chunk_results else None
    else:
        prompt = _prepend_commitments(geological_reader_prompt(
            session_id, data["safe_condensed"], data["safe_tier4"], data["session_metadata"]
        ))
        geo_result = call_opus(prompt)
    dt = time.time() - t0
    if geo_result:
        with open(session_dir / "geological_notes.json", "w") as f:
            json.dump(geo_result, f, indent=2)
        n_obs = len(geo_result.get("micro", [])) + len(geo_result.get("meso", [])) + len(geo_result.get("macro", []))
        results["passes"]["geological_reader"] = {"status": "ok", "observations": n_obs, "time": round(dt)}
        print(f" {n_obs} observations ({dt:.0f}s)")
    else:
        results["passes"]["geological_reader"] = {"status": "failed", "time": round(dt)}
        results["errors"].append("geological_reader failed")
        print(f" FAILED ({dt:.0f}s)")

    # ── Pass 3: Primitives Tagger ──
    print(f"    Primitives Tagger...", end="", flush=True)
    t0 = time.time()
    tier2plus_all = _build_tier2plus(data["safe_condensed"], data["safe_tier4"])
    expected_count = len(tier2plus_all)

    if chunks:
        # For chunked sessions, tag each chunk separately then merge
        chunk_results = []
        for ci, chunk in enumerate(chunks):
            chunk_data = _make_chunk_data(data, chunk)
            prompt = _prepend_commitments(primitives_tagger_prompt(
                session_id, chunk_data["safe_condensed"], chunk_data["safe_tier4"], chunk_data["session_metadata"]
            ))
            r = call_opus(prompt)
            if r:
                chunk_results.append(r)
                n = len(r.get("tagged_messages", []))
                print(f" c{ci+1}({n})", end="", flush=True)
        prim_result = _merge_prim_results(chunk_results) if chunk_results else None
    else:
        all_expected_indices = {m["i"] for m in tier2plus_all}
        prompt = _prepend_commitments(primitives_tagger_prompt(
            session_id, data["safe_condensed"], data["safe_tier4"], data["session_metadata"]
        ))
        prim_result = call_opus(prompt)

        # Continuation loop for single-prompt sessions
        if prim_result:
            n_tagged = len(prim_result.get("tagged_messages", []))
            max_continuations = 10
            continuation_round = 0
            while n_tagged < expected_count and n_tagged > 0 and continuation_round < max_continuations:
                continuation_round += 1
                tagged_indices = {m.get("msg_index", m.get("i", -1)) for m in prim_result["tagged_messages"]}
                remaining_indices = all_expected_indices - tagged_indices
                if not remaining_indices:
                    break
                print(f" {n_tagged}/{expected_count}, continuing (round {continuation_round})...", end="", flush=True)
                t1 = time.time()
                cont_prompt = _prepend_commitments(primitives_tagger_prompt(
                    session_id, data["safe_condensed"], data["safe_tier4"],
                    data["session_metadata"], subset_indices=remaining_indices
                ))
                cont_result = call_opus(cont_prompt)
                dt += time.time() - t1
                if cont_result and cont_result.get("tagged_messages"):
                    prim_result["tagged_messages"].extend(cont_result["tagged_messages"])
                    prev_tagged = n_tagged
                    n_tagged = len(prim_result["tagged_messages"])
                    if n_tagged == prev_tagged:
                        break
                else:
                    break
            prim_result["tagged_messages"].sort(key=lambda m: m.get("msg_index", m.get("i", 0)))
            prim_result.pop("_note", None)

    dt = time.time() - t0
    if prim_result:
        n_tagged = len(prim_result.get("tagged_messages", []))
        with open(session_dir / "semantic_primitives.json", "w") as f:
            json.dump(prim_result, f, indent=2)
        results["passes"]["primitives_tagger"] = {"status": "ok", "tagged": n_tagged, "expected": expected_count, "time": round(dt)}
        print(f" {n_tagged}/{expected_count} tagged ({dt:.0f}s)")
    else:
        results["passes"]["primitives_tagger"] = {"status": "failed", "time": round(dt)}
        results["errors"].append("primitives_tagger failed")
        print(f" FAILED ({dt:.0f}s)")

    # ── Pass 4: Free Explorer + Verification (LAST) ──
    # Reads merged outputs from passes 1-3 + session data.
    # For chunked sessions, it gets the merged results — no per-chunk calls needed.
    thread_data = thread_result or {}
    geo_data = geo_result or {}
    prim_data = prim_result or {}

    print(f"    Explorer + Verification...", end="", flush=True)
    t0 = time.time()
    prompt = _prepend_commitments(explorer_verification_prompt(
        session_id, data["safe_condensed"], data["safe_tier4"], data["session_metadata"],
        thread_data, geo_data, prim_data
    ))
    explorer_result = call_opus(prompt)
    dt = time.time() - t0
    if explorer_result:
        with open(session_dir / "explorer_notes.json", "w") as f:
            json.dump(explorer_result, f, indent=2)
        n_obs = len(explorer_result.get("observations", []))
        verification = explorer_result.get("verification", {})
        quality = verification.get("overall_data_quality", "unknown")
        results["passes"]["explorer"] = {"status": "ok", "observations": n_obs, "quality": quality, "time": round(dt)}
        results["verification"] = verification
        print(f" {n_obs} obs, quality={quality} ({dt:.0f}s)")
    else:
        results["passes"]["explorer"] = {"status": "failed", "time": round(dt)}
        results["errors"].append("explorer failed")
        print(f" FAILED ({dt:.0f}s)")

    return results


def update_progress(progress, session_result, idx, total):
    """Update the progress JSON file."""
    progress["updated_at"] = datetime.now(timezone.utc).isoformat()
    progress["current_session"] = idx + 1
    progress["total_sessions"] = total
    progress["pct_complete"] = round((idx + 1) / total * 100, 1)

    if session_result["errors"]:
        progress["failed"].append(session_result)
    else:
        progress["completed"].append({
            "session": session_result["session"],
            "passes": session_result["passes"],
            "verification": session_result.get("verification", {}),
        })

    # Accumulate totals
    for pass_name, pass_result in session_result["passes"].items():
        if pass_result["status"] == "ok":
            progress["totals"]["successful_passes"] += 1
        else:
            progress["totals"]["failed_passes"] += 1

    # Write progress
    with open(PROGRESS_FILE, "w") as f:
        json.dump(progress, f, indent=2, default=str)


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--start-from", type=int, default=0)
    parser.add_argument("--session", type=str, default=None)
    args = parser.parse_args()

    print("=" * 70)
    print("Phase 1 Full Redo — All Sessions, Sequential")
    print(f"Model: {MODEL}")
    print(f"Started: {datetime.now(timezone.utc).isoformat()}")
    print("=" * 70)

    # Get sessions to process (excluding duplicates)
    if args.session:
        session_dirs = [SESSIONS_DIR / args.session]
    else:
        all_dirs = sorted(
            d for d in SESSIONS_DIR.iterdir()
            if d.is_dir() and d.name.startswith("session_")
            and (d / "safe_condensed.json").exists()
        )
        # Skip duplicates
        session_dirs = [
            d for d in all_dirs
            if d.name.replace("session_", "") not in DUPLICATE_SKIP_IDS
        ]
        skipped_dupes = len(all_dirs) - len(session_dirs)
        if skipped_dupes > 0:
            print(f"Skipped {skipped_dupes} duplicate sessions")

    total = len(session_dirs)
    print(f"Sessions to process: {total}")
    print(f"Starting from: {args.start_from}")
    print()

    # Initialize progress
    progress = {
        "operation": "Phase 1 Full Redo",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "current_session": 0,
        "total_sessions": total,
        "pct_complete": 0,
        "completed": [],
        "failed": [],
        "totals": {"successful_passes": 0, "failed_passes": 0},
    }
    with open(PROGRESS_FILE, "w") as f:
        json.dump(progress, f, indent=2)

    start_time = time.time()

    for idx, sd in enumerate(session_dirs):
        if idx < args.start_from:
            continue

        elapsed = time.time() - start_time
        rate = (idx - args.start_from + 1) / elapsed if elapsed > 0 and idx > args.start_from else 0.01
        remaining = (total - idx - 1) / rate if rate > 0 else 0

        print(f"\n[{idx+1}/{total}] {sd.name} (elapsed: {elapsed/60:.0f}m, remaining: ~{remaining/60:.0f}m)")

        result = process_session(sd, progress)
        update_progress(progress, result, idx, total)

    elapsed = time.time() - start_time
    progress["completed_at"] = datetime.now(timezone.utc).isoformat()
    progress["total_duration_seconds"] = round(elapsed)
    with open(PROGRESS_FILE, "w") as f:
        json.dump(progress, f, indent=2, default=str)

    print()
    print("=" * 70)
    print(f"Phase 1 Full Redo — Complete")
    print(f"  Sessions: {total}")
    print(f"  Successful passes: {progress['totals']['successful_passes']}")
    print(f"  Failed passes: {progress['totals']['failed_passes']}")
    print(f"  Duration: {elapsed/60:.0f} minutes")
    print(f"  Progress file: {PROGRESS_FILE}")
    print("=" * 70)


if __name__ == "__main__":
    main()
