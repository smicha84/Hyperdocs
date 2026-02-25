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
from tools.log_config import get_logger

logger = get_logger("phase0.prepare_agent_data")


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
    from config import get_session_output_dir, INDEXES_DIR
    OUT_DIR = get_session_output_dir()
except ImportError:
    SESSION_ID = os.getenv("HYPERDOCS_SESSION_ID", "")
    OUT_DIR = Path(os.getenv("HYPERDOCS_OUTPUT_DIR", "./output")) / f"session_{SESSION_ID[:8]}"
    INDEXES_DIR = Path(os.getenv("HYPERDOCS_STORE_DIR", str(Path.home() / "PERMANENT_HYPERDOCS"))) / "indexes"

# Prefer enriched_session_v2.json (has LLM pass results) over v1
INPUT_V2 = OUT_DIR / "enriched_session_v2.json"
INPUT_V1 = OUT_DIR / "enriched_session.json"
INPUT = INPUT_V2 if INPUT_V2.exists() else INPUT_V1

logger.info(f"Reading {INPUT} {'(v2 with LLM enrichment)' if 'v2' in INPUT.name else '(v1 base)'}...")
with open(INPUT) as f:
    data = json.load(f)

messages = data["messages"]
stats = data["session_stats"]

# ── 1. Session summary (no messages) ─────────────────────────────────
summary = {k: v for k, v in data.items() if k != "messages"}
summary_file = OUT_DIR / "session_metadata.json"
with open(summary_file, "w") as f:
    json.dump(summary, f, indent=2, default=str)
logger.info(f"  session_metadata.json: {summary_file.stat().st_size / 1024:.0f} KB")

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
logger.info(f"  emergency_contexts.json: {len(emergency_windows)} windows")

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
logger.info(f"  batches/: {n_batches} batch files of ~{batch_size} messages each")

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
    logger.info(f"  sanitized: {sanitized_count} files on disk")

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
logger.info(f"  safe_tier4.json: {len(safe_tier4)} msgs (full sanitized content)")

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
logger.info(f"  safe_condensed.json: {len(safe_condensed)} msgs (full sanitized content)")

logger.info(f"\nDone. All files in: {OUT_DIR}")

# ── 10. Opus-filtered files (if classifications exist) ─────────────────
# When opus_classifications.json exists (from opus_classifier.py), build
# Opus-filtered message files that Phase 1 agents should prefer over
# Python tier-filtered files.
opus_cls_path = OUT_DIR / "opus_classifications.json"
if opus_cls_path.exists():
    logger.info("\n── Opus classifications detected — building filtered files ──")
    try:
        from build_opus_messages import build_opus_filtered
        result = build_opus_filtered(OUT_DIR)
        if result:
            print(f"  Opus priority: {result['priority_count']} msgs "
                  f"(vs Python tier4: {len(tier4)} msgs)")
            print(f"  Delta: +{result['new_messages']} new, "
                  f"-{result['lost_messages']} dropped")
    except ImportError:
        # build_opus_messages.py not available — skip silently
        pass
    except (OSError, json.JSONDecodeError, KeyError, ValueError, TypeError) as e:
        logger.error(f"  Warning: Opus filtering failed: {e}")

    print("\nIMPORTANT: Agents should read safe_opus_priority.json and "
          "opus_priority_messages.json\n"
          "  instead of safe_tier4.json and tier4_priority_messages.json "
          "when Opus-filtered files exist.")
else:
    print("\nNote: No opus_classifications.json found. "
          "Run opus_classifier.py to enable Opus-filtered agent data.")

# ── 11. Code similarity context — filtered to session-mentioned files ──
# Loads the pre-computed code_similarity_index.json and filters to only
# matches where both files appear in this session's file_mention_counts
# (except dead_copy, which includes if EITHER file is mentioned).
# Matches with signal_score < 1.0 are filtered out as noise.
from datetime import datetime, timezone

code_sim_index_path = INDEXES_DIR / "code_similarity_index.json"
session_files = set(stats.get("file_mention_counts", {}).keys())

if code_sim_index_path.exists() and session_files:
    try:
        with open(code_sim_index_path) as f:
            sim_index = json.load(f)

        # Filter matches: require signal_score >= 1.0 to exclude noise
        # For dead_copy: include if EITHER file is in session (one copy may not appear)
        # For all other patterns: require BOTH files in session
        filtered_matches = []
        for m in sim_index.get("matches", []):
            if m.get("signals", {}).get("signal_score", 0) < 1.0:
                continue
            a_in = m["file_a"] in session_files
            b_in = m["file_b"] in session_files
            if a_in and b_in:
                filtered_matches.append(m)
            elif (a_in or b_in) and "dead_copy" in m.get("patterns", []):
                filtered_matches.append(m)

        # Collect file_stats for each session-mentioned file
        all_file_stats = sim_index.get("file_stats", {})
        filtered_file_stats = {
            fname: all_file_stats[fname]
            for fname in session_files
            if fname in all_file_stats
        }

        code_sim_context = {
            "session_id": stats.get("session_id", ""),
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "source_index": "code_similarity_index.json",
            "session_files_count": len(session_files),
            "matches_included": len(filtered_matches),
            "signal_score_threshold": 1.0,
            "dead_copy_either_file": True,
            "matches": filtered_matches,
            "file_stats": filtered_file_stats,
        }

        code_sim_file = OUT_DIR / "code_similarity_context.json"
        with open(code_sim_file, "w") as f:
            json.dump(code_sim_context, f, indent=2, default=str)
        logger.info(f"  code_similarity_context.json: {len(filtered_matches)} matches "
                    f"for {len(session_files)} session files "
                    f"({len(filtered_file_stats)} with stats)")
    except (OSError, json.JSONDecodeError, KeyError, ValueError, TypeError) as e:
        logger.error(f"  Warning: Code similarity context generation failed: {e}")
        code_sim_context = {
            "session_id": stats.get("session_id", ""),
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "source_index": "code_similarity_index.json",
            "session_files_count": len(session_files),
            "matches_included": 0,
            "matches": [],
            "file_stats": {},
            "error": str(e),
        }
        with open(OUT_DIR / "code_similarity_context.json", "w") as f:
            json.dump(code_sim_context, f, indent=2, default=str)
elif not code_sim_index_path.exists():
    logger.warning(f"  code_similarity_index.json not found at {code_sim_index_path} — skipping")
    code_sim_context = {
        "session_id": stats.get("session_id", ""),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_index": "code_similarity_index.json",
        "session_files_count": len(session_files),
        "matches_included": 0,
        "matches": [],
        "file_stats": {},
    }
    with open(OUT_DIR / "code_similarity_context.json", "w") as f:
        json.dump(code_sim_context, f, indent=2, default=str)
else:
    logger.info("  No files mentioned in session — skipping code similarity context")
    code_sim_context = {
        "session_id": stats.get("session_id", ""),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_index": "code_similarity_index.json",
        "session_files_count": 0,
        "matches_included": 0,
        "matches": [],
        "file_stats": {},
    }
    with open(OUT_DIR / "code_similarity_context.json", "w") as f:
        json.dump(code_sim_context, f, indent=2, default=str)

# ── 12. Lite genealogy — file families from temporal + name signals only ──
# Full file_genealogy.py needs Phase 1+2 outputs (idea graph), creating a
# circular dependency. Lite genealogy runs only the two signals that need
# Phase 0 data: temporal succession (file X stops, file Y starts) and
# name similarity (shared filename stems). Gives Phase 1 agents partial
# file family awareness without requiring their own outputs.
from phase_2_synthesis.file_genealogy import (
    detect_temporal_succession,
    detect_name_similarity,
    cluster_into_families,
    get_file_active_range,
)
from collections import defaultdict as _defaultdict
import re as _re


def _build_file_timelines_from_messages(messages_list):
    """Build per-file activity timelines from message metadata.files arrays.

    Returns: {filename: [{msg: N, action: "mentioned"}, ...]}
    """
    timelines = _defaultdict(list)
    for m in messages_list:
        idx = m.get("index", 0)
        meta = m.get("metadata", {})
        if not isinstance(meta, dict):
            continue
        files = meta.get("files", [])
        for f in files:
            if isinstance(f, str) and f.endswith(".py"):
                timelines[f].append({"msg": idx, "action": "mentioned"})
    # Sort each timeline by message index
    for f in timelines:
        timelines[f].sort(key=lambda x: x["msg"])
    return dict(timelines)


try:
    timelines = _build_file_timelines_from_messages(messages)

    if len(timelines) >= 2:
        temporal_links = detect_temporal_succession(timelines)
        name_links = detect_name_similarity(timelines)
        all_links = temporal_links + name_links

        families, standalone = cluster_into_families(all_links, timelines)

        lite_genealogy = {
            "session_id": stats.get("session_id", ""),
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "signals_used": ["temporal_succession", "name_similarity"],
            "signals_deferred": ["idea_graph_lineage"],
            "file_families": families,
            "standalone_files": standalone,
            "total_concepts": len(families) + len(standalone),
            "total_files": len(timelines),
            "reduction": f"{len(timelines)} files -> {len(families) + len(standalone)} concepts",
            "links_detected": {
                "temporal": len(temporal_links),
                "name_similarity": len(name_links),
                "total": len(all_links),
            },
        }
        logger.info(f"  lite_genealogy.json: {len(families)} families, "
                    f"{len(standalone)} standalone, {len(all_links)} links "
                    f"({len(timelines)} files)")
    else:
        lite_genealogy = {
            "session_id": stats.get("session_id", ""),
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "signals_used": ["temporal_succession", "name_similarity"],
            "signals_deferred": ["idea_graph_lineage"],
            "file_families": [],
            "standalone_files": list(timelines.keys()),
            "total_concepts": len(timelines),
            "total_files": len(timelines),
            "reduction": f"{len(timelines)} files -> {len(timelines)} concepts",
            "links_detected": {"temporal": 0, "name_similarity": 0, "total": 0},
        }
        logger.info(f"  lite_genealogy.json: <2 files, no families to detect")

    with open(OUT_DIR / "lite_genealogy.json", "w") as f:
        json.dump(lite_genealogy, f, indent=2, default=str)
except (ImportError, OSError, KeyError, ValueError, TypeError) as e:
    logger.error(f"  Warning: Lite genealogy generation failed: {e}")
    lite_genealogy = {
        "session_id": stats.get("session_id", ""),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "signals_used": [],
        "signals_deferred": ["idea_graph_lineage", "temporal_succession", "name_similarity"],
        "file_families": [],
        "standalone_files": [],
        "total_concepts": 0,
        "total_files": 0,
        "error": str(e),
    }
    with open(OUT_DIR / "lite_genealogy.json", "w") as f:
        json.dump(lite_genealogy, f, indent=2, default=str)
