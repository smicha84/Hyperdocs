#!/usr/bin/env python3
"""
Option B Experiment: New evidence collector script.

Approach: A dedicated script reads ALL 8 data sources and builds a
comprehensive per-file evidence package. For each file mentioned in
session_metadata.top_files, it collects:
  - Every message that mentions the file
  - Every primitive tagged on those messages AND messages in the time window
  - Every geological observation about that file's time window
  - Every explorer note referencing it
  - Genealogy links
  - Similarity matches
  - Chronological timeline from all thread entries

Key difference from Option A: correlates by TIME WINDOW (±10 messages
around each mention), not just by filename string match. This captures
context that's related to the file but doesn't name it explicitly.

Runs on session 513d4807. Produces evidence for geological_reader.py.
"""
import json
import os
import re
from pathlib import Path
from collections import defaultdict

SESSION_DIR = Path(__file__).resolve().parent.parent / "output" / "session_513d4807"
PERM_SESSION_DIR = Path.home() / "PERMANENT_HYPERDOCS" / "sessions" / "session_513d4807"
CROSS_SESSION_INDEX = Path(__file__).resolve().parent.parent / "output" / "cross_session_file_index.json"
TARGET_FILE = "geological_reader.py"
OUTPUT_PATH = Path(__file__).resolve().parent / "output" / "option_b_geological_reader.json"
WINDOW = 10  # Messages before/after a mention to include as context


def load_json(filename, search_dirs=None):
    """Load JSON from the first directory where the file exists."""
    if search_dirs is None:
        search_dirs = [SESSION_DIR, PERM_SESSION_DIR]
    for d in search_dirs:
        path = d / filename
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
    print(f"  WARNING: {filename} not found in any search dir")
    return {}


def mentions_file(text, filename):
    """Check if text mentions the target file."""
    if not text or not isinstance(text, str):
        return False
    base = filename.replace(".py", "")
    return filename in text or base in text


def in_window(msg_index, mention_indices, window=WINDOW):
    """Check if a message index is within the window of any mention."""
    for m in mention_indices:
        if m >= 0 and abs(msg_index - m) <= window:
            return True
    return False


# ── Load ALL 8 data sources ──────────────────────────────────
print(f"Option B: Loading all data sources for session 513d4807")

session_metadata = load_json("session_metadata.json")
geological_notes = load_json("geological_notes.json")
semantic_primitives = load_json("semantic_primitives.json")
explorer_notes = load_json("explorer_notes.json")
file_genealogy = load_json("file_genealogy.json")
thread_extractions = load_json("thread_extractions.json")
idea_graph = load_json("idea_graph.json")
grounded_markers = load_json("grounded_markers.json")

cross_session = {}
if CROSS_SESSION_INDEX.exists():
    with open(CROSS_SESSION_INDEX) as f:
        cross_session = json.load(f)


# ── Step 1: Find ALL message indices that mention the file ───
print("  Step 1: Finding all mention indices...")

mention_indices = set()

# From thread extractions
threads_dict = thread_extractions.get("threads", {})
for thread_key, thread_val in threads_dict.items():
    if not isinstance(thread_val, dict):
        continue
    for entry in thread_val.get("entries", []):
        content = entry.get("content", "") if isinstance(entry, dict) else ""
        if mentions_file(content, TARGET_FILE):
            mention_indices.add(entry.get("msg_index", -1))

# From PERMANENT version dossiers (has first/last mention index)
perm_dossier = load_json("file_dossiers.json", [PERM_SESSION_DIR])
for k, v in perm_dossier.get("dossiers", {}).items():
    if isinstance(v, dict) and v.get("file_name") == TARGET_FILE:
        for idx_key in ("first_mention_index", "last_mention_index"):
            idx_val = v.get(idx_key)
            if idx_val is not None:
                mention_indices.add(idx_val)
        # Also check mentioned_in
        for mi in v.get("mentioned_in", []):
            if isinstance(mi, dict):
                mention_indices.add(mi.get("msg_index", -1))
            elif isinstance(mi, int):
                mention_indices.add(mi)
        break

# From geological notes (check all zoom levels for the file)
for zoom in ["micro", "meso", "macro"]:
    for obs in geological_notes.get(zoom, []):
        text = obs.get("observation", "") if isinstance(obs, dict) else str(obs)
        if mentions_file(text, TARGET_FILE):
            msg_range = obs.get("message_range", [])
            if isinstance(msg_range, list) and len(msg_range) == 2:
                mention_indices.update(range(msg_range[0], msg_range[1] + 1))

mention_indices.discard(-1)
print(f"    Found {len(mention_indices)} mention indices: {sorted(mention_indices)[:20]}...")


# ── Step 2: Build time window ────────────────────────────────
# All message indices within WINDOW of any mention
window_indices = set()
for m in mention_indices:
    for offset in range(-WINDOW, WINDOW + 1):
        window_indices.add(m + offset)
window_indices = {i for i in window_indices if i >= 0}
print(f"    Window ({WINDOW}): {len(window_indices)} indices in range")


# ── 1. Emotional Arc ─────────────────────────────────────────
print("  Building emotional_arc...")

tagged = semantic_primitives.get("tagged_messages", [])
distributions = semantic_primitives.get("distributions", {})
summary_stats = semantic_primitives.get("summary_statistics", {})

# Collect ALL tagged messages in the time window
window_emotions = []
for tm in tagged:
    idx = tm.get("msg_index", -1)
    if idx in window_indices:
        window_emotions.append({
            "msg_index": idx,
            "emotional_tenor": tm.get("emotional_tenor", "unknown"),
            "confidence_signal": tm.get("confidence_signal", "unknown"),
            "action_vector": tm.get("action_vector", "unknown"),
            "intent_marker": tm.get("intent_marker", "unknown"),
            "friction_log": tm.get("friction_log", ""),
            "decision_trace": tm.get("decision_trace", ""),
            "is_direct_mention": idx in mention_indices,
        })

# Compute per-file emotion distribution
file_emotion_dist = defaultdict(int)
for em in window_emotions:
    file_emotion_dist[em["emotional_tenor"]] += 1

# Emotion trajectory (ordered)
window_emotions.sort(key=lambda x: x["msg_index"])
emotion_trajectory = [{"idx": e["msg_index"], "emotion": e["emotional_tenor"]}
                     for e in window_emotions]

emotional_arc = {
    "session_distribution": distributions.get("emotional_tenor", {}),
    "file_window_distribution": dict(file_emotion_dist),
    "emotion_trajectory": emotion_trajectory,
    "session_arc": summary_stats.get("session_arc", ""),
    "dominant_emotion": summary_stats.get("dominant_emotion", ""),
    "friction_episodes": summary_stats.get("friction_episodes", 0),
    "file_nearby_emotions": window_emotions,
    "data_points": len(window_emotions),
}


# ── 2. Geological Character ──────────────────────────────────
print("  Building geological_character...")

# Collect observations that EITHER mention the file OR overlap the time window
file_micro = []
for obs in geological_notes.get("micro", []):
    text = obs.get("observation", "") if isinstance(obs, dict) else str(obs)
    msg_range = obs.get("message_range", []) if isinstance(obs, dict) else []
    # Match by filename OR by time window overlap
    if mentions_file(text, TARGET_FILE):
        if isinstance(obs, dict):
            obs["match_reason"] = "filename"
        file_micro.append(obs)
    elif isinstance(msg_range, list) and len(msg_range) == 2:
        obs_range = set(range(msg_range[0], msg_range[1] + 1))
        if obs_range & mention_indices:  # Direct overlap with mention
            if isinstance(obs, dict):
                obs["match_reason"] = "time_window"
            file_micro.append(obs)

file_meso = []
for obs in geological_notes.get("meso", []):
    text = obs.get("observation", "") if isinstance(obs, dict) else str(obs)
    msg_range = obs.get("message_range", []) if isinstance(obs, dict) else []
    if mentions_file(text, TARGET_FILE):
        if isinstance(obs, dict):
            obs["match_reason"] = "filename"
        file_meso.append(obs)
    elif isinstance(msg_range, list) and len(msg_range) == 2:
        obs_range = set(range(msg_range[0], msg_range[1] + 1))
        if obs_range & mention_indices:
            if isinstance(obs, dict):
                obs["match_reason"] = "time_window"
            file_meso.append(obs)

file_macro = []
for obs in geological_notes.get("macro", []):
    text = obs.get("observation", "") if isinstance(obs, dict) else str(obs)
    if mentions_file(text, TARGET_FILE):
        if isinstance(obs, dict):
            obs["match_reason"] = "filename"
        file_macro.append(obs)

file_observations = []
for obs in geological_notes.get("observations", []):
    text = obs if isinstance(obs, str) else obs.get("observation", "") if isinstance(obs, dict) else str(obs)
    if mentions_file(text, TARGET_FILE):
        file_observations.append(obs)

geological_character = {
    "micro_observations": file_micro,
    "meso_observations": file_meso,
    "macro_observations": file_macro,
    "standalone_observations": file_observations,
    "geological_metaphor": geological_notes.get("geological_metaphor", ""),
    "data_points": len(file_micro) + len(file_meso) + len(file_macro) + len(file_observations),
}


# ── 3. Lineage ────────────────────────────────────────────────
print("  Building lineage...")

# Per-session genealogy
families = file_genealogy.get("file_families", [])
session_family = None
for fam in families:
    versions = fam.get("versions", fam.get("members", fam.get("files", [])))
    member_names = [v if isinstance(v, str) else v.get("file", "") for v in versions]
    if any(TARGET_FILE in m for m in member_names):
        session_family = {
            "family_name": fam.get("concept", fam.get("name", "unnamed")),
            "members": member_names,
            "source": "session_513d4807",
        }
        break

# Cross-session genealogy + confidence history + all sessions
cross_files = cross_session.get("files", {})
cross_genealogy = None
cross_confidence_history = []
cross_sessions = []
cross_story_arcs = []
for key, entry in cross_files.items():
    if not isinstance(entry, dict):
        continue
    if TARGET_FILE == Path(key).name or TARGET_FILE in key:
        gen = entry.get("genealogy")
        if gen:
            cross_genealogy = gen
        cross_confidence_history = entry.get("confidence_history", [])
        cross_sessions = entry.get("sessions", [])
        cross_story_arcs = entry.get("story_arcs", [])
        break

# Also check idea_graph for lineage-related nodes
lineage_nodes = []
for node in idea_graph.get("nodes", []):
    if isinstance(node, dict):
        label = node.get("label", node.get("id", ""))
        if mentions_file(label, TARGET_FILE) or "geological_reader" in str(node).lower():
            lineage_nodes.append({
                "id": node.get("id", ""),
                "label": label,
                "state": node.get("state", ""),
                "confidence": node.get("confidence", ""),
            })

lineage = {
    "session_family": session_family,
    "cross_session_family": cross_genealogy,
    "confidence_history": cross_confidence_history,
    "cross_session_story_arcs": cross_story_arcs,
    "sessions_referenced": cross_sessions,
    "idea_graph_lineage_nodes": lineage_nodes,
    "data_points": ((1 if session_family else 0) +
                   (1 if cross_genealogy else 0) +
                   len(cross_confidence_history) +
                   len(lineage_nodes)),
}


# ── 4. Explorer Observations ─────────────────────────────────
print("  Building explorer_observations...")

file_explorer_obs = []
for obs in explorer_notes.get("observations", []):
    text = obs if isinstance(obs, str) else obs.get("observation", "") if isinstance(obs, dict) else str(obs)
    if mentions_file(text, TARGET_FILE):
        file_explorer_obs.append(obs)

# Check verification section for per-agent issues
verification = explorer_notes.get("verification", {})
file_verification = {}
for section_key, section_val in verification.items():
    if isinstance(section_val, str) and mentions_file(section_val, TARGET_FILE):
        file_verification[section_key] = section_val
    elif isinstance(section_val, list):
        matching = [item for item in section_val
                   if mentions_file(str(item), TARGET_FILE)]
        if matching:
            file_verification[section_key] = matching
    elif isinstance(section_val, dict):
        for sub_key, sub_val in section_val.items():
            if mentions_file(str(sub_val), TARGET_FILE):
                file_verification[f"{section_key}.{sub_key}"] = sub_val

explorer_summary = explorer_notes.get("explorer_summary", "")

# Also pull anomalies
anomalies = []
for obs in explorer_notes.get("observations", []):
    if isinstance(obs, dict) and obs.get("id", "").startswith("anomaly"):
        if mentions_file(obs.get("observation", ""), TARGET_FILE):
            anomalies.append(obs)

explorer_observations = {
    "observations": file_explorer_obs,
    "verification_issues": file_verification,
    "anomalies": anomalies,
    "session_explorer_summary": explorer_summary if mentions_file(explorer_summary, TARGET_FILE) else "",
    "data_points": len(file_explorer_obs) + len(file_verification) + len(anomalies),
}


# ── 5. Chronological Timeline ────────────────────────────────
print("  Building chronological_timeline...")

# Collect ALL thread entries that mention the file, from ALL threads
timeline = []
for thread_key, thread_val in threads_dict.items():
    if not isinstance(thread_val, dict):
        continue
    for entry in thread_val.get("entries", []):
        content = entry.get("content", "") if isinstance(entry, dict) else ""
        if mentions_file(content, TARGET_FILE):
            timeline.append({
                "msg_index": entry.get("msg_index", -1),
                "thread": thread_key,
                "content": content,
                "significance": entry.get("significance", ""),
            })

# Also add grounded_markers that reference the file
markers = grounded_markers.get("markers", [])
for m in markers:
    if not isinstance(m, dict):
        continue
    marker_text = json.dumps(m)
    if mentions_file(marker_text, TARGET_FILE):
        timeline.append({
            "msg_index": m.get("msg_index", m.get("first_discovered", -1)),
            "thread": "grounded_marker",
            "content": m.get("claim", m.get("warning", m.get("title", "")))[:500],
            "significance": m.get("severity", m.get("priority", "")),
        })

timeline.sort(key=lambda x: x.get("msg_index", 0) if isinstance(x.get("msg_index"), int) else 0)

# Deduplicate by (msg_index, thread) pair
seen = set()
deduped = []
for t in timeline:
    key = (t.get("msg_index"), t.get("thread"))
    if key not in seen:
        seen.add(key)
        deduped.append(t)

chronological_timeline = {
    "events": deduped,
    "data_points": len(deduped),
}


# ── 6. Code Similarity ───────────────────────────────────────
print("  Building code_similarity...")

code_sim = []
for key, entry in cross_files.items():
    if not isinstance(entry, dict):
        continue
    if TARGET_FILE == Path(key).name or TARGET_FILE in key:
        code_sim = entry.get("code_similarity", [])
        if code_sim:
            break

code_similarity = {
    "matches": code_sim,
    "data_points": len(code_sim),
}


# ── Assemble output ──────────────────────────────────────────
output = {
    "file": TARGET_FILE,
    "session": "513d4807",
    "option": "B",
    "approach": "New evidence collector with time-window correlation",
    "mention_indices": sorted(mention_indices),
    "window_size": WINDOW,
    "emotional_arc": emotional_arc,
    "geological_character": geological_character,
    "lineage": lineage,
    "explorer_observations": explorer_observations,
    "chronological_timeline": chronological_timeline,
    "code_similarity": code_similarity,
}

OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
with open(OUTPUT_PATH, "w") as f:
    json.dump(output, f, indent=2, ensure_ascii=False)

print(f"\nOption B output: {OUTPUT_PATH}")
print(f"  Size: {OUTPUT_PATH.stat().st_size:,} bytes")

# Summary
sections = ["emotional_arc", "geological_character", "lineage",
            "explorer_observations", "chronological_timeline", "code_similarity"]
total_dp = 0
for s in sections:
    dp = output[s].get("data_points", 0)
    total_dp += dp
    print(f"  {s}: {dp} data points")
print(f"  TOTAL: {total_dp} data points")
