#!/usr/bin/env python3
"""
Metadata Extractor
==================

Pure Python extraction of structured metadata from chat history.
NO LLM CALLS. This is deterministic, free, fast.

Extracts:
- Timestamps, dates, time of day patterns
- File names and paths mentioned
- Error patterns (tracebacks, exceptions, error messages)
- Message counts (per hour, per day)
- Role ratios (user vs assistant)
- Tool calls and their types
- Screenshots/images
- Browser open commands
- Server activity (port mentions, localhost, etc.)
- Code blocks and languages

This metadata feeds into Haiku with pre-enriched context.
"""

import re
import json
from pathlib import Path
from datetime import datetime, timedelta
from collections import defaultdict
from typing import Dict, List, Any, Optional, Set
from dataclasses import dataclass, field

# Import geological reader (required)
try:
    from .geological_reader import GeologicalMessage, GeologicalSession
except ImportError:
    from geological_reader import GeologicalMessage, GeologicalSession

# Import display format adapter (optional — only used in standalone main())
try:
    from .display_format_adapter import DisplayFormatAdapter
except ImportError:
    try:
        from display_format_adapter import DisplayFormatAdapter
    except ImportError:
        DisplayFormatAdapter = None


@dataclass
class MessageMetadata:
    """Metadata extracted from a single message."""
    index: int
    timestamp: datetime
    hour_of_day: int
    day_of_week: str
    content_length: int

    # Content patterns
    has_image: bool = False
    image_count: int = 0
    has_code_block: bool = False
    code_languages: List[str] = field(default_factory=list)

    # Files
    files_mentioned: List[str] = field(default_factory=list)
    paths_mentioned: List[str] = field(default_factory=list)

    # Errors
    has_error: bool = False
    error_types: List[str] = field(default_factory=list)
    has_traceback: bool = False

    # Commands
    has_browser_open: bool = False
    has_server_command: bool = False
    ports_mentioned: List[int] = field(default_factory=list)

    # Terminal activity (NEW - verified patterns from real data)
    has_terminal_paste: bool = False  # User pasted terminal output
    terminal_sessions: List[str] = field(default_factory=list)  # ttys000, ttys001, etc.
    python_scripts_run: List[str] = field(default_factory=list)  # python3 script.py
    terminal_mentions: int = 0  # Count of "terminal window" mentions

    # Server issues (natural language, not commands)
    server_issue_reported: bool = False  # "can't connect to server" etc.

    # File operations (user requests)
    files_to_create: List[str] = field(default_factory=list)  # "create a new file"
    files_to_open: List[str] = field(default_factory=list)    # "open", "look at", "read"
    files_to_edit: List[str] = field(default_factory=list)    # "edit", "update", "fix", "change"

    # Tool calls (for assistant messages)
    tool_calls: List[str] = field(default_factory=list)

    # Frustration signals (caps, punctuation)
    caps_ratio: float = 0.0
    exclamation_count: int = 0
    question_count: int = 0
    has_profanity: bool = False  # Strong frustration signal

    # Repeated phrase detection (extreme frustration signal)
    has_repeated_phrase: bool = False
    repeated_phrase: str = ""
    repeat_count: int = 0

    # Emergency intervention - EXTREME frustration
    # Triggered when: profanity + (high caps OR many exclamations OR angry keywords)
    is_emergency_intervention: bool = False
    emergency_reason: str = ""  # Why this was flagged as emergency

    def to_dict(self) -> Dict:
        return {
            "index": self.index,
            "timestamp": self.timestamp.isoformat(),
            "hour": self.hour_of_day,
            "day": self.day_of_week,
            "length": self.content_length,
            "images": self.image_count,
            "code_block": self.has_code_block,
            "code_langs": self.code_languages,
            "files": self.files_mentioned,
            "paths": self.paths_mentioned,
            "error": self.has_error,
            "error_types": self.error_types,
            "traceback": self.has_traceback,
            "browser_open": self.has_browser_open,
            "server_cmd": self.has_server_command,
            "ports": self.ports_mentioned,
            # Terminal activity (verified patterns)
            "terminal_paste": self.has_terminal_paste,
            "terminal_sessions": self.terminal_sessions,
            "python_scripts": self.python_scripts_run,
            "terminal_mentions": self.terminal_mentions,
            "server_issue": self.server_issue_reported,
            # File operations
            "files_create": self.files_to_create,
            "files_open": self.files_to_open,
            "files_edit": self.files_to_edit,
            # Tool/frustration
            "tools": self.tool_calls,
            "caps_ratio": round(self.caps_ratio, 2),
            "exclamations": self.exclamation_count,
            "questions": self.question_count,
            "profanity": self.has_profanity,
            "repeated_phrase": self.has_repeated_phrase,
            "repeat_count": self.repeat_count,
            "emergency_intervention": self.is_emergency_intervention,
            "emergency_reason": self.emergency_reason
        }

    def to_opus_context(self) -> str:
        """
        Generate a compact one-line context string for Opus pre-prompt.
        This tells Opus what to expect BEFORE seeing the message content.
        """
        parts = [f"[{self.index}]", self.timestamp.strftime("%H:%M"), self.day_of_week[:3]]

        # Content indicators
        if self.image_count > 0:
            parts.append(f"IMG:{self.image_count}")
        if self.has_code_block:
            parts.append(f"CODE:{','.join(self.code_languages[:2]) or 'block'}")

        # Files
        if self.files_mentioned:
            parts.append(f"FILES:{','.join(self.files_mentioned[:2])}")

        # Errors
        if self.has_error:
            err_str = ','.join(self.error_types[:2]) if self.error_types else 'error'
            parts.append(f"ERR:{err_str}")
        if self.has_traceback:
            parts.append("TRACEBACK")

        # Terminal/Server
        if self.has_terminal_paste:
            parts.append("TERM_PASTE")
        if self.python_scripts_run:
            parts.append(f"RUN:{','.join(self.python_scripts_run[:2])}")
        if self.server_issue_reported:
            parts.append("SERVER_ISSUE")
        if self.ports_mentioned:
            parts.append(f"PORT:{','.join(map(str, self.ports_mentioned[:2]))}")

        # File operations
        if self.files_to_create:
            parts.append(f"CREATE:{','.join(self.files_to_create[:2])}")
        if self.files_to_edit:
            parts.append(f"EDIT:{','.join(self.files_to_edit[:2])}")

        # Frustration signals (compact)
        frustration = []
        if self.caps_ratio > 0.3:
            frustration.append(f"CAPS:{self.caps_ratio:.0%}")
        if self.exclamation_count >= 2:
            frustration.append(f"{self.exclamation_count}!")
        if self.has_profanity:
            frustration.append("PROFANITY")
        if frustration:
            parts.append(" ".join(frustration))

        # Emergency (most important)
        if self.is_emergency_intervention:
            parts.append(f"⚠️EMERGENCY:{self.emergency_reason}")
        elif self.has_repeated_phrase:
            parts.append(f"SPAM:{self.repeat_count}x")

        return " | ".join(parts)


@dataclass
class SessionMetadata:
    """Aggregated metadata for an entire session/file."""
    session_id: str
    file_name: str

    # Time stats
    total_messages: int = 0
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    duration_hours: float = 0.0

    # Message patterns
    messages_per_hour: Dict[int, int] = field(default_factory=dict)
    messages_per_day: Dict[str, int] = field(default_factory=dict)
    busiest_hour: int = 0

    # Files
    all_files_mentioned: List[str] = field(default_factory=list)
    file_mention_counts: Dict[str, int] = field(default_factory=dict)
    most_mentioned_files: List[str] = field(default_factory=list)

    # Errors
    total_errors: int = 0
    error_type_counts: Dict[str, int] = field(default_factory=dict)
    traceback_count: int = 0

    # Images/Screenshots
    total_images: int = 0
    messages_with_images: int = 0

    # Code
    total_code_blocks: int = 0
    languages_used: Set[str] = field(default_factory=set)

    # Server/Browser activity
    browser_opens: int = 0
    server_commands: int = 0
    ports_used: Set[int] = field(default_factory=set)

    # Terminal activity (NEW - verified from real data)
    terminal_paste_count: int = 0  # Messages with pasted terminal output
    unique_terminal_sessions: Set[str] = field(default_factory=set)  # ttys000, ttys001, etc.
    max_concurrent_terminals: int = 0  # Highest ttys number seen
    python_scripts_run: Set[str] = field(default_factory=set)  # Unique scripts run
    terminal_mention_messages: int = 0  # Messages mentioning "terminal window"
    server_issues_reported: int = 0  # "can't connect to server" etc.

    # File operations tracking
    file_create_requests: int = 0  # How many times user asked to create files
    file_open_requests: int = 0    # How many times user asked to open/read files
    file_edit_requests: int = 0    # How many times user asked to edit files
    files_created: Set[str] = field(default_factory=set)   # Unique files requested to create
    files_opened: Set[str] = field(default_factory=set)    # Unique files requested to open
    files_edited: Set[str] = field(default_factory=set)    # Unique files requested to edit
    file_access_counts: Dict[str, int] = field(default_factory=dict)  # Per-file access count

    # Frustration indicators
    high_caps_messages: int = 0  # >30% caps
    high_exclamation_messages: int = 0  # 3+ exclamations
    profanity_messages: int = 0  # Messages with strong language

    # Emergency intervention tracking (EXTREME frustration)
    emergency_intervention_count: int = 0  # Number of emergency moments
    emergency_reasons: List[str] = field(default_factory=list)  # Why each was flagged
    repeated_phrase_messages: int = 0  # Messages with phrase spam

    # Individual message metadata
    message_metadata: List[MessageMetadata] = field(default_factory=list)

    def to_dict(self) -> Dict:
        return {
            "session_id": self.session_id,
            "file_name": self.file_name,
            "total_messages": self.total_messages,
            "start_time": self.start_time.isoformat() if self.start_time else None,
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "duration_hours": round(self.duration_hours, 2),
            "messages_per_hour": self.messages_per_hour,
            "messages_per_day": self.messages_per_day,
            "busiest_hour": self.busiest_hour,
            "files_mentioned": self.all_files_mentioned,
            "file_mention_counts": dict(sorted(self.file_mention_counts.items(), key=lambda x: -x[1])),
            "most_mentioned_files": self.most_mentioned_files,
            "total_errors": self.total_errors,
            "error_types": self.error_type_counts,
            "traceback_count": self.traceback_count,
            "total_images": self.total_images,
            "messages_with_images": self.messages_with_images,
            "total_code_blocks": self.total_code_blocks,
            "languages_used": list(self.languages_used),
            "browser_opens": self.browser_opens,
            "server_commands": self.server_commands,
            "ports_used": list(self.ports_used),
            # Terminal activity (verified from real data)
            "terminal_paste_count": self.terminal_paste_count,
            "unique_terminal_sessions": list(self.unique_terminal_sessions),
            "max_concurrent_terminals": self.max_concurrent_terminals,
            "python_scripts_run": list(self.python_scripts_run),
            "terminal_mention_messages": self.terminal_mention_messages,
            "server_issues_reported": self.server_issues_reported,
            # File operations
            "file_create_requests": self.file_create_requests,
            "file_open_requests": self.file_open_requests,
            "file_edit_requests": self.file_edit_requests,
            "files_created": list(self.files_created),
            "files_opened": list(self.files_opened),
            "files_edited": list(self.files_edited),
            "most_accessed_files": dict(sorted(self.file_access_counts.items(), key=lambda x: -x[1])),
            # Frustration
            "high_caps_messages": self.high_caps_messages,
            "high_exclamation_messages": self.high_exclamation_messages,
            "profanity_messages": self.profanity_messages,
            "emergency_intervention_count": self.emergency_intervention_count,
            "emergency_reasons": self.emergency_reasons,
            "repeated_phrase_messages": self.repeated_phrase_messages,
        }

    def to_haiku_context(self) -> str:
        """Generate a compact context string for Haiku."""
        lines = [
            f"SESSION: {self.session_id}",
            f"MESSAGES: {self.total_messages} over {self.duration_hours:.1f} hours",
            f"TIME: {self.start_time.strftime('%Y-%m-%d %H:%M') if self.start_time else '?'} to {self.end_time.strftime('%H:%M') if self.end_time else '?'}",
            f"BUSIEST HOUR: {self.busiest_hour}:00",
        ]

        if self.most_mentioned_files:
            lines.append(f"TOP FILES: {', '.join(self.most_mentioned_files[:5])}")

        if self.total_errors > 0:
            lines.append(f"ERRORS: {self.total_errors} ({', '.join(self.error_type_counts.keys())})")

        if self.total_images > 0:
            lines.append(f"SCREENSHOTS: {self.total_images}")

        if self.browser_opens > 0:
            lines.append(f"BROWSER OPENS: {self.browser_opens}")

        if self.server_commands > 0 or self.server_issues_reported > 0:
            parts = []
            if self.server_commands > 0:
                parts.append(f"{self.server_commands} cmds")
            if self.server_issues_reported > 0:
                parts.append(f"{self.server_issues_reported} issues")
            if self.ports_used:
                parts.append(f"ports: {', '.join(map(str, self.ports_used))}")
            lines.append(f"SERVER: {', '.join(parts)}")

        # Terminal activity (verified from real data)
        if self.max_concurrent_terminals > 0 or self.terminal_paste_count > 0:
            term_parts = []
            if self.max_concurrent_terminals > 0:
                term_parts.append(f"max {self.max_concurrent_terminals + 1} concurrent terminals")
            if self.terminal_paste_count > 0:
                term_parts.append(f"{self.terminal_paste_count} terminal pastes")
            if self.python_scripts_run:
                term_parts.append(f"{len(self.python_scripts_run)} scripts run")
            lines.append(f"TERMINALS: {', '.join(term_parts)}")

        # File operations
        total_file_ops = self.file_create_requests + self.file_open_requests + self.file_edit_requests
        if total_file_ops > 0:
            file_parts = []
            if self.file_create_requests > 0:
                file_parts.append(f"{self.file_create_requests} creates ({len(self.files_created)} unique)")
            if self.file_open_requests > 0:
                file_parts.append(f"{self.file_open_requests} opens ({len(self.files_opened)} unique)")
            if self.file_edit_requests > 0:
                file_parts.append(f"{self.file_edit_requests} edits ({len(self.files_edited)} unique)")
            lines.append(f"FILE OPS: {', '.join(file_parts)}")
            # Most accessed files
            if self.file_access_counts:
                top_files = sorted(self.file_access_counts.items(), key=lambda x: -x[1])[:3]
                lines.append(f"HOT FILES: {', '.join(f'{f}({c}x)' for f,c in top_files)}")

        # Frustration indicators
        frustration_parts = []
        if self.high_caps_messages > 0:
            frustration_parts.append(f"{self.high_caps_messages} caps msgs")
        if self.high_exclamation_messages > 0:
            frustration_parts.append(f"{self.high_exclamation_messages} exclamation msgs")
        if self.profanity_messages > 0:
            frustration_parts.append(f"{self.profanity_messages} profanity msgs")
        if frustration_parts:
            lines.append(f"FRUSTRATION: {', '.join(frustration_parts)}")

        # Emergency interventions (user catching Claude's mistakes)
        if self.emergency_intervention_count > 0:
            # Count reason types
            from collections import Counter
            reason_counts = Counter()
            for r in self.emergency_reasons:
                for reason in r.split(','):
                    reason_counts[reason] += 1
            top_reasons = [f"{r}({c})" for r, c in reason_counts.most_common(3)]
            lines.append(f"EMERGENCY INTERVENTIONS: {self.emergency_intervention_count} ({', '.join(top_reasons)})")

        return "\n".join(lines)

    def get_opus_context_window(self, message_index: int, window_size: int = 5) -> str:
        """
        Get metadata context for N messages leading up to (and including) message_index.
        This is the pre-prompt for Opus before it sees the actual message content.

        Args:
            message_index: The message Opus is about to analyze
            window_size: How many previous messages to include (default 5)

        Returns:
            Formatted context string for Opus pre-prompt
        """
        if not self.message_metadata:
            return ""

        # Get the window of messages
        start_idx = max(0, message_index - window_size + 1)
        end_idx = min(message_index + 1, len(self.message_metadata))

        lines = [f"METADATA CONTEXT (messages {start_idx}-{message_index}):"]
        for meta in self.message_metadata[start_idx:end_idx]:
            marker = " ← ANALYZE THIS" if meta.index == message_index else ""
            lines.append(f"{meta.to_opus_context()}{marker}")

        return "\n".join(lines)


class MetadataExtractor:
    """
    Extracts structured metadata from messages using pure Python.
    No LLM calls. Fast, deterministic, free.
    """

    # Regex patterns (compiled once)
    # NOTE: These patterns have been VERIFIED against real PERMANENT_ARCHIVE data
    PATTERNS = {
        # Files
        'py_file': re.compile(r'\b([\w_-]+\.py)\b'),
        'js_file': re.compile(r'\b([\w_-]+\.(?:js|ts|jsx|tsx))\b'),
        'html_file': re.compile(r'\b([\w_-]+\.(?:html|css))\b'),
        'json_file': re.compile(r'\b([\w_-]+\.json)\b'),
        'any_file': re.compile(r'\b([\w_-]+\.(?:py|js|ts|jsx|tsx|html|css|json|md|txt|yaml|yml|toml|sh|xlsx|csv))\b'),
        'file_path': re.compile(r'(/[\w./_-]+\.(?:py|js|ts|html|json|md|xlsx|csv))\b'),

        # Errors
        'error_keyword': re.compile(r'\b(Error|Exception|Traceback|error|failed|failure)\b'),
        'python_error': re.compile(r'\b(TypeError|ValueError|KeyError|AttributeError|ImportError|NameError|IndexError|RuntimeError|FileNotFoundError|ModuleNotFoundError|SyntaxError|ReferenceError)\b'),
        'traceback': re.compile(r'Traceback \(most recent call last\)|File ".*", line \d+'),

        # Images (VERIFIED: [Image #1] is the actual pattern)
        'image_ref': re.compile(r'\[Image #?\d+\]|\[Screenshot\]'),

        # Code blocks
        'code_block': re.compile(r'```(\w*)\n'),

        # Browser activity (VERIFIED: natural language + file:// URLs)
        # Real patterns: "pull up ... in safari", "open safari", file:///path
        'browser_open': re.compile(r'\b(?:pull\s+up|open)\s+.*?\b(?:safari|browser|chrome)\b|file:///|webbrowser\.open', re.IGNORECASE),

        # Server commands (VERIFIED: pasted terminal commands)
        # Real patterns: python3 script.py output, npm run, flask run
        'server_cmd': re.compile(r'\b(?:python3?\s+[\w_-]+\.py|npm\s+(?:run\s+)?(?:dev|start)|flask\s+run|uvicorn|gunicorn|http\.server)\b'),

        # Port patterns (VERIFIED: localhost:8080, port 3000, etc.)
        'port': re.compile(r'(?:localhost|127\.0\.0\.1|0\.0\.0\.0):(\d{4,5})\b|port\s*[=:]\s*(\d{4,5})'),
        'localhost': re.compile(r'localhost:\d+|127\.0\.0\.1:\d+|0\.0\.0\.0:\d+'),

        # Terminal activity (VERIFIED from real data - pasted terminal output)
        # Real patterns: "Last login: ... on ttys000", "ttys001", "ttys002"
        'terminal_paste': re.compile(r'Last login:.*on ttys\d+|stefanmichaelcheck@Mac|stefanmichaelcheck@Stefans-MBP'),
        'terminal_session': re.compile(r'ttys(\d{3})'),  # Extracts the session number
        'python_script_run': re.compile(r'python3?\s+([\w_-]+\.py)'),  # python3 script.py

        # Terminal window mentions (VERIFIED: natural language)
        'terminal_mention': re.compile(r'\bterminal\s+window\b', re.IGNORECASE),

        # Server issues (VERIFIED: natural language complaints)
        # Real patterns: "can't connect to the server", "server not working"
        'server_issue': re.compile(r"can't connect to (?:the )?server|server\s+(?:not\s+)?(?:working|running|responding)|connection\s+refused", re.IGNORECASE),

        # Tool calls (Claude format)
        'tool_use': re.compile(r'<tool_use>.*?name="(\w+)"', re.DOTALL),

        # Profanity (VERIFIED: strong frustration signals)
        'profanity': re.compile(r'\b(?:fuck|fucking|shit|damn|hell|crap|ass)\b', re.IGNORECASE),

        # Emergency intervention - USER CATCHING CLAUDE'S MISTAKES
        # Triggered when Claude did something stupid and user has to intervene
        'emergency_intervention': re.compile(
            r'\b(?:'
            r'no[,.]?\s+(?:that\'?s?\s+)?(?:wrong|not|completely)|'  # "no, that's wrong"
            r'what\s+(?:is|the\s+hell\s+is)\s+this|'  # "what is this?" / "what the hell is this"
            r'you\s+(?:forgot|missed|ignored|broke|deleted|removed)|'  # "you forgot"
            r'that\'?s?\s+(?:not\s+what|completely\s+wrong|the\s+opposite)|'  # "that's not what I asked"
            r'(?:this|it)\s+doesn\'?t?\s+(?:work|make\s+sense)|'  # "this doesn't work"
            r'why\s+did\s+you|'  # "why did you..."
            r'(?:delete|remove|undo)\s+(?:that|this|it)|'  # "delete that"
            r'start\s+over|'  # "start over"
            r'you\s+just\s+(?:made|did|broke)|'  # "you just broke"
            r'I\s+(?:just\s+)?(?:said|told\s+you|asked)|'  # "I just said..."
            r'that\'?s?\s+(?:a|the)\s+(?:mistake|error|bug|problem)|'  # "that's a mistake"
            r'(?:stop|don\'?t)\s+(?:doing\s+)?(?:that|this)|'  # "stop doing that"
            r'you\'?re?\s+(?:not\s+)?(?:listening|reading|paying\s+attention)'  # "you're not listening"
            r')\b',
            re.IGNORECASE
        ),

        # File operations (user requests - natural language)
        # Create: "create", "make", "new file", "add a file", "write a new"
        'file_create': re.compile(
            r'(?:create|make|write|add)\s+(?:a\s+)?(?:new\s+)?(?:file|script|module|component)?\s*["\']?([\w_-]+\.(?:py|js|ts|html|css|json|md|txt|yaml|sh))["\']?|'
            r'(?:new\s+file)\s+["\']?([\w_-]+\.(?:py|js|ts|html|css|json|md|txt|yaml|sh))["\']?',
            re.IGNORECASE
        ),
        # Open/Read: "open", "look at", "read", "check", "show me", "pull up"
        'file_open': re.compile(
            r'(?:open|read|look\s+at|check|show\s+me|pull\s+up|view)\s+["\']?([\w_/-]+\.(?:py|js|ts|html|css|json|md|txt|yaml|sh|xlsx|csv))["\']?|'
            r'(?:open|read|look\s+at|check|show\s+me)\s+(?:the\s+)?file\s+["\']?([\w_/-]+\.(?:py|js|ts|html|css|json|md|txt|yaml|sh))["\']?',
            re.IGNORECASE
        ),
        # Edit: "edit", "update", "change", "modify", "fix", "update"
        'file_edit': re.compile(
            r'(?:edit|update|change|modify|fix|adjust|tweak)\s+["\']?([\w_/-]+\.(?:py|js|ts|html|css|json|md|txt|yaml|sh))["\']?|'
            r'(?:edit|update|change|modify|fix)\s+(?:the\s+)?(?:file\s+)?["\']?([\w_/-]+\.(?:py|js|ts|html|css|json|md|txt|yaml|sh))["\']?|'
            r'(?:in|to)\s+["\']?([\w_/-]+\.(?:py|js|ts|html|css|json|md|txt|yaml|sh))["\']?\s*[,:]?\s*(?:change|add|remove|update|fix)',
            re.IGNORECASE
        ),
    }

    DAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']

    def _detect_repeated_phrases(self, content: str) -> tuple:
        """
        Detect CONSECUTIVE spam - true frustration repetition.
        Returns: (has_repeat, phrase, count)

        ONLY detects actual spam patterns like:
        - "NO NO NO NO NO" (same word back-to-back 3+ times)
        - "WHAT'S YOUR PROBLEM? WHAT'S YOUR PROBLEM? WHAT'S YOUR PROBLEM?"
        - "fix it fix it fix it" (phrase repeated consecutively)

        Does NOT detect words that just appear multiple times spread out.
        """
        if len(content) < 10:
            return False, "", 0

        import re

        # Method 1: CONSECUTIVE same word (word word word)
        # Regex: word followed by whitespace and same word, 3+ times
        match = re.search(r'\b(\w{2,20})\s+\1(?:\s+\1)+', content, re.IGNORECASE)
        if match:
            word = match.group(1)
            # Count consecutive occurrences
            full_match = match.group(0)
            count = len(re.findall(r'\b' + re.escape(word) + r'\b', full_match, re.IGNORECASE))
            if count >= 3:
                return True, word.upper(), count

        # Method 2: CONSECUTIVE same sentence/phrase with punctuation
        # Pattern: "phrase? phrase? phrase?" or "phrase! phrase! phrase!"
        sentences = re.split(r'(?<=[.!?])\s*', content)
        sentences = [s.strip() for s in sentences if len(s.strip()) >= 5]

        if len(sentences) >= 3:
            # Check for 3+ consecutive identical sentences
            for i in range(len(sentences) - 2):
                s = sentences[i].lower().strip('!?.').strip()
                if len(s) >= 5:
                    # Count consecutive matches starting at i
                    count = 1
                    for j in range(i + 1, len(sentences)):
                        if sentences[j].lower().strip('!?.').strip() == s:
                            count += 1
                        else:
                            break
                    if count >= 3:
                        return True, s, count

        return False, "", 0

    def extract_message_metadata(self, msg: GeologicalMessage, index: int) -> MessageMetadata:
        """Extract metadata from a single message."""
        content = msg.content or ""

        meta = MessageMetadata(
            index=index,
            timestamp=msg.timestamp,
            hour_of_day=msg.timestamp.hour,
            day_of_week=self.DAYS[msg.timestamp.weekday()],
            content_length=len(content)
        )

        # Images (VERIFIED pattern: [Image #1])
        image_matches = self.PATTERNS['image_ref'].findall(content)
        meta.has_image = len(image_matches) > 0
        meta.image_count = len(image_matches)

        # Code blocks
        code_matches = self.PATTERNS['code_block'].findall(content)
        meta.has_code_block = len(code_matches) > 0 or '```' in content
        meta.code_languages = [lang for lang in code_matches if lang]

        # Files
        meta.files_mentioned = list(set(self.PATTERNS['any_file'].findall(content)))
        meta.paths_mentioned = list(set(self.PATTERNS['file_path'].findall(content)))

        # Errors
        meta.has_error = bool(self.PATTERNS['error_keyword'].search(content))
        meta.error_types = list(set(self.PATTERNS['python_error'].findall(content)))
        meta.has_traceback = bool(self.PATTERNS['traceback'].search(content))

        # Browser/Server (VERIFIED patterns)
        meta.has_browser_open = bool(self.PATTERNS['browser_open'].search(content))
        meta.has_server_command = bool(self.PATTERNS['server_cmd'].search(content))

        # Port extraction (handles both localhost:8080 and port=8080 formats)
        port_matches = self.PATTERNS['port'].findall(content)
        ports = []
        for match in port_matches:
            # match is a tuple from groups (localhost_port, port_equal_port)
            if isinstance(match, tuple):
                for p in match:
                    if p and p.isdigit():
                        ports.append(int(p))
            elif match and str(match).isdigit():
                ports.append(int(match))
        meta.ports_mentioned = list(set(ports))

        # Terminal activity (VERIFIED from real data)
        meta.has_terminal_paste = bool(self.PATTERNS['terminal_paste'].search(content))
        terminal_sessions = self.PATTERNS['terminal_session'].findall(content)
        meta.terminal_sessions = list(set(terminal_sessions))  # e.g., ['000', '001', '002']
        python_scripts = self.PATTERNS['python_script_run'].findall(content)
        meta.python_scripts_run = list(set(python_scripts))  # e.g., ['script.py', 'server.py']
        meta.terminal_mentions = len(self.PATTERNS['terminal_mention'].findall(content))

        # Server issues (VERIFIED: natural language complaints)
        meta.server_issue_reported = bool(self.PATTERNS['server_issue'].search(content))

        # File operations (user requests)
        # Create requests
        create_matches = self.PATTERNS['file_create'].findall(content)
        for match in create_matches:
            # match is tuple of groups, get non-empty ones
            files = [f for f in (match if isinstance(match, tuple) else [match]) if f]
            meta.files_to_create.extend(files)
        meta.files_to_create = list(set(meta.files_to_create))

        # Open/read requests
        open_matches = self.PATTERNS['file_open'].findall(content)
        for match in open_matches:
            files = [f for f in (match if isinstance(match, tuple) else [match]) if f]
            meta.files_to_open.extend(files)
        meta.files_to_open = list(set(meta.files_to_open))

        # Edit requests
        edit_matches = self.PATTERNS['file_edit'].findall(content)
        for match in edit_matches:
            files = [f for f in (match if isinstance(match, tuple) else [match]) if f]
            meta.files_to_edit.extend(files)
        meta.files_to_edit = list(set(meta.files_to_edit))

        # Tool calls
        tool_matches = self.PATTERNS['tool_use'].findall(content)
        meta.tool_calls = list(set(tool_matches))

        # Frustration signals
        if content:
            alpha_chars = [c for c in content if c.isalpha()]
            if alpha_chars:
                caps_count = sum(1 for c in alpha_chars if c.isupper())
                meta.caps_ratio = caps_count / len(alpha_chars)
            meta.exclamation_count = content.count('!')
            meta.question_count = content.count('?')
            meta.has_profanity = bool(self.PATTERNS['profanity'].search(content))

            # Repeated phrase detection (EXTREME frustration)
            # Detect when user copy-pastes the same phrase 3+ times
            meta.has_repeated_phrase, meta.repeated_phrase, meta.repeat_count = \
                self._detect_repeated_phrases(content)

            # Emergency intervention detection
            # User catching Claude's mistakes - requires urgency signals:
            # - CAPS or exclamation marks, OR
            # - Repeated phrases (extreme frustration)
            emergency_match = self.PATTERNS['emergency_intervention'].search(content)
            has_urgency_signal = (
                meta.caps_ratio > 0.4 or
                meta.exclamation_count >= 2 or
                meta.has_repeated_phrase  # Spamming same phrase = extreme frustration
            )

            # Repeated phrases alone are emergency-level frustration
            if meta.has_repeated_phrase:
                meta.is_emergency_intervention = True
                meta.emergency_reason = f"REPEAT({meta.repeat_count}x):{meta.repeated_phrase}"

            elif emergency_match and has_urgency_signal:
                meta.is_emergency_intervention = True
                matched_text = emergency_match.group(0)
                # Build reason string
                reasons = []
                if 'forgot' in matched_text.lower() or 'missed' in matched_text.lower():
                    reasons.append("claude_forgot")
                if 'wrong' in matched_text.lower() or 'mistake' in matched_text.lower():
                    reasons.append("claude_wrong")
                if "doesn't work" in matched_text.lower() or 'broke' in matched_text.lower():
                    reasons.append("code_broken")
                if 'start over' in matched_text.lower() or 'undo' in matched_text.lower():
                    reasons.append("undo_requested")
                if 'not what' in matched_text.lower() or 'not listening' in matched_text.lower():
                    reasons.append("misunderstood")
                if 'stop' in matched_text.lower() or "don't" in matched_text.lower():
                    reasons.append("stop_requested")
                # Add urgency indicator
                if meta.caps_ratio > 0.4:
                    reasons.append("CAPS")
                if meta.exclamation_count >= 2:
                    reasons.append(f"{meta.exclamation_count}!")
                meta.emergency_reason = ",".join(reasons) if reasons else "intervention"

        return meta

    def extract_session_metadata(self, session: GeologicalSession, file_name: str) -> SessionMetadata:
        """Extract aggregated metadata for an entire session."""
        meta = SessionMetadata(
            session_id=session.session_id,
            file_name=file_name,
            total_messages=len(session.messages)
        )

        if not session.messages:
            return meta

        # Time bounds
        timestamps = [m.timestamp for m in session.messages]
        meta.start_time = min(timestamps)
        meta.end_time = max(timestamps)
        meta.duration_hours = (meta.end_time - meta.start_time).total_seconds() / 3600

        # Per-message extraction
        file_counts = defaultdict(int)
        error_counts = defaultdict(int)
        hour_counts = defaultdict(int)
        day_counts = defaultdict(int)

        for i, msg in enumerate(session.messages):
            msg_meta = self.extract_message_metadata(msg, i)
            meta.message_metadata.append(msg_meta)

            # Aggregate
            hour_counts[msg_meta.hour_of_day] += 1
            day_counts[msg_meta.day_of_week] += 1

            for f in msg_meta.files_mentioned:
                file_counts[f] += 1

            if msg_meta.has_error:
                meta.total_errors += 1
                for et in msg_meta.error_types:
                    error_counts[et] += 1

            if msg_meta.has_traceback:
                meta.traceback_count += 1

            meta.total_images += msg_meta.image_count
            if msg_meta.has_image:
                meta.messages_with_images += 1

            if msg_meta.has_code_block:
                meta.total_code_blocks += 1
                meta.languages_used.update(msg_meta.code_languages)

            if msg_meta.has_browser_open:
                meta.browser_opens += 1

            if msg_meta.has_server_command:
                meta.server_commands += 1

            meta.ports_used.update(msg_meta.ports_mentioned)

            if msg_meta.caps_ratio > 0.3:
                meta.high_caps_messages += 1

            if msg_meta.exclamation_count >= 3:
                meta.high_exclamation_messages += 1

            if msg_meta.has_profanity:
                meta.profanity_messages += 1

            # Emergency intervention (user catching Claude's mistakes)
            if msg_meta.is_emergency_intervention:
                meta.emergency_intervention_count += 1
                if msg_meta.emergency_reason:
                    meta.emergency_reasons.append(msg_meta.emergency_reason)

            # Track repeated phrase spam separately
            if msg_meta.has_repeated_phrase:
                meta.repeated_phrase_messages += 1

            # Terminal activity aggregation (VERIFIED patterns)
            if msg_meta.has_terminal_paste:
                meta.terminal_paste_count += 1

            for session in msg_meta.terminal_sessions:
                meta.unique_terminal_sessions.add(session)
                # Track max concurrent terminals (ttys000 = 0, ttys003 = 3)
                try:
                    session_num = int(session)
                    meta.max_concurrent_terminals = max(meta.max_concurrent_terminals, session_num)
                except ValueError:
                    pass

            meta.python_scripts_run.update(msg_meta.python_scripts_run)

            if msg_meta.terminal_mentions > 0:
                meta.terminal_mention_messages += 1

            if msg_meta.server_issue_reported:
                meta.server_issues_reported += 1

            # File operations aggregation
            if msg_meta.files_to_create:
                meta.file_create_requests += 1
                meta.files_created.update(msg_meta.files_to_create)
                for f in msg_meta.files_to_create:
                    meta.file_access_counts[f] = meta.file_access_counts.get(f, 0) + 1

            if msg_meta.files_to_open:
                meta.file_open_requests += 1
                meta.files_opened.update(msg_meta.files_to_open)
                for f in msg_meta.files_to_open:
                    meta.file_access_counts[f] = meta.file_access_counts.get(f, 0) + 1

            if msg_meta.files_to_edit:
                meta.file_edit_requests += 1
                meta.files_edited.update(msg_meta.files_to_edit)
                for f in msg_meta.files_to_edit:
                    meta.file_access_counts[f] = meta.file_access_counts.get(f, 0) + 1

        # Finalize aggregates
        meta.messages_per_hour = dict(hour_counts)
        meta.messages_per_day = dict(day_counts)
        meta.busiest_hour = max(hour_counts, key=hour_counts.get) if hour_counts else 0

        meta.file_mention_counts = dict(file_counts)
        meta.all_files_mentioned = list(file_counts.keys())
        meta.most_mentioned_files = sorted(file_counts, key=file_counts.get, reverse=True)

        meta.error_type_counts = dict(error_counts)

        return meta


def main():
    """CLI for testing metadata extraction."""
    import argparse
    from hyperdoc_tracking_manager import HyperdocTracker

    parser = argparse.ArgumentParser(description="Metadata Extractor")
    parser.add_argument("--file", type=str, help="Process specific file")
    parser.add_argument("--limit", type=int, default=1, help="Number of files to process")
    parser.add_argument("--output", type=str, help="Output JSON file")

    args = parser.parse_args()

    tracker = HyperdocTracker()
    adapter = DisplayFormatAdapter(tracker.archive_path)
    extractor = MetadataExtractor()

    if args.file:
        files = [args.file]
    else:
        files = [f.name for f in adapter.discover_files()[:args.limit]]

    results = []
    for filename in files:
        print(f"\nProcessing: {filename}")
        session = adapter.load_single_file(filename)

        if session:
            meta = extractor.extract_session_metadata(session, filename)
            results.append(meta.to_dict())

            print("\n" + "=" * 60)
            print("HAIKU CONTEXT:")
            print("=" * 60)
            print(meta.to_haiku_context())
            print("=" * 60)

    if args.output:
        with open(args.output, 'w') as f:
            json.dump(results, f, indent=2)
        print(f"\nSaved to {args.output}")


if __name__ == "__main__":
    main()
