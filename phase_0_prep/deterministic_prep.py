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

# Add V5 code to Python path for imports
V5_CODE = Path(__file__).parent / ".claude" / "hooks" / "hyperdoc" / "hyperdocs_2" / "V5" / "code"
sys.path.insert(0, str(V5_CODE))

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
