"""
依赖注入 - FastAPI 依赖配置

集中管理所有服务的创建和注入，
确保单一实例和正确的生命周期管理。
"""

from functools import lru_cache
from typing import Optional
import os

from finsight.adapters.yfinance_adapter import YFinanceAdapter
from finsight.adapters.ddgs_adapter import DDGSAdapter
from finsight.adapters.cnn_adapter import CNNSentimentAdapter
from finsight.adapters.system_time_adapter import SystemTimeAdapter
from finsight.adapters.llm_adapter import LiteLLMAdapter
from finsight.orchestrator import Orchestrator, create_orchestrator
from finsight.presentation import ReportWriter, create_report_writer


class ServiceContainer:
    """
    服务容器 - 管理所有服务实例

    采用单例模式确保服务实例的复用
    """

    _instance: Optional['ServiceContainer'] = None
    _initialized: bool = False

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if self._initialized:
            return

        # 初始化适配器
        self._market_data = YFinanceAdapter()
        self._news = self._market_data  # YFinanceAdapter 同时实现 NewsPort
        self._sentiment = CNNSentimentAdapter()
        self._search = DDGSAdapter()
        self._time = SystemTimeAdapter()

        # LLM 适配器（可选）
        self._llm: Optional[LiteLLMAdapter] = None
        self._init_llm()

        # 初始化编排器
        self._orchestrator = create_orchestrator(
            market_data_port=self._market_data,
            news_port=self._news,
            sentiment_port=self._sentiment,
            search_port=self._search,
            time_port=self._time,
            llm_port=self._llm,
        )

        # 初始化报告生成器
        self._report_writer = create_report_writer()

        self._initialized = True

    def _init_llm(self):
        """初始化 LLM 适配器"""
        # 从环境变量获取配置
        provider = os.getenv('LLM_PROVIDER', 'gemini_proxy')
        model = os.getenv('LLM_MODEL', 'gemini-2.5-flash-preview-05-20')
        api_key = os.getenv('GEMINI_API_KEY') or os.getenv('OPENAI_API_KEY')

        if api_key:
            try:
                self._llm = LiteLLMAdapter(
                    provider=provider,
                    model=model,
                )
            except Exception:
                # LLM 初始化失败，使用规则兜底
                self._llm = None

    @property
    def orchestrator(self) -> Orchestrator:
        """获取编排器实例"""
        return self._orchestrator

    @property
    def report_writer(self) -> ReportWriter:
        """获取报告生成器实例"""
        return self._report_writer

    @property
    def time_adapter(self) -> SystemTimeAdapter:
        """获取时间适配器"""
        return self._time


@lru_cache()
def get_service_container() -> ServiceContainer:
    """
    获取服务容器单例

    使用 lru_cache 确保只创建一次
    """
    return ServiceContainer()


def get_orchestrator() -> Orchestrator:
    """FastAPI 依赖：获取编排器"""
    container = get_service_container()
    return container.orchestrator


def get_report_writer() -> ReportWriter:
    """FastAPI 依赖：获取报告生成器"""
    container = get_service_container()
    return container.report_writer


def get_time_service() -> SystemTimeAdapter:
    """FastAPI 依赖：获取时间服务"""
    container = get_service_container()
    return container.time_adapter


# 配置类
class Settings:
    """应用配置"""

    # 基本配置
    APP_NAME: str = "FinSight API"
    APP_VERSION: str = "2.0.0"
    DEBUG: bool = os.getenv('DEBUG', 'false').lower() == 'true'

    # 服务配置
    HOST: str = os.getenv('HOST', '0.0.0.0')
    PORT: int = int(os.getenv('PORT', '8000'))

    # CORS 配置
    CORS_ORIGINS: list = os.getenv('CORS_ORIGINS', '*').split(',')

    # 速率限制
    RATE_LIMIT_PER_MINUTE: int = int(os.getenv('RATE_LIMIT', '60'))

    # LLM 配置
    LLM_PROVIDER: str = os.getenv('LLM_PROVIDER', 'gemini_proxy')
    LLM_MODEL: str = os.getenv('LLM_MODEL', 'gemini-2.5-flash-preview-05-20')

    # 超时配置（秒）
    REQUEST_TIMEOUT: int = int(os.getenv('REQUEST_TIMEOUT', '30'))


@lru_cache()
def get_settings() -> Settings:
    """获取应用配置"""
    return Settings()
