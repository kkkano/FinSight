# FinSight 全面重构与新功能总纲（Master Spec）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**基线 commit:** `4a1c05507468fdf3db07d002911a1123e6471a30`
**仓库根:** 本文件所在仓库（FinSight）。所有相对路径以仓库根为准。
**日期:** 2026-07-03

**Goal:** 在不中断线上服务的前提下，修复已确认的 bug 与安全隐患、重建 LangGraph 编排层的单一意图源与 agent 通信机制、拆解六个巨型文件、收口配置与前后端契约、引入多用户隔离，并交付 8 个新功能。

**Architecture:** 分 7 个工作包（WP0-WP6）串行推进；WP0/WP1 是无争议速赢，WP2 重设计编排层（意图/计划/执行/通信），WP3 纯机械拆分巨型文件（零行为变更、以金样快照守护），WP4 配置与契约工程化，WP5 多用户，WP6 新功能。每个 WP 是独立可测试、可交付的计划文件。

**Tech Stack:** Python 3.11 / FastAPI / LangGraph 1.0.7 / Pydantic v2 / SQLite(+PostgreSQL checkpointer)；React 19 / Vite 6 / TypeScript 5 / Zustand 5 / ECharts 5 / axios / Supabase JS。

---

## Global Constraints（每个 WP 的每个任务都隐含遵守）

- **绝不执行 `git commit` / `git push` 以外主人未批准的 git 操作**；每个任务末尾的 commit 步骤须以约定式提交格式书写（feat/fix/refactor/test/chore/perf）。
- Python 代码风格与现有代码一致：中文 docstring/注释可用；类型注解必须完整；禁止裸 `except:`；新增 `except Exception` 必须至少 `logger.debug` 留痕。
- 前端遵守不可变更新（禁止直接 mutate state）；新文件 ≤400 行、既有文件不因新增内容超过 800 行（超了先拆）。
- 所有新增/修改行为必须先写失败测试（TDD），后端 `pytest`、前端 `pnpm test:unit`（以 `frontend/package.json` 的 `test:unit` script 为准）。
- 每个任务保持"独立可回滚"：一个任务 = 一次 commit。
- 环境变量新增时必须同步登记到 `.env.server.example`（带注释与默认值）。
- 禁止引入新的重量级依赖，允许清单见各 WP 的 Global Constraints。
- 运行后端测试命令统一为：`python -m pytest <path> -x -q`（Windows Git Bash 下同样成立）。
- **行为冻结原则**：标注 `[MECHANICAL]` 的任务不允许任何行为变更，验收 = 全量测试绿 + 金样快照零 diff（见 WP3 Task 0）。

---

## 工作包索引与依赖

| WP | 文件 | 内容 | 依赖 | 预估 |
|----|------|------|------|------|
| WP0 | `01-wp0-quick-wins.md` | 速赢：真 bug、虚假隐私声明、安全端口、超时、鉴权头 | 无 | 1-2 天 |
| WP1 | `02-wp1-frontend-hotpath.md` | 前端流式热路径性能 + 滚动/反馈体验 | 无 | 2-3 天 |
| WP2 | `03-wp2-orchestration-redesign.md` | 编排层重设计：IntentFrame 单一意图源、DAG 执行、AgentBrief 与证据黑板、多问题分节 | WP0 | 1.5-2 周 |
| WP3 | `04-wp3-god-file-split.md` | 六个巨型文件机械拆分 + `*_stub` 改名 | WP2（建议）| 1-2 周 |
| WP4 | `05-wp4-config-and-contract.md` | pydantic-settings 收口、llm_config 去硬编码、OpenAPI→TS codegen、client.ts 拆分、useChatStream | WP0 | 1 周 |
| WP5 | `06-wp5-multiuser.md` | Supabase JWT 后端校验、业务数据 user_id 隔离、每用户成本护栏 | WP0 | 1 周 |
| WP6 | `07-wp6-features.md` | 新功能：A股数据源、watchlist、报告分享、SSE 断点续传、PWA、组合归因、报告→回测 | WP2/WP4/WP5 部分 | 按功能独立 |
| 08 | `08-frontend-redesign.md` | 前端视觉与交互彻底重构（TERMINAL 设计语言）：token/组件规范/对话去气泡/真实步进器/三层过程可视化/图表主题/导航/欢迎页归一 | 建议在 WP1 后 | 1-2 周 |
| 09 | `09-feature-linkage-audit.md` | 功能联动与摆设审计：图表真实性治理（inline=LLM 编造数据的根治）、八条联动打通、12 件摆设处置、工作台"今日驾驶舱"信息架构 | 08 的 SourceBadge；部分依赖 WP6 F2 | 1-1.5 周 |
| 10 | `10-agent-native.md` | Agent 原生化：团队协作协议（lead/质询/委托）、身份系统（档案/观点记忆/战绩）、感知层（评分器与 agent 人格合一、tab 驻场分析师、全链路署名） | Part 1 依赖 WP2；Part 2/3 可并行 | 1.5-2 周 |

执行顺序建议：WP0 → WP1 → 08(Task1-3 可先行) → WP2 → WP3 → WP4 → WP5 → WP6 → 08(剩余) → 09 → 10。WP1 与 WP0 可并行；08 是纯表现层，可与后端 WP 并行推进（同文件冲突时逻辑 WP 先行）；10 的 Task 1/5/6/7（档案/记忆/战绩/人格合一）不依赖 WP2，可提前。

---

## 问题登记册（Issue Registry）

每个问题有唯一 ID，spec 任务通过 ID 回链。严重度：P0=损害正确性/信任/安全，P1=显著质量/维护性问题，P2=改进项。

### 编排层（ORC，详见 WP2 开头的诊断报告）

| ID | 严重度 | 位置 | 问题 | 解决于 |
|----|--------|------|------|--------|
| ORC-01 | P0 | `backend/graph/nodes/understand_request.py` 全文 | 同一意图存在 5 套并行表示：`understanding`、`understanding.v2`、`intent_contract`（3 模式）、`request_frame(s)`、`reply_contract`，无单一事实源 | WP2 T1-T4 |
| ORC-02 | P0 | `understand_request.py:2463-3234` | LLM router（`route_conversation`）的决策被 40+ 处关键词 if 瀑布围攻：规则可推翻/绕过 LLM，主函数有 ≥6 个早退 return，路由不可预测 | WP2 T3 |
| ORC-03 | P0 | `backend/graph/adapters/agent_adapter.py:392` | agent 仅收到 `(query, ticker)` 两个参数——会话历史、intent、前组产出全部丢失，每个 agent 从裸文本重新猜意图 | WP2 T6 |
| ORC-04 | P0 | `backend/graph/executor.py:52-93,629-635` | 步骤只有 `parallel_group`（连续块=串行组），无 `depends_on` DAG；组间无任何数据流动，"组1→组2→组3"只是排队不是依赖 | WP2 T5 |
| ORC-05 | P1 | `executor.py:296-321` | 唯一的跨步骤数据流是 `run_python_compute` 的 `step:` 引用注入；agent 之间通信为零，仅靠 `synthesize` 事后合并 | WP2 T6-T7 |
| ORC-06 | P1 | `backend/graph/nodes/research_debate.py:16` | "多空辩论"默认关闭（`DEBATE_GRAPH_ENABLED=false`），且为确定性规则拼装，非 agent 交互 | WP2 T7（纳入黑板后评估开启） |
| ORC-07 | P1 | `backend/graph/runner.py:118-132` + `understand_request.py:38-40` | 图拓扑说谎：`resolve_subject/clarify/parse_operation` 注册在图里但主路径不走；`understand_request` 内部直接调用其他节点函数 | WP2 T8 |
| ORC-08 | P1 | `backend/graph/nodes/planner.py` + `planner_stub.py` | 双 planner（LLM + 2440 行规则函数）互为 AB/fallback，选择逻辑 `_should_use_task_graph_planner` 又是一坨关键词/操作名集合判断 | WP2 T9 归并判据；WP3 拆文件 |
| ORC-09 | P2 | `understand_request.py`（priority=8/10/20/24/25/26/30/35/40/80）| task priority 魔法数字无命名语义 | WP2 T4 |
| ORC-10 | P2 | `understand_request.py:3332` | `understanding.confidence` 硬编码 0.78/0.42 | WP2 T4 |
| ORC-11 | P1 | 多问题 query 渲染 | `tasks[]`/`task_ids` 贯穿到 `task_results`，但 chat 渲染不保证按任务分节，次要任务淹没主问题 | WP2 T10 |
| ORC-12 | P1 | `understand_request.py:68-191` vs `conversation_router.py:200-376` | 同一套意图关键词两份实现已漂移 | WP2 T2 |

### 后端（BE）

| ID | 严重度 | 位置 | 问题 | 解决于 |
|----|--------|------|------|--------|
| BE-01 | P0 | `backend/tools/price.py:543-553` | `p1/p2` 在 `if price_num:` 内赋值、f-string 在 if 外使用 → 数据源文本无 `$数字` 时 `UnboundLocalError` 被外层 except 吞掉，成功源被当失败丢弃 | WP0 T1 |
| BE-02 | P1 | `price.py:529-556` | 11 源串行级联 + 源间 `time.sleep(0.5)`；循环内 `import re` | WP0 T1（sleep/import）；并行化列 WP6 F2 备注 |
| BE-03 | P1 | 全后端 | 736 处宽泛 `except Exception`、其中 ~83 处裸 `pass` 吞错 | WP3 各拆分任务顺带治理 + 全局规则 |
| BE-04 | P1 | `backend/agents/*.py` | 4 个 agent 重复定义 `__init__/_get_tool_registry/_format_output`，基类抽象被架空 | WP2 T6（签名统一时收编） |
| BE-05 | P1 | 19 个文件 34 份 `_env_*` 重复 + 160 处散装 `os.getenv` | 配置碎片化，无启动期校验 | WP4 T1-T2 |
| BE-06 | P0 | `backend/llm_config.py:110-111` | 硬编码第三方默认端点 `token-plan-cn.xiaomimimo.com` | WP4 T3 |
| BE-07 | P1 | `backend/services/rebalance_engine.py:23` | services 反向依赖 api 层 schema | WP3 T7 |
| BE-08 | P1 | `backend/api/main.py`（1356 行）| God module：装配+调度器+内联端点混杂；`asyncio` 重复 import（第3、9行）| WP0 T6（import）；WP3 T6（拆分） |
| BE-09 | P2 | `backend/data/*.sqlite.pre_migration.bak` | 备份文件混入仓库 | WP0 T7 |
| BE-10 | P2 | `price.py` `_last_fetch_info` 模块级 dict | 无上限缓慢泄漏 | WP0 T1 |
| BE-11 | P1 | 8 文件 39 处直接 `sqlite3`，无 Repository/迁移机制 | 数据层各自为政 | WP5 T2（引入最小 Repository + 迁移助手） |
| BE-12 | P2 | `agents_router.py` vs `agent_router.py`；`api/conversation_router.py` vs `graph/nodes/conversation_router.py` | 命名冲突 | WP3 T8 |

### 前端（FE）

| ID | 严重度 | 位置 | 问题 | 解决于 |
|----|--------|------|------|--------|
| FE-01 | P0 | `frontend/src/store/useStore.ts:662-685` | 流式每 token 全量 JSON.stringify 100 条消息写 localStorage | WP1 T1 |
| FE-02 | P0 | `frontend/src/components/ChatList.tsx:361-365` | 每 token 强制滚底，无法回看 | WP1 T2 |
| FE-03 | P1 | `ChatList.tsx` 消息列表 | 无 memo/虚拟化，流式全列表重渲染；`parseSmartChartBlocks` 每 token 全文正则 | WP1 T3-T4 |
| FE-04 | P1 | `frontend/src/api/client.ts:290-296` | 全局唯一超时 800000ms（注释写 120s）、无重试 | WP0 T4 |
| FE-05 | P0 | `client.ts:1228-1334` | 三个流式 fetch 不带 Authorization | WP0 T5 |
| FE-06 | P1 | `client.ts:1492` | `response.clone()` 导致整流缓冲 | WP0 T5 |
| FE-07 | P1 | `useStore.ts`（35 字段）+ `ChatInput.tsx:278-302` 整包解构 | 上帝 store、无 selector | WP1 T5（热点 selector 化；store 全面切片属 YAGNI，暂不做，见 WP6 末尾清单） |
| FE-08 | P1 | `ChatInput.tsx:22-135` vs `ChatList.tsx:16-144` | ~130 行 ticker/图表逻辑复制且漂移 | WP4 T6 |
| FE-09 | P1 | `ChatInput.tsx:371-913` `handleSend` 543 行 + 两套假进度体系 | 巨型函数 | WP4 T7（useChatStream） |
| FE-10 | P1 | `ChatList.tsx:404-407` | Retry 走非流式管线、丢 sessionId | WP4 T7 |
| FE-11 | P2 | `client.ts` 手写 60+ 端点、15 个 `Promise<any>` | 契约漂移 | WP4 T4-T5 |
| FE-12 | P2 | 25+ 数据 hook 手写 loading/error | 无服务端状态库 | WP4 T8 |

### 体验（UX）

| ID | 严重度 | 位置 | 问题 | 解决于 |
|----|--------|------|------|--------|
| UX-01 | P0 | `frontend/src/components/SettingsModal.tsx:855` | 隐私声明与事实相反（声称 key 只存本地，实际 POST 到服务端） | WP0 T3 |
| UX-02 | P1 | `SettingsModal.tsx` handleSave | 保存失败只有 console.error，无 UI 反馈 | WP0 T3 |
| UX-03 | P1 | `ChatInput.tsx:612-708` | 文字流完还要同步等图表检测才落定 | WP1 T6 |
| UX-04 | P1 | `ChatInput.tsx:1027` | 生成期间输入框 disabled | WP1 T7 |
| UX-05 | P1 | `client.ts:1262-1278` + ChatInput | 8s 无事件合成 `synthetic_done` 伪装完成 | WP6 F5（续传后改为明示提醒） |
| UX-06 | P2 | `ChatList.tsx:718-757` | 复制无反馈；删除会话无确认 | WP1 T8 |
| UX-07 | P2 | 全局 | 中英文文案硬编码混杂 | WP4 T9（locales/zh.ts 常量表） |
| UX-08 | P2 | 流式状态区 | 无 aria-live/progressbar 语义 | WP1 T2 顺带 |
| UX-09 | P1 | SSE 断线 | 无自动重连/续传 | WP6 F5 |

### 安全（SEC）

| ID | 严重度 | 位置 | 问题 | 解决于 |
|----|--------|------|------|--------|
| SEC-01 | P0 | portfolio/conversation/monitor 全链路 | 零用户隔离，公网所有访客共享数据 | WP5 全部 |
| SEC-02 | P1 | `backend/api/main.py:1083` | `API_AUTH_ENABLED` 默认 false，烧钱端点匿名可用仅靠 IP 限流 | WP5 T4（每用户配额）+ 部署文档 |
| SEC-03 | P1 | `docker-compose.yml:79-80` | 8000 端口绑 0.0.0.0，绕过 Cloudflare | WP0 T8 |
| SEC-04 | P2 | volume 内 `user_config.json` | LLM key 明文落盘 | WP4 T3 备注（加密为后续项，不在本 spec 范围） |
| SEC-05 | P2 | `backend/services/release_drills.py:246` | `subprocess.run` 需确保无 HTTP 可达路径 | WP0 T9（加运行时断言） |

---

## 全局验收门禁（每个 WP 完成时全部执行）

```bash
# 1. 后端全量测试
python -m pytest backend/tests -x -q
# 2. 前端测试 + 构建
cd frontend && pnpm test:unit && pnpm build && cd ..
# 3. 金样快照（WP3 Task 0 建立后适用）
python -m pytest tests/golden -x -q
# 4. 启动冒烟（两终端或 docker compose）
python -m uvicorn backend.api.main:app --port 8000  # /health 返回 200
```

## 术语表

- **意图（intent）**：用户 query 被解析后的结构化表示；重构后统一为 `IntentFrame`。
- **任务（task）**：意图分解出的独立研究单元（`IntentTask`），一个多问题 query 产生多个 task。
- **计划（PlanIR）**：task 编译成的可执行步骤列表（tool/agent step）。
- **组/依赖**：旧机制 `parallel_group`（连续块并发）；新机制 `depends_on`（DAG）。
- **AgentBrief**：agent 收到的完整任务简报（取代裸 `(query, ticker)`）。
- **证据黑板（evidence digest bus）**：执行期共享的 agent 产出摘要，供后续 agent 读取。
- **金样快照（golden snapshot）**：LLM 关闭状态下确定性管线对固定 query 集的输出快照，机械重构的零 diff 守护。
