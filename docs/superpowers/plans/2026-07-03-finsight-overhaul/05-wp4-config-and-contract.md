# WP4 配置收口与前后端契约工程化 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 后端：环境变量读取收口（消灭 19 文件 34 份 `_env_*` 重复）、`llm_config` 去第三方硬编码端点。前端：OpenAPI→TS 类型自动生成、`client.ts` 按域拆分、`sendMessageStream` 改对象参数、抽 `useChatStream`、ticker/图表工具函数归一、文案常量表。

**Architecture:** 后端两步走（先统一 env helper，再引入 typed Settings）；前端以"OpenAPI 快照文件"为契约桥（后端测试导出 openapi.json → 前端 codegen → CI diff 守护），避免 CI 里起服务。

**Tech Stack:** pydantic-settings（已随 pydantic v2 生态可用，若未安装需批准加依赖 `pydantic-settings==2.*`）；前端 devDependencies：`openapi-typescript@^7`（需主人批准）。`@tanstack/react-query` 列为可选任务。

## Global Constraints

- 新依赖仅限上述三项，且每项使用前在任务里再次确认 `package.json`/`requirements.txt` 中不存在等价物。
- env 变量语义与默认值**不许变**——本 WP 是搬运不是调参。

---

### Task 1: 统一 env helper（BE-05 第一步）

**Files:**
- Create: `backend/utils/env.py`
- Modify: 19 个含 `_env_*` 定义的文件（`grep -rln "def _env_int\|def _env_bool\|def _env_str\|def _env_float" backend --include="*.py"`）
- Test: `backend/tests/test_env_helpers.py`

**Interfaces:**

```python
# backend/utils/env.py
def env_str(key: str, default: str = "") -> str
def env_int(key: str, default: int) -> int          # 解析失败返回 default（与现存实现一致）
def env_float(key: str, default: float) -> float
def env_bool(key: str, default: bool = False) -> bool  # {"1","true","yes","on"} → True
def env_csv(key: str, default: str = "") -> list[str]
```

- [x] **Step 1: 写测试**（覆盖：正常/缺失/解析失败/bool 真值表/csv 去空白）。
- [x] **Step 2: 实现**（语义以 `backend/graph/nodes/planner.py:28-47` 版本为准——它是最常见变体；迁移前 diff 各文件变体，发现语义不同的变体（如 min/max 钳制版）保留原地不动并在 notes 登记）。
- [x] **Step 3: 逐文件替换**：删除本地 `_env_*` 定义，`from backend.utils.env import env_int as _env_int`（别名保持模块内旧调用名，行数改动最小）。一文件一验证。
- [x] **Step 4: 守护**：`grep -rn "def _env_int\|def _env_bool" backend --include="*.py" | grep -v utils/env.py | wc -l` → 0。全量 + 金样零 diff。
- [x] **Step 5: Commit**（`756ec5f`）

```bash
git commit -am "refactor(config): single env helper module replaces 34 duplicated _env_* definitions"
```

---

### Task 2: typed Settings（BE-05 第二步，范围：planner/executor/agent/security 四域）

**Files:**
- Create: `backend/config/settings.py`
- Modify: `backend/graph/nodes/planner.py`、`backend/graph/executor.py`（+dag_executor）、`backend/graph/adapters/agent_adapter.py`、`backend/api/security_gate.py`（WP3 产物；若 WP3 未做则 main.py 对应段）
- Test: `backend/tests/test_settings.py`

**Interfaces:**

```python
# backend/config/settings.py
from functools import lru_cache
from pydantic_settings import BaseSettings

class PlannerSettings(BaseSettings):
    report_timeout_sec: int = 240        # LANGGRAPH_PLANNER_REPORT_TIMEOUT_SEC
    report_max_tokens: int = 6000
    report_max_attempts: int = 3
    chat_timeout_sec: int = 150
    chat_max_tokens: int = 3000
    chat_max_attempts: int = 2
    ab_enabled: bool = False             # LANGGRAPH_PLANNER_AB_ENABLED
    ab_split: int = 50
    model_config = {"env_prefix": "LANGGRAPH_PLANNER_", "extra": "ignore"}
    # 字段名 ↔ 旧 env 名的映射用 validation_alias 精确对齐，逐个变量核对，禁止靠猜

class ExecutorSettings(BaseSettings): ...   # LIVE_TOOLS / HEARTBEAT / INVOKER_TIMEOUT / RETRY_ATTEMPTS
class AgentSettings(BaseSettings): ...      # AGENT_LLM_ANALYZE_* / BASE_AGENT_*
class SecuritySettings(BaseSettings): ...   # API_AUTH_* / TRUST_PROXY_HEADERS / RATE_LIMIT_*

@lru_cache
def planner_settings() -> PlannerSettings: return PlannerSettings()
# executor_settings/agent_settings/security_settings 同型；测试用 cache_clear() 重置
```

- [x] **Step 1:** 为四域各写一个"env 覆盖生效 + 默认值正确"的测试（monkeypatch env → cache_clear → 断言字段）。
- [x] **Step 2:** 实现四个 Settings 类：**先 grep 收集该域全部 os.getenv/env_* 调用点及其默认值列成表**（写入 notes-settings-map.md），逐一映射为字段；调用点改为 `planner_settings().report_timeout_sec` 形式。
- [x] **Step 3:** 全量 + 金样零 diff（金样 conftest 里 monkeypatch 的 env 变量在 Settings 化后仍必须生效——测试里加 `cache_clear` 钩子到 `deterministic_env` fixture）。
- [x] **Step 4: Commit**（`94e48ee`）

```bash
git commit -am "feat(config): typed pydantic-settings for planner/executor/agent/security domains"
```

---

### Task 3: llm_config 去硬编码端点（BE-06）

**Files:**
- Modify: `backend/llm_config.py:110-111` 及消费处
- Modify: `.env.server.example`、`README.md` / `README_CN.md`（快速开始注明必填）
- Test: `backend/tests/test_llm_config_requires_endpoint.py`

- [ ] **Step 1: 写失败测试**

```python
import pytest


def test_create_llm_fails_loudly_without_endpoint(monkeypatch):
    for key in ("OPENAI_COMPATIBLE_API_BASE", "OPENAI_COMPATIBLE_API_KEY", "OPENAI_COMPATIBLE_MODEL"):
        monkeypatch.delenv(key, raising=False)
    from backend import llm_config
    with pytest.raises(RuntimeError, match="OPENAI_COMPATIBLE_API_BASE"):
        llm_config.create_llm()
```

- [ ] **Step 2: 实现**：删除 `DEFAULT_OPENAI_COMPATIBLE_API_BASE/MODEL` 两个硬编码常量；`create_llm`（及 EndpointManager 初始化）在 base/model 均缺失时抛：

```python
raise RuntimeError(
    "LLM endpoint not configured: set OPENAI_COMPATIBLE_API_BASE / OPENAI_COMPATIBLE_MODEL "
    "(and OPENAI_COMPATIBLE_API_KEY) in .env.server — see .env.server.example"
)
```

注意排查所有引用点：`grep -rn "DEFAULT_OPENAI_COMPATIBLE" backend`。`.env.server.example` 给出示例值（占位符 `https://your-llm-endpoint/v1`，**不写任何真实商业端点**）。
- [ ] **Step 3:** 全量测试（凡依赖隐式默认端点的测试改为显式 monkeypatch env）。
- [ ] **Step 4: Commit**

```bash
git commit -am "fix(llm-config): remove hardcoded third-party default endpoint; fail loudly with setup guidance"
```

---

### Task 4: OpenAPI 快照桥（FE-11 第一步）

**Files:**
- Create: `backend/tests/test_openapi_snapshot.py`、`frontend/src/api/openapi.snapshot.json`（生成物，入库）
- Modify: `frontend/package.json`（scripts + devDependency `openapi-typescript`）
- Create: `frontend/src/api/schema.d.ts`（生成物，入库）

- [ ] **Step 1: 后端导出快照**

```python
# backend/tests/test_openapi_snapshot.py
import json
from pathlib import Path

SNAPSHOT = Path("frontend/src/api/openapi.snapshot.json")


def test_openapi_snapshot_is_current():
    from backend.api.main import app
    current = json.dumps(app.openapi(), ensure_ascii=False, indent=2, sort_keys=True)
    if not SNAPSHOT.exists():
        SNAPSHOT.write_text(current, encoding="utf-8")
        return
    assert SNAPSHOT.read_text(encoding="utf-8") == current, (
        "OpenAPI drift: 后端 schema 变了。跑 `python -m pytest backend/tests/test_openapi_snapshot.py` 前"
        "删除快照重新生成，并在前端执行 `pnpm gen:api` 同步类型，两个生成物一起提交。"
    )
```

- [ ] **Step 2: 前端 codegen**：`pnpm add -D openapi-typescript`（**先获主人批准**）；`package.json` scripts 加：

```json
"gen:api": "openapi-typescript src/api/openapi.snapshot.json -o src/api/schema.d.ts"
```

跑一次生成 `schema.d.ts` 入库。
- [ ] **Step 3: CI 守护**：`.github/workflows` 现有 CI 里（`grep -rn "pytest" .github/workflows`）确认该测试被全量套覆盖；前端 job 加一步 `pnpm gen:api && git diff --exit-code src/api/schema.d.ts`。
- [ ] **Step 4: Commit**

```bash
git commit -am "feat(contract): openapi snapshot bridge + generated TS schema with CI drift guard"
```

---

### Task 5: client.ts 按域拆分 + any 消灭（FE-11 第二步）

**Files:**
- Create: `frontend/src/api/http.ts`（axios 实例 + 拦截器 + buildAuthHeaders 从 client.ts 迁入）、`frontend/src/api/sse.ts`（`parseSSEStream` + withStreamGuards）、`frontend/src/api/domains/{chat,reports,portfolio,monitor,dashboard,market,screener,backtest,config,system,rag}.ts`
- Modify: `frontend/src/api/client.ts` → 兼容出口：`export const apiClient = { ...chatApi, ...reportsApi, … }`（旧调用点零改动）

**Steps:**
- [ ] Step 1: 迁移地图：`grep -n "  [a-zA-Z]*(" frontend/src/api/client.ts` 给 60+ 方法分域，写 `notes-client-map.md`。
- [ ] Step 2: 一域一 commit 剪切；方法签名不变；**返回 `Promise<any>` 的 15 个方法**（`grep -n "Promise<any>" client.ts` 列清单）改用 `schema.d.ts` 生成类型：`import type { paths } from "../schema"; type ConfigResponse = paths["/api/config"]["get"]["responses"]["200"]["content"]["application/json"]`。
- [ ] Step 3: `withStreamGuards`（FE 报告 A4 的 idle-done 重复逻辑）在 `sse.ts` 实现一份：

```ts
export interface SSECallbacks { onEvent?; onThinking?; onDone?; onError?; /* …与 executeAgent 现有对象风格一致 */ }
export function withStreamGuards(cb: SSECallbacks, opts: { idleDoneMs?: number } = {}): SSECallbacks {
  let sawDone = false, sawError = false
  let idleTimer: ReturnType<typeof setTimeout> | null = null
  // 逐字搬运 client.ts:1239-1290 的 sawDone/idleDoneTimer 逻辑，包装 onDone/onError/onEvent
  …
}
```

`sendMessageStream` 改签名 `(body: SendMessageBody, callbacks: SSECallbacks, opts?: StreamOpts)`；原 13 位置参数的调用点（ChatInput）同步改写。
- [ ] Step 4: `pnpm test:unit && pnpm build` + 手工冒烟聊天/报告/执行台。
- [ ] Step 5: Commit

```bash
git commit -am "refactor(api-client): domain modules + typed responses + unified stream guards; sendMessageStream object params"
```

---

### Task 6: ticker/图表工具归一（FE-08）

**Files:**
- Modify: `frontend/src/utils/ticker.ts`（已存在——先读它，把 ChatInput/ChatList 双份实现与它三方对比，取语义并集）
- Create: `frontend/src/utils/chartIntent.ts`（`isInlineChartRenderable/shouldGenerateChart/chart marker 注入`，以 ChatInput 版为准，ChatList 版差异点用注释标注并保留其关键词并集）
- Modify: `frontend/src/components/ChatInput.tsx:22-135`、`frontend/src/components/ChatList.tsx:16-144`（删本地副本改 import）
- Test: `frontend/src/utils/chartIntent.test.ts`（正例：`"画一下 AAPL 的k线"`、`"NVDA 趋势图"`；反例：`"介绍下苹果公司"`）

**Steps:** 常规四步（测试→实现→替换→验证），Commit：

```bash
git commit -am "refactor(frontend): single-source ticker & chart-intent utils, kill 130-line drift between ChatInput/ChatList"
```

---

### Task 7: useChatStream 抽取（FE-09/FE-10）

**Files:**
- Create: `frontend/src/hooks/useChatStream.ts`
- Modify: `frontend/src/components/ChatInput.tsx`（handleSend 543 行 → 组件内 <80 行）、`frontend/src/components/ChatList.tsx:404`（Retry 改走同一 hook）

**Interfaces:**

```ts
export interface UseChatStreamResult {
  send: (text: string, opts?: { agentsOverride?: string[] }) => Promise<void>
  retry: (messageId: string) => Promise<void>   // 复用原消息的 query/context，同一管线
  stop: () => void
}
export function useChatStream(sessionId: string): UseChatStreamResult
// 内部：模糊查询拦截 → ticker 提取(utils/ticker) → 历史构建 → sendMessageStream(SSECallbacks)
//       → store 桥接（消息增改/executionStore 事件/flushPersist）→ 图表异步补挂(WP1 T6 的 injectChartsIfAny 迁入)
//       → 报告回捞(recoverReportIfAvailable)
// 进度估算：删除 ChatInput 的 estimateProgress/mapStageToSource 硬编码，进度一律读 executionStore
```

**Steps:**
- [ ] Step 1: hook 骨架 + 把 handleSend 逻辑分七块注释锚点逐块搬运（每块搬完 `pnpm test:unit` 一次）。
- [ ] Step 2: Retry 切换：`ChatList` 的 `handleRetry` 改为 `chatStream.retry(message.id)`（带 sessionId、带 history，修复 FE-10）。
- [ ] Step 3: 删除 ChatInput 内两套假进度中的本地一套（保留 executionStore 的 `PIPELINE_STAGE_BASE_PROGRESS`）。
- [ ] Step 4: 手工冒烟：发送/停止/重试/断流回捞/执行台联动。Commit：

```bash
git commit -am "refactor(chat): useChatStream hook unifies send/retry/stop pipelines; single progress source"
```

---

### Task 8（可选，需批准 `@tanstack/react-query`）: 数据 hooks 收敛（FE-12）

范围：先迁 5 个最热 hook（`useDashboardData/useMarketQuotes/useMorningBrief/useFindings/usePortfolio`——以 `ls frontend/src/hooks` 实际为准）为 `useQuery` 包装；`QueryClientProvider` 挂 App 根；staleTime 默认 30s、行情类 5s。其余 20 个 hook 留待后续按需迁移。**未批准依赖前跳过。**

---

### Task 9: 中文文案常量表（UX-07 第一步）

**Files:**
- Create: `frontend/src/locales/zh.ts`
- Modify: `ChatInput.tsx`（placeholder"Ask anything…"类）、`ChatList.tsx`（"Streaming response..."）、`executionStore.ts`（"Execution completed"/"准备执行..."）、`useStore.ts`（"已停止生成…"）

**Interfaces:**

```ts
// locales/zh.ts —— 纯常量对象，不上 i18n 框架（YAGNI）
export const zh = {
  chat: {
    inputPlaceholder: "问点什么，比如：AAPL 现在多少钱 / 给我一份 NVDA 投资分析",
    streaming: "正在生成回答…",
    stopped: "已停止生成（结果已保留）",
    copied: "已复制",
  },
  execution: {
    preparing: "准备执行…",
    running: "执行中…",
    completed: "执行完成",
    recovered: "已回捞完整报告",
  },
} as const
```

**Steps:** grep 上述四文件中全部用户可见硬编码串 → 挪入常量表 → 引用替换 → `pnpm test:unit`（涉及断言文案的测试同步改）→ Commit：

```bash
git commit -am "refactor(i18n): user-facing copy centralized in locales/zh.ts, mixed-language strings unified to Chinese"
```

---

## WP4 完成门禁

- [ ] `python -m pytest backend/tests tests/golden -x -q` 全绿（含 openapi 快照测试）
- [ ] `cd frontend && pnpm gen:api && git diff --exit-code src/api/schema.d.ts && pnpm test:unit && pnpm build`
- [ ] `grep -rn "def _env_int" backend --include="*.py" | grep -v utils/env.py` → 空
- [ ] `grep -n "Promise<any>" frontend/src/api` → 0 处
- [ ] 手工冒烟：聊天全链路 + 设置保存 + 仪表盘
