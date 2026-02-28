# AGENTS - tests/rag_qualityV2

本目录是 RAG 质量评估 V2 框架，定位为与 `tests/rag_quality` 并行的增强评估体系。  
V2 聚焦 claim/keypoint 级别归因评估，不反向依赖 V1 代码，仅复用 V1 数据集文件。

## 目录结构

```text
tests/rag_qualityV2/
├── __init__.py
├── AGENTS.md
├── REPORT.md
├── clients_v2.py
├── engine_v2.py
├── prompts_v2.py
├── run_layer1_v2.py
├── run_layer2_v2.py
├── run_layer3_v2.py
├── types_v2.py
├── thresholds_v2.json
├── baseline_layer1_v2.json
├── baseline_layer2_v2.json
├── baseline_layer3_v2.json
├── conftest.py
├── test_metrics_v2.py
├── test_gate_v2.py
├── test_engine_v2.py
├── test_cli_v2.py
└── reports/
    └── .gitkeep
```

## 文件职责（一句话）

1. `types_v2.py`：定义 V2 报告、case 结果、gate/drift 结构体。
2. `prompts_v2.py`：集中管理 answer/claim/keypoint/judge 的结构化提示词。
3. `clients_v2.py`：封装 Grok Chat 与 SiliconFlow Embedding 的 OpenAI 兼容客户端。
4. `engine_v2.py`：实现检索、claim/keypoint 判定、指标计算、门控与漂移检查。
5. `run_layer1_v2.py`：Layer1 执行入口（mock_contexts 直评）。
6. `run_layer2_v2.py`：Layer2 执行入口（chunk + embedding 检索后评估）。
7. `run_layer3_v2.py`：Layer3 执行入口（完整 pipeline 输出后评估）。
8. `thresholds_v2.json`：V2 全局与分层阈值、漂移阈值配置。
9. `baseline_layer*_v2.json`：三层基线文件。
10. `REPORT.md`：V2 使用说明、指标定义、故障排查、CI 命令。
11. `conftest.py`：pytest 夹具（复用 V1 dataset + 加载 V2 阈值）。
12. `test_metrics_v2.py`：指标公式边界测试。
13. `test_gate_v2.py`：门控与漂移规则测试。
14. `test_engine_v2.py`：引擎核心流程测试（fake client）。
15. `test_cli_v2.py`：三个 runner 的 mock gate 冒烟测试。

## 依赖边界

1. 允许依赖：`tests/rag_quality/dataset.json`（数据输入）。
2. 禁止依赖：`tests/rag_quality/*` 的运行脚本逻辑（避免耦合与回归联动）。
3. 外部服务：
   - Chat/Judge：Grok 兼容接口（默认）
   - Embedding：SiliconFlow embeddings（默认）

## 数据流

1. runner 读取 dataset/thresholds
2. runner 生成答案或调用 pipeline
3. `engine_v2.evaluate_case_v2` 做 claim/keypoint 评估
4. `engine_v2.build_eval_report_v2` 聚合报告
5. `engine_v2.check_gates_v2` + `check_drift_v2` 执行门控
6. 输出 report JSON 与可选 baseline

## 开发约束

1. 不在仓库中写入任何明文 API Key。
2. 新增指标必须同步更新：
   - `types_v2.py`
   - `engine_v2.py`
   - `thresholds_v2.json`
   - `REPORT.md`
   - `test_metrics_v2.py` / `test_gate_v2.py`
3. CI 快测必须保持无外部依赖（`--mock --gate` 可通过）。

