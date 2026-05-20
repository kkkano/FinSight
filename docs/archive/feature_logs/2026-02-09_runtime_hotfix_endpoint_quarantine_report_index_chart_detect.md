# 2026-02-09 — Runtime Hotfix: endpoint quarantine + report_index migration + chart detect 404 cleanup

## 背景
- 线上出现“接口 200 但结果异常”现象，同时日志包含：
  - 多 endpoint 连续 403 blocked
  - `report index async upsert failed` (`no such column: source_type`)
  - 前端 `POST /api/chart/detect` 持续 404 噪声
- 目标是先“跑通主链路”，减少无关噪声并恢复稳定结果。

## 本次改动

### 1) 临时下线被封禁 endpoint（先保可用链路）
- 修改 `user_config.json`：
  - `name=2` -> `enabled=false`
  - `name=https://api.freestyle.cc.cd/v1/chat/completions` -> `enabled=false`
- 保留 `legacy-single` 可用端点，避免请求在被封禁端点轮换浪费时间。

### 2) report_index SQLite 迁移修复
- 更新 `scripts/report_index_migrate.py`：
  - 新增确保列：`source_type`、`filing_type`、`publisher`
  - 新增索引：`idx_report_index_source_type`
- 执行迁移：
  - `python scripts/report_index_migrate.py --db backend/data/report_index.sqlite`
  - 输出显示已补齐缺失列并创建备份。

### 3) 清理 `/api/chart/detect` 404 噪声
- 在 `backend/api/market_router.py` 新增 `POST /api/chart/detect`
- 在 `backend/api/main.py` 注入 detector 依赖到 `MarketRouterDeps`
- 前端无需改动，原调用路径直接恢复 200。

### 4) 兼容性修复（避免 INVALID_ARGUMENT 400）
- `backend/llm_config.py:create_llm` 默认 `max_tokens` 从固定高值改为 env 驱动：
  - `LLM_MAX_TOKENS`（默认 `8192`）
- 解决代理端对 `max_tokens=65536` 的参数拒绝问题。

## 验证
- `pytest -q backend/tests/test_report_index_migration_scripts.py backend/tests/test_report_index_api.py backend/tests/test_llm_rotation.py`
  - 结果：`18 passed`
- 接口冒烟：
  - `POST /api/chart/detect` -> `200`（结构化响应）
  - `POST /chat/supervisor` -> `200` 且 `trace.synthesize_runtime.fallback=false`

## 结果
- 报告索引异步入库 schema 报错已清除。
- 图表检测接口 404 噪声已清除。
- LLM 主链路恢复可用，synthesize 不再因参数错误直接 fallback。

## 后续建议
- 对被 quarantine 的 endpoint 做独立健康探测与白名单策略复核，通过后再逐个恢复。
- 将 `LLM_MAX_TOKENS` 暴露到设置页或运行手册，避免环境漂移。
