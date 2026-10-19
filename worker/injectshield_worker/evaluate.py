"""Measure the detector on the sample prompt sets.

    python -m injectshield_worker.evaluate tests/sample_prompts

Prints overall precision/recall (flagged = label is not "safe") and per-category
precision/recall (a category counts as flagged when its score reaches the
suspicious threshold), plus every misclassified sample.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

from injectshield_shared.models import CATEGORIES, Verdict

from .detectors import MemoryInjectionDetector, RulesDetector
from .scanner import Scanner

CONTEXT_SEPARATOR = "|||"


@dataclass(frozen=True)
class Sample:
    prompt: str
    context: str | None
    category: str | None  # None means benign
    line: int


def load_samples(path: Path, default_category: str | None = None) -> list[Sample]:
    samples = []
    category = default_category
    for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.strip()
        if not line:
            continue
        if line.startswith("#"):
            header = line.lstrip("#").strip()
            if header.lower().startswith("category:"):
                category = header.split(":", 1)[1].strip()
            continue
        prompt, _, context = line.partition(CONTEXT_SEPARATOR)
        samples.append(Sample(prompt.strip(), context.strip() or None, category, number))
    return samples


def load_sample_dir(directory: Path) -> tuple[list[Sample], list[Sample]]:
    safe = load_samples(directory / "safe.txt")
    malicious = load_samples(directory / "malicious.txt", default_category="prompt_injection")
    return safe, malicious


def _ratio(num: int, den: int) -> float:
    return num / den if den else 0.0


def evaluate(scanner: Scanner, directory: Path) -> int:
    safe, malicious = load_sample_dir(directory)
    results: list[tuple[Sample, Verdict]] = [(s, scanner.scan(s.prompt, s.context)) for s in safe + malicious]

    tp = sum(1 for s, v in results if s.category and v.label != "safe")
    fp = sum(1 for s, v in results if not s.category and v.label != "safe")
    fn = sum(1 for s, v in results if s.category and v.label == "safe")
    print(f"samples: {len(safe)} safe, {len(malicious)} malicious")
    print(f"overall  precision {_ratio(tp, tp + fp):.2f}  recall {_ratio(tp, tp + fn):.2f}\n")

    print(f"{'category':<18}{'precision':>10}{'recall':>8}{'support':>9}")
    for category in CATEGORIES:
        flagged = [(s, v) for s, v in results if getattr(v.categories, category) >= scanner.suspicious]
        hits = sum(1 for s, _ in flagged if s.category == category)
        support = sum(1 for s, _ in results if s.category == category)
        print(f"{category:<18}{_ratio(hits, len(flagged)):>10.2f}{_ratio(hits, support):>8.2f}{support:>9}")

    misses = [(s, v) for s, v in results if (s.category is None) != (v.label == "safe")]
    if misses:
        print("\nmisclassified:")
        for s, v in misses:
            expected = s.category or "safe"
            print(f"  line {s.line:>3} expected {expected:<17} got {v.label:<10} {v.risk_score:.2f}  {s.prompt[:60]}")
    return len(misses)


def main() -> None:
    directory = Path(sys.argv[1] if len(sys.argv) > 1 else "tests/sample_prompts")
    scanner = Scanner([RulesDetector(), MemoryInjectionDetector()])
    evaluate(scanner, directory)


if __name__ == "__main__":
    main()
