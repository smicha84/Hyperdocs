#!/usr/bin/env python3
"""
Extract all visualization data from the Hyperdocs pipeline output.
Produces dashboard_data.json with rich data for the interactive dashboard.
"""
import json
import re
from pathlib import Path
from collections import Counter, defaultdict
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from tools.log_config import get_logger

logger = get_logger("tools.extract_dashboard_data")

BASE = Path(__file__).parent
HYPERDOCS = BASE / "hyperdocs"
SESSIONS = BASE
INDEX_FILE = BASE / "cross_session_file_index.json"


def count_pattern(text, patterns):
    """Count occurrences of patterns in text (case-insensitive)."""
    total = 0
    lower = text.lower()
    for p in patterns:
        total += lower.count(p.lower())
    return total


def extract_file_data():
    """Extract rich metadata from all 456 hyperdoc JSONs."""
    files = []
    for f in sorted(HYPERDOCS.glob("*_hyperdoc.json")):
        try:
            data = json.loads(f.read_text())
        except (json.JSONDecodeError, OSError):
            continue

        fp = data.get("file_path", "")
        header = data.get("header", "")
        footer = data.get("footer", "")
        anns = data.get("inline_annotations", [])
        sc = data.get("session_count", 0)

        # Parse structured data from header
        frictions = len(re.findall(r'(?:F\d+|Friction|friction\b)', header))
        decisions = len(re.findall(r'(?:D\d+|Decision|chose\s)', header, re.I))
        warnings_count = len(re.findall(r'(?:\[W|Warning|warning\b|W\d+)', header))
        failed = len(re.findall(r'(?:Failed|ABANDONED|PIVOTED|CONSTRAINED)', header, re.I))

        # Extract confidence/state
        state_match = re.search(r'@ctx:state[:\s]+(\w+)', header)
        conf_match = re.search(r'@ctx:confidence[:\s]+(\w+)', header)
        emotion_match = re.search(r'@ctx:emotion[:\s]+(\w+)', header)

        state = state_match.group(1) if state_match else "unknown"
        confidence = conf_match.group(1) if conf_match else "unknown"
        emotion = emotion_match.group(1) if emotion_match else "unknown"

        # Check for key patterns
        is_dead_code = "dead code" in header.lower() or "orphan" in header.lower() or "zero import" in header.lower()
        is_missing = "not exist" in header.lower() or "does not exist on disk" in header.lower()
        has_key_mismatch = "key mismatch" in header.lower() or "context key" in header.lower()
        has_truncation = "truncat" in header.lower()

        # Extract annotation targets
        ann_targets = [a.get("target", "") for a in anns if a.get("target")]

        # Size metrics
        total_size = len(json.dumps(data))
        header_lines = header.count("\n")
        footer_lines = footer.count("\n")

        # Extract recommendations count
        recs = len(re.findall(r'R\d+\b', header))

        # Extract credibility if present
        cred_match = re.search(r'credibility[_\s]*score[:\s]*(\d+\.?\d*)/(\d+)', footer, re.I)
        credibility = None
        if cred_match:
            credibility = {"verified": int(float(cred_match.group(1))),
                          "total": int(float(cred_match.group(2)))}

        files.append({
            "path": fp,
            "name": Path(fp).name,
            "ext": Path(fp).suffix,
            "sessions": sc,
            "size_kb": round(total_size / 1024, 1),
            "header_chars": len(header),
            "footer_chars": len(footer),
            "annotations": len(anns),
            "ann_targets": ann_targets,
            "frictions": frictions,
            "decisions": decisions,
            "warnings": warnings_count,
            "failed_approaches": failed,
            "recommendations": recs,
            "state": state,
            "confidence": confidence,
            "emotion": emotion,
            "is_dead_code": is_dead_code,
            "is_missing": is_missing,
            "has_key_mismatch": has_key_mismatch,
            "has_truncation": has_truncation,
            "credibility": credibility,
        })

    return files


def extract_session_data():
    """Extract per-session completeness and metadata."""
    sessions = []
    for sd in sorted(SESSIONS.iterdir()):
        if not sd.is_dir() or not sd.name.startswith("session_"):
            continue

        sid = sd.name.replace("session_", "")

        # Check which phase outputs exist
        phase_files = {
            "enriched_session": (sd / "enriched_session.json").exists(),
            "session_metadata": (sd / "session_metadata.json").exists(),
            "thread_extractions": (sd / "thread_extractions.json").exists(),
            "geological_notes": (sd / "geological_notes.json").exists(),
            "semantic_primitives": (sd / "semantic_primitives.json").exists(),
            "explorer_notes": (sd / "explorer_notes.json").exists(),
            "idea_graph": (sd / "idea_graph.json").exists(),
            "synthesis": (sd / "synthesis.json").exists(),
            "grounded_markers": (sd / "grounded_markers.json").exists(),
            "file_dossiers": (sd / "file_dossiers.json").exists(),
            "claude_md_analysis": (sd / "claude_md_analysis.json").exists(),
        }

        # Get message count
        msg_count = 0
        frustration_peaks = 0
        summary_path = sd / "session_metadata.json"
        if summary_path.exists():
            try:
                s = json.loads(summary_path.read_text())
                stats = s.get("session_stats", s) if isinstance(s, dict) else {}
                if isinstance(stats, dict):
                    msg_count = stats.get("total_messages", 0)
                    fp = stats.get("frustration_peaks", [])
                    frustration_peaks = len(fp) if isinstance(fp, list) else 0
            except (json.JSONDecodeError, KeyError, TypeError, OSError):
                pass

        p0 = 1 if phase_files["enriched_session"] else 0
        p1 = sum(1 for k in ["thread_extractions", "geological_notes", "semantic_primitives", "explorer_notes"] if phase_files[k])
        p2 = sum(1 for k in ["idea_graph", "synthesis", "grounded_markers"] if phase_files[k])
        p3 = sum(1 for k in ["file_dossiers", "claude_md_analysis"] if phase_files[k])

        sessions.append({
            "id": sid[:8],
            "messages": msg_count,
            "frustration_peaks": frustration_peaks,
            "p0": p0, "p1": p1, "p2": p2, "p3": p3,
            "complete": p0 == 1 and p1 >= 3 and p2 >= 2 and p3 >= 1,
        })

    return sessions


def extract_idea_graphs():
    """Extract the richest idea graphs for visualization."""
    graphs = []
    for sd in sorted(SESSIONS.iterdir()):
        if not sd.is_dir() or not sd.name.startswith("session_"):
            continue

        ig_path = sd / "idea_graph.json"
        if not ig_path.exists():
            continue

        try:
            data = json.loads(ig_path.read_text())
            nodes = data.get("nodes", [])
            edges = data.get("edges", [])
            if len(nodes) >= 5:
                graphs.append({
                    "session": sd.name.replace("session_", "")[:8],
                    "node_count": len(nodes),
                    "edge_count": len(edges),
                    "nodes": [{
                        "id": n.get("id", n.get("node_id", "")),
                        "name": n.get("name", n.get("label", n.get("idea", "")))[:60],
                        "confidence": n.get("confidence", "unknown"),
                        "emotion": n.get("emotional_context", n.get("emotion", ""))[:40],
                    } for n in nodes[:50]],
                    "edges": [{
                        "source": e.get("source", e.get("from", "")),
                        "target": e.get("target", e.get("to", "")),
                        "type": e.get("transition_type", e.get("type", e.get("relationship", "related"))),
                    } for e in edges[:80]],
                })
        except (json.JSONDecodeError, KeyError, TypeError, OSError):
            pass

    # Sort by node count, take top 20
    graphs.sort(key=lambda x: -x["node_count"])
    return graphs[:20]


def compute_aggregates(files, sessions):
    """Compute dashboard-level aggregates."""
    # File type distribution
    ext_counts = Counter(f["ext"] for f in files)

    # State distribution
    state_counts = Counter(f["state"] for f in files)

    # Dead code / missing / key mismatch counts
    issue_counts = {
        "dead_code": sum(1 for f in files if f["is_dead_code"]),
        "missing_from_disk": sum(1 for f in files if f["is_missing"]),
        "key_mismatch": sum(1 for f in files if f["has_key_mismatch"]),
        "truncation_violations": sum(1 for f in files if f["has_truncation"]),
    }

    # Session size distribution
    size_dist = {"tiny_0_50": 0, "small_51_200": 0, "medium_201_1000": 0,
                 "large_1001_5000": 0, "mega_5000_plus": 0}
    for s in sessions:
        m = s["messages"]
        if m <= 50: size_dist["tiny_0_50"] += 1
        elif m <= 200: size_dist["small_51_200"] += 1
        elif m <= 1000: size_dist["medium_201_1000"] += 1
        elif m <= 5000: size_dist["large_1001_5000"] += 1
        else: size_dist["mega_5000_plus"] += 1

    # Hyperdoc size distribution
    hd_dist = {"under_10": 0, "10_20": 0, "20_30": 0, "30_40": 0, "40_50": 0, "over_50": 0}
    for f in files:
        kb = f["size_kb"]
        if kb < 10: hd_dist["under_10"] += 1
        elif kb < 20: hd_dist["10_20"] += 1
        elif kb < 30: hd_dist["20_30"] += 1
        elif kb < 40: hd_dist["30_40"] += 1
        elif kb < 50: hd_dist["40_50"] += 1
        else: hd_dist["over_50"] += 1

    # Top files by various metrics
    top_sessions = sorted(files, key=lambda x: -x["sessions"])[:20]
    top_frictions = sorted(files, key=lambda x: -x["frictions"])[:20]
    top_annotations = sorted(files, key=lambda x: -x["annotations"])[:20]
    top_size = sorted(files, key=lambda x: -x["size_kb"])[:20]

    # Phase completion rates
    total_s = len(sessions)
    phase_rates = {
        "p0": sum(1 for s in sessions if s["p0"] > 0) / max(total_s, 1) * 100,
        "p1": sum(1 for s in sessions if s["p1"] >= 3) / max(total_s, 1) * 100,
        "p2": sum(1 for s in sessions if s["p2"] >= 2) / max(total_s, 1) * 100,
        "p3": sum(1 for s in sessions if s["p3"] >= 1) / max(total_s, 1) * 100,
    }

    # Credibility scores
    cred_files = [f for f in files if f["credibility"]]
    avg_cred = 0
    if cred_files:
        scores = [f["credibility"]["verified"] / max(f["credibility"]["total"], 1)
                  for f in cred_files]
        avg_cred = round(sum(scores) / len(scores) * 100, 1)

    return {
        "total_files": len(files),
        "total_sessions": len(sessions),
        "total_messages": sum(s["messages"] for s in sessions),
        "total_annotations": sum(f["annotations"] for f in files),
        "total_frictions": sum(f["frictions"] for f in files),
        "total_decisions": sum(f["decisions"] for f in files),
        "total_warnings": sum(f["warnings"] for f in files),
        "total_failed": sum(f["failed_approaches"] for f in files),
        "total_size_mb": round(sum(f["size_kb"] for f in files) / 1024, 1),
        "enhanced_files": len(list((BASE / "enhanced_files").glob("*.py"))) if (BASE / "enhanced_files").exists() else 0,
        "lines_added": 180820,
        "ext_counts": dict(ext_counts.most_common()),
        "state_counts": dict(state_counts.most_common()),
        "issue_counts": issue_counts,
        "size_dist": size_dist,
        "hd_dist": hd_dist,
        "phase_rates": phase_rates,
        "avg_credibility": avg_cred,
        "top_by_sessions": [{"name": f["name"], "sessions": f["sessions"]} for f in top_sessions],
        "top_by_frictions": [{"name": f["name"], "frictions": f["frictions"]} for f in top_frictions],
        "top_by_annotations": [{"name": f["name"], "annotations": f["annotations"]} for f in top_annotations],
        "top_by_size": [{"name": f["name"], "size_kb": f["size_kb"]} for f in top_size],
    }


def main():
    logger.info("Extracting visualization data...")

    logger.info("  Reading 456 hyperdoc JSONs...")
    files = extract_file_data()
    logger.info(f"  → {len(files)} files extracted")

    logger.info("  Reading session directories...")
    sessions = extract_session_data()
    logger.info(f"  → {len(sessions)} sessions extracted")

    logger.info("  Extracting idea graphs...")
    idea_graphs = extract_idea_graphs()
    logger.info(f"  → {len(idea_graphs)} rich graphs extracted")

    logger.info("  Computing aggregates...")
    aggregates = compute_aggregates(files, sessions)

    dashboard_data = {
        "generated_at": "2026-02-08",
        "files": files,
        "sessions": sessions,
        "idea_graphs": idea_graphs,
        "aggregates": aggregates,
    }

    out_path = BASE / "dashboard_data.json"
    out_path.write_text(json.dumps(dashboard_data))
    logger.info(f"\n  Written: {out_path}")
    logger.info(f"  Size: {out_path.stat().st_size // 1024} KB")
    logger.info(f"  Files: {len(files)}")
    logger.info(f"  Sessions: {len(sessions)}")
    logger.info(f"  Idea graphs: {len(idea_graphs)}")


if __name__ == "__main__":
    main()
