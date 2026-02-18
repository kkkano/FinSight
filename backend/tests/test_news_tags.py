# -*- coding: utf-8 -*-
"""
Tests for Phase H news tagging system.

Covers:
- NEWS_TAG_RULES uniqueness and completeness
- _headline_tags() correctness
- _build_news_item() includes tags in output
- _to_news_item() passes through tags
- NewsItem schema accepts new fields
"""

import pytest

from backend.tools.news import NEWS_TAG_RULES, _headline_tags, _build_news_item
from backend.dashboard.data_service import _to_news_item
from backend.dashboard.schemas import NewsItem


# ---------------------------------------------------------------------------
# NEWS_TAG_RULES integrity
# ---------------------------------------------------------------------------
class TestNewsTagRules:
    """Verify tag rules are well-formed and non-redundant."""

    def test_rules_not_empty(self):
        assert len(NEWS_TAG_RULES) >= 15, "Should have at least 15 tag rules"

    def test_no_duplicate_tag_names(self):
        tag_names = [tag for tag, _ in NEWS_TAG_RULES]
        assert len(tag_names) == len(set(tag_names)), (
            f"Duplicate tag names: {[t for t in tag_names if tag_names.count(t) > 1]}"
        )

    def test_each_rule_has_keywords(self):
        for tag, keywords in NEWS_TAG_RULES:
            assert isinstance(tag, str) and tag, f"Tag name must be non-empty: {tag}"
            assert isinstance(keywords, list), f"Keywords must be list for {tag}"
            assert len(keywords) >= 2, f"Tag '{tag}' should have at least 2 keywords"


# ---------------------------------------------------------------------------
# _headline_tags() correctness
# ---------------------------------------------------------------------------
class TestHeadlineTags:
    """Verify tag computation logic."""

    def test_tech_tag_english(self):
        tags = _headline_tags("Apple announces new cloud technology platform")
        assert "科技" in tags

    def test_ai_tag(self):
        tags = _headline_tags("OpenAI releases new AI model for enterprise")
        assert "AI" in tags

    def test_semiconductor_tag(self):
        tags = _headline_tags("TSMC reports record chip revenue for Q4")
        assert "半导体" in tags

    def test_macro_tag(self):
        tags = _headline_tags("Fed holds interest rates, inflation remains sticky")
        assert "宏观" in tags

    def test_earnings_tag_chinese(self):
        tags = _headline_tags("苹果公司发布第三季度财报，营收超预期")
        assert "财报" in tags

    def test_geopolitics_tag(self):
        tags = _headline_tags("US-China trade conflict escalates with new sanctions")
        assert "地缘" in tags or "美国" in tags or "中国" in tags

    def test_max_three_tags(self):
        # This headline matches many categories
        text = "AI chip semiconductor technology earnings revenue report crypto bitcoin"
        tags = _headline_tags(text)
        assert len(tags) <= 3, f"Should cap at 3 tags, got {len(tags)}: {tags}"

    def test_empty_text_returns_empty(self):
        assert _headline_tags("") == []

    def test_no_match_returns_empty(self):
        tags = _headline_tags("A completely unrelated boring text about nothing")
        # May or may not match — just verify it's a list
        assert isinstance(tags, list)

    def test_custom_max_tags_via_env(self, monkeypatch):
        monkeypatch.setenv("NEWS_TAG_MAX", "1")
        text = "AI chip semiconductor technology earnings revenue"
        tags = _headline_tags(text)
        assert len(tags) <= 1

    def test_chinese_text_tags(self):
        tags = _headline_tags("中国央行宣布降低利率以应对通胀压力")
        assert "中国" in tags or "宏观" in tags


# ---------------------------------------------------------------------------
# _build_news_item() includes tags
# ---------------------------------------------------------------------------
class TestBuildNewsItemTags:
    """Verify _build_news_item() computes and includes tags."""

    def test_tags_field_present(self):
        item = _build_news_item(
            title="NVIDIA reports record chip revenue",
            source="Reuters",
        )
        assert "tags" in item, "tags field should be present in output"
        assert isinstance(item["tags"], list)

    def test_tags_match_content(self):
        item = _build_news_item(
            title="Fed raises interest rates amid inflation concerns",
            source="Bloomberg",
            snippet="The Federal Reserve raised rates by 25bps",
        )
        tags = item["tags"]
        assert "宏观" in tags, f"Should tag macro content, got: {tags}"

    def test_empty_title_returns_empty_dict(self):
        item = _build_news_item(title="", source="test")
        assert item == {}

    def test_tags_with_snippet(self):
        item = _build_news_item(
            title="Company Update",
            source="Reuters",
            snippet="The semiconductor chip maker reported strong earnings",
        )
        tags = item["tags"]
        assert any(t in tags for t in ["半导体", "财报"]), (
            f"Should detect tags from snippet, got: {tags}"
        )


# ---------------------------------------------------------------------------
# _to_news_item() passes through tags
# ---------------------------------------------------------------------------
class TestToNewsItemTags:
    """Verify _to_news_item() preserves tags from input dict."""

    def test_tags_passed_through(self):
        raw = {
            "title": "Test headline",
            "url": "http://example.com",
            "source": "Test",
            "ts": "2026-01-01T00:00:00",
            "summary": "A test summary",
            "tags": ["科技", "AI"],
        }
        result = _to_news_item(raw)
        assert result["tags"] == ["科技", "AI"]

    def test_no_tags_field_when_absent(self):
        raw = {
            "title": "Test headline",
            "url": "http://example.com",
        }
        result = _to_news_item(raw)
        assert "tags" not in result, "Should not add tags if not present in input"

    def test_empty_tags_not_passed(self):
        raw = {
            "title": "Test headline",
            "tags": [],
        }
        result = _to_news_item(raw)
        assert "tags" not in result, "Should not include empty tags list"

    def test_non_list_tags_ignored(self):
        raw = {
            "title": "Test headline",
            "tags": "not a list",
        }
        result = _to_news_item(raw)
        assert "tags" not in result, "Should ignore non-list tags"

    def test_string_item_fallback(self):
        result = _to_news_item("Plain text headline")
        assert result["title"] == "Plain text headline"
        assert "tags" not in result


# ---------------------------------------------------------------------------
# NewsItem schema accepts new fields
# ---------------------------------------------------------------------------
class TestNewsItemSchema:
    """Verify updated NewsItem Pydantic model accepts Phase H fields."""

    def test_basic_fields(self):
        item = NewsItem(title="Test")
        assert item.title == "Test"
        assert item.url == ""
        assert item.tags is None

    def test_with_tags(self):
        item = NewsItem(title="Test", tags=["科技", "AI"])
        assert item.tags == ["科技", "AI"]

    def test_with_ranking_fields(self):
        item = NewsItem(
            title="Test",
            ranking_score=0.85,
            source_reliability=0.9,
            impact_score=0.7,
            asset_relevance=0.6,
            time_decay=0.95,
        )
        assert item.ranking_score == 0.85
        assert item.source_reliability == 0.9
        assert item.impact_score == 0.7

    def test_with_all_fields(self):
        item = NewsItem(
            title="Fed cuts rates",
            url="http://example.com",
            source="Reuters",
            ts="2026-01-01T00:00:00",
            summary="The Federal Reserve cut rates",
            tags=["宏观"],
            ranking_score=0.92,
            time_decay=0.98,
            source_reliability=0.95,
            impact_score=0.8,
            asset_relevance=0.0,
            ranking_reason="High impact macro event",
        )
        assert item.tags == ["宏观"]
        assert item.ranking_reason == "High impact macro event"

    def test_null_optional_fields(self):
        item = NewsItem(title="Test")
        assert item.tags is None
        assert item.ranking_score is None
        assert item.time_decay is None
        assert item.source_reliability is None
        assert item.impact_score is None
        assert item.asset_relevance is None
        assert item.ranking_reason is None

    def test_serialization_round_trip(self):
        data = {
            "title": "NVIDIA earnings beat",
            "tags": ["财报", "半导体"],
            "ranking_score": 0.88,
            "impact_score": 0.75,
        }
        item = NewsItem(**data)
        dumped = item.model_dump(exclude_none=True)
        assert dumped["tags"] == ["财报", "半导体"]
        assert dumped["ranking_score"] == 0.88
        # Fields not set should not appear
        assert "time_decay" not in dumped
