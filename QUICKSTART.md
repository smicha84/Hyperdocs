# Hyperdocs Quickstart

Get from zero to working hyperdocs in 5 steps.

## Prerequisites

- Python 3.9+
- Claude Code installed
- Anthropic API key (for Phases 1-3; Phase 0 is free)

## Step 1: Install

```bash
pip install .
hyperdocs install
```

This copies the `/hyperdocs` slash command to your project's `.claude/commands/`
and adds the real-time PostToolUse hook to `.claude/settings.json`.

## Step 2: Configure

Create a `.env` file with your API key:

```bash
cp .env.example .env
# Edit .env and add your ANTHROPIC_API_KEY
```

## Step 3: Discover sessions

```bash
hyperdocs discover
```

Shows all Claude Code sessions available for processing, grouped by project.

## Step 4: Estimate cost and process

```bash
# See what it will cost (no API calls)
hyperdocs cost SESSION_ID

# Run free phases only (Phase 0 + 2)
hyperdocs process SESSION_ID

# Run all phases with a budget cap
hyperdocs process SESSION_ID --full --budget 15.00
```

## Step 5: View results

```bash
# Check what's been processed
hyperdocs status

# Open the dashboard
hyperdocs dashboard SESSION_ID
```

## What each phase does

| Phase | Cost | What it does |
|-------|------|-------------|
| 0 | Free | Deterministic metadata extraction from chat history |
| 0b | Free | Prepare agent data (split enriched session into safe files) |
| 0c | ~$15 | Opus message classification (replaces Python tier heuristics) |
| 1 | ~$45 | 4 Opus agents extract threads, geological layers, primitives |
| 2 | Free | Deterministic synthesis (idea graph, grounded markers) |
| 3 | Free | Generate file dossiers and HTML viewer |

## CLI Reference

```
hyperdocs install              Set up slash command + hook
hyperdocs discover             Scan and list sessions
hyperdocs process SESSION_ID   Run pipeline
hyperdocs status               Show all session status
hyperdocs dashboard [SESSION]  Open HTML dashboard
hyperdocs cost SESSION_ID      Estimate processing cost
```

### Process flags

```
--full          Run all phases (including Opus)
--phase N       Run only phase N (0, 1, 2, or 3)
--dry-run       Estimate costs without running
--budget USD    Stop if costs would exceed budget
--force         Re-run even if output exists
--normalize     Run schema normalizer
```
