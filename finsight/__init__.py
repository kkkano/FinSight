"""
FinSight - AI 驱动的金融分析智能助手

基于 Clean/Hex 六边形架构构建，提供：
- 股票分析
- 市场情绪分析
- 资产对比
- 宏观经济事件追踪

架构层次：
- domain: 核心领域模型
- ports: 端口接口定义
- adapters: 外部服务适配器
- use_cases: 业务用例
- orchestrator: 请求编排与路由
- presentation: 报告生成
- infrastructure: 基础设施（日志、缓存、配置）
- api: FastAPI 路由

快速开始：
```python
from finsight import create_app

# 创建 FastAPI 应用
app = create_app()

# 或者使用编排器直接调用
from finsight.orchestrator import create_orchestrator
from finsight.domain.models import AnalysisRequest
```
"""

__version__ = "2.0.0"
__author__ = "FinSight Team"

# 核心领域模型
from finsight.domain.models import (
    AnalysisRequest,
    AnalysisResult,
    Intent,
    ResponseMode,
    StockPrice,
    CompanyInfo,
    NewsItem,
    MarketSentiment,
)

# 编排器
from finsight.orchestrator import (
    Orchestrator,
    Router,
    create_orchestrator,
)

# 报告生成
from finsight.presentation import (
    ReportWriter,
    ReportFormat,
    create_report_writer,
)

# API 应用
from finsight.api import app, create_app

__all__ = [
    # 版本信息
    "__version__",
    "__author__",
    # 领域模型
    "AnalysisRequest",
    "AnalysisResult",
    "Intent",
    "ResponseMode",
    "StockPrice",
    "CompanyInfo",
    "NewsItem",
    "MarketSentiment",
    # 编排器
    "Orchestrator",
    "Router",
    "create_orchestrator",
    # 报告
    "ReportWriter",
    "ReportFormat",
    "create_report_writer",
    # API
    "app",
    "create_app",
]
