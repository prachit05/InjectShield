"""The detection pipeline: normalise, run every detector, score."""

from __future__ import annotations

import time

from injectshield_shared.config import Settings
from injectshield_shared.models import Verdict

from .detectors import Detector, MemoryInjectionDetector, RulesDetector
from .normalize import normalize
from .scoring import DEFAULT_MALICIOUS, DEFAULT_SUSPICIOUS, score

BASE_VERSION = "rules-v1+mem-v1"


class Scanner:
    def __init__(
        self,
        detectors: list[Detector],
        *,
        model_version: str = BASE_VERSION,
        suspicious: float = DEFAULT_SUSPICIOUS,
        malicious: float = DEFAULT_MALICIOUS,
    ):
        self.detectors = detectors
        self.model_version = model_version
        self.suspicious = suspicious
        self.malicious = malicious

    def scan(self, prompt: str, context: str | None = None) -> Verdict:
        started = time.perf_counter()

        norm_prompt = normalize(prompt, "prompt_injection")
        norm_context = normalize(context, "memory_injection") if context else None

        findings = list(norm_prompt.findings)
        if norm_context:
            findings += norm_context.findings
        for detector in self.detectors:
            findings += detector.scan(norm_prompt.text, norm_context.text if norm_context else None)

        latency_ms = int((time.perf_counter() - started) * 1000)
        return score(
            findings,
            model_version=self.model_version,
            suspicious=self.suspicious,
            malicious=self.malicious,
            latency_ms=latency_ms,
        )


def build_scanner(settings: Settings) -> Scanner:
    detectors: list[Detector] = [RulesDetector(), MemoryInjectionDetector()]
    version = BASE_VERSION
    if settings.classifier_enabled:
        from .detectors.classifier import ClassifierDetector

        classifier = ClassifierDetector(settings.classifier_model)
        detectors.append(classifier)
        version += f"+{classifier.version}"
    return Scanner(
        detectors,
        model_version=version,
        suspicious=settings.threshold_suspicious,
        malicious=settings.threshold_malicious,
    )
