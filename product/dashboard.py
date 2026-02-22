#!/usr/bin/env python3
"""
Hyperdocs Dashboard — Static HTML generator.

Reads pipeline outputs and generates a single HTML file showing:
1. Pipeline status (which phases are done)
2. File genealogy (file families and standalone files)
3. Credibility scores (per-file ground truth results)
4. Key findings (iron rules, frictions, decisions)
5. Settings and config

No server. Opens directly in browser.
"""
import json
import os
import subprocess
import sys
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
try:
    from config import OUTPUT_DIR as OUTPUT_BASE, REPO_ROOT as HYPERDOCS_ROOT
except ImportError:
    HYPERDOCS_ROOT = Path(__file__).resolve().parent.parent
    OUTPUT_BASE = Path(os.getenv("HYPERDOCS_OUTPUT_DIR", str(HYPERDOCS_ROOT / "output")))


def find_latest_session():
    """Find the most recently modified session output directory."""
    if not OUTPUT_BASE.exists():
        return None
    session_dirs = sorted(
        [d for d in OUTPUT_BASE.iterdir() if d.is_dir() and d.name.startswith("session_")],
        key=lambda d: d.stat().st_mtime,
        reverse=True,
    )
    return session_dirs[0] if session_dirs else None


def load_json_safe(path):
    """Load JSON or return empty dict. Marks missing files for dashboard display."""
    if not path.exists():
        return {"_data_missing": True, "_missing_file": path.name}
    try:
        with open(path) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {"_data_missing": True, "_missing_file": path.name}


def _normalize_markers(m):
    """Convert flat markers list to structured format if needed."""
    if "warnings" in m or "patterns" in m:
        return m
    flat = m.get("markers", [])
    if not flat:
        return m
    structured = {"warnings": [], "patterns": [], "recommendations": [], "metrics": [], "iron_rules_registry": []}
    for item in flat:
        cat = item.get("category", "behavior")
        entry = {"id": item.get("marker_id", ""), "severity": "medium", "target": item.get("target_file", ""),
                 "warning": item.get("claim", ""), "description": item.get("claim", ""),
                 "value": "", "confidence": item.get("confidence", 0.5)}
        if cat == "risk": structured["warnings"].append(entry)
        elif cat == "decision": structured["recommendations"].append(entry)
        elif cat == "architecture": structured["metrics"].append(entry)
        else: structured["patterns"].append(entry)
    return {**m, **structured}


def generate_dashboard(session_dir):
    """Generate the dashboard HTML."""
    status = load_json_safe(session_dir / "pipeline_status.json")
    summary = load_json_safe(session_dir / "session_metadata.json")
    genealogy = load_json_safe(session_dir / "file_genealogy.json")
    gt_summary = load_json_safe(session_dir / "ground_truth_summary.json")
    grounded = _normalize_markers(load_json_safe(session_dir / "grounded_markers.json"))
    discovery = load_json_safe(OUTPUT_BASE / "discovery.json")

    session_id = status.get("session_id", session_dir.name.replace("session_", ""))
    stats = summary.get("session_stats", {})
    total_msgs = stats.get("total_messages", "?")
    user_msgs = stats.get("user_messages", "?")
    asst_msgs = stats.get("assistant_messages", "?")

    # Phase status
    phases = [
        ("phase_0", "Deterministic Prep", "$0"),
        ("phase_1", "Agent Extraction", "Opus"),
        ("phase_2", "Synthesis + Genealogy", "Opus"),
        ("phase_3", "Hyperdoc Writing", "Opus"),
        ("phase_4", "Smart Insertion", "$0"),
    ]

    phase_html = ""
    for key, name, cost in phases:
        info = status.get(key, {})
        state = info.get("state", "PENDING")
        if state == "COMPLETE":
            color = "#1a3a1a"; border = "#2a5a2a"; text = "#9ece6a"; icon = "DONE"
        elif state == "FAILED":
            color = "#3a1a1a"; border = "#5a2a2a"; text = "#f7768e"; icon = "FAIL"
        elif state == "IN_PROGRESS":
            color = "#3a3a1a"; border = "#5a5a2a"; text = "#e0af68"; icon = " >> "
        else:
            color = "#1a1a1a"; border = "#2a2a2a"; text = "#555"; icon = "    "
        phase_html += f'<div style="background:{color};border:1px solid {border};border-radius:6px;padding:10px 14px;display:flex;justify-content:space-between;align-items:center"><span style="color:{text};font-weight:700">[{icon}] {name}</span><span style="color:#555;font-size:11px">{cost}</span></div>\n'

    # File genealogy
    genealogy_html = ""
    families = genealogy.get("file_families", [])
    standalone = genealogy.get("standalone_files", [])
    reduction = genealogy.get("reduction", "")

    if families:
        genealogy_html += f'<p style="color:#888;font-size:12px;margin-bottom:12px">{reduction}</p>'
        for fam in families:
            genealogy_html += f'<div style="margin-bottom:12px"><div style="color:#7aa2f7;font-weight:600;font-size:13px">{fam["concept"]} ({fam["total_versions"]} versions)</div>'
            for v in fam.get("versions", []):
                icon = "*" if v["status"] == "current" else " "
                color = "#9ece6a" if v["status"] == "current" else "#555"
                genealogy_html += f'<div style="color:{color};font-size:12px;padding-left:16px">{icon} {v["file"]} [{v["status"]}] msgs {v.get("active_msgs","?")}</div>'
            genealogy_html += '</div>'
        if standalone:
            genealogy_html += f'<div style="color:#555;font-size:11px;margin-top:8px">{len(standalone)} standalone files</div>'
    else:
        genealogy_html = '<p style="color:#555">Run Phase 2 to detect file genealogy</p>'

    # Credibility scores
    cred_html = ""
    per_file = gt_summary.get("per_file", [])
    if per_file:
        avg = gt_summary.get("average_credibility", 0)
        cred_html += f'<p style="color:#888;font-size:12px;margin-bottom:8px">Average credibility: {int(avg*100)}%</p>'
        for row in sorted(per_file, key=lambda r: -r.get("credibility", 0)):
            score = row.get("credibility", 0)
            if score >= 0.67:
                color = "#9ece6a"
            elif score >= 0.5:
                color = "#e0af68"
            else:
                color = "#f7768e"
            bar_width = max(int(score * 200), 2)
            cred_html += f'<div style="display:flex;align-items:center;gap:8px;margin:3px 0;font-size:12px"><span style="color:{color};min-width:32px;text-align:right;font-weight:700">{int(score*100)}%</span><div style="background:{color};height:8px;width:{bar_width}px;border-radius:2px"></div><span style="color:#888">{row["file"]}</span></div>'
    else:
        cred_html = '<p style="color:#555">No credibility scores available</p>'

    # Key findings
    findings_html = ""
    iron_rules = grounded.get("iron_rules_registry", [])
    warnings = grounded.get("warnings", [])
    metrics = grounded.get("metrics", [])

    if iron_rules:
        findings_html += '<div style="margin-bottom:12px"><div style="color:#f7768e;font-weight:600;font-size:13px;margin-bottom:4px">Iron Rules</div>'
        for rule in iron_rules[:5]:
            findings_html += f'<div style="color:#ccc;font-size:11px;padding-left:12px;margin:2px 0">Rule {rule.get("rule_number","?")}: {rule.get("rule","")[:80]}</div>'
        findings_html += '</div>'

    if warnings:
        findings_html += '<div style="margin-bottom:12px"><div style="color:#e0af68;font-weight:600;font-size:13px;margin-bottom:4px">Top Warnings</div>'
        for w in warnings[:5]:
            sev = w.get("severity", "?")
            findings_html += f'<div style="color:#ccc;font-size:11px;padding-left:12px;margin:2px 0">[{w.get("id","")}] [{sev}] {w.get("warning","")[:80]}</div>'
        findings_html += '</div>'

    if metrics:
        findings_html += '<div><div style="color:#73daca;font-weight:600;font-size:13px;margin-bottom:4px">Metrics</div>'
        for m in metrics[:5]:
            findings_html += f'<div style="color:#ccc;font-size:11px;padding-left:12px;margin:2px 0">[{m.get("id","")}] {m.get("description","")[:80]}: {m.get("value","")}</div>'
        findings_html += '</div>'

    if not findings_html:
        findings_html = '<p style="color:#555">Run Phase 2 for key findings</p>'

    # Realtime buffer stats
    buffer_file = OUTPUT_BASE / "realtime_buffer.jsonl"
    buffer_ops = 0
    buffer_files = set()
    if buffer_file.exists():
        with open(buffer_file) as f:
            for line in f:
                buffer_ops += 1
                try:
                    op = json.loads(line)
                    fp = op.get("file_path", "")
                    if fp:
                        buffer_files.add(fp)
                except json.JSONDecodeError:
                    pass

    # Build HTML
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Hyperdocs Dashboard — {session_id}</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:'SF Mono','Fira Code',monospace;background:#08080e;color:#c0c0cc;font-size:13px;line-height:1.5}}
.page{{max-width:960px;margin:0 auto;padding:24px 20px}}
h1{{color:#eee;font-size:20px;font-weight:600}}
h1 span{{color:#7aa2f7}}
.sub{{color:#555;font-size:11px;margin:2px 0 20px}}
.grid{{display:grid;grid-template-columns:1fr 1fr;gap:16px;margin:16px 0}}
.card{{background:#10101a;border:1px solid #1e1e30;border-radius:8px;padding:16px}}
.card h2{{color:#eee;font-size:14px;margin-bottom:10px;padding-bottom:6px;border-bottom:1px solid #1e1e30}}
.stats{{display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin:12px 0}}
.stat{{background:#10101a;border:1px solid #1e1e30;border-radius:6px;padding:10px;text-align:center}}
.stat .n{{font-size:20px;font-weight:700}}
.stat .l{{font-size:9px;color:#555;text-transform:uppercase;margin-top:2px}}
.footer{{text-align:center;color:#444;font-size:10px;margin-top:24px;padding-top:12px;border-top:1px solid #1e1e30}}
</style>
</head>
<body>
<div class="page">
<h1>Hyperdocs <span>Dashboard</span></h1>
<div class="sub">Session {session_id} | {total_msgs} messages ({user_msgs} user / {asst_msgs} assistant) | Generated {datetime.now().strftime('%Y-%m-%d %H:%M')}</div>

<div class="stats">
<div class="stat"><div class="n" style="color:#7aa2f7">{total_msgs}</div><div class="l">Messages</div></div>
<div class="stat"><div class="n" style="color:#9ece6a">{len(families)}</div><div class="l">File Families</div></div>
<div class="stat"><div class="n" style="color:#e0af68">{int(gt_summary.get('average_credibility',0)*100) if gt_summary else '?'}%</div><div class="l">Avg Credibility</div></div>
<div class="stat"><div class="n" style="color:#73daca">{buffer_ops}</div><div class="l">Realtime Ops</div></div>
</div>

<div class="grid">

<div class="card">
<h2>Pipeline Status</h2>
<div style="display:flex;flex-direction:column;gap:6px">
{phase_html}
</div>
</div>

<div class="card">
<h2>File Genealogy</h2>
{genealogy_html}
</div>

<div class="card">
<h2>Credibility Scores</h2>
{cred_html}
</div>

<div class="card">
<h2>Key Findings</h2>
{findings_html}
</div>

</div>

<div class="footer">
Hyperdocs 3 | {len(families)} file families | {len(standalone)} standalone | {buffer_ops} realtime operations captured across {len(buffer_files)} files
</div>

</div>
</body>
</html>"""

    dashboard_path = session_dir / "hyperdocs_dashboard.html"
    with open(dashboard_path, "w") as f:
        f.write(html)

    return dashboard_path


def main():
    session_dir = find_latest_session()
    if not session_dir:
        print("No session output found. Run 'python3 concierge.py --discover' first.")
        return

    print(f"Generating dashboard for {session_dir.name}...")
    path = generate_dashboard(session_dir)
    print(f"Dashboard: {path}")

    # Auto-open
    if sys.platform == "darwin":
        subprocess.run(["open", str(path)])
    elif sys.platform == "linux":
        subprocess.run(["xdg-open", str(path)])
    else:
        print(f"Open in browser: {path}")


if __name__ == "__main__":
    main()
