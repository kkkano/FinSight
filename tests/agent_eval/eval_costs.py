"""按官方公告的新用户费率估算 Step5 已报告用量，不替代实际账单。"""
STEP5_MODEL = "step-5-preview"
STEPFUN_BASE = "https://api.stepfun.com/v1"
STEP5_PRICING = {"currency": "CNY", "uncached_input_per_million": 7,
                 "cached_input_per_million": 0.70, "output_per_million": 20, "cache_rate_basis": "new_user"}
COMPONENTS = ("uncached_input_cny", "cached_input_cny", "output_cny", "total_cny")


def estimate_step5_cost(usage, model: str, base_url: str):
    if model != STEP5_MODEL or base_url.rstrip("/") != STEPFUN_BASE or not isinstance(usage, dict):
        return None
    prompt, output = usage.get("prompt_tokens"), usage.get("completion_tokens")
    if type(prompt) is not int or type(output) is not int or min(prompt, output) < 0:
        return None
    details = usage.get("prompt_tokens_details")
    cached = details.get("cached_tokens") if isinstance(details, dict) else None
    if cached is not None and (type(cached) is not int or not 0 <= cached <= prompt):
        return None
    discounted = cached if cached is not None else 0
    uncached = prompt - discounted
    return {"currency": "CNY", "prompt_tokens": prompt, "completion_tokens": output,
            "cached_tokens": cached, "cache_discount_applied": cached is not None,
            "uncached_input_cny": uncached * 7 / 1000000,
            "cached_input_cny": discounted * 7 / 10000000,
            "output_cny": output * 20 / 1000000,
            "total_cny": (uncached * 70 + discounted * 7 + output * 200) / 10000000}


def sum_cost_estimates(estimates):
    estimates = list(estimates)
    known = [estimate for estimate in estimates if estimate is not None]
    components = {name: round(sum(estimate[name] for estimate in known), 7) if known else None
                  for name in COMPONENTS}
    all_priced = bool(estimates) and len(known) == len(estimates)
    return {"currency": "CNY", "priced_calls": len(known), "unpriced_calls": len(estimates) - len(known),
            "all_calls_priced": all_priced, "known_components": components,
            "known_subtotal_cny": components["total_cny"],
            "total_cny": components["total_cny"] if all_priced else None}
