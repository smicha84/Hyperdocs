#!/usr/bin/env python3
"""
Hyperdocs CLI — Unified command-line interface.

Usage:
    hyperdocs install              Set up slash command + hook in Claude Code
    hyperdocs discover             Scan and list available sessions
    hyperdocs process SESSION_ID   Run the pipeline on a session
    hyperdocs status               Show pipeline status for all sessions
    hyperdocs dashboard [SESSION]  Generate and open the HTML dashboard
    hyperdocs cost SESSION_ID      Show cost estimate for a session
"""
import argparse
import os
import subprocess
import sys
from pathlib import Path

# Resolve the package root (parent of hyperdocs/ package dir)
_PACKAGE_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _PACKAGE_DIR.parent

# Ensure the repo root is on sys.path so tools/, product/, etc. can be imported
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


def cmd_install(args):
    """Set up Hyperdocs slash command and PostToolUse hook."""
    from product.install import main as install_main
    install_main()


def cmd_discover(args):
    """Scan all Claude Code sessions and show what's available."""
    from product.concierge import discover
    discover()


def cmd_process(args):
    """Run the pipeline on a session."""
    # Build the equivalent run_pipeline.py command
    cmd = [sys.executable, str(_REPO_ROOT / "tools" / "run_pipeline.py"), args.session_id]
    if args.full:
        cmd.append("--full")
    if args.phase is not None:
        cmd.extend(["--phase", str(args.phase)])
    if args.force:
        cmd.append("--force")
    if args.dry_run:
        cmd.append("--dry-run")
    if args.budget is not None:
        cmd.extend(["--budget", str(args.budget)])
    if args.normalize:
        cmd.append("--normalize")

    env = {**os.environ, "PYTHONPATH": str(_REPO_ROOT)}
    result = subprocess.run(cmd, env=env)
    sys.exit(result.returncode)


def _collect_status_data():
    """Collect status data for all sessions. Returns dict of {sid: info}."""
    import json
    output_dir = _REPO_ROOT / "output"
    permanent_dir = Path.home() / "PERMANENT_HYPERDOCS" / "sessions"

    sessions = {}
    for search_dir in [output_dir, permanent_dir]:
        if not search_dir.exists():
            continue
        for d in sorted(search_dir.iterdir()):
            if not d.is_dir() or not d.name.startswith("session_"):
                continue
            sid = d.name.replace("session_", "")
            if sid in sessions:
                continue
            phases = {}
            phases["0"] = (d / "enriched_session.json").exists()
            phases["0b"] = (d / "session_metadata.json").exists()
            phases["1"] = (d / "thread_extractions.json").exists()
            phases["2"] = (d / "idea_graph.json").exists()
            phases["3"] = (d / "file_dossiers.json").exists()
            cost_file = d / "session_cost.json"
            cost = None
            if cost_file.exists():
                try:
                    cost = json.loads(cost_file.read_text()).get("total_cost_usd")
                except Exception:
                    pass
            loc = "permanent" if "PERMANENT" in str(d) else "output"
            sessions[sid] = {"dir": str(d), "phases": phases, "cost": cost, "location": loc}
    return sessions


def cmd_status(args):
    """Show pipeline status for all processed sessions."""
    sessions = _collect_status_data()

    if not sessions:
        if getattr(args, 'format', None) == 'json':
            import json
            print(json.dumps({"sessions": [], "total": 0, "complete": 0}))
        else:
            print("No processed sessions found.")
        return

    if getattr(args, 'format', None) == 'json':
        import json
        total = len(sessions)
        complete = sum(1 for s in sessions.values() if all(s["phases"].values()))
        output = {
            "sessions": [
                {"session_id": sid, **{k: v for k, v in info.items() if k != "dir"}}
                for sid, info in sorted(sessions.items())
            ],
            "total": total,
            "complete": complete,
        }
        print(json.dumps(output, indent=2))
        return

    print(f"{'Session':<12} {'P0':>3} {'P0b':>4} {'P1':>3} {'P2':>3} {'P3':>3} {'Cost':>8}  Location")
    print(f"{'-'*12} {'-'*3} {'-'*4} {'-'*3} {'-'*3} {'-'*3} {'-'*8}  {'-'*20}")

    for sid, info in sorted(sessions.items()):
        p = info["phases"]
        marks = [
            "Y" if p.get("0") else ".",
            " Y" if p.get("0b") else " .",
            "Y" if p.get("1") else ".",
            "Y" if p.get("2") else ".",
            "Y" if p.get("3") else ".",
        ]
        cost_str = f"${info['cost']:.2f}" if info["cost"] else "—"
        print(f"{sid:<12} {marks[0]:>3} {marks[1]:>4} {marks[2]:>3} {marks[3]:>3} {marks[4]:>3} {cost_str:>8}  {info['location']}")

    total = len(sessions)
    complete = sum(1 for s in sessions.values() if all(s["phases"].values()))
    print(f"\n{total} sessions, {complete} fully complete")


def cmd_dashboard(args):
    """Generate and open the HTML dashboard."""
    cmd = [sys.executable, str(_REPO_ROOT / "product" / "concierge.py"), "--dashboard"]
    if args.session_id:
        cmd.extend(["--session", args.session_id])
    env = {**os.environ, "PYTHONPATH": str(_REPO_ROOT)}
    result = subprocess.run(cmd, env=env)
    sys.exit(result.returncode)


def cmd_cost(args):
    """Show cost estimate for a session."""
    cmd = [sys.executable, str(_REPO_ROOT / "tools" / "run_pipeline.py"),
           args.session_id, "--dry-run"]
    env = {**os.environ, "PYTHONPATH": str(_REPO_ROOT)}
    result = subprocess.run(cmd, env=env)
    sys.exit(result.returncode)


def main():
    parser = argparse.ArgumentParser(
        prog="hyperdocs",
        description="Hyperdocs — Extract knowledge from Claude Code chat history",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Subcommands:
  install              Set up slash command + hook in Claude Code
  discover             Scan and list available sessions
  process SESSION_ID   Run the pipeline on a session
  status               Show pipeline status for all sessions
  dashboard [SESSION]  Generate and open the HTML dashboard
  cost SESSION_ID      Show cost estimate for a session

Examples:
  hyperdocs install
  hyperdocs discover
  hyperdocs process 1c9e0a77 --dry-run
  hyperdocs process 1c9e0a77 --full --budget 15.00
  hyperdocs status
  hyperdocs cost 1c9e0a77
        """,
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s 0.3.0")
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # install
    subparsers.add_parser("install", help="Set up slash command + hook in Claude Code")

    # discover
    subparsers.add_parser("discover", help="Scan and list available sessions")

    # process
    p_process = subparsers.add_parser("process", help="Run the pipeline on a session")
    p_process.add_argument("session_id", help="Session UUID (full or first 8 chars)")
    p_process.add_argument("--full", action="store_true", help="Run all phases including Opus")
    p_process.add_argument("--phase", type=int, choices=[0, 1, 2, 3], help="Run only this phase")
    p_process.add_argument("--force", action="store_true", help="Re-run even if output exists")
    p_process.add_argument("--dry-run", action="store_true", help="Estimate costs only")
    p_process.add_argument("--budget", type=float, metavar="USD", help="Max USD to spend")
    p_process.add_argument("--normalize", action="store_true", help="Run schema normalizer")

    # status
    p_status = subparsers.add_parser("status", help="Show pipeline status for all sessions")
    p_status.add_argument("--format", choices=["text", "json"], default="text",
                          help="Output format (default: text)")

    # dashboard
    p_dash = subparsers.add_parser("dashboard", help="Generate and open the HTML dashboard")
    p_dash.add_argument("session_id", nargs="?", default=None, help="Session ID (optional)")

    # cost
    p_cost = subparsers.add_parser("cost", help="Show cost estimate for a session")
    p_cost.add_argument("session_id", help="Session UUID (full or first 8 chars)")

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        sys.exit(0)

    commands = {
        "install": cmd_install,
        "discover": cmd_discover,
        "process": cmd_process,
        "status": cmd_status,
        "dashboard": cmd_dashboard,
        "cost": cmd_cost,
    }
    commands[args.command](args)


if __name__ == "__main__":
    main()
