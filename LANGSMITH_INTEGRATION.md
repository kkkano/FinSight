# LangSmith 集成文档

## 📋 概述

本次更新为 FinSight 添加了 **LangSmith 可观测性集成**，实现运行追踪、事件记录和性能监控功能。

---

## 🆕 新增/修改的文件

| 文件 | 类型 | 说明 |
|------|------|------|
| `langsmith_integration.py` | 🆕 新增 | 核心集成模块，提供追踪 API |
| `test_langsmith_integration.py` | 🆕 新增 | 单元测试和快速测试 |
| `config.py` | ✏️ 修改 | 添加 LangSmith 配置项 |
| `requirements.txt` | ✏️ 修改 | 添加 langsmith 依赖 |
| `streaming_support.py` | ✏️ 修改 | 集成 LangSmith 追踪到回调 |
| `main.py` | ✏️ 修改 | 启动时初始化 LangSmith |
| `LANGSMITH_INTEGRATION.md` | 🆕 新增 | 本文档 |

---

## 🔧 配置方法

### 1. 环境变量配置

在 `.env` 文件中添加：

```env
# LangSmith 配置（可选）
LANGSMITH_API_KEY=your_api_key_here
LANGSMITH_PROJECT=FinSight
LANGSMITH_ENDPOINT=https://api.smith.langchain.com
ENABLE_LANGSMITH=true
```

### 2. 获取 API Key

1. 访问 [LangSmith](https://smith.langchain.com/)
2. 注册/登录账户
3. 在 Settings → API Keys 中创建新密钥
4. 将密钥添加到 `.env` 文件

### 3. 安装依赖

```bash
pip install langsmith
# 或
pip install -r requirements.txt
```

---

## 📊 功能说明

### 核心功能

1. **运行追踪** - 自动记录每次分析的开始、结束、耗时
2. **事件记录** - 记录工具调用、LLM 推理等事件
3. **错误追踪** - 捕获并记录分析过程中的错误
4. **异步上报** - 不阻塞主分析流程

### API 接口

```python
from langsmith_integration import (
    init_langsmith,     # 初始化客户端
    start_run,          # 开始追踪
    log_event,          # 记录事件
    finish_run,         # 完成追踪
    is_enabled,         # 检查是否启用
    trace_analysis,     # 装饰器
)
```

### 使用示例

#### 基础使用（自动集成）

只需配置环境变量，FinSight 会自动追踪所有分析：

```bash
# 设置环境变量
export ENABLE_LANGSMITH=true
export LANGSMITH_API_KEY=your_key

# 运行分析
python main.py "分析 AAPL 股票"
```

#### 手动使用

```python
from langsmith_integration import start_run, log_event, finish_run

# 开始追踪
run = start_run(
    name="自定义分析",
    query="分析苹果股票",
    metadata={"user": "test"}
)

# 记录事件
log_event(run, "custom_event", {"data": "value"})

# 完成追踪
summary = finish_run(run, status="success", outputs={"result": "..."})
```

#### 使用装饰器

```python
from langsmith_integration import trace_analysis

@trace_analysis("我的分析")
def my_analysis(query: str) -> str:
    # 分析逻辑
    return "分析结果"

result = my_analysis("NVDA")  # 自动追踪
```

---

## 🏗️ 架构说明

### 数据流

```
用户查询
    ↓
main.py (初始化 LangSmith)
    ↓
streaming_support.py (回调触发追踪)
    ↓
langsmith_integration.py (异步上报)
    ↓
LangSmith Cloud (存储和可视化)
```

### 回调集成点

| 回调方法 | 追踪动作 |
|---------|---------|
| `on_chain_start` | 创建运行，记录查询 |
| `on_tool_start` | 记录工具开始事件 |
| `on_tool_end` | 记录工具结束事件 |
| `on_llm_start` | 记录 LLM 推理开始 |
| `on_chain_end` | 完成运行，统计指标 |
| `on_chain_error` | 记录错误并完成运行 |

### 关键设计

1. **可选依赖** - LangSmith 未安装时自动降级，不影响核心功能
2. **异步上报** - 使用线程池，不阻塞分析流程
3. **静默失败** - 上报错误不会抛出异常，不影响用户体验
4. **环境变量控制** - 通过 `ENABLE_LANGSMITH` 控制启用/禁用

---

## 🧪 测试

### 运行快速测试

```bash
python test_langsmith_integration.py --quick
```

### 运行完整单元测试

```bash
python test_langsmith_integration.py --full
```

### 测试覆盖

- ✅ RunContext 数据结构
- ✅ 运行追踪生命周期
- ✅ 事件记录
- ✅ 错误处理
- ✅ 装饰器
- ✅ 回调混入类
- ✅ 与 streaming_support 集成

---

## 📈 在 LangSmith 中查看

启用追踪后，可以在 LangSmith Web UI 中：

1. **查看运行列表** - 按时间、状态筛选
2. **运行详情** - 查看输入、输出、工具调用链
3. **性能分析** - 耗时分布、工具使用统计
4. **错误追踪** - 快速定位失败的运行

---

## ⚠️ 注意事项

### 隐私与合规

- 运行数据（用户查询、工具输出）会上传到 LangSmith 云端
- 如有敏感数据，建议：
  - 在上报前脱敏处理
  - 使用 LangSmith 的自托管方案
  - 或保持 `ENABLE_LANGSMITH=false`

### 成本

- LangSmith 可能按运行量收费
- 建议在开发/测试环境启用，生产环境按需启用
- 查看 [LangSmith 定价](https://www.langchain.com/langsmith)

### 性能影响

- 异步上报，对主流程无阻塞
- 线程池最多 2 个工作线程
- 上报失败静默处理，不影响分析

---

## 🔄 回滚方法

如需禁用 LangSmith 集成：

```bash
# 方法 1: 设置环境变量
export ENABLE_LANGSMITH=false

# 方法 2: 删除 API Key
unset LANGSMITH_API_KEY
```

代码无需修改，集成会自动降级。

---

## 📚 参考

- [LangSmith 官方文档](https://docs.smith.langchain.com/)
- [LangChain Tracing](https://python.langchain.com/docs/langsmith/)
- [LangSmith Python SDK](https://github.com/langchain-ai/langsmith-sdk)

---

## 📝 更新日志

| 日期 | 版本 | 说明 |
|------|------|------|
| 2025-11-29 | 1.0.0 | 初始集成 |

---

*由 GitHub Copilot 生成*
