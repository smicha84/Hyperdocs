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


def load_code_similarity(output_dir: Path) -> dict:
    """Load code similarity index and build per-file lookup.
    Returns {filepath: [{similar_to, score, pattern_type}, ...]}"""
    sim_path = output_dir / "code_similarity_index.json"
    # Also check PERMANENT_HYPERDOCS/indexes/
    if not sim_path.exists():
        alt = Path.home() / "PERMANENT_HYPERDOCS" / "indexes" / "code_similarity_index.json"
        if alt.exists():
            sim_path = alt
    if not sim_path.exists():
        return {}

    try:
        data = json.loads(sim_path.read_text())
    except (json.JSONDecodeError, UnicodeDecodeError):
        return {}

    matches = data.get("matches", data.get("pairs", []))
    by_file = defaultdict(list)
    for m in matches:
        if isinstance(m, dict):
            f1 = m.get("file_a", m.get("file1", ""))
            f2 = m.get("file_b", m.get("file2", ""))
            signals = m.get("signals", {})
            # Score from signals (text_similarity or func_overlap) or top-level
            score = m.get("score", signals.get("text_similarity", signals.get("func_overlap", 0)))
            ptype = m.get("pattern_type", m.get("type", "unknown"))
            if f1 and f2 and score > 0.3:
                by_file[f1].append({"similar_to": f2, "score": round(score, 3), "pattern": ptype})
                by_file[f2].append({"similar_to": f1, "score": round(score, 3), "pattern": ptype})

    # Sort by score descending, keep top 5 per file
    for fp in by_file:
        by_file[fp] = sorted(by_file[fp], key=lambda x: -x["score"])[:5]

    return dict(by_file)


def load_genealogy_families(output_dir: Path) -> dict:
    """Load per-session genealogy data and build per-file lookup.
    Returns {filepath: {family_name, family_members, role}}
    Searches both output_dir/session_* and output_dir/sessions/session_*."""
    by_file = {}

    # Find session directories — could be at output_dir/session_* or output_dir/sessions/session_*
    search_dirs = [output_dir]
    sessions_subdir = output_dir / "sessions"
    if sessions_subdir.exists():
        search_dirs.append(sessions_subdir)

    for search_dir in search_dirs:
        for d in sorted(search_dir.iterdir()):
            if not d.is_dir() or not d.name.startswith("session_"):
                continue
            gen_path = d / "file_genealogy.json"
            if not gen_path.exists():
                continue
            try:
                data = json.loads(gen_path.read_text())
            except (json.JSONDecodeError, UnicodeDecodeError):
                continue

            families = data.get("file_families", data.get("families", data.get("genealogy_families", [])))
            for fam in families:
                name = fam.get("concept", fam.get("name", fam.get("family_name", "unnamed")))
                versions = fam.get("versions", fam.get("members", fam.get("files", [])))
                member_files = []
                for v in versions:
                    fp = v if isinstance(v, str) else v.get("file", "")
                    if fp:
                        member_files.append(fp)
                for fp in member_files:
                    if fp not in by_file:
                        by_file[fp] = {
                            "family_name": name,
                            "family_members": member_files,
                            "session_source": d.name.replace("session_", ""),
                        }

    return by_file


def build_frustration_file_map(output_dir: Path) -> dict:
    """Join frustration peaks with file mentions to build per-file frustration associations.
    Returns {filepath: [{session, message_index, caps_ratio, profanity}, ...]}
    Searches both output_dir/session_* and output_dir/sessions/session_*."""
    by_file = defaultdict(list)

    search_dirs = [output_dir]
    sessions_subdir = output_dir / "sessions"
    if sessions_subdir.exists():
        search_dirs.append(sessions_subdir)

    for search_dir in search_dirs:
        for d in sorted(search_dir.iterdir()):
            if not d.is_dir() or not d.name.startswith("session_"):
                continue
            summary_path = d / "session_summary.json"
            enriched_path = d / "enriched_session.json"
            if not summary_path.exists():
                continue

            session_id = d.name.replace("session_", "")
            try:
                summary = json.loads(summary_path.read_text())
            except (json.JSONDecodeError, UnicodeDecodeError):
                continue

            stats = summary.get("session_stats", summary)
            peaks = stats.get("frustration_peaks", [])
            if not peaks:
                continue

            # Get file mentions per message from enriched session
            msg_files = {}
            if enriched_path.exists():
                try:
                    enriched = json.loads(enriched_path.read_text())
                    for msg in enriched.get("messages", []):
                        idx = msg.get("index", -1)
                        # File mentions live in metadata.files, metadata.files_edit, etc.
                        meta = msg.get("metadata", {})
                        files = meta.get("files", [])
                        files += meta.get("files_create", [])
                        files += meta.get("files_edit", [])
                        # Also check top-level for alternative schemas
                        files += msg.get("files_mentioned", [])
                        if files:
                            msg_files[idx] = list(set(files))
                except (json.JSONDecodeError, UnicodeDecodeError):
                    pass

            # For each frustration peak, find files mentioned in nearby messages (within 5 msg window)
            for peak in peaks:
                peak_idx = peak.get("index", -1)
                if peak_idx < 0:
                    continue

                # Look at messages within ±5 of the frustration peak
                associated_files = set()
                for offset in range(-5, 6):
                    check_idx = peak_idx + offset
                    if check_idx in msg_files:
                        associated_files.update(msg_files[check_idx])

                for fp in associated_files:
                    by_file[fp].append({
                        "session": session_id,
                        "message_index": peak_idx,
                        "caps_ratio": peak.get("caps_ratio", 0),
                        "profanity": peak.get("profanity", False),
                    })

    return dict(by_file)


def main():
    print("=" * 60)
    print("Phase 4a: Cross-Session Dossier Aggregation (v2 — with genealogy, similarity, frustration)")
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

    # ── Enrich with cross-session signals ─────────────────────────────
    print("Loading cross-session enrichment data...")

    # Also check PERMANENT_HYPERDOCS for session data
    PERM_SESSIONS = Path.home() / "PERMANENT_HYPERDOCS" / "sessions"

    # Code similarity
    sim_data = load_code_similarity(OUTPUT)
    if not sim_data:
        sim_data = load_code_similarity(Path.home() / "PERMANENT_HYPERDOCS" / "indexes")
    sim_hits = 0
    for fp, entry in aggregated.items():
        basename = Path(fp).name
        matches = sim_data.get(fp, sim_data.get(basename, []))
        if matches:
            entry["code_similarity"] = matches
            sim_hits += 1
        else:
            entry["code_similarity"] = []
    print(f"  Code similarity: {sim_hits} files have matches (from {len(sim_data)} indexed)")

    # Genealogy families — check both output/ and PERMANENT_HYPERDOCS/
    gen_data = load_genealogy_families(OUTPUT)
    if not gen_data and PERM_SESSIONS.exists():
        gen_data = load_genealogy_families(PERM_SESSIONS.parent)
    if not gen_data:
        gen_data = load_genealogy_families(Path.home() / "PERMANENT_HYPERDOCS")
    gen_hits = 0
    for fp, entry in aggregated.items():
        basename = Path(fp).name
        family = gen_data.get(fp, gen_data.get(basename, None))
        if family:
            entry["genealogy"] = family
            gen_hits += 1
        else:
            entry["genealogy"] = None
    print(f"  Genealogy: {gen_hits} files in families (from {len(gen_data)} mapped)")

    # Frustration-file associations — check both output/ and PERMANENT_HYPERDOCS/
    frust_data = build_frustration_file_map(OUTPUT)
    if not frust_data and PERM_SESSIONS.exists():
        frust_data = build_frustration_file_map(Path.home() / "PERMANENT_HYPERDOCS")
    frust_hits = 0
    for fp, entry in aggregated.items():
        basename = Path(fp).name
        associations = frust_data.get(fp, frust_data.get(basename, []))
        if associations:
            entry["frustration_associations"] = associations
            frust_hits += 1
        else:
            entry["frustration_associations"] = []
    print(f"  Frustration attribution: {frust_hits} files associated with frustration peaks")
    print()

    # Top 20
    top = sorted(aggregated.values(), key=lambda x: x["session_count"], reverse=True)[:20]
    print("Top 20 files by session count:")
    for t in top:
        disk = "DISK" if t["exists_on_disk"] else "    "
        sim = f" sim:{len(t.get('code_similarity', []))}" if t.get('code_similarity') else ""
        gen = " GEN" if t.get('genealogy') else ""
        frust = f" frust:{len(t.get('frustration_associations', []))}" if t.get('frustration_associations') else ""
        print(f"  {t['session_count']:>3}x [{disk}]{gen}{sim}{frust} {t['file_path']}")
    print()

    # Build output
    output_data = {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "generator": "Phase 4a - Cross-Session Dossier Aggregation v2 (with genealogy, similarity, frustration)",
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
