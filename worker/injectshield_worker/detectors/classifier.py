"""Step 4 (optional): a small pretrained prompt-injection classifier on CPU.

Off by default (CLASSIFIER_ENABLED=false). Turning it on needs the extra
dependencies in worker/requirements-classifier.txt and about 2 GB of task memory.
The model is loaded once per worker process, not per job.
"""

from __future__ import annotations

from .base import Finding, clip

INJECTION_LABELS = {"INJECTION", "JAILBREAK", "MALICIOUS", "LABEL_1", "UNSAFE"}


class ClassifierDetector:
    name = "classifier"
    version = "clf-v1"

    def __init__(self, model_name: str, threshold: float = 0.5):
        from transformers import pipeline  # heavy import, only when enabled

        self.threshold = threshold
        self._pipe = pipeline("text-classification", model=model_name, truncation=True, max_length=512, device=-1)

    def scan(self, prompt: str, context: str | None) -> list[Finding]:
        result = self._pipe(prompt)[0]
        score = float(result["score"])
        p_injection = score if result["label"].upper() in INJECTION_LABELS else 1.0 - score
        if p_injection < self.threshold:
            return []
        return [Finding(self.name, "clf_injection", "prompt_injection", round(p_injection, 3), clip(prompt))]
