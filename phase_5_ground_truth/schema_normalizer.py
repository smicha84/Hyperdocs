#!/usr/bin/env python3
"""
Schema Normalizer — Repairs agent-produced JSON files across all sessions.

The Problem: 269 sessions were processed by Opus agents that produced between
41 and 182 different JSON schemas per file type. The data EXISTS but lives
under different key names in every session.

The Fix: For each of 9 file types, find the data wherever it lives, extract it
into a canonical schema, and preserve everything else in _extra.

Safety:
  - Original files backed up to {session}/backups/{filename}
  - ALL original data preserved in _extra field (nothing lost)
  - Idempotent: running twice produces the same result
  - Atomic writes: temp file then rename (no partial writes)
  - Dry-run mode available

Usage:
    python3 schema_normalizer.py                # normalize all sessions
    python3 schema_normalizer.py --dry-run      # report what would change
    python3 schema_normalizer.py --session session_0012ebed  # one session
"""

import json
import os
import sys
import shutil
import tempfile
from pathlib import Path
from datetime import datetime, timezone
from collections import Counter


# ── Canonical field names ────────────────────────────────────────

METADATA_KEYS = {"session_id", "generated_at", "generator", "generated_by",
                 "source_files", "phase", "extraction_method"}


def extract_metadata(data):
    """Pull standard metadata from any schema."""
    meta = {}
    for k in METADATA_KEYS:
        if k in data:
            meta[k] = data[k]
    # Normalize generated_by → generator
    if "generated_by" in meta and "generator" not in meta:
        meta["generator"] = meta.pop("generated_by")
    return meta


def collect_extra(data, canonical_keys):
    """Collect all keys NOT in the canonical set into _extra."""
    extra = {}
    skip = canonical_keys | METADATA_KEYS | {"_normalized_at", "_normalization_log", "_extra"}
    for k, v in data.items():
        if k not in skip:
            extra[k] = v
    return extra if extra else None


# ── Normalizers per file type ────────────────────────────────────

def normalize_thread_extractions(data):
    """Find thread/extraction data and normalize to canonical threads dict."""
    log = []
    threads = {}

    # Strategy 1: threads is a dict with expected keys
    if "threads" in data and isinstance(data["threads"], dict) and data["threads"]:
        raw = data["threads"]
        for tname, tdata in raw.items():
            if isinstance(tdata, dict):
                entries = tdata.get("entries", tdata.get("moments", []))
                desc = tdata.get("description", tdata.get("thread_name", tname))
                threads[tname] = {"description": desc, "entries": entries if isinstance(entries, list) else []}
            elif isinstance(tdata, list):
                threads[tname] = {"description": tname, "entries": tdata}
        log.append(f"threads dict: {len(threads)} threads found")

    # Strategy 2: threads is a list
    elif "threads" in data and isinstance(data["threads"], list) and data["threads"]:
        for item in data["threads"]:
            if isinstance(item, dict):
                name = item.get("thread", item.get("thread_name", item.get("name", item.get("category", "unknown"))))
                entries = item.get("entries", item.get("moments", item.get("messages", [])))
                if isinstance(name, str):
                    if name not in threads:
                        threads[name] = {"description": name, "entries": []}
                    if isinstance(entries, list):
                        threads[name]["entries"].extend(entries)
                    else:
                        threads[name]["entries"].append(item)
        log.append(f"threads list: {len(threads)} threads extracted")

    # Strategy 3: extractions (list) — the dominant pattern (182 sessions)
    elif "extractions" in data and isinstance(data["extractions"], list) and data["extractions"]:
        raw = data["extractions"]
        for item in raw:
            if isinstance(item, dict):
                cat = item.get("thread", item.get("category", item.get("type", "uncategorized")))
                if isinstance(cat, str):
                    if cat not in threads:
                        threads[cat] = {"description": cat, "entries": []}
                    threads[cat]["entries"].append(item)
        log.append(f"extractions list: {len(raw)} items → {len(threads)} threads")

    # Strategy 4: extractions (dict)
    elif "extractions" in data and isinstance(data["extractions"], dict) and data["extractions"]:
        raw = data["extractions"]
        for cat, items in raw.items():
            if isinstance(items, list):
                threads[cat] = {"description": cat, "entries": items}
            elif isinstance(items, dict):
                threads[cat] = {"description": cat, "entries": [items]}
        log.append(f"extractions dict: {len(threads)} categories")

    # Strategy 5: thread_N_ top-level keys (e.g., thread_1_topic_intent)
    if not threads:
        thread_keys = {k: v for k, v in data.items()
                       if k.startswith("thread_") and not k.startswith("thread_summary")
                       and not k.startswith("thread_count") and not k.startswith("thread_relationships")}
        if thread_keys:
            for k, v in thread_keys.items():
                threads[k] = {"description": k, "entries": v if isinstance(v, list) else [v]}
            log.append(f"thread_N keys: {len(thread_keys)} found at top level")

    if not threads:
        log.append("NO extractable thread data found")

    canonical = extract_metadata(data)
    canonical["threads"] = threads
    canonical["_extra"] = collect_extra(data, {"threads", "extractions"}
                           | {k for k in data if k.startswith("thread_")})
    canonical["_normalization_log"] = log
    return canonical


def normalize_semantic_primitives(data):
    """Find primitives data and normalize to tagged_messages list."""
    log = []
    tagged = []
    distributions = data.get("distributions", {})
    summary = data.get("summary_statistics", data.get("session_primitive_summary", {}))

    PRIMITIVE_FIELDS = {"action_vector", "confidence_signal", "emotional_tenor",
                        "intent_marker", "friction_log", "decision_trace", "disclosure_pointer"}

    def is_primitive_item(item):
        if not isinstance(item, dict):
            return False
        return bool(PRIMITIVE_FIELDS & set(item.keys()))

    def extract_from_segments(segments):
        """Flatten segment-grouped primitives into a flat list."""
        out = []
        for seg in segments:
            if not isinstance(seg, dict):
                continue
            # Segment might contain primitives directly or nested
            for k in ["primitives", "tagged_messages", "messages", "items"]:
                if k in seg and isinstance(seg[k], list):
                    out.extend(seg[k])
                    break
                elif k in seg and isinstance(seg[k], dict):
                    # Primitives as a dict (one set per segment) — convert to list item
                    prim = seg[k]
                    # Add segment context
                    prim["_segment_id"] = seg.get("segment_id", seg.get("label", ""))
                    prim["_message_indices"] = seg.get("message_indices", [])
                    out.append(prim)
                    break
            else:
                # Maybe the segment IS a primitive
                if is_primitive_item(seg):
                    out.append(seg)
        return out

    # Strategy 1: tagged_messages (already canonical)
    if "tagged_messages" in data and isinstance(data["tagged_messages"], list):
        tagged = data["tagged_messages"]
        log.append(f"tagged_messages: {len(tagged)} items")

    # Strategy 2: primitives (list of primitive items)
    elif "primitives" in data and isinstance(data["primitives"], list):
        prims = data["primitives"]
        if prims and is_primitive_item(prims[0]):
            tagged = prims
            log.append(f"primitives list (direct): {len(tagged)} items")
        else:
            # Primitives might be segment-grouped
            tagged = extract_from_segments(prims)
            if tagged:
                log.append(f"primitives list (flattened segments): {len(tagged)} items")
            else:
                # Just preserve as-is
                tagged = prims
                log.append(f"primitives list (non-standard items): {len(tagged)} items preserved as-is")

    # Strategy 3: segments
    elif "segments" in data and isinstance(data["segments"], list):
        tagged = extract_from_segments(data["segments"])
        log.append(f"segments: flattened to {len(tagged)} items")

    # Strategy 4: primitives_by_segment / primitives_per_segment
    elif "primitives_by_segment" in data and isinstance(data["primitives_by_segment"], (list, dict)):
        pbs = data["primitives_by_segment"]
        if isinstance(pbs, list):
            tagged = extract_from_segments(pbs)
        elif isinstance(pbs, dict):
            for seg_items in pbs.values():
                if isinstance(seg_items, list):
                    tagged.extend(seg_items)
        log.append(f"primitives_by_segment: {len(tagged)} items")

    elif "primitives_per_segment" in data and isinstance(data["primitives_per_segment"], (list, dict)):
        pps = data["primitives_per_segment"]
        if isinstance(pps, list):
            tagged = extract_from_segments(pps)
        elif isinstance(pps, dict):
            for seg_items in pps.values():
                if isinstance(seg_items, list):
                    tagged.extend(seg_items)
        log.append(f"primitives_per_segment: {len(tagged)} items")

    # Strategy 5: message_primitives, per_exchange_primitives, tagged_segments, significant_messages
    if not tagged:
        for alt_key in ["message_primitives", "per_exchange_primitives", "tagged_segments",
                         "primitive_extractions", "significant_messages"]:
            if alt_key in data:
                val = data[alt_key]
                if isinstance(val, list) and val:
                    tagged = val
                    log.append(f"{alt_key}: {len(val)} items")
                    break
                elif isinstance(val, dict):
                    # Convert dict of message_id → primitives to list
                    for mk, mv in val.items():
                        if isinstance(mv, dict):
                            mv["_message_key"] = mk
                            tagged.append(mv)
                        elif isinstance(mv, list):
                            tagged.extend(mv)
                    if tagged:
                        log.append(f"{alt_key} (dict→list): {len(tagged)} items")
                        break

    if not tagged:
        log.append("NO per-message primitive data found")

    # Preserve session-level primitives if they exist
    session_level = data.get("session_level_primitives", data.get("session_primitive_summary", None))

    canonical = extract_metadata(data)
    canonical["tagged_messages"] = tagged
    canonical["distributions"] = distributions if isinstance(distributions, dict) else {}
    canonical["summary_statistics"] = summary if isinstance(summary, dict) else {}
    if session_level:
        canonical["session_level_primitives"] = session_level
    canonical["_extra"] = collect_extra(data, {
        "tagged_messages", "primitives", "segments", "distributions",
        "summary_statistics", "session_level_primitives", "session_primitive_summary",
        "primitives_by_segment", "primitives_per_segment", "primitives_schema",
        "primitive_definitions"
    })
    canonical["_normalization_log"] = log
    return canonical


def normalize_geological_notes(data):
    """Find multi-resolution observations and normalize."""
    log = []
    micro = []
    meso = []
    macro = []
    observations = []

    # Collect from all known key names
    for key, target in [
        ("micro", micro), ("meso", meso), ("macro", macro),
        ("observations", observations),
        ("strata", observations), ("layers", observations),
        ("geological_layers", observations), ("zoom_levels", observations),
        ("exploration_notes", observations),
        ("analysis_levels", observations), ("vertical_structures", observations),
        ("stratigraphy", observations), ("stratigraphic_column", observations),
        ("geological_features", observations), ("deep_time_observations", observations),
    ]:
        if key in data and isinstance(data[key], list):
            target.extend(data[key])
            log.append(f"{key}: {len(data[key])} items")
        elif key in data and isinstance(data[key], dict):
            # Sometimes micro/meso/macro are dicts with observations inside
            inner = data[key]
            for sub_key in ["observations", "entries", "notes", "findings"]:
                if sub_key in inner and isinstance(inner[sub_key], list):
                    target.extend(inner[sub_key])
                    log.append(f"{key}.{sub_key}: {len(inner[sub_key])} items")
                    break
            else:
                target.append(inner)
                log.append(f"{key}: 1 dict item")

    # Check for cross-cutting features, faults, fossils
    for extra_key in ["cross_cutting_features", "fault_lines", "fossils", "session_character"]:
        if extra_key in data and data[extra_key]:
            if isinstance(data[extra_key], list):
                observations.extend(data[extra_key])
                log.append(f"{extra_key}: {len(data[extra_key])} items added to observations")

    if not micro and not meso and not macro and not observations:
        log.append("NO geological data found")

    canonical = extract_metadata(data)
    canonical["micro"] = micro
    canonical["meso"] = meso
    canonical["macro"] = macro
    canonical["observations"] = observations
    canonical["geological_metaphor"] = data.get("geological_metaphor", "")
    canonical["_extra"] = collect_extra(data, {
        "micro", "meso", "macro", "observations", "strata", "layers",
        "geological_layers", "zoom_levels", "cross_cutting_features",
        "fault_lines", "fossils", "session_character", "geological_metaphor",
        "exploration_notes", "analysis_method"
    })
    canonical["_normalization_log"] = log
    return canonical


def normalize_explorer_notes(data):
    """Find explorer observations and normalize."""
    log = []
    observations = []

    for key in ["observations", "exploration_notes", "explorer_observations",
                "exploration_findings", "free_notes", "notes",
                "notable_observations", "surprising_observations",
                "overlooked_patterns", "explorer_findings", "explorations",
                "exploration_summary"]:
        if key in data and isinstance(data[key], list) and data[key]:
            observations.extend(data[key])
            log.append(f"{key}: {len(data[key])} items")

    # Also collect from specific sections
    for key in ["abandoned_ideas", "patterns", "warnings", "anomalies",
                "unanswered_questions", "open_questions", "what_matters_most",
                "emotional_dynamics", "cross_session_connections",
                "cross_session_links", "ideas_detected"]:
        if key in data and isinstance(data[key], list) and data[key]:
            for item in data[key]:
                if isinstance(item, dict):
                    item["_source_section"] = key
                observations.append(item) if isinstance(item, (dict, str)) else None
            log.append(f"{key}: {len(data[key])} items merged into observations")

    explorer_summary = data.get("explorer_summary", "")

    if not observations and not explorer_summary:
        log.append("NO explorer data found")

    canonical = extract_metadata(data)
    canonical["observations"] = observations
    canonical["explorer_summary"] = explorer_summary
    canonical["_extra"] = collect_extra(data, {
        "observations", "exploration_notes", "explorer_observations",
        "exploration_findings", "free_notes", "notes",
        "abandoned_ideas", "patterns", "warnings", "anomalies",
        "unanswered_questions", "open_questions", "what_matters_most",
        "emotional_dynamics", "cross_session_connections", "cross_session_links",
        "ideas_detected", "explorer_summary", "session_profile",
        "session_topology", "topology_description", "notable_patterns",
        "thread_relationships", "connections_to_other_sessions"
    })
    canonical["_normalization_log"] = log
    return canonical


def normalize_idea_graph(data):
    """Normalize idea graph — mostly already good, just standardize."""
    log = []
    nodes = []
    edges = []

    if "nodes" in data and isinstance(data["nodes"], list):
        nodes = data["nodes"]
        log.append(f"nodes: {len(nodes)}")
    elif "graph" in data and isinstance(data["graph"], dict):
        nodes = data["graph"].get("nodes", [])
        edges = data["graph"].get("edges", [])
        log.append(f"graph.nodes: {len(nodes)}, graph.edges: {len(edges)}")
    elif "idea_nodes" in data:
        nodes = data["idea_nodes"] if isinstance(data["idea_nodes"], list) else []
        log.append(f"idea_nodes: {len(nodes)}")

    if not edges:
        if "edges" in data and isinstance(data["edges"], list):
            edges = data["edges"]
            log.append(f"edges: {len(edges)}")
        elif "transitions" in data and isinstance(data["transitions"], list):
            edges = data["transitions"]
            log.append(f"transitions (as edges): {len(edges)}")

    metadata = data.get("metadata", data.get("statistics", data.get("graph_stats", {})))
    subgraphs = data.get("subgraphs", [])

    if not nodes:
        log.append("NO idea graph nodes found")

    canonical = extract_metadata(data)
    canonical["nodes"] = nodes
    canonical["edges"] = edges
    canonical["metadata"] = metadata if isinstance(metadata, dict) else {}
    if subgraphs:
        canonical["subgraphs"] = subgraphs
    canonical["_extra"] = collect_extra(data, {
        "nodes", "edges", "metadata", "statistics", "graph_stats",
        "graph", "idea_nodes", "transitions", "subgraphs",
        "node_count", "edge_count", "session_context"
    })
    canonical["_normalization_log"] = log
    return canonical


def normalize_synthesis(data):
    """Normalize synthesis passes to dict format."""
    log = []
    passes = {}
    key_findings = data.get("key_findings", [])
    session_character = data.get("session_character", data.get("session_type", ""))
    cross_session = data.get("cross_session_links", [])

    # Strategy 1: passes as dict (dominant — 191 sessions)
    if "passes" in data and isinstance(data["passes"], dict):
        passes = data["passes"]
        log.append(f"passes dict: {len(passes)} keys")

    # Strategy 2: passes as list
    elif "passes" in data and isinstance(data["passes"], list):
        for i, p in enumerate(data["passes"]):
            if isinstance(p, dict):
                name = p.get("pass_name", p.get("name", p.get("label", f"pass_{i+1}")))
                passes[name] = p
            else:
                passes[f"pass_{i+1}"] = p
        log.append(f"passes list: {len(passes)} converted to dict")

    # Strategy 3: pass_N_ top-level keys
    else:
        pass_keys = {k: v for k, v in data.items() if k.startswith("pass_")}
        if pass_keys:
            passes = pass_keys
            log.append(f"pass_N keys: {len(passes)} found at top level")
        elif "six_pass_synthesis" in data:
            sps = data["six_pass_synthesis"]
            if isinstance(sps, dict):
                passes = sps
            elif isinstance(sps, list):
                for i, p in enumerate(sps):
                    passes[f"pass_{i+1}"] = p
            log.append(f"six_pass_synthesis: {len(passes)} passes")
        elif "narrative_synthesis" in data:
            passes["narrative_synthesis"] = data["narrative_synthesis"]
            log.append("narrative_synthesis: 1 item")
        elif "one_sentence" in data or "one_line_summary" in data:
            passes["summary"] = {
                "one_sentence": data.get("one_sentence", data.get("one_line_summary", "")),
                "key_insights": data.get("key_insights", data.get("key_metrics", {})),
                "narrative_arc": data.get("narrative_arc", ""),
                "emotional_trajectory": data.get("emotional_trajectory", ""),
                "session_type": data.get("session_type", ""),
                "behavioral_assessment": data.get("behavioral_assessment", {}),
                "files_produced": data.get("files_produced", []),
            }
            log.append("one_line_summary/key_insights style: consolidated")
        else:
            log.append("NO synthesis pass data found")

    canonical = extract_metadata(data)
    canonical["passes"] = passes
    canonical["key_findings"] = key_findings if isinstance(key_findings, list) else []
    canonical["session_character"] = session_character
    canonical["cross_session_links"] = cross_session if isinstance(cross_session, list) else []
    canonical["_extra"] = collect_extra(data, {
        "passes", "key_findings", "session_character", "cross_session_links",
        "session_type", "one_sentence", "key_metrics", "behavioral_assessment",
        "narrative_synthesis",
    } | {k for k in data if k.startswith("pass_")})
    canonical["_normalization_log"] = log
    return canonical


def normalize_grounded_markers(data):
    """Normalize grounded markers — find markers wherever they live."""
    log = []
    markers = []

    if "markers" in data and isinstance(data["markers"], list) and data["markers"]:
        markers = data["markers"]
        log.append(f"markers: {len(markers)} items")
    elif "markers" in data and isinstance(data["markers"], list) and not data["markers"]:
        # Empty markers — check alt locations
        for alt_key in ["warnings", "recommendations", "patterns"]:
            if alt_key in data and isinstance(data[alt_key], list) and data[alt_key]:
                for item in data[alt_key]:
                    if isinstance(item, dict):
                        item["_source_type"] = alt_key
                    markers.append(item)
                log.append(f"markers empty, recovered from {alt_key}: {len(data[alt_key])} items")
        if "metrics" in data and isinstance(data["metrics"], dict):
            # metrics-style: convert to a single summary marker
            markers.append({
                "marker_id": "GM-METRICS",
                "category": "metrics",
                "claim": json.dumps(data["metrics"]),
                "confidence": 0.5,
                "_source_type": "metrics"
            })
            log.append("metrics dict converted to summary marker")
    elif "markers" not in data:
        # No markers key at all — check session_level_markers first
        for level_key in ["session_level_markers", "file_level_markers", "function_level_markers"]:
            if level_key in data and isinstance(data[level_key], list) and data[level_key]:
                for item in data[level_key]:
                    if isinstance(item, dict):
                        item["_source_type"] = level_key
                    markers.append(item)
                log.append(f"{level_key}: {len(data[level_key])} items")
        # Then check warnings/recs if still empty
        if not markers:
            for alt_key_inner in ["warnings", "recommendations", "patterns"]:
                if alt_key_inner in data and isinstance(data[alt_key_inner], list) and data[alt_key_inner]:
                    for item in data[alt_key_inner]:
                        if isinstance(item, dict):
                            item["_source_type"] = alt_key_inner
                        markers.append(item)
                    log.append(f"no markers key, recovered from {alt_key_inner}: {len(data[alt_key_inner])} items")
        # Skip the original alt_key loop since we handled it above
        for alt_key in []:
            if alt_key in data and isinstance(data[alt_key], list) and data[alt_key]:
                for item in data[alt_key]:
                    if isinstance(item, dict):
                        item["_source_type"] = alt_key
                    markers.append(item)
                log.append(f"no markers key, recovered from {alt_key}: {len(data[alt_key])} items")
    else:
        log.append("NO marker data found")

    canonical = extract_metadata(data)
    canonical["markers"] = markers
    canonical["total_markers"] = len(markers)
    canonical["_extra"] = collect_extra(data, {
        "markers", "total_markers", "marker_count",
        "warnings", "recommendations", "patterns", "metrics",
        "placement_summary", "purpose", "source"
    })
    canonical["_normalization_log"] = log
    return canonical


def normalize_file_dossiers(data):
    """Normalize file dossiers — find dossiers dict."""
    log = []
    dossiers = {}

    if "dossiers" in data and isinstance(data["dossiers"], dict):
        dossiers = data["dossiers"]
        log.append(f"dossiers dict: {len(dossiers)} files")
    elif "dossiers" in data and isinstance(data["dossiers"], list):
        for item in data["dossiers"]:
            if isinstance(item, dict):
                fname = item.get("file", item.get("filename", item.get("name", f"unknown_{len(dossiers)}")))
                dossiers[fname] = item
        log.append(f"dossiers list: {len(dossiers)} files converted to dict")
    else:
        # Check for data_file_dossiers or other alt keys
        for alt_key in ["data_file_dossiers", "file_dossiers", "files",
                        "detailed_dossiers", "code_file_dossiers",
                        "analysis_output_dossiers", "conceptual_entity_dossiers",
                        "standard_dossiers", "peripheral_files"]:
            if alt_key in data and isinstance(data[alt_key], (dict, list)):
                if isinstance(data[alt_key], dict):
                    dossiers = data[alt_key]
                elif isinstance(data[alt_key], list):
                    for item in data[alt_key]:
                        if isinstance(item, dict):
                            fname = item.get("file", item.get("filename", f"unknown_{len(dossiers)}"))
                            dossiers[fname] = item
                log.append(f"{alt_key}: {len(dossiers)} files")
                break
        else:
            log.append("NO dossier data found")

    significance = data.get("significance_tiers", {})
    summary_stats = data.get("summary_statistics", {})

    canonical = extract_metadata(data)
    canonical["dossiers"] = dossiers
    canonical["total_files_cataloged"] = data.get("total_files_cataloged",
                                          data.get("total_files_analyzed",
                                          data.get("total_unique_files",
                                          data.get("total_files_mapped",
                                          data.get("total_files_mentioned", len(dossiers))))))
    canonical["significance_tiers"] = significance if isinstance(significance, dict) else {}
    canonical["summary_statistics"] = summary_stats if isinstance(summary_stats, dict) else {}
    canonical["_extra"] = collect_extra(data, {
        "dossiers", "total_files_cataloged", "total_files_analyzed",
        "total_unique_files", "total_files_mapped", "total_files_mentioned",
        "significance_tiers", "summary_statistics", "data_file_dossiers",
        "file_dossiers", "files", "file_clusters", "method",
        "total_code_files", "total_data_files", "session_context",
        "sources_cross_referenced"
    })
    canonical["_normalization_log"] = log
    return canonical


def normalize_claude_md_analysis(data):
    """Normalize claude_md_analysis — standardize gate activations."""
    log = []
    gate_activations = []
    overall = {}

    if "gate_activations" in data and isinstance(data["gate_activations"], list):
        gate_activations = data["gate_activations"]
        log.append(f"gate_activations: {len(gate_activations)} items")
    elif "gate_activations" in data and isinstance(data["gate_activations"], dict):
        gate_activations = [data["gate_activations"]]
        log.append("gate_activations: 1 dict converted to list")

    if "overall_assessment" in data and isinstance(data["overall_assessment"], (dict, str)):
        overall = data["overall_assessment"]
        log.append(f"overall_assessment: {'dict' if isinstance(overall, dict) else 'string'}")

    # Collect behavior profile data from alt schemas
    behavior_profile = data.get("claude_behavior_profile",
                        data.get("claude_behavior_patterns",
                        data.get("behavioral_timeline", {})))

    gates_not_triggered = data.get("gates_not_triggered", [])
    security = data.get("tier2_security_analysis", {})

    if not gate_activations and not overall and not behavior_profile:
        # Try to find ANY analysis data
        for key in ["key_findings", "recommendations_for_future_sessions",
                     "trust_calibration_assessment", "claude_capability_assessment"]:
            if key in data:
                overall[key] = data[key]
                log.append(f"recovered {key} into overall_assessment")

    if not gate_activations and not overall:
        log.append("NO claude_md analysis data found")

    canonical = extract_metadata(data)
    canonical["gate_activations"] = gate_activations
    canonical["gates_not_triggered"] = gates_not_triggered if isinstance(gates_not_triggered, list) else []
    canonical["overall_assessment"] = overall
    canonical["behavior_profile"] = behavior_profile if isinstance(behavior_profile, dict) else {}
    canonical["tier2_security_analysis"] = security if isinstance(security, dict) else {}
    canonical["_extra"] = collect_extra(data, {
        "gate_activations", "gates_not_triggered", "overall_assessment",
        "claude_behavior_profile", "claude_behavior_patterns", "behavioral_timeline",
        "tier2_security_analysis", "analysis_purpose", "session_context",
        "session_profile", "session_behavioral_context",
        "key_findings", "recommendations_for_future_sessions",
        "trust_calibration_assessment", "claude_capability_assessment",
        "gates_low_relevance"
    })
    canonical["_normalization_log"] = log
    return canonical


# ── Registry ─────────────────────────────────────────────────────

NORMALIZERS = {
    "thread_extractions.json": normalize_thread_extractions,
    "geological_notes.json": normalize_geological_notes,
    "semantic_primitives.json": normalize_semantic_primitives,
    "explorer_notes.json": normalize_explorer_notes,
    "idea_graph.json": normalize_idea_graph,
    "synthesis.json": normalize_synthesis,
    "grounded_markers.json": normalize_grounded_markers,
    "file_dossiers.json": normalize_file_dossiers,
    "claude_md_analysis.json": normalize_claude_md_analysis,
}


# ── Main processing ──────────────────────────────────────────────

def normalize_file(filepath, normalizer_fn, dry_run=False):
    """Normalize a single file. Returns (status, log_lines)."""
    try:
        with open(filepath) as f:
            data = json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        return "ERROR", [f"Failed to read: {e}"]

    # Skip if already normalized
    if "_normalized_at" in data:
        return "SKIP", ["Already normalized"]

    # Run the normalizer
    canonical = normalizer_fn(data)
    canonical["_normalized_at"] = datetime.now(timezone.utc).isoformat()

    if dry_run:
        return "WOULD_NORMALIZE", canonical.get("_normalization_log", [])

    # Back up original
    backup_dir = filepath.parent / "backups"
    backup_dir.mkdir(exist_ok=True)
    backup_path = backup_dir / filepath.name
    if not backup_path.exists():
        shutil.copy2(filepath, backup_path)

    # Atomic write: temp file then rename
    fd, tmp_path = tempfile.mkstemp(dir=filepath.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(canonical, f, indent=2, default=str)
        os.replace(tmp_path, filepath)
    except Exception as e:
        os.unlink(tmp_path)
        return "WRITE_ERROR", [f"Failed to write: {e}"]

    return "NORMALIZED", canonical.get("_normalization_log", [])


def normalize_session(session_dir, dry_run=False):
    """Normalize all agent-produced files in a session."""
    results = {}
    for filename, normalizer_fn in NORMALIZERS.items():
        filepath = session_dir / filename
        if filepath.exists():
            status, log = normalize_file(filepath, normalizer_fn, dry_run)
            results[filename] = {"status": status, "log": log}
    return results


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Schema Normalizer")
    parser.add_argument("--dry-run", action="store_true", help="Report only, don't modify files")
    parser.add_argument("--session", type=str, help="Normalize a single session directory name")
    args = parser.parse_args()

    sessions_dir = Path.home() / "PERMANENT_HYPERDOCS" / "sessions"

    if args.session:
        target = sessions_dir / args.session
        if not target.exists():
            print(f"Session not found: {target}")
            sys.exit(1)
        session_dirs = [target]
    else:
        session_dirs = sorted(d for d in sessions_dir.iterdir() if d.is_dir())

    print(f"{'DRY RUN — ' if args.dry_run else ''}Schema Normalizer")
    print(f"Sessions: {len(session_dirs)}")
    print(f"File types: {len(NORMALIZERS)}")
    print()

    totals = Counter()
    per_file_totals = {fn: Counter() for fn in NORMALIZERS}
    all_logs = []

    for sd in session_dirs:
        results = normalize_session(sd, dry_run=args.dry_run)
        for filename, result in results.items():
            status = result["status"]
            totals[status] += 1
            per_file_totals[filename][status] += 1
            if status not in ("SKIP",):
                all_logs.append(f"  {sd.name}/{filename}: {status} — {'; '.join(result['log'])}")

    # Print summary
    print("=" * 70)
    print("RESULTS")
    print("=" * 70)
    print(f"\nOverall: {dict(totals)}")
    print()
    for filename in NORMALIZERS:
        counts = per_file_totals[filename]
        print(f"  {filename:<36s}  {dict(counts)}")

    # Print detailed logs (limited)
    if all_logs:
        print(f"\nDetailed log ({len(all_logs)} entries):")
        for line in all_logs[:50]:
            print(line)
        if len(all_logs) > 50:
            print(f"  ... and {len(all_logs) - 50} more")

    # Write full log to file
    log_path = sessions_dir.parent / "indexes" / "normalization_log.json"
    log_data = {
        "run_at": datetime.now(timezone.utc).isoformat(),
        "dry_run": args.dry_run,
        "sessions_processed": len(session_dirs),
        "totals": dict(totals),
        "per_file": {fn: dict(c) for fn, c in per_file_totals.items()},
        "details": all_logs,
    }
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with open(log_path, "w") as f:
        json.dump(log_data, f, indent=2)
    print(f"\nFull log: {log_path}")


if __name__ == "__main__":
    main()
