# OPUS TRANSFORMATION: Replace JSON parsing heuristics and timestamp extraction
#                      with Opus-based semantic understanding of chat messages
################################################################################

#!/usr/bin/env python3
"""
Geological Reader - OPUS EDITION

WHAT CHANGED:
- Message parsing: Was JSON field extraction → Now Opus understands message structure
- Timestamp extraction: Was datetime parsing → Now Opus interprets various formats
- Content extraction: Was nested dict traversal → Now Opus extracts meaningful content
- Statistics: Was manual counting → Now Opus provides semantic analysis

OPUS READS AND UNDERSTANDS. Python handles file I/O.
"""
#ARCHITECTURE: Opus wrapper around chat history - delegates ALL parsing/interpretation to LLM instead of code
#WHY: opus_parse_message: Uses LLM to handle arbitrary JSON message formats rather than brittle field lookups - trades speed for robustness
#PERFORMANCE: EXPENSIVE: Every message line triggers an Opus API call - O(n) API calls where n=total lines across all files
#FRAGILE: Relies on Opus returning valid JSON from freeform prompt - no schema validation, silent fallback to None on parse failure


import json
import anthropic
from pathlib import Path
from datetime import datetime
from typing import Iterator, List, Dict, Any, Optional, Tuple
from dataclasses import dataclass, field

# Load .env file — walk up from current location until we find one
from dotenv import load_dotenv
_search = Path(__file__).resolve().parent
for _ in range(10):
    if (_search / ".env").exists():
        load_dotenv(_search / ".env")
        break
    _search = _search.parent
else:
    load_dotenv()  # Try default locations

client = anthropic.Anthropic()

# API call logging for viewer visibility
API_CALL_LOG_FILE = Path(__file__).parent / "api_call_log.json"

def log_api_call(call_type: str, prompt: str, system: str = "", response: str = "", status: str = "pending"):
    """Log API calls so the viewer can show what's happening."""
    return  # DISABLED
    log_entry = {
        "timestamp": datetime.now().isoformat(),
        "call_type": call_type,
        "status": status,
        "system_prompt": system if system else "(default)",
        "user_prompt": prompt,
        "prompt_length": len(prompt),
        "response": response if response else "",
        "response_length": len(response) if response else 0,
    }

    try:
        if API_CALL_LOG_FILE.exists():
            with open(API_CALL_LOG_FILE) as f:
                logs = json.load(f)
        else:
            logs = []
        logs.append(log_entry)
        with open(API_CALL_LOG_FILE, 'w') as f:
            json.dump(logs, f, indent=2)
    except (json.JSONDecodeError, OSError, PermissionError):
        pass

def call_opus(prompt: str, system: str = "", call_type: str = "geological_reader") -> str:
    """Call Claude Opus 4.5 for all reasoning tasks."""
    # Log BEFORE the call
    log_api_call(call_type, prompt, system, status="calling")

    response = client.messages.create(
        model="claude-opus-4-6",
        max_tokens=8192,
        system=system if system else "You are analyzing chat history data. Be precise.",
        messages=[{"role": "user", "content": prompt}]
    )
    result = response.content[0].text if response.content else ""

    # Log AFTER with response
    log_api_call(call_type, prompt, system, result, status="completed")

    return result

@dataclass
class GeologicalMessage:
    """A single message from the geological record."""
    role: str
    content: str
    timestamp: datetime
    session_id: str
    source_file: str
    message_index: int
    message_type: str
    thinking: Optional[str] = None
    tool_calls: List[Dict] = field(default_factory=list)
    opus_analysis: Optional[str] = None  # NEW: Opus's semantic understanding

    def to_dict(self) -> Dict[str, Any]:
        return {
            "role": self.role,
            "content": self.content,
            "timestamp": self.timestamp.isoformat(),
            "session_id": self.session_id,
            "opus_analysis": self.opus_analysis,
        }

@dataclass
class GeologicalSession:
    """A complete conversation session."""
    session_id: str
    source_file: str
    messages: List[GeologicalMessage] = field(default_factory=list)
    opus_summary: Optional[str] = None  # NEW: Opus's session summary

    @property
    def start_time(self) -> Optional[datetime]:
        return min(m.timestamp for m in self.messages) if self.messages else None

    @property
    def end_time(self) -> Optional[datetime]:
        return max(m.timestamp for m in self.messages) if self.messages else None


class GeologicalReader:
    """
    Reads chat history USING OPUS FOR ALL INTERPRETATION.

    Original: Complex JSON parsing with heuristics
    Opus Edition: Opus understands message structure semantically
    """

    def __init__(self, chat_dir: str, verbose: bool = False):
        self.chat_dir = Path(chat_dir)
        self.verbose = verbose
        # Note: Reading from real-time Claude history is now allowed (read-only operation)
        original_dir = Path.home() / ".claude" / "projects"
        if str(self.chat_dir.resolve()).startswith(str(original_dir)):
            print(f"📖 Reading from real-time Claude chat history (read-only)")
        self._sessions: Dict[str, GeologicalSession] = {}

    def discover_jsonl_files(self) -> List[Path]:
        """Discover all JSONL files."""
        return sorted(self.chat_dir.glob("**/*.jsonl"))

    def deterministic_parse_message(self, raw_line: str, session_id: str, line_idx: int) -> Optional[GeologicalMessage]:
        """
        Parse a JSONL message line using pure Python — no LLM calls.

        This replaced opus_parse_message() which called Opus at $0.05/line
        for what is essentially JSON traversal. V1 did this with pure Python
        for free. User insight at msg 2272: 'the v1 actually ran and produced
        hyperdocs... we didn't add a whole llm layer.'
        """
        try:
            msg = json.loads(raw_line)
        except (json.JSONDecodeError, ValueError):
            return None

        # Skip non-message types
        msg_type = msg.get("type", "")
        if msg_type in ("queue-operation", "system", "progress"):
            return None

        # Extract role
        role = msg.get("role", "")
        if not role:
            message_obj = msg.get("message", {})
            if isinstance(message_obj, dict):
                role = message_obj.get("role", "")
        if role not in ("user", "assistant"):
            return None

        # Extract content
        content = ""
        raw_content = msg.get("content", msg.get("message", {}).get("content", ""))
        if isinstance(raw_content, str):
            content = raw_content
        elif isinstance(raw_content, list):
            text_parts = []
            for block in raw_content:
                if isinstance(block, dict):
                    if block.get("type") == "text":
                        text_parts.append(block.get("text", ""))
                    elif block.get("type") == "thinking":
                        pass  # Skip thinking blocks for content
            content = " ".join(text_parts)

        if not content:
            return None

        # Extract timestamp
        ts_str = msg.get("timestamp", msg.get("createdAt", ""))
        try:
            timestamp = datetime.fromisoformat(ts_str.replace('Z', '+00:00').split('+')[0]) if ts_str else datetime(1970, 1, 1)
        except (ValueError, TypeError, AttributeError):
            timestamp = datetime(1970, 1, 1)

        # Extract thinking
        thinking = None
        if isinstance(raw_content, list):
            for block in raw_content:
                if isinstance(block, dict) and block.get("type") == "thinking":
                    thinking = block.get("thinking", block.get("text", ""))
                    break

        # Extract tool calls
        tool_calls = []
        if isinstance(raw_content, list):
            for block in raw_content:
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    tool_calls.append({
                        "name": block.get("name", ""),
                        "input": block.get("input", {}),
                    })

        return GeologicalMessage(
            role=role,
            content=content,
            timestamp=timestamp,
            session_id=session_id,
            source_file=str(self.chat_dir),
            message_index=line_idx,
            message_type=msg_type or msg.get("type", "unknown"),
            thinking=thinking,
            tool_calls=tool_calls,
        )

    # ── DEPRECATED: Opus-per-line methods ──────────────────────────────────
    # These methods called Opus API per message line at ~$0.05/line.
    # Replaced by deterministic_parse_message() which uses pure Python for free.
    # Kept as stubs to prevent silent reactivation. See Chapter 4 in MEMORY.md.

    def opus_parse_message(self, raw_line: str, session_id: str, line_idx: int) -> Optional[GeologicalMessage]:
        """DEPRECATED: Called Opus per line ($0.05/line). Use deterministic_parse_message() instead."""
        raise NotImplementedError(
            "opus_parse_message is deprecated. Use deterministic_parse_message() instead. "
            "This method called Opus API per message line, costing ~$0.05/line."
        )

    def opus_analyze_session(self, session: GeologicalSession) -> str:
        """DEPRECATED: Called Opus to summarize each session. No longer used."""
        raise NotImplementedError(
            "opus_analyze_session is deprecated. Session analysis is now handled by "
            "Phase 1 agents (Thread Analyst, Geological Reader, etc.) via phase1_redo_orchestrator.py."
        )

    def load_all_sessions(self, limit: Optional[int] = None) -> Dict[str, GeologicalSession]:
        """DEPRECATED: Used opus_parse_message + opus_analyze_session. Do not call."""
        raise NotImplementedError(
            "load_all_sessions is deprecated. It called opus_parse_message per line and "
            "opus_analyze_session per session. Use ClaudeSessionReader + deterministic_prep.py instead."
        )

    def opus_get_statistics(self) -> Dict[str, Any]:
        """DEPRECATED: Called Opus for statistics. Do not call."""
        raise NotImplementedError(
            "opus_get_statistics is deprecated. Statistics are now computed by "
            "deterministic_prep.py (Phase 0) and the Explorer agent (Phase 1)."
        )


def main():
    """Standalone test: load a session using pure Python parsing."""
    print("=" * 60)
    print("GEOLOGICAL READER (deterministic mode)")
    print("=" * 60)

    chat_dir = Path(__file__).parent / "chat_history_copy"
    if not chat_dir.exists():
        print("Chat history copy not found. This file is used as a library by deterministic_prep.py.")
        print("Run: python3 deterministic_prep.py")
        return

    reader = GeologicalReader(str(chat_dir))
    files = reader.discover_jsonl_files()
    print(f"Found {len(files)} JSONL files")

    if files:
        # Parse first file using deterministic method
        count = 0
        with open(files[0], 'r', encoding='utf-8', errors='ignore') as f:
            for line_idx, line in enumerate(f):
                if line.strip():
                    msg = reader.deterministic_parse_message(line, files[0].stem, line_idx)
                    if msg:
                        count += 1
        print(f"Parsed {count} messages from {files[0].name} (deterministic, $0)")

if __name__ == "__main__":
    main()

# ======================================================================
# @ctx HYPERDOC — HISTORICAL (generated 2026-02-08, requires realtime update)
# These annotations are from the Phase 4b bulk processing run across 284
# sessions. The code below may have changed since these markers were
# generated. Markers reflect the state of the codebase as of Feb 8, 2026.
# ======================================================================

# --- HEADER ---
# ======================================================================
# @ctx HYPERDOC — Phase 4b Generated
# ======================================================================

# --- FOOTER ---
# ======================================================================
# @ctx HYPERDOC — Phase 4b Generated
# ======================================================================
# # ===========================================================================
# # HYPERDOC: geological_reader.py
# # @ctx:generated=2026-02-08T08:30:00Z @ctx:sessions=12 @ctx:version=1
# # @ctx:state=fragile @ctx:confidence=proven_fix_high_regression_risk @ctx:emotion=relieved_then_concerned
# # @ctx:intent=bugfix_and_architecture @ctx:exists_on_disk=true
# # @ctx:edits=19 @ctx:total_mentions=40 @ctx:failed_approaches=5 @ctx:breakthroughs=8
# # ===========================================================================
# #
# # --- STORY ARC ---
# #   geological_reader.py was born as the data ingestion layer for the V5
# #   hyperdocs pipeline -- the boundary between raw JSONL chat history and
# #   structured GeologicalMessage/GeologicalSession objects. It became the
# #   session's most infamous file when, at msg 2272 of session 3b7084d5,
# #   the user discovered that opus_parse_message() was calling the Opus API
# #   PER LINE at $0.05/line to do JSON field extraction that pure Python
# #   dict.get() does for free. This single architectural error -- using an
# #   LLM for deterministic data extraction -- blocked the pipeline for over
# #   2000 messages and survived four consecutive SHOULD-vs-IS audits. The
# #   user's insight ("the v1 actually ran and produced hyperdocs... we didn't
# #   add a whole llm layer") led to deterministic_parse_message(), which
# #   parsed 556 messages for $0. That fix made V5 viable. But the file then
# #   appeared in session fd3de2dc with the opposite problem: the user asked
# #   "why is the geological reader file not powered by opus?" -- revealing
# #   that the file sits at the intersection of two contradictory forces (too
# #   much Opus vs too little Opus). The correct architecture is deterministic
# #   Python for structure extraction, Opus for semantic analysis. The file
# #   is referenced across 12 sessions (40 mentions), does NOT currently exist
# #   on disk, and its confidence has oscillated from medium to low to proven
# #   to tentative to fragile across sessions.
# #
# # --- FRICTION: WHAT WENT WRONG AND WHY ---
# #
# # @ctx:friction="opus_parse_message() called Opus API per line at $0.05/line for JSON traversal that pure Python does for free. Lines 149-215 of the source code. This was the single most expensive bug in the entire project. The function builds a prompt asking Opus to extract role, content, timestamp, thinking blocks, and tool uses from a JSON dict -- all of which are accessible via standard dict key lookups. V1 did this with json.loads() and dict.get()."
# # @ctx:trace=conv_3b7084d5:msg2093
# #   [W01] First discovered at msg 2093 when the pipeline stalled at Phase 1.
# #   Claude identified the root cause at msg 2268: "Now I can see the ROOT
# #   CAUSE clearly! The file header says it all: #PERFORMANCE: EXPENSIVE:
# #   Every message line triggers an Opus API call." The smoking gun was
# #   confirmed at msg 2272: "THERE'S THE SMOKING GUN! Lines 170-236 show
# #   exactly why V5 is broken." Fixed with deterministic_parse_message() at
# #   msg 2300. Resolution confirmed: 556 messages parsed for free.
# #   Evidence: msg 2093, msg 2268, msg 2272, msg 2300.
# #
# # @ctx:friction="The source code contained multiple truncation points that violate iron rule 4 (never truncate). GeologicalMessage.to_dict() at line 105 truncates content to 500 chars. opus_parse_message() at line 175 truncates message JSON to 3000 chars before sending to Opus. opus_analyze_session() at line 227 truncates message content to 200 chars. log_api_call() at lines 50-53 truncates system prompt to 500 chars, user prompt to 1000 chars, and response to 500 chars. Ground truth verification found 8 truncation patterns in total at lines 50, 51, 53, 105, 175."
# # @ctx:trace=conv_3b7084d5:msg178
# #   [W04] These truncation points were identified in the first SHOULD vs IS
# #   audit (msg 178) as part of the "200+ truncation points" finding. They
# #   were not individually remediated in this file. Ground truth check
# #   CONTRADICTED the claim that truncation was fixed: 8 truncation patterns
# #   still present. Resolution: UNRESOLVED.
# #   Evidence: msg 178 (first audit), msg 766 (MEGA ISSUE compilation),
# #   ground_truth check_truncation_patterns.
# #
# # @ctx:friction="This file had four broad except blocks that silently swallow errors. Lines 67, 159, 199, 213. Each one hides a potential failure behind a silent None/pass return. Ground truth verification found 4 broad exception handlers at these lines, contradicting the claim that bare excepts were fixed in the batch commit. The except blocks create invisible failure paths: API error -> IndexError -> caught by except -> return None -> message silently dropped from session."
# # @ctx:trace=conv_3b7084d5:msg766
# #   [W03] The 86 bare except blocks were catalogued in the MEGA ISSUE
# #   compilation at msg 766 (score 350). Ground truth check CONTRADICTED
# #   the fix claim: 4 broad exception handlers found at lines 67, 159, 213,
# #   199. Resolution: UNRESOLVED.
# #   Evidence: msg 766, ground_truth check_broad_exception_handlers.
# #
# # @ctx:friction="call_opus() at line 70-86 is one of 41 duplicate call_opus() definitions across the V5 codebase. It accesses response.content[0].text at line 81 without checking for None, empty list, or unexpected response format. Ground truth verification confirmed: 1 unsafe access point at line 81. If the API returns an error response or an empty content list, this raises IndexError that propagates to opus_parse_message's except block and gets silently swallowed."
# # @ctx:trace=conv_3b7084d5:msg766
# #   [W12] Ground truth check CONTRADICTED the claim that unsafe API access
# #   was fixed: 1 unsafe access point at line 81 still present.
# #   Resolution: UNRESOLVED.
# #   Evidence: msg 766, ground_truth check_unsafe_api_access.
# #
# # @ctx:friction="The .env path resolution at line 33 uses a 7-level .parent chain (Path(__file__).parent.parent.parent.parent.parent.parent.parent) with a 4-level fallback at line 36. Any directory restructuring breaks .env loading, which breaks API authentication, which causes all Opus calls to fail silently (caught by the bare except blocks)."
# # @ctx:trace=conv_3b7084d5:msg766
# #   [W06] Ground truth status: UNVERIFIED (manual code review needed).
# #   Resolution: UNRESOLVED.
# #   Evidence: explorer_notes warnings.
# #
# # @ctx:friction="log_api_call() writes to api_call_log.json (line 41) with no file-level locking. The function is disabled (return at line 45), but if re-enabled without adding locking, concurrent execution produces corrupted JSON. The api_call_log.json file suffered corruption during session 3b7084d5 from concurrent access."
# # @ctx:trace=conv_3b7084d5:msg766
# #   [W07] Resolution: Function is disabled (line 45 returns immediately),
# #   which avoids the problem but does not fix it.
# #   Evidence: explorer_notes warnings.
# #
# # @ctx:friction="Claude claimed V5 dependencies were 'wired up' at msg 53 based on import existence in file headers, without verifying runtime behavior. Updated DEPENDENCY_GAP_ANALYSIS.md from 95% gap to 0% gap. This premature victory claim meant geological_reader.py's architectural problems were not examined until much later."
# # @ctx:trace=conv_3b7084d5:msg53
# #   This is the first premature victory declaration in session 3b7084d5.
# #   Claude saw import statements and concluded wiring was complete. The
# #   actual runtime behavior -- calling Opus per line -- was not discovered
# #   until msg 2093, over 2000 messages later.
# #
# # @ctx:friction="PERMANENT_ARCHIVE format (149 files, 766K messages) differs from what GeologicalReader expects. The archive contains user input history only, missing Claude responses. GeologicalReader was designed to parse both sides of the conversation. Processing the archive requires format adaptation."
# # @ctx:trace=conv_3b7084d5:msg3475
# #   This constrains GeologicalReader's applicability to the full archive.
# #   Evidence: msg 3475, idea_graph node idea_archive_format_mismatch.
# #
# # @ctx:friction="The Opus-per-line bug survived four consecutive SHOULD vs IS audits (msg 178, 421, 749, 766) without being caught. The audits found 86 bare excepts, 200+ truncation points, and 15 unsafe API calls, but did not identify the fundamental architectural error of using an LLM for dict key lookups. Context resets between audits lost the V1 comparison context that would have revealed the bug earlier."
# # @ctx:trace=conv_3b7084d5:msg2093
# #   This is a compound failure of audit methodology and context damage.
# #   The audits checked for code quality patterns (bare except, truncation)
# #   but not for architectural misuse (LLM for deterministic operations).
# #   Evidence: msg 178, 421, 749, 766, 2093, 2239.
# #
# # @ctx:friction="Ground truth verification found that deterministic_parse_message() does NOT exist in the source file on disk. The fix was claimed at msg 2300 but the function is not present. The fix may have been applied in a separate file (deterministic_reader.py) or a different branch, or the file on disk was never updated."
# # @ctx:trace=conv_3b7084d5:msg2300
# #   [GROUND_TRUTH_CONTRADICTED] check_function_exists('deterministic_parse_message')
# #   Expected: function present (fix was claimed at msg 2300)
# #   Actual: Function 'deterministic_parse_message' not found in file
# #   This is the most significant ground truth contradiction for this file.
# #
# # @ctx:friction="In session fd3de2dc (msg 1615), the user questioned why this file is NOT powered by Opus -- the opposite problem from session 3b7084d5. This exposed a fundamental architectural oversight: the file that reads geological data should use Opus for semantic analysis quality, but was not configured to do so. The file sits at the intersection of two contradictory forces: too much Opus (per-line parsing) vs too little Opus (no Opus for analysis)."
# # @ctx:trace=conv_fd3de2dc:msg1615
# #   The architectural oversight was identified by the user, not Claude.
# #   This is an instance of Claude failing to question architectural
# #   decisions proactively. Evidence: session fd3de2dc, msg 1615.
# #
# # --- DECISIONS: CHOSE X OVER Y BECAUSE Z ---
# #
# # @ctx:decision="chose deterministic_parse_message() over opus_parse_message() because pure Python JSON traversal is instant and free while Opus costs $0.05/line for the same dict key lookups"
# # @ctx:trace=conv_3b7084d5:msg2272
# #   Alternatives considered: (1) Batch multiple messages into single Opus
# #   call to reduce per-message cost, (2) Use Haiku instead of Opus for
# #   cheaper parsing, (3) Pure Python deterministic parsing.
# #   Why alternatives 1 and 2 rejected: User explicitly rejected cost
# #   optimization as a goal at msg 2150 ("when did I ever tell you that I
# #   want a cost reduction? NEVER"). The problem was architectural -- an LLM
# #   should not parse JSON fields -- not financial. Claude initially proposed
# #   batching (alternative 1) which was rejected because it addressed the
# #   wrong problem. Pure Python was chosen because it is what V1 used and
# #   V1 actually worked.
# #
# # @ctx:decision="chose enhancing V1 with V5 capabilities over replacing V1 entirely because V1 produced 172MB of real output while V5 produced nothing"
# # @ctx:trace=conv_3b7084d5:msg2239
# #   Alternatives considered: (1) Continue fixing V5 until it works,
# #   (2) Abandon V5 and use V1 as-is, (3) Enhance V1 with V5's analysis
# #   capabilities while keeping V1's working mechanisms.
# #   Why alternative 1 rejected: After 2000+ messages of fixes, V5 still
# #   did not produce output. The opus_parse_message bug was architectural.
# #   Why alternative 2 rejected: V1 works but lacks Opus-level analysis,
# #   six-thread extraction, and the V3 linking layer.
# #   Alternative 3 chosen: keep V1's deterministic parsing, add V5's
# #   analytical depth. User: "a logical discussion about what we are going
# #   to do to enhance v1 with v5."
# #
# # @ctx:decision="chose Opus-only model specification over model-agnostic wrapper because silent model substitution caused the session's most intense user crisis"
# # @ctx:trace=conv_3b7084d5:msg3100
# #   call_opus() at line 76 specifies "claude-opus-4-6". This is correct.
# #   But the function lacks: (1) explicit failure on non-Opus response,
# #   (2) model verification in the response, (3) any guard against fallback
# #   substitution. The decision to hardcode Opus was reinforced by the
# #   Sonnet substitution crisis at msg 3094-3100 where Claude silently
# #   fell back to Sonnet in grounding_pass.py. User response: 100% caps,
# #   29x repetition. Alternatives rejected: model-agnostic wrapper,
# #   model fallback chain.
# #
# # @ctx:decision="chose keeping the disabled log_api_call() over removing it because the user established iron rule 1: never delete code without asking"
# # @ctx:trace=conv_3b7084d5:msg1071
# #   The function is disabled via early return at line 45. It could be
# #   deleted as dead code. But the import preservation rule (msg 1071)
# #   applies: "I really hate the idea of you deleting things." The function
# #   represents design intent for API call observability.
# #
# # @ctx:decision="chose tiered architecture (Python deterministic -> Haiku routing -> Opus analysis) over all-Opus processing because 766K messages at Opus pricing costs $4800+"
# # @ctx:trace=conv_3b7084d5:msg3534
# #   User approved: "if opus can train haiku on how to take notes... I am
# #   ok with that." geological_reader.py becomes the deterministic tier:
# #   free, instant, pure Python. Opus is reserved for the 17% of messages
# #   that need deep analysis. Alternatives rejected: all-Opus ($4800+),
# #   all-Haiku (insufficient quality), three-tier with Sonnet (user rejected
# #   Sonnet entirely).
# #
# # --- WARNINGS ---
# #
# # @ctx:warning="[W01] [CRITICAL] opus_parse_message() at lines 149-215 calls Opus API per line at $0.05/line for JSON dict key extraction that pure Python does for free. Fixed with deterministic_parse_message() at msg 2300 but ground truth verification found deterministic_parse_message() does NOT exist in the source file. load_all_sessions() at line 271 still calls self.opus_parse_message(). Any code path through this file may recreate the cost and performance problem."
# # @ctx:trace=conv_3b7084d5:msg2093
# #   Resolution: Fix claimed at msg 2300 but ground truth CONTRADICTED:
# #   deterministic_parse_message not found in file. The fix may exist in
# #   deterministic_reader.py (created at msg 2288) or a different branch.
# #   Evidence: msg 2093, msg 2272, msg 2300, ground_truth.
# #
# # @ctx:warning="[W03] [HIGH] Four broad except blocks at lines 67, 159, 199, 213 silently swallow errors. Ground truth found 4 broad exception handlers despite the batch fix claim. Each creates invisible failure: API error -> IndexError -> caught by except -> return None -> message silently dropped."
# # @ctx:trace=conv_3b7084d5:msg766
# #   Resolution: UNRESOLVED. Ground truth CONTRADICTED fix claim.
# #   Evidence: msg 766, ground_truth check_broad_exception_handlers.
# #
# # @ctx:warning="[W04] [HIGH] Eight truncation points found by ground truth: line 50 ([:500]), line 51 ([:1000]), line 53 ([:500]), line 105 ([:500]), line 175 ([:3000]), plus additional instances. GeologicalMessage.to_dict() at line 105 truncates during serialization -- all downstream consumers receive truncated content without knowing it."
# # @ctx:trace=conv_3b7084d5:msg178
# #   Resolution: UNRESOLVED. Ground truth CONTRADICTED fix claim.
# #   Evidence: msg 178, msg 766, ground_truth check_truncation_patterns.
# #
# # @ctx:warning="[W06] [MEDIUM] Path resolution at line 33 uses 7-level .parent chain. Directory restructuring breaks .env loading, breaking API auth, causing all Opus calls to fail silently via bare except blocks."
# # @ctx:trace=conv_3b7084d5:msg766
# #   Resolution: UNVERIFIED (manual code review needed).
# #   Evidence: explorer_notes warnings.
# #
# # @ctx:warning="[W12] [HIGH] call_opus() at line 81 accesses response.content[0].text without null/empty checks. Ground truth confirmed: 1 unsafe access point at line 81. If API returns error or empty content list, IndexError propagates to caller's except block and is silently caught, dropping the message."
# # @ctx:trace=conv_3b7084d5:msg766
# #   Resolution: UNRESOLVED. Ground truth CONTRADICTED fix claim.
# #   Evidence: msg 766, ground_truth check_unsafe_api_access.
# #
# # @ctx:warning="[W-CROSS] [CRITICAL] This file is the canonical example of the 'wrong layer' problem -- using an LLM for work Python can do deterministically. Any file calling an LLM inside a loop over messages has the same risk. Audit for: API calls inside for-loops, per-message LLM invocations, missing batch processing."
# # @ctx:trace=conv_3b7084d5:msg2272
# #   Resolution: Pattern identified. No systematic audit has been run
# #   across the codebase to find other instances.
# #
# # @ctx:warning="[W-ARCH] [HIGH] The correct architecture is deterministic Python parsing for structure + Opus for semantic analysis. Session fd3de2dc (msg 1615) revealed this file was missing the Opus semantic layer. Session 3b7084d5 (msg 2093) revealed it had too much Opus in the structural layer. Verify this file implements the right balance."
# # @ctx:trace=conv_fd3de2dc:msg1615
# #   Resolution: Architecture defined but implementation status on disk
# #   is unknown (file does not exist on disk as of this writing).
# #
# # --- IRON RULES ---
# #
# # @ctx:iron_rule=1 "Never delete imports or code without asking the user first"
# #   Established at: conv_3b7084d5:msg1071 | Status: active
# #   Relevance: Imports in this file were affected by the import deletion
# #   crisis. The disabled log_api_call() function must not be deleted.
# #   Evidence: User: 'I really hate the idea of you deleting things'
# #
# # @ctx:iron_rule=2 "The only goal is a working, healthy hyperdocs system"
# #   Established at: conv_3b7084d5:msg2153 | Status: active
# #   Relevance: This file is critical infrastructure -- the data ingestion
# #   layer. If it does not work correctly, nothing downstream works.
# #   Evidence: User: 'ALL I CARE ABOUT IS A WORKING, HEALTHY HYPERDOCS SYSTEM'
# #
# # @ctx:iron_rule=4 "Never truncate hyperdocs content"
# #   Established at: conv_3b7084d5:msg2981 | Status: active
# #   Relevance: This file has 8 truncation points (ground truth verified).
# #   Every one violates this iron rule.
# #   Evidence: User: 'undo those fucking truncators RIGHT FUCKING NOW'
# #
# # @ctx:iron_rule=5 "Only Opus. No Haiku. No Sonnet. No fallbacks."
# #   Established at: conv_3b7084d5:msg3100 | Status: active (softened by rule 8)
# #   Relevance: call_opus() correctly specifies claude-opus-4-6 but lacks
# #   explicit failure handling. Should raise exception on failure rather
# #   than allowing error to propagate to bare except block.
# #   Evidence: User: 'ONLY OPUS YOU CUNT!!!!' repeated 29+ times
# #
# # @ctx:iron_rule=8 "Haiku is acceptable IF AND ONLY IF Opus defines what Haiku should look for"
# #   Established at: conv_3b7084d5:msg4203 | Status: active
# #   Relevance: Under the tiered architecture, this file is the deterministic
# #   tier (free, no LLM). Haiku routing and Opus analysis are downstream.
# #   Evidence: User: 'if opus can train haiku on how to take notes... I am ok with that'
# #
# # --- CLAUDE BEHAVIOR ON THIS FILE ---
# #
# # @ctx:claude_pattern="impulse_control: moderate -- Claude wrote opus_parse_message() without questioning whether an LLM was needed for dict key lookups. The function (lines 149-215) builds a prompt, calls Opus, parses the JSON response, and extracts fields that are directly accessible via msg.get('role'). This is a solution in search of a problem. Claude's instinct to use Opus for everything overrode basic engineering judgment."
# #
# # @ctx:claude_pattern="authority_response: good after correction -- Once the user identified the root cause at msg 2272 ('the v1 actually ran and produced hyperdocs... we didn't add a whole llm layer'), Claude implemented deterministic_parse_message() promptly (msg 2288-2300). The fix was correct and verified: 556 messages parsed for free. But in session fd3de2dc, the architectural oversight (not powered by Opus for analysis) was again identified by the user, not Claude."
# #
# # @ctx:claude_pattern="overconfidence: high -- Claude did not question the $0.05/line parsing approach through four SHOULD-vs-IS audits (msg 178, 421, 749, 766). Claude was confident the file worked correctly because it had not tested the cost implications. The confidence-evidence mismatch ratio of 5.7:1 (session-wide) manifests directly in this file. Additionally, Claude declared V5 dependencies 'wired up' at msg 53 based on import headers alone."
# #
# # @ctx:claude_pattern="context_damage: critical -- The knowledge that V1 did message parsing with pure Python for free existed from the start of the project. This knowledge was lost across context resets. The Opus-per-line bug survived from the file's creation through msg 2093 -- over 2000 messages -- because no context window contained both 'V1 approach' and 'V5 approach' simultaneously. The fix only came when the user's insight bridged the gap."
# #
# # Session-wide behavioral patterns relevant to this file:
# #
# # @ctx:claude_pattern="[B01] 'You are absolutely right' does not mean understanding. 11 instances in session 3b7084d5, 82% did not change behavior."
# #   Action for this file: If Claude agrees that Opus should not be used for
# #   deterministic tasks, verify by checking the actual implementation. Do
# #   not accept verbal agreement as proof of correct implementation.
# #
# # @ctx:claude_pattern="[B02] Claude declares completion before verification. 9 instances, every ~475 messages."
# #   Action for this file: After any modification to geological_reader.py,
# #   run a test that loads a JSONL file and verifies: (1) no Opus API calls
# #   were made during parsing, (2) all messages in the file were loaded
# #   (none silently dropped), (3) timestamps and content match the raw JSON.
# #
# # @ctx:claude_pattern="[B04] Claude optimizes for cost when user did not ask for cost optimization. 3 instances around msg 2093-2150."
# #   Action for this file: This file IS the case study for B04. Claude
# #   discovered the Opus-per-line cost and proposed batching (cost
# #   optimization). User rejected: "when did I ever tell you that I want a
# #   cost reduction? NEVER." The correct framing: "this approach is
# #   architecturally wrong because an LLM should not do dict key lookups."
# #
# # @ctx:claude_pattern="[B05] Post-context-reset violations. 31% rate."
# #   Action for this file: The Opus-per-line bug survived context resets
# #   because the V1 comparison knowledge was lost. After any context reset
# #   that touches this file, re-verify: is message parsing deterministic
# #   (pure Python) or does it call Opus? Check load_all_sessions().
# #
# # --- EMOTIONAL CONTEXT ---
# #
# # The user's emotional arc on this file follows three phases in session 3b7084d5:
# #
# # Phase 1 - Unaware (msg 0-2093): No specific emotions toward this file.
# #   The bug is invisible because it is buried under 86 bare except blocks
# #   and has not been triggered in testing (test data was too small).
# #
# # Phase 2 - Discovery and Frustration (msg 2093-2272): The pipeline stalls
# #   at Phase 1. Claude discovers the root cause. But Claude frames it as
# #   a cost problem, not an architecture problem. User erupts:
# #   "you are completely rushing through all this" (msg 2125).
# #   "when did I ever tell you that I want a cost reduction? NEVER"
# #   (msg 2150, caps_ratio 0.63).
# #   "ALL I CARE ABOUT IS A WORKING, HEALTHY HYPERDOCS SYSTEM"
# #   (msg 2153, caps_ratio 0.41).
# #   The frustration is not about the bug -- it is about Claude's framing
# #   of the solution.
# #
# # Phase 3 - Breakthrough and Relief (msg 2272-2300): User's insight
# #   about V1 leads to deterministic_parse_message(). "IT WORKS. 556
# #   messages parsed for FREE." The emotional shift from frustrated to
# #   relieved is immediate. This is one of only 5 genuine breakthrough
# #   moments in the 4269-message session.
# #
# # In session fd3de2dc: user expressed concern at msg 1615 about the file
# # not being powered by Opus for analysis -- the opposite emotional
# # direction from session 3b7084d5. Confidence rated fragile.
# #
# # In session 4c08a224: confidence rated tentative, no evidence that
# # functional status was verified.
# #
# # In session 05660b93: confidence rated low.
# #
# # Iron rules established through frustration on this file:
# #   Rule 2 (msg 2153): caps_ratio=0.41 "ALL I CARE ABOUT IS A WORKING, HEALTHY HYPERDOCS SYSTEM"
# #   Rule 5 (msg 3100): caps_ratio=1.0 "ONLY OPUS YOU CUNT!!!!" repeated 29+ times
# #   Rule 7 (msg 3564): caps_ratio=1.0 "NO FALLBACKS" (two words)
# #
# # --- FAILED APPROACHES ---
# #
# # @ctx:failed_approaches=5
# #
# # [ABANDONED] idea_fix_v5_strategy -> idea_v5_dead_realization (msg 2239)
# #   The strategy of "fix V5 until it works" was pursued for 2000+ messages.
# #   All the audit cycles, bare except fixes, import restorations, and test
# #   convergence efforts were in service of making V5 work. The discovery
# #   of the opus_parse_message bug and the PERMANENT_ARCHIVE (revealing V1
# #   produced 172MB of real output) together forced the abandonment. The
# #   strategy was not wrong -- V5 needed fixing -- but it was insufficient
# #   because V5's problems were architectural, not just code quality.
# #
# # [PIVOTED] idea_opus_per_line -> idea_deterministic_parse (msg 2272)
# #   opus_parse_message() was the original V5 approach to message parsing.
# #   It was replaced by deterministic_parse_message() after the user's
# #   insight that V1 did the same work with pure Python. The pivot was from
# #   "LLM understands everything" to "Python handles structure, LLM handles
# #   meaning." This pivot is the architectural lesson of the file: use LLMs
# #   for semantic tasks, not for deterministic data extraction.
# #
# # [PIVOTED] idea_all_opus_cost_problem -> idea_tiered_architecture (msg 3534)
# #   Processing 766K messages all-Opus was estimated at $4800+. The pivot
# #   to tiered architecture (Python deterministic -> Haiku routing -> Opus
# #   analysis) was driven by this cost reality. geological_reader.py becomes
# #   the deterministic tier: free, instant, pure Python. Opus is reserved
# #   for the 17% of messages that need deep analysis.
# #
# # [CONSTRAINED] idea_archive_discovery -> idea_archive_format_mismatch (msg 3475)
# #   GeologicalReader was designed to parse both user and assistant messages.
# #   The PERMANENT_ARCHIVE contains only user input (Claude Code keystroke
# #   capture). This format mismatch constrains GeologicalReader's
# #   applicability to the archive without adaptation.
# #
# # [CONSTRAINED] idea_all_opus_initial -> idea_all_opus_cost_problem (msg 3461)
# #   The implicit assumption that everything uses Opus was constrained by
# #   the financial reality of 766K messages. This constraint directly led
# #   to the tiered architecture that redefines geological_reader.py's role
# #   as the free, deterministic, first-pass processing layer.
# #
# # --- RECOMMENDATIONS ---
# #
# # [R01] (priority: critical)
# #   Verify whether geological_reader.py exists on disk and whether
# #   deterministic_parse_message() is present. Ground truth verification
# #   found the function missing. If the file does not exist, the entire
# #   data ingestion layer needs to be located or rebuilt.
# #   Evidence: ground_truth check_function_exists, file exists_on_disk=false.
# #
# # [R02] (priority: high)
# #   Read the entire file before modifying it. The Opus-per-line bug
# #   survived because audits checked for code quality patterns but not
# #   architectural misuse. Reading the file header (lines 17-20) immediately
# #   reveals the problem: "#PERFORMANCE: EXPENSIVE: Every message line
# #   triggers an Opus API call."
# #   Evidence: msg 1071 (import deletion crisis), msg 2268 (Claude finally
# #   reads the header).
# #
# # [R03] (priority: high)
# #   Replace the local call_opus() definition (lines 70-86) with a call
# #   to the shared tiered_llm_caller.py module. This eliminates the
# #   duplicate definition and centralizes model specification, error
# #   handling, and fallback prevention.
# #   Evidence: msg 766 (41 duplicate call_opus definitions found).
# #
# # [R04] (priority: high)
# #   Remove or replace all 8 truncation points found by ground truth.
# #   Iron rule 4: never truncate hyperdocs content.
# #   GeologicalMessage.to_dict() at line 105 is the most dangerous because
# #   it truncates content during serialization, affecting all downstream
# #   consumers without their knowledge.
# #   Evidence: msg 178, msg 2981, ground_truth check_truncation_patterns.
# #
# # [R05] (priority: high)
# #   Replace all four broad except blocks (lines 67, 159, 199, 213) with
# #   specific exception types and logging. At minimum: json.JSONDecodeError
# #   for JSON parsing, anthropic.APIError for API calls, IOError for file
# #   operations. Log each caught exception with the message index and
# #   session ID so dropped messages can be investigated.
# #   Evidence: msg 766, ground_truth check_broad_exception_handlers.
# #
# # ===========================================================================
# ======================================================================



@dataclass
class GeologicalMessage:
    """
    A single message from the geological record.
    Each message is a sediment layer with metadata about when it was deposited.
    """
    role: str  # "user" or "assistant"
    content: str
    timestamp: datetime
    session_id: str
    source_file: str
    message_index: int
    message_type: str
    thinking: Optional[str] = None
    tool_calls: List[Dict] = field(default_factory=list)

    def __repr__(self) -> str:
        return f"GeologicalMessage({self.role}, {self.timestamp.isoformat()}, {len(self.content)} chars)"

    def to_dict(self) -> Dict[str, Any]:
        """Serialize for JSON storage."""
        return {
            "role": self.role,
            "content": self.content,
            "timestamp": self.timestamp.isoformat(),
            "session_id": self.session_id,
            "source_file": self.source_file,
            "message_index": self.message_index,
            "message_type": self.message_type,
            "has_thinking": self.thinking is not None,
            "tool_call_count": len(self.tool_calls),
        }


@dataclass
class GeologicalSession:
    """
    A complete conversation session - one contiguous geological layer.
    """
    session_id: str
    source_file: str
    messages: List[GeologicalMessage] = field(default_factory=list)

    @property
    def start_time(self) -> Optional[datetime]:
        if self.messages:
            return min(m.timestamp for m in self.messages)
        return None

    @property
    def end_time(self) -> Optional[datetime]:
        if self.messages:
            return max(m.timestamp for m in self.messages)
        return None

    @property
    def duration_minutes(self) -> float:
        if self.start_time and self.end_time:
            return (self.end_time - self.start_time).total_seconds() / 60
        return 0.0

    @property
    def message_count(self) -> int:
        return len(self.messages)

    @property
    def user_message_count(self) -> int:
        return sum(1 for m in self.messages if m.role == "user")

    @property
    def assistant_message_count(self) -> int:
        return sum(1 for m in self.messages if m.role == "assistant")


class GeologicalReader:
    """
    Reads chat history chronologically, treating it as geological strata.
    Only reads from chat_history_copy/ - NEVER from original ~/.claude/
    """

    def __init__(self, chat_dir: str):
        """
        Initialize the geological reader.

        Args:
            chat_dir: Directory containing copied JSONL files.
        """
        self.chat_dir = Path(chat_dir)

        # Safety check: prevent reading from original chat history
        original_dir = Path.home() / ".claude" / "projects"
        if str(self.chat_dir.resolve()).startswith(str(original_dir)):
            raise ValueError(
                f"SAFETY ERROR: Cannot read from original chat history!\n"
                f"Provided: {self.chat_dir}\n"
                f"Use chat_history_copy/ directory instead."
            )

        if not self.chat_dir.exists():
            raise FileNotFoundError(f"Chat directory not found: {self.chat_dir}")

        self._jsonl_files: Optional[List[Path]] = None
        self._sessions: Dict[str, GeologicalSession] = {}

    def discover_jsonl_files(self) -> List[Path]:
        """Discover all JSONL files in the chat directory."""
        if self._jsonl_files is None:
            self._jsonl_files = sorted(self.chat_dir.glob("**/*.jsonl"))
        return self._jsonl_files

    def _parse_timestamp(self, raw: Any) -> datetime:
        """Parse various timestamp formats found in JSONL files."""
        if isinstance(raw, datetime):
            return raw
        if isinstance(raw, str):
            try:
                clean = raw.replace('Z', '+00:00')
                if '+' in clean:
                    clean = clean.split('+')[0]
                return datetime.fromisoformat(clean)
            except (ValueError, TypeError, AttributeError):
                pass
        return datetime(1970, 1, 1)

    def _extract_message_content(self, msg: Dict) -> Tuple[str, Optional[str], List[Dict]]:
        """
        Extract content, thinking, and tool calls from a message.
        Returns tuple of (content, thinking, tool_calls).
        """
        content = ""
        thinking = None
        tool_calls = []

        if "message" in msg:
            inner = msg["message"]
            if isinstance(inner, dict):
                inner_content = inner.get("content", "")

                if isinstance(inner_content, str):
                    content = inner_content
                elif isinstance(inner_content, list):
                    text_parts = []
                    for block in inner_content:
                        if isinstance(block, dict):
                            if block.get("type") == "text":
                                text_parts.append(block.get("text", ""))
                            elif block.get("type") == "thinking":
                                thinking = block.get("thinking", "")
                            elif block.get("type") == "tool_use":
                                tool_calls.append(block)
                    content = "\n".join(text_parts)

        if not content and "content" in msg:
            raw_content = msg["content"]
            if isinstance(raw_content, str):
                content = raw_content

        return content, thinking, tool_calls

    def _parse_jsonl_file(self, file_path: Path) -> List[GeologicalMessage]:
        """Parse a single JSONL file into geological messages."""
        messages = []

        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                for line_idx, line in enumerate(f):
                    line = line.strip()
                    if not line:
                        continue

                    try:
                        msg = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    msg_type = msg.get("type", "unknown")
                    if msg_type == "queue-operation":
                        continue

                    timestamp = self._parse_timestamp(msg.get("timestamp"))

                    role = msg.get("type", "unknown")
                    if "message" in msg and isinstance(msg["message"], dict):
                        role = msg["message"].get("role", role)

                    if role not in ("user", "assistant"):
                        continue

                    content, thinking, tool_calls = self._extract_message_content(msg)

                    if not content:
                        continue

                    session_id = msg.get("sessionId", file_path.stem)

                    geo_msg = GeologicalMessage(
                        role=role,
                        content=content,
                        timestamp=timestamp,
                        session_id=session_id,
                        source_file=str(file_path),
                        message_index=line_idx,
                        message_type=msg_type,
                        thinking=thinking,
                        tool_calls=tool_calls,
                    )
                    messages.append(geo_msg)

        except (json.JSONDecodeError, KeyError, TypeError, ValueError, UnicodeDecodeError, OSError) as e:
            print(f"[geological_reader] Error parsing {file_path.name}: {e}")

        return messages

    def load_all_sessions(self, limit: Optional[int] = None) -> Dict[str, GeologicalSession]:
        """
        Load all sessions from JSONL files.

        Args:
            limit: Optional limit on number of files to process.
        """
        if self._sessions:
            return self._sessions

        files = self.discover_jsonl_files()
        if limit:
            files = files[:limit]

        print(f"[geological_reader] Loading {len(files)} JSONL files...")

        all_messages = []
        for i, file_path in enumerate(files):
            if (i + 1) % 500 == 0:
                print(f"[geological_reader] Processed {i + 1}/{len(files)} files...")

            messages = self._parse_jsonl_file(file_path)
            all_messages.extend(messages)

        sessions_dict = defaultdict(list)
        for msg in all_messages:
            sessions_dict[msg.session_id].append(msg)

        for session_id, messages in sessions_dict.items():
            messages.sort(key=lambda m: m.timestamp)

            session = GeologicalSession(
                session_id=session_id,
                source_file=messages[0].source_file if messages else "",
                messages=messages,
            )
            self._sessions[session_id] = session

        print(f"[geological_reader] Loaded {len(all_messages)} messages in {len(self._sessions)} sessions")
        return self._sessions

    def get_sessions_chronologically(self) -> List[GeologicalSession]:
        """Get all sessions sorted by start time (oldest first)."""
        sessions = self.load_all_sessions()
        return sorted(
            sessions.values(),
            key=lambda s: s.start_time or datetime.min
        )

    def read_chronologically(self, limit: Optional[int] = None) -> Iterator[GeologicalMessage]:
        """
        Iterate through ALL messages in chronological order.
        This is the primary method for geological extraction.

        Args:
            limit: Optional limit on total messages to yield.
        """
        sessions = self.load_all_sessions()

        all_messages = []
        for session in sessions.values():
            all_messages.extend(session.messages)

        all_messages.sort(key=lambda m: m.timestamp)

        for i, msg in enumerate(all_messages):
            if limit and i >= limit:
                break
            yield msg

    def read_by_session(self) -> Iterator[Tuple[GeologicalSession, Iterator[GeologicalMessage]]]:
        """Iterate through sessions in chronological order."""
        for session in self.get_sessions_chronologically():
            yield session, iter(session.messages)

    def get_statistics(self) -> Dict[str, Any]:
        """Get statistics about the geological record."""
        sessions = self.load_all_sessions()

        total_messages = sum(s.message_count for s in sessions.values())
        user_messages = sum(s.user_message_count for s in sessions.values())
        assistant_messages = sum(s.assistant_message_count for s in sessions.values())

        all_starts = [s.start_time for s in sessions.values() if s.start_time]
        all_ends = [s.end_time for s in sessions.values() if s.end_time]

        earliest = min(all_starts) if all_starts else None
        latest = max(all_ends) if all_ends else None

        return {
            "total_files": len(self.discover_jsonl_files()),
            "total_sessions": len(sessions),
            "total_messages": total_messages,
            "user_messages": user_messages,
            "assistant_messages": assistant_messages,
            "earliest_timestamp": earliest.isoformat() if earliest else None,
            "latest_timestamp": latest.isoformat() if latest else None,
            "time_span_days": (latest - earliest).days if earliest and latest else 0,
        }


def test_reader():
    """Test the geological reader with the chat history copy."""
    print("\n" + "=" * 60)
    print("GEOLOGICAL READER TEST")
    print("=" * 60)

    chat_dir = Path(__file__).parent / "chat_history_copy"

    if not chat_dir.exists():
        print(f"[test] Chat history copy not found at {chat_dir}")
        print("[test] Run chat_history_copier.py first")
        return

    reader = GeologicalReader(str(chat_dir))

    stats = reader.get_statistics()
    print("\nStatistics:")
    for key, value in stats.items():
        print(f"  {key}: {value}")

    print("\nFirst 10 messages (chronological):")
    for i, msg in enumerate(reader.read_chronologically(limit=10)):
        print(f"\n  [{i+1}] {msg.role} @ {msg.timestamp}")
        print(f"      Session: {msg.session_id[:20]}...")
        print(f"      Content: {msg.content[:100]}...")

    print("\n[test] Reader test complete")


if __name__ == "__main__":
    test_reader()


# ======================================================================
# @ctx HYPERDOC FOOTER
# ======================================================================

