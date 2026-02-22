"""
Hyperdocs Configuration — Central settings for all phases.

All scripts import from here. Override with environment variables:
    HYPERDOCS_SESSION_ID     — Session UUID to process
    HYPERDOCS_CHAT_HISTORY   — Path to JSONL file
    HYPERDOCS_OUTPUT_DIR     — Where pipeline writes outputs
    HYPERDOCS_ARCHIVE_PATH   — Path to PERMANENT_ARCHIVE (optional)
    HYPERDOCS_PROJECT_ID     — Claude Code project identifier (optional)
    ANTHROPIC_API_KEY        — Required for phases 1-3
"""
import os
import sys
from pathlib import Path

# ── Session ────────────────────────────────────────────────────
SESSION_ID = os.getenv("HYPERDOCS_SESSION_ID", "")
SESSION_SHORT = SESSION_ID[:8] if SESSION_ID else ""

# ── Paths ──────────────────────────────────────────────────────
REPO_ROOT = Path(__file__).resolve().parent
CLAUDE_SESSIONS_DIR = Path.home() / ".claude" / "projects"

# Chat history input
CHAT_HISTORY_PATH = os.getenv("HYPERDOCS_CHAT_HISTORY", "")

# Canonical chat history directory (all sessions, never deleted)
CHAT_HISTORY_DIR = Path(os.getenv(
    "HYPERDOCS_CHAT_HISTORY_DIR",
    str(Path.home() / "PERMANENT_CHAT_HISTORY" / "sessions")
))

# Output directory
OUTPUT_DIR = Path(os.getenv("HYPERDOCS_OUTPUT_DIR", str(REPO_ROOT / "output")))

# PERMANENT_ARCHIVE (optional, for bulk processing)
ARCHIVE_PATH = os.getenv("HYPERDOCS_ARCHIVE_PATH", "")

# Claude Code project identifier (for session file lookup)
PROJECT_ID = os.getenv("HYPERDOCS_PROJECT_ID", "")

# ── V5 Source Code Directory ──────────────────────────────────
# Phase 4 (insertion) reads source files from disk.
# The improved modules live directly in phase_0_prep/ (v5_compat dissolved).
V5_SOURCE_DIR = Path(os.getenv(
    "HYPERDOCS_V5_SOURCE",
    str(REPO_ROOT / "phase_0_prep")
))

# ── Permanent Storage ─────────────────────────────────────────
STORE_DIR = Path(os.getenv("HYPERDOCS_STORE_DIR", str(Path.home() / "PERMANENT_HYPERDOCS")))
SESSIONS_STORE_DIR = STORE_DIR / "sessions"
INDEXES_DIR = STORE_DIR / "indexes"
HYPERDOCS_STORE_DIR = STORE_DIR / "hyperdocs"
CHAT_ARCHIVE_DIR = Path(os.getenv("HYPERDOCS_CHAT_ARCHIVE", str(Path.home() / "PERMANENT_CHAT_HISTORY")))

# ── Helpers ────────────────────────────────────────────────────

def get_session_output_dir():
    """Get or create the output directory for the current session."""
    if SESSION_SHORT:
        out = OUTPUT_DIR / f"session_{SESSION_SHORT}"
    else:
        out = OUTPUT_DIR / "session"
    out.mkdir(parents=True, exist_ok=True)
    return out


def get_session_file():
    """Find the JSONL chat history file."""
    if CHAT_HISTORY_PATH:
        p = Path(CHAT_HISTORY_PATH)
        if p.exists():
            return p

    if SESSION_ID and PROJECT_ID:
        candidate = CLAUDE_SESSIONS_DIR / PROJECT_ID / f"{SESSION_ID}.jsonl"
        if candidate.exists():
            return candidate

    # Check permanent chat history directory
    if SESSION_ID and CHAT_HISTORY_DIR.exists():
        candidate = CHAT_HISTORY_DIR / f"{SESSION_ID}.jsonl"
        if candidate.exists():
            return candidate

    if SESSION_ID:
        for project_dir in CLAUDE_SESSIONS_DIR.iterdir():
            if not project_dir.is_dir():
                continue
            candidate = project_dir / f"{SESSION_ID}.jsonl"
            if candidate.exists():
                return candidate

    return None

# ======================================================================
# @ctx HYPERDOC — HISTORICAL (generated 2026-02-08, requires realtime update)
# These annotations are from the Phase 4b bulk processing run across 284
# sessions. The code below may have changed since these markers were
# generated. Markers reflect the state of the codebase as of Feb 8, 2026.
# ======================================================================

# --- HEADER ---
# ===========================================================================
# HYPERDOC HEADER: config.py
# @ctx:version=1 @ctx:source_sessions=conv_17f28a6a,conv_3f08a820,conv_4953cc6b,conv_557ba4c2,conv_636caafa,conv_79247a7b,conv_bb648cb9,conv_d69cce9f
# @ctx:generated=2026-02-08T22:30:00Z
# @ctx:total_mentions=8 @ctx:sessions=8 @ctx:edits=1 @ctx:churn_rank=1/15
# @ctx:emotion=neutral @ctx:confidence=working @ctx:maturity=stable
# @ctx:failed_approaches=2
# ===========================================================================
#
# --- STORY ARC ---
#
# config.py was created during the Hyperdocs 3 system build (session 4953cc6b,
# Feb 7, 2026) to solve a specific problem: every pipeline script had hardcoded
# paths and session IDs baked into it, making the system impossible to run on
# any session other than the reference session 3b7084d5. The user demanded the
# system be portable, and config.py was the answer: centralize all paths and
# session identifiers into one module with environment variable overrides. The
# file was validated when Phase 0 was tested on a fresh session (513d4807) and
# processed 190 messages without modification, proving the configuration
# abstraction worked. config.py is now imported by 4 pipeline scripts
# (deterministic_prep.py, extract_threads.py, prepare_agent_data.py,
# file_genealogy.py) and has not been modified since creation. It is one of
# the lowest-churn files in the system, which is the correct behavior for a
# configuration module: write once, reference everywhere.
#
# --- FRICTION: WHAT WENT WRONG AND WHY ---
#
# @ctx:friction="All pipeline scripts had hardcoded paths and session IDs before config.py was created, making the system non-portable"
# @ctx:trace=conv_4953cc6b:msg554
#   [F01] Before config.py existed, deterministic_prep.py, extract_threads.py,
#   and other Phase 0-2 scripts contained hardcoded paths like
#   '/Users/stefanmichaelcheck/PycharmProjects/.../output/session_3b7084d5/'
#   and hardcoded session IDs like '3b7084d5'. Running on any other session
#   required manual find-and-replace across multiple files. This was identified
#   during the Hyperdocs 3 system organization in session 4953cc6b and fixed by
#   extracting all path/session logic into config.py with env var overrides.
#
# @ctx:friction="P01 parsing logic must handle Python config files like config.py, which have different patterns than source code"
# @ctx:trace=conv_79247a7b:msg24
#   [F02] During the P01 fragility investigation in session 79247a7b, config.py
#   was identified as one of 13 files that P01 parsing must handle correctly.
#   The synthesis notes: 'The diversity of file types (including config.py as
#   Python config) demonstrates that P01 must parse configuration files, not
#   just source code.' Config files use module-level constants and os.getenv()
#   patterns that differ from typical function/class source code. If P01 uses
#   regex-based parsing optimized for source code patterns, it may misinterpret
#   config.py's assignment-heavy structure.
#
# @ctx:friction="The cross_session_file_index.json aggregator marked config.py as exists_on_disk=true despite the file existing at hyperdocs_3/config.py"
# @ctx:trace=conv_4953cc6b:msg685
#   [F03] The Phase 4a aggregation script (aggregate_dossiers.py) records
#   exists_on_disk=true for config.py. This is a false negative caused by the
#   aggregator searching for config.py at the repository root or in .claude/hooks/
#   rather than at its actual location inside hyperdocs_3/. The file is 69 lines
#   of Python at .claude/hooks/hyperdoc/hyperdocs_3/config.py. This same path
#   confusion affected session bb648cb9's dossier, which describes config.py as
#   'peripheral configuration module' for the VibeCodingGuard gate system, when
#   the actual config.py in the dossier corpus refers to the hyperdocs pipeline
#   configuration. The generic name 'config.py' creates ambiguity across contexts.
#
# --- DECISIONS: CHOSE X OVER Y BECAUSE Z ---
#
# @ctx:decision="chose environment variable overrides over a JSON/YAML config file because env vars work without additional file parsing dependencies and integrate with shell-based agent spawning"
# @ctx:trace=conv_4953cc6b:msg554
#   Alternatives considered: JSON config file (config.json), YAML config, .env
#   file with python-dotenv, command-line arguments via argparse
#   Why rejected: JSON/YAML would require an additional parsing dependency and
#   a separate config file to manage. The batch_orchestrator.py spawns agents
#   via subprocess with environment variables already (HYPERDOCS_SESSION_ID,
#   ANTHROPIC_API_KEY). Using os.getenv() in config.py means the same env vars
#   that the orchestrator sets are consumed directly, with no intermediate file.
#   Command-line arguments would require every importing script to implement
#   argparse, increasing boilerplate.
#
# @ctx:decision="chose Path(__file__).resolve().parent for REPO_ROOT over hardcoded absolute paths because it makes the system relocatable"
# @ctx:trace=conv_4953cc6b:msg554
#   Alternatives considered: hardcoded path string, Path.home() relative path,
#   git root detection via subprocess
#   Why rejected: Hardcoded paths were the problem being solved. Path.home()
#   relative paths would break if the repo is not under the home directory.
#   Git root detection via subprocess would add latency and would fail in
#   non-git contexts. Path(__file__).resolve().parent is zero-dependency,
#   zero-latency, and works regardless of where the repo is cloned.
#
# @ctx:decision="chose a flat module with constants over a Config class with methods because the configuration surface is small (6 values) and does not need instance management"
# @ctx:trace=conv_4953cc6b:msg554
#   Alternatives considered: Config dataclass, singleton Config class,
#   ConfigParser-based approach
#   Why rejected: With only 6 configuration values (SESSION_ID, CHAT_HISTORY_PATH,
#   OUTPUT_DIR, ARCHIVE_PATH, PROJECT_ID, REPO_ROOT) and 2 helper functions,
#   a class would add ceremony without benefit. Importers use
#   'from config import SESSION_ID, get_session_output_dir' which is cleaner
#   than 'Config.instance().session_id'. The flat module pattern matches the
#   stdlib os.path convention.
#
# --- WARNINGS ---
#
# @ctx:warning="[W01] [medium] SESSION_ID defaults to empty string, which causes get_session_output_dir() to use the generic path 'output/session' instead of a session-specific path, potentially causing output collisions if multiple sessions are processed sequentially without setting the env var"
# @ctx:trace=conv_4953cc6b:msg554
#   Resolution: UNRESOLVED
#   Evidence: Line 17: SESSION_ID = os.getenv('HYPERDOCS_SESSION_ID', ''). Line 43:
#   out = OUTPUT_DIR / 'session' (fallback when SESSION_SHORT is empty). If a script
#   imports config without setting HYPERDOCS_SESSION_ID, outputs go to a shared
#   'output/session/' directory. The batch_orchestrator.py sets HYPERDOCS_SESSION_ID
#   before launching agents, so this is not a problem in orchestrated runs, but it
#   is a footgun for manual/ad-hoc script execution.
#
# @ctx:warning="[W02] [low] get_session_file() scans all project directories under ~/.claude/projects/ when PROJECT_ID is not set, which could be slow with many projects and could return the wrong session if the same session ID exists under multiple projects"
# @ctx:trace=conv_4953cc6b:msg554
#   Resolution: UNRESOLVED
#   Evidence: Lines 60-66: the fallback loop iterates CLAUDE_SESSIONS_DIR.iterdir()
#   and returns the first match. If ~/.claude/projects/ contains many subdirectories,
#   this scan has O(n) cost per directory. More critically, if two projects have a
#   session file with the same UUID prefix, the first match wins regardless of which
#   project is correct. Setting HYPERDOCS_PROJECT_ID prevents this ambiguity.
#
# @ctx:warning="[W03] [medium] The generic filename 'config.py' creates dossier ambiguity across 8 sessions -- some sessions reference the hyperdocs pipeline config, others reference VibeCodingGuard gate system config, and the aggregator cannot distinguish them"
# @ctx:trace=conv_bb648cb9:msg0
#   Resolution: UNRESOLVED
#   Evidence: Session bb648cb9 dossier describes config.py as 'peripheral
#   configuration module for the gate system' with cross_references to
#   gate_controller.py and subagent_runner.py. Session d69cce9f describes it as
#   'configuration file that gates depend on for thresholds, mode settings, and
#   runtime parameters.' Neither of these descriptions matches the actual hyperdocs_3/
#   config.py which handles pipeline session IDs and output paths. The name collision
#   means Phase 4 dossier aggregation may mix signals from different config.py files
#   across the codebase.
#
# --- IRON RULES ---
#
# - Output files are NOT part of the system -- the output directory config.py
#   points to (OUTPUT_DIR) contains user data, not system files.
# - NEVER delete code/imports without asking -- config.py's imports and constants
#   represent design intent even if they appear unused in some analysis contexts.
#
# --- CLAUDE BEHAVIOR ON THIS FILE ---
#
# @ctx:claude_pattern="impulse_control: good -- config.py was created as a focused 69-line module without scope creep. No database connections, no logging configuration, no feature flags were added beyond the 6 values needed."
# @ctx:claude_pattern="authority_response: responsive -- The user's requirement to remove hardcoded paths was directly translated into env var overrides. No deviation from the directive."
# @ctx:claude_pattern="overconfidence: low -- The file was validated on a fresh session (513d4807) before being declared working. No premature victory claims."
# @ctx:claude_pattern="context_damage: none -- The file has not been modified since creation. No edits have introduced regressions."
#
# --- EMOTIONAL CONTEXT ---
#
# No direct user emotional reactions are tied to config.py specifically. The
# file was created during the Hyperdocs 3 organization session (4953cc6b) where
# the user's primary emotion was relief at getting the system organized into
# phase folders with proper configuration. The user's earlier frustration
# (Chapter 5 in MEMORY.md: 'you are completely rushing through all this',
# 'ALL I CARE ABOUT IS A WORKING, HEALTHY HYPERDOCS SYSTEM') was the
# motivating force behind creating proper infrastructure like config.py.
# The fact that config.py enabled successful testing on a fresh session
# (513d4807) was a positive validation moment.
#
# --- FAILED APPROACHES ---
#
# @ctx:failed_approaches=2
# [ABANDONED] Hardcoded paths in each pipeline script -> config.py centralization (conv_4953cc6b:msg554)
#   Every pipeline script originally contained its own hardcoded paths to the
#   output directory and session data. This approach failed immediately when
#   the system needed to process any session other than the reference session
#   3b7084d5. The fix was to extract all path logic into config.py.
#
# [CONSTRAINED] Generic name 'config.py' -> ambiguous dossier aggregation (conv_bb648cb9:msg0)
#   The name 'config.py' is used by multiple subsystems in the repository:
#   the hyperdocs pipeline config (this file), VibeCodingGuard gate system
#   config (referenced in bb648cb9, d69cce9f), and potentially other config
#   modules. The Phase 4a aggregator (aggregate_dossiers.py) merges dossiers
#   by filename, so all references to any 'config.py' are aggregated into a
#   single entry. This introduces noise into the dossier. A namespaced filename
#   like 'hyperdocs_config.py' would prevent this collision but was not adopted.
#
# --- RECOMMENDATIONS ---
#
# [R01] (priority: medium)
#   Add a validation function that raises a clear error when SESSION_ID is empty
#   and a script attempts to use session-dependent paths. Currently, empty SESSION_ID
#   silently produces the generic 'output/session/' path, which can cause output
#   collisions.
#   Evidence: Line 17 defaults to empty string; Line 43 falls through silently.
#
# [R02] (priority: low)
#   Consider renaming to 'hyperdocs_config.py' or 'pipeline_config.py' to avoid
#   name collision with other config.py files in the codebase. This would require
#   updating 4 import statements (deterministic_prep.py, extract_threads.py,
#   prepare_agent_data.py, file_genealogy.py) and the aggregator would produce
#   cleaner dossier data.
#   Evidence: Sessions bb648cb9 and d69cce9f dossiers conflate this file with
#   VibeCodingGuard gate config.
#
# [R03] (priority: low)
#   Add ANTHROPIC_API_KEY to config.py (currently documented in the docstring
#   at line 10 but not assigned to a variable). Scripts that need the API key
#   currently call os.getenv('ANTHROPIC_API_KEY') independently, which is
#   inconsistent with the centralization pattern.
#   Evidence: Line 10 documents ANTHROPIC_API_KEY but config.py does not export it.
#
# ===========================================================================

# --- FOOTER ---
# ===========================================================================
# HYPERDOC FOOTER: config.py
# @ctx:version=1 @ctx:source_sessions=conv_17f28a6a,conv_3f08a820,conv_4953cc6b,conv_557ba4c2,conv_636caafa,conv_79247a7b,conv_bb648cb9,conv_d69cce9f
# @ctx:generated=2026-02-08T22:30:00Z
# ===========================================================================
#
# --- VERSION HISTORY ---
# v1 (2026-02-08): Initial extraction from 8 sessions (17f28a6a, 3f08a820, 4953cc6b, 557ba4c2, 636caafa, 79247a7b, bb648cb9, d69cce9f)
#
# --- RELATED FILES ---
# deterministic_prep.py -- Imports get_session_output_dir, SESSION_ID, get_session_file from config.py. The primary Phase 0 script that enriches raw session data. config.py was created specifically to decouple this file from hardcoded paths.
# extract_threads.py -- Imports get_session_output_dir from config.py. Phase 1 thread extraction agent script that writes output to the session-specific directory.
# prepare_agent_data.py -- Imports get_session_output_dir from config.py. Prepares safe_*.json files for Phase 1 agents.
# file_genealogy.py -- Imports get_session_output_dir and SESSION_ID from config.py. Phase 2 synthesis script that tracks file identity across renames.
# batch_orchestrator.py -- Sets HYPERDOCS_SESSION_ID environment variable before spawning agents. The orchestrator is the primary consumer of config.py's env var interface, though it does not import config.py directly.
# aggregate_dossiers.py -- Phase 4a aggregation script that indexed config.py across sessions but incorrectly marked it as exists_on_disk=true due to path resolution issues.
#
# --- METRICS ---
# Total mentions: 8 (across sessions, with name-collision caveat) | Edits: 1 (creation) | Failed attempts: 2
# Churn rank: 1/15 (lowest churn -- file has not been modified since creation, which is correct behavior for a config module)
#
# --- IDEA GRAPH SUBGRAPHS ---
# [Hardcoded Path Elimination] (3 nodes)
#   N1 (Hardcoded Paths in Pipeline Scripts, state=broken, confidence=fragile)
#   --[pivoted]--> N2 (Centralized Config Module with Env Var Overrides, state=proposed, confidence=tentative)
#   --[concretized]--> N3 (config.py Created and Validated on Fresh Session 513d4807, state=working, confidence=stable)
#   This subgraph represents the transition from hardcoded paths scattered across pipeline scripts to a single config module.
#   N1 captures the original problem: deterministic_prep.py, extract_threads.py, and other scripts each contained
#   absolute paths to /Users/stefanmichaelcheck/.../output/session_3b7084d5/. N2 is the proposed solution: a config.py
#   module using os.getenv() with sensible defaults. N3 is the validated outcome: config.py was tested on session
#   513d4807 (190 messages processed, $0 cost for Phase 0) and confirmed working. The pivot from N1 to N2 was not
#   a gradual evolution but a single refactoring decision during the Hyperdocs 3 organization session (4953cc6b).
#
# [P01 Parsing Target Surface] (2 nodes, cross-session reference)
#   N_P01 (P01 Fragility Investigation, state=active, confidence=fragile, session=79247a7b)
#   --[split]--> N_CONFIG (config.py as Parsing Target, state=identified, confidence=working)
#   config.py was identified as one of 13 files in the P01 parsing target surface during session 79247a7b.
#   The fragility investigation found that P01 must correctly parse configuration files (assignment-heavy,
#   os.getenv() patterns) alongside source code files (function/class definitions). config.py represents the
#   'Python config file' class within the P01 fragility taxonomy.
#
# --- SESSION-WIDE METRICS (for context) ---
# [M01] Session 4953cc6b is the primary creation session: 685 messages, 15 per-file agents launched in parallel, 22-34KB hyperdocs per file. config.py was created as infrastructure during the system organization phase.
# [M02] Session 79247a7b fragility investigation: 25 messages, 127 seconds, 672K input tokens. config.py was one of 13 files in the P01 parsing target surface (5 mentions across extraction outputs).
# [M03] Session bb648cb9 P16 investigation: config.py listed as tier 3 peripheral with cross-dependencies to subagent_runner.py and gate_controller.py. This likely references a different config.py in the VibeCodingGuard gate system, not the hyperdocs pipeline config.
# [M04] Session d69cce9f gate audit: config.py listed as tier 2 supporting infrastructure for 12 gate enforcers. Same name-collision caveat as M03.
#
# --- UNFINISHED BUSINESS: GROUND TRUTH VERIFICATION ---
#
# @ctx:claims_verified=2 @ctx:claims_failed=1 @ctx:claims_unverified=2
# @ctx:credibility_score=2/3
#
# [VERIFIED] config.py exists on disk at .claude/hooks/hyperdoc/hyperdocs_3/config.py
# @ctx:claim_verified="config.py exists and is importable by pipeline scripts"
#   Glob search confirmed file at hyperdocs_3/config.py. 69 lines of Python.
#   4 pipeline scripts successfully import from it.
#
# [VERIFIED] config.py enables session portability via env var overrides
# @ctx:claim_verified="Phase 0 successfully ran on fresh session 513d4807 using config.py env var overrides"
#   MEMORY.md Chapter 14 records: 'Phase 0 tested on fresh session 513d4807: PASSED
#   (190 msgs processed)'. This validates that config.py's env var abstraction works
#   for sessions other than the reference session 3b7084d5.
#
# [CONTRADICTED] cross_session_file_index.json records exists_on_disk=true for config.py
# @ctx:claim_failed="config.py does not exist on disk"
# @ctx:expected="exists_on_disk=true"
# @ctx:actual="File exists at .claude/hooks/hyperdoc/hyperdocs_3/config.py (69 lines). The aggregator searched the wrong directory or did not resolve the path relative to the hyperdocs_3 package."
#   The aggregate_dossiers.py script checks file existence but may use a search path
#   that does not include the hyperdocs_3 directory. This false negative means the
#   aggregator's exists_on_disk field is unreliable for files inside hyperdocs_3/.
#
# [UNVERIFIED] Whether sessions bb648cb9 and d69cce9f reference this specific config.py or a different config.py in the gate system
# @ctx:unverified_claim="Sessions bb648cb9 and d69cce9f reference the same config.py file" @ctx:verification_method=path_comparison
# @ctx:status=unverified
#   Why it matters: If those sessions reference a different config.py (e.g., in the
#   VibeCodingGuard gate system root), then 2 of the 8 session references in this
#   hyperdoc are noise. The dossier aggregation by filename cannot distinguish them.
#
# [UNVERIFIED] Whether ANTHROPIC_API_KEY documentation in docstring matches actual usage across all pipeline scripts
# @ctx:unverified_claim="ANTHROPIC_API_KEY is documented at line 10 as required for phases 1-3" @ctx:verification_method=grep_codebase
# @ctx:status=unverified
#   Why it matters: If some pipeline scripts look for the API key under a different
#   env var name or in a different location, the docstring creates a false sense of
#   centralization. A codebase-wide grep for ANTHROPIC_API_KEY would confirm.
#
# [UNMONITORED] No test exists to verify config.py's env var override behavior
# @ctx:regression_risk="env var overrides could silently break if default values change" @ctx:guard=none
#   Risk: If someone changes the default value of OUTPUT_DIR from REPO_ROOT/'output'
#   to something else, all pipeline scripts that rely on the default would silently
#   write to a different directory. No test asserts the expected default values.
#
# ===========================================================================
# END HYPERDOC: config.py
# ===========================================================================
