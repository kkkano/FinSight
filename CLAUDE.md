# CLAUDE.md

此文件为 Claude Code (claude.ai/code) 在此代码库中工作时提供指导。

## 项目概述

FinSight 是一个 AI 驱动的股票分析代理，使用 ReAct (推理和行动) 框架来提供全面的金融分析。系统能够自主从多个来源收集实时数据，并生成详细的专业投资报告。

## 开发命令

### 环境设置
```bash
# 创建并激活虚拟环境 (Windows)
python -m venv .venv && .\.venv\Scripts\activate

# 安装依赖
pip install -r requirements.txt
# 备选方案（国内镜像）：
pip install -r requirements.txt -i https://mirrors.aliyun.com/pypi/simple/
```

### 运行应用
```bash
# 交互模式
python main.py

# 单次查询执行
python main.py "分析 AAPL 股票"
```

### 测试
```bash
# 运行现有测试
python test/testsentiment.py
python tests.py
python test.py
```

## 架构概览

### 核心组件
- **`agent.py`**: 实现具有"思考-行动-观察"循环的 ReAct 框架
- **`tools.py`**: 包含具有级联回退策略的多源数据采集工具
- **`llm_service.py`**: LiteLLM 封装，支持灵活的 LLM 提供商集成
- **`config.py`**: 多个 LLM 提供商的集中配置
- **`main.py`**: 命令行界面，支持交互式和批处理模式

### 数据获取策略
系统实现复杂的多源数据策略：
1. **主要 API**: Alpha Vantage (稳定，每天 500 次请求)
2. **次要 API**: Finnhub (每分钟 60 次请求)
3. **免费 API**: yfinance (容易达到请求限制)
4. **网页抓取**: 直接解析雅虎财经
5. **搜索引擎**: DuckDuckGo 作为最终备选

### 智能代码路由
- **公司股票** (如 AAPL, TSLA): 使用金融 API 获取实时数据
- **市场指数** (如 ^IXIC, ^GSPC): 使用基于搜索的策略
- 根据代码模式自动检测并适当路由

## 关键配置文件

### 环境变量 (`.env`)
API 访问所需：
```env
# LLM 配置
GEMINI_PROXY_API_KEY=你的 Gemini API 密钥
GEMINI_PROXY_API_BASE=https://你的代理地址/v1

# 金融数据 API (可选但推荐)
ALPHA_VANTAGE_API_KEY=你的 Alpha Vantage 密钥
FINNHUB_API_KEY=你的 Finnhub 密钥
```

### LLM 提供商配置 (`config.py`)
支持多个提供商：
- Gemini 代理 (默认)
- OpenAI
- AnyScale (Llama 模型)
- Anthropic

## 工具系统设计

### 可用工具
- `get_stock_price`: 具有多源备选的实时定价
- `get_company_info`: 公司简介和财务数据
- `get_company_news`: 最新新闻，支持指数智能路由
- `get_market_sentiment`: CNN 恐惧贪婪指数
- `get_economic_events`: 即将到来的经济事件
- `get_performance_comparison`: 多股票分析
- `analyze_historical_drawdowns`: 历史最大回撤分析，包含恢复追踪
- `search`: DuckDuckGo 网络搜索
- `get_current_datetime`: 分析上下文的时间戳

### 错误处理
- 指数退避重试机制
- 数据源间的优雅降级
- 用于故障排除的详细日志
- 提供可操作指导的用户友好错误消息

## 开发注意事项

### 报告生成
代理生成遵循严格结构的详细 800+ 字报告：
1. 执行摘要与明确建议
2. 当前市场状况和表现指标
3. 宏观环境和催化剂
4. 技术和情绪分析
5. 包含历史回撤的风险评估
6. 包含进出场点的投资策略
7. 牛/熊/基准情景分析
8. 关键监控事件

### 关键开发模式
- 所有 API 密钥通过环境变量管理
- 工具实现级联回退以获得最大可靠性
- 代理遵循结构化的两阶段工作流程（数据收集 → 报告生成）
- 具有重试逻辑的全面错误处理
- 确保报告使用当前数据的日期感知分析

### 重要限制
- 分析依赖公共 API，可能有请求限制
- 无实时交易能力
- 免费来源的数据可能有轻微延迟
- 报告仅供参考，不构成财务建议