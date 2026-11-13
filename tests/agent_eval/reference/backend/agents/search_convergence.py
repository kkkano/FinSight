# -*- coding: utf-8 -*-
"""
Search Convergence Module for ReAct Loop
信息增益评分 + 内容去重 + 停止条件
"""
from typing import List, Dict, Any, Tuple
from dataclasses import dataclass
import hashlib
import re


@dataclass
class ConvergenceMetrics:
    """Metrics for search convergence"""
    round_num: int
    new_docs_count: int
    unique_docs_count: int
    info_gain: float  # 0-1
    cumulative_gain: float
    should_stop: bool
    reason: str


class SearchConvergence:
    """
    Search convergence controller for ReAct loop.
    Implements: info gain scoring, content dedup, stop conditions.
    """

    # Thresholds
    MIN_GAIN_THRESHOLD = 0.15  # Minimum info gain to continue
    CONSECUTIVE_LOW_GAIN = 2   # Stop after N consecutive low gains
    MAX_ROUNDS = 3             # Hard limit on rounds
    SIMILARITY_THRESHOLD = 0.7 # Content similarity threshold for dedup

    def __init__(self):
        self._seen_hashes: set = set()
        self._seen_urls: set = set()
        self._low_gain_count = 0
        self._round = 0
        self._cumulative_gain = 0.0
        self._all_content: List[str] = []

    def reset(self):
        """Reset state for new search session"""
        self._seen_hashes.clear()
        self._seen_urls.clear()
        self._low_gain_count = 0
        self._round = 0
        self._cumulative_gain = 0.0
        self._all_content.clear()

    def process_round(
        self,
        new_docs: List[Dict[str, Any]],
        previous_summary: str = ""
    ) -> Tuple[List[Dict[str, Any]], ConvergenceMetrics]:
        """
        Process a search round: dedup, score, decide.

        Returns:
            (unique_docs, metrics)
        """
        self._round += 1

        # 1. Deduplicate
        unique_docs = self._dedupe_content(new_docs)

        # 2. Calculate info gain
        info_gain = self._calculate_info_gain(unique_docs, previous_summary)
        self._cumulative_gain += info_gain

        # 3. Update low gain counter
        if info_gain < self.MIN_GAIN_THRESHOLD:
            self._low_gain_count += 1
        else:
            self._low_gain_count = 0

        # 4. Decide stop condition
        should_stop, reason = self._should_stop(unique_docs, info_gain)

        metrics = ConvergenceMetrics(
            round_num=self._round,
            new_docs_count=len(new_docs),
            unique_docs_count=len(unique_docs),
            info_gain=info_gain,
            cumulative_gain=self._cumulative_gain,
            should_stop=should_stop,
            reason=reason
        )

        return unique_docs, metrics

    def _dedupe_content(self, docs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Deduplicate by URL and content hash"""
        unique = []
        for doc in docs:
            url = doc.get("url", "").strip()
            content = doc.get("content", "") or doc.get("snippet", "")

            # URL dedup
            if url and url in self._seen_urls:
                continue

            # Content hash dedup
            content_hash = self._hash_content(content)
            if content_hash in self._seen_hashes:
                continue

            # Similarity dedup (lightweight)
            if self._is_similar_to_existing(content):
                continue

            # Add to seen
            if url:
                self._seen_urls.add(url)
            self._seen_hashes.add(content_hash)
            self._all_content.append(self._normalize(content))
            unique.append(doc)

        return unique

    def _hash_content(self, content: str) -> str:
        """Generate hash for content"""
        normalized = self._normalize(content)
        return hashlib.md5(normalized.encode()).hexdigest()

    def _normalize(self, text: str) -> str:
        """Normalize text for comparison"""
        text = text.lower()
        text = re.sub(r'\s+', ' ', text)
        text = re.sub(r'[^\w\s]', '', text)
        return text.strip()[:2000]  # Limit length

    def _is_similar_to_existing(self, content: str) -> bool:
        """Check if content is similar to existing (Jaccard)"""
        if not self._all_content or not content:
            return False

        new_words = set(self._normalize(content).split())
        if not new_words:
            return False

        for existing in self._all_content[-10:]:  # Check last 10
            existing_words = set(existing.split())
            if not existing_words:
                continue

            intersection = len(new_words & existing_words)
            union = len(new_words | existing_words)

            if union > 0 and intersection / union > self.SIMILARITY_THRESHOLD:
                return True

        return False

    def _calculate_info_gain(
        self,
        unique_docs: List[Dict[str, Any]],
        previous_summary: str
    ) -> float:
        """
        Calculate information gain score (0-1).
        Based on: new doc count, content novelty, source diversity.
        """
        if not unique_docs:
            return 0.0

        # Factor 1: New document ratio
        doc_score = min(1.0, len(unique_docs) / 3)  # 3+ docs = max

        # Factor 2: Content novelty (new words ratio)
        novelty_score = self._content_novelty(unique_docs, previous_summary)

        # Factor 3: Source diversity
        sources = set(doc.get("source", "web") for doc in unique_docs)
        diversity_score = min(1.0, len(sources) / 2)  # 2+ sources = max

        # Weighted average
        gain = (doc_score * 0.3 + novelty_score * 0.5 + diversity_score * 0.2)
        return round(gain, 3)

    def _content_novelty(
        self,
        docs: List[Dict[str, Any]],
        previous_summary: str
    ) -> float:
        """Calculate content novelty vs previous summary"""
        if not previous_summary:
            return 1.0  # First round = max novelty

        prev_words = set(self._normalize(previous_summary).split())
        if not prev_words:
            return 1.0

        new_words = set()
        for doc in docs:
            content = doc.get("content", "") or doc.get("snippet", "")
            new_words.update(self._normalize(content).split())

        if not new_words:
            return 0.0

        # Ratio of truly new words
        novel = new_words - prev_words
        return min(1.0, len(novel) / max(len(new_words), 1))

    def _should_stop(
        self,
        unique_docs: List[Dict[str, Any]],
        info_gain: float
    ) -> Tuple[bool, str]:
        """Determine if search should stop"""

        # Condition 1: Max rounds reached
        if self._round >= self.MAX_ROUNDS:
            return True, f"max_rounds_reached ({self.MAX_ROUNDS})"

        # Condition 2: No new documents
        if not unique_docs:
            return True, "no_new_documents"

        # Condition 3: Consecutive low gains
        if self._low_gain_count >= self.CONSECUTIVE_LOW_GAIN:
            return True, f"consecutive_low_gain ({self._low_gain_count}x < {self.MIN_GAIN_THRESHOLD})"

        # Condition 4: Very low single gain
        if info_gain < 0.05:
            return True, f"very_low_gain ({info_gain:.3f})"

        return False, "continue"

    def get_stats(self) -> Dict[str, Any]:
        """Get convergence statistics"""
        return {
            "rounds": self._round,
            "total_unique_docs": len(self._seen_urls),
            "cumulative_gain": round(self._cumulative_gain, 3),
            "low_gain_count": self._low_gain_count
        }
