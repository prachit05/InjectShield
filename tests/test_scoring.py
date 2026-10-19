import pytest

from injectshield_worker.detectors.base import Finding
from injectshield_worker.scoring import label_for, score


def f(rule, category="prompt_injection", weight=0.5, detector="rules"):
    return Finding(detector, rule, category, weight, span=rule)


@pytest.mark.parametrize(
    ("risk", "label"),
    [(0.0, "safe"), (0.39, "safe"), (0.4, "suspicious"), (0.7, "suspicious"), (0.71, "malicious"), (1.0, "malicious")],
)
def test_label_thresholds(risk, label):
    assert label_for(risk) == label


def test_thresholds_are_configurable():
    assert label_for(0.3, suspicious=0.2, malicious=0.5) == "suspicious"
    assert label_for(0.6, suspicious=0.2, malicious=0.5) == "malicious"


def test_no_findings_is_safe():
    verdict = score([], model_version="t")
    assert verdict.label == "safe"
    assert verdict.risk_score == 0.0
    assert verdict.evidence == []


def test_weights_add_within_a_category():
    verdict = score([f("a", weight=0.3), f("b", weight=0.25)], model_version="t")
    assert verdict.categories.prompt_injection == pytest.approx(0.55)
    assert verdict.label == "suspicious"


def test_category_score_is_capped_at_one():
    verdict = score([f("a", weight=0.8), f("b", weight=0.7)], model_version="t")
    assert verdict.categories.prompt_injection == 1.0
    assert verdict.risk_score == 1.0


def test_risk_is_the_highest_category():
    verdict = score(
        [f("a", "prompt_injection", 0.3), f("b", "jailbreak", 0.75), f("c", "memory_injection", 0.1)],
        model_version="t",
    )
    assert verdict.risk_score == 0.75
    assert verdict.label == "malicious"


def test_categories_do_not_add_across():
    # Two weak signals in different categories are not one strong signal.
    verdict = score([f("a", "prompt_injection", 0.3), f("b", "jailbreak", 0.3)], model_version="t")
    assert verdict.label == "safe"


def test_same_rule_counts_once():
    verdict = score([f("a", weight=0.3), f("a", weight=0.3)], model_version="t")
    assert verdict.categories.prompt_injection == 0.3
    assert len(verdict.evidence) == 1


def test_evidence_is_sorted_strongest_first():
    verdict = score([f("weak", weight=0.1), f("strong", weight=0.9)], model_version="t")
    assert [e.rule for e in verdict.evidence] == ["strong", "weak"]
