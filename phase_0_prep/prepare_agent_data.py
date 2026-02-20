#!/usr/bin/env python3
"""
Prepare agent-friendly data files from enriched_session.json.

Splits the 8.5 MB enriched session into smaller, focused files that
extraction agents can read directly via the Read tool.
"""

import os
import sys
import json
from pathlib import Path


def _collapse_preview(text: str) -> str:
    """Collapse char-per-line encoded text for readable previews."""
    if not text or '\n' not in text:
        return text
    lines = text.split('\n')
    if len(lines) < 4:
        return text
    single_char = sum(1 for l in lines if len(l) <= 1)
    if single_char / len(lines) > 0.7 and len(lines) > 6:
        return ''.join(lines)
    return text

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
try:
    from config import get_session_output_dir
    OUT_DIR = get_session_output_dir()
except ImportError:
    SESSION_ID = os.getenv("HYPERDOCS_SESSION_ID", "")
    OUT_DIR = Path(os.getenv("HYPERDOCS_OUTPUT_DIR", "./output")) / f"session_{SESSION_ID[:8]}"

INPUT = OUT_DIR / "enriched_session.json"

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

# ── 4. Conversation condensed — all messages, full sanitized content ──
# Content is already profanity-sanitized (step 8 runs before safe file generation).
# No truncation — agents need full content for accurate classification.
condensed = []
for m in messages:
    content = m["content"]

    condensed.append({
        "i": m["index"],
        "r": m["role"],
        "c": content,
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
        "is_protocol": m.get("is_protocol", False),
        "protocol_type": m.get("protocol_type"),
        "was_char_encoded": m.get("was_char_encoded", False),
        "content_ref": m.get("filter_signals_content_referential", False),
        "llm_behavior": m.get("llm_behavior"),
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

# ── 8. Sanitize profanity in all output files + in-memory data ────────
# Two-pass sanitization:
#   Pass 1: Sanitize JSON files already written to disk (steps 1-7)
#   Pass 2: Sanitize in-memory data so safe files (step 9) get clean content
profanity_map = {
    'fuck': '[expletive]', 'Fuck': '[Expletive]', 'FUCK': '[EXPLETIVE]',
    'fucking': '[expletive]', 'Fucking': '[Expletive]', 'FUCKING': '[EXPLETIVE]',
    'fucked': '[expletive]', 'fucker': '[expletive]',
    'shit': '[expletive]', 'Shit': '[Expletive]', 'SHIT': '[EXPLETIVE]',
    'cunt': '[expletive]', 'CUNT': '[EXPLETIVE]',
    'bitch': '[expletive]', 'asshole': '[expletive]', 'goddamn': '[expletive]',
}
keystroke_map = {
    'f\\nu\\nc\\nk': '[expletive]', 's\\nh\\ni\\nt': '[expletive]',
    'c\\nu\\nn\\nt': '[expletive]', 'b\\ni\\nt\\nc\\nh': '[expletive]',
}


def _sanitize_text(text):
    """Remove profanity from text for API content policy compliance."""
    for word, repl in profanity_map.items():
        text = text.replace(word, repl)
    for ks, repl in keystroke_map.items():
        text = text.replace(ks, repl)
    return text


# Pass 1: Sanitize files on disk
sanitized_count = 0
for json_file in OUT_DIR.glob("**/*.json"):
    content = json_file.read_text()
    original = content
    content = _sanitize_text(content)
    if content != original:
        json_file.write_text(content)
        sanitized_count += 1

if sanitized_count:
    print(f"  sanitized: {sanitized_count} files on disk")

# Pass 2: Sanitize in-memory data (tier4, condensed) so safe files get clean content
for m in tier4:
    if m.get("content"):
        m["content"] = _sanitize_text(m["content"])
for m in condensed:
    if m.get("c"):
        m["c"] = _sanitize_text(m["c"])

# ── 9. Create safe files with FULL sanitized content for agents ──────
# Content is now profanity-free. No truncation. Agents get the complete picture.
safe_tier4 = []
for m in tier4:
    safe_tier4.append({
        "index": m.get("index", 0),
        "role": m.get("role", ""),
        "timestamp": m.get("timestamp", ""),
        "content_length": m.get("content_length", 0),
        "filter_tier": m.get("filter_tier", 0),
        "filter_signals": m.get("filter_signals", []),
        "behavior_flags": m.get("behavior_flags", {}),
        "metadata": m.get("metadata", {}),
        "content": _collapse_preview(str(m.get("content", ""))),
        "is_protocol": m.get("is_protocol", False),
        "protocol_type": m.get("protocol_type"),
        "was_char_encoded": m.get("was_char_encoded", False),
        "content_ref": m.get("filter_signals_content_referential", False),
        "llm_behavior": m.get("llm_behavior"),
    })

safe_t4_file = OUT_DIR / "safe_tier4.json"
with open(safe_t4_file, "w") as f:
    json.dump({"count": len(safe_tier4), "messages": safe_tier4}, f, indent=2, default=str)
print(f"  safe_tier4.json: {len(safe_tier4)} msgs (full sanitized content)")

safe_condensed = []
for m in condensed:
    safe_condensed.append({
        "i": m.get("i", m.get("index", 0)),
        "r": m.get("r", m.get("role", "")),
        "c": m.get("c", ""),
        "cl": m.get("cl", m.get("content_length", 0)),
        "t": m.get("t", m.get("filter_tier", 0)),
        "ts": m.get("ts", m.get("timestamp", "")),
        "meta": m.get("meta", m.get("metadata", {})),
        "signals": m.get("signals", m.get("filter_signals", [])),
        "behavior": m.get("behavior", m.get("behavior_flags", {})),
        "is_protocol": m.get("is_protocol", False),
        "protocol_type": m.get("protocol_type"),
        "was_char_encoded": m.get("was_char_encoded", False),
        "content_ref": m.get("content_ref", False),
        "llm_behavior": m.get("llm_behavior"),
    })

safe_cond_file = OUT_DIR / "safe_condensed.json"
with open(safe_cond_file, "w") as f:
    json.dump({"count": len(safe_condensed), "messages": safe_condensed}, f, indent=2, default=str)
print(f"  safe_condensed.json: {len(safe_condensed)} msgs (full sanitized content)")

print(f"\nDone. All files in: {OUT_DIR}")

# ── 10. Opus-filtered files (if classifications exist) ─────────────────
# When opus_classifications.json exists (from opus_classifier.py), build
# Opus-filtered message files that Phase 1 agents should prefer over
# Python tier-filtered files.
opus_cls_path = OUT_DIR / "opus_classifications.json"
if opus_cls_path.exists():
    print("\n── Opus classifications detected — building filtered files ──")
    try:
        from build_opus_filtered import build_opus_filtered
        result = build_opus_filtered(OUT_DIR)
        if result:
            print(f"  Opus priority: {result['priority_count']} msgs "
                  f"(vs Python tier4: {len(tier4)} msgs)")
            print(f"  Delta: +{result['new_messages']} new, "
                  f"-{result['lost_messages']} dropped")
    except ImportError:
        # build_opus_filtered.py not available — skip silently
        pass
    except Exception as e:
        print(f"  Warning: Opus filtering failed: {e}")

    print("\nIMPORTANT: Agents should read safe_opus_priority.json and "
          "opus_priority_messages.json\n"
          "  instead of safe_tier4.json and tier4_priority_messages.json "
          "when Opus-filtered files exist.")
else:
    print("\nNote: No opus_classifications.json found. "
          "Run opus_classifier.py to enable Opus-filtered agent data.")
