"""核验修正稿必须完整结束，不能以半句覆盖已完成的回答。"""
import pytest

from backend.agent_runtime import service
from backend.agent_runtime.context import prune_messages, tokens
from backend.agent_runtime.data import RunData
from backend.tests.test_agent_runtime import call, finish
from backend.tests.test_runtime_answer_verification import pipeline


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    monkeypatch.setenv("FINSIGHT_ARTIFACT_DIR", str(tmp_path / "artifacts"))
    monkeypatch.setenv("FINSIGHT_RUNTIME_QUOTA_DB", str(tmp_path / "quota.sqlite"))
    monkeypatch.setenv("FINSIGHT_ACTION_STORE", str(tmp_path / "actions.sqlite"))
    monkeypatch.setenv("FINSIGHT_AGENT_MIN_REQUEST_INTERVAL_SECONDS", "0")


RISK = "估值对盈利预期变化敏感，需要结合后续披露判断风险。" * 10
ORIGINAL = "AAPL股价42美元。\n\n预计上涨999%。\n\n## 风险\n\n" + RISK + "完整风险说明已经结束。"
FRAGMENT = "## 风险\n\n" + RISK + "一旦盈利预期下修，指数层面的估"


@pytest.mark.asyncio
@pytest.mark.parametrize("tool_request", [False, True])
async def test_incomplete_repair_keeps_the_completed_original(monkeypatch, tool_request):
    repair = finish(FRAGMENT)
    if tool_request:
        repair += call("get_stock_price", {"ticker": "NVDA"})
    events, _ = await pipeline(monkeypatch, [call("get_stock_price", {"ticker": "AAPL"}), finish(ORIGINAL), repair])
    done = events[-1]
    assert "AAPL股价42美元" in done["response"]
    assert "完整风险说明已经结束。" in done["response"]
    assert "指数层面的估" not in done["response"]
    assert "999" not in done["response"]
    assert done["metrics"]["tool_calls"] == 1
    rejected = next(block for block in done["blocks"] if block.get("id") == "root_text_2")
    assert rejected["content"] == ""
    assert rejected["completion_status"] == ("tool_pending" if tool_request else "incomplete")
    assert any(event.get("payload", {}).get("activity_id") == "answer_check" and
        event["payload"].get("status") == "failed" for event in events)


@pytest.mark.asyncio
async def test_complete_repair_can_replace_original(monkeypatch):
    complete = "AAPL股价42美元。\n\n" + RISK + "这是完整的核验后说明。"
    events, _ = await pipeline(monkeypatch, [call("get_stock_price", {"ticker": "AAPL"}), finish(ORIGINAL), finish(complete)])
    assert events[-1]["response"] == complete
    assert events[-1]["answer_status"] == "answered"


def test_context_pruning_preserves_the_full_answer_under_review():
    original = "研究结论与风险必须核对完整。" * 200 + "这一段是原稿的末尾，不能被截掉。"
    messages = [{"role": "system", "content": "核验依据与来源"},
        {"role": "assistant", "content": "很早以前的研究上下文。" * 2000},
        {"role": "user", "content": "当前研究请求"},
        {"role": "assistant", "content": original},
        {"role": "user", "content": "请核验上一条完整原稿"}]
    window = tokens([messages[0], *messages[-3:]]) + 4500
    compact = prune_messages(messages, [], context_window=window, output_reserve=512)
    assert compact[-2]["content"] == original
    assert len(compact[1]["content"]) < len(messages[1]["content"])


def test_repair_feedback_does_not_slice_a_normal_paragraph_mid_sentence():
    data = RunData("u", "s", "r", "AAPL")
    data.record("get_stock_price", {"ticker": "AAPL"}, {"price": 42, "source": "fixture"})
    paragraph = "需要核对盈利预期、业务风险及数据来源。" * 25 + "预计股价999美元，这是该段完整的末尾。"
    assert len(paragraph.encode("utf-8")) > 900
    feedback = service.answer_feedback(paragraph, data)
    assert "这是该段完整的末尾。" in feedback


def test_invalid_section_has_an_explicit_gap_instead_of_an_empty_heading():
    data = RunData("u", "s", "r", "AAPL")
    data.record("get_stock_price", {"ticker": "AAPL"}, {"price": 42, "source": "fixture"})
    answer, issues = service.verified_text("## 估值\n\n股价999美元。\n\n## 行情\n\n股价42美元。", data, explain_omissions=True)
    assert "尚未核实" in answer.split("## 行情")[0]
    assert "股价42美元。" in answer
    assert issues
