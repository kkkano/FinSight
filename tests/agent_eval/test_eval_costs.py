"""Step5 实际 usage 的费率估算与未知费用合同。"""
import pytest

from .eval_costs import STEP5_MODEL, STEPFUN_BASE, estimate_step5_cost, sum_cost_estimates


def test_step5_input_cache_and_output_components_use_requested_rates():
    usage = {"prompt_tokens": 1000, "completion_tokens": 100,
             "prompt_tokens_details": {"cached_tokens": 400}}
    estimate = estimate_step5_cost(usage, STEP5_MODEL, STEPFUN_BASE)
    assert estimate["uncached_input_cny"] == pytest.approx(0.0042)
    assert estimate["cached_input_cny"] == pytest.approx(0.00028)
    assert estimate["output_cny"] == pytest.approx(0.002)
    assert estimate["total_cny"] == pytest.approx(0.00648)
    assert estimate["cached_tokens"] == 400 and estimate["cache_discount_applied"] is True


def test_unreported_cache_is_not_deducted_from_input_charge():
    estimate = estimate_step5_cost({"prompt_tokens": 1000, "completion_tokens": 100}, STEP5_MODEL, STEPFUN_BASE)
    assert estimate["cached_tokens"] is None and estimate["cache_discount_applied"] is False
    assert estimate["uncached_input_cny"] == pytest.approx(0.007)
    assert estimate["total_cny"] == pytest.approx(0.009)


@pytest.mark.parametrize("usage", [None, {}, {"total_tokens": 100}, {"prompt_tokens": True, "completion_tokens": 1},
                                    {"prompt_tokens": 1, "completion_tokens": 1, "prompt_tokens_details": {"cached_tokens": 2}}])
def test_missing_or_invalid_usage_never_becomes_zero_fee(usage):
    assert estimate_step5_cost(usage, STEP5_MODEL, STEPFUN_BASE) is None


def test_official_step5_rates_are_not_assigned_to_other_models_or_proxies():
    usage = {"prompt_tokens": 1, "completion_tokens": 1}
    assert estimate_step5_cost(usage, "another-model", STEPFUN_BASE) is None
    assert estimate_step5_cost(usage, STEP5_MODEL, "https://proxy.invalid/v1") is None


def test_cost_totals_preserve_unknown_calls_and_known_components():
    estimate = estimate_step5_cost({"prompt_tokens": 250, "completion_tokens": 26,
                                   "prompt_tokens_details": {"cached_tokens": 0}}, STEP5_MODEL, STEPFUN_BASE)
    assert estimate["total_cny"] == pytest.approx(0.00227)
    total = sum_cost_estimates([estimate, None, estimate])
    assert total["priced_calls"] == 2 and total["unpriced_calls"] == 1
    assert total["known_components"]["uncached_input_cny"] == pytest.approx(0.0035)
    assert total["known_subtotal_cny"] == pytest.approx(0.00454)
    assert total["total_cny"] is None and total["all_calls_priced"] is False
    complete = sum_cost_estimates([estimate, estimate])
    assert complete["total_cny"] == pytest.approx(0.00454) and complete["all_calls_priced"] is True


@pytest.mark.parametrize("estimates", [[], [None]])
def test_no_reported_usage_keeps_total_and_components_unknown(estimates):
    total = sum_cost_estimates(estimates)
    assert total["total_cny"] is None and total["known_subtotal_cny"] is None
    assert all(value is None for value in total["known_components"].values())
    assert total["all_calls_priced"] is False
