# RAG 评估指南

更新时间：2026-07-16

生产 RAG 为 PostgreSQL + pgvector、BGE-M3 1024 维。评估分为检索质量、生成质量、隔离/安全和运行稳定性，不能只看单个相似度分数。

## 指标

| 层 | 核心指标 |
|---|---|
| 检索 | Recall@K、Precision@K、MRR、nDCG、空结果率、P95 |
| 生成 | Faithfulness、Answer Relevancy、Context Precision/Recall、Citation Coverage |
| 金融事实 | 数字/日期一致性、as-of 新鲜度、单位/币种正确性、冲突披露 |
| 安全 | user/thread/run 隔离、敏感元数据脱敏、诊断接口认证 |
| 稳定性 | PostgreSQL 故障、模型不可用、受控回退、重复摄取和并发一致性 |

## 评估集要求

评估集应覆盖价格、新闻、财报、宏观、风险、公告/网页、中文/英文、多标的、无答案、冲突来源、过期文档和恶意 scope。每条样本记录 query、期望证据/source id、ground truth（如适用）、时间口径和允许的无答案行为。

禁止用生产秘密或未脱敏用户数据制作 fixture。

## 运行

仓库当前评估入口位于：

- `tests/retrieval_eval/`：检索 gate 与报告；
- `tests/rag_quality/`、`tests/rag_qualityV2/`：生成与质量评估；
- `backend/tests/`：RAG 服务、scope、PostgreSQL 和执行接入测试。

先运行受影响的定向 pytest，再在发布前运行对应 gate。命令以各目录脚本/README 和 CI 为准，不在本文硬编码可能过时的通过数量。

## 判定原则

- 阈值由版本化评估配置/CI 定义；文档不复制一次性跑分作为永久事实。
- 模型、embedding、chunk、reranker、top-k、过滤或 schema 变化必须与上一个生产基线对比。
- 平均分通过但关键金融事实错误、跨用户泄露或 Citation Coverage 不达标，仍判失败。
- 无答案样本应奖励正确拒答/披露，不能逼迫模型猜测。
- 记录模型、数据集版本、commit、配置、耗时和失败样本，确保可复现。

## 变更门禁

- [ ] 摄取/去重/scope 定向测试通过。
- [ ] 1024 维与 pgvector schema 一致。
- [ ] 检索指标未显著回退，关键样本全部通过。
- [ ] 生成忠实度、引用和数字一致性通过。
- [ ] PostgreSQL/embedding/LLM 故障路径行为明确。
- [ ] 受保护的运维查询、日志与评估产物通过 scope 隔离和脱敏检查。
