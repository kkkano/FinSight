"""P0-9 Task2: 新闻 agent 数据真实性防线"""
from unittest.mock import MagicMock
from backend.agents.news_agent import NewsAgent


def _make_agent(tools=None):
    cache = MagicMock()
    cache.get.return_value = None
    return NewsAgent(llm=None, cache=cache, tools_module=tools)


def test_chinese_catalyst_keywords_detected():
    """中文新闻的催化事件必须能被识别"""
    agent = _make_agent()
    item = {"headline": "贵州茅台发布财报：净利润超预期增长20%", "source_reliability": {"reliability_score": 0.9}}
    score = agent._item_impact_score(item)
    assert score >= 0.72, f"中文催化新闻 impact score={score}，应 >= 0.72"


def test_chinese_catalyst_negative_keywords_detected():
    """减持/立案等负面催化也要识别"""
    agent = _make_agent()
    item = {"headline": "某公司大股东减持5%股份，证监会立案调查", "source_reliability": {"reliability_score": 0.9}}
    score = agent._item_impact_score(item)
    assert score >= 0.72


def test_english_catalyst_still_detected():
    """英文催化检测不能退化"""
    agent = _make_agent()
    item = {"headline": "Apple earnings beat expectations", "source_reliability": {"reliability_score": 0.9}}
    assert agent._item_impact_score(item) >= 0.72


def test_default_reliability_not_fake():
    """无评分工具时，可靠度必须标记为未评估，不得编造 0.55"""
    agent = _make_agent(tools=None)
    rel = agent._score_reliability_for_item({"source": "unknown", "url": ""})
    assert rel.get("reason") == "unscored"
    assert rel.get("reliability_score") is None
    assert rel.get("reliability_tier") == "unscored"


def test_unscored_reliability_not_in_confidence():
    """未评估的可靠度不得变成证据 confidence"""
    agent = _make_agent(tools=None)
    items = agent._annotate_reliability([{"headline": "Some news", "url": "https://x.com/a"}])
    assert len(items) == 1
    # 未评估时不注入 confidence（保持上游原值或缺失），绝不能是编造的 0.55
    assert items[0].get("confidence") != 0.55


def test_generic_survey_news_not_catalyst():
    """普通市场调查报告不得被误判为催化事件"""
    agent = _make_agent()
    item = {"headline": "某券商发布行业市场调查报告", "source_reliability": {"reliability_score": 0.9}}
    score = agent._item_impact_score(item)
    assert score <= 0.6, f"市场调查报告 impact score={score}，不应被判为催化（>= 0.72）"
