#!/usr/bin/env python3
"""
Hyperdocs Activity Monitor — Live dashboard for pipeline processing.

Serves a self-contained HTML dashboard on localhost:8800 that auto-refreshes
every 3 seconds, showing:
  - Phase 0 batch status
  - Phase 1 live progress (per-session, per-pass)
  - Quality distribution (clean / minor / significant)
  - Aggregate metrics
  - Session-level detail table

Data sources (read fresh on every request):
  ~/PERMANENT_HYPERDOCS/indexes/phase1_redo_progress.json
  ~/PERMANENT_HYPERDOCS/indexes/phase0_reprocess_log.json
  ~/PERMANENT_HYPERDOCS/indexes/completeness_report.json

Usage:
    python3 activity_monitor.py          # starts on port 8800
    python3 activity_monitor.py --port 9000
"""

import json
import os
import sys
from datetime import datetime, timezone
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path

INDEXES = Path.home() / "PERMANENT_HYPERDOCS" / "indexes"
SESSIONS = Path.home() / "PERMANENT_HYPERDOCS" / "sessions"
PORT = 8800


def load_json(path):
    try:
        with open(path) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def gather_status():
    """Read all data sources and build a unified status dict."""
    p1 = load_json(INDEXES / "phase1_redo_progress.json")
    p0 = load_json(INDEXES / "phase0_reprocess_log.json")
    completeness = load_json(INDEXES / "completeness_report.json")

    # Count sessions on disk
    session_dirs = [d for d in SESSIONS.iterdir() if d.is_dir() and d.name.startswith("session_")] if SESSIONS.exists() else []
    total_sessions = len(session_dirs)

    # Phase 1 aggregates
    completed = p1.get("completed", [])
    failed = p1.get("failed", [])

    quality_dist = {"clean": 0, "minor_issues": 0, "significant_issues": 0, "unknown": 0}
    total_entries = 0
    total_observations = 0
    total_tagged = 0
    total_tagged_expected = 0
    pass_times = {"thread_analyst": [], "geological_reader": [], "primitives_tagger": [], "explorer": []}

    for s in completed:
        v = s.get("verification", {})
        q = v.get("overall_data_quality", "unknown")
        quality_dist[q] = quality_dist.get(q, 0) + 1

        passes = s.get("passes", {})
        if "thread_analyst" in passes:
            total_entries += passes["thread_analyst"].get("entries", 0)
            pass_times["thread_analyst"].append(passes["thread_analyst"].get("time", 0))
        if "geological_reader" in passes:
            total_observations += passes["geological_reader"].get("observations", 0)
            pass_times["geological_reader"].append(passes["geological_reader"].get("time", 0))
        if "primitives_tagger" in passes:
            total_tagged += passes["primitives_tagger"].get("tagged", 0)
            total_tagged_expected += passes["primitives_tagger"].get("expected", 0)
            pass_times["primitives_tagger"].append(passes["primitives_tagger"].get("time", 0))
        if "explorer" in passes:
            pass_times["explorer"].append(passes["explorer"].get("time", 0))

    avg_times = {}
    for k, v in pass_times.items():
        avg_times[k] = round(sum(v) / len(v)) if v else 0

    # Estimate remaining time
    n_done = len(completed) + len(failed)
    n_total = p1.get("total_sessions", total_sessions)
    avg_session_time = sum(sum(v) for v in pass_times.values()) / max(len(completed), 1)
    eta_seconds = (n_total - n_done) * avg_session_time if n_done > 0 else 0

    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "total_sessions_on_disk": total_sessions,
        "phase0": {
            "sessions_processed": p0.get("sessions_processed", 0),
            "sessions_failed": p0.get("sessions_failed", 0),
            "sessions_skipped": p0.get("sessions_skipped", 0),
            "duration_seconds": p0.get("duration_seconds", 0),
            "completed_at": p0.get("completed_at", ""),
        },
        "phase1": {
            "operation": p1.get("operation", ""),
            "started_at": p1.get("started_at", ""),
            "updated_at": p1.get("updated_at", ""),
            "total_sessions": n_total,
            "completed": len(completed),
            "failed": len(failed),
            "remaining": n_total - n_done,
            "pct_complete": round(n_done / max(n_total, 1) * 100, 1),
            "current_session": p1.get("current_session", ""),
            "quality_distribution": quality_dist,
            "totals": {
                "thread_entries": total_entries,
                "geological_observations": total_observations,
                "primitives_tagged": total_tagged,
                "primitives_expected": total_tagged_expected,
                "tag_coverage_pct": round(total_tagged / max(total_tagged_expected, 1) * 100, 1),
            },
            "avg_pass_times": avg_times,
            "avg_session_time": round(avg_session_time),
            "eta_seconds": round(eta_seconds),
            "successful_passes": p1.get("totals", {}).get("successful_passes", 0),
            "failed_passes": p1.get("totals", {}).get("failed_passes", 0),
        },
        "session_details": [
            {
                "session": s["session"],
                "quality": s.get("verification", {}).get("overall_data_quality", "?"),
                "threads": s.get("passes", {}).get("thread_analyst", {}).get("entries", 0),
                "geo": s.get("passes", {}).get("geological_reader", {}).get("observations", 0),
                "tagged": s.get("passes", {}).get("primitives_tagger", {}).get("tagged", 0),
                "expected": s.get("passes", {}).get("primitives_tagger", {}).get("expected", 0),
                "explorer_obs": s.get("passes", {}).get("explorer", {}).get("observations", 0),
                "time": sum(
                    s.get("passes", {}).get(p, {}).get("time", 0)
                    for p in ["thread_analyst", "geological_reader", "primitives_tagger", "explorer"]
                ),
                "issues_high": sum(
                    1 for cat in s.get("verification", {}).values()
                    if isinstance(cat, list)
                    for issue in cat
                    if isinstance(issue, dict) and issue.get("severity") in ("high", "significant")
                ),
            }
            for s in completed
        ],
        "failed_details": [
            {"session": s.get("session", "?"), "errors": s.get("errors", [])}
            for s in failed
        ],
        "completeness": {
            "sessions_scanned": completeness.get("sessions_scanned", 0),
            "incomplete": len(completeness.get("incomplete_sessions", [])),
        },
    }


DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Hyperdocs Activity Monitor</title>
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body {
    font-family: 'SF Mono', 'Fira Code', 'JetBrains Mono', monospace;
    background: #0d1117;
    color: #c9d1d9;
    padding: 24px;
    line-height: 1.5;
  }
  h1 { color: #58a6ff; font-size: 20px; margin-bottom: 4px; }
  .subtitle { color: #8b949e; font-size: 12px; margin-bottom: 24px; }
  .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 16px; margin-bottom: 24px; }
  .card {
    background: #161b22;
    border: 1px solid #30363d;
    border-radius: 8px;
    padding: 16px;
  }
  .card h2 { color: #8b949e; font-size: 11px; text-transform: uppercase; letter-spacing: 1px; margin-bottom: 12px; }
  .metric { font-size: 32px; font-weight: 700; color: #f0f6fc; }
  .metric-sm { font-size: 18px; color: #f0f6fc; font-weight: 600; }
  .metric-label { font-size: 11px; color: #8b949e; margin-top: 2px; }
  .metric-row { display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 8px; }

  .progress-bar {
    width: 100%;
    height: 8px;
    background: #21262d;
    border-radius: 4px;
    margin: 12px 0;
    overflow: hidden;
  }
  .progress-fill {
    height: 100%;
    border-radius: 4px;
    transition: width 0.5s ease;
  }
  .progress-fill.green { background: linear-gradient(90deg, #238636, #2ea043); }
  .progress-fill.blue { background: linear-gradient(90deg, #1f6feb, #58a6ff); }

  .quality-bar { display: flex; gap: 8px; margin-top: 8px; }
  .quality-chip {
    padding: 4px 10px;
    border-radius: 12px;
    font-size: 12px;
    font-weight: 600;
  }
  .q-clean { background: #0d4429; color: #3fb950; }
  .q-minor { background: #3d2e00; color: #d29922; }
  .q-significant { background: #4a1c1c; color: #f85149; }
  .q-unknown { background: #21262d; color: #8b949e; }

  .pass-times { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin-top: 8px; }
  .pass-time { text-align: center; }
  .pass-time .label { font-size: 10px; color: #8b949e; }
  .pass-time .value { font-size: 16px; color: #c9d1d9; font-weight: 600; }

  table {
    width: 100%;
    border-collapse: collapse;
    font-size: 12px;
  }
  th {
    text-align: left;
    padding: 8px 12px;
    background: #161b22;
    color: #8b949e;
    font-size: 10px;
    text-transform: uppercase;
    letter-spacing: 1px;
    border-bottom: 1px solid #30363d;
    position: sticky;
    top: 0;
  }
  td {
    padding: 6px 12px;
    border-bottom: 1px solid #21262d;
  }
  tr:hover td { background: #161b22; }
  .tag-clean { color: #3fb950; }
  .tag-minor { color: #d29922; }
  .tag-significant { color: #f85149; }
  .tag-unknown { color: #8b949e; }

  .eta { color: #58a6ff; font-size: 14px; margin-top: 4px; }
  .pulse { animation: pulse 2s ease-in-out infinite; }
  @keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.5; } }
  .live-dot { display: inline-block; width: 8px; height: 8px; background: #3fb950; border-radius: 50%; margin-right: 6px; }
  .live-dot.active { animation: pulse 1s ease-in-out infinite; }

  .failed-row td { color: #f85149; }
  #last-update { color: #484f58; font-size: 11px; position: fixed; bottom: 8px; right: 16px; }

  .table-wrapper { max-height: 500px; overflow-y: auto; border: 1px solid #30363d; border-radius: 8px; }
  .section-title { color: #58a6ff; font-size: 14px; margin: 24px 0 12px; }
</style>
</head>
<body>

<h1><span class="live-dot active" id="live-dot"></span>Hyperdocs Activity Monitor</h1>
<div class="subtitle" id="subtitle">Connecting...</div>

<div class="grid">
  <div class="card">
    <h2>Phase 0 — Data Prep</h2>
    <div class="metric" id="p0-processed">—</div>
    <div class="metric-label">sessions processed</div>
    <div class="progress-bar"><div class="progress-fill green" id="p0-bar" style="width:0%"></div></div>
    <div class="metric-row">
      <div><span class="metric-sm" id="p0-failed">—</span> <span class="metric-label">failed</span></div>
      <div><span class="metric-sm" id="p0-time">—</span> <span class="metric-label">seconds</span></div>
    </div>
  </div>

  <div class="card">
    <h2>Phase 1 — Opus Agents</h2>
    <div class="metric" id="p1-completed">—</div>
    <div class="metric-label" id="p1-label">sessions completed</div>
    <div class="progress-bar"><div class="progress-fill blue" id="p1-bar" style="width:0%"></div></div>
    <div class="eta" id="p1-eta"></div>
    <div class="metric-row">
      <div><span class="metric-sm" id="p1-failed">—</span> <span class="metric-label">failed</span></div>
      <div><span class="metric-sm" id="p1-passes">—</span> <span class="metric-label">passes ok</span></div>
    </div>
  </div>

  <div class="card">
    <h2>Quality Distribution</h2>
    <div class="quality-bar" id="quality-bar"></div>
    <div style="margin-top: 16px">
      <div class="metric-row">
        <span class="metric-label">Tag Coverage</span>
        <span class="metric-sm" id="tag-coverage">—</span>
      </div>
      <div class="metric-row">
        <span class="metric-label">Thread Entries</span>
        <span class="metric-sm" id="total-entries">—</span>
      </div>
      <div class="metric-row">
        <span class="metric-label">Geological Obs</span>
        <span class="metric-sm" id="total-obs">—</span>
      </div>
      <div class="metric-row">
        <span class="metric-label">Primitives Tagged</span>
        <span class="metric-sm" id="total-tagged">—</span>
      </div>
    </div>
  </div>

  <div class="card">
    <h2>Avg Pass Times</h2>
    <div class="pass-times">
      <div class="pass-time">
        <div class="label">Thread</div>
        <div class="value" id="avg-thread">—</div>
      </div>
      <div class="pass-time">
        <div class="label">Geological</div>
        <div class="value" id="avg-geo">—</div>
      </div>
      <div class="pass-time">
        <div class="label">Primitives</div>
        <div class="value" id="avg-prims">—</div>
      </div>
      <div class="pass-time">
        <div class="label">Explorer</div>
        <div class="value" id="avg-explorer">—</div>
      </div>
    </div>
    <div style="margin-top: 16px">
      <div class="metric-row">
        <span class="metric-label">Avg per Session</span>
        <span class="metric-sm" id="avg-session">—</span>
      </div>
    </div>
  </div>
</div>

<div class="section-title">Session Details</div>
<div class="table-wrapper">
  <table>
    <thead>
      <tr>
        <th>Session</th>
        <th>Quality</th>
        <th>Threads</th>
        <th>Geo</th>
        <th>Tagged</th>
        <th>Explorer</th>
        <th>Time</th>
      </tr>
    </thead>
    <tbody id="session-table"></tbody>
  </table>
</div>

<div id="failed-section" style="display:none">
  <div class="section-title" style="color: #f85149">Failed Sessions</div>
  <div class="table-wrapper">
    <table>
      <thead><tr><th>Session</th><th>Errors</th></tr></thead>
      <tbody id="failed-table"></tbody>
    </table>
  </div>
</div>

<div id="last-update">—</div>

<script>
function fmt(s) { return s < 10 ? '0' + s : s; }
function fmtTime(sec) {
  if (!sec || sec <= 0) return '—';
  const h = Math.floor(sec / 3600);
  const m = Math.floor((sec % 3600) / 60);
  if (h > 0) return h + 'h ' + m + 'm';
  if (m > 0) return m + 'm ' + (sec % 60) + 's';
  return sec + 's';
}

function qualityClass(q) {
  if (q === 'clean') return 'tag-clean';
  if (q === 'minor_issues') return 'tag-minor';
  if (q === 'significant_issues') return 'tag-significant';
  return 'tag-unknown';
}

function qualityChipClass(q) {
  if (q === 'clean') return 'q-clean';
  if (q === 'minor_issues') return 'q-minor';
  if (q === 'significant_issues') return 'q-significant';
  return 'q-unknown';
}

function qualityLabel(q) {
  if (q === 'clean') return 'Clean';
  if (q === 'minor_issues') return 'Minor';
  if (q === 'significant_issues') return 'Significant';
  return q;
}

let refreshCount = 0;

async function refresh() {
  try {
    const res = await fetch('/api/status');
    const d = await res.json();
    refreshCount++;

    // Subtitle
    const dot = document.getElementById('live-dot');
    const p1 = d.phase1;
    if (p1.remaining > 0) {
      document.getElementById('subtitle').textContent =
        'Processing ' + p1.current_session + ' (' + p1.completed + '/' + p1.total_sessions + ')';
      dot.className = 'live-dot active';
    } else if (p1.completed > 0) {
      document.getElementById('subtitle').textContent =
        'Phase 1 complete — ' + p1.completed + ' sessions processed';
      dot.className = 'live-dot';
    } else {
      document.getElementById('subtitle').textContent = 'Idle — no active processing';
      dot.className = 'live-dot';
    }

    // Phase 0
    const p0 = d.phase0;
    document.getElementById('p0-processed').textContent = p0.sessions_processed;
    document.getElementById('p0-failed').textContent = p0.sessions_failed;
    document.getElementById('p0-time').textContent = p0.duration_seconds;
    const p0pct = p0.sessions_processed > 0 ? 100 : 0;
    document.getElementById('p0-bar').style.width = p0pct + '%';

    // Phase 1
    document.getElementById('p1-completed').textContent = p1.completed;
    document.getElementById('p1-label').textContent =
      'of ' + p1.total_sessions + ' sessions (' + p1.pct_complete + '%)';
    document.getElementById('p1-bar').style.width = p1.pct_complete + '%';
    document.getElementById('p1-failed').textContent = p1.failed;
    document.getElementById('p1-passes').textContent = p1.successful_passes;
    document.getElementById('p1-eta').textContent =
      p1.remaining > 0 ? 'ETA: ' + fmtTime(p1.eta_seconds) + ' remaining' : '';

    // Quality
    const qd = p1.quality_distribution;
    let qhtml = '';
    for (const [k, v] of Object.entries(qd)) {
      if (v > 0) {
        qhtml += '<span class="quality-chip ' + qualityChipClass(k) + '">' + qualityLabel(k) + ': ' + v + '</span>';
      }
    }
    document.getElementById('quality-bar').innerHTML = qhtml || '<span class="quality-chip q-unknown">No data</span>';

    // Totals
    document.getElementById('tag-coverage').textContent = p1.totals.tag_coverage_pct + '%';
    document.getElementById('total-entries').textContent = p1.totals.thread_entries.toLocaleString();
    document.getElementById('total-obs').textContent = p1.totals.geological_observations.toLocaleString();
    document.getElementById('total-tagged').textContent =
      p1.totals.primitives_tagged.toLocaleString() + ' / ' + p1.totals.primitives_expected.toLocaleString();

    // Avg times
    document.getElementById('avg-thread').textContent = fmtTime(p1.avg_pass_times.thread_analyst);
    document.getElementById('avg-geo').textContent = fmtTime(p1.avg_pass_times.geological_reader);
    document.getElementById('avg-prims').textContent = fmtTime(p1.avg_pass_times.primitives_tagger);
    document.getElementById('avg-explorer').textContent = fmtTime(p1.avg_pass_times.explorer);
    document.getElementById('avg-session').textContent = fmtTime(p1.avg_session_time);

    // Session table
    const tbody = document.getElementById('session-table');
    let rows = '';
    for (const s of d.session_details.reverse()) {
      const qc = qualityClass(s.quality);
      const tagStr = s.expected > 0 ? s.tagged + '/' + s.expected : s.tagged;
      rows += '<tr>' +
        '<td>' + s.session.replace('session_', '') + '</td>' +
        '<td class="' + qc + '">' + qualityLabel(s.quality) + '</td>' +
        '<td>' + s.threads + '</td>' +
        '<td>' + s.geo + '</td>' +
        '<td>' + tagStr + '</td>' +
        '<td>' + s.explorer_obs + '</td>' +
        '<td>' + fmtTime(s.time) + '</td>' +
        '</tr>';
    }
    tbody.innerHTML = rows;

    // Failed table
    if (d.failed_details.length > 0) {
      document.getElementById('failed-section').style.display = 'block';
      const ftbody = document.getElementById('failed-table');
      let frows = '';
      for (const f of d.failed_details) {
        frows += '<tr class="failed-row"><td>' + f.session + '</td><td>' + f.errors.join(', ') + '</td></tr>';
      }
      ftbody.innerHTML = frows;
    }

    // Last update
    const now = new Date();
    document.getElementById('last-update').textContent =
      'Updated ' + fmt(now.getHours()) + ':' + fmt(now.getMinutes()) + ':' + fmt(now.getSeconds()) +
      ' (refresh #' + refreshCount + ')';

  } catch (e) {
    document.getElementById('subtitle').textContent = 'Connection error: ' + e.message;
    document.getElementById('live-dot').className = 'live-dot';
  }
}

refresh();
setInterval(refresh, 3000);
</script>
</body>
</html>"""


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/api/status":
            data = gather_status()
            body = json.dumps(data).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/" or self.path == "/index.html":
            body = DASHBOARD_HTML.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        pass  # Suppress request logs


def main():
    port = PORT
    if "--port" in sys.argv:
        idx = sys.argv.index("--port")
        if idx + 1 < len(sys.argv):
            port = int(sys.argv[idx + 1])

    server = HTTPServer(("127.0.0.1", port), Handler)
    print(f"Hyperdocs Activity Monitor running at http://localhost:{port}")
    print("Press Ctrl+C to stop.")

    # Auto-open in browser (unless --no-open)
    if "--no-open" not in sys.argv:
        os.system(f"open http://localhost:{port}")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
        server.server_close()


if __name__ == "__main__":
    main()
