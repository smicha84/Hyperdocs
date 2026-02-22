#!/usr/bin/env python3
"""
Option C Experiment: Enrich at Phase 4a aggregation time.

Approach: Expand aggregate_dossiers.py to also aggregate geological_notes,
semantic_primitives, explorer_notes, and file_genealogy across ALL sessions.
For each file in the cross-session index, collect all geological observations,
primitives distributions, explorer warnings, and genealogy links from every
session that mentions the file.

This is the only option that produces CROSS-SESSION data for each section.

Runs across all session directories. Produces enriched extract for geological_reader.py.
"""
import json
import os
from pathlib import Path
from collections import defaultdict

OUTPUT_DIR = Path(__file__).resolve().parent.parent / "output"
PERM_SESSIONS = Path.home() / "PERMANENT_HYPERDOCS" / "sessions"
CROSS_SESSION_INDEX = OUTPUT_DIR / "cross_session_file_index.json"
TARGET_FILE = "geological_reader.py"
OUTPUT_PATH = Path(__file__).resolve().parent / "output" / "option_c_geological_reader.json"


def mentions_file(text, filename):
    """Check if text mentions the target file."""
    if not text or not isinstance(text, str):
        return False
    base = filename.replace(".py", "")
    return filename in text or base in text


def load_session_json(session_dir, filename):
    """Load a JSON file from a session directory."""
    path = session_dir / filename
    if not path.exists():
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None


# ── Find all session directories ─────────────────────────────
print("Option C: Scanning all session directories...")

session_dirs = []
for search_dir in [OUTPUT_DIR, PERM_SESSIONS]:
    if not search_dir.exists():
        continue
    for d in sorted(search_dir.iterdir()):
        if d.is_dir() and d.name.startswith("session_"):
            session_dirs.append(d)

# Deduplicate by session ID (prefer PERMANENT version)
seen_sessions = {}
for d in session_dirs:
    sid = d.name.replace("session_", "")[:8]
    if sid not in seen_sessions or "PERMANENT" in str(d):
        seen_sessions[sid] = d

session_dirs = sorted(seen_sessions.values(), key=lambda d: d.name)
print(f"  Found {len(session_dirs)} unique sessions")


# ── Load cross-session index for baseline ─────────────────────
cross_session = {}
if CROSS_SESSION_INDEX.exists():
    with open(CROSS_SESSION_INDEX) as f:
        cross_session = json.load(f)

# Find geological_reader.py entry to know which sessions reference it
target_entry = None
cross_files = cross_session.get("files", {})
for key, entry in cross_files.items():
    if not isinstance(entry, dict):
        continue
    if TARGET_FILE == Path(key).name or TARGET_FILE in key:
        if entry.get("session_count", 0) > (target_entry or {}).get("session_count", 0):
            target_entry = entry

if target_entry:
    target_sessions = target_entry.get("sessions", [])
    print(f"  {TARGET_FILE}: {target_entry.get('session_count')} sessions, {target_entry.get('total_mentions')} mentions")
    print(f"  Sessions: {target_sessions[:10]}...")
else:
    target_sessions = [d.name.replace("session_", "")[:8] for d in session_dirs]
    print(f"  {TARGET_FILE}: NOT in cross-session index, scanning all")


# ── Aggregate across all relevant sessions ────────────────────
print("\n  Aggregating data across sessions...")

all_emotional = defaultdict(list)  # session -> [emotion entries]
cross_emotion_dist = defaultdict(int)
cross_confidence_dist = defaultdict(int)
cross_action_dist = defaultdict(int)

all_geological = defaultdict(list)  # session -> [observations]
all_explorer = defaultdict(list)    # session -> [observations]
all_timeline = []                   # flat list of all events
all_lineage = {}                    # from file_genealogy across sessions

sessions_with_data = set()

for session_dir in session_dirs:
    sid = session_dir.name.replace("session_", "")[:8]

    # Only process sessions that reference the target file
    if target_sessions and sid not in target_sessions:
        # Quick check: does this session's thread_extractions mention the file?
        threads = load_session_json(session_dir, "thread_extractions.json")
        if threads:
            found = False
            threads_data = threads.get("threads", {})
            if isinstance(threads_data, dict):
                for tk, tv in threads_data.items():
                    if not isinstance(tv, dict):
                        continue
                    for entry in tv.get("entries", []):
                        if mentions_file(entry.get("content", ""), TARGET_FILE):
                            found = True
                            break
                    if found:
                        break
            if not found:
                continue
        else:
            continue

    sessions_with_data.add(sid)

    # ── Semantic Primitives ──────────────────────────────────
    primitives = load_session_json(session_dir, "semantic_primitives.json")
    if primitives:
        dist = primitives.get("distributions", {})
        for emotion, count in dist.get("emotional_tenor", {}).items():
            cross_emotion_dist[emotion] += count
        for conf, count in dist.get("confidence_signal", {}).items():
            cross_confidence_dist[conf] += count
        for action, count in dist.get("action_vector", {}).items():
            cross_action_dist[action] += count

        summary = primitives.get("summary_statistics", {})
        all_emotional[sid].append({
            "dominant_emotion": summary.get("dominant_emotion", ""),
            "session_arc": summary.get("session_arc", ""),
            "friction_episodes": summary.get("friction_episodes", 0),
            "distribution": dist.get("emotional_tenor", {}),
        })

    # ── Geological Notes ─────────────────────────────────────
    geo = load_session_json(session_dir, "geological_notes.json")
    if geo:
        for zoom in ["micro", "meso", "macro"]:
            for obs in geo.get(zoom, []):
                text = obs.get("observation", "") if isinstance(obs, dict) else str(obs)
                if mentions_file(text, TARGET_FILE):
                    entry = obs if isinstance(obs, dict) else {"observation": text}
                    entry["session"] = sid
                    entry["zoom_level"] = zoom
                    all_geological[sid].append(entry)

        for obs in geo.get("observations", []):
            text = obs if isinstance(obs, str) else obs.get("observation", "") if isinstance(obs, dict) else str(obs)
            if mentions_file(text, TARGET_FILE):
                entry = obs if isinstance(obs, dict) else {"observation": text}
                if isinstance(entry, dict):
                    entry["session"] = sid
                    entry["zoom_level"] = "observation"
                all_geological[sid].append(entry)

    # ── Explorer Notes ───────────────────────────────────────
    explorer = load_session_json(session_dir, "explorer_notes.json")
    if explorer:
        for obs in explorer.get("observations", []):
            text = obs if isinstance(obs, str) else obs.get("observation", "") if isinstance(obs, dict) else str(obs)
            if mentions_file(text, TARGET_FILE):
                entry = obs if isinstance(obs, dict) else {"observation": text}
                if isinstance(entry, dict):
                    entry["session"] = sid
                all_explorer[sid].append(entry)

    # ── Thread Extractions (Timeline) ────────────────────────
    threads = load_session_json(session_dir, "thread_extractions.json")
    if threads:
        threads_data = threads.get("threads", {})
        # Handle both dict and list schemas
        if isinstance(threads_data, dict):
            for thread_key, thread_val in threads_data.items():
                if not isinstance(thread_val, dict):
                    continue
                for entry in thread_val.get("entries", []):
                    content = entry.get("content", "") if isinstance(entry, dict) else ""
                    if mentions_file(content, TARGET_FILE):
                        all_timeline.append({
                            "session": sid,
                            "msg_index": entry.get("msg_index", -1),
                            "thread": thread_key,
                            "content": content,
                            "significance": entry.get("significance", ""),
                        })
        elif isinstance(threads_data, list):
            # Some sessions have threads as a flat list of extraction dicts
            for ext in threads_data:
                if not isinstance(ext, dict):
                    continue
                sw = ext.get("threads", {})
                if isinstance(sw, dict):
                    for thread_key in sw:
                        entries = sw[thread_key]
                        if isinstance(entries, list):
                            for entry_item in entries:
                                if isinstance(entry_item, str) and mentions_file(entry_item, TARGET_FILE):
                                    all_timeline.append({
                                        "session": sid,
                                        "msg_index": ext.get("msg_index", -1),
                                        "thread": thread_key,
                                        "content": entry_item,
                                        "significance": "",
                                    })

    # ── File Genealogy ───────────────────────────────────────
    gen = load_session_json(session_dir, "file_genealogy.json")
    if gen:
        for fam in gen.get("file_families", []):
            versions = fam.get("versions", fam.get("members", fam.get("files", [])))
            member_names = [v if isinstance(v, str) else v.get("file", "") for v in versions]
            if any(TARGET_FILE in m for m in member_names):
                family_name = fam.get("concept", fam.get("name", "unnamed"))
                if family_name not in all_lineage:
                    all_lineage[family_name] = {
                        "family_name": family_name,
                        "members": member_names,
                        "sessions": [sid],
                    }
                else:
                    all_lineage[family_name]["sessions"].append(sid)
                    # Merge members
                    existing = set(all_lineage[family_name]["members"])
                    for m in member_names:
                        if m not in existing:
                            all_lineage[family_name]["members"].append(m)

print(f"  Sessions with data for {TARGET_FILE}: {len(sessions_with_data)}")
print(f"    Session IDs: {sorted(sessions_with_data)}")


# ── Build output sections ────────────────────────────────────

# 1. Emotional Arc (cross-session)
emotional_arc = {
    "cross_session_emotion_distribution": dict(cross_emotion_dist),
    "cross_session_confidence_distribution": dict(cross_confidence_dist),
    "cross_session_action_distribution": dict(cross_action_dist),
    "per_session_emotions": dict(all_emotional),
    "sessions_with_emotional_data": len(all_emotional),
    "data_points": sum(len(v) for v in all_emotional.values()),
}

# 2. Geological Character (cross-session)
flat_geological = []
for sid_obs in all_geological.values():
    flat_geological.extend(sid_obs)

geological_character = {
    "cross_session_observations": flat_geological,
    "sessions_with_geological_data": len(all_geological),
    "by_zoom_level": {
        zoom: [o for o in flat_geological if o.get("zoom_level") == zoom]
        for zoom in ["micro", "meso", "macro", "observation"]
    },
    "data_points": len(flat_geological),
}

# 3. Lineage (cross-session)
cross_genealogy = target_entry.get("genealogy") if target_entry else None
confidence_history = target_entry.get("confidence_history", []) if target_entry else []
story_arcs = target_entry.get("story_arcs", []) if target_entry else []

lineage = {
    "cross_session_families": list(all_lineage.values()),
    "cross_session_genealogy": cross_genealogy,
    "confidence_history": confidence_history,
    "story_arcs": story_arcs,
    "sessions_referenced": sorted(sessions_with_data),
    "data_points": len(all_lineage) + len(confidence_history) + len(story_arcs),
}

# 4. Explorer Observations (cross-session)
flat_explorer = []
for sid_obs in all_explorer.values():
    flat_explorer.extend(sid_obs)

explorer_observations = {
    "cross_session_observations": flat_explorer,
    "sessions_with_explorer_data": len(all_explorer),
    "data_points": len(flat_explorer),
}

# 5. Chronological Timeline (cross-session, sorted by session then msg_index)
all_timeline.sort(key=lambda x: (x.get("session", ""), x.get("msg_index", 0)))

chronological_timeline = {
    "cross_session_events": all_timeline,
    "sessions_with_timeline": len(set(t["session"] for t in all_timeline)),
    "data_points": len(all_timeline),
}

# 6. Code Similarity (from cross-session index)
code_sim = target_entry.get("code_similarity", []) if target_entry else []
code_similarity = {
    "matches": code_sim,
    "data_points": len(code_sim),
}


# ── Assemble output ──────────────────────────────────────────
output = {
    "file": TARGET_FILE,
    "option": "C",
    "approach": "Enrich at Phase 4a aggregation (cross-session)",
    "sessions_scanned": len(session_dirs),
    "sessions_with_data": len(sessions_with_data),
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

print(f"\nOption C output: {OUTPUT_PATH}")
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
