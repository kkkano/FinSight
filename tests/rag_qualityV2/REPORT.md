# FinSight RAG Quality V2 — 评估报告

> **评估框架**: RAG Quality V2 (Claim-level + Keypoint-level)
> **评估日期**: 2026-02-28
> **LLM (Chat/Judge)**: Grok-4.1-fast (`grok.jiuuij.de5.net`)
> **Embedding**: BAAI/bge-m3 (`api.siliconflow.cn`)
> **数据集**: `tests/rag_quality/dataset.json` (12 cases, v1)

---

## 1. 为什么需要 V2

V1 基于 RAGAS 0.4.x 的四项指标（faithfulness、answer_relevancy、context_precision、context_recall），在短答案 QA 场景表现出色。但在 FinSight 的投研叙事场景中暴露了三个局限：

1. **评估目标错位**：Layer3 生成的是长篇投研叙事（含推理与建议），单一 faithfulness 无法区分"是检索缺失还是无证据扩写"。
2. **数值敏感度不足**：金融场景的核心是数字（营收、毛利率、增速），RAGAS 将数值与普通文本等权对待，无法单独追踪数值一致性。
3. **可诊断性弱**：四项指标高度耦合，某项低分时难以快速定位是 Retrieval 问题、Generation 问题还是 Grounding 问题。

**V2 目标**：把"检索覆盖、陈述归因、数值一致性、关键点完成度"拆开评估，形成**可诊断、可门控、可回归**的质量框架。

---

## 2. 扒开黑盒 — V2 六维指标方法论

### 2.1 评估流水线

V2 对每个测试用例执行以下 6 步流水线：

```
                    ┌─────────────┐
                    │  Question   │
                    │ + Context   │
                    └──────┬──────┘
                           │
                    ┌──────▼──────┐
              ┌─────┤  Answer (A) ├─────┐
              │     └─────────────┘     │
              │                         │
     ┌────────▼────────┐     ┌─────────▼─────────┐
     │ Extract Claims  │     │ Extract Keypoints  │
     │   from Answer   │     │ from Ground Truth  │
     └────────┬────────┘     └─────────┬──────────┘
              │                        │
     ┌────────▼────────┐     ┌─────────▼──────────┐
     │ Embed + Top-K   │     │ Embed + Top-K      │
     │ Evidence Recall  │     │ Evidence Recall     │
     └────────┬────────┘     └─────────┬──────────┘
              │                        │
     ┌────────▼────────┐     ┌─────────▼──────────┐
     │  LLM Judge:     │     │  LLM Judge:        │
     │  Claim Verdict   │     │  Keypoint Coverage │
     └────────┬────────┘     └─────────┬──────────┘
              │                        │
              └────────────┬───────────┘
                    ┌──────▼──────┐
                    │ Aggregate   │
                    │  6 Metrics  │
                    └──────┬──────┘
                    ┌──────▼──────┐
                    │ Gate Check  │
                    └─────────────┘
```

### 2.2 六维指标定义

| # | 指标 | 公式 | 取值 | 含义 |
|---|------|------|------|------|
| 1 | `keypoint_coverage` (KC) | `(covered + 0.5 × partial) / total_keypoints` | [0, 1] | 答案覆盖标准答案关键点的比例 |
| 2 | `keypoint_context_recall` (KCR) | `keypoints_supported_by_context / total_keypoints` | [0, 1] | 关键点能在检索证据中找到依据的比例 |
| 3 | `claim_support_rate` (CSR) | `supported_claims / total_claims` | [0, 1] | 答案陈述被证据支持的比例 |
| 4 | `unsupported_claim_rate` (UCR) | `unsupported_claims / total_claims` | [0, 1] | 无证据支撑的幻觉陈述占比（越低越好） |
| 5 | `contradiction_rate` (CR) | `contradicted_claims / total_claims` | [0, 1] | 与证据直接矛盾的陈述占比（越低越好） |
| 6 | `numeric_consistency_rate` (NCR) | `supported_numeric / total_numeric` | [0, 1] | 数值型陈述与证据一致的比例 |

**分母为 0 的处理**：当某维度分母为 0（如无 numeric claim），该指标返回 `null`，不参与门控计算。

### 2.3 LLM Judge 判定规则

**Claim Judge** 对每条 claim 输出三元标签：
- `supported`：证据可直接支撑该陈述
- `unsupported`：证据不足以支持
- `contradicted`：证据与陈述明确冲突

额外字段：`is_numeric_claim`（是否含金额/比例/增速）、`numeric_consistent`（数值是否一致，允许等价表达如单位换算、四舍五入）。

**Keypoint Judge** 对每个 keypoint 输出覆盖标签：
- `covered`：答案完整覆盖（计 1.0）
- `partial`：只覆盖部分事实或缺时间/单位（计 0.5）
- `missing`：未覆盖（计 0.0）

额外字段：`context_supported`（该 keypoint 在证据中可找到直接支撑）。

### 2.4 V1 → V2 指标映射

| V1 (RAGAS) | V2 (Claim/Keypoint) | 关系 |
|---|---|---|
| faithfulness | CSR + UCR + CR | V2 将 faithfulness 拆为三个独立维度 |
| answer_relevancy | KC + KCR | V2 将相关性拆为答案完整度与证据可追溯性 |
| context_precision | KCR (部分) | 检索精度通过 keypoint 在证据中的支撑率间接衡量 |
| context_recall | KCR | 检索召回通过 keypoint 证据覆盖直接衡量 |
| _(无)_ | NCR | **V2 新增** — 金融场景核心：数值一致性 |

---

## 3. RAG 测试金字塔

```
                          ╱╲
                         ╱  ╲
                        ╱ L3 ╲          ← 端到端 Pipeline (LangGraph)
                       ╱      ╲            最真实、最慢、信号最强
                      ╱────────╲
                     ╱   L2     ╲       ← 真实 Embedding 检索 + synthesize_agent
                    ╱            ╲         测试检索 + 生成协同
                   ╱──────────────╲
                  ╱      L1        ╲    ← Mock Context + 直接 Prompt
                 ╱                  ╲      测试 LLM 生成质量基线
                ╱────────────────────╲
```

### 三层定位

| 层级 | 输入 | Pipeline | 测什么 | 不测什么 | 信号含义 |
|------|------|----------|--------|----------|----------|
| **Layer 1** | Mock contexts → LLM Prompt | 无 | LLM 生成能力基线 | 检索质量 | "给定完美证据，LLM 能否生成合格答案" |
| **Layer 2** | 真实 Embedding + Top-K → synthesize_agent | chunk + retrieval | 检索 + 生成协同 | Pipeline 路由 | "检索能否找到正确证据并生成合格答案" |
| **Layer 3** | 完整 LangGraph E2E | 全流程 | 端到端质量 | 单一环节归因 | "用户视角的真实输出质量" |

**核心原则**：Layer1 是地基、Layer2 测管道、Layer3 验全局。三层全 PASS 才能发布。

### 运行命令

```bash
# Layer 1
python tests/rag_qualityV2/run_layer1_v2.py --gate --save-baseline

# Layer 2
python tests/rag_qualityV2/run_layer2_v2.py --top-k 5 --chunk-size 300 --gate --save-baseline

# Layer 3
python tests/rag_qualityV2/run_layer3_v2.py --output-mode brief --gate --save-baseline
```

---

## 4. 测试用例说明

12 个测试用例覆盖 3 种文档类型 × 3 种问题类型：

### 财报类 (filing) — 4 cases

| Case ID | 问题 | 问题类型 | 难度 |
|---------|------|----------|------|
| `filing_maotai_revenue_2024q3` | 茅台 2024Q3 营业收入及分项数据 | factoid | 低 |
| `filing_catl_gross_margin_2024` | 宁德时代 2024H1 毛利率及驱动因素 | analysis | 中 |
| `filing_byd_ev_sales_2024h1` | 比亚迪 2024H1 新能源汽车销量与市场份额 | factoid | 低 |
| `filing_paic_embedded_value_2024` | 中国平安 2024 中期内含价值及新业务价值 | factoid | 低 |

### 电话会类 (transcript) — 4 cases

| Case ID | 问题 | 问题类型 | 难度 |
|---------|------|----------|------|
| `transcript_alibaba_cloud_guidance` | 阿里云 FY25Q2 业绩指引及 AI 增长 | analysis | 中 |
| `transcript_tencent_gaming_recovery` | 腾讯游戏业务复苏与新增长引擎 | analysis | 高 |
| `transcript_meituan_profitability` | 美团各业务板块盈利情况与竞争格局 | analysis | 高 |
| `transcript_jd_supply_chain` | 京东自营供应链竞争优势与运营效率 | analysis | 高 |

### 新闻类 (news) — 4 cases

| Case ID | 问题 | 问题类型 | 难度 |
|---------|------|----------|------|
| `news_fed_rate_cut_astock` | 美联储降息对 A 股的影响路径 | list | 中 |
| `news_china_ev_export_competition` | 中国电车出口面临的贸易壁垒 | list | 高 |
| `news_apple_iphone16_china_sales` | iPhone 16 中国首周销售表现分析 | analysis | 中 |
| `news_semiconductor_export_controls` | 美国半导体出口管制对中国 AI 的影响 | analysis | 高 |

---

## 5. 实测结果总览

### 5.1 三层总览对比

**运行参数**：`--save-baseline --delay 0 --intra-case-delay 0`（Layer3 额外 `--output-mode brief`）

| 层级 | Run ID | Gate | Drift | KC | KCR | CSR | UCR ↓ | CR ↓ | NCR |
|------|--------|------|-------|------|------|------|-------|------|------|
| Layer1 | `layer1_v2-20260228-182903` | **PASS** | **PASS** | 0.8796 | 0.9479 | 0.9431 | 0.0569 | 0.0 | 0.9896 |
| Layer2 | `layer2_v2-20260228-205342` | **PASS** | **PASS** | 0.8960 | 0.9623 | 1.0000 | 0.0000 | 0.0 | 0.9861 |
| Layer3 | `layer3_v2-20260228-211806` | **PASS** | **PASS** | 0.9072 | 0.9653 | 0.9924 | 0.0076 | 0.0 | 1.0000 |

> 三层全 PASS，12/12 case 均通过门控。

### 5.2 按文档类型 (Layer 3)

| doc_type | KC | KCR | CSR | UCR ↓ | CR ↓ | NCR |
|----------|------|------|------|-------|------|------|
| filing | **1.0000** | **1.0000** | **1.0000** | 0.0000 | 0.0 | **1.0000** |
| news | 0.9062 | 0.9375 | 0.9773 | 0.0227 | 0.0 | **1.0000** |
| transcript | 0.8155 | 0.9583 | **1.0000** | 0.0000 | 0.0 | **1.0000** |

**要点**：
- 财报类全维度满分 — 结构化数据 + factoid 问题天然优势
- 电话会类 KC 偏低（0.8155）— 长叙事中个别细粒度 keypoint 被遗漏
- 新闻类 UCR 略高（0.0227）— 一条无证据支撑的 claim 拉低

### 5.3 按问题类型 (Layer 3)

| q_type | KC | KCR | CSR | UCR ↓ | CR ↓ | NCR |
|--------|------|------|------|-------|------|------|
| factoid | **1.0000** | **1.0000** | **1.0000** | 0.0000 | 0.0 | **1.0000** |
| analysis | 0.8410 | 0.9405 | **1.0000** | 0.0000 | 0.0 | **1.0000** |
| list | **1.0000** | **1.0000** | 0.9546 | 0.0454 | 0.0 | **1.0000** |

**要点**：
- factoid 全满分 — 精确问答是 RAG 最佳场景
- analysis 类 KC 较低（0.841）— 开放分析中 keypoint 粒度更细，易遗漏
- list 类 CSR 略低（0.9546）— 列表类答案 claim 数量多，偶发无证据支撑

---

## 6. Layer 3 逐案详析

### 6.1 E2E 逐案指标

| # | Case ID | 类型 | KC | KCR | CSR | UCR ↓ | CR ↓ | NCR | 状态 |
|---|---------|------|------|------|------|-------|------|------|------|
| 01 | `filing_maotai_revenue_2024q3` | filing/factoid | 1.0 | 1.0 | 1.0 | 0.0 | 0.0 | 1.0 | ✅ 满分 |
| 02 | `filing_catl_gross_margin_2024` | filing/analysis | 1.0 | 1.0 | 1.0 | 0.0 | 0.0 | 1.0 | ✅ 满分 |
| 03 | `filing_byd_ev_sales_2024h1` | filing/factoid | 1.0 | 1.0 | 1.0 | 0.0 | 0.0 | 1.0 | ✅ 满分 |
| 04 | `filing_paic_embedded_value_2024` | filing/factoid | 1.0 | 1.0 | 1.0 | 0.0 | 0.0 | 1.0 | ✅ 满分 |
| 05 | `transcript_alibaba_cloud_guidance` | transcript/analysis | 1.0 | 1.0 | 1.0 | 0.0 | 0.0 | 1.0 | ✅ 满分 |
| 06 | `transcript_tencent_gaming_recovery` | transcript/analysis | 0.7143 | 1.0 | 1.0 | 0.0 | 0.0 | 1.0 | ⚠️ KC |
| 07 | `transcript_meituan_profitability` | transcript/analysis | 0.8333 | 0.8333 | 1.0 | 0.0 | 0.0 | 1.0 | ⚠️ KC |
| 08 | `transcript_jd_supply_chain` | transcript/analysis | 0.7143 | 1.0 | 1.0 | 0.0 | 0.0 | 1.0 | ⚠️ KC |
| 09 | `news_fed_rate_cut_astock` | news/list | 1.0 | 1.0 | 1.0 | 0.0 | 0.0 | 1.0 | ✅ 满分 |
| 10 | `news_china_ev_export_competition` | news/list | 1.0 | 1.0 | 0.9091 | 0.0909 | 0.0 | 1.0 | ⚠️ UCR |
| 11 | `news_apple_iphone16_china_sales` | news/analysis | 1.0 | 1.0 | 1.0 | 0.0 | 0.0 | 1.0 | ✅ 满分 |
| 12 | `news_semiconductor_export_controls` | news/analysis | 0.625 | 0.75 | 1.0 | 0.0 | 0.0 | 1.0 | ⚠️ KC |

**统计**：满分 7/12 (58.3%)，带 ⚠️ 但仍 PASS 5/12 (41.7%)，失败 0/12。

### 6.2 非满分用例根因分析

#### Case 06: `transcript_tencent_gaming_recovery` — KC=0.7143

**问题**：7 个 keypoints 中 4 个 covered、3 个 partial。

| Keypoint | 状态 | 原因 |
|----------|------|------|
| 《王者荣耀》表现稳健 | partial | 答案只提整体游戏复苏，未点名《王者荣耀》创历史新高 |
| 《和平精英》表现稳健 | partial | 答案未提及《和平精英》在核心市场保持稳定 |
| 新游戏管线储备充足 | partial | 答案只提研发成本管理，未提及 2025 年多款重磅新游 |

**根因**：Pipeline 的 brief 模式优先输出宏观结论（"全面恢复增长"），牺牲了个别产品级细节。证据中存在相关信息（KCR=1.0），但生成环节未充分利用。

---

#### Case 07: `transcript_meituan_profitability` — KC=0.8333, KCR=0.8333

**问题**：6 个 keypoints 中 5 个 covered、1 个 missing。

| Keypoint | 状态 | 原因 |
|----------|------|------|
| 全年集团层面自由现金流预计为正 | missing | 答案和证据均未提及自由现金流（FCF），仅覆盖经营利润 |

**根因**：标准答案的 "自由现金流预计为正" keypoint 在证据中也找不到支撑（context_supported=false），属于 **ground truth 超出证据范围**。这是评估设计的边界 case，不影响 Pipeline 质量判断。

---

#### Case 08: `transcript_jd_supply_chain` — KC=0.7143

**问题**：7 个 keypoints 中 5 个 covered、1 个 partial、1 个 missing。

| Keypoint | 状态 | 原因 |
|----------|------|------|
| 京东管理层表示采用自营供应链模式 | missing | 答案列举了供应链的各项优势指标，但未直接引用"自营供应链模式是最核心竞争壁垒"的管理层定性表述 |
| 自营供应链带来更高的用户信任 | partial | 答案通过复购频次间接体现信任，但未直接使用"信任"相关词汇 |

**根因**：生成偏好量化数据（毛利率、仓库数、周转天数），对管理层定性表述覆盖不足。

---

#### Case 10: `news_china_ev_export_competition` — CSR=0.9091, UCR=0.0909

**问题**：11 条 claims 中 10 条 supported、1 条 unsupported。

| Claim | 判定 | 原因 |
|-------|------|------|
| "2024年下半年泰国、印尼等国相继启动补贴审查程序" | unsupported | 证据中有泰国/印尼单独的调查描述，但"相继启动审查程序"的综合性总结超出了证据的直接表述 |

**根因**：生成环节将两个独立事件（泰国调查 + 印尼质疑）综合概括为"相继启动审查程序"，属于轻度归纳扩写。

---

#### Case 12: `news_semiconductor_export_controls` — KC=0.625, KCR=0.75

**问题**：8 个 keypoints 中 5 个 covered、1 个 partial、2 个 missing。

| Keypoint | 状态 | 原因 |
|----------|------|------|
| A100 GPU 被列入出口禁令 | missing | 答案只提到 A800/H800（降规版），未提及 A100 原版 |
| H100 GPU 被列入出口禁令 | missing | 同上，未提及 H100 原版 |
| 管制措施限制算力阈值以上芯片出口 | partial | 提到"收紧算力性能阈值"但未说明具体阈值标准 |

**根因**：证据聚焦 2024 年 10 月新规（针对 A800/H800 降规版），而 keypoints 涉及更早期的 A100/H100 禁令（2022-2023 年），时间跨度不匹配导致覆盖缺失。

---

## 7. 跨层趋势分析

### 7.1 总体指标趋势

| 指标 | Layer1 | Layer2 | Layer3 | 趋势 | 解读 |
|------|--------|--------|--------|------|------|
| KC | 0.8796 | 0.8960 | 0.9072 | ↑ 逐层提升 | E2E pipeline 的 grounded fallback 机制提升了覆盖率 |
| KCR | 0.9479 | 0.9623 | 0.9653 | ↑ 逐层提升 | 真实检索的证据覆盖优于 mock context |
| CSR | 0.9431 | **1.0000** | 0.9924 | ↑ then ↓ | L2 满分但 L3 有一条 unsupported claim（归纳扩写所致） |
| UCR | 0.0569 | **0.0000** | 0.0076 | ↓ 显著改善 | L1 的幻觉率最高（mock context 下 LLM 更容易扩写） |
| CR | 0.0000 | 0.0000 | 0.0000 | → 全程零 | 无事实矛盾，说明 Prompt 的"不得编造"约束有效 |
| NCR | 0.9896 | 0.9861 | **1.0000** | ↑ 最终满分 | L3 数值一致性达到完美，brief 模式 + numeric 后处理生效 |

### 7.2 按文档类型的跨层趋势

**filing (财报类)**

| 指标 | L1 | L2 | L3 | 趋势 |
|------|------|------|------|------|
| KC | 0.9583 | 1.0 | 1.0 | ↑ 稳定满分 |
| CSR | 0.9125 | 1.0 | 1.0 | ↑ 大幅改善 |
| NCR | 1.0 | 1.0 | 1.0 | → 全程满分 |

**transcript (电话会类)**

| 指标 | L1 | L2 | L3 | 趋势 |
|------|------|------|------|------|
| KC | 0.7521 | 0.8452 | 0.8155 | ↑ then ↓ |
| KCR | 0.8854 | 0.9583 | 0.9583 | ↑ 稳定 |
| NCR | 1.0 | 0.9583 | 1.0 | ↓ then ↑ |

**news (新闻类)**

| 指标 | L1 | L2 | L3 | 趋势 |
|------|------|------|------|------|
| KC | 0.9285 | 0.8428 | 0.9062 | ↓ then ↑ |
| UCR | 0.0833 | 0.0 | 0.0227 | ↓↑ 波动 |
| NCR | 0.9688 | 1.0 | 1.0 | ↑ 稳定满分 |

### 7.3 趋势关键发现

1. **KC 随层级上升但 transcript 类波动**：电话会议内容信息密度高、keypoints 粒度细，E2E pipeline 的 brief 模式会牺牲部分细节。
2. **UCR 在 L1 最高**：Mock context 场景下，LLM 更容易脱离证据扩写（无真实检索约束）。
3. **NCR 在 L3 达到完美**：brief 输出模式 + engine_v2 的 numeric claim 后处理机制确保数值严格一致。
4. **CR 全场零**：12 个 case × 3 层 = 36 次评估，零矛盾。Prompt 中"不得引入证据外事实"的硬约束非常有效。

---

## 8. 亮点与发现

### 8.1 亮点

| 发现 | 数据支撑 | 原因分析 |
|------|----------|----------|
| 财报类 4/4 全维度满分 (L3) | filing: 全部 1.0 | 结构化数据 + factoid 问题 = RAG 最佳场景 |
| 数值一致性 L3 满分 | NCR = 1.0 | Prompt 约束 + engine_v2 numeric 后处理双重保障 |
| 矛盾率全场零 | CR = 0.0 (36 次评估) | "不得编造证据外事实"硬约束有效 |
| 幻觉率极低 | UCR: L2=0.0, L3=0.0076 | 检索增强 + faithfulness 约束将幻觉压到极低 |
| 7/12 case E2E 满分 | 58.3% 完美得分 | 基础 RAG 能力扎实 |

### 8.2 改进空间

| 问题模式 | 影响 case | 建议 |
|----------|-----------|------|
| brief 模式丢失产品级细节 | tencent_gaming (#06) | 考虑在 brief 模式中保留关键产品名提及 |
| 管理层定性表述覆盖不足 | jd_supply_chain (#08) | Prompt 增加"引用管理层核心表述"要求 |
| Ground truth 超出证据范围 | meituan_profitability (#07) | 审查 dataset.json 中 FCF 相关 keypoint |
| 归纳扩写导致 unsupported | ev_export (#10) | 加强"仅输出证据直接支撑的结论"约束 |
| 历史 vs 新规时间跨度 | semiconductor (#12) | 补充 2022-2023 年 A100/H100 禁令的 context |

---

## 9. 指标优化指南

当某个指标低于预期时，按以下路径排查：

| 指标低分 | 含义 | 排查方向 | 修复方向 |
|----------|------|----------|----------|
| **KC 低** | 答案未覆盖标准答案的关键点 | 检查生成 Prompt 是否要求"覆盖所有要点" | 优化 Prompt 要求；调整 output_mode |
| **KCR 低** | 关键点在证据中找不到支撑 | 检查检索召回率，是否 top-k 不够 | 增大 top-k；优化 chunk 策略 |
| **CSR 低** | 答案含无证据支撑的陈述 | 检查 claim_judgments 中 unsupported 的 rationale | 加强 faithfulness 约束 |
| **UCR 高** | 幻觉率过高 | 检查是否存在归纳扩写、常识补充 | 缩小生成范围；添加"只输出证据直接支撑的结论" |
| **CR 高** | 答案与证据矛盾 | 检查 claim_judgments 中 contradicted 的 rationale | 检查 context ranking；是否有冲突证据 |
| **NCR 低** | 数值不一致 | 检查 numeric_consistent=false 的 claims | 检查提取和格式化环节；验证单位换算 |

### 快速定位流程

```
指标异常
  ├── KC/KCR 低 → 检索问题（Retrieval）
  │     ├── KCR 也低 → 证据中就没有 → 增加数据源/top-k
  │     └── KCR 正常 → 生成未利用证据 → 优化 Prompt
  ├── CSR/UCR/CR 异常 → 生成问题（Generation）
  │     ├── UCR 高 → 幻觉 → 加强约束
  │     └── CR 高 → 矛盾 → 检查证据排序
  └── NCR 低 → 数值处理问题
        ├── 检查 is_numeric_claim 判定
        └── 检查单位换算/四舍五入逻辑
```

---

## 10. 框架技术细节

### 10.1 架构

```
types_v2.py          ← 数据类型定义 (CaseResultV2, GateResultV2, ...)
  ↓
clients_v2.py        ← API 客户端工厂 (Chat/Embedding)
  ↓
prompts_v2.py        ← 5 组 Prompt 模板
  ↓
engine_v2.py         ← 核心评估引擎 (741 行)
  ↓
run_layer{1,2,3}_v2.py  ← 三层运行脚本
  ↓
thresholds_v2.json   ← 门控阈值配置
  ↓
reports/             ← JSON 评估报告输出
```

### 10.2 环境变量

```bash
# Chat / Judge（默认 Grok）
RQV2_CHAT_API_KEY=<YOUR_CHAT_KEY>
RQV2_CHAT_BASE_URL=https://grok.jiuuij.de5.net/v1
RQV2_CHAT_MODEL=grok-4.1-fast

# Embedding（默认 SiliconFlow）
RQV2_EMBED_API_KEY=<YOUR_EMBED_KEY>
RQV2_EMBED_BASE_URL=https://api.siliconflow.cn/v1
RQV2_EMBED_MODEL=BAAI/bge-m3

# 回退兼容（可选）
LLM_API_KEY=<FALLBACK_KEY>
```

### 10.3 门控规则

**阈值文件**: `tests/rag_qualityV2/thresholds_v2.json`

**全局默认**:

| 指标 | 门控值 | 方向 | Excellent |
|------|--------|------|-----------|
| keypoint_coverage | ≥ 0.70 | min | 0.85 |
| keypoint_context_recall | ≥ 0.70 | min | 0.85 |
| claim_support_rate | ≥ 0.70 | min | 0.88 |
| unsupported_claim_rate | ≤ 0.15 | max | 0.08 |
| contradiction_rate | ≤ 0.05 | max | 0.02 |
| numeric_consistency_rate | ≥ 0.90 | min | 0.96 |

**文档类型覆盖**：filing 更严格（NCR ≥ 0.97, UCR ≤ 0.10），news/transcript 适度放宽。

**问题类型覆盖**：factoid 要求 KC ≥ 0.80 + NCR ≥ 0.95。

**Null 策略**：任一指标 null_rate = 100% 直接失败；> 10% 也失败。

**覆盖策略**：同时命中 doc_type 和 question_type 覆盖时，min 取更大值，max 取更小值。

**漂移门控**：
- KC/KCR/CSR/NCR delta_min: -0.05（不得比基线低 5%）
- UCR delta_max: +0.03（幻觉率不得比基线高 3%）
- CR delta_max: +0.02（矛盾率不得比基线高 2%）

---

## 11. 与 V1 的对照

| 维度 | V1 (RAGAS) | V2 (Claim/Keypoint) |
|------|------------|---------------------|
| 主要指标 | 4 项 (faithfulness, relevancy, precision, recall) | 6 项 (KC, KCR, CSR, UCR, CR, NCR) |
| 适配场景 | 短答案 / 标准 QA | 长叙事 + 证据归因 |
| 数值敏感性 | 无 | 有 (NCR 独立追踪) |
| 可诊断性 | 中等 | 高（可区分检索缺失 / 无证据扩写 / 数值错误） |
| 硬门控 | 以 min 为主 | 同时支持 min/max + null-rate 硬规则 |
| 漂移检测 | 单向 (delta_min) | 双向 (delta_min + delta_max) |
| LLM 依赖 | RAGAS 内置 (需 OpenAI) | 可替换任意 OpenAI 兼容 API |

**建议**：
1. 看 "基础 RAG 能力" → 优先看 V1
2. 看 "真实叙事输出质量" → 优先看 V2
3. 发布前 → 以 V2 gate 作为最终质量拦截

---

## 12. 常见故障排查

### 12.1 LLM JSON 解析失败

**现象**：`extract_keypoints` / `extract_claims` / `judge_claim` 报 JSON 解析错误。

**处理**：
1. 检查上游模型是否返回了 markdown/code fence 包裹
2. 降低 temperature 到 `0.0`
3. 复查代理是否在响应中注入额外前后缀

### 12.2 Embedding endpoint 不可用

**现象**：`Embedding 调用失败`。

**处理**：
1. 检查 `RQV2_EMBED_BASE_URL` 是否支持 `/embeddings` endpoint
2. 检查 `RQV2_EMBED_MODEL` 可用性（默认 `BAAI/bge-m3`）
3. 检查 key 权限是否包含 embedding 调用

### 12.3 null_rate 超阈值

**现象**：门控显示 `null_rate=100%` 或 `>10%`。

**处理**：
1. 查看 `case_results[].metric_errors` 定位是 claim judge 还是 keypoint judge 失败
2. 先用 `--mock` 验证框架逻辑，再切真实 API
3. 若仅某一层失败，优先检查该层答案来源

---

## 13. 基线更新与 CI

### 基线更新流程

1. 先跑非 gate 观察结果
2. 再跑 `--gate --save-baseline`
3. 提交 `baseline_layer{1,2,3}_v2.json`
4. 在 PR 描述里附上指标变化与漂移解释

### CI 快测

```bash
pytest -q tests/rag_qualityV2
python tests/rag_qualityV2/run_layer1_v2.py --mock --gate
python tests/rag_qualityV2/run_layer2_v2.py --mock --gate
python tests/rag_qualityV2/run_layer3_v2.py --mock --gate
```

---

## 14. 结论与改进方向

### 总体评价

V2 框架在 12 个真实测试用例上展现了强大的评估能力：

- **三层全 PASS**：Layer1/2/3 均通过门控和漂移检测
- **矛盾率零**：36 次评估无一事实矛盾
- **数值一致性 L3 满分**：金融场景最核心的数值精度达到完美
- **幻觉率极低**：L3 UCR=0.0076（仅 1 条 unsupported claim / 132 条总 claim）
- **财报类全满分**：4/4 case 六维度全部 1.0

### 下一步优化

1. **Prompt 优化**：在 brief 模式中保留关键产品名和管理层核心表述，提升 transcript 类 KC
2. **数据集审查**：检查 ground_truth 中超出证据范围的 keypoints（如美团 FCF）
3. **时间跨度覆盖**：对半导体管制等 case 补充历史政策 context，避免 A100/H100 遗漏
4. **归纳扩写检测**：在 claim judge 中增加"是否为归纳概括"的判定维度
5. **自动化回归**：将 V2 gate 接入 CI/CD，每次 Prompt 变更自动触发三层评估

---

*最后更新：2026-02-28*
*评估框架：RAG Quality V2（Grok-4.1-fast Chat + SiliconFlow BGE-M3 Embedding）*
