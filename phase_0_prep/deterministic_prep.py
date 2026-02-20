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

# Import V5 modules from bundled v5_compat package
from phase_0_prep.v5_compat import (
    ClaudeSessionReader, ClaudeMessage, ClaudeSession,
    GeologicalMessage, MetadataExtractor, MessageFilter,
    ClaudeBehaviorAnalyzer,
)

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
        opus_analysis=None,
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
        except Exception as e:
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
