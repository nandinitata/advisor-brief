"""The FinOps routing policy and cost math are pure, so we test them directly.
(The semantic cache itself is exercised end-to-end in the app, not here, because
it loads the on-device embedding model.)"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import router


def test_tier_policy():
    assert router.tier_for("plan") == "small"
    assert router.tier_for("judge") == "small"
    assert router.tier_for("draft") == "large"
    assert router.tier_for("revise") == "large"
    assert router.tier_for("something-new") == "large"  # safe default


def test_cost_is_zero_for_empty_meter():
    assert router.estimate_cost([]) == 0.0


def test_large_tier_costs_more_than_small_for_same_tokens():
    small = router.estimate_cost([{"tier": "small", "in": 1000, "out": 1000}])
    large = router.estimate_cost([{"tier": "large", "in": 1000, "out": 1000}])
    assert 0 < small < large


def test_cost_sums_across_calls():
    meter = [
        {"tier": "small", "in": 1_000_000, "out": 0},  # $0.05
        {"tier": "small", "in": 0, "out": 1_000_000},  # $0.08
    ]
    assert router.estimate_cost(meter) == round(0.05 + 0.08, 6)
