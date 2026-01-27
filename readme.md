# FinSight: AI-Powered Intelligent Financial Analysis Platform

[English Version](./readme.md) | [中文版](./readme_cn.md) | [Examples](./example.md)

## 🎯 Project Overview

FinSight is an intelligent financial analysis platform built on **Clean/Hexagonal Architecture**. Powered by Large Language Models (LLMs) and integrated with multiple financial data sources, it provides a **RESTful API** and **Web frontend interface** that can autonomously understand user intent, collect data, and generate structured professional analysis reports.

### Core Features

- **🔍 Intelligent Intent Recognition**: Dual-engine intent parsing with LLM + rule-based fallback
- **📊 Multi-Source Data Integration**: yfinance real-time quotes, DuckDuckGo news search, CNN Fear & Greed Index
- **🏗️ Professional Architecture**: Clean/Hexagonal Architecture, SOLID principles, clear layered design
- **🌐 Web Interface**: Clean and professional frontend for analysis, with quick queries and history
- **📈 Dual Analysis Modes**: Summary mode (300-500 words) and Deep mode (800+ words)
- **⚡ Performance Optimized**: LRU caching, token bucket rate limiting, API cost tracking
- **🛡️ Security Protection**: Security headers middleware, input validation, XSS/SQL injection prevention
- **📝 Comprehensive Testing**: 150+ unit tests + integration tests covering all core modules

### Use Cases

- **Stock Analysis**: Price queries, technical analysis, in-depth research reports
- **Market Sentiment**: CNN Fear & Greed Index real-time monitoring
- **Asset Comparison**: Multi-asset return comparison analysis
- **Economic Calendar**: FOMC, CPI, and other key economic event tracking
- **News Aggregation**: Automatic stock-related news summary

---

## 🚀 Quick Start

### Prerequisites

- Python 3.10+
- Gemini API Key (or other LLM API key)
- Stable internet connection

### Installation

```bash
# 1. Clone the repository
git clone https://github.com/kkkano/FinSight-main.git
cd FinSight-main

# 2. Create virtual environment
python -m venv .venv

# Windows
.\.venv\Scripts\activate
# Linux/macOS
source .venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure environment variables
# Create a .env file in the root directory
echo 'GEMINI_PROXY_API_KEY="your_api_key"' > .env
```

### Launch Options

#### Option 1: Web API Service (Recommended)

```bash
# Start FastAPI service
python -m uvicorn finsight.api.main:app --host 0.0.0.0 --port 8000 --reload

# Access
# Web Interface: http://localhost:8000/
# API Docs:      http://localhost:8000/docs
# ReDoc:         http://localhost:8000/redoc
```

#### Option 2: Command Line Mode

```bash
python main.py
```

### API Usage Examples

```python
import requests

# Summary analysis
response = requests.post(
    "http://localhost:8000/api/v1/analyze",
    json={"query": "Analyze Apple stock", "mode": "summary"}
)
print(response.json()["report"])

# Deep analysis
response = requests.post(
    "http://localhost:8000/api/v1/analyze",
    json={"query": "Compare AAPL and MSFT investment value", "mode": "deep"}
)
print(response.json()["report"])
```

---

## 🏗️ System Architecture

### Hexagonal Architecture (Clean Architecture)

```
finsight/
├── domain/              # Domain Layer - Core business models
│   ├── models.py        #   Data models (StockPrice, NewsItem, etc.)
│   └── ports.py         #   Port interfaces (abstract dependencies)
│
├── adapters/            # Adapter Layer - External service integration
│   ├── yfinance_adapter.py  #   Yahoo Finance data
│   ├── search_adapter.py    #   DuckDuckGo search
│   ├── cnn_adapter.py       #   CNN sentiment index
│   └── llm_adapter.py       #   LLM calls
│
├── use_cases/           # Use Case Layer - Business logic
│   ├── get_stock_price.py
│   ├── analyze_stock.py
│   ├── get_market_sentiment.py
│   └── compare_assets.py
│
├── orchestrator/        # Orchestrator Layer - Flow control
│   ├── router.py        #   Intent routing
│   ├── orchestrator.py  #   Request orchestration
│   └── report_writer.py #   Report generation
│
├── api/                 # API Layer - HTTP interface
│   ├── main.py          #   FastAPI application entry
│   ├── routes/          #   Routes (analysis/health/metrics)
│   ├── schemas.py       #   Request/Response models
│   └── dependencies.py  #   Dependency injection
│
├── infrastructure/      # Infrastructure Layer
│   ├── logging.py       #   Structured logging
│   ├── metrics.py       #   Metrics collection
│   ├── errors.py        #   Error handling/retry
│   ├── cache.py         #   LRU cache
│   ├── rate_limiter.py  #   Rate limiter
│   ├── cost_tracker.py  #   Cost tracking
│   └── security.py      #   Security middleware
│
└── web/                 # Web Frontend
    ├── templates/       #   HTML pages
    └── static/          #   CSS/JS static assets
```

### Data Flow

```
User Request → FastAPI → Intent Recognition → Route Dispatch → Use Case Execution → Adapter Call → Data Aggregation → Report Generation → Response
```

### Core Design Principles

| Principle | Practice |
|-----------|----------|
| **SOLID** | Single responsibility, dependency inversion, interface segregation |
| **DRY** | Common adapter abstraction, shared infrastructure |
| **Ports & Adapters** | Domain layer has no external implementation dependencies |
| **Dependency Injection** | Unified management via ServiceContainer |

---

## 📊 API Endpoints

### Analysis

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/v1/analyze` | Intelligent analysis (main endpoint) |
| POST | `/api/v1/clarify` | Intent clarification |

### Health Checks

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Health status |
| GET | `/ready` | Readiness check |
| GET | `/live` | Liveness check |

### System Monitoring

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/v1/metrics/system` | System metrics |
| GET | `/api/v1/metrics/cache` | Cache statistics |
| GET | `/api/v1/metrics/rate-limits` | Rate limit statistics |
| GET | `/api/v1/metrics/costs` | Cost statistics |
| GET | `/api/v1/metrics/all` | All metrics |

---

## 🧪 Testing

```bash
# Run all unit tests
python -m pytest tests/unit -v

# Run integration tests
python -m pytest tests/integration -v

# Run specific module tests
python -m pytest tests/unit/test_models.py -v
python -m pytest tests/unit/test_orchestrator.py -v
python -m pytest tests/unit/test_infrastructure.py -v
python -m pytest tests/unit/test_performance.py -v
python -m pytest tests/unit/test_security.py -v
```

### Test Coverage

| Module | Tests | Description |
|--------|-------|-------------|
| Domain Models | 22 | Data models, enums, validation |
| Infrastructure | 33 | Logging, metrics, error handling |
| Orchestrator | 22 | Routing, use case orchestration |
| Performance | 30 | Cache, rate limiting, cost tracking |
| Security | 29 | Middleware, input validation |
| Integration | 21 | API endpoints, end-to-end |
| **Total** | **157+** | |

---

## ⚙️ Configuration

### Environment Variables

```env
# LLM API Key
GEMINI_PROXY_API_KEY="your_gemini_api_key"
OPENAI_API_KEY="your_openai_key"         # Optional

# Service Configuration
FINSIGHT_HOST="0.0.0.0"
FINSIGHT_PORT=8000
FINSIGHT_DEBUG=true

# LLM Settings
LLM_PROVIDER="gemini_proxy"
LLM_MODEL="gemini-2.5-flash-preview-05-20"
```

### LLM Model Switching

FinSight supports multiple models via LiteLLM:

```python
# Gemini (default)
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

## 📝 Changelog

### v2.0.0 (2026-01-28) - Architecture Refactoring
- ✅ Complete refactoring to Clean/Hexagonal Architecture
- ✅ New FastAPI RESTful API service
- ✅ New Web frontend interface (smart analysis, history, system monitoring)
- ✅ New intelligent intent recognition engine (LLM + rule-based dual engine)
- ✅ New LRU caching system (configurable strategy and TTL)
- ✅ New token bucket + sliding window rate limiter
- ✅ New API cost tracking and budget alerts
- ✅ New security headers middleware and input validation
- ✅ New structured logging and metrics collection system
- ✅ New error handling and automatic retry mechanism
- ✅ New 157+ unit tests and integration tests
- ✅ Complete API documentation (Swagger/ReDoc)

### v1.2.0 (2025-10-19)
- ✅ Fixed CNN Fear & Greed Index scraping
- ✅ Optimized economic event search

### v1.0.0 (2025-10-01)
- ✅ Basic ReAct framework with 9 core tools

---

## ⚠️ Disclaimer

> FinSight provides analysis for reference only and **does not constitute investment advice**. All investment decisions should be made in consultation with a professional financial advisor. Past performance does not guarantee future returns. The author is not responsible for any losses arising from the use of this tool.
