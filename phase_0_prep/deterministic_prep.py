#!/usr/bin/env python3
"""
Phase 0: Deterministic Prep
============================

Runs ALL free Python extractors on a reference session, producing one
enriched_session.json that all extraction agents will read.

Zero LLM cost. Pure Python metadata extraction, filtering, behavior analysis.

Reuses existing V5 modules:
  - ClaudeSessionReader  → parse JSONL into structured messages
  - MetadataExtractor    → 50+ signals per message (files, errors, frustration)
  - MessageFilter        → 4-tier classification (skip/basic/standard/priority)
  - ClaudeBehaviorAnalyzer → context damage flags on assistant messages

Usage:
    python3 deterministic_prep.py
"""

import os
import sys
import json
import hashlib
from pathlib import Path
from datetime import datetime
from collections import defaultdict

# Import V5 modules from parent directory (improved versions, no LLM calls, no hardcoded paths)
# Works both as `python3 phase_0_prep/deterministic_prep.py` and when imported as module
try:
    from phase_0_prep.claude_session_reader import ClaudeSessionReader, ClaudeMessage, ClaudeSession
    from phase_0_prep.geological_reader import GeologicalMessage
    from phase_0_prep.metadata_extractor import MetadataExtractor
    from phase_0_prep.message_filter import MessageFilter
    from phase_0_prep.claude_behavior_analyzer import ClaudeBehaviorAnalyzer
except ImportError:
    from claude_session_reader import ClaudeSessionReader, ClaudeMessage, ClaudeSession
    from geological_reader import GeologicalMessage
    from metadata_extractor import MetadataExtractor
    from message_filter import MessageFilter
    from claude_behavior_analyzer import ClaudeBehaviorAnalyzer

# ── Configuration ──────────────────────────────────────────────────────────
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
try:
    from config import SESSION_ID, get_session_file, get_session_output_dir
    SESSION_FILE = get_session_file()
    OUTPUT_DIR = get_session_output_dir()
except ImportError:
    SESSION_ID = os.getenv("HYPERDOCS_SESSION_ID", "")
    SESSION_FILE = Path(os.getenv("HYPERDOCS_CHAT_HISTORY", ""))
    OUTPUT_DIR = Path(os.getenv("HYPERDOCS_OUTPUT_DIR", "./output")) / f"session_{SESSION_ID[:8]}"
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


import re

# ── Phase 0 Data Quality Fixes ─────────────────────────────────────────────
# These fixes address 9 systemic bugs discovered by Explorer agents across
# 17 sessions on Feb 10, 2026. Each fix traces to a specific grounded marker.

PROTOCOL_PATTERNS = [
    (r'<local-command-caveat>.*?</local-command-caveat>', 'local_command_caveat'),
    (r'<local-command-stdout>.*?</local-command-stdout>', 'local_command_stdout'),
    (r'<local-command-stderr>.*?</local-command-stderr>', 'local_command_stderr'),
    (r'<command-name>.*?</command-name>', 'command_name'),
    (r'<command-message>.*?</command-message>', 'command_message'),
    (r'<command-args>.*?</command-args>', 'command_args'),
    (r'<system-reminder>.*?</system-reminder>', 'system_reminder'),
    (r'<task-notification>.*?</task-notification>', 'task_notification'),
]

CHAR_PER_LINE_PATTERN = re.compile(r'^(.)\n(.)\n(.)\n(.)\n', re.MULTILINE)


def detect_protocol_message(content: str, role: str = "user", content_length: int = 0) -> dict:
    """Detect if a message is system-generated protocol, not human content.

    Checks (in order):
    1. Empty/zero-length messages → tool result wrappers
    2. XML protocol tags (system-reminder, command-name, etc.)
    3. /clear continuation boilerplate
    4. Skill injections (.claude/skills/ content)
    """
    # Empty or whitespace-only content = tool result wrapper or streaming delimiter
    if not content or len(content.strip()) == 0:
        return {"is_protocol": True, "protocol_type": "empty_wrapper"}
    # XML protocol tags
    for pattern, ptype in PROTOCOL_PATTERNS:
        if re.search(pattern, content, re.DOTALL):
            return {"is_protocol": True, "protocol_type": ptype}
    # /clear session continuation boilerplate (appears in user messages after compaction)
    continuation_markers = [
        "This session is being continued from a previous conversation",
        "The summary below covers the earlier portion",
        "session is being continued from a previous",
    ]
    for marker in continuation_markers:
        if marker in content:
            return {"is_protocol": True, "protocol_type": "clear_continuation"}
    # Skill injections: Claude Code injects .claude/skills/ content as user messages
    # when the user invokes a slash command (e.g. /pdf, /xlsx). The injected content
    # is system-generated documentation, not human-typed input.
    if "Base directory for this skill:" in content and ".claude/skills/" in content:
        return {"is_protocol": True, "protocol_type": "skill_injection"}
    # Automated relay messages from subagent sessions (memory agents, observer agents).
    # These are system-generated observation relays, not human input.
    relay_markers = [
        "Hello memory agent",
        "PROGRESS SUMMARY CHECKPOINT",
        "<observed_from_primary",
    ]
    for marker in relay_markers:
        if marker in content:
            return {"is_protocol": True, "protocol_type": "subagent_relay"}
    return {"is_protocol": False, "protocol_type": None}


def collapse_char_per_line(content: str) -> tuple:
    """Fix character-per-line encoding: A\\nL\\nW\\nA\\nY\\nS → ALWAYS.
    Returns (collapsed_content, was_encoded)."""
    if not content or '\n' not in content:
        return content, False
    # Check if content matches char-per-line pattern (single chars separated by newlines)
    lines = content.split('\n')
    if len(lines) < 4:
        return content, False
    # Count single-char lines
    single_char_lines = sum(1 for l in lines if len(l) <= 1)
    ratio = single_char_lines / len(lines) if lines else 0
    if ratio > 0.7 and len(lines) > 6:
        # This is char-per-line encoded — collapse it
        collapsed = ''.join(lines)
        return collapsed, True
    return content, False


def detect_subagent_session(session_id: str, messages=None, source_file: str = "") -> dict:
    """Detect if this is a subagent session.

    Three detection strategies:
    1. Session ID pattern: '_agent-' or 'agent-' prefix
    2. Source filename pattern: JSONL file contains '_agent-' (the batch reprocessor
       strips this from the session ID, but the filename preserves it)
    3. Content pattern: first user message starts with 'Hello memory agent' or
       contains '<observed_from_primary' (automated relay from parent session)
    """
    is_sub = '_agent-' in session_id or session_id.startswith('agent-')
    agent_id = None
    agent_type = None
    if '_agent-' in session_id:
        agent_id = session_id.split('_agent-')[1]
    elif session_id.startswith('agent-'):
        agent_id = session_id.replace('agent-', '')

    # Strategy 2: Check source JSONL filename for agent pattern
    # The batch reprocessor passes short_id (8 chars) as SESSION_ID, but the
    # JSONL filename preserves the full stem like "4d1482f2_agent-a7112c1"
    if not is_sub and source_file:
        fname = Path(source_file).stem if source_file else ""
        if '_agent-' in fname:
            is_sub = True
            agent_id = fname.split('_agent-')[1]
            agent_type = "task_agent"
        elif fname.startswith('agent-'):
            is_sub = True
            agent_id = fname.replace('agent-', '')
            agent_type = "task_agent"

    # Content-based detection for memory agents and other subagents
    # that don't have 'agent-' in their session ID.
    # Must collapse char-per-line encoding first (raw content may be "H\ne\nl\nl\no\n...")
    if not is_sub and messages:
        for msg in messages[:5]:  # Check first 5 messages only
            raw_content = (msg.content or "") if hasattr(msg, 'content') else ""
            collapsed, _ = collapse_char_per_line(raw_content)
            content_lower = collapsed.lower()
            if 'hello memory agent' in content_lower:
                is_sub = True
                agent_type = "memory_agent"
                break
            if '<observed_from_primary' in content_lower:
                is_sub = True
                agent_type = "observer_agent"
                break
            if 'progress summary checkpoint' in content_lower and msg.role == 'user':
                is_sub = True
                agent_type = "memory_agent"
                break

    return {"is_subagent": is_sub, "agent_id": agent_id, "agent_type": agent_type}


def detect_content_referential_signals(content: str, role: str, signals: list) -> bool:
    """Detect if filter signals are about analyzed content, not session dynamics.
    Returns True if signals are likely content-referential.

    Two detection strategies:
    1. Analytical indicators: long assistant messages discussing failure/error patterns
    2. Signal density anomaly: extremely high failure/frustration counts (>20) on long
       messages of either role — indicates the code being written/displayed IS about
       failure analysis, not that failures are happening in the session.
    """
    if not signals or not content:
        return False
    content_lower = content.lower()

    # Strategy 1: Assistant analytical content (original detection)
    if role == 'assistant':
        analysis_indicators = [
            'problem', 'issue', 'failure mode', 'error handling', 'exception',
            'vulnerability', 'risk', 'challenge', 'limitation', 'concern',
            'section', 'paper', 'report', 'analysis', 'finding',
            'gate', 'enforcer', 'P0', 'P01', 'P02', 'P03',
        ]
        indicator_count = sum(1 for ind in analysis_indicators if ind in content_lower)
        if indicator_count >= 2 and len(content) > 500:
            return True

    # Strategy 2: Signal density anomaly (either role)
    # When failure/frustration counts are high relative to message length,
    # the signals are from the content topic, not from session dynamics.
    signal_counts = {}
    for sig in signals:
        if ':' in sig:
            key, val = sig.split(':', 1)
            try:
                signal_counts[key] = int(val)
            except ValueError:
                pass
    failure_count = signal_counts.get('failure', 0)
    frustration_count = signal_counts.get('frustration', 0)
    architecture_count = signal_counts.get('architecture', 0)
    # High absolute counts on long messages
    if (failure_count > 20 or frustration_count > 10) and len(content) > 1000:
        return True
    # Moderate counts combined with architecture signals = discussing a system's
    # failure handling, not experiencing failures
    if failure_count >= 3 and architecture_count >= 3 and len(content) > 500:
        return True

    # Strategy 3: Assistant messages with multiple failure/frustration signals but
    # positive/analytical tone indicators (plans, implementations, analyses)
    if role == 'assistant' and (failure_count >= 1 or frustration_count >= 1):
        positive_indicators = [
            'implementation', 'created', 'built', 'designed', 'plan',
            'here\'s', 'let me', 'i\'ll', 'step 1', 'step 2', 'phase',
        ]
        positive_count = sum(1 for ind in positive_indicators if ind in content_lower)
        if positive_count >= 2 and len(content) > 300:
            return True

    return False


def compute_real_content_length(content: str, collapsed_content: str, was_encoded: bool) -> int:
    """Compute the true content length, correcting for encoding artifacts."""
    if was_encoded:
        return len(collapsed_content)
    return len(content)


def claude_to_geological(msg: ClaudeMessage, idx: int, source: str) -> GeologicalMessage:
    """Adapt ClaudeMessage → GeologicalMessage for MetadataExtractor compatibility."""
    return GeologicalMessage(
        role=msg.role,
        content=msg.content or "",
        timestamp=msg.timestamp,
        session_id=msg.session_id or SESSION_ID,
        source_file=source,
        message_index=idx,
        message_type=msg.role,
        thinking=msg.thinking or "",
        tool_calls=[],
    )


def main():
    print("=" * 60)
    print("Phase 0: Deterministic Prep (Pure Python, $0)")
    print("=" * 60)
    print(f"Session:  {SESSION_ID}")
    print(f"File:     {SESSION_FILE}")
    print(f"Output:   {OUTPUT_DIR}")
    print()

    # ── Step 1: Load session ───────────────────────────────────────────
    if not SESSION_FILE.exists():
        print(f"ERROR: Session file not found: {SESSION_FILE}")
        sys.exit(1)

    reader = ClaudeSessionReader(verbose=False)
    session = reader.load_session_file(SESSION_FILE)
    if not session:
        print("ERROR: Could not parse session file")
        sys.exit(1)

    print(f"Loaded {len(session.messages)} messages "
          f"({sum(1 for m in session.messages if m.role == 'user')} user, "
          f"{sum(1 for m in session.messages if m.role == 'assistant')} assistant)")

    # ── Step 2: Initialize extractors ──────────────────────────────────
    meta_extractor = MetadataExtractor()
    msg_filter = MessageFilter(verbose=False)
    behavior_analyzer = ClaudeBehaviorAnalyzer()

    # ── Step 3: Process each message ───────────────────────────────────
    enriched_messages = []
    prev_claude_msgs = []  # Rolling window for behavior analysis

    # ── Subagent detection (uses session ID, filename, and first few messages) ──
    subagent_info = detect_subagent_session(
        SESSION_ID, messages=session.messages[:5], source_file=str(SESSION_FILE)
    )

    # Session-level accumulators
    stats = {
        "session_id": SESSION_ID,
        "total_messages": len(session.messages),
        "user_messages": 0,
        "assistant_messages": 0,
        "human_messages": 0,          # NEW: actual human-typed messages (excludes protocol)
        "protocol_messages": 0,       # NEW: system-generated wrappers
        "tier_distribution": {"1_skip": 0, "2_basic": 0, "3_standard": 0, "4_priority": 0},
        "frustration_peaks": [],
        "file_mention_counts": defaultdict(int),
        "error_count": 0,
        "tool_failure_count": 0,      # NEW: tool calls that failed
        "emergency_interventions": [],
        "total_input_tokens": session.total_input_tokens,
        "total_output_tokens": session.total_output_tokens,
        "total_thinking_chars": session.total_thinking_chars,
        "is_subagent": subagent_info["is_subagent"],     # NEW
        "agent_id": subagent_info["agent_id"],            # NEW
        "agent_type": subagent_info.get("agent_type"),    # NEW: memory_agent, observer_agent, etc.
        "char_per_line_messages": 0,  # NEW: count of encoding-corrupted messages
    }

    tier_key_map = {1: "1_skip", 2: "2_basic", 3: "3_standard", 4: "4_priority"}

    for idx, msg in enumerate(session.messages):
        # Count by role
        if msg.role == "user":
            stats["user_messages"] += 1
        elif msg.role == "assistant":
            stats["assistant_messages"] += 1

        content = msg.content or ""

        # ── FIX 1+6: Protocol detection on RAW content first (catches empty wrappers),
        # then char-per-line collapse, then protocol re-check on collapsed content
        # (catches continuation markers that were char-encoded) ──
        protocol_info = detect_protocol_message(content, role=msg.role, content_length=len(content))

        # Collapse char-per-line encoding
        collapsed_content, was_char_encoded = collapse_char_per_line(content)

        # Re-check protocol on collapsed content (catches /clear continuation boilerplate
        # that was char-per-line encoded and not detected on raw content)
        if not protocol_info["is_protocol"] and was_char_encoded:
            protocol_info = detect_protocol_message(collapsed_content, role=msg.role, content_length=len(collapsed_content))
        if protocol_info["is_protocol"]:
            stats["protocol_messages"] += 1
        elif msg.role == "user":
            stats["human_messages"] += 1
        if was_char_encoded:
            stats["char_per_line_messages"] += 1
        real_content_length = compute_real_content_length(content, collapsed_content, was_char_encoded)

        # Use collapsed content for metadata extraction (fixes caps_ratio, file detection)
        analysis_content = collapsed_content if was_char_encoded else content

        # ── Metadata extraction (pure Python) ──
        geo_msg = claude_to_geological(msg, idx, str(SESSION_FILE))
        # Override content with collapsed version for accurate extraction
        if was_char_encoded:
            geo_msg.content = collapsed_content
        try:
            metadata = meta_extractor.extract_message_metadata(geo_msg, idx)
            metadata_dict = metadata.to_dict()
        except (KeyError, TypeError, ValueError, AttributeError) as e:
            metadata_dict = {"error": str(e), "index": idx}

        # ── FIX 4: Detect tool failures ──
        if isinstance(metadata_dict, dict) and msg.role == "assistant":
            # Check for tool failure indicators in the content
            if msg.model == "<synthetic>" and "error" in content.lower():
                metadata_dict["is_synthetic_error"] = True
                stats["tool_failure_count"] += 1

        # ── Message filtering (pure Python) ──
        # Filter on collapsed content for accurate classification
        filter_result = msg_filter.classify(analysis_content)

        # ── FIX P0-001: Protocol override flag ──
        # Protocol messages should be tier 1 regardless of content richness
        protocol_tier_override = protocol_info["is_protocol"] and filter_result.tier > 1

        # ── FIX P0-002: Suppress ALL extracted signals on protocol messages ──
        # Continuation summaries contain quoted content from prior sessions.
        # The metadata extractor finds errors, profanity, frustration etc. in that
        # quoted text, but none of it is from THIS session. Suppress everything.
        if protocol_info["is_protocol"] and isinstance(metadata_dict, dict):
            if metadata_dict.get("error", False):
                metadata_dict["error_context"] = "protocol_recap"
                metadata_dict["error"] = False
            # Suppress profanity/caps/emergency from recycled content
            metadata_dict["profanity"] = False
            metadata_dict["caps_ratio"] = 0
            metadata_dict["emergency_intervention"] = False
            metadata_dict["emergency_reason"] = ""

        # ── FIX 7: Tag content-referential signals ──
        is_content_ref = detect_content_referential_signals(
            analysis_content, msg.role, filter_result.signals
        )

        # ── FIX 3+7: Separate mentioned vs encountered errors ──
        # Must run AFTER is_content_ref is computed
        # Applies to BOTH assistant and user messages (user can paste plans/analyses)
        if isinstance(metadata_dict, dict) and not protocol_info["is_protocol"]:
            error_flag = metadata_dict.get("error", False)
            if error_flag and msg.model != "<synthetic>":
                if is_content_ref or len(analysis_content) > 500:
                    metadata_dict["error_context"] = "mentioned_not_encountered"
                    metadata_dict["error"] = False

        # ── Behavior analysis for assistant messages (pure Python) ──
        # FIX P0-003: Skip behavior analysis for protocol messages (empty wrappers
        # get spurious confusion/damage flags from the analyzer)
        behavior_dict = None
        if msg.role == "assistant" and not protocol_info["is_protocol"]:
            try:
                flags = behavior_analyzer.analyze_message(
                    msg, prev_claude_msgs[-5:] if prev_claude_msgs else []
                )
                behavior_dict = flags.to_dict()
            except (KeyError, TypeError, ValueError, AttributeError) as e:
                behavior_dict = {"error": str(e)}

        # Rolling context window for behavior analysis
        prev_claude_msgs.append(msg)
        if len(prev_claude_msgs) > 10:
            prev_claude_msgs = prev_claude_msgs[-10:]

        # ── Build enriched record ──
        record = {
            "index": idx,
            "role": msg.role,
            "content": content,
            "content_length": real_content_length,              # FIX 6: corrected length
            "content_length_raw": len(content),                 # preserve original for audit
            "content_hash": hashlib.sha256(content.encode()).hexdigest()[:16],
            "timestamp": msg.timestamp.isoformat() if msg.timestamp else None,
            "uuid": msg.uuid,
            "model": msg.model,
            "has_thinking": msg.thinking is not None and len(msg.thinking or "") > 0,
            "thinking_length": len(msg.thinking) if msg.thinking else 0,
            "metadata": metadata_dict,
            "filter_tier": 1 if protocol_tier_override else filter_result.tier,
            "filter_tier_name": "skip" if protocol_tier_override else filter_result.tier_name,
            "filter_score": 0 if protocol_tier_override else filter_result.score,
            "filter_signals": filter_result.signals,
            "filter_signals_content_referential": is_content_ref,  # FIX 7
            "behavior_flags": behavior_dict,
            "is_protocol": protocol_info["is_protocol"],          # FIX 1
            "protocol_type": protocol_info["protocol_type"],      # FIX 1
            "was_char_encoded": was_char_encoded,                 # FIX 6
            "llm_behavior": None,                                 # Populated by LLM passes (llm_pass_runner.py)
        }
        enriched_messages.append(record)

        # ── Accumulate session stats ──
        effective_tier = 1 if protocol_tier_override else filter_result.tier
        tier_key = tier_key_map.get(effective_tier, "1_skip")
        stats["tier_distribution"][tier_key] += 1

        # Frustration peaks (from metadata caps_ratio and profanity)
        # FIX 8: Only user messages can be frustration peaks — assistant discussing
        # frustration patterns is not itself frustrated
        # FIX 9: Use analysis_content (collapsed) for profanity check accuracy
        caps = metadata_dict.get("caps_ratio", 0) if isinstance(metadata_dict, dict) else 0
        profanity = metadata_dict.get("profanity", False) if isinstance(metadata_dict, dict) else False
        emergency = metadata_dict.get("emergency_intervention", False) if isinstance(metadata_dict, dict) else False

        if msg.role == "user" and not protocol_info["is_protocol"] and (caps > 0.3 or profanity):
            stats["frustration_peaks"].append({
                "index": idx,
                "caps_ratio": caps,
                "profanity": profanity,
                "content_preview": analysis_content[:120],
            })

        # Emergency interventions — exclude protocol messages (continuation summaries
        # may contain profanity from prior sessions, not actual emergencies)
        if emergency and not protocol_info["is_protocol"]:
            stats["emergency_interventions"].append({
                "index": idx,
                "reason": metadata_dict.get("emergency_reason", ""),
                "content_preview": analysis_content[:120],
            })

        # File mention tracking
        files = metadata_dict.get("files", []) if isinstance(metadata_dict, dict) else []
        for f in files:
            stats["file_mention_counts"][f] += 1

        if metadata_dict.get("error", False) if isinstance(metadata_dict, dict) else False:
            stats["error_count"] += 1

        # Progress indicator
        if (idx + 1) % 100 == 0:
            print(f"  Processed {idx + 1}/{len(session.messages)} messages...")

    # ── Step 4: Write output ───────────────────────────────────────────
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Convert defaultdict to regular dict for JSON serialization
    stats["file_mention_counts"] = dict(stats["file_mention_counts"])

    # ── FIX P0-006: Remove false positive files ──
    # Two strategies: (1) blocklist of common generic filenames that regex picks up
    # from natural language, (2) short names that are substrings of longer detected names
    GENERIC_FILE_BLOCKLIST = {
        'file.py', 'mentioned.py', 'other_file.py', 'filename.py', 'example.py',
        'test.py', 'main.py', 'script.py', 'module.py', 'utils.py', 'helper.py',
        'config.py', 'setup.py', 'run.py', 'app.py', 'index.js', 'index.html',
        'style.css', 'styles.css', 'file.txt', 'data.json', 'output.json',
    }
    all_files = set(stats["file_mention_counts"].keys())
    false_positives = set()
    # Strategy 1: blocklist
    for f in all_files:
        if f.lower() in GENERIC_FILE_BLOCKLIST:
            false_positives.add(f)
    # Strategy 2: substring matches
    for short_name in all_files:
        if short_name in false_positives:
            continue
        base = short_name.rsplit('.', 1)[0] if '.' in short_name else short_name
        if len(base) <= 12:
            for long_name in all_files:
                if long_name != short_name and short_name in long_name:
                    false_positives.add(short_name)
                    break
    if false_positives:
        for fp in false_positives:
            del stats["file_mention_counts"][fp]
        stats["false_positive_files_removed"] = sorted(false_positives)
        # Also remove from per-message metadata (check both exact and path-style matches)
        fp_basenames = {fp.lower() for fp in false_positives}
        for record in enriched_messages:
            if isinstance(record.get("metadata"), dict):
                files = record["metadata"].get("files", [])
                if files:
                    record["metadata"]["files"] = [
                        f for f in files
                        if f not in false_positives
                        and os.path.basename(f).lower() not in fp_basenames
                    ]

    # Sort files by mention count (descending)
    stats["top_files"] = sorted(
        stats["file_mention_counts"].items(),
        key=lambda x: x[1],
        reverse=True
    )[:30]

    output = {
        "session_id": SESSION_ID,
        "source_file": str(SESSION_FILE),
        "generated_at": datetime.now().isoformat(),
        "generator": "deterministic_prep.py (Phase 0)",
        "session_stats": stats,
        "messages": enriched_messages,
    }

    output_file = OUTPUT_DIR / "enriched_session.json"
    with open(output_file, "w") as f:
        json.dump(output, f, indent=2, default=str)

    file_size_mb = output_file.stat().st_size / (1024 * 1024)

    # ── Step 5: Print summary ──────────────────────────────────────────
    print()
    print("=" * 60)
    print("Phase 0 Complete")
    print("=" * 60)
    print(f"Output file:    {output_file}")
    print(f"File size:      {file_size_mb:.1f} MB")
    print(f"Messages:       {len(enriched_messages)}")
    print(f"  User:         {stats['user_messages']}")
    print(f"  Assistant:    {stats['assistant_messages']}")
    print(f"Tier distribution:")
    for tier, count in stats["tier_distribution"].items():
        pct = count / len(enriched_messages) * 100 if enriched_messages else 0
        print(f"  {tier}: {count} ({pct:.0f}%)")
    print(f"Frustration peaks:     {len(stats['frustration_peaks'])}")
    print(f"Emergency interventions: {len(stats['emergency_interventions'])}")
    print(f"Unique files mentioned:  {len(stats['file_mention_counts'])}")
    print(f"Errors detected:         {stats['error_count']}")
    # Phase 0 data quality metrics
    print(f"\nData quality fixes applied:")
    print(f"  Protocol messages:     {stats['protocol_messages']} (system-generated, not human)")
    print(f"  Human messages:        {stats['human_messages']} (actual human input)")
    print(f"  Char-per-line fixed:   {stats['char_per_line_messages']} messages")
    print(f"  Tool failures:         {stats['tool_failure_count']}")
    print(f"  Subagent session:      {stats['is_subagent']} (agent_id: {stats['agent_id']})")

    if stats["top_files"]:
        print(f"\nTop 10 most-mentioned files:")
        for fname, count in stats["top_files"][:10]:
            print(f"  {count:3d}x  {fname}")

    print(f"\nToken usage (session total):")
    print(f"  Input:    {stats['total_input_tokens']:,}")
    print(f"  Output:   {stats['total_output_tokens']:,}")
    print(f"  Thinking: {stats['total_thinking_chars']:,} chars")


if __name__ == "__main__":
    main()

# ======================================================================
# @ctx HYPERDOC — HISTORICAL (generated 2026-02-08, requires realtime update)
# These annotations are from the Phase 4b bulk processing run across 284
# sessions. The code below may have changed since these markers were
# generated. Markers reflect the state of the codebase as of Feb 8, 2026.
# ======================================================================

# --- HEADER ---
# ======================================================================
# @ctx HYPERDOC — Phase 4b Generated
# ======================================================================

# --- FOOTER ---
# ======================================================================
# @ctx HYPERDOC — Phase 4b Generated
# ======================================================================
# # ===========================================================================
# # HYPERDOC HEADER: deterministic_prep.py
# # @ctx:version=1 @ctx:source_sessions=392ebf35,4901d024,4953cc6b,4a65878f,5255f985,54451960,557ba4c2,58d1281e,5c9dea21,5fc2eb24,636caafa,67d9ceb3,7a2dbfe0,7ce258d7,81e29dc8
# # @ctx:generated=2026-02-08T18:30:00Z
# # @ctx:state=stable @ctx:confidence=0.90 @ctx:emotion=calm
# # @ctx:intent=correctness @ctx:edits=3 @ctx:mentions=15_sessions
# # @ctx:failed_approaches=0
# # ===========================================================================
# #
# # --- STORY ARC ---
# #
# # deterministic_prep.py was created during session 3b7084d5 (Feb 6, 2026) as
# # the answer to a cost crisis: the V5 geological_reader.py was calling Opus
# # per message line at $0.05/line, making full archive processing cost $4,800+.
# # The user realized that the original V1 pipeline had used pure Python JSON
# # parsing for free, and that V5 had unnecessarily added an LLM layer to what
# # should be deterministic metadata extraction. deterministic_prep.py was born
# # from this insight: run all free Python extractors first (ClaudeSessionReader,
# # MetadataExtractor, MessageFilter, ClaudeBehaviorAnalyzer) to produce an
# # enriched_session.json that downstream LLM agents would consume. It processed
# # its first session (3b7084d5, 4,269 messages) for $0 on Feb 7, 2026. It then
# # scaled to 275 sessions (137,623 messages) during bulk historical processing
# # on Feb 7-8, completing in 4 minutes at zero cost. As of Feb 8, 285 session
# # output directories exist. The file has been stable since creation -- the 3
# # edits it received were for config.py integration and hardcoded path removal,
# # not bug fixes. Its main known issues are downstream signal quality problems:
# # false positive frustration detection on short messages, filter signal
# # contamination when processing analysis-agent output, and missing error
# # detail recording.
# #
# # --- FRICTION: WHAT WENT WRONG AND WHY ---
# #
# # @ctx:friction="Frustration detection produces false positives on short messages due to caps_ratio inflating on 1-2 character texts"
# # @ctx:trace=conv_fd3de2dc:explorer_notes_A03
# #   The frustration peak detection (line 185: caps > 0.3) triggers on messages
# #   as short as 2 characters ('B\n1') where one capital letter produces
# #   caps_ratio=1.0. Session fd3de2dc's explorer_notes documented this: 'The
# #   frustration detection in deterministic_prep.py needs a minimum character
# #   threshold. Messages under ~20 characters should not have caps_ratio
# #   considered as a frustration signal.' This remains UNRESOLVED in the current
# #   code -- line 185 has no minimum content length guard.
# #
# # @ctx:friction="Filter signals produce false positives when processing analysis-agent sessions that report on failures in other sessions"
# # @ctx:trace=conv_636caafa:grounded_markers_warnings_0
# #   Session 636caafa found that message idx 61 (a report about other sessions)
# #   carried frustration:3 and failure:3 filter signals despite the session
# #   having 0 frustration peaks and 0 errors. The keywords 'failure' and
# #   'frustration' appeared in the report CONTENT (describing other sessions)
# #   but were tagged as THIS session's behavioral signals. The grounded_markers
# #   recommended adding a 'signal_source' field to distinguish 'experienced'
# #   from 'reflected' signals. This remains UNRESOLVED.
# #
# # @ctx:friction="Emergency detector produces false positives during role-play and simulation sessions"
# # @ctx:trace=conv_7ce258d7:grounded_markers_WARN04
# #   Session 7ce258d7's grounded_markers WARN-04 documented that REPEAT(3x):GO
# #   emergency detection triggered during simulation v5 when Claude was
# #   role-playing. The detector cannot distinguish simulation dialogue from real
# #   user distress. Recommendation: add context awareness to suppress the
# #   emergency heuristic when the message is within a code block, quote, or
# #   simulation header. This remains UNRESOLVED.
# #
# # @ctx:friction="Error tracking records error_count but not which file or operation caused the error"
# # @ctx:trace=conv_5c9dea21:grounded_markers_W3
# #   Session 5c9dea21's grounded_markers W3 found that session_stats.error_count=1
# #   with message 52 having error:true, but no metadata records which file failed
# #   to read. The synthesis recommended modifying deterministic_prep.py to record
# #   file paths alongside error counts. Currently line 134 catches exceptions
# #   with metadata_dict = {"error": str(e), "index": idx} but does not propagate
# #   the error source to session-level stats. This remains UNRESOLVED.
# #
# # @ctx:friction="50% of processed transcript batches were warmup-only sessions, wasting downstream Phase 1 agent launch costs"
# # @ctx:trace=conv_4a65878f:file_dossiers
# #   Session 4a65878f found that 5 of 10 transcripts in a batch were warmup-only
# #   sessions containing no substantive content. deterministic_prep.py processes
# #   these identically to substantive sessions, producing full enriched_session.json
# #   files. Phase 1 then launches 4 agents per session regardless. Recommendation:
# #   add a warmup session filter that detects sessions with >90% empty messages
# #   and <100 total messages, flagging them to skip or deprioritize in Phase 1.
# #   This remains UNRESOLVED.
# #
# # @ctx:friction="Character-per-line user message encoding inflates content_length metrics"
# # @ctx:trace=conv_0a7d910e:explorer_notes_obs005
# #   Session 0a7d910e's explorer_notes documented that many user messages have
# #   text stored with each character on its own line ('I\nm\np\nl\ne\nm\ne\nn\nt').
# #   deterministic_prep.py's content_length field (line 160) reflects the stored
# #   format (849 chars) rather than the semantic length (~280 chars). This inflates
# #   content_length comparisons across sessions. The parser handles this correctly
# #   for reading but not for density metrics. This is an upstream JSONL encoding
# #   issue, not a deterministic_prep bug, but affects its output quality.
# #
# # --- DECISIONS: CHOSE X OVER Y BECAUSE Z ---
# #
# # @ctx:decision="chose pure Python extraction over LLM-based extraction because the V1 pipeline proved that metadata extraction does not require an LLM and the all-Opus approach would cost $4,800+ for the full archive"
# # @ctx:trace=conv_3b7084d5:msg2150-2200
# #   Alternatives considered: Opus per-message extraction (V5 approach), Haiku
# #   for metadata extraction, hybrid Python+LLM
# #   Why rejected: Opus per-message was $0.05/line, Haiku still costs money for
# #   something pure Python can do for free. The user's key insight was 'the v1
# #   actually ran and produced hyperdocs... we didn't add a whole llm layer'.
# #
# # @ctx:decision="chose adapter pattern (claude_to_geological) over refactoring MetadataExtractor to accept ClaudeMessage directly because MetadataExtractor was a working V5 module that should not be modified"
# # @ctx:trace=conv_3b7084d5:phase0_creation
# #   Alternatives considered: modify MetadataExtractor's interface, create a
# #   new metadata extractor from scratch
# #   Why rejected: modifying V5 modules risked breaking other V5 code paths;
# #   creating from scratch duplicated working logic. The adapter (lines 52-65)
# #   converts ClaudeMessage to GeologicalMessage at zero cost.
# #
# # @ctx:decision="chose config.py centralization with env var fallback over hardcoded paths because the pipeline needed to run on different sessions and machines without code changes"
# # @ctx:trace=conv_4953cc6b:chapter_6
# #   Alternatives considered: command-line arguments, hardcoded session ID,
# #   separate config files per session
# #   Why rejected: CLI args require remembering flags; hardcoded IDs require
# #   editing source; per-session configs proliferate. config.py with env var
# #   override (lines 42-49) provides zero-config defaults with override capability.
# #
# # --- WARNINGS ---
# #
# # @ctx:warning="[W1] [medium] Frustration detection false positives on short messages: caps_ratio threshold at 0.3 has no minimum content length guard, producing false peaks on 1-2 character messages"
# # @ctx:trace=conv_fd3de2dc:explorer_notes_A03
# #   Resolution: UNRESOLVED
# #   Evidence: Line 185: 'if caps > 0.3 or profanity'. Session fd3de2dc:
# #   content_preview 'B\n1' with caps_ratio 1.0 flagged as frustration peak.
# #
# # @ctx:warning="[W2] [medium] Filter signal contamination: keyword-based signal extraction tags report CONTENT as session BEHAVIOR, producing false signals on analysis-agent sessions"
# # @ctx:trace=conv_636caafa:grounded_markers_warnings_0,conv_58d1281e:grounded_markers_WARN05
# #   Resolution: UNRESOLVED
# #   Evidence: Session 636caafa msg 61: frustration:3 failure:3 from report
# #   text about other sessions. Session 58d1281e msg 57: failure:9 pivot:4
# #   from investigation report describing gate failure modes.
# #
# # @ctx:warning="[W3] [medium] Emergency detection false positives on role-play and simulation sessions: REPEAT(Nx) heuristic cannot distinguish simulation dialogue from real user distress"
# # @ctx:trace=conv_7ce258d7:grounded_markers_WARN04
# #   Resolution: UNRESOLVED
# #   Evidence: Session 7ce258d7 msg 1434: REPEAT(3x):GO triggered during
# #   simulation v5 role-play.
# #
# # @ctx:warning="[W4] [low] Error tracking lacks file path recording: session_stats.error_count increments but does not record which operation or file caused each error"
# # @ctx:trace=conv_5c9dea21:grounded_markers_W3
# #   Resolution: UNRESOLVED
# #   Evidence: Session 5c9dea21: error_count=1, msg 52 error:true, but no
# #   field identifies the source file or operation that failed.
# #
# # @ctx:warning="[W5] [low] No warmup session detection: all sessions receive identical processing regardless of whether they contain substantive content, wasting downstream Phase 1 agent costs on empty sessions"
# # @ctx:trace=conv_4a65878f:file_dossiers
# #   Resolution: UNRESOLVED
# #   Evidence: Session 4a65878f: 5 of 10 transcripts in a batch were warmup-only.
# #   Each still triggers 4 Phase 1 agent launches.
# #
# # --- IRON RULES ---
# #
# # 1. This file must never call an LLM. It is the $0 foundation of the pipeline.
# #    All metadata extraction is pure Python. If a signal requires LLM analysis,
# #    it belongs in Phase 1 or later.
# # 2. Output must be enriched_session.json, not any other filename. prepare_agent_data.py
# #    and all Phase 1 agents depend on this exact filename.
# # 3. The content field in enriched messages must contain the FULL message content,
# #    never truncated. Downstream agents depend on full content for analysis.
# #
# # --- CLAUDE BEHAVIOR ON THIS FILE ---
# #
# # @ctx:claude_pattern="impulse_control: high -- this file was created in a single pass
# #   and has required only 3 minor edits since. No premature optimization or
# #   feature creep. The adapter pattern on lines 52-65 is minimal."
# # @ctx:claude_pattern="authority_response: high -- the file was born directly from
# #   the user's insight that V1 used pure Python. Claude implemented exactly what
# #   was asked without attempting to add LLM calls or 'enhance' the approach."
# # @ctx:claude_pattern="overconfidence: low -- no premature victory declarations
# #   around this file. It was tested on session 3b7084d5 first, then bulk
# #   processing of 275 sessions, with results verified at each step."
# # @ctx:claude_pattern="context_damage: none observed -- the file has been stable
# #   since creation. No instances of Claude losing track of this file's role
# #   or accidentally modifying it."
# #
# # --- EMOTIONAL CONTEXT ---
# #
# # This file was created during a period of user relief after the 'Phase 0
# # Revelation' (MEMORY.md Chapter 4). The user had been frustrated that V5
# # added expensive LLM layers to what V1 did for free. User's key quote:
# # 'the v1 actually ran and produced hyperdocs... we didn't add a whole llm
# # layer' (session 3b7084d5, msg ~2150). The creation of deterministic_prep.py
# # represented a return to the user's original working approach.
# # No direct frustration was directed at this file itself. The frustration
# # was at the V5 architecture that this file was designed to replace.
# #
# # --- FAILED APPROACHES ---
# #
# # @ctx:failed_approaches=0
# # No failed approaches specific to this file. It was designed correctly from
# # the start based on the V1 pattern. The failed approach was the V5
# # geological_reader.py calling Opus per line ($0.05/line), which deterministic_prep.py
# # was specifically created to replace for Phase 0.
# #
# # --- RECOMMENDATIONS ---
# #
# # [R01] (priority: medium)
# #   Add minimum content length guard to frustration detection. Line 185
# #   should read: if (caps > 0.3 and len(content) >= 20) or profanity.
# #   Evidence: session fd3de2dc explorer_notes A03.
# #
# # [R02] (priority: medium)
# #   Add signal_source field ('experienced' vs 'reflected') to filter_signals
# #   output. For sessions where isSidechain=true or the session is a spawned
# #   analysis agent, default report-message signals to 'reflected'.
# #   Evidence: sessions 636caafa and 58d1281e grounded_markers.
# #
# # [R03] (priority: medium)
# #   Add context awareness to emergency detection. Suppress REPEAT(Nx)
# #   heuristic when content is within a code block, quote, or simulation
# #   header. Evidence: session 7ce258d7 grounded_markers WARN-04.
# #
# # [R04] (priority: medium)
# #   Add error_details list to session_stats alongside error_count. Each
# #   entry should record: message index, file path (if applicable), exception
# #   type, and error message. Evidence: session 5c9dea21 grounded_markers W3.
# #
# # [R05] (priority: medium)
# #   Add warmup session detection. After processing all messages, check if
# #   >90% are tier 1 (skip) and total_messages < 100. If so, add a
# #   'warmup_session': true flag to the output. batch_orchestrator.py can
# #   then skip Phase 1 agent launches for these sessions.
# #   Evidence: session 4a65878f file_dossiers.
# #
# # ===========================================================================
# ======================================================================



# @ctx:inline ----
# # @ctx:function=claude_to_geological @ctx:added=2026-02-06 @ctx:hyperdoc_updated=2026-02-08
# # @ctx:decision="chose adapter pattern over refactoring MetadataExtractor because V5 modules should not be modified"
# # Converts ClaudeMessage to GeologicalMessage at zero cost. Required because
# # MetadataExtractor.extract_message_metadata() expects GeologicalMessage objects,
# # but ClaudeSessionReader produces ClaudeMessage objects. The adapter avoids
# # modifying either V5 module.
# ----
def claude_to_geological(msg: ClaudeMessage, idx: int, source: str) -> GeologicalMessage:
    """Adapt ClaudeMessage → GeologicalMessage for MetadataExtractor compatibility."""
    return GeologicalMessage(
        role=msg.role,
        content=msg.content or "",
        timestamp=msg.timestamp,
        session_id=msg.session_id or SESSION_ID,
        source_file=source,
        message_index=idx,
        message_type=msg.role,
        thinking=msg.thinking or "",
        tool_calls=[],
    )


# @ctx:inline ----
# # @ctx:function=main @ctx:added=2026-02-06 @ctx:hyperdoc_updated=2026-02-08
# # @ctx:warning="Frustration detection (line 185) has no minimum content length guard -- produces false positives on 1-2 char messages"
# # @ctx:warning="Error tracking (line 205) increments error_count but does not record source file path"
# # @ctx:warning="No warmup session detection -- all sessions get identical processing regardless of content"
# # Processes messages in a single pass: for each message, runs metadata extraction,
# # filter classification, and behavior analysis (assistant messages only). Accumulates
# # session-level stats including tier distribution, frustration peaks, file mentions,
# # and emergency interventions. Writes enriched_session.json as sole output.
# # Known false positive sources: caps_ratio on short msgs, filter signals on
# # report content, emergency detection on role-play/simulation.
# ----
def main():
    print("=" * 60)
    print("Phase 0: Deterministic Prep (Pure Python, $0)")
    print("=" * 60)
    print(f"Session:  {SESSION_ID}")
    print(f"File:     {SESSION_FILE}")
    print(f"Output:   {OUTPUT_DIR}")
    print()

    # ── Step 1: Load session ───────────────────────────────────────────
    if not SESSION_FILE.exists():
        print(f"ERROR: Session file not found: {SESSION_FILE}")
        sys.exit(1)

    reader = ClaudeSessionReader(verbose=False)
    session = reader.load_session_file(SESSION_FILE)
    if not session:
        print("ERROR: Could not parse session file")
        sys.exit(1)

    print(f"Loaded {len(session.messages)} messages "
          f"({sum(1 for m in session.messages if m.role == 'user')} user, "
          f"{sum(1 for m in session.messages if m.role == 'assistant')} assistant)")

    # ── Step 2: Initialize extractors ──────────────────────────────────
    meta_extractor = MetadataExtractor()
    msg_filter = MessageFilter(verbose=False)
    behavior_analyzer = ClaudeBehaviorAnalyzer()

    # ── Step 3: Process each message ───────────────────────────────────
    enriched_messages = []
    prev_claude_msgs = []  # Rolling window for behavior analysis

    # Session-level accumulators
    stats = {
        "session_id": SESSION_ID,
        "total_messages": len(session.messages),
        "user_messages": 0,
        "assistant_messages": 0,
        "tier_distribution": {"1_skip": 0, "2_basic": 0, "3_standard": 0, "4_priority": 0},
        "frustration_peaks": [],
        "file_mention_counts": defaultdict(int),
        "error_count": 0,
        "emergency_interventions": [],
        "total_input_tokens": session.total_input_tokens,
        "total_output_tokens": session.total_output_tokens,
        "total_thinking_chars": session.total_thinking_chars,
    }

    tier_key_map = {1: "1_skip", 2: "2_basic", 3: "3_standard", 4: "4_priority"}

    for idx, msg in enumerate(session.messages):
        # Count by role
        if msg.role == "user":
            stats["user_messages"] += 1
        elif msg.role == "assistant":
            stats["assistant_messages"] += 1

        content = msg.content or ""

        # ── Metadata extraction (pure Python) ──
        geo_msg = claude_to_geological(msg, idx, str(SESSION_FILE))
        try:
            metadata = meta_extractor.extract_message_metadata(geo_msg, idx)
            metadata_dict = metadata.to_dict()
        except Exception as e:
            metadata_dict = {"error": str(e), "index": idx}

        # ── Message filtering (pure Python) ──
        filter_result = msg_filter.classify(content)

        # ── Behavior analysis for assistant messages (pure Python) ──
        behavior_dict = None
        if msg.role == "assistant":
            try:
                flags = behavior_analyzer.analyze_message(
                    msg, prev_claude_msgs[-5:] if prev_claude_msgs else []
                )
                behavior_dict = flags.to_dict()
            except Exception as e:
                behavior_dict = {"error": str(e)}

        # Rolling context window for behavior analysis
        prev_claude_msgs.append(msg)
        if len(prev_claude_msgs) > 10:
            prev_claude_msgs = prev_claude_msgs[-10:]

        # ── Build enriched record ──
        record = {
            "index": idx,
            "role": msg.role,
            "content": content,
            "content_length": len(content),
            "content_hash": hashlib.sha256(content.encode()).hexdigest()[:16],
            "timestamp": msg.timestamp.isoformat() if msg.timestamp else None,
            "uuid": msg.uuid,
            "model": msg.model,
            "has_thinking": msg.thinking is not None and len(msg.thinking or "") > 0,
            "thinking_length": len(msg.thinking) if msg.thinking else 0,
            "metadata": metadata_dict,
            "filter_tier": filter_result.tier,
            "filter_tier_name": filter_result.tier_name,
            "filter_score": filter_result.score,
            "filter_signals": filter_result.signals,
            "behavior_flags": behavior_dict,
        }
        enriched_messages.append(record)

        # ── Accumulate session stats ──
        tier_key = tier_key_map.get(filter_result.tier, "1_skip")
        stats["tier_distribution"][tier_key] += 1

        # Frustration peaks (from metadata caps_ratio and profanity)
        caps = metadata_dict.get("caps_ratio", 0) if isinstance(metadata_dict, dict) else 0
        profanity = metadata_dict.get("profanity", False) if isinstance(metadata_dict, dict) else False
        emergency = metadata_dict.get("emergency_intervention", False) if isinstance(metadata_dict, dict) else False

        if caps > 0.3 or profanity:
            stats["frustration_peaks"].append({
                "index": idx,
                "caps_ratio": caps,
                "profanity": profanity,
                "content_preview": content[:120],
            })

        if emergency:
            stats["emergency_interventions"].append({
                "index": idx,
                "reason": metadata_dict.get("emergency_reason", ""),
                "content_preview": content[:120],
            })

        # File mention tracking
        files = metadata_dict.get("files", []) if isinstance(metadata_dict, dict) else []
        for f in files:
            stats["file_mention_counts"][f] += 1

        if metadata_dict.get("error", False) if isinstance(metadata_dict, dict) else False:
            stats["error_count"] += 1

        # Progress indicator
        if (idx + 1) % 100 == 0:
            print(f"  Processed {idx + 1}/{len(session.messages)} messages...")

    # ── Step 4: Write output ───────────────────────────────────────────
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Convert defaultdict to regular dict for JSON serialization
    stats["file_mention_counts"] = dict(stats["file_mention_counts"])

    # Sort files by mention count (descending)
    stats["top_files"] = sorted(
        stats["file_mention_counts"].items(),
        key=lambda x: x[1],
        reverse=True
    )[:30]

    output = {
        "session_id": SESSION_ID,
        "source_file": str(SESSION_FILE),
        "generated_at": datetime.now().isoformat(),
        "generator": "deterministic_prep.py (Phase 0)",
        "session_stats": stats,
        "messages": enriched_messages,
    }

    output_file = OUTPUT_DIR / "enriched_session.json"
    with open(output_file, "w") as f:
        json.dump(output, f, indent=2, default=str)

    file_size_mb = output_file.stat().st_size / (1024 * 1024)

    # ── Step 5: Print summary ──────────────────────────────────────────
    print()
    print("=" * 60)
    print("Phase 0 Complete")
    print("=" * 60)
    print(f"Output file:    {output_file}")
    print(f"File size:      {file_size_mb:.1f} MB")
    print(f"Messages:       {len(enriched_messages)}")
    print(f"  User:         {stats['user_messages']}")
    print(f"  Assistant:    {stats['assistant_messages']}")
    print(f"Tier distribution:")
    for tier, count in stats["tier_distribution"].items():
        pct = count / len(enriched_messages) * 100 if enriched_messages else 0
        print(f"  {tier}: {count} ({pct:.0f}%)")
    print(f"Frustration peaks:     {len(stats['frustration_peaks'])}")
    print(f"Emergency interventions: {len(stats['emergency_interventions'])}")
    print(f"Unique files mentioned:  {len(stats['file_mention_counts'])}")
    print(f"Errors detected:         {stats['error_count']}")

    if stats["top_files"]:
        print(f"\nTop 10 most-mentioned files:")
        for fname, count in stats["top_files"][:10]:
            print(f"  {count:3d}x  {fname}")

    print(f"\nToken usage (session total):")
    print(f"  Input:    {stats['total_input_tokens']:,}")
    print(f"  Output:   {stats['total_output_tokens']:,}")
    print(f"  Thinking: {stats['total_thinking_chars']:,} chars")


if __name__ == "__main__":
    main()


# ======================================================================
# @ctx HYPERDOC FOOTER
# ======================================================================

# --- INLINE ---
# @ctx:inline ----
# # @ctx:function=claude_to_geological @ctx:added=2026-02-06 @ctx:hyperdoc_updated=2026-02-08
# # @ctx:decision="chose adapter pattern over refactoring MetadataExtractor because V5 modules should not be modified"
# # Converts ClaudeMessage to GeologicalMessage at zero cost. Required because
# # MetadataExtractor.extract_message_metadata() expects GeologicalMessage objects,
# # but ClaudeSessionReader produces ClaudeMessage objects. The adapter avoids
# # modifying either V5 module.
# ----

# --- INLINE ---
# @ctx:inline ----
# # @ctx:function=main @ctx:added=2026-02-06 @ctx:hyperdoc_updated=2026-02-08
# # @ctx:warning="Frustration detection (line 185) has no minimum content length guard -- produces false positives on 1-2 char messages"
# # @ctx:warning="Error tracking (line 205) increments error_count but does not record source file path"
# # @ctx:warning="No warmup session detection -- all sessions get identical processing regardless of content"
# # Processes messages in a single pass: for each message, runs metadata extraction,
# # filter classification, and behavior analysis (assistant messages only). Accumulates
# # session-level stats including tier distribution, frustration peaks, file mentions,
# # and emergency interventions. Writes enriched_session.json as sole output.
# # Known false positive sources: caps_ratio on short msgs, filter signals on
# # report content, emergency detection on role-play/simulation.
# ----

