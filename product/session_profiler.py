#!/usr/bin/env python3
"""
Session Profiler — Discover and visualize Claude Code chat history.

Scans the user's chat history, profiles each session (size, message count,
date range, activity level), and generates an interactive HTML visualization.

This is part of the Hyperdocs onboarding experience — the user sees their
data before the pipeline touches it.

Usage:
    python3 session_profiler.py                    # Auto-discover + visualize
    python3 session_profiler.py --chat-dir /path   # Custom chat directory
    python3 session_profiler.py --output /path.html # Custom output location
"""
import json
import os
import sys
from pathlib import Path
from datetime import datetime, timezone
from collections import defaultdict

HYPERDOCS_ROOT = Path(__file__).resolve().parent.parent

# ── Discovery ─────────────────────────────────────────────────────────

def find_chat_history():
    """Find Claude Code chat history in standard locations."""
    candidates = [
        Path.home() / "PERMANENT_CHAT_HISTORY" / "sessions",
        Path.home() / ".claude" / "projects",
    ]
    # Also check config
    sys.path.insert(0, str(HYPERDOCS_ROOT))
    try:
        from config import CHAT_ARCHIVE_DIR
        candidates.insert(0, CHAT_ARCHIVE_DIR / "sessions")
    except ImportError:
        pass

    for d in candidates:
        if d.exists() and any(d.glob("*.jsonl")):
            return d
    return None


def profile_session(filepath):
    """Extract metadata from a single JSONL session file without reading the whole thing."""
    stat = filepath.stat()
    size_bytes = stat.st_size
    modified = datetime.fromtimestamp(stat.st_mtime)

    # Quick scan: read first and last few lines for timestamps and message counts
    first_ts = None
    last_ts = None
    user_count = 0
    assistant_count = 0
    total_lines = 0
    has_thinking = False

    try:
        with open(filepath) as f:
            for line in f:
                total_lines += 1
                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    continue

                ts_str = data.get("timestamp", "")
                if ts_str:
                    if first_ts is None:
                        first_ts = ts_str
                    last_ts = ts_str

                msg_type = data.get("type", data.get("role", ""))
                if msg_type == "user":
                    user_count += 1
                elif msg_type == "assistant":
                    assistant_count += 1

                if data.get("thinking") or data.get("has_thinking"):
                    has_thinking = True
    except (OSError, UnicodeDecodeError):
        pass

    # Parse timestamps
    start_time = None
    end_time = None
    duration_minutes = 0
    if first_ts:
        try:
            start_time = datetime.fromisoformat(first_ts.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            pass
    if last_ts:
        try:
            end_time = datetime.fromisoformat(last_ts.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            pass
    if start_time and end_time:
        duration_minutes = (end_time - start_time).total_seconds() / 60

    # Classify session size
    size_mb = size_bytes / (1024 * 1024)
    if size_mb < 0.01:
        size_class = "tiny"
    elif size_mb < 0.5:
        size_class = "small"
    elif size_mb < 5:
        size_class = "medium"
    elif size_mb < 20:
        size_class = "large"
    else:
        size_class = "mega"

    # Detect if it's a subagent session
    stem = filepath.stem
    is_agent = "_agent-" in stem or stem.startswith("agent-")

    return {
        "id": stem[:8] if not is_agent else stem,
        "full_id": stem,
        "size_bytes": size_bytes,
        "size_mb": round(size_mb, 2),
        "size_class": size_class,
        "total_lines": total_lines,
        "user_messages": user_count,
        "assistant_messages": assistant_count,
        "total_messages": user_count + assistant_count,
        "start_time": start_time.isoformat() if start_time else None,
        "end_time": end_time.isoformat() if end_time else None,
        "date": start_time.strftime("%Y-%m-%d") if start_time else modified.strftime("%Y-%m-%d"),
        "duration_minutes": round(duration_minutes),
        "has_thinking": has_thinking,
        "is_agent": is_agent,
        "modified": modified.isoformat(),
    }


def profile_all_sessions(chat_dir):
    """Profile every session in the chat directory."""
    sessions = []
    files = sorted(chat_dir.glob("*.jsonl"), key=lambda f: f.stat().st_mtime)

    total = len(files)
    for i, f in enumerate(files):
        if (i + 1) % 100 == 0:
            print(f"  Profiling {i+1}/{total}...", flush=True)
        sessions.append(profile_session(f))

    # Sort by start_time (or modified date)
    sessions.sort(key=lambda s: s.get("start_time") or s["modified"])
    return sessions


# ── Visualization ─────────────────────────────────────────────────────

def generate_html(sessions, output_path):
    """Generate the interactive session timeline visualization."""

    # Aggregate stats
    total_sessions = len(sessions)
    total_size_gb = sum(s["size_bytes"] for s in sessions) / (1024**3)
    total_messages = sum(s["total_messages"] for s in sessions)
    total_user = sum(s["user_messages"] for s in sessions)
    total_assistant = sum(s["assistant_messages"] for s in sessions)
    agent_sessions = sum(1 for s in sessions if s["is_agent"])
    human_sessions = total_sessions - agent_sessions

    # Date range
    dates = [s["date"] for s in sessions if s["date"]]
    first_date = min(dates) if dates else "?"
    last_date = max(dates) if dates else "?"

    # Size classes
    size_counts = defaultdict(int)
    for s in sessions:
        size_counts[s["size_class"]] += 1

    # Sessions per day
    daily = defaultdict(int)
    daily_size = defaultdict(float)
    for s in sessions:
        d = s["date"]
        if d:
            daily[d] += 1
            daily_size[d] += s["size_mb"]

    # Prepare chart data — each session as a bar
    # For 3000+ sessions, we need to be smart about rendering
    # Group into date buckets if too many sessions
    session_json = json.dumps([{
        "id": s["id"],
        "full_id": s["full_id"],
        "size_mb": s["size_mb"],
        "size_class": s["size_class"],
        "messages": s["total_messages"],
        "user": s["user_messages"],
        "assistant": s["assistant_messages"],
        "date": s["date"],
        "duration": s["duration_minutes"],
        "is_agent": s["is_agent"],
        "lines": s["total_lines"],
    } for s in sessions])

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Your Claude Code History</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;600;700&family=Space+Grotesk:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
  :root {{
    --font-body: 'Space Grotesk', system-ui, sans-serif;
    --font-mono: 'JetBrains Mono', 'SF Mono', Consolas, monospace;
    --bg: #09090b;
    --surface: #111113;
    --surface2: #18181b;
    --border: rgba(255,255,255,0.06);
    --border-bright: rgba(255,255,255,0.12);
    --text: #e4e4e7;
    --text-dim: #71717a;
    --text-muted: #52525b;
    --accent: #8b5cf6;
    --accent-dim: rgba(139,92,246,0.12);
    --green: #22c55e;
    --green-dim: rgba(34,197,94,0.08);
    --amber: #f59e0b;
    --amber-dim: rgba(245,158,11,0.08);
    --cyan: #06b6d4;
    --red: #ef4444;
  }}
  @media (prefers-color-scheme: light) {{
    :root {{
      --bg: #fafafa; --surface: #fff; --surface2: #f4f4f5;
      --border: rgba(0,0,0,0.06); --border-bright: rgba(0,0,0,0.12);
      --text: #18181b; --text-dim: #71717a; --text-muted: #a1a1aa;
      --accent: #7c3aed; --accent-dim: rgba(124,58,237,0.08);
      --green: #16a34a; --green-dim: rgba(22,163,74,0.06);
      --amber: #d97706; --amber-dim: rgba(217,119,6,0.06);
      --cyan: #0891b2; --red: #dc2626;
    }}
  }}
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{
    font-family: var(--font-body);
    background: var(--bg);
    color: var(--text);
    -webkit-font-smoothing: antialiased;
  }}

  .hero {{
    padding: 48px 48px 32px;
    background: radial-gradient(ellipse at 50% 100%, var(--accent-dim) 0%, transparent 60%);
    border-bottom: 1px solid var(--border);
  }}
  .hero h1 {{ font-size: 36px; font-weight: 700; letter-spacing: -1px; margin-bottom: 8px; }}
  .hero h1 span {{ color: var(--accent); }}
  .hero .sub {{ color: var(--text-dim); font-size: 15px; margin-bottom: 24px; }}

  .kpi-row {{
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
    gap: 12px;
    margin-top: 24px;
  }}
  .kpi {{
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 16px;
    animation: fadeScale 0.35s ease-out both;
    animation-delay: calc(var(--i, 0) * 0.06s);
  }}
  .kpi-val {{
    font-size: 28px; font-weight: 700;
    font-variant-numeric: tabular-nums;
    letter-spacing: -1px;
  }}
  .kpi-val.purple {{ color: var(--accent); }}
  .kpi-val.green {{ color: var(--green); }}
  .kpi-val.amber {{ color: var(--amber); }}
  .kpi-val.cyan {{ color: var(--cyan); }}
  .kpi-label {{
    font-family: var(--font-mono);
    font-size: 10px; font-weight: 600;
    text-transform: uppercase; letter-spacing: 1.2px;
    color: var(--text-muted);
    margin-top: 4px;
  }}

  .chart-section {{
    padding: 32px 48px;
  }}
  .chart-section h2 {{
    font-size: 20px; font-weight: 600;
    margin-bottom: 4px;
  }}
  .chart-section .desc {{
    font-size: 13px; color: var(--text-dim);
    margin-bottom: 20px;
  }}

  .chart-wrap {{
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 24px;
    position: relative;
  }}
  .chart-container {{
    position: relative;
    width: 100%;
    height: 220px;
  }}
  .chart-controls {{
    display: flex; gap: 8px; margin-bottom: 12px; flex-wrap: wrap;
  }}
  .chart-controls button {{
    font-family: var(--font-mono);
    font-size: 11px; font-weight: 500;
    padding: 5px 12px;
    border: 1px solid var(--border-bright);
    border-radius: 6px;
    background: var(--surface2);
    color: var(--text-dim);
    cursor: pointer;
    transition: all 0.15s;
  }}
  .chart-controls button:hover {{ color: var(--text); border-color: var(--accent); }}
  .chart-controls button.active {{
    background: var(--accent-dim); color: var(--accent);
    border-color: var(--accent);
  }}

  .tooltip {{
    position: fixed;
    background: var(--surface2);
    border: 1px solid var(--border-bright);
    border-radius: 8px;
    padding: 12px 16px;
    font-size: 12px;
    pointer-events: none;
    z-index: 100;
    box-shadow: 0 8px 24px rgba(0,0,0,0.3);
    max-width: 280px;
    display: none;
  }}
  .tooltip .tt-id {{ font-family: var(--font-mono); font-weight: 600; color: var(--accent); }}
  .tooltip .tt-row {{ display: flex; justify-content: space-between; gap: 16px; margin-top: 4px; }}
  .tooltip .tt-label {{ color: var(--text-muted); }}
  .tooltip .tt-val {{ font-family: var(--font-mono); color: var(--text); font-weight: 500; }}

  .size-legend {{
    display: flex; gap: 16px; margin-top: 16px; flex-wrap: wrap;
  }}
  .size-legend .leg {{
    display: flex; align-items: center; gap: 6px;
    font-family: var(--font-mono);
    font-size: 10px; color: var(--text-muted);
  }}
  .size-legend .dot {{
    width: 10px; height: 10px; border-radius: 2px;
  }}

  @keyframes fadeScale {{
    from {{ opacity: 0; transform: scale(0.95); }}
    to {{ opacity: 1; transform: scale(1); }}
  }}
  @media (prefers-reduced-motion: reduce) {{
    * {{ animation: none !important; }}
  }}
  @media (max-width: 768px) {{
    .hero, .chart-section {{ padding: 24px 16px; }}
    .hero h1 {{ font-size: 24px; }}
    .kpi-row {{ grid-template-columns: repeat(2, 1fr); }}
  }}
</style>
</head>
<body>

<div class="hero">
  <h1>Your Claude Code <span>History</span></h1>
  <p class="sub">
    {total_sessions:,} sessions from {first_date} to {last_date}.
    Every bar is a conversation with Claude.
  </p>
  <div class="kpi-row">
    <div class="kpi" style="--i:0"><div class="kpi-val purple">{total_sessions:,}</div><div class="kpi-label">Sessions</div></div>
    <div class="kpi" style="--i:1"><div class="kpi-val green">{total_size_gb:.2f} GB</div><div class="kpi-label">Total Data</div></div>
    <div class="kpi" style="--i:2"><div class="kpi-val amber">{total_messages:,}</div><div class="kpi-label">Messages</div></div>
    <div class="kpi" style="--i:3"><div class="kpi-val cyan">{human_sessions:,}</div><div class="kpi-label">Human Sessions</div></div>
    <div class="kpi" style="--i:4"><div class="kpi-val">{agent_sessions:,}</div><div class="kpi-label">Agent Sessions</div></div>
    <div class="kpi" style="--i:5"><div class="kpi-val">{len(daily)}</div><div class="kpi-label">Active Days</div></div>
  </div>
</div>

<div class="chart-section">
  <h2>Session Timeline</h2>
  <p class="desc">Each bar is one session. Height = file size. Hover for details. Click to zoom.</p>

  <div class="chart-wrap">
    <div class="chart-controls">
      <button class="active" onclick="setMetric('size_mb')">By Size</button>
      <button onclick="setMetric('messages')">By Messages</button>
      <button onclick="setMetric('lines')">By Lines</button>
      <button onclick="setMetric('duration')">By Duration</button>
      <button onclick="toggleAgents(this)">Hide Agents</button>
    </div>
    <div class="chart-container"><canvas id="barChart"></canvas></div>
    <div class="size-legend">
      <div class="leg"><div class="dot" style="background:#8b5cf6"></div>Mega (&gt;20MB)</div>
      <div class="leg"><div class="dot" style="background:#22c55e"></div>Large (5-20MB)</div>
      <div class="leg"><div class="dot" style="background:#06b6d4"></div>Medium (0.5-5MB)</div>
      <div class="leg"><div class="dot" style="background:#f59e0b"></div>Small (&lt;0.5MB)</div>
      <div class="leg"><div class="dot" style="background:#3f3f46"></div>Tiny (&lt;10KB)</div>
    </div>
  </div>
</div>

<div class="tooltip" id="tooltip"></div>

<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.7/dist/chart.umd.min.js"></script>
<script>
const allSessions = {session_json};
let currentMetric = 'size_mb';
let hideAgents = false;
let chart = null;

const colorMap = {{
  mega: '#8b5cf6',
  large: '#22c55e',
  medium: '#06b6d4',
  small: '#f59e0b',
  tiny: '#3f3f46',
}};

function getFiltered() {{
  return hideAgents ? allSessions.filter(s => !s.is_agent) : allSessions;
}}

function buildChart() {{
  const sessions = getFiltered();
  const canvas = document.getElementById('barChart');
  const ctx = canvas.getContext('2d');

  if (chart) chart.destroy();

  const labels = sessions.map(s => s.id);
  const data = sessions.map(s => s[currentMetric] || 0);
  const colors = sessions.map(s => s.is_agent ? '#27272a' : colorMap[s.size_class]);

  const metricLabels = {{
    size_mb: 'Size (MB)',
    messages: 'Messages',
    lines: 'Lines',
    duration: 'Duration (min)',
  }};

  chart = new Chart(ctx, {{
    type: 'bar',
    data: {{
      labels: labels,
      datasets: [{{
        data: data,
        backgroundColor: colors,
        borderWidth: 0,
        borderRadius: 1,
        barPercentage: 1.0,
        categoryPercentage: 1.0,
      }}],
    }},
    options: {{
      responsive: true,
      maintainAspectRatio: false,
      animation: {{ duration: 400 }},
      plugins: {{
        legend: {{ display: false }},
        tooltip: {{ enabled: false }},
      }},
      scales: {{
        x: {{
          display: false,
        }},
        y: {{
          type: 'logarithmic',
          min: 0.001,
          grid: {{ color: 'rgba(255,255,255,0.04)' }},
          ticks: {{
            color: '#71717a',
            font: {{ family: "'JetBrains Mono'", size: 10 }},
            callback: function(v) {{
              if (currentMetric === 'size_mb') {{
                if (v >= 1) return v + ' MB';
                if (v >= 0.01) return Math.round(v*1000) + ' KB';
                return '';
              }}
              if (v >= 1000) return (v/1000).toFixed(0) + 'K';
              return v;
            }},
          }},
          title: {{
            display: true,
            text: metricLabels[currentMetric] + ' (log scale)',
            color: '#71717a',
            font: {{ family: "'JetBrains Mono'", size: 10, weight: 600 }},
          }},
        }},
      }},
      onHover: function(evt, elements) {{
        const tt = document.getElementById('tooltip');
        if (elements.length > 0) {{
          const idx = elements[0].index;
          const s = sessions[idx];
          tt.innerHTML = `
            <div class="tt-id">${{s.full_id}}</div>
            <div class="tt-row"><span class="tt-label">Date</span><span class="tt-val">${{s.date}}</span></div>
            <div class="tt-row"><span class="tt-label">Size</span><span class="tt-val">${{s.size_mb}} MB</span></div>
            <div class="tt-row"><span class="tt-label">Messages</span><span class="tt-val">${{s.messages}}</span></div>
            <div class="tt-row"><span class="tt-label">User / Assistant</span><span class="tt-val">${{s.user}} / ${{s.assistant}}</span></div>
            <div class="tt-row"><span class="tt-label">Duration</span><span class="tt-val">${{s.duration}} min</span></div>
            <div class="tt-row"><span class="tt-label">Lines</span><span class="tt-val">${{s.lines.toLocaleString()}}</span></div>
            <div class="tt-row"><span class="tt-label">Agent</span><span class="tt-val">${{s.is_agent ? 'Yes' : 'No'}}</span></div>
          `;
          tt.style.display = 'block';
          tt.style.left = (evt.native.clientX + 16) + 'px';
          tt.style.top = (evt.native.clientY - 10) + 'px';
        }} else {{
          tt.style.display = 'none';
        }}
      }},
    }},
  }});

}}

function setMetric(m) {{
  currentMetric = m;
  document.querySelectorAll('.chart-controls button').forEach(b => b.classList.remove('active'));
  event.target.classList.add('active');
  buildChart();
}}

function toggleAgents(btn) {{
  hideAgents = !hideAgents;
  btn.textContent = hideAgents ? 'Show Agents' : 'Hide Agents';
  btn.classList.toggle('active', hideAgents);
  buildChart();
}}

buildChart();
</script>

</body>
</html>"""
    output_path.write_text(html)
    return output_path


# ── Main ──────────────────────────────────────────────────────────────

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Session Profiler")
    parser.add_argument("--chat-dir", default="", help="Path to chat history directory")
    parser.add_argument("--output", default="", help="Output HTML path")
    args = parser.parse_args()

    print("=" * 60)
    print("Hyperdocs Session Profiler")
    print("=" * 60)

    # Find chat history
    if args.chat_dir:
        chat_dir = Path(args.chat_dir)
    else:
        chat_dir = find_chat_history()
        if not chat_dir:
            print("ERROR: Could not find Claude Code chat history.")
            print("  Checked: ~/PERMANENT_CHAT_HISTORY/sessions/, ~/.claude/projects/")
            sys.exit(1)

    print(f"Chat directory: {chat_dir}")
    files = list(chat_dir.glob("*.jsonl"))
    print(f"Sessions found: {len(files)}")
    print()

    # Profile all sessions
    print("Profiling sessions...")
    sessions = profile_all_sessions(chat_dir)
    print(f"  Profiled: {len(sessions)}")

    # Generate visualization
    if args.output:
        output_path = Path(args.output)
    else:
        output_path = HYPERDOCS_ROOT / "output" / "session_profile.html"

    output_path.parent.mkdir(parents=True, exist_ok=True)
    generate_html(sessions, output_path)

    print(f"\nVisualization: {output_path}")
    print(f"  Size: {output_path.stat().st_size // 1024} KB")

    # Auto-open
    os.system(f'open "{output_path}"')

    # Also save raw profile data
    profile_path = output_path.with_suffix(".json")
    with open(profile_path, "w") as f:
        json.dump({
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "chat_dir": str(chat_dir),
            "total_sessions": len(sessions),
            "sessions": sessions,
        }, f, indent=2, default=str)
    print(f"  Profile data: {profile_path}")


if __name__ == "__main__":
    main()
