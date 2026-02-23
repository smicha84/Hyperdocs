"""
Evidence renderer registry.

Maps directive type names to renderer classes.
Used by evidence_resolver.py to dispatch @evidence:type(params) directives.
"""
from .debug_sequence import DebugSequenceRenderer
from .emotional_arc import EmotionalArcRenderer
from .idea_transition import IdeaTransitionRenderer
from .reaction_log import ReactionLogRenderer
from .file_timeline import FileTimelineRenderer
from .geological_event import GeologicalEventRenderer
from .decision_trace import DecisionTraceRenderer

RENDERER_REGISTRY = {
    "debug_sequence": DebugSequenceRenderer,
    "emotional_arc": EmotionalArcRenderer,
    "idea_transition": IdeaTransitionRenderer,
    "reaction_log": ReactionLogRenderer,
    "file_timeline": FileTimelineRenderer,
    "geological_event": GeologicalEventRenderer,
    "decision_trace": DecisionTraceRenderer,
}
