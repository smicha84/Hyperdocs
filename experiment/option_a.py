#!/usr/bin/env python3
"""
Option A Experiment: Expand generate_dossiers.py with 5 new data readers.

Approach: After the existing dossier loop, read geological_notes.json,
semantic_primitives.json, explorer_notes.json, file_genealogy.json.
Correlate each with the target file by scanning for filename mentions.
Add 6 new keys to each dossier dict.

Runs on session 513d4807. Produces dossier for geological_reader.py.
"""
import json
import os
import re
from pathlib import Path
from collections import defaultdict

SESSION_DIR = Path(__file__).resolve().parent.parent / "output" / "session_513d4807"
CROSS_SESSION_INDEX = Path(__file__).resolve().parent.parent / "output" / "cross_session_file_index.json"
TARGET_FILE = "geological_reader.py"
OUTPUT_PATH = Path(__file__).resolve().parent / "output" / "option_a_geological_reader.json"


def load_json(filename):
    path = SESSION_DIR / filename
    if not path.exists():
        print(f"  WARNING: {filename} not found at {path}")
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def mentions_file(text, filename):
    """Check if text mentions the target file (by name or base name)."""
    if not text or not isinstance(text, str):
        return False
    base = filename.replace(".py", "")
    return filename in text or base in text


# ── Load session data ─────────────────────────────────────────
print(f"Option A: Loading data from {SESSION_DIR}")
session_metadata = load_json("session_metadata.json")
geological_notes = load_json("geological_notes.json")
semantic_primitives = load_json("semantic_primitives.json")
explorer_notes = load_json("explorer_notes.json")
file_genealogy = load_json("file_genealogy.json")
thread_extractions = load_json("thread_extractions.json")

# Also load cross-session index for code similarity
cross_session = {}
if CROSS_SESSION_INDEX.exists():
    with open(CROSS_SESSION_INDEX) as f:
        cross_session = json.load(f)


# ── 1. Emotional Arc ─────────────────────────────────────────
# From semantic_primitives: tagged messages that occur near messages
# mentioning the target file, plus overall distribution
print("  Building emotional_arc...")

tagged = semantic_primitives.get("tagged_messages", [])
distributions = semantic_primitives.get("distributions", {})
summary_stats = semantic_primitives.get("summary_statistics", {})

# Find messages near the file's mention (within ±5 messages of any mention)
# Scan thread_extractions for message indices that mention the file
file_mention_indices = set()
threads_scan = thread_extractions.get("threads", {})
for thread_key, thread_val in threads_scan.items():
    if not isinstance(thread_val, dict):
        continue
    for entry in thread_val.get("entries", []):
        content = entry.get("content", "") if isinstance(entry, dict) else ""
        if mentions_file(content, TARGET_FILE):
            file_mention_indices.add(entry.get("msg_index", -1))

# Also check the PERMANENT version of dossiers for first/last mention
perm_dossier_path = Path.home() / "PERMANENT_HYPERDOCS" / "sessions" / "session_513d4807" / "file_dossiers.json"
if perm_dossier_path.exists():
    perm_data = json.load(open(perm_dossier_path))
    for k, v in perm_data.get("dossiers", {}).items():
        if isinstance(v, dict) and v.get("file_name") == TARGET_FILE:
            for idx_key in ("first_mention_index", "last_mention_index"):
                idx_val = v.get(idx_key)
                if idx_val is not None:
                    file_mention_indices.add(idx_val)
            break

print(f"    File mention indices: {sorted(file_mention_indices)}")

# Collect emotional tenor from tagged messages near any mention
nearby_emotions = []
for tm in tagged:
    idx = tm.get("msg_index", -1)
    for mention_idx in file_mention_indices:
        if mention_idx >= 0 and abs(idx - mention_idx) <= 5:
            nearby_emotions.append({
                "msg_index": idx,
                "emotional_tenor": tm.get("emotional_tenor", "unknown"),
                "confidence_signal": tm.get("confidence_signal", "unknown"),
                "action_vector": tm.get("action_vector", "unknown"),
            })
            break

emotional_arc = {
    "session_distribution": distributions.get("emotional_tenor", {}),
    "session_arc": summary_stats.get("session_arc", ""),
    "dominant_emotion": summary_stats.get("dominant_emotion", ""),
    "friction_episodes": summary_stats.get("friction_episodes", 0),
    "file_nearby_emotions": nearby_emotions,
    "data_points": len(nearby_emotions),
}


# ── 2. Geological Character ─────────────────────────────────
# From geological_notes: micro/meso/macro observations mentioning the file
print("  Building geological_character...")

file_micro = []
for obs in geological_notes.get("micro", []):
    text = obs.get("observation", "") if isinstance(obs, dict) else str(obs)
    if mentions_file(text, TARGET_FILE):
        file_micro.append(obs)

file_meso = []
for obs in geological_notes.get("meso", []):
    text = obs.get("observation", "") if isinstance(obs, dict) else str(obs)
    if mentions_file(text, TARGET_FILE):
        file_meso.append(obs)

file_macro = []
for obs in geological_notes.get("macro", []):
    text = obs.get("observation", "") if isinstance(obs, dict) else str(obs)
    if mentions_file(text, TARGET_FILE):
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
# From file_genealogy (per-session) + cross_session_file_index (cross-session)
print("  Building lineage...")

# Per-session genealogy
families = file_genealogy.get("file_families", [])
file_family = None
for fam in families:
    versions = fam.get("versions", fam.get("members", fam.get("files", [])))
    member_names = []
    for v in versions:
        fp = v if isinstance(v, str) else v.get("file", "")
        member_names.append(fp)
    if any(TARGET_FILE in m for m in member_names):
        file_family = {
            "family_name": fam.get("concept", fam.get("name", "unnamed")),
            "members": member_names,
            "source": "session_513d4807",
        }
        break

# Cross-session genealogy
cross_files = cross_session.get("files", {})
cross_genealogy = None
for key, entry in cross_files.items():
    if TARGET_FILE in key.lower() or (isinstance(entry, dict) and
            TARGET_FILE.replace(".py", "") in key.lower()):
        gen = entry.get("genealogy")
        if gen:
            cross_genealogy = gen
        # Also get confidence history
        break

# Also check by bare filename
if not cross_genealogy:
    entry = cross_files.get(TARGET_FILE, {})
    if isinstance(entry, dict):
        cross_genealogy = entry.get("genealogy")

lineage = {
    "session_family": file_family,
    "cross_session_family": cross_genealogy,
    "data_points": (1 if file_family else 0) + (1 if cross_genealogy else 0),
}


# ── 4. Explorer Observations ─────────────────────────────────
# From explorer_notes: observations, verification notes mentioning the file
print("  Building explorer_observations...")

file_explorer_obs = []
for obs in explorer_notes.get("observations", []):
    text = obs if isinstance(obs, str) else obs.get("observation", "") if isinstance(obs, dict) else str(obs)
    if mentions_file(text, TARGET_FILE):
        file_explorer_obs.append(obs)

# Check verification section
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

explorer_summary = explorer_notes.get("explorer_summary", "")

explorer_observations = {
    "observations": file_explorer_obs,
    "verification_issues": file_verification,
    "session_explorer_summary": explorer_summary if mentions_file(explorer_summary, TARGET_FILE) else "",
    "data_points": len(file_explorer_obs) + len(file_verification),
}


# ── 5. Chronological Timeline ────────────────────────────────
# From thread_extractions: all entries mentioning the file, ordered by msg_index
print("  Building chronological_timeline...")

timeline = []
threads_dict = thread_extractions.get("threads", {})
for thread_key, thread_val in threads_dict.items():
    if not isinstance(thread_val, dict):
        continue
    entries = thread_val.get("entries", [])
    for entry in entries:
        content = entry.get("content", "") if isinstance(entry, dict) else ""
        if mentions_file(content, TARGET_FILE):
            timeline.append({
                "msg_index": entry.get("msg_index", -1),
                "thread": thread_key,
                "content": content,
                "significance": entry.get("significance", ""),
            })

timeline.sort(key=lambda x: x.get("msg_index", 0))

chronological_timeline = {
    "events": timeline,
    "data_points": len(timeline),
}


# ── 6. Code Similarity ───────────────────────────────────────
# From cross_session_file_index code_similarity field
print("  Building code_similarity...")

code_sim = []
for key, entry in cross_files.items():
    if TARGET_FILE in key.lower():
        code_sim = entry.get("code_similarity", [])
        break
if not code_sim:
    entry = cross_files.get(TARGET_FILE, {})
    if isinstance(entry, dict):
        code_sim = entry.get("code_similarity", [])

code_similarity = {
    "matches": code_sim,
    "data_points": len(code_sim),
}


# ── Assemble output ──────────────────────────────────────────
output = {
    "file": TARGET_FILE,
    "session": "513d4807",
    "option": "A",
    "approach": "Expand generate_dossiers.py with 5 new data readers inline",
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

print(f"\nOption A output: {OUTPUT_PATH}")
print(f"  Size: {OUTPUT_PATH.stat().st_size:,} bytes")

# Summary
sections = ["emotional_arc", "geological_character", "lineage",
            "explorer_observations", "chronological_timeline", "code_similarity"]
for s in sections:
    dp = output[s].get("data_points", 0)
    print(f"  {s}: {dp} data points")
