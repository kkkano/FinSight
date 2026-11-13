"""绘图追问使用显式工具协议，已有资料和实时追加要求完整传给模型。"""
import pytest
from backend.tests.test_agent_runtime import runtime, finish, call


def test_context_estimate_counts_tokens_offline_instead_of_utf8_bytes(monkeypatch):
    from backend.agent_runtime.context import _tokenizer, tokens
    import socket

    def forbid_network(*_args, **_kwargs):
        raise AssertionError("分词估算不应联网")

    monkeypatch.setattr(socket, "create_connection", forbid_network)
    _tokenizer.cache_clear()
    text = "英特尔的营业利润与现金流需要使用实际披露数据核验。" * 100
    assert len(text) // 3 < tokens(text) < len(text.encode("utf-8")) * .75


@pytest.mark.asyncio
async def test_live_chart_instruction_produces_artifact_before_answer(tmp_path):
    rt, events = runtime(tmp_path, [])
    rt.query = "解释英特尔的价格走势"
    raw = {"rows": [{"time": "2026-10-01", "close": 80}, {"time": "2026-10-02", "close": 60}]}
    ref = rt.data.record("get_stock_historical_data", {"ticker": "INTC"}, raw)
    rt.instruct("画个图给我解释一下", "chart-request")
    rt.model.turns = [call("render_chart", {"handle": ref, "title": "INTC价格走势", "chart_type": "line",
                     "x": "time", "series": [{"field": "close"}]}), finish("已画出价格走势，可看到区间回落。")]
    try:
        result = await rt.run_agent()
        assert "已画出" in result["summary"] and result["stopped"] == "completed"
        assert any(message.get("content") == "画个图给我解释一下" for message in rt.model.inputs[0])
        assert len(rt.data.artifacts) == 1 and rt.data.artifacts[0]["data"]["rows"] == raw["rows"]
        kinds = [kind for kind, _, _ in events]
        assert kinds.index("artifact.ready") < kinds.index("content.delta")
    finally:
        await rt.close()
