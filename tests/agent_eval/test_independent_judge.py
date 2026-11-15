import importlib.util
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location("paged_grading", Path(__file__).with_name("run_paged_grading.py"))
grading = importlib.util.module_from_spec(spec)
spec.loader.exec_module(grading)

SETTINGS = {"FINSIGHT_EVAL_APIKL_API_BASE": "https://apikl.invalid/v1", "FINSIGHT_EVAL_APIKL_API_KEY": "apikl-key",
            "FINSIGHT_EVAL_XFMMDA_API_BASE": "https://xfmmda.invalid/v1", "FINSIGHT_EVAL_XFMMDA_API_KEY": "xfmmda-key",
            "FINSIGHT_EVAL_CHICKENER_API_BASE": "https://chickener.invalid/v1", "FINSIGHT_EVAL_CHICKENER_API_KEY": "chickener-key"}


@pytest.mark.parametrize("model,base,key", [("gpt-6.1-sol", "https://apikl.invalid/v1", "apikl-key"),
                                            ("DeepSeek-V4.1-Flash", "https://xfmmda.invalid/v1", "xfmmda-key"),
                                            ("gpt-6.1-sol", "https://chickener.invalid/v1", "chickener-key")])
def test_declared_judge_uses_only_its_own_endpoint_key(model, base, key):
    assert grading.independent_judge_key(SETTINGS, {"model": model, "base_url": base}) == key


@pytest.mark.parametrize("declared", [{"model": "gpt-6.1-sol", "base_url": "https://xfmmda.invalid/v1"},
                                      {"model": "deepseek-v4.1-flash", "base_url": "https://chickener.invalid/v1"},
                                      {"model": "DeepSeek-V4.1-Flash", "base_url": "https://apikl.invalid/v1"},
                                      {"model": "other", "base_url": "https://apikl.invalid/v1"}])
def test_judge_cannot_borrow_another_provider_credentials(declared):
    with pytest.raises(ValueError, match="^independent_judge_configuration_changed$"):
        grading.independent_judge_key(SETTINGS, declared)


def test_same_base_subject_key_is_never_used_for_judge():
    # APIKL DeepSeek 被测与 APIKL Sol 评分共用 base_url，评分只能取 apikl 评分凭据
    settings = {**SETTINGS, "FINSIGHT_EVAL_APIKLDS_API_BASE": "https://apikl.invalid/v1",
                "FINSIGHT_EVAL_APIKLDS_API_KEY": "apiklds-subject-key"}
    assert grading.independent_judge_key(settings, {"model": "gpt-6.1-sol", "base_url": "https://apikl.invalid/v1"}) == "apikl-key"
    with pytest.raises(ValueError, match="^independent_judge_configuration_changed$"):
        grading.independent_judge_key(settings, {"model": "deepseek-flash", "base_url": "https://apikl.invalid/v1"})
