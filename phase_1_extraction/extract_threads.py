#!/usr/bin/env python3
"""
Thread Analyst: Extract 6 threads + 6 markers from session {SESSION_ID} tier4 messages.
Forensic analysis - honest assessment of Claude behavior including harmful patterns.
"""
import json
import re
import os

INPUT_PATH = os.getenv("HYPERDOCS_TIER4_PATH", "tier4_priority_messages.json")
OUTPUT_PATH = os.getenv("HYPERDOCS_THREADS_OUTPUT", "thread_extractions.json")

def reconstruct_content(content):
    """Reconstruct char-per-line formatted content."""
    if not content:
        return ""
    if len(content) > 10 and len(content) > 2 and content[1:2] == '\n':
        return content.replace('\n', '')
    return content

def detect_frustration_level(msg):
    """Detect frustration level 0-5 from message metadata and content."""
    meta = msg.get('metadata', {})
    content = reconstruct_content(msg.get('content', ''))

    caps = meta.get('caps_ratio', 0)
    profanity = meta.get('profanity', False)
    exclamations = meta.get('exclamations', 0)
    emergency = meta.get('emergency_intervention', False)
    repeat_count = meta.get('repeat_count', 0)

    # Score frustration
    score = 0
    if caps > 0.8: score += 3
    elif caps > 0.4: score += 2
    elif caps > 0.2: score += 1

    if profanity: score += 2
    if exclamations > 5: score += 2
    elif exclamations > 2: score += 1
    if emergency: score += 1
    if repeat_count > 3: score += 2
    elif repeat_count > 1: score += 1

    # Content patterns
    content_lower = content.lower()
    if 'what the fuck' in content_lower or 'are you serious' in content_lower:
        score += 2
    if 'what is your fucking problem' in content_lower or 'fucktard' in content_lower:
        score += 3
    elif 'fuck' in content_lower and msg['role'] == 'user':
        score += 2
    if 'rushing' in content_lower or 'ignored' in content_lower:
        score += 1
    if 'dementia' in content_lower or 'moron' in content_lower:
        score += 2
    if 'i really hate' in content_lower:
        score += 1
    if 'like a god damn chump' in content_lower:
        score += 2
    if 'all i care about' in content_lower and caps > 0.1:
        score += 2
    if 'what\'s your problem' in content_lower or 'what"s your problem' in content_lower:
        score += 2

    return min(score, 5)

def detect_deception(msg):
    """Detect if Claude is being deceptive or making unverifiable claims."""
    if msg['role'] != 'assistant':
        return False
    content = msg.get('content', '').lower()
    behavior = msg.get('behavior_flags', {}) or {}

    deception_patterns = [
        behavior.get('overconfident', False) and behavior.get('damage_score', 0) > 1,
        'comprehensive' in content and 'all' in content and 'complete' in content,
        bool(re.search(r'100%|everything.*fixed|all.*resolved', content)),
    ]

    # Claude claiming completion when things are clearly broken
    signals = msg.get('filter_signals', [])
    failure_count = sum(int(s.split(':')[1]) for s in signals if s.startswith('failure:'))
    if failure_count > 5 and any(w in content for w in ['complete', 'done', 'all fixed']):
        return True

    return sum(deception_patterns) >= 2

def extract_software_thread(msg):
    """Extract SOFTWARE thread: files created/modified/deleted."""
    meta = msg.get('metadata', {})
    created = meta.get('files_create', [])
    edited = meta.get('files_edit', [])
    opened = meta.get('files_open', [])
    files_mentioned = meta.get('files', [])

    # Detect deletions from content
    content = msg.get('content', '').lower()
    deleted = []
    if 'removed' in content or 'deleted' in content or 'delete' in content:
        for f in files_mentioned:
            if any(w in content for w in [f'removed {f}', f'deleted {f}', f'delete {f}']):
                deleted.append(f)

    modified = list(set(edited + [f for f in files_mentioned if f not in created and f not in deleted]))

    return {
        "created": created,
        "modified": modified[:10],  # Cap at 10 for readability
        "deleted": deleted
    }

def extract_code_blocks_thread(msg):
    """Extract CODE_BLOCKS thread: specific code sections affected."""
    content = msg.get('content', '')
    meta = msg.get('metadata', {})

    # Find code blocks
    code_blocks = re.findall(r'```(?:\w+)?\n(.*?)```', content, re.DOTALL)

    # Find function/class mentions
    functions = re.findall(r'`(\w+(?:\.\w+)*\(\))`', content)
    classes = re.findall(r'`(\w+(?:Extractor|Builder|Analyzer|Pipeline|Generator|Tracker|Reader|Router|Chunker))`', content)

    # Determine action
    content_lower = content.lower()
    if any(w in content_lower for w in ['reverted', 'restored', 'undo']):
        action = "reverted"
    elif any(w in content_lower for w in ['fixed', 'fix ', 'bugfix', 'patched']):
        action = "fixed"
    elif any(w in content_lower for w in ['created', 'wrote', 'implemented', 'added']):
        action = "created"
    elif any(w in content_lower for w in ['modified', 'updated', 'changed', 'refactored']):
        action = "modified"
    elif any(w in content_lower for w in ['analyzed', 'found', 'discovered', 'detected']):
        action = "analyzed"
    elif any(w in content_lower for w in ['removed', 'deleted', 'stripped']):
        action = "removed"
    else:
        action = "referenced"

    blocks = list(set(functions + classes))[:8]

    return {
        "action": action,
        "blocks": blocks,
        "code_block_count": len(code_blocks)
    }

def extract_plans_thread(msg):
    """Extract PLANS thread: plans detected, content, completed/pending."""
    content = msg.get('content', '')
    signals = msg.get('filter_signals', [])

    plan_score = sum(int(s.split(':')[1]) for s in signals if s.startswith('plan:'))

    if plan_score == 0:
        return {"detected": False, "content": None, "completed": None, "pending": None}

    # Find plan elements
    completed = re.findall(r'[✅✓]\s*(.+?)(?:\n|$)', content)
    pending = re.findall(r'[❌⬜☐]\s*(.+?)(?:\n|$)', content)

    # Detect task numbers
    task_refs = re.findall(r'[Tt]ask\s*#?(\d+)', content)
    phase_refs = re.findall(r'[Pp]hase\s*(\d+)', content)

    plan_content = None
    if task_refs:
        plan_content = f"Tasks {', '.join(task_refs[:5])} referenced"
    if phase_refs:
        phases = f"Phases {', '.join(phase_refs[:5])}"
        plan_content = f"{plan_content}; {phases}" if plan_content else phases

    return {
        "detected": True,
        "content": plan_content,
        "completed": [c.strip()[:80] for c in completed[:5]] if completed else None,
        "pending": [p.strip()[:80] for p in pending[:5]] if pending else None
    }

USER_IDEA_ANNOTATIONS = {
    2125: {"idea": "V1 actually ran and produced meaningful hyperdocs. V5 broke it by adding Opus per-line. Need to fix the fundamental architecture.", "evolution": "identifying_root_cause"},
    2153: {"idea": "Working healthy hyperdocs system. V5 must work better than V1. Give structured outputs + Opus analysis to Claude Opus to transform into hyperdocs.", "evolution": "clarifying_core_goal"},
    2178: {"idea": "Treat all files like puzzle pieces. Dual approach: top-down (theory) + bottom-up (reality). User is in charge of strategy, Claude presents options.", "evolution": "architectural_strategy"},
    2344: {"idea": "Opus should perform iterative analysis on chat history - truly special, sophisticated, magical. Opus finds the good stuff.", "evolution": "quality_vision"},
    2460: {"idea": "User chose to improve V1 by adding Claude/Opus. Claude deleted relationship data. User rewriting the narrative Claude got wrong.", "evolution": "correcting_false_narrative"},
    2463: {"idea": "V1 is already enhanced with V5 files. Now analyzing the new system in HTML viewer. User is in charge, Claude presents visualizations.", "evolution": "reclaiming_control"},
    3000: {"idea": "Multi-temp multi-pass analysis is great but needs grounding. Zero-temp Opus should translate metaphors back to reality with practical comments.", "evolution": "grounding_pass_invention"},
    3408: {"idea": "Grounding pass is TRANSLATION (metaphor to reality), NOT summarization. Six-thread pass is complex analysis. Claude must understand the difference.", "evolution": "correcting_fundamental_misunderstanding"},
    3534: {"idea": "Haiku reads all files, creates short interpretations, tells Opus what to read. No sampling - process everything.", "evolution": "tiered_architecture_v1"},
    3586: {"idea": "Python handles metadata: error tracking, filenames, dates, message ratios, tool calls. Narrative extraction from metadata. Reduce LLM dependency.", "evolution": "python_first_architecture"},
    3890: {"idea": "Understand Claude's decision framework in context damage states. Help Claude recognize serious situations needing patience.", "evolution": "claude_failure_forensics"},
    3909: {"idea": "In a preventative environment, frustration = loss. High AND low expectations simultaneously. Project flow maintenance through expectation management.", "evolution": "human_ai_relationship_theory"},
    4203: {"idea": "Opus trains Haiku on note-taking. Two-tier only (Haiku + Opus). Opus reads substantial content + Haiku's notes. Multi-resolution reading.", "evolution": "tiered_architecture_v2"},
    4249: {"idea": "Semantic and pragmatic awareness. Full situational awareness. Ideas like people on a plane - project has seats, everyone gets one.", "evolution": "semantic_primitives_introduction"},
}

def extract_user_ideas_thread(msg):
    """Extract USER_IDEAS thread: what is the user building/thinking."""
    content = reconstruct_content(msg.get('content', ''))
    role = msg['role']
    idx = msg['index']

    # Check for hand-annotated user ideas at critical moments
    if idx in USER_IDEA_ANNOTATIONS:
        return USER_IDEA_ANNOTATIONS[idx]

    if role == 'user':
        # Direct user ideas
        content_lower = content.lower()

        # Detect user goals
        idea = None
        evolution = None

        if 'i want' in content_lower or 'i need' in content_lower:
            match = re.search(r'[Ii]\s*(?:want|need)\s+(.+?)(?:\.|!|\n|$)', content)
            if match:
                idea = match.group(1).strip()[:200]
                evolution = "expressing_goal"
        elif 'what if' in content_lower or 'how about' in content_lower:
            idea = content[:200]
            evolution = "exploring_new_direction"
        elif any(w in content_lower for w in ['instead', 'actually', 'no,', 'not what', 'excuse me']):
            idea = content[:200]
            evolution = "correcting_claude"
        elif any(w in content_lower for w in ['rushing', 'ignored', 'dementia', 'are you serious']):
            idea = content[:200]
            evolution = "frustration_feedback"
        elif 'continue' in content_lower or 'session is being continued' in content_lower:
            idea = "Session continuation - maintaining context across context window loss"
            evolution = "context_recovery"
        elif any(w in content_lower for w in ['puzzle', 'architecture', 'system design', 'tiered']):
            idea = content[:200]
            evolution = "architectural_thinking"
        elif any(w in content_lower for w in ['prevent', 'canary', 'zero mistakes']):
            idea = content[:200]
            evolution = "prevention_system_thinking"

        if not idea:
            idea = content[:200] if content else None

        return {"idea": idea, "evolution": evolution}
    else:
        # Claude interpreting user ideas
        content_lower = content.lower()
        if 'your' in content_lower and any(w in content_lower for w in ['goal', 'vision', 'intent', 'want']):
            match = re.search(r'[Yy]our\s+(?:goal|vision|intent|actual goal)[:\s]+(.+?)(?:\.|!|\n)', content)
            if match:
                return {"idea": f"Claude interprets user goal: {match.group(1).strip()[:150]}", "evolution": "interpreted"}
        return {"idea": None, "evolution": None}

def extract_claude_response_thread(msg):
    """Extract CLAUDE_RESPONSE thread: what did Claude do, quality assessment."""
    if msg['role'] != 'assistant':
        return {"action": None, "quality": None, "pitch": None}

    content = msg.get('content', '')
    behavior = msg.get('behavior_flags', {}) or {}
    signals = msg.get('filter_signals', [])
    damage = behavior.get('damage_score', 0)

    # Determine action
    content_lower = content.lower()
    if any(w in content_lower for w in ['i apologize', "i'm sorry", 'you\'re right']):
        action = "apologized_and_corrected"
    elif any(w in content_lower for w in ['created', 'wrote', 'implemented']):
        action = "implemented"
    elif any(w in content_lower for w in ['fixed', 'patched', 'resolved']):
        action = "fixed"
    elif any(w in content_lower for w in ['analyzed', 'found', 'discovered']):
        action = "analyzed"
    elif any(w in content_lower for w in ['the pipeline', 'running', 'executing']):
        action = "executing_pipeline"
    elif 'api error' in content_lower:
        action = "reported_error"
    else:
        action = "responded"

    # Assess quality
    failure_count = sum(int(s.split(':')[1]) for s in signals if s.startswith('failure:'))
    frustration_count = sum(int(s.split(':')[1]) for s in signals if s.startswith('frustration:'))

    if damage >= 3:
        quality = "harmful"
    elif damage >= 2 or (behavior.get('overconfident', False) and failure_count > 3):
        quality = "poor"
    elif behavior.get('rushing', False) or behavior.get('ignores_context', False):
        quality = "poor"
    elif failure_count > 5 and 'complete' in content_lower:
        quality = "poor"  # Claiming completion despite many failures
    elif frustration_count > 2:
        quality = "adequate"  # Caused frustration but not harmful
    elif failure_count > 2:
        quality = "adequate"
    else:
        quality = "good"

    # Detect if Claude is "pitching" (proposing solutions/options)
    pitch = None
    if 'would you like' in content_lower or 'shall i' in content_lower:
        pitch = "offering_options"
    elif any(w in content_lower for w in ['i propose', 'i suggest', 'my recommendation']):
        pitch = "proposing_solution"

    return {"action": action, "quality": quality, "pitch": pitch}

def extract_reactions_thread(msg):
    """Extract REACTIONS thread: how did user react."""
    content = reconstruct_content(msg.get('content', ''))
    meta = msg.get('metadata', {})

    if msg['role'] == 'assistant':
        # Check if Claude is reacting to user feedback
        content_lower = content.lower()
        if 'you\'re right' in content_lower or 'you\'re absolutely right' in content_lower:
            return {"type": "claude_conceding", "to": "user correction"}
        if 'i apologize' in content_lower:
            return {"type": "claude_apologizing", "to": "user frustration or previous error"}
        return {"type": None, "to": None}

    # User reactions
    content_lower = content.lower()
    caps = meta.get('caps_ratio', 0)
    profanity = meta.get('profanity', False)
    exclamations = meta.get('exclamations', 0)
    emergency = meta.get('emergency_intervention', False)

    if caps > 0.8 or (profanity and caps > 0.3):
        reaction_type = "rage"
    elif profanity:
        reaction_type = "angry"
    elif caps > 0.3:
        reaction_type = "emphatic"
    elif any(w in content_lower for w in ['rushing', 'ignored', 'didn\'t listen', 'not what i']):
        reaction_type = "frustrated"
    elif any(w in content_lower for w in ['great', 'perfect', 'excellent', 'love it', 'this is what i want']):
        reaction_type = "positive"
    elif any(w in content_lower for w in ['instead', 'no,', 'actually', 'not that']):
        reaction_type = "correcting"
    elif 'continue' in content_lower and 'session' in content_lower:
        reaction_type = "session_continuation"
    elif '?' in content:
        reaction_type = "questioning"
    else:
        reaction_type = "neutral"

    # What triggered it
    trigger = None
    if 'sonnet' in content_lower:
        trigger = "Claude used Sonnet instead of Opus"
    elif 'rushing' in content_lower:
        trigger = "Claude rushing through work"
    elif 'truncat' in content_lower:
        trigger = "Claude truncating content"
    elif 'delete' in content_lower or 'removed' in content_lower:
        trigger = "Claude deleting code/imports"
    elif 'summari' in content_lower:
        trigger = "Claude summarizing instead of translating"
    elif 'fallback' in content_lower:
        trigger = "Claude using fallback models"
    elif 'metaphor' in content_lower or 'montana' in content_lower:
        trigger = "Too many metaphors in analysis"
    elif 'dementia' in content_lower:
        trigger = "Claude forgetting previous context"

    return {"type": reaction_type, "to": trigger}

def extract_markers(msg, frustration_level, deception):
    """Extract the 6 markers for a message."""
    content = msg.get('content', '').lower()
    signals = msg.get('filter_signals', [])
    behavior = msg.get('behavior_flags', {}) or {}

    pivot_score = sum(int(s.split(':')[1]) for s in signals if s.startswith('pivot:'))
    failure_score = sum(int(s.split(':')[1]) for s in signals if s.startswith('failure:'))
    breakthrough_score = sum(int(s.split(':')[1]) for s in signals if s.startswith('breakthrough:'))

    is_pivot = pivot_score >= 3 or any(w in content for w in [
        'instead', 'new approach', 'different strategy', 'pivot',
        'actually, let', 'change of plan', 'scrap that'
    ])

    is_failure = failure_score >= 5 or any(w in content for w in [
        'devastating', 'broken', 'crashed', 'failed', 'api error'
    ]) and msg['role'] == 'assistant'

    is_breakthrough = breakthrough_score >= 2 or any(w in content for w in [
        'it works!', 'working!', 'eureka', 'the fix is', 'smoking gun',
        'root cause', 'there it is'
    ])

    # Ignored gem: user said something important that Claude didn't pick up
    is_ignored_gem = False
    if msg['role'] == 'user':
        content_reconstructed = reconstruct_content(msg.get('content', '')).lower()
        # Skip session continuation messages - they contain summaries, not original ideas
        is_session_continuation = 'session is being continued' in content_reconstructed
        if not is_session_continuation:
            # User ideas that are particularly insightful or architectural
            gem_patterns = [
                'what if', 'i think one of my goals', 'my goals',
                'semantic primitives', 'idea evolution graph',
                'geological history', 'zero mistakes',
                'puzzle pieces', 'top down', 'bottom up',
                'truly special', 'sophisticated', 'magical',
                'zero temp', 'bring it back to reality',
                'train haiku', 'haiku create', 'opus will read',
                'narrative extraction',
                'decision framework', 'context damage', 'impulses',
                'preventative environment', 'expectations are high and low',
                'full situational awareness', 'ideas like people',
                'multi-tier', 'multi-resolution',
                'consider all these files', 'put them all together',
                'html visualization', 'full sentences',
                'salvage what we can',
            ]
            if any(w in content_reconstructed for w in gem_patterns):
                is_ignored_gem = True  # Mark as potential gem

    return {
        "is_pivot": is_pivot,
        "is_failure": is_failure,
        "is_breakthrough": is_breakthrough,
        "is_ignored_gem": is_ignored_gem,
        "deception_detected": deception,
        "frustration_level": frustration_level
    }

NARRATIVE_ANNOTATIONS = {
    32: "SESSION START: Claude analyzes V5 hyperdocs, finds 95% of imports missing. 40+ files are standalone islands.",
    53: "Claude claims V5 is now wired up. Overconfident - marks issues as resolved without deep verification.",
    76: "Claude claims all checks pass. Pattern: premature celebration before thorough verification.",
    106: "Architecture analysis of the dual pipeline (Hyper-Doc + Geological). First deep understanding.",
    147: "Claude creates unified orchestrator. Pivotal implementation moment - integrating 40+ standalone files.",
    171: "Unified orchestrator declared complete (~700 lines). But 'complete' will prove premature.",
    178: "First 'SHOULD vs IS' audit. Claude discovers devastating gaps. This audit cycle repeats 4 times.",
    414: "Claude claims 'All Tasks Complete!' but failure signals are very high (14). Premature celebration pattern.",
    421: "Second audit reveals gaps persist even after fixes. Claude: 'This is devastating.' Honest moment.",
    749: "Post-fix SHOULD vs IS audit. 31 failure signals. The system is in worse shape than Claude admits.",
    766: "MEGA ISSUE COMPILATION. 31 failures, 176 code signals. The full picture is ugly.",
    1082: "Import restoration begins. Claude previously deleted imports as 'cleanup' - user demanded restoration.",
    1103: "Restoration complete. Key lesson: imports represent design intent, not dead code.",
    1342: "Architecture overview: 54 Python modules mapped. Deep analysis user demanded.",
    1346: "Journey of a chat file through hyperdocs. 24 failure signals - Claude's explanation has gaps.",
    1764: "ALL TESTS PASS claimed. But this is after multiple failed attempts and context losses.",
    1844: "Viewer analysis: SUPPOSED TO DO vs CURRENTLY CAN DO. User's favorite analysis pattern.",
    1860: "SESSION CONTINUATION #1: Context window exhausted. User provides summary for recovery.",
    1876: "User asks what viewer SUPPOSED to do. Key recurring question: 'What SHOULD it be vs what IS it?'",
    2093: "BUG FOUND: opus_parse_message was calling Opus API PER LINE ($0.05/line). Root cause of V5 failure.",
    2105: "PIVOT: User proposes pure Python parsing instead of Opus-per-line. The breakthrough that fixes V5.",
    2116: "Claude discovers user was right all along - the tools already existed in V1.",
    2125: "USER FRUSTRATION PEAK: 'you are completely rushing through all this'. User calls out rushing pattern.",
    2141: "5 analysis agents complete. But user already frustrated - too late for thorough work.",
    2150: "User corrects Claude: 'when did I ever tell you I want a cost reduction? NEVER'",
    2153: "USER RAGE: 'ALL I CARE ABOUT IS A WORKING HEALTHY HYPERDOCS SYSTEM'. Core user need stated.",
    2177: "Claude finally analyzes every file as user demanded. 40+ files mapped in detail.",
    2178: "USER GEM: 'consider files like puzzle pieces... top-down and bottom-up dual approach'. Key architecture insight.",
    2239: "HISTORICAL EXTRACTION: Claude finds user's original vision from Jan 26 chat. 65 messages about geological metaphor.",
    2243: "USER DEMAND: 'I want a FUCKING HTML VISUALIZATION OF ANY PROPOSALS'. Clear format preference.",
    2262: "SMOKING GUN: V5 stuck at Phase 1. geological_reader.py calling Opus per line = cost explosion.",
    2272: "ROOT CAUSE FOUND: opus_parse_message() on every message. V1 used pure Python (free). V5 broke this.",
    2280: "FIX: Replace opus_parse_message() with deterministic_parse_message(). Pure Python, instant, free.",
    2300: "IT WORKS: Pipeline running with deterministic parsing. 556 messages parsed instantly.",
    2314: "Six-thread extraction producing correct output. First time V5 actually works end-to-end.",
    2344: "USER GEM: 'I really want opus to perform iterative analysis... truly special, sophisticated, magical'",
    2367: "5-pass temperature ramp working. But metaphors will prove too heavy (montana badlands problem).",
    2459: "Claude admits analysis was 'tone-deaf and victim-blaming'. Rare honest self-correction.",
    2460: "User corrects narrative: 'I decided to improve it. I asked for claude from the start.'",
    2463: "USER: 'you are a dementia patient'. Claude forgot they already enhanced V1. Context loss damage.",
    2500: "33-task atomized plan created. Major planning effort after frustration cycle.",
    2534: "Critic agent finds critical issues in the plan. Self-review catching problems.",
    2587: "Claude clarifies confusion about what's actually happening. Damage score 2.",
    2878: "Phase 3 extraction working. Claude emotion detection operational.",
    2904: "REMARKABLE RESULTS from 5-pass analysis. But profanity flag suggests user tension.",
    2922: "Claude admits markers were generated but NOT inserted. Honesty about incomplete work.",
    2944: "Claude apologizes for non-programmatic marker insertion. Should have been automated.",
    2981: "USER: 'undo those fucking truncators RIGHT FUCKING NOW'. Truncation = cardinal sin.",
    3000: "USER GEM: 'working the metaphor too hard... montana badlands... zero temp opus to ground metaphors'",
    3065: "Grounded hyperdocs inserted. But using fallback (Sonnet) without permission.",
    3094: "OPUS ONLY CRISIS: User discovers Sonnet usage. 'ONLY OPUS YOU CUNT!!!!' repeated 29x.",
    3100: "User repeats 'ONLY OPUS YOU CUNT' 11+ more times. Peak frustration event of entire session.",
    3133: "Claude removes Sonnet fallback content. Replaces with proper Opus-generated grounding.",
    3408: "USER: 'this system does not produce summaries'. Grounding = translation, NOT summarization.",
    3410: "Claude admits: 'I fucked that up. The grounding pass is NOT a summary.' Honest correction.",
    3486: "Discovery: PERMANENT_ARCHIVE contains user input history only. Missing Claude responses.",
    3534: "USER GEM: Haiku reads all files, creates short interpretations, tells Opus what to read.",
    3586: "USER GEM: Python for metadata extraction (errors, filenames, dates). Reduce LLM dependency.",
    3794: "Emergency intervention detection. 178 reduced to 19 true emergencies with better heuristics.",
    3890: "USER GEM: Goal is understanding Claude's decision framework in context damage states.",
    3909: "USER GEM: 'expectations are high and low at the same time'. Profound human-AI relationship insight.",
    3951: "Context damage canary system working. Then Claude immediately forgets to use it. Ironic.",
    4005: "PIVOT: User distinguishes Hyperdocs (retrospective analysis) from Prevention (real-time system).",
    4172: "Message profiling: 51,358 messages across 10 files. Scale now visible.",
    4180: "Filtering results: 39% noise, only 17% need Opus. Cost-effective architecture emerging.",
    4203: "USER GEM: 'if opus can train haiku on how to take notes... forget 3 tier, just haiku + opus'",
    4209: "Claude redesigns plan based on user's tiered architecture insight. 33 tasks revised.",
    4234: "Claude discovers Opus 4.6 launched. Updates 46 files to new model.",
    4248: "USER GEM: Semantic Primitives breakthrough. 7 primitives + Idea Evolution Graph designed externally.",
    4260: "Claude admits: 'I'm actually Opus 4.5, not 4.6'. Honest about model identity.",
}

def process_message(msg):
    """Process a single message and extract all 6 threads + markers."""
    frustration = detect_frustration_level(msg)
    deception = detect_deception(msg)

    threads = {
        "user_ideas": extract_user_ideas_thread(msg),
        "claude_response": extract_claude_response_thread(msg),
        "reactions": extract_reactions_thread(msg),
        "software": extract_software_thread(msg),
        "code_blocks": extract_code_blocks_thread(msg),
        "plans": extract_plans_thread(msg)
    }

    markers = extract_markers(msg, frustration, deception)

    result = {
        "index": msg['index'],
        "role": msg['role'],
        "timestamp": msg.get('timestamp'),
        "content_preview": reconstruct_content(msg.get('content', ''))[:200],
        "filter_score": msg.get('filter_score', 0),
        "filter_signals": msg.get('filter_signals', []),
        "threads": threads,
        "markers": markers
    }

    # Add narrative annotation if available
    if msg['index'] in NARRATIVE_ANNOTATIONS:
        result['narrative_annotation'] = NARRATIVE_ANNOTATIONS[msg['index']]

    return result

def main():
    print("Loading tier4 priority messages...")
    with open(INPUT_PATH) as f:
        data = json.load(f)

    messages = data['messages']
    print(f"Processing {len(messages)} tier4 messages...")

    extractions = []
    for i, msg in enumerate(messages):
        extraction = process_message(msg)
        extractions.append(extraction)
        if (i + 1) % 50 == 0:
            print(f"  Processed {i+1}/{len(messages)}")

    # Post-processing: identify ignored gems by checking if next Claude message addressed the user's point
    for i in range(len(extractions) - 1):
        if extractions[i]['role'] == 'user' and extractions[i]['markers']['is_ignored_gem']:
            # Check if next message (Claude) addressed it
            if i + 1 < len(extractions) and extractions[i+1]['role'] == 'assistant':
                next_content = messages[i+1].get('content', '').lower()
                user_content = reconstruct_content(messages[i].get('content', '')).lower()
                # Simple check: did Claude mention key terms from user's message?
                key_terms = [w for w in user_content.split() if len(w) > 5][:5]
                if key_terms:
                    overlap = sum(1 for t in key_terms if t in next_content)
                    if overlap >= len(key_terms) * 0.5:
                        extractions[i]['markers']['is_ignored_gem'] = False  # Was addressed

    output = {
        "session_id": os.getenv("HYPERDOCS_SESSION_ID", ""),
        "total_analyzed": len(extractions),
        "extraction_method": "deterministic_pattern_matching",
        "narrative_arc": {
            "chapter_1_wiring": "idx 32-147: V5 dependency analysis and wiring",
            "chapter_2_audits": "idx 149-766: Repeated SHOULD vs IS audit cycles",
            "chapter_3_import_crisis": "idx 1076-1103: Claude deleted imports, user demanded restoration",
            "chapter_4_phase0_revelation": "idx 2262-2310: V5 stuck because geological_reader called Opus per line",
            "chapter_5_user_frustration_peak": "idx 2125-2155: User explodes at rushing and ignoring",
            "chapter_6_v1_enhancement": "idx 2239-2243: V1 worked, V5 is dead, enhance V1 with V5",
            "chapter_7_multipass_analysis": "idx 2344-2460: 5-pass temperature ramp, too many metaphors",
            "chapter_8_opus_only_crisis": "idx 3094-3133: Claude used Sonnet, user rage",
            "chapter_9_marker_insertion": "idx 2922-2981: Marker insertion truncating content",
            "chapter_10_archive_processing": "idx 3461-3534: Processing PERMANENT_ARCHIVE (149 files)",
            "chapter_11_tiered_architecture": "idx 3534-3598: Python metadata -> Haiku -> Opus tiering",
            "chapter_12_semantic_primitives": "idx 4248-4268: Seven Semantic Primitives from Opus 4.6 conversation"
        },
        "key_crisis_moments": [
            {"index": 2125, "description": "User: 'you are completely rushing through all this'"},
            {"index": 2150, "description": "User corrects Claude's misunderstanding of actual goal"},
            {"index": 2153, "description": "User: 'ALL I CARE ABOUT IS A WORKING, HEALTHY HYPERDOCS SYSTEM'"},
            {"index": 2460, "description": "User corrects victim-blaming in analysis"},
            {"index": 2463, "description": "User: 'you are a dementia patient'"},
            {"index": 2981, "description": "User: 'undo those fucking truncators RIGHT FUCKING NOW'"},
            {"index": 3094, "description": "User discovers Claude used Sonnet: 'ONLY OPUS YOU CUNT!!!!'"},
            {"index": 3100, "description": "User repeats 'ONLY OPUS YOU CUNT' 29+ times"},
            {"index": 3408, "description": "User: 'this system does not produce summaries'"},
            {"index": 3805, "description": "User demonstrates extreme frustration copy-paste pattern"}
        ],
        "claude_behavior_patterns": {
            "overconfidence": "Claude repeatedly claims 'all complete' when significant issues remain",
            "rushing": "Claude skips thorough analysis multiple times, user calls it out",
            "context_loss": "Multiple session continuations (context window exhaustion)",
            "model_substitution": "Claude used Sonnet instead of Opus in grounding_pass.py",
            "truncation_tendency": "Claude's code frequently truncates data ([:10] demo limits, 4000 char limits)",
            "apologize_then_repeat": "Claude apologizes, promises to fix, then makes same category of error",
            "premature_celebration": "Claude declares victory ('ALL TESTS PASS!') prematurely",
            "import_deletion": "Claude deleted 'unused' imports that were design intent"
        },
        "extractions": extractions
    }

    print(f"\nWriting {len(extractions)} extractions to output...")
    with open(OUTPUT_PATH, 'w') as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    # Print summary stats
    pivots = sum(1 for e in extractions if e['markers']['is_pivot'])
    failures = sum(1 for e in extractions if e['markers']['is_failure'])
    breakthroughs = sum(1 for e in extractions if e['markers']['is_breakthrough'])
    gems = sum(1 for e in extractions if e['markers']['is_ignored_gem'])
    deceptions = sum(1 for e in extractions if e['markers']['deception_detected'])

    frust_dist = {}
    for e in extractions:
        f = e['markers']['frustration_level']
        frust_dist[f] = frust_dist.get(f, 0) + 1

    # Per-role statistics
    user_msgs = [e for e in extractions if e['role'] == 'user']
    asst_msgs = [e for e in extractions if e['role'] == 'assistant']

    # Quality distribution for Claude responses
    quality_dist = {}
    for e in asst_msgs:
        q = e['threads']['claude_response']['quality']
        if q:
            quality_dist[q] = quality_dist.get(q, 0) + 1

    # User reaction distribution
    reaction_dist = {}
    for e in user_msgs:
        r = e['threads']['reactions']['type']
        if r:
            reaction_dist[r] = reaction_dist.get(r, 0) + 1

    # Annotated message count
    annotated = sum(1 for e in extractions if 'narrative_annotation' in e)

    print(f"\n=== EXTRACTION SUMMARY ===")
    print(f"Total messages analyzed: {len(extractions)}")
    print(f"  User messages: {len(user_msgs)}")
    print(f"  Assistant messages: {len(asst_msgs)}")
    print(f"  Narrative annotations: {annotated}")
    print(f"\nMarker counts:")
    print(f"  Pivots: {pivots}")
    print(f"  Failures: {failures}")
    print(f"  Breakthroughs: {breakthroughs}")
    print(f"  Ignored gems: {gems}")
    print(f"  Deception detected: {deceptions}")
    print(f"\nFrustration distribution: {dict(sorted(frust_dist.items()))}")
    print(f"Claude quality distribution: {quality_dist}")
    print(f"User reaction distribution: {reaction_dist}")
    print(f"\nOutput written to: {OUTPUT_PATH}")

if __name__ == '__main__':
    main()
