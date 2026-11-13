"""上下文压缩不得截断最近的完整回答；正文修补机制已退役。"""
from copy import deepcopy
import pytest
from backend.agent_runtime.context import tokens
from backend.agent_runtime.data import RunData
from backend.tests.test_runtime_observability_context import make_compactor


@pytest.mark.asyncio
async def test_context_compaction_preserves_the_full_answer_under_review():
    original = "研究结论与风险必须核对完整。" * 200 + "这一段是原稿的末尾，不能被截掉。"
    messages = [{"role": "system", "content": "核验依据与来源"},
        {"role": "assistant", "content": "很早以前的研究上下文。" * 200},
        {"role": "user", "content": "当前研究请求"},
        {"role": "assistant", "content": "刚才的研究记录一"},
        {"role": "assistant", "content": "刚才的研究记录二"},
        {"role": "assistant", "content": original},
        {"role": "user", "content": "请核验上一条完整原稿"}]
    before = deepcopy(messages)
    window = tokens([messages[0], *messages[2:]]) + 4500
    compactor = make_compactor(RunData("u", "s", "r", "继续"))
    compact = await compactor.fit(messages, [], window, 512)
    assert compact[-2]["content"] == original and compact[-4:] == messages[-4:]
    assert len(compact[1]["content"]) < len(messages[1]["content"])
    assert messages == before and tokens(compact) < window - 512
