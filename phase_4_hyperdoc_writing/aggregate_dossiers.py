#!/usr/bin/env python3
"""
Phase 4a: Cross-Session Dossier Aggregation

Reads all 261 session file_dossiers.json files, normalizes the two
incompatible schemas (dict-keyed vs list-based), and aggregates per-file
across all sessions.

Output: output/cross_session_file_index.json

$0 cost — pure Python, no LLM calls.
"""
import json
import os
from pathlib import Path
from collections import defaultdict
from datetime import datetime

H3 = Path(__file__).resolve().parent.parent
OUTPUT = H3 / "output"
PROJECT_ROOT = H3.parent.parent.parent.parent  # .claude/hooks/hyperdoc/hyperdocs_3 -> project root

COMMON_FIELDS = [
    "claude_behavior", "confidence", "key_decisions",
    "related_files", "story_arc", "total_mentions", "warnings"
]


def normalize_dict_format(dossiers: dict, session_id: str) -> list[dict]:
    """Normalize dict-keyed dossiers {filepath: metadata} into list format."""
    entries = []
    for filepath, meta in dossiers.items():
        if not isinstance(meta, dict):
            continue
        entry = {
            "file": filepath,
            "session_id": session_id,
            "confidence": meta.get("confidence", "unknown"),
            "total_mentions": meta.get("total_mentions", 0),
            "story_arc": meta.get("story_arc", ""),
            "key_decisions": meta.get("key_decisions", []),
            "warnings": meta.get("warnings", []),
            "related_files": meta.get("related_files", []),
            "claude_behavior": meta.get("claude_behavior", {}),
            "significance": meta.get("significance", "unknown"),
            "grounded_markers": meta.get("grounded_markers", []),
            "idea_graph_nodes": meta.get("idea_graph_nodes", []),
            "source_messages": meta.get("source_messages", []),
        }
        entries.append(entry)
    return entries


def normalize_list_format(dossiers: list, session_id: str) -> list[dict]:
    """Normalize list-based dossiers [{file: ..., ...}] into common format."""
    entries = []
    for item in dossiers:
        if not isinstance(item, dict):
            continue
        filepath = item.get("file") or item.get("file_path") or item.get("filename", "")
        if not filepath or filepath == "TRULY_UNKNOWN":
            continue
        entry = {
            "file": filepath,
            "session_id": session_id,
            "confidence": item.get("confidence", "unknown"),
            "total_mentions": item.get("total_mentions", 0),
            "story_arc": item.get("story_arc", ""),
            "key_decisions": item.get("key_decisions", []),
            "warnings": item.get("warnings", []),
            "related_files": item.get("related_files", []),
            "claude_behavior": item.get("claude_behavior", {}),
            "significance": item.get("category", item.get("significance", "unknown")),
            "mentioned_in": item.get("mentioned_in", []),
            "exists": item.get("exists", None),
            "confidence_rationale": item.get("confidence_rationale", ""),
        }
        entries.append(entry)
    return entries


def check_exists_on_disk(filepath: str) -> bool:
    """Check if a file path exists relative to the project root."""
    if not filepath:
        return False
    candidates = [
        PROJECT_ROOT / filepath,
        PROJECT_ROOT / ".claude" / "hooks" / filepath,
        PROJECT_ROOT / ".claude" / "hooks" / "hyperdoc" / filepath,
    ]
    for c in candidates:
        if c.exists():
            return True
    # Try absolute path
    if Path(filepath).is_absolute() and Path(filepath).exists():
        return True
    return False


def merge_warnings(all_warnings: list[list]) -> list[dict]:
    """Merge warnings across sessions, deduplicating by content."""
    seen = set()
    merged = []
    for session_warnings in all_warnings:
        for w in session_warnings:
            if isinstance(w, dict):
                key = w.get("warning", w.get("id", str(w)))
            else:
                key = str(w)
            if key not in seen:
                seen.add(key)
                merged.append(w)
    return merged


def merge_decisions(all_decisions: list[list]) -> list:
    """Merge key decisions across sessions, deduplicating."""
    seen = set()
    merged = []
    for session_decisions in all_decisions:
        for d in session_decisions:
            key = str(d) if not isinstance(d, str) else d
            if key not in seen:
                seen.add(key)
                merged.append(d)
    return merged


def aggregate_file_entries(entries: list[dict]) -> dict:
    """Aggregate multiple session entries for a single file."""
    sessions = sorted(set(e["session_id"] for e in entries))
    total_mentions = sum(e.get("total_mentions", 0) or 0 for e in entries)

    # Confidence history
    confidence_history = []
    for e in entries:
        conf = e.get("confidence", "unknown")
        if conf and conf != "unknown":
            confidence_history.append({
                "session": e["session_id"],
                "confidence": conf,
            })

    # Merge warnings and decisions
    all_warnings = [e.get("warnings", []) for e in entries]
    all_decisions = [e.get("key_decisions", []) for e in entries]
    merged_warnings = merge_warnings(all_warnings)
    merged_decisions = merge_decisions(all_decisions)

    # Story arcs
    story_arcs = []
    for e in entries:
        arc = e.get("story_arc", "")
        if arc:
            story_arcs.append({"session": e["session_id"], "arc": arc})

    # Behavioral patterns
    behaviors = defaultdict(list)
    for e in entries:
        cb = e.get("claude_behavior", {})
        if isinstance(cb, dict):
            for k, v in cb.items():
                if v:
                    behaviors[k].append({"session": e["session_id"], "value": v})

    # Significance scores
    sig_scores = defaultdict(int)
    for e in entries:
        sig = e.get("significance", "unknown")
        if isinstance(sig, str):
            sig_scores[sig] += 1

    # Related files (union)
    all_related = set()
    for e in entries:
        for rf in e.get("related_files", []):
            if isinstance(rf, str):
                all_related.add(rf)

    filepath = entries[0]["file"]

    return {
        "file_path": filepath,
        "session_count": len(sessions),
        "total_mentions": total_mentions,
        "exists_on_disk": check_exists_on_disk(filepath),
        "sessions": sessions,
        "merged_warnings": merged_warnings,
        "merged_decisions": merged_decisions,
        "confidence_history": confidence_history,
        "story_arcs": story_arcs,
        "behavioral_patterns": dict(behaviors),
        "significance_scores": dict(sig_scores),
        "related_files": sorted(all_related),
    }


def main():
    print("=" * 60)
    print("Phase 4a: Cross-Session Dossier Aggregation")
    print("=" * 60)
    print(f"Output dir: {OUTPUT}")
    print(f"Project root: {PROJECT_ROOT}")
    print()

    # Collect all normalized entries
    all_entries = []
    sessions_read = 0
    dict_format = 0
    list_format = 0
    skipped = 0
    unknown_recovered = 0

    for d in sorted(OUTPUT.iterdir()):
        if not d.is_dir() or not d.name.startswith("session_"):
            continue
        dossier_path = d / "file_dossiers.json"
        if not dossier_path.exists():
            skipped += 1
            continue

        session_id = d.name.replace("session_", "")
        try:
            data = json.loads(dossier_path.read_text())
        except (json.JSONDecodeError, UnicodeDecodeError):
            skipped += 1
            continue

        dossiers = data.get("dossiers", {})
        sessions_read += 1

        if isinstance(dossiers, dict):
            entries = normalize_dict_format(dossiers, session_id)
            dict_format += 1
        elif isinstance(dossiers, list):
            entries = normalize_list_format(dossiers, session_id)
            list_format += 1
        else:
            skipped += 1
            continue

        all_entries.extend(entries)

    print(f"Sessions read: {sessions_read}")
    print(f"  Dict format: {dict_format}")
    print(f"  List format: {list_format}")
    print(f"  Skipped: {skipped}")
    print(f"Total dossier entries: {len(all_entries)}")
    print()

    # Group by file path
    by_file = defaultdict(list)
    for entry in all_entries:
        fp = entry["file"]
        by_file[fp].append(entry)

    print(f"Unique file paths: {len(by_file)}")

    # Aggregate
    aggregated = {}
    for filepath, entries in sorted(by_file.items()):
        aggregated[filepath] = aggregate_file_entries(entries)

    # Stats
    single = sum(1 for v in aggregated.values() if v["session_count"] == 1)
    multi_2 = sum(1 for v in aggregated.values() if v["session_count"] == 2)
    multi_3plus = sum(1 for v in aggregated.values() if v["session_count"] >= 3)
    exists_count = sum(1 for v in aggregated.values() if v["exists_on_disk"])

    print(f"  1 session only: {single}")
    print(f"  2 sessions: {multi_2}")
    print(f"  3+ sessions: {multi_3plus}")
    print(f"  Exist on disk: {exists_count}")
    print()

    # Top 20
    top = sorted(aggregated.values(), key=lambda x: x["session_count"], reverse=True)[:20]
    print("Top 20 files by session count:")
    for t in top:
        disk = "DISK" if t["exists_on_disk"] else "    "
        print(f"  {t['session_count']:>3}x [{disk}] {t['file_path']}")
    print()

    # Build output
    output_data = {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "generator": "Phase 4a - Cross-Session Dossier Aggregation",
        "stats": {
            "sessions_read": sessions_read,
            "dict_format": dict_format,
            "list_format": list_format,
            "total_entries": len(all_entries),
            "unique_files": len(aggregated),
            "single_session": single,
            "multi_2_sessions": multi_2,
            "multi_3plus_sessions": multi_3plus,
            "exists_on_disk": exists_count,
        },
        "files": aggregated,
    }

    out_path = OUTPUT / "cross_session_file_index.json"
    with open(out_path, "w") as f:
        json.dump(output_data, f, indent=2, default=str)

    size = out_path.stat().st_size
    print(f"Written: {out_path}")
    print(f"Size: {size:,} bytes")
    print("Done.")


if __name__ == "__main__":
    main()
