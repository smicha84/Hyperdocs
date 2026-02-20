#!/usr/bin/env python3
"""
Build Opus-Filtered Message Files

Takes opus_classifications.json + enriched_session.json and produces
message files filtered by Opus importance instead of Python tiers.

This replaces tier4_priority_messages.json with opus_priority_messages.json
for Phase 1 agents. Messages classified as critical, significant, or context
by Opus are included, regardless of Python tier.

Usage:
    python3 build_opus_filtered.py --session 0012ebed
    python3 build_opus_filtered.py --dir ~/PERMANENT_HYPERDOCS/sessions/session_0012ebed
"""

import json
import os
import sys
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
try:
    from config import get_session_output_dir, SESSION_ID
except ImportError:
    SESSION_ID = os.getenv("HYPERDOCS_SESSION_ID", "")
    def get_session_output_dir():
        return Path(os.getenv("HYPERDOCS_OUTPUT_DIR", "./output")) / f"session_{SESSION_ID[:8]}"


def build_opus_filtered(session_dir: Path):
    """Build Opus-filtered message files from classifications + enriched session."""

    # Load classifications
    cls_path = session_dir / "opus_classifications.json"
    if not cls_path.exists():
        print(f"ERROR: opus_classifications.json not found in {session_dir}")
        print("Run opus_classifier.py first.")
        return None

    cls_data = json.loads(cls_path.read_text())
    classifications = cls_data.get("classifications", [])
    opus_by_idx = {}
    for c in classifications:
        idx = c.get("msg_index")
        if idx is not None:
            opus_by_idx[idx] = c

    # Load enriched session
    enriched_path = session_dir / "enriched_session.json"
    if not enriched_path.exists():
        print(f"ERROR: enriched_session.json not found")
        return None

    enriched = json.loads(enriched_path.read_text())
    all_messages = enriched.get("messages", [])

    print(f"Total messages: {len(all_messages)}")
    print(f"Opus classifications: {len(opus_by_idx)}")

    # Build filtered sets
    critical_msgs = []
    significant_msgs = []
    context_msgs = []
    noise_msgs = []
    unclassified_msgs = []

    for msg in all_messages:
        idx = msg.get("index", -1)
        opus = opus_by_idx.get(idx)

        if opus:
            importance = opus.get("importance", "noise")
            # Enrich the message with Opus classification
            msg["opus_importance"] = importance
            msg["opus_categories"] = opus.get("categories", [])
            msg["opus_reason"] = opus.get("reason", "")
            msg["opus_connected_files"] = opus.get("connected_files", [])

            if importance == "critical":
                critical_msgs.append(msg)
            elif importance == "significant":
                significant_msgs.append(msg)
            elif importance == "context":
                context_msgs.append(msg)
            else:
                noise_msgs.append(msg)
        else:
            # Message wasn't classified (in a skipped chunk)
            # Fall back to Python tier
            tier = msg.get("filter_tier", 1)
            msg["opus_importance"] = None
            msg["opus_categories"] = []
            msg["opus_reason"] = "Not classified by Opus (chunk parse error)"
            if tier >= 3:
                significant_msgs.append(msg)
            elif tier >= 2:
                context_msgs.append(msg)
            else:
                unclassified_msgs.append(msg)

    print(f"\nOpus distribution:")
    print(f"  Critical:     {len(critical_msgs)}")
    print(f"  Significant:  {len(significant_msgs)}")
    print(f"  Context:      {len(context_msgs)}")
    print(f"  Noise:        {len(noise_msgs)}")
    print(f"  Unclassified: {len(unclassified_msgs)} (fell back to Python tier)")

    # Build priority messages (critical + significant)
    # This replaces tier4_priority_messages.json
    priority = critical_msgs + significant_msgs
    priority.sort(key=lambda m: m.get("index", 0))

    # Build extended messages (critical + significant + context)
    # This replaces tier2plus_messages.json
    extended = critical_msgs + significant_msgs + context_msgs
    extended.sort(key=lambda m: m.get("index", 0))

    # Compare to Python tier system
    python_tier4 = [m for m in all_messages if m.get("filter_tier", 0) >= 4]
    python_tier2plus = [m for m in all_messages if m.get("filter_tier", 0) >= 2]

    # Find messages Opus includes that Python excluded
    priority_indices = set(m.get("index") for m in priority)
    python_tier4_indices = set(m.get("index") for m in python_tier4)
    new_in_priority = priority_indices - python_tier4_indices
    lost_from_priority = python_tier4_indices - priority_indices

    print(f"\n=== Comparison: Opus priority vs Python tier 4 ===")
    print(f"  Python tier 4:     {len(python_tier4)} messages")
    print(f"  Opus priority:     {len(priority)} messages (critical + significant)")
    print(f"  NEW (Opus adds):   {len(new_in_priority)} messages")
    print(f"  LOST (Opus drops): {len(lost_from_priority)} messages")

    # Write opus_priority_messages.json (replaces tier4_priority_messages.json)
    priority_output = {
        "session_id": cls_data.get("session_id", ""),
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "generator": "build_opus_filtered.py",
        "filter_method": "opus_classification",
        "importance_levels_included": ["critical", "significant"],
        "total_session_messages": len(all_messages),
        "messages_included": len(priority),
        "comparison": {
            "python_tier4_count": len(python_tier4),
            "opus_priority_count": len(priority),
            "new_messages_added": len(new_in_priority),
            "messages_dropped": len(lost_from_priority),
        },
        "messages": priority,
    }

    out_priority = session_dir / "opus_priority_messages.json"
    with open(out_priority, "w") as f:
        json.dump(priority_output, f, indent=2, default=str, ensure_ascii=False)

    # Write opus_extended_messages.json (replaces tier2plus_messages.json)
    extended_output = {
        "session_id": cls_data.get("session_id", ""),
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "generator": "build_opus_filtered.py",
        "filter_method": "opus_classification",
        "importance_levels_included": ["critical", "significant", "context"],
        "total_session_messages": len(all_messages),
        "messages_included": len(extended),
        "messages": extended,
    }

    out_extended = session_dir / "opus_extended_messages.json"
    with open(out_extended, "w") as f:
        json.dump(extended_output, f, indent=2, default=str, ensure_ascii=False)

    # Write safe version (metadata only, no raw content — for agents)
    safe_priority = []
    for msg in priority:
        safe_msg = {
            "index": msg.get("index"),
            "role": msg.get("role"),
            "timestamp": msg.get("timestamp"),
            "content_length": msg.get("content_length", 0),
            "content_preview": str(msg.get("content_preview", msg.get("content", "")))[:300],
            "filter_tier": msg.get("filter_tier"),
            "filter_signals": msg.get("filter_signals", []),
            "opus_importance": msg.get("opus_importance"),
            "opus_categories": msg.get("opus_categories", []),
            "opus_reason": msg.get("opus_reason", ""),
            "opus_connected_files": msg.get("opus_connected_files", []),
            "metadata": msg.get("metadata", {}),
            "behavior_flags": msg.get("behavior_flags", {}),
        }
        safe_priority.append(safe_msg)

    safe_output = {
        "session_id": cls_data.get("session_id", ""),
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "generator": "build_opus_filtered.py",
        "filter_method": "opus_classification",
        "importance_levels_included": ["critical", "significant"],
        "messages": safe_priority,
    }

    out_safe = session_dir / "safe_opus_priority.json"
    with open(out_safe, "w") as f:
        json.dump(safe_output, f, indent=2, default=str, ensure_ascii=False)

    print(f"\nWritten:")
    print(f"  {out_priority} ({out_priority.stat().st_size:,} bytes)")
    print(f"  {out_extended} ({out_extended.stat().st_size:,} bytes)")
    print(f"  {out_safe} ({out_safe.stat().st_size:,} bytes)")

    return {
        "priority_count": len(priority),
        "extended_count": len(extended),
        "new_messages": len(new_in_priority),
        "lost_messages": len(lost_from_priority),
        "critical": len(critical_msgs),
        "significant": len(significant_msgs),
        "context": len(context_msgs),
    }


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Build Opus-filtered message files")
    parser.add_argument("--session", default="", help="Session ID")
    parser.add_argument("--dir", default="", help="Session output directory")
    args = parser.parse_args()

    if args.dir:
        session_dir = Path(args.dir)
    elif args.session:
        candidates = [
            Path(__file__).resolve().parent.parent / "output" / f"session_{args.session[:8]}",
            Path.home() / "PERMANENT_HYPERDOCS" / "sessions" / f"session_{args.session[:8]}",
        ]
        session_dir = next((c for c in candidates if c.exists()), candidates[0])
    else:
        session_dir = get_session_output_dir()

    print("=" * 60)
    print("Build Opus-Filtered Message Files")
    print("=" * 60)
    print(f"Session: {session_dir}")
    print()

    result = build_opus_filtered(session_dir)
    if result:
        print(f"\n=== RESULT ===")
        print(f"Opus priority: {result['priority_count']} messages ({result['critical']} critical + {result['significant']} significant)")
        print(f"Opus extended: {result['extended_count']} messages (+ {result['context']} context)")
        print(f"Delta from Python: +{result['new_messages']} new, -{result['lost_messages']} dropped")


if __name__ == "__main__":
    main()
