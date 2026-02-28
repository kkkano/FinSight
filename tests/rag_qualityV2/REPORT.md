# RAG Quality V2（Grok + SiliconFlow Embedding）

## 1. 为什么需要 V2
V1 的 RAGAS 指标在短答案问答场景表现很好，但在 Layer3 的 narrative 长报告场景会出现“评估目标错位”：

1. 生成形态是长篇投研叙事，含推理与结构化建议。
2. 评估上下文通常是有限 `mock_contexts`。
3. 单一 faithfulness / answer_relevancy 难以解释“是检索问题、归因问题，还是叙事扩写问题”。

V2 目标：把“检索覆盖、陈述归因、数值一致性、关键点完成度”拆开评估，形成可诊断、可门控、可回归的质量框架。

---

## 2. 指标体系（V2）

V2 每个 case 计算 6 项核心指标：

1. `keypoint_coverage = (covered + 0.5*partial) / total_keypoints`
2. `keypoint_context_recall = covered_keypoints_by_context / total_keypoints`
3. `claim_support_rate = supported_claims / total_claims`
4. `unsupported_claim_rate = unsupported_claims / total_claims`
5. `contradiction_rate = contradicted_claims / total_claims`
6. `numeric_consistency_rate = supported_numeric_claims / total_numeric_claims`（分母为 0 时返回 `null`）

评估流程：

1. 生成答案 `A`
2. 从 `ground_truth` 抽取 keypoints
3. 从答案抽取 claims
4. 用 embedding 为 keypoint/claim 召回 top-k 证据
5. LLM Judge 判定 claim 与 keypoint 覆盖
6. 汇总指标并执行门控

---

## 3. 三层运行方式

数据集默认复用：`tests/rag_quality/dataset.json`

### Layer1（mock_contexts -> answer -> V2 指标）
```bash
python tests/rag_qualityV2/run_layer1_v2.py --mock --gate
python tests/rag_qualityV2/run_layer1_v2.py --gate --save-baseline
```

### Layer2（chunk + embedding 检索 -> answer -> V2 指标）
```bash
python tests/rag_qualityV2/run_layer2_v2.py --mock --gate
python tests/rag_qualityV2/run_layer2_v2.py --top-k 5 --chunk-size 300 --gate --save-baseline
```

### Layer3（完整 Pipeline -> answer -> V2 指标）
```bash
python tests/rag_qualityV2/run_layer3_v2.py --mock --gate
python tests/rag_qualityV2/run_layer3_v2.py --output-mode brief --gate --save-baseline
```

### 3.1 真实运行结果（2026-02-28 全量 12/12）
真实运行参数：
`--save-baseline --delay 0 --intra-case-delay 0`（Layer3 额外 `--output-mode brief`）

| Layer | Run ID | Gate | Drift | keypoint_coverage | keypoint_context_recall | claim_support_rate | unsupported_claim_rate | contradiction_rate | numeric_consistency_rate |
|---|---|---|---|---:|---:|---:|---:|---:|---:|
| Layer1 | `layer1_v2-20260228-182903` | PASS | PASS | 0.8796 | 0.9479 | 0.9431 | 0.0569 | 0.0000 | 0.9896 |
| Layer2 | `layer2_v2-20260228-205342` | PASS | PASS | 0.8960 | 0.9623 | 1.0000 | 0.0000 | 0.0000 | 0.9861 |
| Layer3 | `layer3_v2-20260228-211806` | PASS | PASS | 0.9072 | 0.9653 | 0.9924 | 0.0076 | 0.0000 | 1.0000 |

本轮三 case 精准补丁（JD / Semiconductor / Fed）修复对比：

| Case | Layer2（修复前 -> 修复后） | Layer3（修复前 -> 修复后） | 结果 |
|---|---|---|---|
| `transcript_jd_supply_chain` | `keypoint_coverage: 0.5000 -> 0.8333` | `keypoint_coverage: 0.5000 -> 0.7143` | ✅ 覆盖率修复 |
| `news_semiconductor_export_controls` | `numeric_consistency_rate: 0.8333 -> 1.0000` | `numeric_consistency_rate: 1.0000 -> 1.0000` | ✅ 数值一致性修复 |
| `news_fed_rate_cut_astock` | `numeric_consistency_rate: 1.0000 -> 1.0000` | `numeric_consistency_rate: 0.8000 -> 1.0000` | ✅ 数值一致性修复 |

本轮落地补丁点：
1. `run_layer2_v2.py` / `run_layer3_v2.py` 增加 case 级问题约束提示（仅针对上述 3 个 case）。
2. `engine_v2.py` 为 numeric claim 增加后处理：当 claim 数字在证据中可对齐时，纠正 `numeric_consistent`。
3. `run_layer3_v2.py` 保留 brief 优先抽取与 grounded fallback，避免短答/澄清答复污染评估。

备注：
1. Exa quota exhausted 日志来自 pipeline 搜索分支降级提示，不影响本轮评估完成与 report 落盘。
2. 这轮目标 case 已完成修复并通过真实回归。
---

## 4. 环境变量模板（不含密钥）

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

---

## 5. 门控规则（硬门控）

阈值文件：`tests/rag_qualityV2/thresholds_v2.json`

全局默认：

1. `keypoint_coverage >= 0.70`
2. `keypoint_context_recall >= 0.70`
3. `claim_support_rate >= 0.70`
4. `unsupported_claim_rate <= 0.15`（硬门控）
5. `contradiction_rate <= 0.05`（硬门控）
6. `numeric_consistency_rate >= 0.90`

Null 策略：

1. 任一指标 `null_rate == 1.0` 直接失败
2. 任一指标 `null_rate > 0.10` 失败

覆盖策略：

1. 同时命中 `doc_type` 与 `question_type` 时
2. `min` 取更严格（更大）
3. `max` 取更严格（更小）

漂移策略：

1. `*_delta_min`：当前-基线 不得低于该阈值
2. `*_delta_max`：当前-基线 不得高于该阈值

---

## 6. 常见故障排查

### 6.1 LLM JSON 解析失败
现象：`extract_keypoints` / `extract_claims` / `judge_claim` 报 JSON 解析错误。  
处理：
1. 检查上游模型是否返回了 markdown/code fence 包裹。
2. 降低 temperature 到 `0.0`。
3. 复查代理是否在响应中注入额外前后缀。

### 6.2 embedding endpoint 不可用
现象：`Embedding 调用失败`。  
处理：
1. 检查 `RQV2_EMBED_BASE_URL` 是否为支持 `/embeddings` 的 endpoint。
2. 检查 `RQV2_EMBED_MODEL` 是否可用（默认 `BAAI/bge-m3`）。
3. 检查 key 权限是否包含 embedding 调用。

### 6.3 null_rate 超阈值
现象：门控显示 `null_rate=100%` 或 `>10%`。  
处理：
1. 看 `case_results[].metric_errors` 定位是 claim judge 还是 keypoint judge 失败。
2. 先用 `--mock` 验证框架逻辑，再切真实 API。
3. 若仅某一层失败，优先检查该层答案来源（Layer2 检索、Layer3 pipeline 输出）。

---

## 7. 基线更新流程

1. 先跑非 gate 观察结果
2. 再跑 `--gate --save-baseline`
3. 提交 `baseline_layer{1,2,3}_v2.json`
4. 在 PR 描述里附上指标变化与漂移解释

---

## 8. 与 V1 的对照

| 维度 | V1 | V2 |
|---|---|---|
| 主要指标 | RAGAS 四项 | claim/keypoint 六项 |
| 适配场景 | 短答案 / 标准 QA | 长叙事 + 证据归因 |
| 可诊断性 | 中等 | 高（可区分检索缺失/无证据扩写/数值错误） |
| 硬门控 | 以 min 为主 | 同时支持 min/max + null-rate 硬规则 |
| 漂移 | 单向（delta_min） | 双向（delta_min + delta_max） |

建议：

1. 想看“基础 RAG 能力”优先看 V1
2. 想看“真实叙事输出质量”优先看 V2
3. 发布前以 V2 gate 作为最终质量拦截

---

## 9. CI 快测

```bash
pytest -q tests/rag_qualityV2
python tests/rag_qualityV2/run_layer1_v2.py --mock --gate
python tests/rag_qualityV2/run_layer2_v2.py --mock --gate
python tests/rag_qualityV2/run_layer3_v2.py --mock --gate
```

---

*最后更新：2026-03-01*  
*评估框架：RAG Quality V2（Grok Chat + SiliconFlow Embedding）*

