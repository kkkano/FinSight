# -*- coding: utf-8 -*-
"""
Tests for Search Convergence Module
"""
import pytest
from backend.agents.search_convergence import SearchConvergence, ConvergenceMetrics


class TestSearchConvergence:
    """Test SearchConvergence class"""

    def test_init(self):
        sc = SearchConvergence()
        assert sc._round == 0
        assert sc._low_gain_count == 0

    def test_reset(self):
        sc = SearchConvergence()
        sc._round = 5
        sc._low_gain_count = 2
        sc._seen_urls.add("http://test.com")
        sc.reset()
        assert sc._round == 0
        assert sc._low_gain_count == 0
        assert len(sc._seen_urls) == 0

    def test_dedupe_by_url(self):
        sc = SearchConvergence()
        docs = [
            {"url": "http://a.com", "content": "content a"},
            {"url": "http://a.com", "content": "content a duplicate"},
            {"url": "http://b.com", "content": "content b"},
        ]
        unique, metrics = sc.process_round(docs)
        assert len(unique) == 2
        assert metrics.new_docs_count == 3
        assert metrics.unique_docs_count == 2

    def test_dedupe_by_content_hash(self):
        sc = SearchConvergence()
        docs = [
            {"url": "http://a.com", "content": "same content here"},
            {"url": "http://b.com", "content": "same content here"},
        ]
        unique, metrics = sc.process_round(docs)
        assert len(unique) == 1

    def test_info_gain_first_round(self):
        sc = SearchConvergence()
        docs = [
            {"url": "http://a.com", "content": "new information", "source": "web"},
            {"url": "http://b.com", "content": "more data", "source": "tavily"},
        ]
        unique, metrics = sc.process_round(docs, previous_summary="")
        assert metrics.info_gain > 0.5  # First round should have high gain
        assert metrics.should_stop is False

    def test_stop_on_no_new_docs(self):
        sc = SearchConvergence()
        # First round
        docs1 = [{"url": "http://a.com", "content": "content"}]
        sc.process_round(docs1)
        # Second round with same docs
        unique, metrics = sc.process_round(docs1)
        assert len(unique) == 0
        assert metrics.should_stop is True
        assert "no_new_documents" in metrics.reason

    def test_stop_on_max_rounds(self):
        sc = SearchConvergence()
        sc.MAX_ROUNDS = 2
        # Round 1
        sc.process_round([{"url": "http://a.com", "content": "a"}])
        # Round 2
        _, metrics = sc.process_round([{"url": "http://b.com", "content": "b"}])
        assert metrics.should_stop is True
        assert "max_rounds" in metrics.reason

    def test_stop_on_consecutive_low_gain(self):
        sc = SearchConvergence()
        sc.MIN_GAIN_THRESHOLD = 0.5
        sc.CONSECUTIVE_LOW_GAIN = 2
        sc.MAX_ROUNDS = 10

        # Round 1 - high gain
        sc.process_round([{"url": "http://a.com", "content": "lots of new info here"}])

        # Round 2 - low gain (similar content)
        sc.process_round(
            [{"url": "http://b.com", "content": "similar info"}],
            previous_summary="lots of new info here"
        )

        # Round 3 - low gain again
        _, metrics = sc.process_round(
            [{"url": "http://c.com", "content": "more similar"}],
            previous_summary="lots of new info here similar info"
        )

        assert metrics.should_stop is True
        assert "consecutive_low_gain" in metrics.reason

    def test_similarity_dedup(self):
        sc = SearchConvergence()
        sc.SIMILARITY_THRESHOLD = 0.7

        # First doc
        docs1 = [{"url": "http://a.com", "content": "apple stock price analysis report"}]
        sc.process_round(docs1)

        # Second doc with very similar content
        docs2 = [{"url": "http://b.com", "content": "apple stock price analysis report today"}]
        unique, _ = sc.process_round(docs2)

        # Should be filtered as too similar
        assert len(unique) == 0

    def test_get_stats(self):
        sc = SearchConvergence()
        sc.process_round([{"url": "http://a.com", "content": "test"}])
        sc.process_round([{"url": "http://b.com", "content": "test2"}])

        stats = sc.get_stats()
        assert stats["rounds"] == 2
        assert stats["total_unique_docs"] == 2
        assert "cumulative_gain" in stats

    def test_content_novelty(self):
        sc = SearchConvergence()

        # First round
        docs1 = [{"url": "http://a.com", "content": "apple earnings report q4"}]
        _, m1 = sc.process_round(docs1, previous_summary="")

        # Second round with completely new content
        docs2 = [{"url": "http://b.com", "content": "microsoft azure cloud growth"}]
        _, m2 = sc.process_round(docs2, previous_summary="apple earnings report q4")

        # New content should have decent gain
        assert m2.info_gain > 0.3


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
