#!/usr/bin/env python3
"""
File Genealogy Detector

AI doesn't version files — it rewrites them under new names. This script
detects file identity across renames, rewrites, and duplications.

Users see 40 files and feel overwhelmed. This shows them: "you actually
have 12 concepts, and here's the latest version of each."

Three detection signals:
1. Idea graph lineage — concept A (mentions file X) evolved into concept B (mentions file Y)
2. Temporal succession — file X stops being modified, file Y starts at the same time
3. Name similarity — files with overlapping stems (thread_extractor → six_thread_extractor)

Input:  thread_extractions.json + idea_graph.json
Output: file_genealogy.json
"""
import os
import sys
import json
import re
from pathlib import Path
from datetime import datetime
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
try:
    from config import get_session_output_dir, SESSION_ID
except ImportError:
    SESSION_ID = os.getenv("HYPERDOCS_SESSION_ID", "")
    def get_session_output_dir():
        out = Path(os.getenv("HYPERDOCS_OUTPUT_DIR", "./output")) / f"session_{SESSION_ID[:8]}"
        out.mkdir(parents=True, exist_ok=True)
        return out


def load_json(path):
    if not path.exists():
        print(f"  WARN: {path} not found")
        return {}
    with open(path) as f:
        return json.load(f)


def build_file_timelines(thread_data):
    """Build activity timelines from thread extractions.

    Supports two formats:
    - Old format: thread_data["extractions"] is a list; each entry has
      entry["threads"]["software"]["created"] and ["modified"] as filename lists.
    - Canonical format: thread_data["threads"] is a dict with category keys;
      thread_data["threads"]["software"]["entries"] is a list of
      {"msg_index": N, "content": "...", "significance": "..."} dicts.
      Filenames are extracted from the free-text "content" field.

    Returns: {filename: [{msg: N, action: created|modified}, ...]}
    """
    timelines = defaultdict(list)

    # --- Old format ---
    extractions = thread_data.get("extractions", [])
    for ext in extractions:
        idx = ext.get("index", 0)
        sw = ext.get("threads", {}).get("software", {})
        if not isinstance(sw, dict):
            continue

        for f in sw.get("created", []):
            if f.endswith(".py"):
                timelines[f].append({"msg": idx, "action": "created"})
        for f in sw.get("modified", []):
            if f.endswith(".py"):
                timelines[f].append({"msg": idx, "action": "modified"})

    # --- Canonical format ---
    # thread_data["threads"] is a dict; "software" key holds file activity entries.
    threads_dict = thread_data.get("threads", {})
    if isinstance(threads_dict, dict):
        sw_category = threads_dict.get("software", {})
        if isinstance(sw_category, dict):
            for entry in sw_category.get("entries", []):
                idx = entry.get("msg_index", 0)
                content = entry.get("content", "")
                # Heuristic: treat "created" vs "modified" by keywords in content.
                # Words like "created", "wrote", "new file" → created action.
                # Words like "modified", "updated", "edited", "changed" → modified action.
                content_lower = content.lower()
                if any(w in content_lower for w in ("creat", "wrote", "new file", "added")):
                    action = "created"
                elif any(w in content_lower for w in ("modif", "updat", "edit", "chang", "fix")):
                    action = "modified"
                else:
                    action = "modified"  # default for ambiguous software entries

                for f in extract_files_from_text(content):
                    timelines[f].append({"msg": idx, "action": action})

    # Sort each timeline by message index
    for f in timelines:
        timelines[f].sort(key=lambda x: x["msg"])

    return dict(timelines)


def get_file_active_range(timeline):
    """Get the first and last message where a file was touched."""
    if not timeline:
        return None, None
    return timeline[0]["msg"], timeline[-1]["msg"]


def extract_files_from_text(text):
    """Extract .py filenames from text."""
    return re.findall(r'[\w_]+\.py', text)


def build_idea_file_links(idea_graph):
    """Map idea nodes to the files they mention.

    Returns: {idea_id: [filename, ...]}
    """
    idea_files = {}
    nodes = idea_graph.get("nodes", [])

    for node in nodes:
        node_id = node.get("id", "")
        text = f"{node.get('name', '')} {node.get('description', '')}"
        files = extract_files_from_text(text)
        if files:
            idea_files[node_id] = list(set(files))

    return idea_files


def detect_idea_graph_lineage(idea_graph, idea_files):
    """Find file-to-file links via idea graph edges.

    If idea A mentions file X and idea B mentions file Y,
    and A→B is evolved/pivoted/concretized, then X→Y is a lineage link.

    Returns: [(file_from, file_to, transition_type, evidence), ...]
    """
    links = []
    edges = idea_graph.get("edges", [])

    for edge in edges:
        # Old format uses "from_id"/"to_id"; canonical format uses "from"/"to".
        src_id = edge.get("from_id") or edge.get("from", "")
        tgt_id = edge.get("to_id") or edge.get("to", "")
        transition = edge.get("transition_type", "")
        trigger = edge.get("trigger_message", 0)
        evidence = edge.get("evidence", "")

        if transition not in ("evolved", "pivoted", "concretized", "split", "merged"):
            continue

        src_files = idea_files.get(src_id, [])
        tgt_files = idea_files.get(tgt_id, [])

        if not src_files or not tgt_files:
            continue

        for sf in src_files:
            for tf in tgt_files:
                if sf != tf:  # Different files linked through concept evolution
                    links.append({
                        "from_file": sf,
                        "to_file": tf,
                        "transition": transition,
                        "trigger_msg": trigger,
                        "evidence": evidence if evidence else "",
                        "source": "idea_graph",
                    })

    return links


def detect_temporal_succession(timelines):
    """Find files where one stops being modified and another starts.

    Signal: file X's last modification is within 20 messages of file Y's first appearance.
    """
    links = []
    files = list(timelines.keys())

    for i, file_a in enumerate(files):
        _, last_a = get_file_active_range(timelines[file_a])
        if last_a is None:
            continue

        for file_b in files[i + 1:]:
            first_b, _ = get_file_active_range(timelines[file_b])
            if first_b is None:
                continue

            # Check if B starts within 5 messages of A ending (bidirectional)
            _, last_b = get_file_active_range(timelines[file_b])
            first_a, _ = get_file_active_range(timelines[file_a])
            gap = first_b - last_a
            gap_reverse = first_a - last_b if last_b is not None and first_a is not None else float('inf')
            if 0 < gap <= 5 or 0 < gap_reverse <= 5:
                gap = min(abs(gap), abs(gap_reverse)) if gap_reverse != float('inf') else gap
                links.append({
                    "from_file": file_a,
                    "to_file": file_b,
                    "transition": "temporal_succession",
                    "trigger_msg": first_b,
                    "evidence": f"{file_a} last modified at msg {last_a}, {file_b} first appears at msg {first_b} (gap: {gap} msgs)",
                    "source": "temporal",
                    "gap": gap,
                })

    return links


def detect_name_similarity(timelines):
    """Find files with overlapping name stems.

    four_thread_extractor.py and six_thread_extractor.py share "thread_extractor".
    """
    links = []
    files = list(timelines.keys())

    def get_stems(filename):
        """Extract meaningful word stems from a filename."""
        name = filename.replace(".py", "")
        parts = name.split("_")
        # Return all 2+ word subsequences
        stems = set()
        for length in range(2, len(parts) + 1):
            for start in range(len(parts) - length + 1):
                stems.add("_".join(parts[start:start + length]))
        return stems

    for i, file_a in enumerate(files):
        stems_a = get_stems(file_a)
        for file_b in files[i + 1:]:
            stems_b = get_stems(file_b)
            shared = stems_a & stems_b
            if shared:
                longest = max(shared, key=len)
                links.append({
                    "from_file": file_a,
                    "to_file": file_b,
                    "transition": "name_similarity",
                    "evidence": f"Shared stem: '{longest}'",
                    "source": "name",
                    "shared_stem": longest,
                })

    return links


def cluster_into_families(all_links, timelines):
    """Cluster files into families based on detected links.

    Uses union-find to group files that are transitively connected.
    """
    # Union-find
    parent = {}

    def find(x):
        if x not in parent:
            parent[x] = x
        if parent[x] != x:
            parent[x] = find(parent[x])
        return parent[x]

    def union(a, b):
        pa, pb = find(a), find(b)
        if pa != pb:
            parent[pa] = pb

    # Score links — idea graph links are strongest, temporal alone is NOT enough
    pair_sources = defaultdict(set)  # track which signal types support each pair
    pair_links = defaultdict(list)

    for link in all_links:
        pair = tuple(sorted([link["from_file"], link["to_file"]]))
        pair_sources[pair].add(link["source"])
        pair_links[pair].append(link)

    # Merge rules (strict to avoid false families):
    # - idea_graph alone: YES (strongest signal — concept evolution explicitly links files)
    # - temporal + name: YES (files succeed each other AND have similar names)
    # - name containment: YES (one filename contains the other: geological_reader_v1 ⊂ geological_reader)
    # - temporal alone: NO (batch edits create false links)
    # - name overlap alone: NO (shared stems can be coincidental)
    for pair, sources in pair_sources.items():
        should_merge = False
        if "idea_graph" in sources:
            should_merge = True
        elif "temporal" in sources and "name" in sources:
            should_merge = True
        elif "name" in sources:
            # Check for containment: one file's base name is a substring of the other
            a_base = pair[0].replace(".py", "")
            b_base = pair[1].replace(".py", "")
            if a_base in b_base or b_base in a_base:
                should_merge = True
        if should_merge:
            union(pair[0], pair[1])

    # Build families
    families = defaultdict(set)
    all_files = set(timelines.keys())
    for f in all_files:
        families[find(f)].add(f)

    # Format output
    result = []
    standalone = []

    for root, members in families.items():
        if len(members) == 1:
            standalone.append(list(members)[0])
            continue

        # Order members by first appearance
        ordered = sorted(members, key=lambda f: get_file_active_range(timelines.get(f, []))[0] or 9999)

        # Determine latest version (most recent last modification)
        latest = max(members, key=lambda f: get_file_active_range(timelines.get(f, []))[1] or 0)

        # Build version list
        versions = []
        for f in ordered:
            first, last = get_file_active_range(timelines.get(f, []))
            status = "current" if f == latest else "superseded"

            # Find evidence for this file's relationship
            evidence_parts = []
            pair_key_candidates = [tuple(sorted([f, other])) for other in members if other != f]
            for pk in pair_key_candidates:
                for link in pair_links.get(pk, []):
                    if link["evidence"]:
                        evidence_parts.append(link["evidence"])

            versions.append({
                "file": f,
                "status": status,
                "active_msgs": f"{first}-{last}" if first and last else "unknown",
                "events": len(timelines.get(f, [])),
                "evidence": evidence_parts[0] if evidence_parts else "",
            })

        # Generate concept name from the latest file
        concept = latest.replace(".py", "").replace("_", " ").title()

        result.append({
            "concept": concept,
            "versions": versions,
            "latest": latest,
            "total_versions": len(versions),
        })

    # Sort families by number of versions (most interesting first)
    result.sort(key=lambda x: -x["total_versions"])

    return result, sorted(standalone)


def main():
    OUT_DIR = get_session_output_dir()

    print("=" * 60)
    print("File Genealogy Detector")
    print("=" * 60)
    print(f"Output dir: {OUT_DIR}")
    print()

    # Load data
    thread_data = load_json(OUT_DIR / "thread_extractions.json")
    idea_graph = load_json(OUT_DIR / "idea_graph.json")

    if not thread_data:
        print("ERROR: thread_extractions.json required")
        return

    # Step 1: Build file timelines
    timelines = build_file_timelines(thread_data)
    print(f"Files with activity: {len(timelines)}")

    # Step 2: Detect links from idea graph
    idea_files = build_idea_file_links(idea_graph) if idea_graph else {}
    idea_links = detect_idea_graph_lineage(idea_graph, idea_files) if idea_graph else []
    print(f"Idea graph links: {len(idea_links)}")

    # Step 3: Detect temporal succession
    temporal_links = detect_temporal_succession(timelines)
    print(f"Temporal succession links: {len(temporal_links)}")

    # Step 4: Detect name similarity
    name_links = detect_name_similarity(timelines)
    print(f"Name similarity links: {len(name_links)}")

    # Step 5: Cluster into families
    all_links = idea_links + temporal_links + name_links
    print(f"Total links: {len(all_links)}")
    print()

    families, standalone = cluster_into_families(all_links, timelines)

    # Output
    output = {
        "session_id": SESSION_ID,
        "generated_at": datetime.now().isoformat(),
        "file_families": families,
        "standalone_files": standalone,
        "total_concepts": len(families) + len(standalone),
        "total_files": len(timelines),
        "reduction": f"{len(timelines)} files -> {len(families) + len(standalone)} concepts",
        "links_detected": {
            "idea_graph": len(idea_links),
            "temporal": len(temporal_links),
            "name_similarity": len(name_links),
            "total": len(all_links),
        },
    }

    out_path = OUT_DIR / "file_genealogy.json"
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2)

    # Print summary
    print("=== FILE FAMILIES ===")
    for fam in families:
        print(f"\n  [{fam['concept']}] ({fam['total_versions']} versions)")
        for v in fam["versions"]:
            icon = "*" if v["status"] == "current" else " "
            print(f"    {icon} {v['file']} [{v['status']}] msgs {v['active_msgs']} ({v['events']} events)")

    print(f"\n=== STANDALONE FILES ({len(standalone)}) ===")
    for f in standalone:
        first, last = get_file_active_range(timelines.get(f, []))
        print(f"    {f} msgs {first}-{last}")

    print(f"\n{output['reduction']}")
    print(f"Output: {out_path}")


if __name__ == "__main__":
    main()
