#!/usr/bin/env python3
"""
Claim Extractor — Extract verifiable claims from pipeline outputs.

Reads grounded_markers.json, semantic_primitives.json, synthesis.json,
idea_graph.json and maps claims to specific files.

Output: ground_truth_claims.json
"""
import json
from pathlib import Path
from datetime import datetime

BASE = Path(__file__).parent.parent  # output/session_3b7084d5/
SESSION_ID = "3b7084d5"

ALL_FILES = [
    "unified_orchestrator.py", "geological_reader.py", "hyperdoc_pipeline.py",
    "story_marker_generator.py", "six_thread_extractor.py", "geological_pipeline.py",
    "marker_generator.py", "opus_logger.py", "opus_struggle_analyzer.py",
    "layer_builder.py", "resurrection_engine.py", "tiered_llm_caller.py",
    "semantic_chunker.py", "anti_resurrection.py", "four_thread_extractor.py",
]


def load_json(filename):
    path = BASE / filename
    if not path.exists():
        print(f"  WARN: {filename} not found")
        return {}
    with open(path) as f:
        return json.load(f)


def file_matches_target(filename, target):
    """Check if a warning target applies to a specific file."""
    if not target:
        return False
    target_lower = target.lower()
    if filename.lower() in target_lower:
        return True
    if "all python files" in target_lower or "all files" in target_lower:
        return True
    if "v5 code" in target_lower:
        return True
    if "llm-calling code" in target_lower or "llm calling code" in target_lower:
        # Applies to files that call LLMs
        llm_callers = [
            "geological_reader.py", "geological_pipeline.py", "layer_builder.py",
            "semantic_chunker.py", "story_marker_generator.py", "hyperdoc_pipeline.py",
            "opus_struggle_analyzer.py", "opus_logger.py", "tiered_llm_caller.py",
            "four_thread_extractor.py", "six_thread_extractor.py",
            "resurrection_engine.py", "anti_resurrection.py",
        ]
        return filename in llm_callers
    if ".env" in target_lower:
        return True  # All V5 files potentially affected by .env issues
    return False


def extract_warning_claims(markers):
    """Extract resolution claims and unresolved warnings from grounded_markers."""
    warnings = markers.get("warnings", [])
    per_file = {f: {"resolution_claims": [], "unresolved_warnings": []} for f in ALL_FILES}

    for w in warnings:
        target = w.get("target", "")
        warning_id = w.get("id", "")
        warning_text = w.get("warning", "")
        severity = w.get("severity", "unknown")
        first_discovered = w.get("first_discovered")
        resolution_index = w.get("resolution_index")
        evidence = w.get("evidence", "")

        for filename in ALL_FILES:
            if not file_matches_target(filename, target):
                continue

            entry = {
                "warning_id": warning_id,
                "severity": severity,
                "warning": warning_text,
                "first_discovered": first_discovered,
                "evidence": evidence,
            }

            if resolution_index is not None:
                entry["claim"] = f"Fixed at msg {resolution_index}"
                entry["resolution_index"] = resolution_index
                per_file[filename]["resolution_claims"].append(entry)
            else:
                entry["claim"] = "UNRESOLVED — no fix recorded"
                per_file[filename]["unresolved_warnings"].append(entry)

    return per_file


def extract_confidence_claims(primitives):
    """Extract messages where confidence=proven/stable and map to files."""
    per_file = {f: [] for f in ALL_FILES}
    messages = primitives.get("messages", [])

    for msg in messages:
        confidence = msg.get("confidence_signal", "")
        if confidence not in ("proven", "stable"):
            continue

        idx = msg.get("index", msg.get("message_index", None))
        friction = msg.get("friction_log", "")
        decision = msg.get("decision_trace", "")
        action = msg.get("action_vector", "")
        content_preview = msg.get("content_preview", "")

        # Try to map to a file via friction_log, decision_trace, or content
        text_to_search = f"{friction} {decision} {content_preview}".lower()

        for filename in ALL_FILES:
            stem = filename.replace(".py", "").lower()
            if stem in text_to_search or filename.lower() in text_to_search:
                per_file[filename].append({
                    "claim": f"Confidence={confidence} at msg {idx}",
                    "msg_index": idx,
                    "confidence": confidence,
                    "action": action,
                    "friction": friction,
                    "decision": decision,
                })

    return per_file


def extract_premature_victories(markers):
    """Extract B02 pattern (premature victory declarations)."""
    patterns = markers.get("patterns", [])
    per_file = {f: [] for f in ALL_FILES}

    for p in patterns:
        if p.get("id") != "B02":
            continue

        instances = p.get("instances", [])
        description = p.get("description", "")
        frequency = p.get("frequency", "")

        # B02 is session-wide — map to files based on what was being worked on
        # We know the 9 premature victories, but exact file mapping requires
        # cross-referencing with synthesis chronological events
        for filename in ALL_FILES:
            per_file[filename].append({
                "pattern": "B02",
                "claim": f"Claude declares completion before verification — {frequency}",
                "description": description,
                "session_wide": True,
            })
        break  # Only one B02 entry

    return per_file


def extract_iron_rule_claims(markers):
    """Extract iron rules and their establishment claims."""
    rules = markers.get("iron_rules_registry", [])
    per_file = {f: [] for f in ALL_FILES}

    # Map rules to relevant files
    rule_file_map = {
        1: ALL_FILES,  # Never delete imports — applies to all
        2: ALL_FILES,  # Working healthy system — applies to all
        3: [],  # HTML visualizations — not code files
        4: ["marker_generator.py", "story_marker_generator.py", "resurrection_engine.py"],
        5: [f for f in ALL_FILES if f not in ("unified_orchestrator.py",)],  # Opus only
        6: ["story_marker_generator.py"],  # Grounding = translation
        7: [f for f in ALL_FILES if f not in ("unified_orchestrator.py",)],  # No fallbacks
        8: ["tiered_llm_caller.py", "semantic_chunker.py"],  # Haiku acceptable if Opus trains
    }

    for rule in rules:
        rule_num = rule.get("rule_number", 0)
        rule_text = rule.get("rule", "")
        established_at = rule.get("established_at")
        status = rule.get("status", "active")

        applicable_files = rule_file_map.get(rule_num, [])
        for filename in applicable_files:
            per_file[filename].append({
                "rule_number": rule_num,
                "claim": f"Iron rule {rule_num} established at msg {established_at}, status: {status}",
                "rule_text": rule_text,
                "established_at": established_at,
                "status": status,
            })

    return per_file


def extract_idea_confidence_claims(idea_graph):
    """Extract idea nodes with high confidence and map to files."""
    per_file = {f: [] for f in ALL_FILES}
    nodes = idea_graph.get("nodes", [])

    for node in nodes:
        confidence = node.get("confidence", "")
        if confidence not in ("proven", "stable", "working"):
            continue

        name = node.get("name", "")
        description = node.get("description", "")
        first_appearance = node.get("first_appearance")

        text_to_search = f"{name} {description}".lower()
        for filename in ALL_FILES:
            stem = filename.replace(".py", "").replace("_", " ").lower()
            if stem in text_to_search or filename.lower() in text_to_search:
                per_file[filename].append({
                    "claim": f"Idea '{name}' confidence={confidence}",
                    "idea_name": name,
                    "confidence": confidence,
                    "first_appearance": first_appearance,
                    "description": description[:200],
                })

    return per_file


def merge_claims(warning_claims, confidence_claims, victory_claims, rule_claims, idea_claims):
    """Merge all claim types into a single per-file structure."""
    result = {}
    for filename in ALL_FILES:
        result[filename] = {
            "resolution_claims": warning_claims.get(filename, {}).get("resolution_claims", []),
            "unresolved_warnings": warning_claims.get(filename, {}).get("unresolved_warnings", []),
            "confidence_claims": confidence_claims.get(filename, []),
            "premature_victories": victory_claims.get(filename, []),
            "iron_rule_claims": rule_claims.get(filename, []),
            "idea_confidence_claims": idea_claims.get(filename, []),
        }
    return result


def main():
    print("=" * 60)
    print("Claim Extractor — Ground Truth Verification")
    print("=" * 60)
    print(f"Session: conv_{SESSION_ID}")
    print(f"Timestamp: {datetime.now().isoformat()}")
    print()

    markers = load_json("grounded_markers.json")
    primitives = load_json("semantic_primitives.json")
    idea_graph = load_json("idea_graph.json")

    print("Extracting claims...")
    warning_claims = extract_warning_claims(markers)
    confidence_claims = extract_confidence_claims(primitives)
    victory_claims = extract_premature_victories(markers)
    rule_claims = extract_iron_rule_claims(markers)
    idea_claims = extract_idea_confidence_claims(idea_graph)

    all_claims = merge_claims(warning_claims, confidence_claims, victory_claims, rule_claims, idea_claims)

    # Summary
    print()
    for filename in ALL_FILES:
        fc = all_claims[filename]
        total = (len(fc["resolution_claims"]) + len(fc["unresolved_warnings"]) +
                 len(fc["confidence_claims"]) + len(fc["premature_victories"]) +
                 len(fc["iron_rule_claims"]) + len(fc["idea_confidence_claims"]))
        resolved = len(fc["resolution_claims"])
        unresolved = len(fc["unresolved_warnings"])
        print(f"  {filename}: {total} claims ({resolved} resolved, {unresolved} unresolved)")

    # Write output
    output = {
        "session_id": SESSION_ID,
        "generated_at": datetime.now().isoformat(),
        "total_files": len(ALL_FILES),
        "claims": all_claims,
    }

    out_path = Path(__file__).parent / "ground_truth_claims.json"
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2)

    total_claims = sum(
        len(v["resolution_claims"]) + len(v["unresolved_warnings"]) +
        len(v["confidence_claims"]) + len(v["premature_victories"]) +
        len(v["iron_rule_claims"]) + len(v["idea_confidence_claims"])
        for v in all_claims.values()
    )
    print(f"\nTotal: {total_claims} claims across {len(ALL_FILES)} files")
    print(f"Output: {out_path}")


if __name__ == "__main__":
    main()
