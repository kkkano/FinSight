# Hallucination Mitigation — LLM 幻觉抑制体系

> **FinSight AI** 的多层防御策略，确保生成内容基于真实证据而非 LLM 编造。

---

## 目录

- [1. 问题定义](#1-问题定义)
- [2. 六层防御架构](#2-六层防御架构)
- [3. 第一层：Agent 证据约束](#3-第一层agent-证据约束)
- [4. 第二层：Evidence Pool 溯源链](#4-第二层evidence-pool-溯源链)
- [5. 第三层：Prompt 约束指令](#5-第三层prompt-约束指令)
- [6. 第四层：未验证事件声明洗涤器](#6-第四层未验证事件声明洗涤器)
- [7. 第五层：Protected Keys 数据保护](#7-第五层protected-keys-数据保护)
- [8. 第六层：冲突检测与置信度惩罚](#8-第六层冲突检测与置信度惩罚)
- [9. 测试覆盖](#9-测试覆盖)
- [10. 运行时监控](#10-运行时监控)
- [11. 局限性与未来方向](#11-局限性与未来方向)

---

## 1. 问题定义

金融研究领域的 LLM 幻觉尤其危险：

| 幻觉类型 | 示例 | 危害 |
|----------|------|------|
| **事件编造** | "预计 2026Q2 发布 Gemini 2.0" | 用户基于虚假事件做出投资决策 |
| **数据伪造** | 编造 PE 比率、EPS 数字 | 导致错误的估值判断 |
| **因果虚构** | 捏造并购传闻与股价关系 | 产生不存在的市场信号 |
| **时间错位** | 将历史事件说成未来计划 | 混淆事件时间线 |

FinSight 通过 **六层纵深防御** 系统性抑制上述幻觉。

---

## 2. 六层防御架构

```
┌─────────────────────────────────────────────────────────┐
│ Layer 6: Conflict Detection + Confidence Penalty        │
│   synthesize.py:498-539 — 8 组 Agent 交叉验证           │
├─────────────────────────────────────────────────────────┤
│ Layer 5: Protected Keys — 数据段强制使用 API 真实值      │
│   synthesize.py:1869 — news/price/tech 不让 LLM 重写    │
├─────────────────────────────────────────────────────────┤
│ Layer 4: Unverified Claim Scrubber — 正则 + 证据交叉     │
│   synthesize.py:205-281 — 模式匹配 + token 命中检验      │
├─────────────────────────────────────────────────────────┤
│ Layer 3: Prompt Constraints — system prompt 明确禁令     │
│   synthesize.py system prompt — "不得编造未证实事件"      │
├─────────────────────────────────────────────────────────┤
│ Layer 2: Evidence Pool — 全程溯源 citation-first        │
│   GraphState.evidence_pool — 每条证据带 source + ts     │
├─────────────────────────────────────────────────────────┤
│ Layer 1: Agent Evidence Constraint — 工具优先于推理      │
│   BaseFinancialAgent — 只用工具获取的数据，不凭空推理    │
└─────────────────────────────────────────────────────────┘
```

---

## 3. 第一层：Agent 证据约束

**原则**：每个 Agent 的分析必须基于工具调用返回的数据，而非 LLM 自行推理。

### 实现机制

- 7 个 Research Agent 均继承 `BaseFinancialAgent`，其 `research()` 方法强制执行 **search → reflect → output** 循环
- Agent 输出的 `AgentOutput` 包含 `evidence_pieces: list[EvidencePiece]`，每条 evidence 带有：
  - `source`: 数据来源（API 名称、URL）
  - `confidence`: 0.0–1.0 置信度
  - `timestamp`: 获取时间
- Agent 的 LLM 调用（`reflect` 阶段）接收的上下文**仅包含工具返回的结构化数据**，不包含先验知识

### 关键文件

| 文件 | 作用 |
|------|------|
| `backend/agents/base_agent.py` | Agent 基类，强制 search→reflect→output 流程 |
| `backend/graph/state.py` | `GraphState.evidence_pool` 定义 |
| `backend/tools/manifest.py` | 17 个注册工具，每个有 `risk_level` 和 `cache_ttl` |

---

## 4. 第二层：Evidence Pool 溯源链

**原则**：所有进入 synthesize 阶段的数据必须可追溯到具体来源。

### 数据流

```
Tool 调用 → EvidencePiece(source, confidence, ts) → evidence_pool[]
                                                         │
                                                         ↓
                                              synthesize.py 构建 grounding text
                                                         │
                                                         ↓
                                              LLM prompt 中的 <realtime_evidence> / <historical_knowledge>
```

### XML 标签分离（E1 引入）

synthesize.py 的 prompt 中，实时数据和 RAG 历史知识使用 XML 标签明确区分：

```xml
<realtime_evidence>
{evidence_pool 中的当次收集数据}
</realtime_evidence>

<historical_knowledge>
{RAG 检索的持久化文档}
</historical_knowledge>

<evidence_priority_rules>
1. 实时数据与历史数据冲突时，以实时数据为准
2. 引用历史数据时必须标注数据时间
3. 无法确认时效性的数据需注明截至日期
</evidence_priority_rules>
```

---

## 5. 第三层：Prompt 约束指令

**原则**：在 system prompt 中明确禁止 LLM 编造未证实的事件和数据。

synthesize.py 的 system prompt 包含以下类型的约束：

- **禁止编造事件**："不得编造任何未在 evidence 中出现的事件、日期或数据"
- **数据引用要求**："所有数值必须来自提供的 evidence，不得自行推算"
- **时间标注**："引用数据时必须标注数据时间和来源"
- **不确定性表达**："对不确定的内容使用'根据现有数据'等限定语"

---

## 6. 第四层：未验证事件声明洗涤器

> 这是 FinSight 最核心的**后处理防御层**，在 LLM 输出之后、返回给用户之前执行。

### 6.1 概述

**文件**: `backend/graph/nodes/synthesize.py`
**行号**: 205–281

该层通过 **正则模式匹配 + 证据交叉验证** 识别并移除 LLM 编造的"未来事件声明"（如虚假的产品发布计划、并购传闻）。

### 6.2 模式定义

```python
# synthesize.py:205-218
_HALLUCINATION_EVENT_PATTERNS: tuple[re.Pattern[str], ...] = (
    # 模式 A: "预计 2026Q2 发布..."
    re.compile(
        r"(?:预计|计划|拟于|即将|有望(?:于)?)\s*20\d{2}\s*(?:年|Q[1-4])"
        r"[^\n。；;]{0,26}(?:发布|推出|上线|发售|量产|落地|开售|开源|并购|收购|拆分)"
        r"[^\n。；;]{0,28}",
        flags=re.IGNORECASE,
    ),
    # 模式 B: "预计...发布...2026年"（时间后置）
    re.compile(
        r"(?:预计|计划|拟于|即将|有望(?:于)?)\s*[^\n。；;]{0,20}"
        r"(?:发布|推出|上线|发售|量产|落地|开售|开源|并购|收购|拆分)"
        r"[^\n。；;]{0,20}(?:20\d{2}\s*(?:年|Q[1-4]))"
        r"[^\n。；;]{0,16}",
        flags=re.IGNORECASE,
    ),
)
```

**触发词矩阵**:

| 前缀词（意图） | 动作词（事件类型） |
|---------------|-------------------|
| 预计、计划、拟于、即将、有望 | 发布、推出、上线、发售、量产、落地、开售、开源、并购、收购、拆分 |

**匹配逻辑**:
- 模式 A: `前缀词 + 时间(20XX年/QN) + 0-26字 + 动作词 + 0-28字`
- 模式 B: `前缀词 + 0-20字 + 动作词 + 0-20字 + 时间(20XX年/QN) + 0-16字`

两个模式覆盖中文中"时间前置"和"时间后置"两种常见语序。

### 6.3 证据交叉验证

当正则匹配到一个可疑声明后，**不是直接删除**，而是调用 `_claim_supported_by_evidence()` 检查该声明是否有证据支撑：

```python
# synthesize.py:226-258
def _claim_supported_by_evidence(claim: str, evidence_text: str) -> bool:
    # Step 1: 完全包含检查（最强验证）
    if normalized_claim in normalized_evidence:
        return True

    # Step 2: 关键 token 提取
    key_tokens = []
    - year_match: 提取年份/季度 (e.g. "2026Q2")
    - verb_match: 提取动作词 (e.g. "发布")
    - entity tokens: 提取实体名 (e.g. "Gemini", "2.0")
    - 排除停用词 (预计/计划/拟于/即将/有望/发布/推出/...)

    # Step 3: 命中计数
    hits = count(token in evidence for token in key_tokens[:8])

    # Step 4: 阈值判定
    if year_match:
        return hits >= 2   # 含时间的声明需 ≥2 个 token 命中
    return hits >= 3       # 无时间的声明需 ≥3 个 token 命中
```

**验证阈值设计**:

| 声明类型 | 最低命中数 | 理由 |
|---------|-----------|------|
| 含具体时间（年/季度） | ≥ 2 tokens | 时间本身已是强特征，2 个命中足够确认 |
| 无具体时间 | ≥ 3 tokens | 需要更多 token 交叉验证防止误匹配 |

### 6.4 洗涤执行

```python
# synthesize.py:261-281
def _scrub_unverified_future_claims(text: str, evidence_text: str) -> str:
    cleaned = text
    for pattern in _HALLUCINATION_EVENT_PATTERNS:
        def _replace(match):
            claim = match.group(0)
            if _claim_supported_by_evidence(claim, evidence_text):
                return claim                          # ← 有证据支撑，保留
            logger.warning("scrubbed unverified future claim: %s", claim)
            return _HALLUCINATION_SAFE_PLACEHOLDER    # ← 无证据，替换
        cleaned = pattern.sub(_replace, cleaned)

    # 合并连续占位符（避免 "[已移除] [已移除] [已移除]"）
    cleaned = re.sub(
        rf"(?:{re.escape(_HALLUCINATION_SAFE_PLACEHOLDER)}\s*){{2,}}",
        _HALLUCINATION_SAFE_PLACEHOLDER + " ",
        cleaned,
    )
    return cleaned.strip()
```

**占位符**: `"[此处信息未经证据验证，已移除]"` — 向用户透明地表示此处内容被洗涤。

### 6.5 四个应用点

该函数在 synthesize 管线中被调用 **4 次**，覆盖所有 LLM 输出路径：

| # | 应用位置 | 行号 | 输入 | 证据源 |
|---|---------|------|------|--------|
| 1 | **叙事草稿** | `synthesize.py:1619` | LLM 生成的 Markdown 叙事体报告 | `narrative_grounding_text` (evidence_pool + rag_context) |
| 2 | **风险段落** | `synthesize.py:1878` | LLM 格式化的 risks 字段 | `llm_grounding_text` |
| 3 | **分析/结论段落** | `synthesize.py:1895` | conclusion / investment_thesis / catalysts 等 12 个字段 | `llm_grounding_text` |
| 4 | **其余 LLM 字段** | `synthesize.py:1904` | 所有其他 LLM 生成的 render_vars | `llm_grounding_text` |

```
LLM 输出
  │
  ├── 叙事模式 ──→ _scrub(..., narrative_grounding_text) ──→ 清洁文本
  │
  └── 模板模式
        ├── risks 字段     ──→ _scrub(..., llm_grounding_text) ──→ 清洁风险
        ├── 12 个分析字段  ──→ _scrub(..., llm_grounding_text) ──→ 清洁分析
        └── 其余字段       ──→ _scrub(..., llm_grounding_text) ──→ 清洁文本
```

---

## 7. 第五层：Protected Keys 数据保护

**原则**：关键数据段（价格、技术指标、新闻摘要、对比指标）**强制使用 API 原始数据**，不允许 LLM 重写。

```python
# synthesize.py:1869
protected_keys = {"news_summary", "comparison_metrics", "price_snapshot", "technical_snapshot"}

for key, stub_value in stub_render_vars.items():
    if key in protected_keys:
        render_vars[key] = stub_value   # ← 始终使用确定性数据，LLM 输出被忽略
        continue
```

**被保护的字段**:

| 字段 | 内容 | 保护理由 |
|------|------|----------|
| `news_summary` | 新闻摘要（来自 NewsAgent 工具调用） | 防止 LLM 编造新闻 |
| `comparison_metrics` | 同行对比指标（来自 API） | 防止 LLM 伪造财务数据 |
| `price_snapshot` | 实时价格快照 | 防止 LLM 编造价格 |
| `technical_snapshot` | 技术指标快照 | 防止 LLM 伪造 RSI/MACD 等指标 |

**Stub 机制**: `_stub_render_vars(state)` 从 `GraphState` 的工具调用结果中提取确定性数据，作为默认值。即使 LLM 完全不返回这些字段，报告中仍有真实数据。

---

## 8. 第六层：冲突检测与置信度惩罚

**原则**：当多个 Agent 对同一维度给出矛盾结论时，降低整体置信度并向用户披露。

### 8.1 可比对矩阵

```python
# synthesize.py:498-507
_COMPARABLE_PAIRS = [
    ("price_agent",       "technical_agent",    "趋势方向"),
    ("price_agent",       "fundamental_agent",  "估值判断"),
    ("fundamental_agent", "technical_agent",    "投资评级"),
    ("news_agent",        "fundamental_agent",  "业绩展望"),
    ("news_agent",        "technical_agent",    "短期方向"),
    ("macro_agent",       "fundamental_agent",  "行业前景"),
    ("macro_agent",       "technical_agent",    "市场环境"),
    ("risk_agent",        "fundamental_agent",  "风险评估"),
]
```

### 8.2 触发条件

```python
# synthesize.py:544-545
should_detect = is_deep_report or (success_count >= 2 and comparable_claims_count >= 1)
```

- **深度研报模式**: 始终启用冲突检测
- **普通模式**: 至少 2 个 Agent 成功 + 至少 1 对可比对声明

### 8.3 置信度惩罚

在 `report_builder.py:1537-1566`，当检测到冲突时：

- 每个**高严重度冲突**: 置信度 -0.15
- 每个**中严重度冲突**: 置信度 -0.08
- 冲突信息以结构化文本注入报告的 `conflict_disclosure` 段落

---

## 9. 测试覆盖

### 单元测试

`backend/tests/test_synthesize_node.py` 中包含针对洗涤器的专项测试：

#### 测试 1: 移除无证据支撑的未来声明

```python
def test_scrub_unverified_future_claims_removes_unsupported_release_claim():
    draft = "预计2026Q2发布Gemini 2.0并推动广告业务增长。"
    evidence = "当前仅有PE 28.5与RSI 55等指标，无产品发布时间信息。"

    out = _scrub_unverified_future_claims(draft, evidence)

    assert "未经证据验证" in out      # 占位符出现
    assert "Gemini 2.0" not in out    # 幻觉内容被移除
```

#### 测试 2: 保留有证据支撑的声明

```python
def test_scrub_unverified_future_claims_keeps_claim_when_grounded():
    draft = "预计2026Q2发布Gemini 2.0并推动广告业务增长。"
    evidence = "公司公告提到：预计2026Q2发布Gemini 2.0，用于广告产品。"

    out = _scrub_unverified_future_claims(draft, evidence)

    assert out == draft  # 有证据支撑，原文保留
```

### 集成测试

- `test_synthesize_node.py` 的其他测试验证完整 synthesize 流程中 stub 数据不被 LLM 覆盖
- Protected keys 测试确保 `news_summary` 等字段始终来自 API 数据

---

## 10. 运行时监控

### 日志

洗涤器每次执行替换都会输出 WARNING 级别日志：

```
[Synthesize] scrubbed unverified future claim: 预计2026Q2发布Gemini 2.0并推动广告业务增长
```

可通过日志聚合统计：
- 每日洗涤次数 → 监控 LLM 幻觉率变化趋势
- 按 ticker 分组 → 发现特定股票的幻觉高发区

### RAG Stats

`rag_stats` 字段中包含检索诊断信息，可间接反映证据覆盖质量：

| 字段 | 含义 |
|------|------|
| `embedding_model` | 使用的 embedding 模型（bge-m3） |
| `reranker_used` | 是否启用了 cross-encoder 精排 |
| `router_decision` | 查询路由决策（SKIP/SECONDARY/PRIMARY/PARALLEL） |
| `total_persistent_docs` | RAG 持久化文档总数 |

---

## 11. 局限性与未来方向

### 当前局限

| 局限 | 说明 |
|------|------|
| **仅覆盖中文事件声明** | 正则模式以中文触发词为主，英文声明（"expected to launch..."）未覆盖 |
| **仅检测未来事件** | 不检测历史事件编造（如 "去年 Q3 营收增长 200%"） |
| **token 匹配非语义** | `_claim_supported_by_evidence` 基于 token 共现而非语义理解 |
| **无数值验证** | 不验证 LLM 输出的数值是否与 evidence 中的数值一致 |

### 未来增强方向

| 方向 | 描述 | 优先级 |
|------|------|--------|
| 英文模式扩展 | 添加 "expected to" / "plans to" / "set to launch" 等英文触发词 | P1 |
| 数值一致性校验 | 提取 LLM 输出中的数字，与 evidence 中的数字做区间匹配 | P1 |
| 语义级验证 | 用 bge-m3 embedding 做 claim-evidence 语义相似度计算 | P2 |
| 历史事件检测 | 扩展模式覆盖 "去年/上季度/此前" 等历史时间词 | P2 |
| 数据时效性标注 | 自动为 LLM 引用的数据添加 "截至 YYYY-MM-DD" 标注 | P2 |

---

## 附录：文件索引

| 文件 | 行号 | 内容 |
|------|------|------|
| `backend/graph/nodes/synthesize.py` | 205–218 | `_HALLUCINATION_EVENT_PATTERNS` 正则定义 |
| `backend/graph/nodes/synthesize.py` | 219 | `_HALLUCINATION_SAFE_PLACEHOLDER` 占位符 |
| `backend/graph/nodes/synthesize.py` | 222–223 | `_normalize_for_match()` 标准化函数 |
| `backend/graph/nodes/synthesize.py` | 226–258 | `_claim_supported_by_evidence()` 证据交叉验证 |
| `backend/graph/nodes/synthesize.py` | 261–281 | `_scrub_unverified_future_claims()` 主洗涤函数 |
| `backend/graph/nodes/synthesize.py` | 1619 | 应用点 1: 叙事草稿洗涤 |
| `backend/graph/nodes/synthesize.py` | 1878 | 应用点 2: 风险段落洗涤 |
| `backend/graph/nodes/synthesize.py` | 1895 | 应用点 3: 分析/结论段落洗涤 |
| `backend/graph/nodes/synthesize.py` | 1904 | 应用点 4: 其余 LLM 字段洗涤 |
| `backend/graph/nodes/synthesize.py` | 498–507 | `_COMPARABLE_PAIRS` 冲突检测矩阵 |
| `backend/graph/nodes/synthesize.py` | 430–539 | `_collect_conflict_disclosure()` 冲突检测 |
| `backend/graph/report_builder.py` | 1537–1566 | 冲突注入 + 置信度惩罚 |
| `backend/tests/test_synthesize_node.py` | 333–353 | 洗涤器单元测试 |
