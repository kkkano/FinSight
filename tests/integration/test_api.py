"""
API 集成测试
"""

import pytest
from fastapi.testclient import TestClient
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime
from decimal import Decimal

from finsight.api.main import create_app
from finsight.api.dependencies import (
    ServiceContainer,
    get_service_container,
    get_orchestrator,
    get_report_writer,
    get_time_service,
)
from finsight.domain.models import (
    Intent,
    ResponseMode,
    AnalysisResult,
    StockPrice,
    MarketSentiment,
)


@pytest.fixture
def mock_orchestrator(mock_stock_price, mock_market_sentiment, mock_news_items):
    """创建模拟编排器"""
    orchestrator = Mock()

    # 默认返回成功的分析结果
    def create_mock_result(intent=Intent.STOCK_PRICE, success=True):
        result = AnalysisResult(
            request_id="test-id",
            intent=intent,
            mode=ResponseMode.SUMMARY,
            success=success,
        )
        result.tools_called = ["mock_tool"]
        return result

    orchestrator.process.return_value = create_mock_result()
    return orchestrator


@pytest.fixture
def mock_report_writer():
    """创建模拟报告生成器"""
    writer = Mock()
    writer.generate.return_value = "# 测试报告\n\n这是一份测试报告。"
    return writer


@pytest.fixture
def test_client(mock_orchestrator, mock_report_writer, mock_time_port):
    """创建测试客户端"""
    app = create_app()

    # 覆盖依赖注入
    app.dependency_overrides[get_orchestrator] = lambda: mock_orchestrator
    app.dependency_overrides[get_report_writer] = lambda: mock_report_writer
    app.dependency_overrides[get_time_service] = lambda: mock_time_port

    return TestClient(app)


class TestHealthEndpoints:
    """健康检查端点测试"""

    def test_health_check(self, test_client):
        """测试健康检查"""
        response = test_client.get("/health")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] in ["healthy", "degraded"]

    def test_ready_check(self, test_client):
        """测试就绪检查"""
        response = test_client.get("/ready")

        assert response.status_code == 200
        data = response.json()
        assert data["ready"] == True

    def test_live_check(self, test_client):
        """测试存活检查"""
        response = test_client.get("/live")

        assert response.status_code == 200
        data = response.json()
        assert data["alive"] == True

    def test_root_endpoint(self, test_client):
        """测试根端点"""
        response = test_client.get("/")

        assert response.status_code == 200
        data = response.json()
        assert "message" in data
        assert "version" in data


class TestAnalysisEndpoints:
    """分析端点测试"""

    def test_analyze_stock_price(self, test_client, mock_orchestrator, mock_stock_price):
        """测试股票价格分析"""
        # 配置返回结果
        mock_result = AnalysisResult(
            request_id="test-id",
            intent=Intent.STOCK_PRICE,
            mode=ResponseMode.SUMMARY,
            success=True,
        )
        mock_result.stock_price = mock_stock_price
        mock_result.tools_called = ["get_stock_price"]
        mock_orchestrator.process.return_value = mock_result

        response = test_client.post(
            "/api/v1/analyze",
            json={
                "query": "AAPL 股价多少",
                "mode": "summary",
            }
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"]

    def test_analyze_with_clarification(self, test_client, mock_orchestrator):
        """测试需要追问的分析"""
        from finsight.domain.models import ClarifyQuestion

        mock_result = AnalysisResult(
            request_id="test-id",
            intent=Intent.UNCLEAR,
            mode=ResponseMode.SUMMARY,
            needs_clarification=True,
            clarify_question=ClarifyQuestion(
                question="请问您想查询什么？",
                field_name="query",
                reason="输入不明确",
            ),
        )
        mock_orchestrator.process.return_value = mock_result

        response = test_client.post(
            "/api/v1/analyze",
            json={
                "query": "嗯嗯",  # 至少2个字符才能通过验证
                "mode": "summary",
            }
        )

        assert response.status_code == 200
        data = response.json()
        assert data["needs_clarification"]

    def test_get_stock_price(self, test_client, mock_orchestrator, mock_stock_price):
        """测试获取股票价格端点"""
        mock_result = AnalysisResult(
            request_id="test-id",
            intent=Intent.STOCK_PRICE,
            mode=ResponseMode.SUMMARY,
            success=True,
        )
        mock_result.stock_price = mock_stock_price
        mock_result.tools_called = ["get_stock_price"]
        mock_orchestrator.process.return_value = mock_result

        response = test_client.get("/api/v1/stock/AAPL/price")

        assert response.status_code == 200

    def test_get_stock_news(self, test_client, mock_orchestrator, mock_news_items):
        """测试获取股票新闻端点"""
        mock_result = AnalysisResult(
            request_id="test-id",
            intent=Intent.STOCK_NEWS,
            mode=ResponseMode.SUMMARY,
            success=True,
        )
        mock_result.news_items = mock_news_items
        mock_result.tools_called = ["get_company_news"]
        mock_orchestrator.process.return_value = mock_result

        response = test_client.get("/api/v1/stock/AAPL/news")

        assert response.status_code == 200

    def test_get_market_sentiment(self, test_client, mock_orchestrator, mock_market_sentiment):
        """测试获取市场情绪端点"""
        mock_result = AnalysisResult(
            request_id="test-id",
            intent=Intent.MARKET_SENTIMENT,
            mode=ResponseMode.SUMMARY,
            success=True,
        )
        mock_result.market_sentiment = mock_market_sentiment
        mock_result.tools_called = ["get_market_sentiment"]
        mock_orchestrator.process.return_value = mock_result

        response = test_client.get("/api/v1/market/sentiment")

        assert response.status_code == 200

    def test_compare_assets(self, test_client, mock_orchestrator, mock_performance_comparison):
        """测试资产对比端点"""
        mock_result = AnalysisResult(
            request_id="test-id",
            intent=Intent.COMPARE_ASSETS,
            mode=ResponseMode.SUMMARY,
            success=True,
        )
        mock_result.comparison = mock_performance_comparison
        mock_result.tools_called = ["get_performance_comparison"]
        mock_orchestrator.process.return_value = mock_result

        response = test_client.post(
            "/api/v1/compare",
            json={
                "tickers": ["AAPL", "GOOGL"],
                "mode": "summary",
            }
        )

        assert response.status_code == 200

    def test_get_stock_analysis(self, test_client, mock_orchestrator):
        """测试深度股票分析端点"""
        mock_result = AnalysisResult(
            request_id="test-id",
            intent=Intent.STOCK_ANALYSIS,
            mode=ResponseMode.DEEP,
            success=True,
            report="# 深度分析报告\n\n这是 AAPL 的分析报告。",
        )
        mock_result.tools_called = ["analyze_stock"]
        mock_orchestrator.process.return_value = mock_result

        response = test_client.get("/api/v1/stock/AAPL/analysis")

        assert response.status_code == 200

    def test_get_economic_events(self, test_client, mock_orchestrator):
        """测试经济日历端点"""
        mock_result = AnalysisResult(
            request_id="test-id",
            intent=Intent.MACRO_EVENTS,
            mode=ResponseMode.SUMMARY,
            success=True,
        )
        mock_result.tools_called = ["search"]
        mock_orchestrator.process.return_value = mock_result

        response = test_client.get("/api/v1/market/events")

        assert response.status_code == 200


class TestErrorHandling:
    """错误处理测试"""

    def test_invalid_request(self, test_client):
        """测试无效请求"""
        response = test_client.post(
            "/api/v1/analyze",
            json={}  # 缺少必要字段
        )

        assert response.status_code == 422  # Validation error

    def test_internal_error(self, test_client, mock_orchestrator):
        """测试内部错误处理"""
        mock_orchestrator.process.side_effect = Exception("Test error")

        response = test_client.post(
            "/api/v1/analyze",
            json={
                "query": "AAPL",
                "mode": "summary",
            }
        )

        assert response.status_code == 500

    def test_not_found(self, test_client):
        """测试 404 错误"""
        response = test_client.get("/api/v1/nonexistent")

        assert response.status_code == 404


class TestCORS:
    """CORS 测试"""

    def test_cors_headers(self, test_client):
        """测试 CORS 头"""
        response = test_client.options(
            "/api/v1/analyze",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "POST",
            }
        )

        # FastAPI 默认配置了 CORS
        assert response.status_code in [200, 204, 405]


class TestRequestValidation:
    """请求验证测试"""

    def test_valid_analyze_request(self, test_client, mock_orchestrator):
        """测试有效的分析请求"""
        mock_result = AnalysisResult(
            request_id="test-id",
            intent=Intent.STOCK_PRICE,
            mode=ResponseMode.SUMMARY,
            success=True,
        )
        mock_result.tools_called = ["get_stock_price"]
        mock_orchestrator.process.return_value = mock_result

        response = test_client.post(
            "/api/v1/analyze",
            json={
                "query": "AAPL 股价",
                "mode": "summary",
            }
        )

        assert response.status_code == 200

    def test_invalid_mode(self, test_client):
        """测试无效的响应模式"""
        response = test_client.post(
            "/api/v1/analyze",
            json={
                "query": "AAPL",
                "mode": "invalid_mode",
            }
        )

        assert response.status_code == 422

    def test_empty_query(self, test_client, mock_orchestrator):
        """测试空查询"""
        # 配置 mock 返回需要追问
        from finsight.domain.models import ClarifyQuestion
        mock_result = AnalysisResult(
            request_id="test-id",
            intent=Intent.UNCLEAR,
            mode=ResponseMode.SUMMARY,
            needs_clarification=True,
            clarify_question=ClarifyQuestion(
                question="请问您想查询什么？",
                field_name="query",
                reason="查询为空",
            ),
        )
        mock_orchestrator.process.return_value = mock_result

        response = test_client.post(
            "/api/v1/analyze",
            json={
                "query": "",
                "mode": "summary",
            }
        )

        # 空查询应该被验证拒绝或处理为需要追问
        assert response.status_code in [200, 422]

    def test_request_with_ticker(self, test_client, mock_orchestrator, mock_stock_price):
        """测试带有 ticker 的请求"""
        mock_result = AnalysisResult(
            request_id="test-id",
            intent=Intent.STOCK_PRICE,
            mode=ResponseMode.SUMMARY,
            success=True,
        )
        mock_result.stock_price = mock_stock_price
        mock_result.tools_called = ["get_stock_price"]
        mock_orchestrator.process.return_value = mock_result

        response = test_client.post(
            "/api/v1/analyze",
            json={
                "query": "股价多少",
                "mode": "summary",
                "ticker": "AAPL",
            }
        )

        assert response.status_code == 200

    def test_deep_mode_request(self, test_client, mock_orchestrator):
        """测试深度模式请求"""
        mock_result = AnalysisResult(
            request_id="test-id",
            intent=Intent.STOCK_ANALYSIS,
            mode=ResponseMode.DEEP,
            success=True,
            report="# 深度分析报告",
        )
        mock_result.tools_called = ["analyze_stock"]
        mock_orchestrator.process.return_value = mock_result

        response = test_client.post(
            "/api/v1/analyze",
            json={
                "query": "深度分析苹果",
                "mode": "deep",
            }
        )

        assert response.status_code == 200
