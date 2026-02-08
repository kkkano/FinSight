# FinSight Issue Tracker

> Auto-generated from comprehensive project audit.
> Check off items as they are resolved.

---

## P0 — CRITICAL

### Security

- [x] **LLM retry 卡死**: `ainvoke_with_rate_limit_retry` 对同一 endpoint 重试 200 次 × 310s = 17.4h
  - Fix: `llm_factory` 注入式 endpoint 轮询, 默认值 6 次 × 5s
  - Files: `backend/services/llm_retry.py`, `backend/graph/nodes/planner.py`, `backend/graph/nodes/synthesize.py`

- [x] **`_normalize_api_base` 破坏完整代理 URL**: 强制剥离 `/chat/completions` 并追加 `/v1`
  - Fix: `raw_url: bool` 字段, `raw=True` 时保留原始 URL
  - Files: `backend/llm_config.py`

- [x] **Config endpoint 任意写入**: `POST /api/config` 允许覆盖 `user_config.json` 任意字段, 可重定向 LLM 流量
  - Fix: `_CONFIG_ALLOWED_KEYS` 白名单 + `_filter_allowed_keys()` 过滤
  - File: `backend/api/config_router.py`

- [x] **Config endpoint 泄露 API Key**: `GET /api/config` 返回明文 API key, 无 redaction
  - Fix: `_redact_config()` 递归 mask 敏感字段
  - File: `backend/api/config_router.py`

- [x] **7 个新 Router 无鉴权**: `security_gate` 中间件已在 `main.py` app 级别挂载, 覆盖所有路由
  - Note: `API_AUTH_ENABLED=false` 为默认值, 生产部署必须开启
  - File: `backend/api/main.py:538-559`

### Bugs

- [x] **编码损坏 — docs/06**: 已清除 9 个 PUA (Private Use Area) 无效字符
  - File: `docs/06_LANGGRAPH_REFACTOR_GUIDE.md`

- [x] **编码损坏 — ChatInput Selection Pill**: 已修复 6 行乱码中文
  - File: `frontend/src/components/ChatInput.tsx`

- [x] **编码损坏 — client.ts 注释**: 已修复全部 30+ 行乱码注释为正确中文
  - File: `frontend/src/api/client.ts`

### Architecture

- [x] **暗色模式 hover 不可见**: `--fin-hover: #1e293b` 与 `--fin-card: #1e293b` 相同
  - Fix: 修改为 `#283548`
  - File: `frontend/src/index.css`

---

## P1 — HIGH

### Security

- [ ] **Path traversal 风险**: 多个 endpoint 接受用户输入的文件名/路径, 未做路径清理
  - Files: `backend/api/report_router.py`, `backend/api/system_router.py`

- [x] **Auth/Rate-limit 默认关闭**: `.env.example` 已添加 PRODUCTION 警告注释
  - File: `.env.example` — 生产部署必须开启 `API_AUTH_ENABLED=true`

### Frontend — Design System

- [x] **NavItem 硬编码 `bg-blue-50`**: Sidebar 激活态使用非 design token 颜色
  - Fix: 替换为 `bg-fin-primary/10`
  - File: `frontend/src/components/Sidebar.tsx:343`

- [x] **无共享 UI 组件**: 按钮/卡片/徽章/输入框全部内联 Tailwind class
  - Fix: 创建 `frontend/src/components/ui/` (Button/Card/Badge/Input)

- [x] **`text-[10px]` 字体过小**: 91 处使用 10px 字体, 不适合金融产品
  - Fix: 定义 `text-2xs: 11px` token, 全局替换
  - Files: 15 个组件文件 + `tailwind.config.js`

- [x] **border-radius 不统一**: `rounded-lg` (52处) vs `rounded-xl` (55处) 混用
  - Fix: 卡片级 `rounded-xl`, 内部元素 `rounded-lg`, 已全局规范化
  - Files: 多个组件文件

- [x] **几乎零 ARIA 属性**: 整个 components/ 仅 NewsFeed 1 处有 aria 标注
  - Fix: 按钮 aria-label, 导航 aria-current, 侧边栏 role="navigation" 等已补充
  - Files: `Sidebar.tsx`, `WorkspaceShell.tsx`, `ChatInput.tsx` 等

### Frontend — Code Quality

- [x] **AgentLogPanel.tsx 过大 (961行)**: 已拆分为 5 个子文件
  - Fix: `frontend/src/components/agent-log/` (Toolbar/EventRow/Export/StatusBar/Container)

- [x] **ReportView.tsx 过大 (1643行)**: 已拆分为 6 个子文件
  - Fix: `frontend/src/components/report/` (Header/Section/AgentCard/Charts/Utils/Container)

- [ ] **ThinkingProcess.tsx 过大 (501行)**: 大量渲染辅助函数可抽取

- [x] **App.css Vite 模板残留**: 43 行全部未使用 CSS
  - Fix: 已清空
  - File: `frontend/src/App.css`

### Backend — Architecture

- [x] **GraphState 弱类型**: 新增 Policy/PlanIR/Artifacts/Trace TypedDict 替换裸 dict
  - File: `backend/graph/state.py`

- [x] **report_builder 静态填充**: `min_chars` 从 2000 降至 800，减少模板填充
  - File: `backend/graph/report_builder.py`

- [x] **硬编码比较结论**: 已替换为动态 ticker 感知的比较视角文本
  - File: `backend/graph/nodes/synthesize.py:562`

### Documentation

- [ ] **docs/06 混合职责**: 1584 行文件同时包含设计规范、TODO 列表、工作日志
  - 应拆分为: 设计规范 + 变更日志 + 待办清单

- [x] **DOCS_INDEX 断链**: 已验证所有文档链接均可访问
  - File: `docs/DOCS_INDEX.md`

---

## P2 — MEDIUM

### Frontend

- [x] **消息不持久化**: 已添加 localStorage 持久化（最近 100 条，streaming 完成时写入）
  - File: `frontend/src/store/useStore.ts`

- [x] **`updateLastMessage` 直接 mutation**: 已改为 immutable map + spread
  - File: `frontend/src/store/useStore.ts`

- [ ] **响应式断点不统一**: CSS 使用 768/1024/1280px, JS `useIsMobileLayout` 仅 1024px
  - 需要: 统一断点策略

- [x] **移动端 Sidebar 无抽屉**: 已改为 fixed drawer + backdrop overlay 模式
  - Files: `frontend/src/components/Sidebar.tsx`, `frontend/src/components/layout/WorkspaceShell.tsx`

### Backend

- [ ] **dry_run 模式无 UX 提示**: 默认 `LANGGRAPH_EXECUTE_LIVE_TOOLS=false`, 用户看不到提示
  - 需要: 前端 banner 或 trace 标记

- [ ] **新闻降级无通知**: news_agent 全部数据源失败时静默降级
  - 需要: 前端显示 "部分数据不可用" 提示

### Documentation

- [x] **无 CONTRIBUTING.md**: 已创建完整贡献者指南
  - File: `CONTRIBUTING.md`
- [x] **无 CHANGELOG.md**: 已创建变更日志 (v0.8.0 + v1.0.0)
  - File: `CHANGELOG.md`
- [x] **readme_cn.md 滞后**: 已与 readme.md 同步, 补充 Runtime Flags 等新增内容
  - File: `readme_cn.md`

---

## Legend

- `[x]` = 已完成
- `[ ]` = 待处理
- File references are relative to project root
