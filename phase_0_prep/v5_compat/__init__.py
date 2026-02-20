"""
V5 compatibility modules bundled for portability.

These files were originally in hyperdocs_2/V5/code/ and are imported by
Phase 0 (deterministic_prep.py), Phase 4 (insert_hyperdocs), and
Phase 5 (ground_truth_verifier). Bundling them here removes the
sys.path hack that pointed to a machine-specific directory.
"""

# Add this directory to sys.path so bare imports within V5 modules resolve
import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).parent))

from .claude_session_reader import ClaudeSessionReader, ClaudeMessage, ClaudeSession
from .geological_reader import GeologicalMessage
from .metadata_extractor import MetadataExtractor
from .message_filter import MessageFilter
from .claude_behavior_analyzer import ClaudeBehaviorAnalyzer
