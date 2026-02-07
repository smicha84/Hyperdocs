#!/usr/bin/env python3
"""
Prepare agent-friendly data files from enriched_session.json.

Splits the 8.5 MB enriched session into smaller, focused files that
extraction agents can read directly via the Read tool.
"""

import json
from pathlib import Path

INPUT = Path(__file__).parent / "output" / "session_3b7084d5" / "enriched_session.json"
OUT_DIR = INPUT.parent

print(f"Reading {INPUT}...")
with open(INPUT) as f:
    data = json.load(f)

messages = data["messages"]
stats = data["session_stats"]

# ── 1. Session summary (no messages) ─────────────────────────────────
summary = {k: v for k, v in data.items() if k != "messages"}
summary_file = OUT_DIR / "session_summary.json"
with open(summary_file, "w") as f:
    json.dump(summary, f, indent=2, default=str)
print(f"  session_summary.json: {summary_file.stat().st_size / 1024:.0f} KB")

# ── 2. Tier 2+ messages — full content for deep analysis ─────────────
tier2plus = [m for m in messages if m["filter_tier"] >= 2]
t2_file = OUT_DIR / "tier2plus_messages.json"
with open(t2_file, "w") as f:
    json.dump({"count": len(tier2plus), "messages": tier2plus}, f, indent=2, default=str)
print(f"  tier2plus_messages.json: {len(tier2plus)} msgs, "
      f"{t2_file.stat().st_size / 1024 / 1024:.1f} MB")

# ── 3. Tier 4 (priority) only — the most important messages ──────────
tier4 = [m for m in messages if m["filter_tier"] == 4]
t4_file = OUT_DIR / "tier4_priority_messages.json"
with open(t4_file, "w") as f:
    json.dump({"count": len(tier4), "messages": tier4}, f, indent=2, default=str)
print(f"  tier4_priority_messages.json: {len(tier4)} msgs, "
      f"{t4_file.stat().st_size / 1024 / 1024:.1f} MB")

# ── 4. Conversation condensed — all messages but content capped ───────
# Tier 4: full content, Tier 3: 1000 chars, Tier 2: 300 chars, Tier 1: 100 chars
condensed = []
for m in messages:
    tier = m["filter_tier"]
    content = m["content"]
    if tier == 4:
        cap = len(content)  # full
    elif tier == 3:
        cap = 1000
    elif tier == 2:
        cap = 300
    else:
        cap = 100

    condensed.append({
        "i": m["index"],
        "r": m["role"],
        "c": content[:cap] + ("..." if len(content) > cap else ""),
        "cl": m["content_length"],
        "t": m["filter_tier"],
        "ts": m["timestamp"],
        "meta": {
            "files": m["metadata"].get("files", []) if isinstance(m["metadata"], dict) else [],
            "error": m["metadata"].get("error", False) if isinstance(m["metadata"], dict) else False,
            "caps": m["metadata"].get("caps_ratio", 0) if isinstance(m["metadata"], dict) else 0,
            "profanity": m["metadata"].get("profanity", False) if isinstance(m["metadata"], dict) else False,
            "emergency": m["metadata"].get("emergency_intervention", False) if isinstance(m["metadata"], dict) else False,
        },
        "signals": m["filter_signals"],
        "behavior": m["behavior_flags"],
    })

condensed_file = OUT_DIR / "conversation_condensed.json"
with open(condensed_file, "w") as f:
    json.dump({"count": len(condensed), "messages": condensed}, f, indent=2, default=str)
print(f"  conversation_condensed.json: {len(condensed)} msgs, "
      f"{condensed_file.stat().st_size / 1024 / 1024:.1f} MB")

# ── 5. User messages only (for frustration/reaction analysis) ─────────
user_msgs = [m for m in messages if m["role"] == "user" and m["filter_tier"] >= 2]
user_file = OUT_DIR / "user_messages_tier2plus.json"
with open(user_file, "w") as f:
    json.dump({"count": len(user_msgs), "messages": user_msgs}, f, indent=2, default=str)
print(f"  user_messages_tier2plus.json: {len(user_msgs)} msgs, "
      f"{user_file.stat().st_size / 1024 / 1024:.1f} MB")

# ── 6. Emergency interventions — full context (5 msgs before + after) ─
emergency_indices = [m["index"] for m in messages
                     if isinstance(m["metadata"], dict)
                     and m["metadata"].get("emergency_intervention", False)]
emergency_windows = []
for ei in emergency_indices:
    window = [m for m in messages if ei - 5 <= m["index"] <= ei + 5]
    emergency_windows.append({
        "emergency_index": ei,
        "context_messages": window
    })

emerg_file = OUT_DIR / "emergency_contexts.json"
with open(emerg_file, "w") as f:
    json.dump({"count": len(emergency_windows), "windows": emergency_windows},
              f, indent=2, default=str)
print(f"  emergency_contexts.json: {len(emergency_windows)} windows")

# ── 7. Batch files for per-message processing ────────────────────────
# Split tier 2+ into batches of 30 messages for agents that need per-message analysis
batch_dir = OUT_DIR / "batches"
batch_dir.mkdir(exist_ok=True)
batch_size = 30
for i in range(0, len(tier2plus), batch_size):
    batch = tier2plus[i:i + batch_size]
    batch_file = batch_dir / f"batch_{i // batch_size + 1:03d}.json"
    with open(batch_file, "w") as f:
        json.dump({"batch_number": i // batch_size + 1,
                    "start_index": batch[0]["index"],
                    "end_index": batch[-1]["index"],
                    "count": len(batch),
                    "messages": batch}, f, indent=2, default=str)

n_batches = (len(tier2plus) + batch_size - 1) // batch_size
print(f"  batches/: {n_batches} batch files of ~{batch_size} messages each")

print(f"\nDone. All files in: {OUT_DIR}")
