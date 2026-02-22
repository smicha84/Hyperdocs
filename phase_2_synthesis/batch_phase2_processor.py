#!/usr/bin/env python3
"""
Batch Phase 2 Processor - Generates idea_graph.json, synthesis.json, grounded_markers.json
from Phase 1 outputs (thread_extractions, geological_notes, semantic_primitives, explorer_notes, session_metadata).
"""
import json
import os
import sys
from datetime import datetime

BASE = os.path.dirname(os.path.abspath(__file__))

def load_json(path):
    try:
        with open(path, 'r') as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError, ValueError):
        return None

def get_session_id(summary, threads, geo, prims, explorer):
    for d in [summary, threads, geo, prims, explorer]:
        if d and 'session_id' in d:
            return d['session_id']
    return "unknown"

def extract_key_messages(threads):
    """Get the most important messages from thread extractions (handles both formats)."""
    if not threads:
        return []

    # Format 1: extractions list
    if 'extractions' in threads:
        extractions = threads['extractions']
        key = []
        for e in extractions:
            score = e.get('filter_score', 0) or 0
            markers = e.get('markers', {})
            if isinstance(markers, dict):
                is_pivot = markers.get('is_pivot', False)
                is_breakthrough = markers.get('is_breakthrough', False)
                is_failure = markers.get('is_failure', False)
                if score >= 5 or is_pivot or is_breakthrough or is_failure:
                    key.append(e)
        if not key:
            key = extractions[-3:] if len(extractions) >= 3 else extractions
        return key

    # Format 2: threads as dict with category sub-keys (CURRENT canonical format)
    # e.g. {"threads": {"ideas": {"description": "...", "entries": [{"msg_index": N, "content": "...", "significance": "high"}]}}}
    if 'threads' in threads:
        thread_data = threads['threads']
        if isinstance(thread_data, dict) and thread_data:
            # Check if it's the canonical dict-of-categories format
            first_val = next(iter(thread_data.values()), None)
            if isinstance(first_val, dict) and ('entries' in first_val or 'description' in first_val):
                nodes_from_threads = []
                for category, cat_data in thread_data.items():
                    if not isinstance(cat_data, dict):
                        continue
                    entries = cat_data.get('entries', [])
                    desc = cat_data.get('description', category)
                    for entry in entries:
                        if not isinstance(entry, dict):
                            continue
                        content = entry.get('content', '')
                        if content and len(content) > 20:
                            msg_idx = entry.get('msg_index', 0)
                            sig = entry.get('significance', 'medium')
                            nodes_from_threads.append({
                                'index': msg_idx,
                                'role': category,
                                'content_preview': content[:200],
                                'filter_score': 10 if sig == 'high' else 5,
                                'markers': {},
                                'narrative_annotation': content,
                                '_thread_label': f"{category}: {content[:60]}",
                            })
                # Sort by significance (high first), then take top entries
                nodes_from_threads.sort(key=lambda x: -x['filter_score'])
                return nodes_from_threads[:8]

        # Format 3: threads as flat list with sub_threads (old batch format)
        if isinstance(thread_data, list):
            nodes_from_threads = []
            for t in thread_data:
                label = t.get('label', '') or t.get('description', '')[:80]
                desc = t.get('description', '') or t.get('outcome', '') or ''
                user_intent = t.get('user_intent', '')
                outcome = t.get('outcome', '')
                indices = t.get('message_indices', [])
                start_idx = indices[0] if indices else 0
                end_idx = indices[-1] if indices else 0
                files = t.get('key_files_referenced', [])

                nodes_from_threads.append({
                    'index': start_idx,
                    'role': 'thread',
                    'content_preview': desc[:200],
                    'filter_score': 10,
                    'markers': {},
                    'narrative_annotation': desc,
                    'threads': {
                        'user_ideas': {'idea': user_intent, 'evolution': 'expressing_goal'} if user_intent else None,
                        'plans': {'detected': bool(outcome), 'content': outcome}
                    },
                    '_thread_label': label,
                    '_files': files,
                    '_outcome': outcome,
                    '_end_idx': end_idx
                })

                for st in t.get('sub_threads', []):
                    st_desc = st.get('description', '')
                    st_label = st.get('label', '')
                    st_indices = st.get('message_indices', [])
                    if st_desc and len(st_desc) > 40:
                        nodes_from_threads.append({
                            'index': st_indices[0] if st_indices else 0,
                            'role': 'sub_thread',
                            'content_preview': st_desc[:200],
                            'filter_score': 5,
                            'markers': {},
                            'narrative_annotation': st_desc,
                            '_thread_label': st_label
                        })

            return nodes_from_threads[:6]

    return []

def extract_narrative(threads):
    if not threads:
        return {}
    arc = threads.get('narrative_arc', {})
    if isinstance(arc, dict):
        return arc
    return {'summary': str(arc)}

def extract_geo_character(geo):
    if not geo:
        return ""
    sc = geo.get('session_character', '')
    if isinstance(sc, dict):
        return sc.get('productivity_assessment', '') or sc.get('dominant_activity', '') or json.dumps(sc)
    if isinstance(sc, str):
        return sc
    # Check geological_metaphor
    gm = geo.get('geological_metaphor', '')
    if gm:
        return gm
    macro = geo.get('macro', [])
    if macro:
        m = macro[0] if isinstance(macro, list) else macro
        return m.get('session_geology', '') or m.get('arc', '') or m.get('geological_metaphor', '') or ''
    return ""

def extract_primitives_summary(prims):
    if not prims:
        return {}
    dists = prims.get('distributions', {})
    summary = prims.get('session_primitive_summary', prims.get('summary_statistics', {}))
    # Build distributions from tagged_messages if not present
    if not dists and 'tagged_messages' in prims:
        from collections import Counter
        for field in ['action_vector', 'confidence_signal', 'emotional_tenor', 'intent_marker']:
            vals = [m.get(field, '') for m in prims['tagged_messages'] if m.get(field)]
            if vals:
                dists[field] = dict(Counter(vals))
    return {'distributions': dists, 'summary': summary}

def extract_observations(explorer):
    if not explorer:
        return [], []
    obs = explorer.get('observations', [])
    # Current canonical format has 'verification' dict, not 'warnings' list
    warnings = explorer.get('warnings', [])
    if not warnings:
        verification = explorer.get('verification', {})
        if isinstance(verification, dict):
            # Extract issues from verification sub-keys as warnings
            for key in ['phase0_issues_found', 'thread_analyst_issues',
                        'geological_reader_issues', 'primitives_tagger_issues']:
                issues = verification.get(key, [])
                if isinstance(issues, list):
                    warnings.extend(issues)
    if isinstance(obs, list) and obs:
        if isinstance(obs[0], dict):
            return obs, warnings
        elif isinstance(obs[0], str):
            return [{'description': o} for o in obs], warnings
    return [], warnings

def extract_stats(summary):
    if not summary:
        return {}
    stats = summary.get('session_stats', summary)
    return {
        'total_messages': stats.get('total_messages', 0),
        'user_messages': stats.get('user_messages', 0),
        'assistant_messages': stats.get('assistant_messages', 0),
        'tier_distribution': stats.get('tier_distribution', {}),
        'total_input_tokens': stats.get('total_input_tokens', 0),
        'total_output_tokens': stats.get('total_output_tokens', 0),
        'file_mention_counts': stats.get('file_mention_counts', {}),
        'error_count': stats.get('error_count', 0),
        'frustration_peaks': stats.get('frustration_peaks', []),
    }

def build_nodes_from_geo(geo):
    """Build nodes from geological notes micro entries."""
    if not geo:
        return []
    nodes = []
    micro = geo.get('micro', [])
    if isinstance(micro, list):
        for m in micro[:6]:
            idx = m.get('index', 0)
            sig = m.get('significance', '') or m.get('description', '') or ''
            typ = m.get('type', 'observation')
            density = m.get('density', 'medium')
            if sig and len(sig) > 20:
                nodes.append({
                    'index': idx,
                    'role': 'geological',
                    'content_preview': sig[:200],
                    'filter_score': 8 if density in ['high', 'very_high'] else 4,
                    'markers': {},
                    'narrative_annotation': sig,
                    '_geo_type': typ,
                    '_density': density
                })
    return nodes

def build_nodes_from_prims(prims):
    """Build nodes from semantic primitives with friction/decision content."""
    if not prims:
        return []
    # Handle both formats: 'tagged_messages' (canonical) and 'primitives' (old)
    msgs = prims.get('tagged_messages', [])
    if not msgs:
        msgs = prims.get('primitives', [])
    if not msgs:
        return []
    nodes = []
    for p in msgs:
        # Canonical format has fields directly; old format nests under 'primitives'
        prim_data = p.get('primitives', p)
        friction = prim_data.get('friction_log', '')
        decision = prim_data.get('decision_trace', '')
        if friction or decision:
            desc = decision or friction
            nodes.append({
                'index': p.get('msg_index', p.get('index', 0)),
                'role': p.get('role', 'unknown'),
                'content_preview': desc[:200],
                'filter_score': 8,
                'markers': {},
                'narrative_annotation': desc,
                '_prim_action': prim_data.get('action_vector', prim_data.get('action', '')),
                '_prim_confidence': prim_data.get('confidence_signal', prim_data.get('confidence', '')),
            })
    return nodes

def build_nodes(threads, geo, prims, explorer):
    """Build idea graph nodes from Phase 1 data, using multiple sources."""
    key_msgs = extract_key_messages(threads)

    # If no key messages from threads, try geo and primitives
    if not key_msgs:
        key_msgs = build_nodes_from_geo(geo)
    if not key_msgs:
        key_msgs = build_nodes_from_prims(prims)

    # If still no messages, create a minimal set from explorer observations
    if not key_msgs:
        observations, _ = extract_observations(explorer)
        for i, obs in enumerate(observations[:3]):
            desc = obs.get('description', '') if isinstance(obs, dict) else str(obs)
            if desc and len(desc) > 20:
                key_msgs.append({
                    'index': i,
                    'role': 'explorer',
                    'content_preview': desc[:200],
                    'filter_score': 5,
                    'markers': {},
                    'narrative_annotation': desc
                })

    # If still nothing, create a single node from session summary
    if not key_msgs:
        key_msgs = [{
            'index': 0,
            'role': 'summary',
            'content_preview': 'Session processed with minimal extractable signal',
            'filter_score': 1,
            'markers': {},
            'narrative_annotation': 'Session processed with minimal extractable signal'
        }]

    nodes = []
    for i, msg in enumerate(key_msgs):
        idx = msg.get('index', i)
        preview = msg.get('content_preview', '') or ''
        markers = msg.get('markers', {})

        narrative = ''
        if isinstance(markers, dict):
            narrative = markers.get('narrative', '') or markers.get('narrative_annotation', '') or ''
        narr_ann = msg.get('narrative_annotation', '')
        thread_label = msg.get('_thread_label', '')

        label = thread_label or narrative or narr_ann or preview[:80] or f"Message {idx}"

        # Confidence from primitives (handle both canonical and old format)
        conf = 'working'
        prim_msgs = []
        if prims:
            prim_msgs = prims.get('tagged_messages', prims.get('primitives', []))
        for p in prim_msgs:
            p_idx = p.get('msg_index', p.get('index', -1))
            if p_idx == idx:
                prim_data = p.get('primitives', p)
                conf = prim_data.get('confidence_signal', 'working')
                break
        # Or from the message itself
        if msg.get('_prim_confidence'):
            conf = msg['_prim_confidence']

        # Maturity
        maturity = 'exploration'
        if isinstance(markers, dict):
            if markers.get('is_breakthrough'):
                maturity = 'discovered'
            elif markers.get('is_pivot'):
                maturity = 'decided'
        thread_data = msg.get('threads', {})
        if thread_data and isinstance(thread_data, dict):
            user_ideas = thread_data.get('user_ideas')
            if user_ideas and isinstance(user_ideas, dict):
                evol = user_ideas.get('evolution', '')
                if evol == 'expressing_goal':
                    maturity = 'decided'
            plans = thread_data.get('plans')
            if plans and isinstance(plans, dict) and plans.get('detected'):
                maturity = 'implemented'

        desc = narr_ann or narrative or preview or f"Key message at index {idx}"

        nodes.append({
            "id": f"N{i+1:02d}",
            "label": label[:100],
            "description": desc[:500],
            "message_index": idx,
            "confidence": conf,
            "maturity": maturity,
            "source": f"thread_extractions:idx-{idx}"
        })

    return nodes

def build_edges(nodes):
    edges = []
    for i in range(len(nodes) - 1):
        n1 = nodes[i]
        n2 = nodes[i+1]
        if 'pivot' in n2.get('label', '').lower() or 'redirect' in n2.get('description', '').lower():
            edge_type = "pivoted"
        elif 'correct' in n2.get('description', '').lower():
            edge_type = "constrained"
        elif n2.get('maturity') == 'discovered':
            edge_type = "concretized"
        else:
            edge_type = "evolved"
        edges.append({
            "from": n1["id"],
            "to": n2["id"],
            "type": edge_type,
            "label": f"Progression from {n1['label'][:40]} to {n2['label'][:40]}",
            "evidence": f"Sequential message progression idx {n1['message_index']} -> {n2['message_index']}"
        })
    return edges

def build_idea_graph(session_id, threads, geo, prims, explorer, summary):
    nodes = build_nodes(threads, geo, prims, explorer)
    edges = build_edges(nodes)
    stats = extract_stats(summary)
    pivot = None
    if threads:
        extractions = threads.get('extractions', [])
        for e in extractions:
            m = e.get('markers', {})
            if isinstance(m, dict) and m.get('is_pivot'):
                pivot = f"msg_{e.get('index', 0)}"
                break
    return {
        "session_id": session_id,
        "generated_at": "2026-02-08T00:00:00Z",
        "generator": "Phase 2 - Idea Evolution Graph (Opus 4.6)",
        "source_files": ["thread_extractions.json", "geological_notes.json", "semantic_primitives.json", "explorer_notes.json", "session_metadata.json"],
        "metadata": {
            "total_nodes": len(nodes),
            "total_edges": len(edges),
            "session_id": session_id,
            "session_span_days": 0,
            "context_reinjections": 0,
            "primary_pivot_point": pivot
        },
        "nodes": nodes,
        "edges": edges
    }

def build_synthesis(session_id, threads, geo, prims, explorer, summary):
    stats = extract_stats(summary)
    arc = extract_narrative(threads)
    geo_char = extract_geo_character(geo)
    prim_sum = extract_primitives_summary(prims)
    observations, warnings = extract_observations(explorer)

    total_msgs = stats.get('total_messages', 0)
    inp_tok = stats.get('total_input_tokens', 0)
    out_tok = stats.get('total_output_tokens', 0)
    ratio = f"{inp_tok // max(out_tok, 1)}:1" if out_tok > 0 else "N/A"
    tier_dist = stats.get('tier_distribution', {})
    skip_count = tier_dist.get('1_skip', 0)
    files = stats.get('file_mention_counts', {})

    arc_text = ""
    if isinstance(arc, dict):
        phases = [v for v in arc.values() if isinstance(v, str)]
        arc_text = " ".join(phases)

    # Thread-based narrative
    thread_narrative = ""
    if threads and 'threads' in threads:
        tl = threads['threads']
        if isinstance(tl, list):
            descs = [t.get('description', '')[:200] for t in tl if t.get('description')]
            thread_narrative = " | ".join(descs)

    analytical = [
        f"Session with {total_msgs} messages. {inp_tok:,} input tokens, {out_tok:,} output tokens ({ratio} read-to-write ratio).",
        f"Tier distribution: {json.dumps(tier_dist)}. {skip_count} of {total_msgs} messages are tier-1 skip (tool calls).",
        arc_text or thread_narrative or geo_char or "Session arc details available in thread_extractions.json.",
        f"Files referenced: {', '.join(list(files.keys())[:8]) if files else 'none identified'}."
    ]

    interpretive = []
    for obs in observations[:4]:
        desc = obs.get('description', '') if isinstance(obs, dict) else str(obs)
        if desc:
            interpretive.append(desc[:500])
    if not interpretive:
        interpretive = ["No significant patterns identified beyond standard session flow."]

    creative = [geo_char] if geo_char else ["Session character captured in geological_notes.json."]

    critical = []
    if isinstance(warnings, list):
        for w in warnings[:4]:
            if isinstance(w, dict):
                critical.append(f"{w.get('title', 'Warning')}: {w.get('description', '')}"[:500])
            elif isinstance(w, str):
                critical.append(w[:500])
    if not critical:
        critical = ["No significant issues identified in this session."]

    integrative = ["This session contributes to the broader project history. Cross-session links are captured in the idea graph."]
    what_matters = ""
    if explorer and isinstance(explorer, dict):
        what_matters = explorer.get('what_matters_most', '')
    if what_matters:
        integrative.append(what_matters)

    findings = []
    key_msgs = extract_key_messages(threads)
    for msg in key_msgs[:3]:
        narr = msg.get('narrative_annotation', '') or ''
        markers = msg.get('markers', {})
        narrative = markers.get('narrative', '') if isinstance(markers, dict) else ''
        finding_text = narr or narrative
        if finding_text:
            findings.append({
                "finding": finding_text[:300],
                "evidence": f"thread_extractions:idx-{msg.get('index', 0)}",
                "significance": "high" if (msg.get('filter_score', 0) or 0) > 10 else "medium"
            })
    # Also extract from threads format
    if not findings and threads and 'threads' in threads:
        tl = threads['threads']
        if isinstance(tl, list):
            for t in tl[:3]:
                outcome = t.get('outcome', '') or t.get('description', '')
                if outcome:
                    findings.append({
                        "finding": outcome[:300],
                        "evidence": f"thread_extractions:thread-{t.get('thread_id', 'T1')}",
                        "significance": "medium"
                    })
    if not findings:
        findings.append({"finding": "Session processed without notable findings beyond standard workflow.", "evidence": "session_metadata.json", "significance": "low"})

    prim_summary = prim_sum.get('summary', {})
    dom_action = prim_summary.get('dominant_action', 'unknown') if isinstance(prim_summary, dict) else 'unknown'
    dom_conf = prim_summary.get('dominant_confidence', 'unknown') if isinstance(prim_summary, dict) else 'unknown'
    dom_emo = prim_summary.get('dominant_emotion', 'unknown') if isinstance(prim_summary, dict) else 'unknown'
    frustration = stats.get('frustration_peaks', [])
    emo_traj = "No frustration peaks." if not frustration else f"Frustration peaks at: {frustration}"

    return {
        "session_id": session_id,
        "generated_at": "2026-02-08T00:00:00Z",
        "generator": "Phase 2 - Multi-Pass Synthesis (Opus 4.6)",
        "source_files": ["thread_extractions.json", "geological_notes.json", "semantic_primitives.json", "explorer_notes.json", "session_metadata.json"],
        "passes": {
            "pass_1_analytical": {"temperature": 0.3, "label": "What happened factually", "content": [c for c in analytical if c]},
            "pass_2_interpretive": {"temperature": 0.5, "label": "What patterns emerge", "content": interpretive},
            "pass_3_creative": {"temperature": 0.7, "label": "What metaphors or analogies capture the session's essence", "content": creative},
            "pass_4_critical": {"temperature": 0.7, "label": "What was missed, what went wrong", "content": critical},
            "pass_5_integrative": {"temperature": 0.7, "label": "How does this connect to the broader project", "content": integrative}
        },
        "key_findings": findings,
        "session_character": {
            "primary_arc": arc_text[:200] or thread_narrative[:200] or "See thread_extractions.json for narrative arc",
            "emotional_trajectory": emo_traj,
            "dominant_action": dom_action,
            "dominant_confidence": dom_conf,
            "dominant_emotion": dom_emo,
            "work_pattern": f"{total_msgs} messages, {ratio} input/output ratio",
            "token_signature": f"{inp_tok:,} input / {out_tok:,} output"
        },
        "cross_session_links": []
    }

def build_markers(session_id, threads, geo, prims, explorer, summary):
    markers = []
    observations, warnings = extract_observations(explorer)
    stats = extract_stats(summary)
    marker_id = 1

    # From extractions format
    if threads and 'extractions' in threads:
        for e in threads['extractions']:
            m = e.get('markers', {})
            if not isinstance(m, dict):
                continue
            narr = e.get('narrative_annotation', '') or m.get('narrative', '') or ''
            if m.get('is_pivot') and narr:
                markers.append({"marker_id": f"GM-{marker_id:03d}", "category": "decision", "claim": narr[:300], "evidence": f"thread_extractions:idx-{e.get('index', 0)}, is_pivot=true", "confidence": 0.85, "actionable_guidance": "This pivot point represents a direction change."})
                marker_id += 1
            if m.get('is_breakthrough') and narr:
                markers.append({"marker_id": f"GM-{marker_id:03d}", "category": "architecture", "claim": narr[:300], "evidence": f"thread_extractions:idx-{e.get('index', 0)}, is_breakthrough=true", "confidence": 0.85, "actionable_guidance": "This breakthrough represents a key insight."})
                marker_id += 1
            if m.get('is_failure') and narr:
                markers.append({"marker_id": f"GM-{marker_id:03d}", "category": "risk", "claim": narr[:300], "evidence": f"thread_extractions:idx-{e.get('index', 0)}, is_failure=true", "confidence": 0.80, "actionable_guidance": "This failure should be tracked to prevent recurrence."})
                marker_id += 1

    # From threads format (canonical dict or old list)
    if threads and 'threads' in threads:
        tl = threads['threads']
        # Canonical dict format: {"ideas": {"description": "...", "entries": [...]}, ...}
        if isinstance(tl, dict):
            for category, cat_data in tl.items():
                if not isinstance(cat_data, dict):
                    continue
                entries = cat_data.get('entries', [])
                desc = cat_data.get('description', category)
                # Add a marker for each high-significance entry
                for entry in entries:
                    if not isinstance(entry, dict):
                        continue
                    content = entry.get('content', '')
                    sig = entry.get('significance', 'medium')
                    if content and sig == 'high':
                        cat_map = {"ideas": "architecture", "reactions": "behavior", "software": "architecture",
                                   "code": "architecture", "plans": "decision", "behavior": "behavior"}
                        markers.append({"marker_id": f"GM-{marker_id:03d}", "category": cat_map.get(category, "behavior"),
                                        "claim": content[:300],
                                        "evidence": f"thread_extractions:{category}:msg_{entry.get('msg_index', 0)}",
                                        "confidence": 0.85,
                                        "actionable_guidance": f"High-significance {category} observation."})
                        marker_id += 1
                # Add a summary marker per non-empty category
                if entries and desc and len(desc) > 10:
                    markers.append({"marker_id": f"GM-{marker_id:03d}", "category": "architecture",
                                    "claim": f"{category}: {desc} ({len(entries)} entries)",
                                    "evidence": f"thread_extractions:{category}",
                                    "confidence": 0.80,
                                    "actionable_guidance": f"Thread category with {len(entries)} entries."})
                    marker_id += 1
        # Old list format
        elif isinstance(tl, list):
            for t in tl[:3]:
                desc = t.get('description', '')
                outcome = t.get('outcome', '')
                files = t.get('key_files_referenced', [])
                if desc and len(desc) > 40:
                    markers.append({"marker_id": f"GM-{marker_id:03d}", "category": "architecture", "claim": desc[:300], "evidence": f"thread_extractions:thread-{t.get('thread_id', 'T')}", "confidence": 0.80, "actionable_guidance": outcome[:200] if outcome else "See thread details."})
                    marker_id += 1
                if files:
                    markers.append({"marker_id": f"GM-{marker_id:03d}", "category": "architecture", "claim": f"Thread referenced {len(files)} files: {', '.join(files[:5])}", "evidence": f"thread_extractions:thread-{t.get('thread_id', 'T')}:key_files", "confidence": 0.90, "actionable_guidance": "These files were the focus of this thread's work."})
                    marker_id += 1

    # From explorer observations (canonical has 'observation', old has 'description')
    for obs in observations[:3]:
        if isinstance(obs, dict):
            desc = obs.get('observation', obs.get('description', ''))
            if desc and len(desc) > 50:
                cat = obs.get('category', 'behavior')
                if cat in ['architecture_discovery', 'file_archaeology']:
                    cat = 'architecture'
                elif cat in ['claude_behavior', 'user_behavior']:
                    cat = 'behavior'
                elif cat in ['signal_analysis', 'session_structure']:
                    cat = 'architecture'
                else:
                    cat = 'behavior'
                sig = obs.get('significance', '')
                markers.append({"marker_id": f"GM-{marker_id:03d}", "category": cat, "claim": desc[:300], "evidence": f"explorer_notes:{obs.get('obs_id', 'observation')}", "confidence": 0.75 if obs.get('confidence') == 'medium' else 0.85, "actionable_guidance": sig[:200] if isinstance(sig, str) and sig else 'See explorer_notes for details.'})
                marker_id += 1

    # From warnings
    for w in warnings[:2]:
        if isinstance(w, dict) and w.get('description'):
            markers.append({"marker_id": f"GM-{marker_id:03d}", "category": "risk", "claim": w.get('description', '')[:300], "evidence": f"explorer_notes:{w.get('warning_id', 'warning')}", "confidence": 0.80, "actionable_guidance": "Monitor for this issue in future sessions."})
            marker_id += 1

    # From behavior patterns
    if threads and 'claude_behavior_patterns' in threads:
        bp = threads['claude_behavior_patterns']
        if isinstance(bp, dict):
            for key, desc in list(bp.items())[:2]:
                if isinstance(desc, str) and len(desc) > 30:
                    markers.append({"marker_id": f"GM-{marker_id:03d}", "category": "behavior", "claim": f"{key}: {desc}"[:300], "evidence": f"thread_extractions:claude_behavior_patterns:{key}", "confidence": 0.75, "actionable_guidance": "Track this behavioral pattern across sessions."})
                    marker_id += 1

    # Ensure at least 3 markers
    if len(markers) < 3:
        files = stats.get('file_mention_counts', {})
        if files:
            markers.append({"marker_id": f"GM-{marker_id:03d}", "category": "architecture", "claim": f"Session referenced {len(files)} files: {', '.join(list(files.keys())[:5])}", "evidence": "session_metadata:file_mention_counts", "confidence": 0.90, "actionable_guidance": "These files were the focus of this session's work."})
            marker_id += 1
        tier = stats.get('tier_distribution', {})
        total = stats.get('total_messages', 0)
        skip = tier.get('1_skip', 0)
        if total > 0:
            markers.append({"marker_id": f"GM-{marker_id:03d}", "category": "behavior", "claim": f"Session had {total} messages with {skip} tier-1 skip ({100*skip//max(total,1)}% noise). {'Reading-heavy' if stats.get('total_input_tokens',0) > 10*stats.get('total_output_tokens',1) else 'Balanced'} session.", "evidence": "session_metadata:session_stats", "confidence": 0.90, "actionable_guidance": "Tier distribution useful for batch processing cost estimation."})
            marker_id += 1
        # Geological character as marker
        geo_char = extract_geo_character(geo) if geo else ''
        if geo_char and len(geo_char) > 40:
            markers.append({"marker_id": f"GM-{marker_id:03d}", "category": "behavior", "claim": geo_char[:300], "evidence": "geological_notes:session_character", "confidence": 0.75, "actionable_guidance": "Session character provides context for interpreting results."})
            marker_id += 1

    return {
        "session_id": session_id,
        "generated_at": "2026-02-08T00:00:00Z",
        "generator": "Phase 2 - Grounded Markers (Opus 4.6)",
        "source_files": ["thread_extractions.json", "geological_notes.json", "semantic_primitives.json", "explorer_notes.json", "session_metadata.json"],
        "total_markers": len(markers),
        "markers": markers
    }

def process_session(session_dir, force=False):
    sid = os.path.basename(session_dir).replace('session_', '')
    ig = os.path.join(session_dir, 'idea_graph.json')
    sy = os.path.join(session_dir, 'synthesis.json')
    gm = os.path.join(session_dir, 'grounded_markers.json')
    if not force and os.path.exists(ig) and os.path.exists(sy) and os.path.exists(gm):
        return 'skip'

    threads = load_json(os.path.join(session_dir, 'thread_extractions.json'))
    geo = load_json(os.path.join(session_dir, 'geological_notes.json'))
    prims = load_json(os.path.join(session_dir, 'semantic_primitives.json'))
    explorer = load_json(os.path.join(session_dir, 'explorer_notes.json'))
    summary = load_json(os.path.join(session_dir, 'session_metadata.json'))

    if not any([threads, geo, prims, explorer, summary]):
        print(f"  FAIL {sid}: no Phase 1 files found")
        return 'fail'

    session_id = get_session_id(summary, threads, geo, prims, explorer)
    idea_graph = build_idea_graph(session_id, threads, geo, prims, explorer, summary)
    synthesis = build_synthesis(session_id, threads, geo, prims, explorer, summary)
    markers_data = build_markers(session_id, threads, geo, prims, explorer, summary)

    with open(ig, 'w') as f:
        json.dump(idea_graph, f, indent=2)
    with open(sy, 'w') as f:
        json.dump(synthesis, f, indent=2)
    with open(gm, 'w') as f:
        json.dump(markers_data, f, indent=2)

    print(f"  DONE {sid}: {idea_graph['metadata']['total_nodes']} nodes, {len(markers_data['markers'])} markers")
    return 'done'

def main():
    force = '--force' in sys.argv
    sessions = [s for s in sys.argv[1:] if s != '--force']
    if not sessions:
        print("Usage: python3 batch_phase2_processor.py [--force] session_id1 session_id2 ...")
        sys.exit(1)

    done = skip = fail = 0
    for sid in sessions:
        session_dir = os.path.join(BASE, f"session_{sid}")
        if not os.path.isdir(session_dir):
            print(f"  MISS {sid}: directory not found")
            fail += 1
            continue
        result = process_session(session_dir, force=force)
        if result == 'done':
            done += 1
        elif result == 'skip':
            print(f"  SKIP {sid}")
            skip += 1
        else:
            fail += 1

    print(f"\nResults: {done} done, {skip} skipped, {fail} failed")

if __name__ == '__main__':
    main()
