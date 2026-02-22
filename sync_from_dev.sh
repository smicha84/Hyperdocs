#!/bin/bash
# sync_from_dev.sh — Auto-sync Hyperdocs source code to GitHub
# Runs hourly via cron. Zero user input required.
#
# Source: hyperdocs_3/ (working dev copy inside pythonProjectartifact)
# Destination: ~/Hyperdocs/ (git repo connected to github.com/smicha84/Hyperdocs)

set -e

SRC="$HOME/PycharmProjects/pythonProject ARXIV4/pythonProjectartifact/.claude/hooks/hyperdoc/hyperdocs_3"
DEST="$HOME/Hyperdocs"
LOG_PREFIX="[$(date '+%Y-%m-%d %H:%M:%S')]"

# Check source exists
if [ ! -d "$SRC" ]; then
    echo "$LOG_PREFIX ERROR: Source directory not found: $SRC"
    exit 1
fi

# Rsync source files, excluding non-source content
rsync -a \
    --exclude='output/' \
    --exclude='obsolete/' \
    --exclude='archive_originals/' \
    --exclude='__pycache__/' \
    --exclude='.DS_Store' \
    --exclude='*.pdf' \
    --exclude='*.docx' \
    --exclude='convo txt.txt' \
    --exclude='archived_claude_md_gates.txt' \
    --exclude='.git/' \
    --exclude='sync_from_dev.sh' \
    --exclude='sync.log' \
    "$SRC/" "$DEST/"

# Check for changes
cd "$DEST"
if git diff --quiet && git diff --cached --quiet && [ -z "$(git ls-files --others --exclude-standard)" ]; then
    echo "$LOG_PREFIX No changes to sync"
    exit 0
fi

# Stage, commit, push
git add -A
CHANGED=$(git diff --cached --stat | tail -1)
git commit -m "Auto-sync: $CHANGED

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"

if ! git push; then
    echo "$LOG_PREFIX ERROR: git push failed"
    exit 1
fi

echo "$LOG_PREFIX Synced and pushed: $CHANGED"
