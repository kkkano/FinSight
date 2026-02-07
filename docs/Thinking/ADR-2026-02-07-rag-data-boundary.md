# ADR-2026-02-07｜RAG 数据边界与研报库策略

> **状态**: Accepted  
> **日期**: 2026-02-07  
> **SSOT 对齐**: `docs/05_RAG_ARCHITECTURE.md`、`docs/06_LANGGRAPH_REFACTOR_GUIDE.md`（11.10 / 11.11 / 11.12）

---

## 1. 背景

RAG 常见误区是把“所有文本（包括模型生成内容）都入库”，导致：

1. 检索污染（陈旧新闻、二次加工内容反复召回）。
2. 幻觉放大（模型生成文本再被当作事实检索）。
3. 成本和运维复杂度失控。

---

## 2. 决策

1. **主库只存原始证据文本**：财报、公告、电话会、研究原文。
2. **生成研报正文默认不入主库**：仅作为会话产物。
3. **实时新闻默认短期策略**：保存摘要+元数据，TTL 7~30 天。
4. **DeepSearch 长文抓取走临时库**：会话级 ephemeral collection。
5. 检索采用混合策略：Dense + Sparse + RRF。

---

## 3. 实现落点

- RAG 服务：`backend/rag/hybrid_service.py`
- 执行层接入：`backend/graph/nodes/execute_plan_stub.py`
- 综合层消费：`backend/graph/nodes/synthesize.py`
- 文档定义：`docs/05_RAG_ARCHITECTURE.md`

---

## 4. 后果

### 正向

- 检索结果更稳定、可追溯。
- 避免“生成内容循环污染”。
- 实时与历史场景分治清晰。

### 代价

- 需要额外维护 TTL 与清理机制。
- 需要持续扩充评测集验证边界策略。

