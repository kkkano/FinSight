# 2026-02-08 Full Audit & Todo Plan（稳定性优先）

## 背景

根据 `PLEASE IMPLEMENT THIS PLAN` 执行请求，按“稳定性优�?+ 生产硬化”完�?P0 阶段落地，并同步文档与门禁�?
## 本次完成

1. 后端安全与会话硬化（P0-1 / P0-2�?   - `backend/api/main.py`
     - CORS 改为 env 驱动：`CORS_ALLOW_ORIGINS`、`CORS_ALLOW_CREDENTIALS`�?     - 公共路径 allowlist 改为 env 驱动：`API_PUBLIC_PATHS`（默认不放行 `/api/dashboard`）�?     - 会话上下文增加回收：`SESSION_CONTEXT_TTL_MINUTES` + `SESSION_CONTEXT_MAX_THREADS`（TTL + LRU）�?   - 安全测试补齐：`backend/tests/test_security_gate_auth_rate_limit.py`�?
2. 前端会话隔离�?API 基址收敛（P0-2 / P0-3�?   - 新增 `frontend/src/config/runtime.ts`：统一读取 `VITE_API_BASE_URL`（默认值兜底）�?   - `frontend/src/api/client.ts` / `frontend/src/hooks/useDashboardData.ts` 改为统一 runtime base�?   - `frontend/src/store/useStore.ts` 首次自动生成并持久化 `public:anonymous:<uuid>`�?   - `frontend/src/pages/Workbench.tsx` 移除固定 fallback `public:anonymous:default`�?
3. Trace 可解释性与前端质量门禁（P0-4 / P0-5 / P0-6�?   - 后端 trace 字段保持可解释输出：`input_state`、`input_sources`、`decision_summary`、`selection_summary`、`status_reason`�?   - 前端日志摘要三段式：动作 / 原因 / 结果（`AgentLogPanel` + `ThinkingProcess`）�?   - 删除 `frontend/src/App.bak.tsx`（历史遗�?lint 噪音源）�?   - `.github/workflows/ci.yml` 增加前置 lint stage，并调整链路�?     - lint -> backend tests -> retrieval unit -> retrieval gate -> frontend build -> e2e -> artifact bundle�?
4. 文档同步（P0-7�?   - `docs/06_LANGGRAPH_REFACTOR_GUIDE.md` 新增 `11.15 稳定性优先整改`，并写入 Worklog 证据行�?   - `docs/11_PRODUCTION_RUNBOOK.md` �?`README.md` 同步新增环境变量与运行策略�?
## 验证结果

- `pytest -q backend/tests/test_security_gate_auth_rate_limit.py backend/tests/test_trace_and_session_security.py`
  - 13 passed
- `npm run lint --prefix frontend`
  - 0 errors, 0 warnings
- `npm run build --prefix frontend`
  - success

## 风险与后�?
1. �澯�����㣨�������տ� hooks �������﷨���⣩��
2. ���谴�ƻ�����ִ��ȫ���ع飺
   - `pytest -q backend/tests`
   - `pytest -q tests/retrieval_eval/test_retrieval_eval_runner.py`
   - `python tests/retrieval_eval/run_retrieval_eval.py --gate`
   - `npm run test:e2e --prefix frontend`

## 结论

本次已完�?P0 核心“上线阻塞项”整改骨架：安全默认、会话隔离、前�?base 统一、lint 门禁前置、文档闭环。可在此基础上继续进�?P1（后端解�?+ dashboard 并发治理 + 排序策略）�?

## 追加收口�?026-02-08，skills + subagent�?
- 使用 skills：`debugging-strategies`、`coding-standards`，并启动独立 subagent 做并行审查�?- subagent 结论：未发现新增阻塞项，仅剩前端 lint 告警需收口�?- 已修复：
  - `frontend/src/components/ChatInput.tsx`：修复乱码导致的语法错误与按�?title 文案�?  - `frontend/src/components/Sidebar.tsx`：`loadUserProfile` / `loadAlertCount` 使用 `useCallback`，修�?hooks 依赖告警�?  - `frontend/src/components/SubscribeModal.tsx`：`loadSubscriptions` 使用 `useCallback`，修�?hooks 依赖告警�?
### 追加验证（全绿）

- `npm run lint --prefix frontend`
  - 0 errors, 0 warnings
- `pytest -q backend/tests`
  - 346 passed, 8 skipped
- `pytest -q tests/retrieval_eval/test_retrieval_eval_runner.py`
  - 6 passed
- `python tests/retrieval_eval/run_retrieval_eval.py --gate`
  - PASS
- `npm run build --prefix frontend`
  - success
- `npm run test:e2e --prefix frontend`
  - 13 passed

### 状�?
- P0 阶段质量门禁已达到“全绿”状态（�?lint �?warning）�?- 可继续进入下一层（P1：后端解�?/ dashboard 并发治理 / 快讯排序策略）�?




---

## P1 执行补录（2026-02-08）

### 1) main.py 拆路由（先做）
- 将 `backend/api/main.py` 从“巨型端点文件”收敛为“应用装配器”：
  - 保留：lifespan、CORS、security gate、中间件、会话/trace辅助函数。
  - 拆出并注册：
    - `backend/api/chat_router.py`
    - `backend/api/user_router.py`
    - `backend/api/system_router.py`
    - `backend/api/market_router.py`
    - `backend/api/subscription_router.py`
    - `backend/api/config_router.py`
    - `backend/api/report_router.py`
  - `main.py` 通过 `create_*_router(...deps...)` 组装，保持现有外部 API 路径不变。
- 兼容性处理：
  - `chat_router` 的 `get_graph_runner` 依赖使用运行时 lambda（`lambda: aget_graph_runner()`），保持测试 monkeypatch 行为不破坏。

### 2) dashboard 并发治理（第二步）
- `backend/api/dashboard_router.py` 引入 `_run_blocking()`：
  - 用 `asyncio.to_thread + wait_for(timeout)` 承载同步 I/O。
  - 默认 timeout：`4.5s`。
  - 失败/超时时写入 `fallback_reasons` 并降级为空结果，而不是阻塞 event loop。
- 覆盖范围：
  - `snapshot`
  - `charts`（并发 gather）
  - `news`

### 3) 快讯排序策略（第三步）
- `backend/dashboard/data_service.py` 重建并清理实现（修复历史编码污染导致的语法风险）。
- 新增排序模型：
  - `ranking_score = time_decay*0.5 + source_reliability*0.3 + impact_score*0.2`
  - 附带字段：`time_decay`、`source_reliability`、`impact_score`、`ranking_score`。
- 保留“双流”输出：
  - 排序流：`market` / `impact`
  - 原始流：`market_raw` / `impact_raw`
  - 解释元信息：`ranking_meta.formula`

### 4) 前端适配 + 轻量美化
- 类型扩展：`frontend/src/types/dashboard.ts`
  - `NewsItem` 增加 ranking 字段。
  - `DashboardData.news` 增加 `market_raw/impact_raw/ranking_meta`。
- 组件改造：
  - `frontend/src/components/dashboard/NewsFeed.tsx`
    - 增加“排序/原始”切换。
    - 展示 `rankingFormula` 与 `ranking_score`。
    - 应用轻量 UI 优化（分隔、hover 层级、按钮交互）。
  - `frontend/src/components/dashboard/DashboardWidgets.tsx`
    - 传入 raw/ranked 数据。
    - 模块纵向间距优化。
  - `frontend/src/pages/Workbench.tsx`
    - 增加“排序/原始”切换。
    - 快讯卡片轻量视觉优化。
  - `frontend/src/components/layout/WorkspaceShell.tsx`
    - 去除 `any[]` 拼接，改为类型安全组合新闻流。

### 5) 验证证据
- `pytest -q backend/tests/test_langgraph_api_stub.py backend/tests/test_streaming_datetime_serialization.py backend/tests/test_report_index_api.py backend/tests/test_security_gate_auth_rate_limit.py`
  - 20 passed
- `pytest -q backend/tests`
  - 346 passed, 8 skipped
- `pytest -q tests/retrieval_eval/test_retrieval_eval_runner.py`
  - 6 passed
- `python tests/retrieval_eval/run_retrieval_eval.py --gate`
  - PASS（Citation Coverage=1.0）
- `npm run lint --prefix frontend`
  - 0 errors, 0 warnings
- `npm run build --prefix frontend`
  - success
- `npm run test:e2e --prefix frontend`
  - 13 passed

### 6) 本轮结论
- 按既定 P1 顺序完成：`main.py 拆路由 -> dashboard 并发治理 -> 快讯排序策略`。
- 现有路由兼容保持，质量门禁全绿，可继续进入后续 P1/P2 子项。

---

## 增量修复（2026-02-08）- Dashboard 默认跳转 GOOGL

### 现象
- 侧边栏点击“仪表盘”后，URL 变为 `/dashboard/GOOGL`，看起来像“默认是谷歌”。

### 根因
- `frontend/src/components/Sidebar.tsx` 里仪表盘跳转 fallback 逻辑原先优先使用 `watchlist[0]`。
- 当前本地用户文件 `data/memory/default_user.json` 的 watchlist 首项就是 `GOOGL`。
- 因此这不是路由硬编码默认值，而是“用户数据驱动的 fallback”。

### 修复
- 将 Sidebar fallback 改为稳定优先级：
  - `currentTicker` -> `portfolio first symbol` -> `AAPL`
- 不再使用 `watchlist[0]` 作为默认跳转来源，避免“默认被历史关注列表劫持”。

### 变更文件
- `frontend/src/components/Sidebar.tsx`

### 验证
- `npm run lint --prefix frontend` 通过
- `npm run build --prefix frontend` 成功

### 影响评估
- 仅影响“点击侧边栏仪表盘按钮”的目标 symbol 选择策略。
- 不影响显式路由（如 `/dashboard/TSLA`）和用户在 Dashboard 内主动切换 symbol。
