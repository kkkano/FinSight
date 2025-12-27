# Tavily Search 集成文档

## 概述

已成功集成 **Tavily Search**，这是一个专门为 AI 应用设计的搜索 API，提供更准确、结构化的搜索结果。

## 功能特点

1. **AI 生成的答案摘要**：Tavily 会自动生成查询的 AI 摘要，提供更精准的答案
2. **结构化数据**：返回结构化的搜索结果，包含相关性评分
3. **多数据源回退**：优先使用 Tavily，失败时自动回退到 DuckDuckGo
4. **LangChain 集成**：支持 LangChain 的 Tavily 工具

## 配置

### 1. 获取 API Key

访问 [Tavily 官网](https://tavily.com) 注册并获取 API Key。

### 2. 配置环境变量

在 `.env` 文件中添加：

```env
TAVILY_API_KEY=your_api_key_here
```

### 3. 安装依赖

依赖已添加到 `requirements.txt`：

```txt
tavily-python==0.3.0
langchain-tavily==0.1.0
```

安装命令：

```bash
pip install tavily-python langchain-tavily
```

## 使用方法

### 在 `backend/tools.py` 中使用

`search()` 函数已自动集成 Tavily Search：

```python
from backend.tools import search

# 自动使用 Tavily（如果配置了 API Key），否则回退到 DuckDuckGo
result = search("纳斯达克指数最新动态")
print(result)
```

### 在 LangChain Agent 中使用

`langchain_tools.py` 中的 `search` 工具已更新，支持 Tavily：

```python
from langchain_tools import FINANCIAL_TOOLS

# search 工具已包含在 FINANCIAL_TOOLS 中
# Agent 会自动使用 Tavily（如果配置了 API Key）
```

## 搜索结果格式

### Tavily 搜索结果示例：

```
📊 AI摘要:
As of today, the Nasdaq Composite Index is at 23,214.69, up 0.82%...

搜索结果:
1. 标题 (相关性: 0.95)
   内容摘要...
   https://example.com
```

### DuckDuckGo 回退结果示例：

```
Search Results (DuckDuckGo):
1. 标题
   内容摘要...
   https://example.com
```

## 测试

运行测试脚本验证集成：

```bash
python test_tavily_search.py
```

测试结果：
- ✅ Tavily API Key 配置检查
- ✅ 模块导入测试
- ✅ 搜索功能测试（多个查询）

## 优势对比

| 特性 | Tavily Search | DuckDuckGo |
|------|--------------|------------|
| AI 摘要 | ✅ 自动生成 | ❌ 无 |
| 相关性评分 | ✅ 有 | ❌ 无 |
| 结构化数据 | ✅ 是 | ⚠️ 部分 |
| 免费额度 | 1000次/月 | 无限制 |
| 准确性 | 高 | 中等 |

## 注意事项

1. **API 限制**：Tavily 免费版每月 1000 次请求
2. **自动回退**：如果 Tavily 不可用或失败，会自动使用 DuckDuckGo
3. **API Key 配置**：如果没有配置 `TAVILY_API_KEY`，系统会自动使用 DuckDuckGo

## 代码位置

- **实现**：`backend/tools.py` - `search()` 和 `_search_with_tavily()` 函数
- **LangChain 工具**：`langchain_tools.py` - `search` 工具定义
- **测试**：`test_tavily_search.py` - 集成测试脚本

## 更新日期

2025-11-30

