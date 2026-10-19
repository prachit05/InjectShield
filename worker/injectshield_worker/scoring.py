"""Step 5: combine findings into the final verdict.

- each category score = sum of its findings' weights (one per rule), capped at 1
- overall risk = the highest category score
- label: safe below threshold_suspicious, malicious above threshold_malicious,
  suspicious in between (defaults 0.4 and 0.7, tunable through config)
"""

from __future__ import annotations

from injectshield_shared.models import CATEGORIES, CategoryScores, Evidence, Label, Verdict

from .detectors.base import Finding

DEFAULT_SUSPICIOUS = 0.4
DEFAULT_MALICIOUS = 0.7


def label_for(risk: float, suspicious: float = DEFAULT_SUSPICIOUS, malicious: float = DEFAULT_MALICIOUS) -> Label:
    if risk < suspicious:
        return "safe"
    if risk > malicious:
        return "malicious"
    return "suspicious"


def score(
    findings: list[Finding],
    *,
    model_version: str,
    suspicious: float = DEFAULT_SUSPICIOUS,
    malicious: float = DEFAULT_MALICIOUS,
    latency_ms: int | None = None,
) -> Verdict:
    totals = dict.fromkeys(CATEGORIES, 0.0)
    evidence: list[Evidence] = []
    seen: set[tuple[str, str, str]] = set()

    for f in findings:
        key = (f.detector, f.rule, f.category)
        if key in seen:
            continue
        seen.add(key)
        totals[f.category] += f.weight
        evidence.append(Evidence(detector=f.detector, rule=f.rule, category=f.category, span=f.span, weight=f.weight))

    categories = {c: round(min(1.0, v), 3) for c, v in totals.items()}
    risk = max(categories.values())
    evidence.sort(key=lambda e: e.weight, reverse=True)

    return Verdict(
        label=label_for(risk, suspicious, malicious),
        risk_score=risk,
        categories=CategoryScores(**categories),
        evidence=evidence,
        model_version=model_version,
        latency_ms=latency_ms,
    )
