#!/usr/bin/env python3
"""
Hyperdocs Installer — One-time setup.

1. Copies /hyperdocs slash command to the user's .claude/commands/
2. Adds PostToolUse hook to .claude/settings.json (merges, doesn't overwrite)
3. Sets HYPERDOCS_PATH environment hint
4. Runs discovery to show available sessions
"""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

HYPERDOCS_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = Path.cwd()


def install_slash_command():
    """Copy the /hyperdocs command to the user's .claude/commands/."""
    commands_dir = PROJECT_ROOT / ".claude" / "commands"
    commands_dir.mkdir(parents=True, exist_ok=True)

    src = HYPERDOCS_ROOT / "commands" / "hyperdocs.md"
    dst = commands_dir / "hyperdocs.md"

    if not src.exists():
        print(f"  ERROR: Source command not found at {src}")
        return False

    # Read and replace $HYPERDOCS_PATH with actual path
    content = src.read_text()
    content = content.replace("$HYPERDOCS_PATH", str(HYPERDOCS_ROOT))

    dst.write_text(content)
    print(f"  Slash command installed: {dst}")
    return True


def install_hook():
    """Add the PostToolUse hook to .claude/settings.json."""
    settings_path = PROJECT_ROOT / ".claude" / "settings.json"

    # Read existing settings
    settings = {}
    if settings_path.exists():
        try:
            with open(settings_path) as f:
                settings = json.load(f)
        except json.JSONDecodeError:
            print(f"  WARN: Could not parse {settings_path}, creating new")

    # Ensure hooks structure exists
    if "hooks" not in settings:
        settings["hooks"] = {}
    if "PostToolUse" not in settings["hooks"]:
        settings["hooks"]["PostToolUse"] = []

    # Check if our hook is already installed
    hook_cmd = f"python3 {HYPERDOCS_ROOT}/realtime_hook.py"
    already_installed = any(
        hook_cmd in str(h.get("hooks", []))
        for h in settings["hooks"]["PostToolUse"]
        if isinstance(h, dict)
    )

    if already_installed:
        print("  Real-time hook already installed")
    else:
        settings["hooks"]["PostToolUse"].append({
            "matcher": "Edit|Write",
            "hooks": [{
                "type": "command",
                "command": hook_cmd,
                "async": True,
                "timeout": 5,
            }],
        })

        with open(settings_path, "w") as f:
            json.dump(settings, f, indent=2)
        print(f"  Real-time hook installed in: {settings_path}")

    return True


def set_env_hint():
    """Create a .env file with HYPERDOCS_PATH for the slash command."""
    env_path = PROJECT_ROOT / ".claude" / "hyperdocs.env"
    env_path.write_text(f"HYPERDOCS_PATH={HYPERDOCS_ROOT}\n")
    print(f"  Environment hint: {env_path}")

    # Also set it for the current shell session
    os.environ["HYPERDOCS_PATH"] = str(HYPERDOCS_ROOT)


def run_discovery():
    """Run the concierge discovery."""
    print()
    subprocess.run([sys.executable, str(HYPERDOCS_ROOT / "concierge.py"), "--discover"])


def main():
    print("=" * 60)
    print("Hyperdocs — Installation")
    print("=" * 60)
    print(f"Installing from: {HYPERDOCS_ROOT}")
    print(f"Installing to:   {PROJECT_ROOT}")
    print()

    # Step 1: Slash command
    print("Step 1: Slash command")
    if not install_slash_command():
        return

    # Step 2: Real-time hook
    print()
    print("Step 2: Real-time hook")
    if not install_hook():
        return

    # Step 3: Environment
    print()
    print("Step 3: Environment")
    set_env_hint()

    # Step 4: Discovery
    print()
    print("Step 4: Session discovery")
    run_discovery()

    print()
    print("=" * 60)
    print("Hyperdocs installed.")
    print()
    print("Type /hyperdocs in your next Claude Code session to start.")
    print("Real-time capture is active — Edit/Write operations are being recorded.")
    print("=" * 60)


if __name__ == "__main__":
    main()
