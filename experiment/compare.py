#!/usr/bin/env python3
"""
Compare all 3 experiment options side by side.
"""
import json
import os
from pathlib import Path

EXPERIMENT_DIR = Path(__file__).resolve().parent / "output"

options = {}
for label in ["a", "b", "c"]:
    path = EXPERIMENT_DIR / f"option_{label}_geological_reader.json"
    if path.exists():
        options[label.upper()] = json.load(open(path))
    else:
        print(f"WARNING: {path} not found")

sections = ["emotional_arc", "geological_character", "lineage",
            "explorer_observations", "chronological_timeline", "code_similarity"]

print("=" * 80)
print("COMPARISON: Data Flow Completeness Experiment")
print(f"Target file: geological_reader.py")
print("=" * 80)

# ── 1. Data Completeness (6 sections present and non-empty) ──
print("\n1. DATA COMPLETENESS (sections populated / 6)")
for opt_key in ["A", "B", "C"]:
    data = options[opt_key]
    populated = sum(1 for s in sections if data.get(s, {}).get("data_points", 0) > 0)
    print(f"   Option {opt_key}: {populated}/6 sections populated")

# ── 2. Evidence Density (total data points) ──────────────────
print("\n2. EVIDENCE DENSITY (total data points per file)")
for opt_key in ["A", "B", "C"]:
    data = options[opt_key]
    total = sum(data.get(s, {}).get("data_points", 0) for s in sections)
    per_section = {s: data.get(s, {}).get("data_points", 0) for s in sections}
    print(f"   Option {opt_key}: {total} total")
    for s in sections:
        dp = per_section[s]
        bar = "█" * dp + "░" * (15 - min(dp, 15))
        print(f"     {s:30s} {dp:>3d}  {bar}")

# ── 3. Cross-Session Coverage ────────────────────────────────
print("\n3. CROSS-SESSION COVERAGE")
for opt_key in ["A", "B", "C"]:
    data = options[opt_key]
    # Count sessions referenced
    sessions = set()
    if data.get("session"):
        sessions.add(data["session"])
    if data.get("sessions_with_data"):
        sessions.update(range(data["sessions_with_data"]))  # placeholder

    # Check lineage for cross-session data
    lineage = data.get("lineage", {})
    conf_hist = lineage.get("confidence_history", [])
    story_arcs = lineage.get("story_arcs", [])
    cross_sessions = lineage.get("sessions_referenced", [])

    # Check emotional_arc for cross-session data
    emotional = data.get("emotional_arc", {})
    per_session_emotions = emotional.get("per_session_emotions", {})
    sessions_with_emotional = emotional.get("sessions_with_emotional_data", 0)

    if opt_key == "C":
        actual_sessions = data.get("sessions_with_data", 0)
        print(f"   Option {opt_key}: {actual_sessions} sessions (CROSS-SESSION)")
        print(f"     Emotional data from {sessions_with_emotional} sessions")
        print(f"     Geological data from {data.get('geological_character', {}).get('sessions_with_geological_data', 0)} sessions")
        print(f"     Timeline from {data.get('chronological_timeline', {}).get('sessions_with_timeline', 0)} sessions")
        print(f"     Confidence history: {len(conf_hist)} entries across sessions")
        print(f"     Story arcs: {len(story_arcs)} cross-session arcs")
    else:
        print(f"   Option {opt_key}: 1 session (SINGLE-SESSION)")
        print(f"     Confidence history: {len(conf_hist)} (from cross-session index)")
        print(f"     Story arcs: {len(story_arcs)}")

# ── 4. Single-Session Depth ──────────────────────────────────
print("\n4. SINGLE-SESSION DEPTH (how much per-session detail preserved)")
for opt_key in ["A", "B", "C"]:
    data = options[opt_key]
    emotional = data.get("emotional_arc", {})
    nearby = emotional.get("file_nearby_emotions", [])
    trajectory = emotional.get("emotion_trajectory", [])

    geo = data.get("geological_character", {})
    micro = geo.get("micro_observations", [])
    meso = geo.get("meso_observations", [])
    macro = geo.get("macro_observations", [])
    cross_obs = geo.get("cross_session_observations", [])

    if opt_key in ["A", "B"]:
        print(f"   Option {opt_key}:")
        print(f"     Nearby emotions: {len(nearby)} (per-message primitives)")
        if trajectory:
            print(f"     Emotion trajectory: {len(trajectory)} points (time-ordered)")
        print(f"     Geological: micro={len(micro)}, meso={len(meso)}, macro={len(macro)}")
        if opt_key == "B":
            window = data.get("window_size", 0)
            mention_indices = data.get("mention_indices", [])
            print(f"     Time window: ±{window} messages around mentions at {mention_indices}")
    else:
        print(f"   Option {opt_key}:")
        print(f"     Geological observations: {len(cross_obs)} (aggregated across sessions)")
        print(f"     Per-session emotions: {len(emotional.get('per_session_emotions', {}))} sessions")
        print(f"     NOTE: Per-message detail NOT preserved in cross-session aggregation")

# ── 5. Output Size ───────────────────────────────────────────
print("\n5. OUTPUT SIZE")
for opt_key in ["A", "B", "C"]:
    path = EXPERIMENT_DIR / f"option_{opt_key.lower()}_geological_reader.json"
    size = path.stat().st_size
    print(f"   Option {opt_key}: {size:>6,} bytes")

# ── 6. Code Footprint ───────────────────────────────────────
print("\n6. CODE FOOTPRINT")
experiment_dir = Path(__file__).resolve().parent
for opt_key, filename in [("A", "option_a.py"), ("B", "option_b.py"), ("C", "option_c.py")]:
    path = experiment_dir / filename
    if path.exists():
        lines = len(path.read_text().splitlines())
        print(f"   Option {opt_key}: {lines} lines ({filename})")

# ── 7. Integration Cleanliness ───────────────────────────────
print("\n7. INTEGRATION CLEANLINESS")
print("   Option A: Modifies generate_dossiers.py (Phase 3). No new files.")
print("             Requires 5 new JSON reads per session run.")
print("             Changes are localized to the dossier-building loop.")
print("   Option B: Creates NEW collect_file_evidence.py (Phase 3).")
print("             generate_dossiers.py could read evidence packages instead.")
print("             Separates concerns: evidence collection vs dossier building.")
print("   Option C: Modifies aggregate_dossiers.py (Phase 4a). No new files.")
print("             Must scan ALL session directories for each aggregation run.")
print("             Cross-session scan takes O(N) time per file * M sessions.")

# ── 8. Pipeline Runner Impact ────────────────────────────────
print("\n8. PIPELINE RUNNER IMPACT")
print("   Option A: run_pipeline.py --phase 3 still works. New data added to existing output.")
print("   Option B: run_pipeline.py needs new step: --phase 3a (evidence) before --phase 3 (dossiers).")
print("   Option C: run_pipeline.py --phase 4a becomes heavier. Cross-session scan adds ~30s.")

# ── Summary Table ────────────────────────────────────────────
print("\n" + "=" * 80)
print("SUMMARY TABLE")
print("=" * 80)
print(f"{'Metric':<35s} {'Option A':>12s} {'Option B':>12s} {'Option C':>12s}")
print("-" * 80)

for opt_key in ["A", "B", "C"]:
    data = options[opt_key]
    populated = sum(1 for s in sections if data.get(s, {}).get("data_points", 0) > 0)
    options[opt_key]["_populated"] = populated
    options[opt_key]["_total_dp"] = sum(data.get(s, {}).get("data_points", 0) for s in sections)

metrics = [
    ("Sections populated (of 6)", lambda d: f"{d['_populated']}/6"),
    ("Total data points", lambda d: str(d["_total_dp"])),
    ("Output size (bytes)", lambda d: f"{EXPERIMENT_DIR.joinpath('option_' + d['option'].lower() + '_geological_reader.json').stat().st_size:,}"),
    ("Cross-session coverage", lambda d: f"{d.get('sessions_with_data', 1)} sessions"),
    ("Per-message emotion detail", lambda d: "Yes" if d.get("emotional_arc", {}).get("file_nearby_emotions") else "No"),
    ("Time-window correlation", lambda d: "Yes" if d.get("window_size") else "No"),
    ("Geological zoom levels", lambda d: str(len([z for z in ["micro", "meso", "macro"]
        if d.get("geological_character", {}).get(f"{z}_observations", d.get("geological_character", {}).get("by_zoom_level", {}).get(z, []))]))),
    ("Confidence history entries", lambda d: str(len(d.get("lineage", {}).get("confidence_history", [])))),
    ("New files required", lambda d: {"A": "0", "B": "1", "C": "0"}[d["option"]]),
    ("Pipeline phase change", lambda d: {"A": "No", "B": "Yes (new step)", "C": "No"}[d["option"]]),
]

for metric_name, metric_fn in metrics:
    vals = []
    for opt_key in ["A", "B", "C"]:
        try:
            vals.append(metric_fn(options[opt_key]))
        except Exception:
            vals.append("?")
    print(f"{metric_name:<35s} {vals[0]:>12s} {vals[1]:>12s} {vals[2]:>12s}")

print("\n" + "=" * 80)
print("Decision is yours. Which approach do you want to implement fully?")
print("=" * 80)
