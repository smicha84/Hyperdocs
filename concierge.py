#!/usr/bin/env python3
"""
Hyperdocs Concierge — Zero-work onboarding.

Modes:
  --discover     Scan all Claude Code sessions, show what's available
  --process ID   Run Phase 0 on a specific session
  --status       Show current pipeline state
  --dashboard    Generate and open the dashboard
"""
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from datetime import datetime

CLAUDE_PROJECTS = Path.home() / ".claude" / "projects"
HYPERDOCS_ROOT = Path(__file__).resolve().parent
OUTPUT_BASE = Path(os.getenv("HYPERDOCS_OUTPUT_DIR", str(HYPERDOCS_ROOT / "output")))


def format_size(size_bytes):
    if size_bytes >= 1_000_000:
        return f"{size_bytes / 1_000_000:.1f} MB"
    elif size_bytes >= 1_000:
        return f"{size_bytes / 1_000:.0f} KB"
    return f"{size_bytes} B"


def count_messages(jsonl_path):
    """Count user and assistant messages in a JSONL file (fast, no full parse)."""
    user = 0
    assistant = 0
    total = 0
    try:
        with open(jsonl_path) as f:
            for line in f:
                total += 1
                if '"role":"user"' in line or '"role": "user"' in line:
                    user += 1
                elif '"role":"assistant"' in line or '"role": "assistant"' in line:
                    assistant += 1
    except (OSError, UnicodeDecodeError):
        pass
    return {"total": total, "user": user, "assistant": assistant}


def discover():
    """Scan all Claude Code sessions, group by project."""
    if not CLAUDE_PROJECTS.exists():
        print("ERROR: ~/.claude/projects/ not found. Is Claude Code installed?")
        return None

    projects = {}
    total_sessions = 0
    total_messages = 0

    for project_dir in sorted(CLAUDE_PROJECTS.iterdir()):
        if not project_dir.is_dir():
            continue

        sessions = []
        for jsonl in project_dir.glob("*.jsonl"):
            size = jsonl.stat().st_size
            modified = datetime.fromtimestamp(jsonl.stat().st_mtime)
            counts = count_messages(jsonl)

            # Skip files with no actual messages
            if counts["user"] == 0 and counts["assistant"] == 0:
                continue

            sessions.append({
                "id": jsonl.stem,
                "path": str(jsonl),
                "size_bytes": size,
                "messages": counts,
                "modified": modified.isoformat(),
                "modified_display": modified.strftime("%Y-%m-%d %H:%M"),
            })

        if sessions:
            sessions.sort(key=lambda s: s["modified"], reverse=True)

            # Derive a readable project name from the encoded directory name
            raw_name = project_dir.name
            # -Users-name-Projects-project → extract last segment
            parts = raw_name.split("-")
            readable = parts[-1] if parts else raw_name

            project_total_msgs = sum(s["messages"]["total"] for s in sessions)
            projects[project_dir.name] = {
                "readable_name": readable,
                "path": str(project_dir),
                "sessions": sessions,
                "total_sessions": len(sessions),
                "total_size": sum(s["size_bytes"] for s in sessions),
                "total_messages": project_total_msgs,
            }
            total_sessions += len(sessions)
            total_messages += project_total_msgs

    # Write discovery.json
    discovery = {
        "discovered_at": datetime.now().isoformat(),
        "total_projects": len(projects),
        "total_sessions": total_sessions,
        "total_messages": total_messages,
        "projects": projects,
    }

    OUTPUT_BASE.mkdir(parents=True, exist_ok=True)
    discovery_path = OUTPUT_BASE / "discovery.json"
    with open(discovery_path, "w") as f:
        json.dump(discovery, f, indent=2)

    # Print summary
    print("=" * 60)
    print("Hyperdocs — Session Discovery")
    print("=" * 60)
    print(f"Found {len(projects)} projects, {total_sessions} sessions, ~{total_messages:,} messages")
    print()

    for key, proj in projects.items():
        print(f"PROJECT: {proj['readable_name']} ({proj['total_sessions']} sessions, {proj['total_messages']:,} messages)")
        # Show top 3 sessions
        for s in proj["sessions"][:3]:
            user_msgs = s["messages"]["user"]
            asst_msgs = s["messages"]["assistant"]
            print(f"  {s['id'][:8]}  {s['modified_display']}  {format_size(s['size_bytes'])}  {user_msgs} user / {asst_msgs} assistant msgs")
        if len(proj["sessions"]) > 3:
            print(f"  ... and {len(proj['sessions']) - 3} more sessions")
        print()

    print(f"Discovery saved to: {discovery_path}")
    print()
    print("Next: run 'python3 concierge.py --process SESSION_ID' to start Phase 0")
    return discovery


def find_session(session_id, discovery=None):
    """Find a session file by ID (full or partial)."""
    if discovery is None:
        discovery_path = OUTPUT_BASE / "discovery.json"
        if discovery_path.exists():
            with open(discovery_path) as f:
                discovery = json.load(f)

    if discovery:
        for proj in discovery.get("projects", {}).values():
            for s in proj.get("sessions", []):
                if s["id"].startswith(session_id):
                    return s

    # Fallback: search directly
    for project_dir in CLAUDE_PROJECTS.iterdir():
        if not project_dir.is_dir():
            continue
        for jsonl in project_dir.glob(f"{session_id}*.jsonl"):
            return {"id": jsonl.stem, "path": str(jsonl)}

    return None


def process(session_id):
    """Run Phase 0 on a specific session."""
    session = find_session(session_id)
    if not session:
        print(f"ERROR: Session '{session_id}' not found.")
        print("Run 'python3 concierge.py --discover' first.")
        return False

    full_id = session["id"]
    session_path = session["path"]
    short_id = full_id[:8]
    session_output = OUTPUT_BASE / f"session_{short_id}"
    session_output.mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print(f"Hyperdocs — Processing Session {short_id}")
    print("=" * 60)
    print(f"Session: {full_id}")
    print(f"File:    {session_path}")
    print(f"Output:  {session_output}")
    print()

    # Set environment for Phase 0 scripts
    env = os.environ.copy()
    env["HYPERDOCS_SESSION_ID"] = full_id
    env["HYPERDOCS_CHAT_HISTORY"] = session_path
    env["HYPERDOCS_OUTPUT_DIR"] = str(OUTPUT_BASE)

    phase0_dir = HYPERDOCS_ROOT / "phase_0_prep"

    # Run deterministic_prep.py
    print("--- Phase 0a: Deterministic Prep ---")
    result = subprocess.run(
        [sys.executable, str(phase0_dir / "deterministic_prep.py")],
        env=env,
        cwd=str(phase0_dir),
    )
    if result.returncode != 0:
        print("ERROR: deterministic_prep.py failed")
        update_status(short_id, "phase_0", "FAILED")
        return False

    # Run prepare_agent_data.py
    print()
    print("--- Phase 0b: Prepare Agent Data ---")
    result = subprocess.run(
        [sys.executable, str(phase0_dir / "prepare_agent_data.py")],
        env=env,
        cwd=str(phase0_dir),
    )
    if result.returncode != 0:
        print("ERROR: prepare_agent_data.py failed")
        update_status(short_id, "phase_0", "FAILED")
        return False

    update_status(short_id, "phase_0", "COMPLETE")

    print()
    print("=" * 60)
    print("Phase 0 complete. Data ready for agent extraction.")
    print()
    print("Next steps (run in Claude Code):")
    print(f"  Phase 1: Launch 4 extraction agents (thread-analyst, geological-reader, primitives-tagger, free-explorer)")
    print(f"  Phase 2: Launch 2 synthesis agents (idea-graph-builder, synthesizer) + file_genealogy.py")
    print(f"  Phase 3: Launch file-mapper + 15 per-file hyperdoc-writer agents")
    print(f"  Phase 4: python3 phase_4_insertion/insert_hyperdocs_v2.py")
    print(f"  Phase 5: python3 phase_5_ground_truth/claim_extractor.py + verifier + reporter")
    print()
    print(f"Check status: python3 concierge.py --status")
    return True


def update_status(session_short, phase, state):
    """Update pipeline_status.json."""
    status_path = OUTPUT_BASE / f"session_{session_short}" / "pipeline_status.json"
    status = {}
    if status_path.exists():
        with open(status_path) as f:
            status = json.load(f)

    status[phase] = {
        "state": state,
        "updated_at": datetime.now().isoformat(),
    }
    status["session_id"] = session_short

    with open(status_path, "w") as f:
        json.dump(status, f, indent=2)


def show_status():
    """Show pipeline state for the most recent session."""
    # Find the most recently modified session output
    if not OUTPUT_BASE.exists():
        print("No output directory found. Run --discover first.")
        return

    session_dirs = sorted(
        [d for d in OUTPUT_BASE.iterdir() if d.is_dir() and d.name.startswith("session_")],
        key=lambda d: d.stat().st_mtime,
        reverse=True,
    )

    if not session_dirs:
        print("No sessions processed yet. Run --process first.")
        return

    latest = session_dirs[0]
    status_path = latest / "pipeline_status.json"

    print("=" * 60)
    print(f"Hyperdocs — Pipeline Status ({latest.name})")
    print("=" * 60)

    if status_path.exists():
        with open(status_path) as f:
            status = json.load(f)
    else:
        status = {}

    phases = [
        ("phase_0", "Deterministic Prep"),
        ("phase_1", "Agent Extraction"),
        ("phase_2", "Synthesis + Genealogy"),
        ("phase_3", "Hyperdoc Writing"),
        ("phase_4", "Smart Insertion"),
        ("phase_5", "Ground Truth"),
    ]

    for phase_key, phase_name in phases:
        info = status.get(phase_key, {})
        state = info.get("state", "PENDING")
        updated = info.get("updated_at", "")

        if state == "COMPLETE":
            icon = "DONE"
        elif state == "FAILED":
            icon = "FAIL"
        elif state == "IN_PROGRESS":
            icon = " >> "
        else:
            icon = "    "

        line = f"  [{icon}] {phase_name}"
        if updated:
            line += f"  ({updated[:16]})"
        print(line)

    # Check what output files exist
    print()
    print("Output files:")
    for f in sorted(latest.iterdir()):
        if f.is_file() and not f.name.startswith("."):
            print(f"  {f.name} ({format_size(f.stat().st_size)})")


def open_dashboard():
    """Generate and open the dashboard."""
    dashboard_script = HYPERDOCS_ROOT / "dashboard.py"
    if dashboard_script.exists():
        subprocess.run([sys.executable, str(dashboard_script)])
    else:
        print("Dashboard not yet built. Coming soon.")


def main():
    parser = argparse.ArgumentParser(description="Hyperdocs Concierge")
    parser.add_argument("--discover", action="store_true", help="Scan all Claude Code sessions")
    parser.add_argument("--process", metavar="SESSION_ID", help="Run Phase 0 on a session")
    parser.add_argument("--status", action="store_true", help="Show pipeline state")
    parser.add_argument("--dashboard", action="store_true", help="Open the dashboard")

    args = parser.parse_args()

    if args.discover:
        discover()
    elif args.process:
        process(args.process)
    elif args.status:
        show_status()
    elif args.dashboard:
        open_dashboard()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
