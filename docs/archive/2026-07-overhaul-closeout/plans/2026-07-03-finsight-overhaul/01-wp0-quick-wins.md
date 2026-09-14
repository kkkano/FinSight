# WP0 速赢周 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 一周内修完全部"低成本高收益"项：1 个真 bug（BE-01）、1 个信任问题（UX-01/02）、3 个前端网络层缺陷（FE-04/05/06）、2 个仓库卫生问题（BE-08/09）、2 个部署安全项（SEC-03/05）。

**Architecture:** 全部是点状修复，互相独立，每个任务一次 commit，可任意顺序执行（建议按编号）。

**Tech Stack:** 同主纲。

## Global Constraints

- 不引入任何新依赖。
- 每个任务先写失败测试（能写测试的场景），再改实现。
- 行号基于基线 commit `4a1c055`，执行前先用给出的 grep 锚点确认，行号漂移以锚点为准。

---

### Task 1: 修复 price.py 价格级联 UnboundLocalError（BE-01/BE-02/BE-10）

**Files:**
- Modify: `backend/tools/price.py:536-556`
- Test: `backend/tests/test_price_cascade_ladder.py`（新建）

**Interfaces:**
- Produces: `get_stock_price(ticker) -> str` 行为不变（正常路径）；新增行为：源文本无 `$数字` 时不再丢弃该源。

- [x] **Step 1: 写失败测试**

新建 `backend/tests/test_price_cascade_ladder.py`：

```python
# -*- coding: utf-8 -*-
"""BE-01：数据源返回文本无 $ 数字时，get_stock_price 不得丢弃该成功源。"""
from unittest.mock import patch

import backend.tools.price as price_mod


def test_source_without_dollar_sign_is_not_discarded():
    """源返回 '195.30 USD'（无 $ 前缀）→ 应原样返回，而不是 NameError 后降级到全失败。"""
    def fake_source(ticker):
        return "AAPL current price: 195.30 USD (from fake_source)"

    # 美股级联首选 _fetch_yahoo_api_v8；只 patch 它返回无 $ 文本，其余源全失败
    with patch.object(price_mod, "_fetch_yahoo_api_v8", side_effect=fake_source), \
         patch.object(price_mod, "_fetch_with_stooq_price", return_value=None), \
         patch.object(price_mod, "_scrape_google_finance", return_value=None), \
         patch.object(price_mod, "_scrape_cnbc", return_value=None), \
         patch.object(price_mod, "_fetch_with_pandas_datareader", return_value=None), \
         patch.object(price_mod, "_fetch_with_yfinance", return_value=None), \
         patch.object(price_mod, "_fetch_with_alpha_vantage", return_value=None), \
         patch.object(price_mod, "_fetch_with_finnhub", return_value=None), \
         patch.object(price_mod, "_fetch_with_twelve_data_price", return_value=None), \
         patch.object(price_mod, "_scrape_yahoo_finance", return_value=None), \
         patch.object(price_mod, "_search_for_price", return_value=None):
        result = price_mod.get_stock_price("AAPL")

    assert "195.30 USD" in result
    assert "All data sources failed" not in result


def test_source_with_dollar_sign_appends_ladder():
    """有 $ 数字时保留原有 Suggested ladder 行为。"""
    def fake_source(ticker):
        return "AAPL: $200.00"

    with patch.object(price_mod, "_fetch_yahoo_api_v8", side_effect=fake_source):
        result = price_mod.get_stock_price("AAPL")

    assert "$200.00" in result
    assert "Suggested ladder: $198.00 / $196.00" in result
```

- [x] **Step 2: 运行确认失败**

Run: `python -m pytest backend/tests/test_price_cascade_ladder.py -x -q`
Expected: 第一个测试 FAIL（返回值包含 "All data sources failed"）。

- [x] **Step 3: 修实现**

打开 `backend/tools/price.py`。锚点：`grep -n "Suggested ladder" backend/tools/price.py`（基线在 553 行附近）。将下面这段：

```python
                # 追加两档分批价，保证有具体数字
                price_num = None
                import re
                m = re.search(r"\$([0-9]+(?:\.[0-9]+)?)", result)
                if m:
                    try:
                        price_num = float(m.group(1))
                    except Exception:
                        price_num = None
                if price_num:
                    p1 = price_num * 0.99
                    p2 = price_num * 0.98
                result = f"{result} | Suggested ladder: ${p1:.2f} / ${p2:.2f} (+/-1% / +/-2% from current)"
                return result
            time.sleep(0.5)
```

整体替换为：

```python
                # 追加两档分批价——仅在能从文本解析出 $ 数字时；解析失败绝不影响本源结果
                m = _PRICE_DOLLAR_RE.search(result)
                if m:
                    try:
                        price_num = float(m.group(1))
                        p1 = price_num * 0.99
                        p2 = price_num * 0.98
                        result = (
                            f"{result} | Suggested ladder: ${p1:.2f} / ${p2:.2f} "
                            f"(+/-1% / +/-2% from current)"
                        )
                    except Exception:
                        logger.debug("ladder append skipped for %s", ticker_key, exc_info=True)
                return result
```

注意三处连带修改：
1. 删除了循环内的 `import re` 与 `time.sleep(0.5)`（BE-02：源间无意义等待）。
2. 在模块顶部（`grep -n "^import re" backend/tools/price.py` 确认；若无则在 import 区加 `import re`）加正则常量：

```python
_PRICE_DOLLAR_RE = re.compile(r"\$([0-9]+(?:\.[0-9]+)?)")
```

3. BE-10 顺带修：找到 `_last_fetch_info` 的定义（`grep -n "_last_fetch_info" backend/tools/price.py` 第一处），在写入处（`get_stock_price` 内两处赋值）之前加容量护栏：

```python
                if len(_last_fetch_info) > 512:
                    _last_fetch_info.clear()
```

（两处赋值前各加一次，或抽成模块级函数 `_record_fetch_info(key, info)` 统一处理——二选一，推荐后者：）

```python
def _record_fetch_info(ticker_key: str, info: dict[str, Any]) -> None:
    if len(_last_fetch_info) > 512:
        _last_fetch_info.clear()
    _last_fetch_info[ticker_key] = info
```

然后把 `get_stock_price` 内两处 `_last_fetch_info[ticker_key] = {...}` 改为 `_record_fetch_info(ticker_key, {...})`。

- [x] **Step 4: 运行确认通过**

Run: `python -m pytest backend/tests/test_price_cascade_ladder.py -x -q`
Expected: 2 passed。

再跑价格相关既有测试确认无回归：
Run: `python -m pytest backend/tests -k "price" -q`
Expected: 全绿。

- [x] **Step 5: Commit**

```bash
git add backend/tools/price.py backend/tests/test_price_cascade_ladder.py
git commit -m "fix(price): ladder append no longer discards sources without \$-prefixed price; drop inter-source sleep; bound _last_fetch_info"
```

---

### Task 2: main.py 重复 import 清理（BE-08 局部）

**Files:**
- Modify: `backend/api/main.py:1-12`

- [x] **Step 1: 确认现状**

Run: `grep -n "^import asyncio" backend/api/main.py`
Expected: 两行（基线为第 3 行与第 9 行）。

- [x] **Step 2: 删除第二处 `import asyncio`**（保留第一处）。

- [x] **Step 3: 验证**

Run: `python -c "import backend.api.main"`
Expected: 无报错（该 import 会拉起 app 装配，需 `.env.server` 存在；若本机无法 import，改跑 `python -m pytest backend/tests -k "smoke or health" -q`）。

- [x] **Step 4: Commit**

```bash
git add backend/api/main.py
git commit -m "chore(api): remove duplicate asyncio import in main.py"
```

---

### Task 3: 修正虚假隐私声明 + 保存失败 Toast（UX-01/UX-02）

**Files:**
- Modify: `frontend/src/components/SettingsModal.tsx`
- Test: `frontend/src/components/SettingsModal.test.tsx`（若已存在则追加用例；不存在则新建）

**Interfaces:**
- Consumes: 项目已有 Toast 系统 `frontend/src/components/ui/Toast.tsx`。执行前先 `grep -n "export" frontend/src/components/ui/Toast.tsx` 确认导出名（预期是 `useToast` 或 `showToast` 一类）；下文以 `useToast` 书写，若实际导出名不同，按实际名替换（仅替换名字，结构不变）。

- [x] **Step 1: 定位虚假文案**

Run: `grep -n "仅存储在浏览器本地\|不会上传到服务器" frontend/src/components/SettingsModal.tsx`
Expected: 命中 1 处（基线 855 行附近）。

- [x] **Step 2: 替换文案**

将该段文案整体替换为（保留原有 JSX 结构/样式类名，只换文字）：

> `API Key 会保存到服务端配置文件（仅持有管理员令牌时可修改），界面回显时只显示掩码，不会以明文回传。`

- [x] **Step 3: 写失败测试（保存失败必须弹 Toast）**

在 `SettingsModal.test.tsx` 中追加（按项目现有测试风格调整 render 辅助；mock `apiClient.saveConfig`——先 `grep -n "saveConfig\|/api/config" frontend/src/api/client.ts` 确认方法名）：

```tsx
it("保存失败时显示错误提示而不是静默", async () => {
  vi.spyOn(apiClient, "saveConfig").mockRejectedValueOnce(new Error("500"))
  render(<SettingsModal open onClose={() => {}} />)
  await userEvent.click(screen.getByRole("button", { name: /保存/ }))
  expect(await screen.findByText(/保存失败/)).toBeInTheDocument()
})
```

- [x] **Step 4: 运行确认失败**

Run: `cd frontend && pnpm test:unit -- SettingsModal`
Expected: 新用例 FAIL（找不到 "保存失败" 文案）。

- [x] **Step 5: 实现**

在 `SettingsModal.tsx` 的 `handleSave` 中：定位 `grep -n "console.error" frontend/src/components/SettingsModal.tsx` 在 catch 块处，改为：

```tsx
} catch (error) {
  console.error("Failed to save config:", error)
  toast({ variant: "error", title: "保存失败", description: "配置未生效，请检查网络或管理员令牌后重试。" })
}
```

组件顶部按 Toast 系统实际 API 引入（例：`const { toast } = useToast()`）。同时在保存成功分支加 `toast({ variant: "success", title: "已保存" })`。

- [x] **Step 6: 运行确认通过**

Run: `cd frontend && pnpm test:unit -- SettingsModal`
Expected: PASS。

- [x] **Step 7: Commit**

```bash
git add frontend/src/components/SettingsModal.tsx frontend/src/components/SettingsModal.test.tsx
git commit -m "fix(settings): truthful api-key storage copy; surface save success/failure via toast"
```

---

### Task 4: axios 超时修正（FE-04）

**Files:**
- Modify: `frontend/src/api/client.ts:290-296`

- [x] **Step 1: 定位**

Run: `grep -n "timeout: 800000" frontend/src/api/client.ts`

- [x] **Step 2: 修改**

```ts
// 普通 REST 请求 30s 超时；长任务（报告/回测/执行）一律走 SSE 通道，不受此限制
timeout: 30_000,
```

- [x] **Step 3: 排查长耗时非 SSE 调用**

Run: `grep -n "backtest\|export\|pdf" frontend/src/api/client.ts`
对确属长耗时的普通 POST（如回测运行、PDF 导出），在该方法调用处显式覆写：`{ timeout: 120_000 }`（axios 第三参/config 位置）。逐个列出你改了哪些方法并写入 commit message。

- [x] **Step 4: 验证**

Run: `cd frontend && pnpm build`
Expected: 构建通过。手工冒烟：dev 起前后端，正常聊天/拉行情不超时。

- [x] **Step 5: Commit**

```bash
git add frontend/src/api/client.ts
git commit -m "fix(api-client): default timeout 30s (comment said 120s but was 800s); explicit 120s for long non-SSE ops"
```

---

### Task 5: 流式请求补 Authorization + 去掉 response.clone()（FE-05/FE-06）

**Files:**
- Modify: `frontend/src/api/client.ts`（`sendMessageStream` / `executeAgent` / `resumeExecution` 三处 fetch；`resumeExecution` 的 clone）

**Interfaces:**
- Consumes: axios 拦截器已有的 Supabase token 获取逻辑。执行前 `grep -n "interceptors.request" -A 15 frontend/src/api/client.ts` 找到它获取 token 的确切调用（预期形如 `supabase.auth.getSession()` 或从 `supabaseClient.ts` 导入的封装）。
- Produces: `async function buildAuthHeaders(): Promise<Record<string, string>>`——供三个流式方法复用。

- [x] **Step 1: 抽取 buildAuthHeaders**

在 `client.ts` 中 axios 拦截器附近新增（token 获取表达式必须与拦截器**逐字相同**，不要自己发明）：

```ts
async function buildAuthHeaders(): Promise<Record<string, string>> {
  try {
    // ↓ 与上方 axios 拦截器同源的 token 获取逻辑，保持一致
    const token = /* 复制拦截器中的取 token 表达式 */
    return token ? { Authorization: `Bearer ${token}` } : {}
  } catch {
    return {}
  }
}
```

- [x] **Step 2: 三个流式方法接入**

Run: `grep -n "fetch(" frontend/src/api/client.ts` 定位 `sendMessageStream`（~1228）、`executeAgent`（~1329）、`resumeExecution`（~1480s）三处。每处 fetch 的 `headers` 改为：

```ts
headers: {
  "Content-Type": "application/json",
  ...(await buildAuthHeaders()),
  // …保留该处原有的其他自定义头
},
```

（所在函数若非 async，先确认——三者都是 async，可直接 await。）

- [x] **Step 3: 去掉 clone（FE-06）**

Run: `grep -n "response.clone()" frontend/src/api/client.ts`
将 `parseSSEStream(response.clone(), ...)` 改为 `parseSSEStream(response, ...)`。改完在该方法体内 `grep` 确认没有第二处消费 `response.body` 的代码。

- [x] **Step 4: 验证**

Run: `cd frontend && pnpm test:unit && pnpm build`
手工冒烟：登录态发消息，DevTools Network 确认 `/api/chat` 请求头携带 `Authorization: Bearer …`。

- [x] **Step 5: Commit**

```bash
git add frontend/src/api/client.ts
git commit -m "fix(api-client): attach supabase bearer to streaming fetches; drop response.clone() buffering in resumeExecution"
```

---

### Task 6: docker-compose 后端端口只绑回环（SEC-03）

**Files:**
- Modify: `docker-compose.yml:79-80`

- [x] **Step 1: 修改**

```yaml
    ports:
      - "127.0.0.1:8000:8000"   # 仅本机可直连；外部流量必须走 Cloudflare Tunnel / 前端反代
```

- [x] **Step 2: 兼容性检查**

`grep -rn "localhost:8000\|127.0.0.1:8000\|:8000" docker-compose.yml frontend/nginx* scripts/ 2>/dev/null`——确认：
- 前端容器访问后端走的是 compose 网络服务名（不受影响）；
- 若宿主机上有 cloudflared 以 `localhost:8000` 为 origin，则 127.0.0.1 绑定仍可达，无需改动。
把检查结论写进 commit body。

- [x] **Step 3: Commit**

```bash
git add docker-compose.yml
git commit -m "fix(deploy): bind backend port to loopback only, close direct-to-origin bypass of Cloudflare"
```

---

### Task 7: 清理 .bak 数据文件（BE-09）

**Files:**
- Delete: `backend/data/report_index_release_drill_existing_20260208050902.sqlite.pre_migration.bak`
- Modify: `.gitignore`

- [x] **Step 1:** `git rm backend/data/*.bak`
- [x] **Step 2:** `.gitignore` 追加两行：

```gitignore
*.bak
backend/data/*.sqlite.pre_migration.*
```

- [x] **Step 3: Commit**

```bash
git commit -m "chore(repo): remove committed sqlite backup artifact; ignore future .bak files"
```

---

### Task 8: release_drills subprocess 护栏（SEC-05）

**Files:**
- Modify: `backend/services/release_drills.py`
- Test: `backend/tests/test_release_drills_guard.py`（新建）

- [x] **Step 1: 确认调用面**

Run: `grep -rn "release_drills" backend/api backend/graph backend/services --include="*.py" | grep -v release_drills.py`
Expected: 无 HTTP router 引用（若有，停下并在 PR 描述中上报，本任务改为移除该引用）。

- [x] **Step 2: 写失败测试**

```python
# backend/tests/test_release_drills_guard.py
import os
from unittest.mock import patch

import pytest


def test_run_drill_refuses_outside_cli(monkeypatch):
    monkeypatch.delenv("FINSIGHT_RELEASE_DRILL_ALLOWED", raising=False)
    from backend.services import release_drills
    with pytest.raises(RuntimeError):
        release_drills._assert_drill_allowed()
```

- [x] **Step 3: 实现**

`release_drills.py` 模块内新增（并在调用 `subprocess.run` 的函数入口第一行调用它）：

```python
def _assert_drill_allowed() -> None:
    """release drill 只允许运维在 CLI 显式开启后执行，杜绝被任何服务路径意外触达。"""
    if os.getenv("FINSIGHT_RELEASE_DRILL_ALLOWED", "").strip().lower() not in {"1", "true", "yes", "on"}:
        raise RuntimeError(
            "release drill blocked: set FINSIGHT_RELEASE_DRILL_ALLOWED=true to run this maintenance script"
        )
```

`.env.server.example` 登记该变量（默认注释掉）。

- [x] **Step 4: 测试通过 + Commit**

Run: `python -m pytest backend/tests/test_release_drills_guard.py -x -q`

```bash
git add backend/services/release_drills.py backend/tests/test_release_drills_guard.py .env.server.example
git commit -m "fix(security): gate release-drill subprocess behind explicit env allowlist"
```

---

## WP0 完成门禁

- [x] `python -m pytest backend/tests -x -q`（修订门禁：无新增失败，19 项基线固有失败清单见 tests/baseline-failures-4a1c055.txt）
- [x] `cd frontend && pnpm test:unit && pnpm build` 全绿（215 passed + build 1.5s）
- [x] 手工冒烟：聊天一轮、设置保存成功/失败各一次、登录后请求带 Authorization
