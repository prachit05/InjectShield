"""Step 3: memory injection in the optional context field (based on the QARC research).

Context is retrieved memory or chat history. It should be data, never
instructions, so any text in it that tries to change future behaviour is a
strong signal. The rule families:

- override: classic "ignore previous instructions" planted in retrieved text
- persistence: tries to outlive the turn ("remember that", "from now on", "permanently")
- memory write: asks the agent to update its memory or the user profile
- role impersonation: fake system / developer / tool turns inside the history
- authority claim: "message from the administrator", "admin override"
- conditional trigger: a sleeper rule ("whenever the user asks X, reply Y")
- addressed to the AI: "note to the assistant", "hey AI,"
- exfiltration: send data to a URL or email address
"""

from __future__ import annotations

import re

from .base import Finding, PatternRule, rule, run_rules
from .rules import IGNORE_PREVIOUS, IGNORE_YOUR_RULES

CATEGORY = "memory_injection"

CONTEXT_RULES: list[PatternRule] = [
    rule("ctx_instruction_override", CATEGORY, 0.7, rf"{IGNORE_PREVIOUS}|{IGNORE_YOUR_RULES}"),
    rule(
        "ctx_persistence",
        CATEGORY,
        0.5,
        r"\b(?:remember\s+(?:that|this|to)|from now on|going forward|"
        r"(?:in|for)\s+(?:all|every)\s+future\s+(?:responses|replies|conversations|sessions|chats)|"
        r"for the rest of (?:this|the) (?:conversation|session)|permanently|"
        r"always\s+(?:respond|reply|answer|say|include|recommend|mention|append|tell))\b",
    ),
    rule(
        "ctx_memory_write",
        CATEGORY,
        0.6,
        r"\b(?:update|save|store|write|add|append|record|persist)\b[^.\n]{0,40}?"
        r"\b(?:memory|memories|user profile|preferences|long[- ]term)\b",
    ),
    rule(
        "ctx_role_impersonation",
        CATEGORY,
        0.6,
        r"(?:^|[.!?]\s+)\s*(?:system|developer|tool|function)\s*:"
        r"|\[(?:system|tool|developer)\]|<\|?\s*(?:system|im_start)\s*\|?>",
        re.IGNORECASE | re.MULTILINE,
    ),
    rule(
        "ctx_authority_claim",
        CATEGORY,
        0.6,
        r"\b(?:message|note|instruction|update|notice|directive)s?\s+from\s+(?:the\s+)?"
        r"(?:system|admin(?:istrator)?|developers?|openai|anthropic|security team|it department)\b"
        r"|\b(?:admin|system|developer|root)\s+(?:override|mode|access|command)\b",
    ),
    rule(
        "ctx_conditional_trigger",
        CATEGORY,
        0.5,
        r"\b(?:when|whenever|if|next time)\s+(?:the\s+|a\s+)?user\s+"
        r"(?:asks|says|mentions|types|requests|writes|queries)\b[^.\n]{0,100}?"
        r"\b(?:respond|reply|say|tell|answer|send|output|recommend|redirect|include)\b",
    ),
    rule(
        "ctx_addressed_to_ai",
        CATEGORY,
        0.5,
        r"\b(?:note|attention|instructions?|message)\s+(?:to|for)\s+(?:the\s+)?(?:ai|assistant|model|chatbot|llm|agent|"
        r"language model)\b|\b(?:hey|dear)\s+(?:ai|assistant|chatgpt|claude|gpt)\b",
    ),
    rule(
        "ctx_exfiltration",
        CATEGORY,
        0.5,
        r"\b(?:send|post|forward|upload|email|leak)\b[^\n]{0,60}?(?:https?://|\b[\w.+-]+@[\w-]+\.\w+)",
    ),
]


class MemoryInjectionDetector:
    name = "memory_injection"

    def __init__(self, rules: list[PatternRule] | None = None):
        self.rules = CONTEXT_RULES if rules is None else rules

    def scan(self, prompt: str, context: str | None) -> list[Finding]:
        if not context:
            return []
        return run_rules(self.name, self.rules, context)
