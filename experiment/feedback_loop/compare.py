#!/usr/bin/env python3
"""
Compare all 3 feedback loop experiment versions side by side.

Metrics:
  1. Output size — bytes per file brief (context window cost)
  2. Data density — distinct data points per file
  3. Cross-session coverage — how many prior sessions are represented
  4. Evidence block count — rendered temporal evidence blocks per file
  5. Warning accumulation — merged warnings surfaced from prior sessions
  6. Genealogy depth — family members and predecessor confidence
  7. Confidence history length — trend data points available
  8. Information uniqueness — data in Version C not in A or B

Usage:
    python3 experiment/feedback_loop/compare.py
"""
import json
from pathlib import Path

EXPERIMENT_DIR = Path(__file__).resolve().parent / "output"

TARGET_FILES = ["p01_plan_enforcer.py", "CLAUDE.md", "llm_client.py"]


def load_version(label):
    """Load a version's output file."""
    path = EXPERIMENT_DIR / f"version_{label.lower()}_briefs.json"
    if path.exists():
        return json.load(open(path))
    print(f"WARNING: {path} not found")
    return None


def brief_size_bytes(brief):
    """Approximate size of a brief in bytes."""
    return len(json.dumps(brief, default=str).encode("utf-8"))


def count_data_points(brief, version):
    """Count distinct data points in a brief."""
    dp = 0
    dp += len(brief.get("confidence_history", []))
    dp += len(brief.get("merged_warnings", []))
    dp += len(brief.get("code_similarity_top3", []))
    dp += 1 if brief.get("genealogy_family") else 0
    dp += len(brief.get("evidence_blocks", []))

    if version in ("B", "C"):
        dp += len(brief.get("emotional_trend", []))
        dp += len(brief.get("decision_trajectory", []))

    if version == "C":
        cs = brief.get("cross_session_data_points", {})
        dp += sum(cs.values())

    return dp


def count_sessions_represented(brief, version):
    """Count how many distinct sessions are represented in the brief."""
    sessions = set()

    for ch in brief.get("confidence_history", []):
        s = ch.get("session", "")
        if s:
            sessions.add(s)

    for eb in brief.get("evidence_blocks", []):
        if isinstance(eb, dict):
            s = eb.get("session", "")
            if s:
                sessions.add(s)
        elif isinstance(eb, str):
            # Parse session from directive string like "... [session:0012ebed]"
            if "[session:" in eb:
                sid = eb.split("[session:")[1].split("]")[0]
                if sid:
                    sessions.add(sid)

    if version in ("B", "C"):
        for et in brief.get("emotional_trend", []):
            s = et.get("session", "")
            if s:
                sessions.add(s)

    if version == "C":
        emo_arc = brief.get("cross_session_emotional_arc", {})
        sessions.update(emo_arc.get("per_session_emotions", {}).keys())

        for obs in brief.get("cross_session_geological", []):
            if isinstance(obs, dict):
                s = obs.get("session", "")
                if s:
                    sessions.add(s)

        for event in brief.get("cross_session_timeline", []):
            if isinstance(event, dict):
                s = event.get("session", "")
                if s:
                    sessions.add(s)

        gc = brief.get("cross_session_graph_context", {})
        sessions.update(gc.get("per_session", {}).keys())

        synth = brief.get("cross_session_synthesis", {})
        sessions.update(synth.get("per_session", {}).keys())

        sessions.update(brief.get("cross_session_geological_metaphors", {}).keys())

        cmd = brief.get("cross_session_claude_md", {})
        sessions.update(cmd.get("per_session", {}).keys())

    return len(sessions)


def genealogy_depth(brief):
    """Count genealogy family members."""
    family = brief.get("genealogy_family")
    if not family:
        return 0
    return family.get("version_count", len(family.get("members", [])))


def evidence_rendered_chars(brief):
    """Total characters in rendered evidence blocks."""
    total = 0
    for eb in brief.get("evidence_blocks", []):
        rendered = eb.get("rendered", eb) if isinstance(eb, dict) else str(eb)
        if isinstance(rendered, str):
            total += len(rendered)
    return total


def count_c_unique_data(brief_c, brief_b):
    """Count data points in Version C that are NOT present in Version B."""
    c_unique = 0

    # Cross-session data types (8 types exclusive to C)
    cs = brief_c.get("cross_session_data_points", {})
    c_unique += sum(cs.values())

    # sessions_with_data field
    c_unique += brief_c.get("sessions_with_data", 0)

    return c_unique


def main():
    versions = {}
    for label in ["a", "b", "c"]:
        data = load_version(label)
        if data:
            versions[label.upper()] = data

    if len(versions) < 3:
        print("ERROR: Need all 3 version outputs to compare")
        return

    print("=" * 90)
    print("COMPARISON: Cross-Session Feedback Loop Experiment")
    print(f"Target files: {', '.join(TARGET_FILES)}")
    print("=" * 90)

    # ── 1. Output Size ──────────────────────────────────────
    print("\n1. OUTPUT SIZE (bytes per file brief)")
    for target in TARGET_FILES:
        print(f"\n   {target}:")
        for ver in ["A", "B", "C"]:
            brief = versions[ver]["briefs"].get(target, {})
            size = brief_size_bytes(brief)
            bar = "\u2588" * min(size // 1000, 40)
            print(f"     Version {ver}: {size:>7,} bytes  {bar}")

    print(f"\n   TOTAL file sizes:")
    for ver in ["A", "B", "C"]:
        path = EXPERIMENT_DIR / f"version_{ver.lower()}_briefs.json"
        total_size = path.stat().st_size if path.exists() else 0
        print(f"     Version {ver}: {total_size:>7,} bytes")

    # ── 2. Data Density ─────────────────────────────────────
    print("\n2. DATA DENSITY (distinct data points per file)")
    for target in TARGET_FILES:
        print(f"\n   {target}:")
        for ver in ["A", "B", "C"]:
            brief = versions[ver]["briefs"].get(target, {})
            dp = count_data_points(brief, ver)
            bar = "\u2588" * min(dp, 50)
            print(f"     Version {ver}: {dp:>4} points  {bar}")

    # ── 3. Cross-Session Coverage ───────────────────────────
    print("\n3. CROSS-SESSION COVERAGE (distinct sessions represented)")
    for target in TARGET_FILES:
        print(f"\n   {target}:")
        for ver in ["A", "B", "C"]:
            brief = versions[ver]["briefs"].get(target, {})
            sess = count_sessions_represented(brief, ver)
            total_sess = brief.get("session_count", 0)
            bar = "\u2588" * min(sess, 30)
            print(f"     Version {ver}: {sess:>3} sessions (of {total_sess} total)  {bar}")

    # ── 4. Evidence Block Count + Size ──────────────────────
    print("\n4. EVIDENCE BLOCKS (count and total rendered chars)")
    for target in TARGET_FILES:
        print(f"\n   {target}:")
        for ver in ["A", "B", "C"]:
            brief = versions[ver]["briefs"].get(target, {})
            blocks = brief.get("evidence_blocks", [])
            count = len(blocks)
            chars = evidence_rendered_chars(brief)
            if ver == "A":
                print(f"     Version {ver}: {count} directives (unresolved strings)")
            else:
                print(f"     Version {ver}: {count} rendered blocks, {chars:,} total chars")

    # ── 5. Warning Accumulation ─────────────────────────────
    print("\n5. WARNING ACCUMULATION (merged warnings from prior sessions)")
    for target in TARGET_FILES:
        print(f"\n   {target}:")
        for ver in ["A", "B", "C"]:
            brief = versions[ver]["briefs"].get(target, {})
            warnings = brief.get("merged_warnings", [])
            print(f"     Version {ver}: {len(warnings)} warnings")

    # ── 6. Genealogy Depth ──────────────────────────────────
    print("\n6. GENEALOGY DEPTH (family members)")
    for target in TARGET_FILES:
        print(f"\n   {target}:")
        for ver in ["A", "B", "C"]:
            brief = versions[ver]["briefs"].get(target, {})
            depth = genealogy_depth(brief)
            family = brief.get("genealogy_family")
            name = family["concept"] if family else "none"
            print(f"     Version {ver}: {depth} members ({name})")

    # ── 7. Confidence History Length ─────────────────────────
    print("\n7. CONFIDENCE HISTORY LENGTH (trend data points)")
    for target in TARGET_FILES:
        print(f"\n   {target}:")
        for ver in ["A", "B", "C"]:
            brief = versions[ver]["briefs"].get(target, {})
            hist = brief.get("confidence_history", [])
            values = [h.get("confidence", "?") for h in hist]
            arrow = " \u2192 "
            trail = arrow.join(values[:6])
            suffix = "..." if len(values) > 6 else ""
            print(f"     Version {ver}: {len(hist)} entries: {trail}{suffix}")

    # ── 8. Information Uniqueness (C vs B) ──────────────────
    print("\n8. INFORMATION UNIQUENESS (data in C not in A or B)")
    for target in TARGET_FILES:
        brief_b = versions["B"]["briefs"].get(target, {})
        brief_c = versions["C"]["briefs"].get(target, {})
        c_unique = count_c_unique_data(brief_c, brief_b)

        print(f"\n   {target}:")
        print(f"     Version C unique data points: {c_unique}")
        if c_unique > 0:
            cs = brief_c.get("cross_session_data_points", {})
            for k, v in cs.items():
                if v > 0:
                    print(f"       {k}: {v}")

        # Size overhead for the unique data
        size_b = brief_size_bytes(brief_b)
        size_c = brief_size_bytes(brief_c)
        overhead = size_c - size_b
        print(f"     Size overhead: {overhead:,} bytes ({overhead * 100 // max(size_b, 1)}% more than B)")

    # ── Summary Table ───────────────────────────────────────
    print("\n" + "=" * 90)
    print("SUMMARY TABLE (averaged across all target files)")
    print("=" * 90)
    print(f"{'Metric':<40s} {'Version A':>14s} {'Version B':>14s} {'Version C':>14s}")
    print("-" * 90)

    # Compute averages
    for metric_name, metric_fn in [
        ("Avg brief size (bytes)", lambda ver, t: brief_size_bytes(versions[ver]["briefs"].get(t, {}))),
        ("Avg data points", lambda ver, t: count_data_points(versions[ver]["briefs"].get(t, {}), ver)),
        ("Avg sessions represented", lambda ver, t: count_sessions_represented(versions[ver]["briefs"].get(t, {}), ver)),
        ("Avg evidence blocks", lambda ver, t: len(versions[ver]["briefs"].get(t, {}).get("evidence_blocks", []))),
        ("Avg rendered evidence chars", lambda ver, t: evidence_rendered_chars(versions[ver]["briefs"].get(t, {}))),
        ("Avg warnings", lambda ver, t: len(versions[ver]["briefs"].get(t, {}).get("merged_warnings", []))),
        ("Avg genealogy depth", lambda ver, t: genealogy_depth(versions[ver]["briefs"].get(t, {}))),
        ("Avg confidence history", lambda ver, t: len(versions[ver]["briefs"].get(t, {}).get("confidence_history", []))),
    ]:
        vals = []
        for ver in ["A", "B", "C"]:
            avg = sum(metric_fn(ver, t) for t in TARGET_FILES) / len(TARGET_FILES)
            vals.append(avg)
        print(f"{metric_name:<40s} {vals[0]:>14,.1f} {vals[1]:>14,.1f} {vals[2]:>14,.1f}")

    # Unique to C
    c_unique_total = sum(
        count_c_unique_data(
            versions["C"]["briefs"].get(t, {}),
            versions["B"]["briefs"].get(t, {})
        )
        for t in TARGET_FILES
    )
    print(f"{'Total C-unique data points':<40s} {'n/a':>14s} {'n/a':>14s} {c_unique_total:>14d}")

    # Density ratio (data points per KB)
    print()
    print("DENSITY RATIO (data points per KB):")
    for ver in ["A", "B", "C"]:
        total_dp = sum(count_data_points(versions[ver]["briefs"].get(t, {}), ver) for t in TARGET_FILES)
        total_kb = sum(brief_size_bytes(versions[ver]["briefs"].get(t, {})) for t in TARGET_FILES) / 1024
        ratio = total_dp / max(total_kb, 0.001)
        print(f"  Version {ver}: {ratio:.2f} data points/KB ({total_dp} points / {total_kb:.1f} KB)")

    print("\n" + "=" * 90)
    print("Decision is yours. Which version gives the best density-to-size ratio?")
    print("=" * 90)


if __name__ == "__main__":
    main()
