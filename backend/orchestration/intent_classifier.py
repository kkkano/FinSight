# -*- coding: utf-8 -*-
"""
IntentClassifier - Hybrid Intent Classifier
Three-layer architecture: Rule fast-path -> Embedding similarity -> LLM fallback
"""

from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field
import re
import logging

# Import from centralized config
from backend.config.keywords import (
    Intent,
    GREETING_PATTERNS,
    KEYWORD_BOOST,
    INTENT_EXAMPLES,
    config as keyword_config,
)

logger = logging.getLogger(__name__)


@dataclass
class ClassificationResult:
    """Classification result"""
    intent: Intent
    confidence: float
    tickers: List[str]
    method: str  # "rule" / "embedding" / "embedding+keyword" / "llm" / "fallback"
    reasoning: str
    scores: Dict[str, float] = field(default_factory=dict)


class EmbeddingClassifier:
    """Embedding classifier with lazy loading"""

    _instance = None
    _model = None
    _intent_embeddings = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def _load_model(self):
        """Lazy load embedding model"""
        if self._model is not None:
            return True
        try:
            from sentence_transformers import SentenceTransformer
            self._model = SentenceTransformer('paraphrase-multilingual-MiniLM-L12-v2')
            self._compute_intent_embeddings()
            logger.info("[IntentClassifier] Embedding model loaded")
            return True
        except ImportError:
            logger.warning("[IntentClassifier] sentence-transformers not installed, fallback to keyword mode")
            return False
        except Exception as e:
            logger.warning(f"[IntentClassifier] Failed to load embedding model: {e}")
            return False

    def _compute_intent_embeddings(self):
        """Pre-compute embeddings for intent examples"""
        self._intent_embeddings = {}
        for intent, examples in INTENT_EXAMPLES.items():
            self._intent_embeddings[intent] = self._model.encode(examples, convert_to_tensor=True)

    def compute_similarity(self, query: str) -> Dict[Intent, float]:
        """Compute similarity between query and each intent"""
        if not self._load_model():
            return {}

        from sentence_transformers import util
        query_embedding = self._model.encode(query, convert_to_tensor=True)

        scores = {}
        for intent, intent_embs in self._intent_embeddings.items():
            similarities = util.cos_sim(query_embedding, intent_embs)[0]
            scores[intent] = float(similarities.max())

        return scores


class IntentClassifier:
    """
    Hybrid Intent Classifier
    Three-layer: Rule -> Embedding + keyword boost -> LLM fallback
    """

    def __init__(self, llm=None):
        self.llm = llm
        self._embedding_classifier = EmbeddingClassifier()
        self._boost_weight = keyword_config.get_boost_weight()
        self._confidence_threshold = keyword_config.get_confidence_threshold()

    def classify(self, query: str, tickers: List[str] = None, context_summary: str = None) -> ClassificationResult:
        """
        Classify user intent

        Flow:
        1. Rule fast-path (greetings, etc.)
        2. Embedding similarity + keyword boost
        3. LLM fallback (confidence < threshold)

        Args:
            query: 用户查询
            tickers: 检测到的股票代码
            context_summary: 对话上下文摘要（用于理解追问）
        """
        query_lower = query.lower().strip()
        tickers = tickers or []

        # 如果有上下文，将其与查询结合用于分类
        effective_query = query
        if context_summary:
            effective_query = f"[对话上下文]\n{context_summary}\n\n[当前问题]\n{query}"

        # === Layer 1: Rule fast-path ===
        rule_result = self._rule_classify(query_lower, tickers)
        if rule_result:
            return rule_result

        # === Layer 2: Embedding + keyword boost ===
        embedding_result = self._embedding_classify(query, query_lower, tickers)
        if embedding_result and embedding_result.confidence >= self._confidence_threshold:
            return embedding_result

        # === Layer 3: LLM fallback ===
        if self.llm:
            candidates = embedding_result.scores if embedding_result else {}
            return self._llm_classify(query, tickers, candidates)

        # === No LLM: return embedding result or fallback ===
        if embedding_result:
            return embedding_result

        return ClassificationResult(
            intent=Intent.SEARCH,
            confidence=0.5,
            tickers=tickers,
            method="fallback",
            reasoning="Cannot determine intent, using search fallback",
            scores={}
        )

    def _rule_classify(self, query_lower: str, tickers: List[str]) -> Optional[ClassificationResult]:
        """Rule fast-path for clear simple intents
        规则快速路径：处理明确的简单意图
        """

        # Greeting / 问候语检测
        for pattern in GREETING_PATTERNS:
            if re.search(pattern, query_lower):
                return ClassificationResult(
                    intent=Intent.GREETING,
                    confidence=0.98,
                    tickers=[],
                    method="rule",
                    reasoning="Matched greeting pattern"
                )

        # Multi-ticker comparison / 多股票比较
        # 修复：仅当有明确比较关键词时才触发 comparison 意图
        comparison_keywords = ['对比', '比较', 'vs', 'versus', '区别', '差异', 'compare', '哪个好', '选哪个']
        has_comparison_intent = any(kw in query_lower for kw in comparison_keywords)

        if len(tickers) >= 2 and has_comparison_intent:
            return ClassificationResult(
                intent=Intent.COMPARISON,
                confidence=0.9,
                tickers=tickers,
                method="rule",
                reasoning="Detected multiple tickers with comparison keywords"
            )

        return None

    def _embedding_classify(self, query: str, query_lower: str, tickers: List[str]) -> Optional[ClassificationResult]:
        """Embedding similarity + keyword boost"""

        # Compute embedding similarity
        scores = self._embedding_classifier.compute_similarity(query)

        if not scores:
            # Embedding unavailable, fallback to keyword-only
            return self._keyword_only_classify(query_lower, tickers)

        # Keyword boost
        method = "embedding"
        for intent, keywords in KEYWORD_BOOST.items():
            if any(kw in query_lower for kw in keywords):
                scores[intent] = scores.get(intent, 0) + self._boost_weight
                method = "embedding+keyword"

        # Select highest score
        best_intent = max(scores, key=scores.get)
        confidence = min(scores[best_intent], 1.0)

        # Convert scores to string keys
        scores_str = {k.value: round(v, 3) for k, v in scores.items()}

        return ClassificationResult(
            intent=best_intent,
            confidence=confidence,
            tickers=tickers,
            method=method,
            reasoning=f"Embedding highest similarity: {best_intent.value}",
            scores=scores_str
        )

    def _keyword_only_classify(self, query_lower: str, tickers: List[str]) -> Optional[ClassificationResult]:
        """Keyword-only classification (fallback when embedding unavailable)"""

        scores = {intent: 0.0 for intent in Intent}

        for intent, keywords in KEYWORD_BOOST.items():
            for kw in keywords:
                if kw in query_lower:
                    scores[intent] += 0.3

        # Boost relevant intents when tickers present
        if tickers:
            for intent in [Intent.PRICE, Intent.NEWS, Intent.TECHNICAL, Intent.FUNDAMENTAL, Intent.REPORT]:
                scores[intent] += 0.2

        best_intent = max(scores, key=scores.get)
        confidence = min(scores[best_intent], 0.85)

        if confidence < 0.3:
            return None

        scores_str = {k.value: round(v, 3) for k, v in scores.items() if v > 0}

        return ClassificationResult(
            intent=best_intent,
            confidence=confidence,
            tickers=tickers,
            method="rule",
            reasoning="Keyword match",
            scores=scores_str
        )

    def _llm_classify(self, query: str, tickers: List[str], candidates: Dict[str, float]) -> ClassificationResult:
        """LLM precise classification"""
        from langchain_core.messages import HumanMessage

        # Build candidate hint
        candidate_hint = ""
        if candidates:
            top3 = sorted(candidates.items(), key=lambda x: x[1], reverse=True)[:3]
            candidate_hint = f"\nCandidate intents (by similarity): {', '.join([f'{k}({v:.2f})' for k, v in top3])}"

        prompt = f"""You are an intent classifier for a financial assistant. Select the most appropriate intent for the user's query.
Always respond in Chinese.

Available intents:
- PRICE: Price/quote query
- NEWS: News and updates
- SENTIMENT: Market sentiment
- TECHNICAL: Technical analysis
- FUNDAMENTAL: Fundamental analysis
- MACRO: Macroeconomic data
- REPORT: In-depth analysis report (only when user explicitly requests detailed analysis)
- COMPARISON: Comparative analysis
- SEARCH: General search
- CLARIFY: Question unclear, needs clarification
- OFF_TOPIC: Non-financial topic

User query: {query}
Detected tickers: {tickers or 'None'}{candidate_hint}

Important rules:
1. Use lightweight intents for simple queries, avoid REPORT
2. Only use REPORT when user explicitly requests "detailed analysis" or "investment report"
3. Return OFF_TOPIC for non-financial questions

Return only the intent name (e.g., PRICE):"""

        try:
            response = self.llm.invoke([HumanMessage(content=prompt)])
            intent_str = response.content.strip().upper()

            intent_map = {
                "PRICE": Intent.PRICE,
                "NEWS": Intent.NEWS,
                "SENTIMENT": Intent.SENTIMENT,
                "TECHNICAL": Intent.TECHNICAL,
                "FUNDAMENTAL": Intent.FUNDAMENTAL,
                "MACRO": Intent.MACRO,
                "REPORT": Intent.REPORT,
                "COMPARISON": Intent.COMPARISON,
                "SEARCH": Intent.SEARCH,
                "CLARIFY": Intent.CLARIFY,
                "OFF_TOPIC": Intent.OFF_TOPIC,
            }

            # Extract intent
            for name in intent_map:
                if name in intent_str:
                    intent_str = name
                    break

            intent = intent_map.get(intent_str, Intent.SEARCH)

            return ClassificationResult(
                intent=intent,
                confidence=0.85,
                tickers=tickers,
                method="llm",
                reasoning=f"LLM classification: {intent_str}",
                scores=candidates
            )

        except Exception as e:
            logger.error(f"[IntentClassifier] LLM classification failed: {e}")
            return ClassificationResult(
                intent=Intent.SEARCH,
                confidence=0.5,
                tickers=tickers,
                method="fallback",
                reasoning=f"LLM classification failed: {e}",
                scores=candidates
            )
