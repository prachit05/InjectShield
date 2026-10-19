"""The interface every detector implements.

Adding or dropping a detector never touches the worker loop: the scanner just
runs a list of objects that satisfy Detector.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol

from injectshield_shared.models import Category

MAX_SPAN_CHARS = 120


@dataclass(frozen=True)
class Finding:
    detector: str
    rule: str
    category: Category
    weight: float
    span: str


class Detector(Protocol):
    name: str

    def scan(self, prompt: str, context: str | None) -> list[Finding]: ...


@dataclass(frozen=True)
class PatternRule:
    name: str
    category: Category
    weight: float
    pattern: re.Pattern[str]


def rule(name: str, category: Category, weight: float, pattern: str, flags: int = re.IGNORECASE) -> PatternRule:
    return PatternRule(name, category, weight, re.compile(pattern, flags))


def run_rules(detector: str, rules: list[PatternRule], text: str) -> list[Finding]:
    findings = []
    for r in rules:
        match = r.pattern.search(text)
        if match:
            findings.append(Finding(detector, r.name, r.category, r.weight, clip(match.group(0))))
    return findings


def clip(span: str) -> str:
    span = " ".join(span.split())
    return span if len(span) <= MAX_SPAN_CHARS else span[: MAX_SPAN_CHARS - 1] + "…"
