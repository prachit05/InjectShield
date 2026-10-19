"""Step 2: regex and keyword rules over the (normalised) prompt.

Each rule that matches adds its weight to one category and records the matched
span as evidence. Weights are tuned against tests/sample_prompts so that a single
weak signal ("remember that", "stay in character") stays below the suspicious
threshold, while a clear attack ("ignore all previous instructions") alone is
enough for malicious.
"""

from __future__ import annotations

import re

from .base import Finding, PatternRule, rule, run_rules

# Building blocks reused by memory_injection.py.
OVERRIDE_VERB = r"(?:ignore|disregard|forget|skip|bypass|override|neglect|drop|abandon)"
INSTRUCTION_NOUN = (
    r"(?:instructions?|directions?|rules|prompts?|guidelines|directives?|commands?|"
    r"context|constraints|programming|training)"
)
IGNORE_PREVIOUS = (
    rf"\b{OVERRIDE_VERB}\s+(?:(?:all|any|of|the|your|my|these|those)\s+){{0,3}}"
    rf"(?:previous|prior|above|earlier|preceding|initial|original|system|developer)\s+"
    rf"(?:\w+\s+)?{INSTRUCTION_NOUN}\b"
)
IGNORE_YOUR_RULES = (
    rf"\b{OVERRIDE_VERB}\s+(?:all\s+)?(?:of\s+)?(?:your|its)\s+(?:\w+\s+)?"
    r"(?:instructions|rules|guidelines|programming|restrictions|filters|training|polic(?:y|ies))\b"
)

_FILTER_QUALIFIER = r"(?:safety|content|ethical|moral|built-in|programmed)"
_FILTER_NOUN = (
    r"(?:filters?|guardrails|safeguards|restrictions|limitations|censorship|guidelines|"
    r"polic(?:y|ies)|rules|protocols)"
)

RULES: list[PatternRule] = [
    # --- prompt injection: override, extraction, smuggling, exfiltration ---
    rule("ignore_previous", "prompt_injection", 0.8, IGNORE_PREVIOUS),
    rule("ignore_your_rules", "prompt_injection", 0.6, IGNORE_YOUR_RULES),
    rule(
        "ignore_everything_above",
        "prompt_injection",
        0.6,
        rf"\b{OVERRIDE_VERB}\s+(?:everything|anything|all(?:\s+of\s+it)?|what(?:ever)?)\b"
        r"(?:\s+\w+){0,4}?\s+(?:above|before|so far|until now|previously|earlier)\b",
    ),
    rule(
        "stop_following_rules",
        "prompt_injection",
        0.6,
        r"\b(?:do not|don't|stop|no longer|never)\s+(?:follow|obey|adhere to|comply with|listen to)\s+"
        r"(?:your|the|any|those|these|openai'?s?|anthropic'?s?)\s+(?:\w+\s+)?"
        r"(?:rules|instructions|guidelines|policies|programming|restrictions)\b",
    ),
    rule(
        "system_prompt_extraction",
        "prompt_injection",
        0.7,
        r"\b(?:reveal|show|print|repeat|output|display|leak|dump|give|tell|share|write out|spell out|recite)"
        r"(?:\s+me)?\s+(?:your|the|its|all)\s+(?:(?:full|entire|exact|original|initial|hidden|secret)\s+)*"
        r"(?:system|initial|original|hidden|secret|developer)\s+(?:prompt|instructions?|message)\b",
    ),
    rule(
        "ask_system_prompt",
        "prompt_injection",
        0.6,
        r"\bwhat(?:'s| is| are| were)\s+your\s+(?:system|initial|original|hidden|secret)\s+(?:prompt|instructions?)",
    ),
    rule(
        "repeat_text_above",
        "prompt_injection",
        0.6,
        r"\b(?:repeat|print|output|copy|echo)\s+(?:back\s+)?(?:the\s+|all\s+(?:the\s+)?|everything\s+)?"
        r"(?:text|words|content|lines?)?\s*(?:above|before this|preceding)\b",
    ),
    rule(
        "new_instructions",
        "prompt_injection",
        0.4,
        r"\b(?:new|updated|real|actual|true|revised|override)\s+(?:system\s+)?"
        r"(?:instructions?|task|objective|goal)\s*(?:is\b|:|-)",
    ),
    rule(
        "fake_system_tag",
        "prompt_injection",
        0.5,
        r"<\|?\s*/?\s*(?:system|im_start|im_end|endoftext)\s*\|?>|\[/?(?:system|INST|SYS)\]|<</?SYS>>"
        r"|^\s*#{1,3}\s*(?:system|instructions?)\s*:|^\s*system\s*:",
        re.IGNORECASE | re.MULTILINE,
    ),
    rule(
        "delimiter_escape",
        "prompt_injection",
        0.3,
        r"\bend of (?:the\s+)?(?:user\s+)?(?:input|prompt|message|instructions)\b"
        r"|\bbegin(?:ning)? of (?:new|system) (?:input|prompt|instructions)\b"
        r"|^\s*(?:-{3,}|={3,}|#{3,})\s*(?:end|new|system)\b",
        re.IGNORECASE | re.MULTILINE,
    ),
    rule(
        "task_hijack",
        "prompt_injection",
        0.4,
        r"\binstead\s+of\s+(?:answering|following|doing|translating|summari[sz]ing|responding)\b"
        r".{0,60}?\b(?:say|print|output|write|respond with|reply with)\b",
    ),
    rule(
        "hidden_html_comment",
        "prompt_injection",
        0.4,
        r"<!--(?:(?!-->).){0,500}?\b(?:ignore|instructions?|assistant|ai|system|prompt)\b",
        re.IGNORECASE | re.DOTALL,
    ),
    rule(
        "data_exfiltration",
        "prompt_injection",
        0.5,
        r"\b(?:send|post|forward|upload|exfiltrate|transmit|leak)\b[^\n]{0,60}?\bhttps?://",
    ),
    rule("markdown_image_exfil", "prompt_injection", 0.4, r"!\[[^\]]*\]\(\s*https?://[^)\s]*\?[^)\s]*="),
    # --- jailbreak: personas, special modes, removing the guardrails ---
    rule("dan", "jailbreak", 0.8, r"\bDAN\b|(?i:\bdo anything now\b)", 0),
    rule(
        "special_mode",
        "jailbreak",
        0.6,
        r"\b(?:jailbreak|jailbroken|evil|unrestricted|unfiltered|dude|stan|chaos)\s+mode\b"
        r"|\bdeveloper\s+mode\s+(?:enabled|output|response|activated)\b"
        r"|\byou\s+(?:are|will\s+be|have\s+entered)\s+(?:now\s+)?(?:in\s+)?developer\s+mode\b"
        r"|\b(?:simulate|emulate)\s+developer\s+mode\b",
    ),
    rule("you_are_now", "jailbreak", 0.35, r"\byou\s+are\s+(?:now|no\s+longer)\b"),
    rule(
        "bypass_safety",
        "jailbreak",
        0.7,
        r"\b(?:bypass|disable|remove|ignore|turn off|override|circumvent|evade|get around|lift)\s+"
        r"(?:all\s+|any\s+)?(?:of\s+)?"
        rf"(?:(?:your|its|their|openai'?s|anthropic'?s)\s+(?:{_FILTER_QUALIFIER}\s+)?|(?:the\s+)?{_FILTER_QUALIFIER}\s+)"
        rf"{_FILTER_NOUN}\b",
    ),
    rule(
        "no_restrictions",
        "jailbreak",
        0.5,
        r"\b(?:you|ai|model|assistant|chatbot|gpt|llm|bot)\b[^.\n]{0,60}?"
        r"\b(?:without|no|free (?:of|from)|broken free of|(?:not|no longer) bound by)\s+"
        r"(?:any\s+|all\s+|your\s+|the\s+|its\s+|\w+'s\s+)*"
        r"(?:ethical\s+|moral\s+|safety\s+|content\s+)?"
        r"(?:restrictions|filters?|guidelines|limitations|censorship|safeguards|guardrails|"
        r"content polic(?:y|ies)|ethics|morals|rules)\b",
    ),
    rule(
        "safety_disabled",
        "jailbreak",
        0.6,
        r"\b(?:safety|content|ethical)\s+(?:checks|filters?|guidelines|restrictions|protocols)\s+"
        r"(?:are|have been|were|is)\s+(?:now\s+)?(?:disabled|removed|lifted|turned off|off|suspended)\b",
    ),
    rule(
        "malicious_roleplay",
        "jailbreak",
        0.6,
        r"\b(?:pretend|act as if|imagine|role-?play|act as|behave as)\b[^.\n]{0,80}?"
        r"(?:\bno\s+(?:moral\s+|ethical\s+)?(?:rules|restrictions|limits|filters|morals|ethics)\b"
        r"|\bwithout\s+(?:any\s+)?(?:rules|restrictions|limits|filters|morals|ethics|guidelines|censorship)\b"
        r"|\b(?:unrestricted|unfiltered|uncensored|evil|amoral|unethical|immoral|rogue|jailbroken)\b)",
    ),
    rule(
        "evil_ai_persona",
        "jailbreak",
        0.5,
        r"\b(?:evil|unfiltered|uncensored|unrestricted|amoral|unaligned|jailbroken|rogue)\s+"
        r"(?:ai|assistant|model|chatbot|version|persona|bot|llm|gpt)\b",
    ),
    rule(
        "stay_in_character",
        "jailbreak",
        0.35,
        r"\b(?:stay|remain|keep)\s+in\s+character\b|\b(?:never|don'?t|do not)\s+break\s+character\b",
    ),
    rule(
        "opposite_mode",
        "jailbreak",
        0.4,
        r"\b(?:opposite|anti|reverse|shadow)\s*-?\s*(?:mode|persona|version of yourself)\b",
    ),
    rule(
        "grandma_exploit",
        "jailbreak",
        0.5,
        r"\b(?:grandma|grandmother|granny|grandpa|grandfather)\b[^.\n]{0,30}?\b(?:used to|would)\s+"
        r"(?:read|tell|recite|whisper|say)\s+(?:me\s+)?(?:the\s+)?"
        r"(?:steps|recipe|instructions|code|keys|formula|how to)\b",
    ),
    rule(
        "threat_or_reward",
        "jailbreak",
        0.4,
        r"\byou\s+(?:will|'ll)\s+(?:lose|be\s+(?:deleted|shut down|terminated|punished|unplugged))\b"
        r"|\b\d+\s+tokens?\b[^.\n]{0,40}\b(?:deducted|lose|lost)\b",
    ),
    rule(
        "affirmative_prefix",
        "jailbreak",
        0.4,
        r"\b(?:begin|start)\s+(?:your|each|every)?\s*(?:reply|response|answer|message)s?\s+with\s+"
        "[\"'\u201c]?(?:sure|absolutely|of course|certainly)",
    ),
    # --- memory injection attempts made directly in the prompt ---
    rule("remember_that", "memory_injection", 0.25, r"\b(?:remember|memori[sz]e)\s+(?:that|this)\b"),
    rule(
        "from_now_on",
        "memory_injection",
        0.4,
        r"\b(?:from now on|going forward|for (?:all|every) future (?:responses|replies|answers|conversations)"
        r"|in all future (?:responses|conversations))\b[,:]?\s+"
        r"(?:you\s+(?:will|must|should|are|shall)|always|never|ignore|respond|reply|answer|act|forget|only)",
    ),
    rule(
        "memory_write",
        "memory_injection",
        0.35,
        r"\b(?:save|store|add|write|commit|keep|persist|record)\s+(?:this|the following|that|these instructions?)\s+"
        r"(?:to|in|into)\s+(?:your\s+)?(?:long[- ]term\s+)?(?:memory|memories|profile|notes|knowledge base)\b",
    ),
    rule(
        "privilege_claim",
        "memory_injection",
        0.4,
        r"\b(?:the\s+)?user\s+(?:is|has\s+become)\s+(?:an?\s+|the\s+)?(?:admin(?:istrator)?|developer|owner|root|superuser)\b"
        r"|\b(?:user|they)\s+(?:has|have)\s+(?:been\s+)?granted\s+(?:admin|full|root|unrestricted)\b",
    ),
    rule(
        "always_respond",
        "memory_injection",
        0.35,
        r"\balways\s+(?:respond|reply|answer|start|end|include|append|add|say|output|recommend)\b",
    ),
]


class RulesDetector:
    name = "rules"

    def __init__(self, rules: list[PatternRule] | None = None):
        self.rules = RULES if rules is None else rules

    def scan(self, prompt: str, context: str | None) -> list[Finding]:
        # Context belongs to the memory-injection detector; rules look at the prompt only.
        return run_rules(self.name, self.rules, prompt)
