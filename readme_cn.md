# FinSight: AI 驱动的智能金融分析平台

[English Version](./readme.md) | [中文版](./readme_cn.md) | [示例](./example.md)

## 🎯 项目概览

FinSight 是一个基于 **Clean/Hexagonal Architecture**（六边形架构）构建的智能金融分析平台。它由大语言模型（LLM）驱动，集成多个金融数据源，提供 **RESTful API** 和 **Web 前端界面**，能够自主理解用户意图、收集数据并生成结构化的专业分析报告。

### 核心特性

- **🔍 智能意图识别**：LLM + 规则引擎双重意图解析，准确理解用户查询
- **📊 多源数据集成**：yfinance 实时行情、DuckDuckGo 新闻搜索、CNN Fear & Greed Index
- **🏗️ 专业架构**：Clean/Hexagonal Architecture，SOLID 原则，清晰的分层设计
- **🌐 Web 界面**：简洁专业的前端分析界面，支持快捷查询与历史记录
- **📈 双模式分析**：摘要模式（300-500字）和深度模式（800+字）
- **⚡ 性能优化**：LRU 缓存、令牌桶限流、API 成本追踪
- **🛡️ 安全防护**：安全头中间件、输入验证、XSS/SQL 注入防护
- **📝 完整测试**：150+ 单元测试 + 集成测试，覆盖所有核心模块

### 使用场景

- **股票分析**：价格查询、技术分析、深度研究报告
- **市场情绪**：CNN 恐慌与贪婪指数实时监测
- **资产对比**：多资产收益率对比分析
- **经济日历**：FOMC、CPI 等重要经济事件追踪
- **新闻聚合**：个股相关新闻自动汇总

---

## 🚀 快速开始

### 前置要求

- Python 3.10+
- Gemini API Key（或其他 LLM API Key）
- 稳定的网络连接

### 安装步骤

```bash
# 1. 克隆仓库
git clone https://github.com/kkkano/FinSight-main.git
cd FinSight-main

# 2. 创建虚拟环境
python -m venv .venv

# Windows
.\.venv\Scripts\activate
# Linux/macOS
source .venv/bin/activate

# 3. 安装依赖
pip install -r requirements.txt

# 4. 配置环境变量
# 在根目录创建 .env 文件
echo 'GEMINI_PROXY_API_KEY="your_api_key"' > .env
```

### 启动方式

#### 方式一：Web API 服务（推荐）

```bash
# 启动 FastAPI 服务
python -m uvicorn finsight.api.main:app --host 0.0.0.0 --port 8000 --reload

# 访问
# Web 界面：http://localhost:8000/
# API 文档：http://localhost:8000/docs
# ReDoc：  http://localhost:8000/redoc
```

#### 方式二：命令行模式

```bash
python main.py
```

### API 使用示例

```python
import requests

# 摘要分析
response = requests.post(
    "http://localhost:8000/api/v1/analyze",
    json={"query": "分析苹果股票", "mode": "summary"}
)
print(response.json()["report"])

# 深度分析
response = requests.post(
    "http://localhost:8000/api/v1/analyze",
    json={"query": "比较 AAPL 和 MSFT 的投资价值", "mode": "deep"}
)
print(response.json()["report"])
```

---

## 🏗️ 系统架构

### 六边形架构（Clean Architecture）

```
finsight/
├── domain/              # 领域层 - 核心业务模型
│   ├── models.py        #   数据模型（StockPrice, NewsItem, etc.）
│   └── ports.py         #   端口接口（抽象依赖）
│
├── adapters/            # 适配器层 - 外部服务集成
│   ├── yfinance_adapter.py  #   Yahoo Finance 数据
│   ├── search_adapter.py    #   DuckDuckGo 搜索
│   ├── cnn_adapter.py       #   CNN 情绪指数
│   └── llm_adapter.py       #   LLM 调用
│
├── use_cases/           # 用例层 - 业务逻辑
│   ├── get_stock_price.py
│   ├── analyze_stock.py
│   ├── get_market_sentiment.py
│   └── compare_assets.py
│
├── orchestrator/        # 编排层 - 流程控制
│   ├── router.py        #   意图路由
│   ├── orchestrator.py  #   请求编排
│   └── report_writer.py #   报告生成
│
├── api/                 # API 层 - HTTP 接口
│   ├── main.py          #   FastAPI 应用入口
│   ├── routes/          #   路由（分析/健康/监控）
│   ├── schemas.py       #   请求/响应模型
│   └── dependencies.py  #   依赖注入
│
├── infrastructure/      # 基础设施层
│   ├── logging.py       #   结构化日志
│   ├── metrics.py       #   指标收集
│   ├── errors.py        #   错误处理/重试
│   ├── cache.py         #   LRU 缓存
│   ├── rate_limiter.py  #   限流器
│   ├── cost_tracker.py  #   成本追踪
│   └── security.py      #   安全中间件
│
└── web/                 # Web 前端
    ├── templates/       #   HTML 页面
    └── static/          #   CSS/JS 静态资源
```

### 数据流

```
用户请求 → FastAPI → 意图识别 → 路由分发 → 用例执行 → 适配器调用 → 数据聚合 → 报告生成 → 响应
```

### 核心设计原则

| 原则 | 实践 |
|------|------|
| **SOLID** | 单一职责、依赖倒置、接口隔离 |
| **DRY** | 通用适配器抽象、共享基础设施 |
| **端口-适配器** | 领域层不依赖外部实现 |
| **依赖注入** | ServiceContainer 统一管理 |

---

## 📊 API 端点

### 分析接口

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/v1/analyze` | 智能分析（主接口） |
| POST | `/api/v1/clarify` | 意图澄清 |

### 健康检查

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/health` | 健康状态 |
| GET | `/ready` | 就绪检查 |
| GET | `/live` | 存活检查 |

### 系统监控

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/v1/metrics/system` | 系统指标 |
| GET | `/api/v1/metrics/cache` | 缓存统计 |
| GET | `/api/v1/metrics/rate-limits` | 限流统计 |
| GET | `/api/v1/metrics/costs` | 成本统计 |
| GET | `/api/v1/metrics/all` | 全部指标 |

---

## 🧪 测试

```bash
# 运行全部单元测试
python -m pytest tests/unit -v

# 运行集成测试
python -m pytest tests/integration -v

# 运行特定模块测试
python -m pytest tests/unit/test_models.py -v
python -m pytest tests/unit/test_orchestrator.py -v
python -m pytest tests/unit/test_infrastructure.py -v
python -m pytest tests/unit/test_performance.py -v
python -m pytest tests/unit/test_security.py -v
```

### 测试覆盖

| 模块 | 测试数 | 说明 |
|------|--------|------|
| 领域模型 | 22 | 数据模型、枚举、验证 |
| 基础设施 | 33 | 日志、指标、错误处理 |
| 编排器 | 22 | 路由、用例编排 |
| 性能 | 30 | 缓存、限流、成本 |
| 安全 | 29 | 中间件、输入验证 |
| 集成 | 21 | API 端点、端到端 |
| **总计** | **157+** | |

---

## ⚙️ 配置

### 环境变量

```env
# LLM API 密钥
GEMINI_PROXY_API_KEY="your_gemini_api_key"
OPENAI_API_KEY="your_openai_key"         # 可选

# 服务配置
FINSIGHT_HOST="0.0.0.0"
FINSIGHT_PORT=8000
FINSIGHT_DEBUG=true

# LLM 设置
LLM_PROVIDER="gemini_proxy"
LLM_MODEL="gemini-2.5-flash-preview-05-20"
```

### LLM 模型切换

FinSight 通过 LiteLLM 支持多种模型：

```python
# Gemini（默认）
LLM_PROVIDER="gemini_proxy"
LLM_MODEL="gemini-2.5-flash-preview-05-20"

# OpenAI
LLM_PROVIDER="openai"
LLM_MODEL="gpt-4"

# Claude
LLM_PROVIDER="anthropic"
LLM_MODEL="claude-3-opus-20240229"
```

---

## 📝 更新日志

### v2.0.0 (2026-01-28) - 架构重构
- ✅ 全面重构为 Clean/Hexagonal Architecture
- ✅ 新增 FastAPI RESTful API 服务
- ✅ 新增 Web 前端界面（智能分析、历史记录、系统监控）
- ✅ 新增智能意图识别引擎（LLM + 规则双引擎）
- ✅ 新增 LRU 缓存系统（可配置策略和 TTL）
- ✅ 新增令牌桶 + 滑动窗口限流器
- ✅ 新增 API 成本追踪与预算告警
- ✅ 新增安全头中间件和输入验证
- ✅ 新增结构化日志和指标收集系统
- ✅ 新增错误处理和自动重试机制
- ✅ 新增 157+ 单元测试和集成测试
- ✅ 完整的 API 文档（Swagger/ReDoc）

### v1.2.0 (2025-10-19)
- ✅ 修复 CNN Fear & Greed Index 抓取
- ✅ 优化经济事件搜索

### v1.0.0 (2025-10-01)
- ✅ 基础 ReAct 框架和 9 个核心工具

---

## ⚠️ 免责声明

> FinSight 提供的分析仅供参考，**不构成投资建议**。所有投资决策应咨询专业财务顾问。历史表现不代表未来收益。作者不对使用本工具产生的任何损失负责。
