# P1-34 回归评估基线 (2026-01-22)

## 完成状态: DONE

## 交付物

| 项目 | 路径 | 说明 |
|------|------|------|
| 基准集 | `tests/regression/baselines/baseline_cases.json` | 25 条测试用例 |
| Mock 工具 | `tests/regression/mocks/mock_tools.py` | 固定数据源 |
| Mock LLM | `tests/regression/mocks/mock_llm.py` | 规则匹配响应 |
| 评估器 | `tests/regression/evaluators/` | Intent/Structure/Citation |
| 运行脚本 | `tests/regression/run_regression.py` | 一键运行 |
| 报告输出 | `tests/regression/reports/` | JSON + Markdown |

## 验收标准

| 标准 | 状态 | 说明 |
|------|------|------|
| 基准集 10-30 条 | PASS | 25 条用例 |
| 一键脚本 | PASS | `python tests/regression/run_regression.py` |
| 覆盖率/引用/耗时统计 | PASS | 报告含所有指标 |
| JSON/MD 对比报告 | PASS | 自动生成 |
| CI < 5 分钟 | PASS | 0.4s |
| Mock 固定数据源 | PASS | 不依赖外网 |

## 基线结果

```
通过率: 20% (5/25)
耗时: 0.4s
意图准确率: 20%
平均耗时: 14ms
P95 耗时: 1ms
```

## 说明

当前 20% 通过率是预期行为：
- Mock 环境下 LLM 分类被跳过
- 只用关键词匹配，大部分查询被识别为 `search`
- 这是基线值，后续优化意图分类后通过率应提升

## 用法

```bash
# 完整运行
python tests/regression/run_regression.py

# 指定输出目录
python tests/regression/run_regression.py --output reports/

# 只运行特定类别
python tests/regression/run_regression.py --category report
```

## 下一步

- P1-31: ReAct 搜索收敛 (依赖此基线)
- 优化意图分类后重新运行基线对比

---

## P1-31 ReAct 搜索收敛 (同日完成)

### 交付物
| 项目 | 路径 | 说明 |
|------|------|------|
| 收敛模块 | `backend/agents/search_convergence.py` | 信息增益+去重+停止条件 |
| 单元测试 | `backend/tests/test_search_convergence.py` | 11 个测试用例 |
| 集成 | `backend/agents/deep_search_agent.py` | 已集成到 research 方法 |

### 核心功能
- **信息增益评分**: 基于新增内容占比计算
- **内容级去重**: URL + 内容哈希 + 文本相似度
- **停止条件**: 连续 N 次增益 < 阈值 / 无新文档 / 达到最大轮次

### 测试结果
```
单元测试: 11/11 通过 (100%)
```

---

## P1-Trace 可观测性统一 (同日完成)

### 交付物
| 项目 | 路径 | 说明 |
|------|------|------|
| TraceEvent Schema v1 | `backend/orchestration/trace_schema.py` | 统一事件格式 |
| 单元测试 | `backend/tests/test_trace_schema.py` | 8 个测试用例 |
| 向后兼容 | `backend/orchestration/trace.py` | 重导出新 schema |
| 集成 | `backend/agents/deep_search_agent.py` | 使用 create_trace_event |

### Schema v1 字段
```python
@dataclass
class TraceEvent:
    schema_version: str = "v1"  # 版本标识
    event_type: str = ""        # 事件类型
    timestamp: str = ""         # ISO 时间戳
    duration_ms: Optional[int]  # 耗时(毫秒)
    agent: str = ""             # Agent 名称
    metadata: Dict[str, Any]    # 元数据
```

### 测试结果
```
单元测试: 8/8 通过 (100%)
```

---

## P2-FE 研报前端分析视图 (已存在)

### 现有功能
| 功能 | 组件 | 状态 |
|------|------|------|
| 置信度分解 | `ConfidenceMeter` + `section.confidence` | ✅ |
| 章节折叠 | `SectionRenderer` (isOpen/onToggle) | ✅ |
| 证据池 | `EvidencePool` 组件 | ✅ |
| 引用点击跳转 | `onCitationJump` | ✅ |
| 原文展开 | `EvidencePool` snippet + 高亮 | ✅ |

---

## P2-Dashboard 市场概览+Watchlist (已存在)

### 现有功能
| 功能 | 组件 | 状态 |
|------|------|------|
| 市场概览 (S&P/NASDAQ/DOW/Gold/BTC) | `MARKET_TICKERS` + `loadMarketQuotes` | ✅ |
| Watchlist 自选股 | `loadWatchlist` + `positionRows` | ✅ |
| 实时刷新 (60s) | `setInterval(refreshAll, 60000)` | ✅ |
| 资产组合快照 | `portfolioSummary` + `Widget` | ✅ |
| 消息中心/提醒 | `alerts` + `Widget` | ✅ |
| 图表展示 | `StockChart` 组件 | ✅ |
