# WP1 前端流式热路径与交互 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 消灭流式回复期间的三个性能杀手（每 token 全量 localStorage 序列化、强制滚底、全列表重渲染+全文图表正则），并补齐四个高频交互缺陷（图表检测阻塞落定、输入框禁用、复制无反馈、删除无确认）。

**Architecture:** 全部改动集中在 `useStore.ts`、`ChatList.tsx`、`ChatInput.tsx` 三个文件，不改任何 API 契约。性能任务用"计数断言"式单测守护（mock localStorage 统计写入次数）。

**Tech Stack:** React 19 + Zustand 5 + Vitest。

## Global Constraints

- 不引入新依赖（虚拟化库 `virtua` 列为可选任务 T9，需主人单独批准后才装）。
- Zustand 更新保持不可变模式。
- 行号基于基线 `4a1c055`，以 grep 锚点为准。

---

### Task 1: localStorage 持久化去抖（FE-01）

**Files:**
- Modify: `frontend/src/store/useStore.ts`（锚点：`grep -n "persistMessages\|upsertConversationSummary" frontend/src/store/useStore.ts`，基线 662-685 / 506-528）
- Test: `frontend/src/store/persistDebounce.test.ts`（新建）

**Interfaces:**
- Produces: `schedulePersist(sessionId: string): void` 与 `flushPersist(sessionId?: string): void`（模块级，非 store 字段）。
- 约束：`updateMessageInSession` 不再同步调用 `persistMessages`，改调 `schedulePersist`；以下时机必须 `flushPersist`：消息流结束（`isLoading` 置 false 处）、切换会话、删除会话、`beforeunload`。

- [x] **Step 1: 写失败测试**

```ts
// frontend/src/store/persistDebounce.test.ts
import { describe, it, expect, vi, beforeEach } from "vitest"

describe("persist debounce", () => {
  beforeEach(() => {
    vi.useFakeTimers()
    localStorage.clear()
  })

  it("流式期间连续 50 次消息更新最多落盘 1 次，flush 后内容完整", async () => {
    const setItemSpy = vi.spyOn(Storage.prototype, "setItem")
    const { useStore, flushPersist } = await import("./useStore")
    const s = useStore.getState()
    const sessionId = s.createConversation ? s.createConversation() : "test-session"
    // 按实际 action 名调整：grep -n "addMessageToSession\|updateMessageInSession" useStore.ts
    s.addMessageToSession(sessionId, { id: "m1", role: "assistant", content: "", isLoading: true })
    for (let i = 0; i < 50; i++) {
      s.updateMessageInSession(sessionId, "m1", { content: "x".repeat(i) })
    }
    expect(setItemSpy.mock.calls.length).toBeLessThanOrEqual(2) // 首次 add 允许 1 次
    vi.advanceTimersByTime(600)
    flushPersist(sessionId)
    const persisted = JSON.stringify(localStorage)
    expect(persisted).toContain("x".repeat(49))
  })
})
```

（action 名与签名以文件实际为准，测试骨架不变：**断言 50 次更新期间 setItem 调用数 ≤2、flush 后终态在盘上**。）

- [x] **Step 2: 运行确认失败**

Run: `cd frontend && pnpm test:unit -- persistDebounce`
Expected: FAIL（当前每次 update 都 setItem，调用数 ≈100）。

- [x] **Step 3: 实现**

在 `useStore.ts` 顶部（store 定义之外）加：

```ts
const PERSIST_DEBOUNCE_MS = 500
const persistTimers = new Map<string, ReturnType<typeof setTimeout>>()

export function flushPersist(sessionId?: string) {
  const ids = sessionId ? [sessionId] : [...persistTimers.keys()]
  for (const id of ids) {
    const timer = persistTimers.get(id)
    if (timer) clearTimeout(timer)
    persistTimers.delete(id)
    persistMessagesNow(id) // ← 原 persistMessages 逻辑改名为 persistMessagesNow（内容不动）
    upsertConversationSummaryNow(id) // ← 同理改名
  }
}

function schedulePersist(sessionId: string) {
  const existing = persistTimers.get(sessionId)
  if (existing) clearTimeout(existing)
  persistTimers.set(
    sessionId,
    setTimeout(() => {
      persistTimers.delete(sessionId)
      persistMessagesNow(sessionId)
      upsertConversationSummaryNow(sessionId)
    }, PERSIST_DEBOUNCE_MS),
  )
}

if (typeof window !== "undefined") {
  window.addEventListener("beforeunload", () => flushPersist())
}
```

然后：
1. 把原 `persistMessages` / `upsertConversationSummary` 函数体重命名为 `persistMessagesNow` / `upsertConversationSummaryNow`（签名不变）。
2. `grep -n "persistMessages(\|upsertConversationSummary(" frontend/src/store/useStore.ts` 逐处替换调用：
   - `updateMessageInSession` 内 → `schedulePersist(sessionId)`
   - 流结束路径（`grep -n "isLoading: false" useStore.ts` 中消息落定的 action）→ `flushPersist(sessionId)`
   - `deleteConversation` / 切换会话 action → 先 `flushPersist(sessionId)` 再执行原逻辑
   - 其余低频调用点（新建会话等）保持直调 `...Now` 版本。

- [x] **Step 4: 运行确认通过**

Run: `cd frontend && pnpm test:unit -- persistDebounce && pnpm test:unit`
Expected: 新测试 PASS，全量无回归。

- [x] **Step 5: Commit**

```bash
git add frontend/src/store/useStore.ts frontend/src/store/persistDebounce.test.ts
git commit -m "perf(store): debounce localStorage persistence during streaming (was full-serialize per token)"
```

---

### Task 2: 滚动停靠检测 + 回到最新按钮 + aria 语义（FE-02/UX-08）

**Files:**
- Modify: `frontend/src/components/ChatList.tsx`（锚点：`grep -n "scrollTo\|useEffect" frontend/src/components/ChatList.tsx`，基线 361-365）

**Interfaces:**
- Produces: 组件内部状态 `isPinnedRef: RefObject<boolean>`、`showJumpToLatest: boolean`；无对外接口变化。

- [x] **Step 1: 实现停靠检测**

找到现有自动滚底 effect（基线 361-365，形如 `useEffect(() => { ...scrollTo(bottom) }, [messages])`），替换为：

```tsx
const PIN_THRESHOLD_PX = 80
const isPinnedRef = useRef(true)
const [showJumpToLatest, setShowJumpToLatest] = useState(false)

const handleScroll = useCallback(() => {
  const el = scrollContainerRef.current // ← 用现有滚动容器 ref 的名字
  if (!el) return
  const distance = el.scrollHeight - el.scrollTop - el.clientHeight
  const pinned = distance < PIN_THRESHOLD_PX
  isPinnedRef.current = pinned
  setShowJumpToLatest((prev) => (prev === !pinned ? prev : !pinned))
}, [])

useEffect(() => {
  if (!isPinnedRef.current) return
  const el = scrollContainerRef.current
  if (el) el.scrollTo({ top: el.scrollHeight })
}, [messages])

const jumpToLatest = useCallback(() => {
  const el = scrollContainerRef.current
  if (el) el.scrollTo({ top: el.scrollHeight, behavior: "smooth" })
  isPinnedRef.current = true
  setShowJumpToLatest(false)
}, [])
```

滚动容器 JSX 上挂 `onScroll={handleScroll}`；容器内末尾加悬浮按钮（样式沿用项目 Tailwind token）：

```tsx
{showJumpToLatest && (
  <button
    type="button"
    onClick={jumpToLatest}
    aria-label="回到最新消息"
    className="sticky bottom-4 left-1/2 -translate-x-1/2 rounded-full border border-fin-border bg-fin-surface px-3 py-1.5 text-xs shadow-lg"
  >
    ↓ 回到最新
  </button>
)}
```

- [x] **Step 2: aria 语义（UX-08）**

找到流式状态 banner（`grep -n "showExecutionBanner\|执行中\|Streaming" ChatList.tsx`），容器加 `role="status" aria-live="polite"`；进度条 div 加 `role="progressbar" aria-valuenow={progress} aria-valuemin={0} aria-valuemax={100}`。

- [x] **Step 3: 手工验证**

dev 起服务：发一条长回复，流式期间向上滚动 → 不再被拽回底部，出现"↓ 回到最新"；点击按钮回底并恢复跟随。

- [x] **Step 4: Commit**

```bash
git add frontend/src/components/ChatList.tsx
git commit -m "fix(chat): scroll follows only when pinned to bottom; add jump-to-latest; aria-live on streaming status"
```

---

### Task 3: 消息组件 memo 化（FE-03a）

**Files:**
- Modify: `frontend/src/components/ChatList.tsx`（`BubbleMessage` / `FlatMessage` 定义处，`grep -n "BubbleMessage\|FlatMessage" ChatList.tsx`）

- [x] **Step 1:** 两个消息组件用 `React.memo` 包裹，自定义比较器：

```tsx
const areMessagePropsEqual = (prev: MessageProps, next: MessageProps) =>
  prev.message === next.message &&
  prev.isLast === next.isLast &&
  prev.theme === next.theme
// message 对象在 store 中按不可变模式更新：内容变则引用变，未变的历史消息引用稳定 → memo 命中

const BubbleMessage = React.memo(BubbleMessageImpl, areMessagePropsEqual)
const FlatMessage = React.memo(FlatMessageImpl, areMessagePropsEqual)
```

（props 名单以实际组件签名为准；比较器只列会影响渲染的 props，回调 props 需先用 `useCallback` 稳定——`grep -n "onRetry\|onCopy" ChatList.tsx` 逐个包 useCallback。）

- [x] **Step 2: 验证**

React DevTools Profiler：流式期间只有最后一条消息重渲染，历史消息 render 次数为 0。
Run: `cd frontend && pnpm test:unit && pnpm build`

- [x] **Step 3: Commit**

```bash
git commit -am "perf(chat): memoize message components; stabilize handler identities"
```

---

### Task 4: 流式中跳过图表解析（FE-03b）

**Files:**
- Modify: `frontend/src/components/ChatList.tsx:547` 附近（锚点：`grep -n "parseSmartChartBlocks" ChatList.tsx`）

- [x] **Step 1:** 把图表块 useMemo 改为：

```tsx
const EMPTY_CHART_BLOCKS: SmartChartBlock[] = []
const chartBlocks = useMemo(
  () => (message.isLoading ? EMPTY_CHART_BLOCKS : parseSmartChartBlocks(message.content)),
  [message.content, message.isLoading],
)
```

（若解析发生在子组件，把 `isLoading` 传下去做同样的门；`stripSmartChartTags` 同理只在落定后执行——流式中间态直接渲染原文。）

- [x] **Step 2: 验证**：流式期间 CPU 明显下降（Performance 面板录制对比），落定后图表正常出现。

- [x] **Step 3: Commit**

```bash
git commit -am "perf(chat): skip smart-chart regex parsing while message is streaming"
```

---

### Task 5: ChatInput 订阅收窄（FE-07 热点部分）

**Files:**
- Modify: `frontend/src/components/ChatInput.tsx:278-302`（锚点：`grep -n "useStore()" frontend/src/components/ChatInput.tsx`）

- [x] **Step 1:** 把整包解构 `const { a, b, c, … } = useStore()` 拆成原子 selector：

```tsx
const isLoading = useStore((s) => s.isLoadingBySession[activeSessionId] ?? false)
const addMessageToSession = useStore((s) => s.addMessageToSession)
const updateMessageInSession = useStore((s) => s.updateMessageInSession)
// …逐字段列出，每行一个 selector；rawEvents / agentLogs 等仅开发台使用的字段
// 不在 ChatInput 订阅——grep 确认它们在 ChatInput 内的使用点，改由使用它们的子组件自行订阅
```

规则：**actions 用单独 selector 取（引用稳定），数据字段逐一取，禁止对象解构整个 store**。

- [x] **Step 2: 验证**：Profiler 确认流式期间 ChatInput 不再每 token 重渲染。`pnpm test:unit` 无回归。

- [x] **Step 3: Commit**

```bash
git commit -am "perf(chat-input): atomic zustand selectors, stop re-rendering on every stream event"
```

---

### Task 6: 文本先落定、图表异步补挂（UX-03）

**Files:**
- Modify: `frontend/src/components/ChatInput.tsx:612-708`（锚点：`grep -n "onDone" frontend/src/components/ChatInput.tsx`）

- [x] **Step 1:** 现状：`onDone` 内 `await detectChartType(...)`（可能再 await `getChartData`）之后才置 `isLoading:false`。改为：

```tsx
onDone: (finalContent) => {
  updateMessageInSession(sessionId, messageId, { content: finalContent, isLoading: false })
  flushPersist(sessionId)
  void (async () => {
    try {
      // 原有的 detectChartType / getChartData / 注入 chart marker 逻辑整体移入此处，
      // 结果通过第二次 updateMessageInSession 补丁式追加
      const patched = await injectChartsIfAny(finalContent /*, tickers…*/)
      if (patched && patched !== finalContent) {
        updateMessageInSession(sessionId, messageId, { content: patched })
        schedulePersist(sessionId)
      }
    } catch (error) {
      console.warn("chart enrichment skipped:", error)
    }
  })()
}
```

`injectChartsIfAny` = 把现有 onDone 里的图表检测代码原样搬进的本地 async 函数（不改判定逻辑，只改时序）。

- [x] **Step 2: 验证**：长回复流完瞬间气泡落定（无加载态残留数秒），图表稍后出现。

- [x] **Step 3: Commit**

```bash
git commit -am "fix(chat): finalize message immediately on done; chart detection patches in asynchronously"
```

---

### Task 7: 生成期间输入框可编辑（UX-04）

**Files:**
- Modify: `frontend/src/components/ChatInput.tsx:1027,1035-1045`

- [x] **Step 1:** textarea 移除 `disabled={isLoading}`（保留 placeholder 切换）；发送按钮已有 停止/发送 切换则保持；`handleSend` 入口加保护：

```tsx
if (isLoading) return // 生成中回车不触发发送（按钮此时是"停止"）
```

同时确认 Enter 发送的 keydown handler 也走该保护。

- [x] **Step 2: 验证**：生成期间可以打字、不能误发；点停止后可立即发送草稿。

- [x] **Step 3: Commit**

```bash
git commit -am "fix(chat-input): allow typing while generating; guard submit instead of disabling textarea"
```

---

### Task 8: 复制反馈 + 删除会话确认（UX-06）

**Files:**
- Modify: `frontend/src/components/ChatList.tsx:718-757`（复制按钮）；`frontend/src/components/Sidebar.tsx` 或会话列表组件（`grep -rn "deleteConversation(" frontend/src/components`）

- [x] **Step 1: 复制反馈**：复制成功把按钮图标临时切为 ✓（1.5s 后还原），失败弹 toast；按钮补 `aria-label="复制回答"`。

```tsx
const [copied, setCopied] = useState(false)
const handleCopy = async () => {
  try {
    await navigator.clipboard.writeText(message.content)
    setCopied(true)
    setTimeout(() => setCopied(false), 1500)
  } catch {
    toast({ variant: "error", title: "复制失败" })
  }
}
```

- [x] **Step 2: 删除确认**：调用 `deleteConversation` 前弹项目已有的确认组件（`grep -rn "confirm" frontend/src/components/ui` 找现成的 Dialog/Confirm；若无，用两段式按钮：首次点击变红显示"再点一次确认删除"，3s 恢复）。

- [x] **Step 3: 验证 + Commit**

```bash
git commit -am "fix(ux): copy feedback state + confirm before conversation deletion"
```

---

### Task 9（可选，需主人批准新依赖）: 长列表虚拟化

安装 `virtua`（~3KB）：消息数 >30 时用 `<Virtualizer>` 包裹消息列表，支持动态高度与倒序聊天。**未获批准前跳过此任务**，Task 3+4 已消除主要卡顿源。

---

## WP1 完成门禁

- [x] `cd frontend && pnpm test:unit && pnpm build` 全绿
- [x] Profiler 实测：3000+ token 长回复流式期间无掉帧（对比录像/火焰图留档到 PR）
- [x] 手工清单：回看不被拽底 / 输入框可打字 / 复制有反馈 / 删除有确认 / 图表照常渲染
