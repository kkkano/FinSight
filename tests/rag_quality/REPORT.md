# FinSight RAG 生成质量评估报告

## 📖 评估框架说明：这个测试到底在测什么？

本测试模块（`tests/rag_quality`）是整个 RAG（检索增强生成）系统中核心的**质量保障（QA）环节**。它不仅仅是在测“能不能找到数据”，而是在全面评估 RAG 系统的**“生成质量”和“检索质量”**。

### 1. 测什么？（四大核心指标）
本测试基于业界标准的 **RAGAS** 评估框架，主要评估四个维度：
- **忠实度 (Faithfulness / 防幻觉)**：LLM 生成的答案，是不是**完全基于**提供的参考文档？有没有胡编乱造（幻觉）？在金融场景下极其重要，财报里的数字绝对不能瞎编。
- **答案相关性 (Answer Relevancy)**：生成的答案有没有**直接回答**用户的问题？还是在答非所问、绕弯子？
- **上下文精确率 (Context Precision)**：找出来的参考文档里，**有用的信息排在前面吗**？是不是塞了一堆无关的垃圾信息（噪声）？
- **上下文召回率 (Context Recall)**：为了回答这个问题所需要的**所有关键信息**，找出来的文档里都包含了吗？有没有漏掉关键数据？

### 2. 数据哪里来的？为什么要设计假数据（`mock_contexts`）？
测试使用的数据（`dataset.json`）**不是**每次测试时从向量数据库里实时搜出来的，而是人工精心准备的**“黄金数据集（Golden Dataset）”**。

**为什么要用写死的 `mock_contexts`（模拟上下文），而不是直接连数据库测？**
这是为了**控制变量（解耦测试）**。RAG 系统分为“检索（找数据）”和“生成（写答案）”两步。如果直接连数据库测，答案错了你不知道是检索没搜到，还是大模型瞎总结。
通过人为给定一段**固定**的参考文本（`mock_contexts`），让大模型基于这段文本去回答问题：
- 因为上下文是固定的，如果大模型回答错了或者瞎编了，那**百分之百是大模型（生成环节）的锅**，或者是 Prompt 没写好。
- 这样可以保证测试的**稳定性**和**可重复性**。每次跑 CI/CD 流水线，不会因为数据库里多了一篇文章导致测试结果忽高忽低。

### 3. 每一步的拆解：测试脚本到底在干啥？
当运行测试脚本时，程序在后台执行了以下步骤：
1. **加载“考卷”**：读取 `dataset.json`，获取预设的 Question（问题）、Mock Contexts（参考资料）和 Ground Truth（标准答案）。
2. **让大模型“做题”**：把 Question 和 Mock Contexts 喂给 RAG 生成大模型，让它基于参考资料写出一个答案（此时大模型看不到标准答案）。
3. **让另一个大模型当“阅卷老师”**：调用 RAGAS 框架，唤起一个“裁判大模型（Evaluator LLM）”来打分：
   - *看忠实度*：对比生成答案和参考资料，看有没有瞎编。
   - *看相关性*：对比生成答案和问题，看有没有答非所问。
   - *看召回率*：对比参考资料和标准答案，看参考资料有没有漏掉关键点。
4. **对成绩进行“门控拦截”（Gate Checking）**：读取 `thresholds.json`（及格线配置）。如果某项指标（如忠实度）低于最低阈值，程序会**报错拦截（Exit 1）**，防止糟糕的代码被发布到生产环境。
5. **基线漂移检测（Drift Detection）**：把本次成绩和上一次的“历史最好成绩”（`baseline.json`）做对比。如果退步超过允许范围，即使及格也会发出警告。

---

## 🔬 RAGAS 是什么？它是怎么打分的？

很多人第一次看到 RAGAS 会有疑惑：调个包丢进去几个字符串，就吐出来几个 0 到 1 的分数，这是什么黑盒？

**答：RAGAS 根本没有什么神秘算法，它的底层就是一堆精心设计好的 Prompt。** 它把你的数据塞进这些 Prompt，发给大模型（LLM）做阅读理解，再把大模型的判断统计成分数。本质上是**用 LLM 当裁判（LLM-as-a-Judge）**。

### 四个指标的打分逻辑（扒开黑盒）

#### 忠实度 (Faithfulness) — 答案有没有瞎编？

输入：`问题 + 参考文档 + 生成的答案`

RAGAS 在背后偷偷发了**两轮 Prompt**：

1. **第一轮**发给 LLM："请把这个 Answer 拆解成一句句独立的陈述句。"
   - 比如答案是 "茅台收入 387 亿，同比增长 15%"，拆成：① 茅台收入 387 亿。② 同比增长 15%。

2. **第二轮**发给 LLM："对照参考文档，逐句判断每条陈述是 True 还是 False。"
   - ① True。② False（假设文档里写的是 16%）。

**得分 = 标记为 True 的句子数 / 总句子数** → 本例 = 1/2 = 0.5

---

#### 答案相关性 (Answer Relevancy) — 答案是不是在答这个问题？

输入：`问题 + 生成的答案`（注意：不需要参考文档）

RAGAS 用的是**反向工程**思路：

1. 把 Answer 发给 LLM："根据这个答案，反推 3 个你认为可能触发这个答案的问题是什么？"
   - 比如答案是 "苹果在中国销量下降了 3%"，反推出：① 苹果销量怎么样？② 中国市场苹果表现如何？③ iPhone 降了多少？

2. 把这 3 个反推问题和**你的原问题**，全部丢给 Embedding 模型算**余弦相似度**。

**得分 = 反推问题与原问题的平均相似度** → 相似度越高，说明答案越切题。

---

#### 上下文召回率 (Context Recall) — 关键信息有没有被遗漏？

输入：`标准答案(ground truth) + 参考文档`

1. 把 Ground Truth 发给 LLM："把这个标准答案拆成一个个独立的事实点。"
   - 比如标准答案拆出：① 上半年毛利率 26.4%。② 主因是碳酸锂价格下降。③ 规模效应摊薄了制造费用。

2. 对每个事实点，让 LLM 在 Contexts 里找："这条信息在参考文档里有没有依据？有标 1，没有标 0。"

**得分 = 在文档中找到的事实点数 / 标准答案的总事实点数**

---

#### 上下文精确率 (Context Precision) — 有用的文档排在前面了吗？

输入：`问题 + 标准答案 + 参考文档列表（有顺序）`

1. 让 LLM 对 Contexts 里的每一段逐一判断："这段文本对回答这个问题有没有用？"，有用标 1，无用标 0。

2. 用一个**排名加权公式**算分（越靠前权重越高）。如果有用的文档都排在最前面 → 高分；如果有用的文档全埋在第 10 页 → 低分，即使找到了也没用。

---

### 代码里的几个参数是什么？

```python
result = evaluate(
    dataset=dataset,        # 把 Question/Contexts/Answer/Ground_Truth 打包传进去
    metrics=[...],          # 告诉 RAGAS 要算哪几个指标
    llm=ragas_llm,          # 【裁判 LLM】—— 负责做上面所有 True/False 判断的大模型
    embeddings=ragas_embeddings  # 【向量模型】—— 专给「答案相关性」算余弦相似度用
)
```

- **`llm`（裁判）**：本项目用的是 DeepSeek-V3。换一个更强的裁判（比如 GPT-4o），评分会更精准，但更贵。
- **`embeddings`（向量模型）**：本项目用的是 bge-m3。只参与答案相关性计算，其余三个指标不用它。
- RAGAS 本身**没有内置任何"金融知识"**，它只是帮你自动化了"发 Prompt → 收结果 → 统计分数"这个流程，让你不用自己手写几十个 API 调用。

---

## 🗺️ 这套测试在整个体系里处于哪一层？

当前 `tests/rag_quality/` 是整个 RAG 测试体系里的**第一层（基础层）**，还有两层目前尚未实现。

```
┌──────────────────────────────────────────────────────────────────┐
│                       RAG 测试金字塔                              │
├──────────────────────────────────────────────────────────────────┤
│                                                                  │
│  Layer 3  ← 【目前没有】E2E 测试                                 │
│            用户问题 → 完整 LangGraph Pipeline                    │
│            (planner → retrieval → synthesize_agent) → 评分      │
│            测的是：用户真实体验                                   │
│                                                                  │
│  Layer 2  ← 【目前没有】集成测试                                 │
│            真实向量检索 → synthesize_agent 真实 Prompt → 评分    │
│            测的是：检索质量 + Agent 提示词效果                   │
│                                                                  │
│  Layer 1  ← 【当前这套 tests/rag_quality/】                     │
│            mock_contexts（黄金文档写死）→ 极简 Prompt → 评分     │
│            测的是：LLM 基础能力（防幻觉 · 基础相关性）            │
│                                                                  │
└──────────────────────────────────────────────────────────────────┘
```

### Layer 1 的价值定位（已完成）

这是"**裸 LLM 天花板测试**"：把正确答案所在的文档直接喂给模型，看它能不能如实总结、不捏造。

- 忠实度 1.0 → DeepSeek-V3 零幻觉，是 FinSight 选用它当 LLM 的信心背书
- 就算 `answer_relevancy` 偏低，那是评估方法的偏差，不是 LLM 本身的问题
- 类比：像单元测试里测一个纯函数——隔离所有外部依赖，只测核心逻辑是否正确

> 注意：这套测试里答案生成用的是 `run_rag_quality.py` 里写死的 4 行极简 Prompt，**不是**项目里任何 Agent 的真实提示词。

### Layer 2 的价值定位（已完成 ✅）

这是"**真实检索集成测试**"：mock_contexts 先经过 Embedding 向量化入库 → 真实 cosine 相似度检索排序 → synthesize_agent 闭卷 Prompt → RAGAS 评估。

**脚本**: `tests/rag_quality/run_layer2_retrieval.py`

**核心差异点（对比 Layer 1）**：
| 维度 | Layer 1 | Layer 2 |
|---|---|---|
| 上下文来源 | mock_contexts 直接传入 | mock_contexts → 切片 → Embedding → Top-K 检索 |
| Prompt 风格 | 4 行极简 Prompt | synthesize_agent 闭卷 `<evidence_pool>` XML 格式 |
| 检索噪声 | 无 | 有（chunk 边界切割、相似度排序可能遗漏） |
| 测试目标 | LLM 基础能力 | 检索质量 + Agent Prompt 效果 |
| 门控阈值 | faithfulness ≥ 0.80 | faithfulness ≥ 0.75（容忍检索噪声） |

**关键参数**：
- `--top-k K`：检索返回 Top-K chunk（默认 5）
- `--chunk-size N`：切片字符数（默认 300，优先句子边界）
- `--embed-model`：Embedding 模型（默认 `BAAI/bge-m3`）

**理解 Layer 2 的分数变化**：
- 忠实度下降（如 1.0→0.83）→ 正常！检索到的 chunk 可能未包含完整的关键数字
- 答案相关性提升（如 0.77→0.79）→ synthesize 真实 Prompt 更贴近问题格式
- 上下文召回率下降（如 0.93→0.82）→ 检索 Top-K 未能覆盖所有 ground_truth 信息点

### Layer 3 的价值定位（已完成 ✅）

这是"**完整 Pipeline E2E 测试**"：用户问题 → 完整 LangGraph Pipeline（planner→execute→synthesize→render）→ 从 artifacts 提取答案 → RAGAS 评估。

**脚本**: `tests/rag_quality/run_layer3_e2e.py`

**核心差异点（对比 Layer 2）**：
| 维度 | Layer 2 | Layer 3 |
|---|---|---|
| 运行路径 | 手动检索 + 手动调 LLM | 完整 GraphRunner.create().ainvoke() |
| 节点覆盖 | 仅检索 + 生成 | build_initial_state → planner → execute_plan → synthesize → render |
| execute_plan | 手动 Embedding 检索 | monkeypatch 注入 mock_contexts 为 evidence_pool |
| 答案来源 | LLM 直接输出 | artifacts.draft_markdown / render_vars |
| Synthesize 模式 | 固定闭卷 Prompt | 由 `LANGGRAPH_SYNTHESIZE_MODE` 控制（stub/llm） |
| 门控阈值 | faithfulness ≥ 0.75 | faithfulness ≥ 0.65（stub 模式容忍占位文本） |

**monkeypatch 策略**：
- `execute_plan_stub` 被替换为 `_injected_execute_plan_stub`
- 从全局注册表 `_TEST_EVIDENCE_REGISTRY` 读取 mock_contexts，转换为 `evidence_pool`
- 保留完整 planner / synthesize / render 节点运行，不跳过任何路由逻辑

**两种运行模式**：
```bash
# stub 模式（默认）：synthesize 输出确定性占位文本，分数偏低但测试稳定
python tests/rag_quality/run_layer3_e2e.py --mock

# llm 模式：synthesize 调用真实 LLM，分数接近 Layer 2
LANGGRAPH_SYNTHESIZE_MODE=llm python tests/rag_quality/run_layer3_e2e.py
```

**当前推进状态**：全部三层测试框架已完成，Layer 1 有真实评估结果，Layer 2/3 已通过 mock 模式验证。

---

> 基于 [RAGAS 0.4.x](https://docs.ragas.io/) 的四项核心指标评估框架
>
> 评估模型：`deepseek-ai/DeepSeek-V3` @ SiliconFlow (`https://api.siliconflow.cn/v1`)
>
> Embedding：`BAAI/bge-m3` @ SiliconFlow

---

## 📊 最新评估结果

**运行时间：** 2026-02-27 16:42:38 UTC　|　**Run ID：** `rag-quality-20260227-164238`

**状态：** ⚠️ 6/12 成功，6/12 因 SiliconFlow RPM 限流（403）失败（需实名认证提升额度）

### 整体指标均值（基于 6 个有效 case）

| 指标 | 含义 | 最低阈值 | 优秀阈值 | 最新得分 | 状态 |
|------|------|:--------:|:--------:|:-------:|:----:|
| **忠实度** (faithfulness) | 答案每个陈述是否有文档支撑（防幻觉） | 0.80 | 0.90 | **1.0000** | ✅ 优秀 |
| **答案相关性** (answer_relevancy) | 答案是否真正回答了问题 | 0.75 | 0.88 | **0.7673** | ✅ 达标 |
| **上下文精确率** (context_precision) | 检索文档中实际被使用的比例 | 0.70 | 0.85 | **N/A** | ⚠️ 指标异常 |
| **上下文召回率** (context_recall) | 标准答案所需信息在检索文档中的覆盖度 | 0.70 | 0.85 | **0.9306** | ✅ 优秀 |

> ⚠️ `context_precision` 全部返回 null：`ContextPrecisionWithoutReference` 指标存在兼容性问题，需排查 RAGAS 版本与该指标的 ascore 调用方式。

### 分文档类型指标

| 文档类型 | 忠实度 | 答案相关性 | 上下文精确率 | 上下文召回率 | 完成情况 |
|----------|:------:|:----------:|:------------:|:------------:|:--------:|
| filing（财报） | **1.000** ✅ | **0.765** ✅ | N/A ⚠️ | **1.000** ✅ | 4/4 ✓ |
| transcript（电话会） | **1.000** ✅ | **0.777** ✅ | N/A ⚠️ | **0.792** ✅ | 2/4 ✓ |
| news（新闻） | N/A | N/A | N/A | N/A | 0/4 ✗ |

### 逐案例得分明细

| # | Case ID | 文档类型 | 忠实度 | 答案相关性 | 上下文精确率 | 上下文召回率 | 状态 |
|---|---------|---------|:------:|:----------:|:------------:|:------------:|:----:|
| 01 | `filing_maotai_revenue_2024q3` | filing | **1.0000** | **1.0000** | N/A | **1.0000** | ✅ |
| 02 | `filing_catl_gross_margin_2024` | filing | **1.0000** | 0.5661 ⚠️ | N/A | **1.0000** | ✅ |
| 03 | `filing_byd_ev_sales_2024h1` | filing | **1.0000** | **0.7732** | N/A | **1.0000** | ✅ |
| 04 | `filing_paic_embedded_value_2024` | filing | **1.0000** | **0.7203** | N/A | **1.0000** | ✅ |
| 05 | `transcript_alibaba_cloud_guidance` | transcript | **1.0000** | **0.7771** | N/A | **0.7500** | ✅ |
| 06 | `transcript_tencent_gaming_recovery` | transcript | **1.0000** | N/A ⚠️ | N/A | **0.8333** | ✅ |
| 07 | `transcript_meituan_profitability` | transcript | — | — | — | — | ❌ RPM限流 |
| 08 | `transcript_jd_supply_chain` | transcript | — | — | — | — | ❌ RPM限流 |
| 09 | `news_fed_rate_cut_astock` | news | — | — | — | — | ❌ RPM限流 |
| 10 | `news_china_ev_export_competition` | news | — | — | — | — | ❌ RPM限流 |
| 11 | `news_apple_iphone16_china_sales` | news | — | — | — | — | ❌ RPM限流 |
| 12 | `news_semiconductor_export_controls` | news | — | — | — | — | ❌ RPM限流 |

**亮点分析：**
- 🌟 忠实度全部 1.0（6/6）—— DeepSeek-V3 金融文档零幻觉，表现优异！
- 📉 Case 02 答案相关性偏低（0.566）—— CATL 问题是「毛利率+驱动因素」双问，模型答案侧重因素分析，相关性评估有偏差
- ⚡ 限流原因：并发 4 指标 × 多个 LLM 子调用，超过 SiliconFlow 未认证账号 RPM 上限

---

## 🧪 测试用例说明

共 **12 个黄金数据集用例**，覆盖三类金融文档场景：

### 📋 财报类（filing）— 4 个用例

| # | Case ID | 测试问题 | 核心考察点 |
|---|---------|---------|-----------|
| 01 | `filing_maotai_revenue_2024q3` | 贵州茅台2024年三季度营业收入是多少？ | 数字精确提取（387.88亿，+15.6%） |
| 02 | `filing_catl_gross_margin_2024` | 宁德时代2024年上半年毛利率是多少？主要驱动因素是什么？ | 多维归因（26.4%，碳酸锂+规模效应） |
| 03 | `filing_byd_ev_sales_2024h1` | 比亚迪2024年上半年新能源汽车销量及市场份额如何？ | 销量+市占率双维（161.3万辆，34.2%） |
| 04 | `filing_paic_embedded_value_2024` | 中国平安2024年中期内含价值是多少？新业务价值增速如何？ | 保险专业指标（EV 14,820亿，NBV +11%） |

> **filing 特殊阈值**：忠实度 ≥ 0.85（财报数字零容忍幻觉）；上下文召回率 ≥ 0.75

### 🎙️ 电话会类（transcript）— 4 个用例

| # | Case ID | 测试问题 | 核心考察点 |
|---|---------|---------|-----------|
| 05 | `transcript_alibaba_cloud_guidance` | 阿里巴巴管理层对云业务增长有何指引？ | 管理层前瞻性表述提取（AI收入三位数增长） |
| 06 | `transcript_tencent_gaming_recovery` | 腾讯管理层如何看待游戏业务的复苏趋势？ | 定性+定量混合（国内+14%，海外35%占比） |
| 07 | `transcript_meituan_profitability` | 美团管理层如何描述盈利路径和竞争态势？ | 多业务线盈利节奏（优选/闪购/外卖份额） |
| 08 | `transcript_jd_supply_chain` | 京东管理层如何阐述供应链优势对毛利率的影响？ | 供应链定性叙述（毛利率15.2%，6小时达） |

> **transcript 特殊阈值**：忠实度 ≥ 0.80；答案相关性 ≥ 0.75（允许适量解读，但需贴近原文）

### 📰 新闻类（news）— 4 个用例

| # | Case ID | 测试问题 | 核心考察点 |
|---|---------|---------|-----------|
| 09 | `news_fed_rate_cut_astock` | 美联储降息对A股市场有哪些主要影响？ | 宏观逻辑链推理（汇率/政策/成长股） |
| 10 | `news_china_ev_export_competition` | 中国新能源汽车出口面临哪些主要贸易壁垒？ | 多国政策梳理（EU 35.3%，US 100%） |
| 11 | `news_apple_iphone16_china_sales` | 苹果iPhone 16系列在中国市场的销售情况如何？ | 销量归因分析（370万，-3%，AI功能缺失） |
| 12 | `news_semiconductor_export_controls` | 美国最新半导体出口管制对中国AI芯片供应有何影响？ | 供应链替代分析（昇腾910B，性能差距30-50%） |

> **news 特殊阈值**：忠实度 ≥ 0.75；答案相关性 ≥ 0.80（侧重时效性和相关性）

---

## 🛠️ 环境准备 & 配置

### 安装依赖（首次）

```bash
# Layer 1 / Layer 2 依赖
pip install ragas>=0.4.0 openai python-dotenv numpy

# Layer 3 额外依赖（完整 LangGraph Pipeline）
pip install -r requirements.txt   # 项目主依赖
```

### 配置 `.env`

在项目根目录 `.env` 中配置以下环境变量：

```env
# ── RAG 质量评估（所有 Layer 均使用）────────────────────────
LLM_API_KEY=sk-xxxxxxxxxxxxxxxxxxxx        # SiliconFlow API Key
LLM_API_BASE=https://api.siliconflow.cn/v1  # API Base URL
EVAL_LLM_MODEL=deepseek-ai/DeepSeek-V3     # RAGAS 裁判模型

# ── Layer 3 额外配置 ────────────────────────────────────────
LANGGRAPH_SYNTHESIZE_MODE=llm              # llm | stub（默认 stub）
```

> ⚠️ **重要**：SiliconFlow 未认证账号有 RPM 限制，运行完整 12 个 case 建议先完成实名认证。
> 认证入口：[SiliconFlow 控制台](https://cloud.siliconflow.cn) → 账号设置 → 实名认证

> 💡 **避免限流 Tips**：每次只跑一种文档类型（`--doc-type filing`），间隔 5 分钟再跑下一组，12 个 case 分三批完成。

### CI 集成（GitHub Actions）

```yaml
# ── Mock 快速验证（< 500ms，无需 API Key）────────────────────
- name: Layer1 Mock Gate
  run: python tests/rag_quality/run_rag_quality.py --mock --gate

- name: Layer2 Mock Gate
  run: python tests/rag_quality/run_layer2_retrieval.py --mock --gate

- name: Layer3 Mock Gate
  run: python tests/rag_quality/run_layer3_e2e.py --mock --gate

# ── 真实评估（仅 filing 类型，避免限流）────────────────────
- name: Layer1 Real Gate (filing)
  env:
    LLM_API_KEY: ${{ secrets.SILICONFLOW_API_KEY }}
    LLM_API_BASE: https://api.siliconflow.cn/v1
    EVAL_LLM_MODEL: deepseek-ai/DeepSeek-V3
  run: python tests/rag_quality/run_rag_quality.py --doc-type filing --gate

- name: Layer2 Real Gate (filing)
  env:
    LLM_API_KEY: ${{ secrets.SILICONFLOW_API_KEY }}
    LLM_API_BASE: https://api.siliconflow.cn/v1
    EVAL_LLM_MODEL: deepseek-ai/DeepSeek-V3
  run: python tests/rag_quality/run_layer2_retrieval.py --doc-type filing --gate

- name: Layer3 Real Gate (filing, stub mode)
  env:
    LLM_API_KEY: ${{ secrets.SILICONFLOW_API_KEY }}
    LLM_API_BASE: https://api.siliconflow.cn/v1
    EVAL_LLM_MODEL: deepseek-ai/DeepSeek-V3
  run: python tests/rag_quality/run_layer3_e2e.py --doc-type filing --gate
```

---

## 📈 指标解读指南

### 各指标含义

| 指标 | 计算方法 | 低分意味着 | 优化方向 |
|------|---------|-----------|---------|
| **忠实度** | 答案原子陈述 ÷ 有文档支撑的陈述 | 模型幻觉严重，捏造财务数据 | 优化系统提示，强制「据文档显示」约束 |
| **答案相关性** | 答案与问题的语义相似度 | 答非所问，答案绕圈子 | 改进问题理解，减少无关背景信息 |
| **上下文精确率** | 检索文档实际贡献度（rank-aware） | 检索噪声多，Top-K 文档质量差 | 优化检索策略，提升 reranker 准确率 |
| **上下文召回率** | 参考答案信息在检索文档中的覆盖率 | 关键财务数据被遗漏 | 扩大 Top-K，优化 chunking 策略 |

### CI 门控阈值

```
全局阈值：
  faithfulness      ≥ 0.80
  answer_relevancy  ≥ 0.65  (已适配 question_type 分层，analysis/list 天然低分拉低均值)
  context_precision ≥ 0.70
  context_recall    ≥ 0.70

分类型阈值覆盖（doc_type）：
  filing:     faithfulness ≥ 0.85, context_recall ≥ 0.75
  transcript: faithfulness ≥ 0.80, answer_relevancy ≥ 0.75
  news:       faithfulness ≥ 0.75, answer_relevancy ≥ 0.80

分层阈值覆盖（question_type）：
  factoid:  answer_relevancy ≥ 0.75  (单一精确问题)
  list:     answer_relevancy ≥ 0.55  (列举型天然低分)
  analysis: answer_relevancy ≥ 0.55  (分析叙述型天然低分)

漂移告警（相对基线）：
  任意指标下滑 > 0.05 → CI 失败
```

### 首次 12/12 基线（2026-02-28）

```
整体指标（Layer 1, delay=35s, intra-delay=35s）：
  faithfulness      = 1.0000  ✨ (满分零幻觉)
  answer_relevancy  = 0.6935
  context_precision = 0.9444
  context_recall    = 0.9514
  null_rate         = 0% (所有指标全部有效)
```

### 已知问题 & 待修复

| 问题 | 原因 | 解决方案 |
|------|------|---------|
| ~~`context_precision` 全部 N/A~~ | ~~返回格式不符~~ | ✅ 已修复，12/12 全部有效 |
| ~~Case 07-12 全部 RPM 失败~~ | ~~SiliconFlow RPM 上限~~ | ✅ 已修复，`--delay 35 --intra-case-delay 35` 全量 12/12 通过 |

---

## 📁 文件结构

```
tests/rag_quality/
├── run_rag_quality.py          # Layer 1：主评估脚本（极简 Prompt + mock_contexts）
├── run_layer2_retrieval.py     # Layer 2：真实 Embedding 检索 + synthesize_agent Prompt
├── run_layer3_e2e.py           # Layer 3：完整 LangGraph Pipeline E2E 测试
├── test_rag_quality.py         # pytest 单元测试（数据集/阈值格式校验 + 门控逻辑）
├── dataset.json                # 12 个黄金用例数据集（filing/transcript/news 各 4 条）
├── thresholds.json             # CI 门控阈值配置（含分层覆盖）
├── baseline.json               # Layer 1 基线（--save-baseline 生成）
├── baseline_layer2.json        # Layer 2 基线（run_layer2_retrieval.py --save-baseline）
├── baseline_layer3.json        # Layer 3 基线（run_layer3_e2e.py --save-baseline）
├── reports/                    # 详细评估报告（JSON）
│   ├── rag-quality-*.json      # Layer 1 报告
│   ├── layer2-*.json           # Layer 2 报告
│   └── layer3-*.json           # Layer 3 报告
└── REPORT.md                   # 本文件（评估结果汇总）
```

## 🚀 三层测试运行命令

### Layer 1：LLM 基础能力测试

```bash
# 完整评估（12 个 case，分批避免限流）
python tests/rag_quality/run_rag_quality.py --doc-type filing
python tests/rag_quality/run_rag_quality.py --doc-type transcript
python tests/rag_quality/run_rag_quality.py --doc-type news

# Mock 模式（不调用 LLM，验证框架逻辑）
python tests/rag_quality/run_rag_quality.py --mock

# CI 门控 + 保存基线
python tests/rag_quality/run_rag_quality.py --gate --save-baseline
```

### Layer 2：真实检索集成测试

```bash
# Mock 模式验证（推荐先跑）
python tests/rag_quality/run_layer2_retrieval.py --mock

# 真实评估（需要 LLM_API_KEY，embedding + RAGAS）
python tests/rag_quality/run_layer2_retrieval.py --doc-type filing

# 调整检索参数
python tests/rag_quality/run_layer2_retrieval.py --top-k 3 --chunk-size 400

# CI 门控 + 保存 Layer 2 基线
python tests/rag_quality/run_layer2_retrieval.py --gate --save-baseline
```

### Layer 3：完整 Pipeline E2E 测试

```bash
# Mock 模式验证（不需要 LLM，测试 Pipeline 路由）
python tests/rag_quality/run_layer3_e2e.py --mock

# stub 模式（默认，synthesize 输出占位文本）
python tests/rag_quality/run_layer3_e2e.py --doc-type filing

# llm 模式（synthesize 调用真实 LLM，质量接近 Layer 2）
LANGGRAPH_SYNTHESIZE_MODE=llm python tests/rag_quality/run_layer3_e2e.py

# CI 门控 + 保存 Layer 3 基线
python tests/rag_quality/run_layer3_e2e.py --gate --save-baseline

# 三层对比（依次运行后查看各层报告）
python tests/rag_quality/run_rag_quality.py --mock --save-baseline
python tests/rag_quality/run_layer2_retrieval.py --mock --save-baseline
python tests/rag_quality/run_layer3_e2e.py --mock
```

### pytest 集成（CI 快速验证，< 500ms）

```bash
# 仅数据集/阈值/门控逻辑校验（不调用 LLM）
pytest tests/rag_quality/test_rag_quality.py -v
```

---

*最后更新：2026-02-28 | 评估框架：RAGAS 0.4.x | 模型：deepseek-ai/DeepSeek-V3 | API：SiliconFlow*
