# P0 止血实现计划（P0-1 ~ P0-8）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 清除假数据、补齐信任要素、开启基础防护，让 FinSight 在一周内从"会演戏的 demo"变成"诚实的产品"。

**Architecture:** 8 个独立小任务，互不依赖，可并行执行。后端任务（1/2/5/7/8）改 Python，前端任务（3/4/6）改 React/TS。每个任务遵循 TDD：先写失败测试 → 实现 → 通过 → 提交。

**Tech Stack:** Python 3.12 + FastAPI + pytest（后端）；React 18 + TypeScript + Tailwind（前端）

**关联文档:**
- 问题来源：`docs/plans/2026-06-02_product_trust_overhaul_roadmap.md`
- P0-9（新闻舆情简报）有独立计划：`docs/plans/2026-06-02_news_sentiment_brief_plan.md`

**执行注意:**
- 后端测试命令：`cd /e/FinSight && python -m pytest backend/tests/<file> -v`
- 前端构建检查：`cd /e/FinSight/frontend && npm run build`
- commit 前必须征得主人同意（全局规则）

---

## Task 1: 杀掉宏观假数据（P0-1）

**问题:** FRED API key 缺失时硬编码 CPI=3.0、利率=4.5、失业率=4.0 冒充真实数据。

**状态更新（2026-06-02）:** 主人已提供有效的 FRED API key，已写入本地 `.env`（gitignored）。
本任务的防御性修复**仍然必须做**——防止未来 key 失效/服务器漏配时退回演戏行为。
修复完成后本地环境会走真实 FRED 数据路径，假数据分支只在 key 缺失时触发。

**Files:**
- Modify: `backend/tools/macro.py:135-143`
- Modify: `backend/agents/macro_agent.py:105-110`（调用方适配）
- Test: `backend/tests/test_macro_no_fake_data.py`（新建）

- [ ] **Step 1.1: 写失败测试**

创建 `backend/tests/test_macro_no_fake_data.py`：

```python
"""P0-1: FRED 无 API key 时不得返回编造的宏观数据"""
import backend.tools.macro as macro_tools


def test_get_fred_data_without_key_returns_unavailable(monkeypatch):
    """无 FRED_API_KEY 时必须返回 data_unavailable，禁止返回编造值"""
    # FRED_API_KEY 是 macro.py 的模块级常量（macro.py:99 `api_key = FRED_API_KEY`）
    monkeypatch.setattr(macro_tools, "FRED_API_KEY", "")

    result = macro_tools.get_fred_data()

    # 绝不允许出现编造的数值（3.0 / 4.5 / 4.0）
    assert result.get("cpi") is None
    assert result.get("fed_rate") is None
    assert result.get("unemployment") is None
    # 状态必须从 "success" 变为 "data_unavailable"
    assert result.get("status") == "data_unavailable"
    assert "FRED_API_KEY" in str(result.get("unavailable_reason", ""))


def test_get_fred_data_without_key_no_estimate_source(monkeypatch):
    """无 key 时不得使用 source=estimate 伪装"""
    monkeypatch.setattr(macro_tools, "FRED_API_KEY", "")

    result = macro_tools.get_fred_data()
    assert result.get("source") != "estimate"
```

注意：`result` 字典在 macro.py:86-96 初始化时所有指标键已存在且值为 None，
`"status"` 初始值为 `"success"`、`"source"` 初始值为 `"FRED"`——测试断言基于此结构。

- [ ] **Step 1.2: 运行测试确认失败**

```bash
python -m pytest backend/tests/test_macro_no_fake_data.py -v
```
预期：FAIL（当前代码返回编造值）

- [ ] **Step 1.3: 修改 `backend/tools/macro.py`**

将 135-143 行的：

```python
            else:
                # 无 API key 时使用搜索回退
                if key == "cpi":
                    result[key] = 3.0  # 估计值
                elif key == "fed_rate":
                    result[key] = 4.5  # 估计值
                elif key == "unemployment":
                    result[key] = 4.0  # 估计值
                result["source"] = "estimate"
```

替换为：

```python
            else:
                # 无 API key：诚实返回不可用，绝不编造数值（P0-1）
                result["status"] = "data_unavailable"
                result["unavailable_reason"] = "FRED_API_KEY not configured"
                break
```

- [ ] **Step 1.4: 适配调用方 `backend/agents/macro_agent.py:105-110`**

找到 `payload = self.tools.get_fred_data()` 之后的处理逻辑，
在使用 payload 的数值之前加状态检查：

```python
            if hasattr(self.tools, "get_fred_data"):
                payload = self.tools.get_fred_data()
                if isinstance(payload, dict) and payload.get("status") == "data_unavailable":
                    # FRED 不可用：明确走 fallback 路径，不把空 payload 当数据用
                    logger.info("[MacroAgent] FRED unavailable: %s", payload.get("unavailable_reason"))
                    payload = None
```

同时检查 `backend/dashboard/data_service.py:177-185` 对 `get_fred_data()` 返回值的用法，
若直接读取 `fred_payload["cpi"]` 等键，需加 `status != "data_unavailable"` 防御。

- [ ] **Step 1.5: 运行测试确认通过 + 回归**

```bash
python -m pytest backend/tests/test_macro_no_fake_data.py backend/tests/test_macro_snapshot.py backend/tests/test_deep_research.py -v
```
预期：全部 PASS（test_deep_research 用 mock 不受影响）

- [ ] **Step 1.6: 提交（需主人同意）**

```bash
git add backend/tools/macro.py backend/agents/macro_agent.py backend/dashboard/data_service.py backend/tests/test_macro_no_fake_data.py
git commit -m "fix(macro): FRED no-key returns data_unavailable instead of fabricated values (P0-1)"
```

---

## Task 2: 杀掉假置信度（P0-2）

**问题:** 数据缺失时 confidence 硬编码 0.2/0.6 演戏，且有 `max(0.2, ...)` 下限保护。

**Files:**
- Modify: `backend/agents/fundamental_agent.py:354-356`
- Modify: `backend/agents/macro_agent.py:488-495`
- Test: `backend/tests/test_no_fake_confidence.py`（新建）

- [ ] **Step 2.1: 写失败测试**

创建 `backend/tests/test_no_fake_confidence.py`：

```python
"""P0-2: 数据缺失时 confidence 不得演戏"""


def test_fundamental_no_evidence_low_confidence_with_fallback_flag():
    """基本面 agent 无证据时：confidence <= 0.1 且 fallback 标记必须设置"""
    from backend.agents.fundamental_agent import FundamentalAgent
    from unittest.mock import MagicMock

    agent = FundamentalAgent(llm=None, cache=MagicMock(), tools_module=None)
    agent._current_ticker = "TEST"
    agent._current_query = "test"

    # 模拟空数据格式化输出
    output = agent._format_output("no data summary", {"ticker": "TEST"})

    if not output.evidence:
        assert output.confidence <= 0.1, (
            f"无证据时 confidence={output.confidence}，不得超过 0.1（演戏行为）"
        )
        assert output.fallback_used is True
        assert output.fallback_reason  # 必须有原因


def test_macro_missing_quality_confidence_capped():
    """宏观 agent 质量分缺失时：confidence <= 0.35 且 risks 含数据质量警告"""
    # 直接验证常量逻辑：见 macro_agent.py 修改后的 _MISSING_QUALITY_CONFIDENCE
    from backend.agents.macro_agent import MacroAgent

    assert getattr(MacroAgent, "_MISSING_QUALITY_CONFIDENCE", None) == 0.35
```

注意：`FundamentalAgent.__init__` 签名需先确认（读 `backend/agents/fundamental_agent.py` 的 `__init__` 和 `_format_output`），
按实际签名调整测试构造方式。若 `_format_output` 不接受该输入形态，改用更小的单元（直接测 confidence 计算逻辑）。

- [ ] **Step 2.2: 运行测试确认失败**

```bash
python -m pytest backend/tests/test_no_fake_confidence.py -v
```
预期：FAIL

- [ ] **Step 2.3: 修改 `backend/agents/fundamental_agent.py:354-356`**

将：

```python
        quality_score = self._safe_float(evidence_quality.get("overall_score")) if isinstance(evidence_quality, dict) else None
        confidence = quality_score if quality_score is not None else (0.7 if evidence else 0.2)
        confidence = max(0.2, min(0.92, confidence))
```

替换为：

```python
        quality_score = self._safe_float(evidence_quality.get("overall_score")) if isinstance(evidence_quality, dict) else None
        # P0-2: 无证据时不演戏——confidence 压到 0.1 并显式标记 fallback
        if evidence:
            confidence = quality_score if quality_score is not None else 0.7
            confidence = max(0.2, min(0.92, confidence))
        else:
            confidence = 0.1
```

并在同函数构造 `AgentOutput` 的地方（搜索 `return AgentOutput`），确保无证据分支设置：

```python
            fallback_used=not bool(evidence) or fallback_used,
            fallback_reason=(fallback_reason or ("no_fundamental_data" if not evidence else None)),
```

（按该文件 AgentOutput 构造的实际参数名对齐；若已有 fallback_used 逻辑则仅补 fallback_reason。）

- [ ] **Step 2.4: 修改 `backend/agents/macro_agent.py:488-495`**

在类顶部（`AGENT_NAME` 附近）加常量：

```python
    _MISSING_QUALITY_CONFIDENCE = 0.35  # P0-2: 质量分缺失时的诚实上限
```

将 488-495 行的：

```python
        overall_quality = evidence_quality.get("overall_score") if isinstance(evidence_quality, dict) else None
        try:
            confidence = float(overall_quality) if overall_quality is not None else 0.6
        except (TypeError, ValueError):
            confidence = 0.6
        confidence = max(0.2, min(0.95, confidence))
        if fallback_used:
            confidence = min(confidence, 0.6)
```

替换为：

```python
        overall_quality = evidence_quality.get("overall_score") if isinstance(evidence_quality, dict) else None
        try:
            confidence = float(overall_quality) if overall_quality is not None else self._MISSING_QUALITY_CONFIDENCE
        except (TypeError, ValueError):
            confidence = self._MISSING_QUALITY_CONFIDENCE
        if overall_quality is None:
            # P0-2: 质量分缺失时压低置信度并在风险中明示
            risks = list(risks or [])
            risks.append("宏观数据质量未评估（评分缺失），本节置信度已下调")
        confidence = max(0.2, min(0.95, confidence))
        if fallback_used:
            confidence = min(confidence, 0.6)
```

- [ ] **Step 2.5: 运行测试确认通过 + 回归**

```bash
python -m pytest backend/tests/test_no_fake_confidence.py backend/tests/ -k "fundamental or macro" -v
```
预期：PASS

- [ ] **Step 2.6: 提交（需主人同意）**

```bash
git add backend/agents/fundamental_agent.py backend/agents/macro_agent.py backend/tests/test_no_fake_confidence.py
git commit -m "fix(agents): honest confidence when data missing, no more fake 0.2/0.6 (P0-2)"
```

---

## Task 3: 免责声明常驻（P0-3）

**问题:** 只有 Chat 底部一行英文小字，Dashboard/Workbench/Report 完全没有。

**Files:**
- Create: `frontend/src/components/common/AiDisclaimer.tsx`
- Modify: `frontend/src/components/layout/WorkspaceShell.tsx`（若它是共同外壳）
- Modify: `frontend/src/components/ChatInput.tsx:1014-1017`

- [ ] **Step 3.1: 确认挂载点**

读 `frontend/src/components/layout/WorkspaceShell.tsx`，确认它是否包裹了
Dashboard/Workbench/Chat 三个 workspace。
- 是 → 免责声明挂在 WorkspaceShell（一处搞定）
- 否 → 分别挂到 `DashboardWorkspace.tsx`、`WorkbenchWorkspace.tsx`（Chat 已有，只需汉化）

- [ ] **Step 3.2: 创建 `frontend/src/components/common/AiDisclaimer.tsx`**

```tsx
/**
 * AiDisclaimer -- 全局常驻 AI 免责声明（P0-3）
 * 所有展示 AI 分析内容的页面必须挂载。
 */
import React from 'react';

interface AiDisclaimerProps {
  /** compact: 单行小字（页面底部）；banner: 醒目横幅（页面顶部） */
  variant?: 'compact' | 'banner';
}

export const AiDisclaimer: React.FC<AiDisclaimerProps> = ({ variant = 'compact' }) => {
  if (variant === 'banner') {
    return (
      <div
        role="note"
        className="flex items-center gap-2 px-3 py-1.5 text-xs rounded-lg border border-amber-200 bg-amber-50 text-amber-800 dark:border-amber-700/50 dark:bg-amber-900/20 dark:text-amber-200"
      >
        <span aria-hidden>⚠️</span>
        <span>本页内容由 AI 生成，仅供研究参考，不构成投资建议。市场有风险，决策需谨慎。</span>
      </div>
    );
  }
  return (
    <p className="text-center text-xs text-fin-muted">
      AI 生成内容可能存在误差 · 仅供研究参考 · 不构成投资建议
    </p>
  );
};

export default AiDisclaimer;
```

- [ ] **Step 3.3: 挂载到 workspace 外壳**

按 Step 3.1 的结论，在外壳组件的主内容区**顶部**插入：

```tsx
import { AiDisclaimer } from '../common/AiDisclaimer';

{/* 主内容区第一个子元素 */}
<AiDisclaimer variant="banner" />
```

- [ ] **Step 3.4: 汉化 ChatInput 免责声明**

`frontend/src/components/ChatInput.tsx:1014-1017`，将：

```tsx
        <p className="text-xs text-fin-muted">
          FinSight AI generated content may be inaccurate. Not financial advice.
        </p>
```

替换为：

```tsx
        <AiDisclaimer variant="compact" />
```

并在文件顶部 import 区加：

```tsx
import { AiDisclaimer } from './common/AiDisclaimer';
```

（按 ChatInput.tsx 实际相对路径调整 import。）

- [ ] **Step 3.5: 构建验证**

```bash
cd frontend && npm run build
```
预期：构建成功，无 TS 错误

- [ ] **Step 3.6: 提交（需主人同意）**

```bash
git add frontend/src/components/common/AiDisclaimer.tsx frontend/src/components/layout/ frontend/src/components/ChatInput.tsx
git commit -m "feat(trust): persistent Chinese AI disclaimer on all workspaces (P0-3)"
```

---

## Task 4: 数据时效标注（P0-4）

**问题:** 报告只显示日期（`toLocaleDateString()`），用户无法判断数据新旧。

**Files:**
- Modify: `frontend/src/components/report/ReportView.tsx:98-101`

- [ ] **Step 4.1: 修改 formattedDate 逻辑**

`frontend/src/components/report/ReportView.tsx:98-101`，将：

```tsx
  const formattedDate = useMemo(() => {
    const date = new Date(report.generated_at);
    return Number.isNaN(date.getTime()) ? report.generated_at : date.toLocaleDateString();
  }, [report.generated_at]);
```

替换为：

```tsx
  const formattedDate = useMemo(() => {
    const date = new Date(report.generated_at);
    if (Number.isNaN(date.getTime())) return report.generated_at;
    // P0-4: 显示完整时间，让用户知道数据时效
    const pad = (n: number) => String(n).padStart(2, '0');
    return `基于 ${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())} 数据生成`;
  }, [report.generated_at]);
```

- [ ] **Step 4.2: 检查 formattedDate 的所有消费方**

```bash
cd frontend && grep -rn "formattedDate" src/
```

确认 `ReportHeader.tsx` 和 `ReportCockpit.tsx` 中 `{formattedDate}` 的展示位置文案通顺
（原来是 "2026-05-29"，现在是 "基于 2026-05-29 14:32 数据生成"）。
若某处只需要短日期（如紧凑卡片），给 ReportHeader 加一个截断处理或保留两个变量。

- [ ] **Step 4.3: 构建验证**

```bash
cd frontend && npm run build
```
预期：构建成功

- [ ] **Step 4.4: 提交（需主人同意）**

```bash
git add frontend/src/components/report/
git commit -m "feat(trust): report shows full generation timestamp (P0-4)"
```

---

## Task 5: CN Screener 降级显式提示（P0-5）

**问题:** CN 市场用户点筛选 → FMP 失败 → 静默降级返回**美股**热门列表，capability_note 是一行英文小字。

**Files:**
- Modify: `backend/tools/screener.py:32-43`（`_yfinance_screen_stocks`）
- Test: `backend/tests/test_screener_cn_no_silent_fallback.py`（新建）

- [ ] **Step 5.1: 写失败测试**

创建 `backend/tests/test_screener_cn_no_silent_fallback.py`：

```python
"""P0-5: CN/HK 市场筛选不得静默降级为美股热门列表"""
from backend.tools.screener import _yfinance_screen_stocks


def test_cn_market_fallback_returns_explicit_error():
    """CN 市场降级时必须返回明确错误，不得返回美股列表"""
    result = _yfinance_screen_stocks("CN", {}, 20, "marketCap", "desc")

    assert result.get("success") is False
    assert "CN" in str(result.get("error", "")) or "A股" in str(result.get("error", ""))
    assert result.get("items") == [] or result.get("items") is None


def test_hk_market_fallback_returns_explicit_error():
    result = _yfinance_screen_stocks("HK", {}, 20, "marketCap", "desc")
    assert result.get("success") is False


def test_us_market_fallback_still_works():
    """US 市场降级到热门股仍允许，但 capability_note 必须中文且明确"""
    result = _yfinance_screen_stocks("US", {}, 5, "marketCap", "desc")
    if result.get("success"):
        note = str(result.get("capability_note", ""))
        assert "热门" in note or "popular" in note.lower()
```

- [ ] **Step 5.2: 运行测试确认失败**

```bash
python -m pytest backend/tests/test_screener_cn_no_silent_fallback.py -v
```
预期：前两个 FAIL（当前 CN 也返回美股列表）。
注意：第三个测试依赖 yfinance 网络调用，若环境无网络可 mock `yf.Ticker`。

- [ ] **Step 5.3: 修改 `backend/tools/screener.py:32-43`**

将：

```python
def _yfinance_screen_stocks(
    market: str,
    filters: dict[str, Any] | None,
    limit: int,
    sort_by: str,
    sort_order: str,
) -> dict[str, Any]:
    """Fallback screener using yfinance when FMP is unavailable."""
    market_norm = str(market or "US").strip().upper()

    # Directly use popular stocks approach - more reliable than Screener API
    return _yfinance_popular_stocks(market_norm, filters, limit, sort_by, sort_order)
```

替换为：

```python
def _yfinance_screen_stocks(
    market: str,
    filters: dict[str, Any] | None,
    limit: int,
    sort_by: str,
    sort_order: str,
) -> dict[str, Any]:
    """Fallback screener using yfinance when FMP is unavailable."""
    market_norm = str(market or "US").strip().upper()

    # P0-5: CN/HK 市场无法用美股热门列表代替筛选——诚实报错，绝不静默换内容
    if market_norm in {"CN", "HK"}:
        return {
            "success": False,
            "market": market_norm,
            "items": [],
            "count": 0,
            "error": f"{market_norm} 市场筛选暂不可用（主数据源 FMP 不可达，且无可用的 {market_norm} 备用筛选源）",
            "capability_note": "A股/港股筛选能力建设中，当前仅支持美股筛选",
        }

    # US 市场允许降级到热门股，但必须明确标注
    result = _yfinance_popular_stocks(market_norm, filters, limit, sort_by, sort_order)
    if result.get("success"):
        result["capability_note"] = "⚠️ 主数据源不可用，当前展示的是美股热门股票快照（非筛选结果）"
    return result
```

- [ ] **Step 5.4: 运行测试确认通过**

```bash
python -m pytest backend/tests/test_screener_cn_no_silent_fallback.py -v
```
预期：PASS

- [ ] **Step 5.5: 提交（需主人同意）**

```bash
git add backend/tools/screener.py backend/tests/test_screener_cn_no_silent_fallback.py
git commit -m "fix(screener): CN/HK no silent fallback to US popular stocks (P0-5)"
```

---

## Task 6: Rebalance 按钮语义澄清（P0-6，已更正范围）

**审计更正:** 复查发现 Rebalance **没有**假执行按钮（按钮为 接受/拒绝/发送到对话/导出，
均为真实功能），且已有 `DisclaimerBanner.tsx` 常驻免责横幅。
原 P0-6 "移除假执行按钮"基于误判，**降级为按钮语义澄清**。

**Files:**
- Modify: `frontend/src/components/workbench/rebalance/ActionButtons.tsx:123-134`
- Modify: `docs/plans/2026-06-02_product_trust_overhaul_roadmap.md`（更正记录）

- [ ] **Step 6.1: 按钮文案语义澄清**

`ActionButtons.tsx` 中将"全部接受"/"全部拒绝"改为"全部标记接受"/"全部标记拒绝"，
避免用户误以为"接受 = 系统会自动执行交易"：

```tsx
          <Button variant="primary" size="sm" onClick={onAcceptAll}>
            <CheckCheck size={14} />
            全部标记接受
          </Button>
          <Button variant="ghost" size="sm" onClick={onRejectAll}>
            <XCircle size={14} />
            全部标记拒绝
          </Button>
```

- [ ] **Step 6.2: 在路线图文档更正 P0-6**

`docs/plans/2026-06-02_product_trust_overhaul_roadmap.md` 第 11 节"上轮审计结论的更正"表格中追加一行：

```markdown
| "Rebalance 执行按钮是摆设" | **有误**。无执行按钮（按钮为标记接受/发送到对话/导出，均真实功能），且已有免责横幅。P0-6 降级为文案澄清 |
```

- [ ] **Step 6.3: 构建验证 + 提交（需主人同意）**

```bash
cd frontend && npm run build
git add frontend/src/components/workbench/rebalance/ActionButtons.tsx docs/plans/
git commit -m "fix(rebalance): clarify accept button semantics, correct audit record (P0-6)"
```

---

## Task 7: HTTP 限流默认开启（P0-7）

**问题:** `RATE_LIMIT_ENABLED` 默认 `"false"`，公网部署裸奔。
（注：LLM 限流 `LLM_RATE_LIMIT_ENABLED` 默认已是 `"true"`，无需修改。）

**Files:**
- Modify: `backend/api/main.py:784`
- Test: `backend/tests/test_rate_limit_default_on.py`（新建）

- [ ] **Step 7.1: 写失败测试**

创建 `backend/tests/test_rate_limit_default_on.py`：

```python
"""P0-7: HTTP 限流必须默认开启"""


def test_rate_limiter_enabled_by_default(monkeypatch):
    monkeypatch.delenv("RATE_LIMIT_ENABLED", raising=False)
    from backend.api.main import SimpleRateLimiter

    limiter = SimpleRateLimiter.from_env()
    assert limiter.enabled is True, "公网产品 HTTP 限流必须默认开启"


def test_rate_limiter_can_be_disabled_explicitly(monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "false")
    from backend.api.main import SimpleRateLimiter

    limiter = SimpleRateLimiter.from_env()
    assert limiter.enabled is False
```

- [ ] **Step 7.2: 运行测试确认失败**

```bash
python -m pytest backend/tests/test_rate_limit_default_on.py -v
```
预期：第一个 FAIL

- [ ] **Step 7.3: 修改 `backend/api/main.py:784`**

将：

```python
        enabled = _env_bool("RATE_LIMIT_ENABLED", "false")
```

替换为：

```python
        enabled = _env_bool("RATE_LIMIT_ENABLED", "true")  # P0-7: 公网产品限流默认开启
```

- [ ] **Step 7.4: 检查现有测试是否依赖默认关闭**

```bash
python -m pytest backend/tests/ -k "rate or limit or api" -v
```

若有测试因限流 429 失败，给该测试的 fixture/setup 加 `monkeypatch.setenv("RATE_LIMIT_ENABLED", "false")`，
保持测试隔离（测试环境显式关闭，生产默认开启）。

- [ ] **Step 7.5: 运行全部测试确认通过 + 提交（需主人同意）**

```bash
python -m pytest backend/tests/test_rate_limit_default_on.py -v
git add backend/api/main.py backend/tests/
git commit -m "fix(security): HTTP rate limit enabled by default (P0-7)"
```

---

## Task 8: 紧急熔断开关（P0-8）

**问题:** 发生滥用时只能改代码重启止血。

**Files:**
- Modify: `backend/api/chat_router.py:94-96, 227-229`（两个报告生成入口）
- Test: `backend/tests/test_emergency_kill_switch.py`（新建）

- [ ] **Step 8.1: 写失败测试**

创建 `backend/tests/test_emergency_kill_switch.py`：

```python
"""P0-8: REPORTS_GENERATION_ENABLED=false 时报告生成必须返回 503"""
import pytest


def test_kill_switch_helper_blocks_when_disabled(monkeypatch):
    monkeypatch.setenv("REPORTS_GENERATION_ENABLED", "false")
    from backend.api.chat_router import _generation_enabled

    assert _generation_enabled() is False


def test_kill_switch_helper_allows_by_default(monkeypatch):
    monkeypatch.delenv("REPORTS_GENERATION_ENABLED", raising=False)
    from backend.api.chat_router import _generation_enabled

    assert _generation_enabled() is True
```

- [ ] **Step 8.2: 运行测试确认失败**

```bash
python -m pytest backend/tests/test_emergency_kill_switch.py -v
```
预期：FAIL（`_generation_enabled` 不存在）

- [ ] **Step 8.3: 在 `backend/api/chat_router.py` 添加开关函数**

在文件顶部 import 区之后、`def create_chat_router(...)` 或第一个路由定义之前加：

```python
def _generation_enabled() -> bool:
    """P0-8: 紧急熔断开关。设 REPORTS_GENERATION_ENABLED=false 可立即停止所有报告生成。"""
    return str(os.getenv("REPORTS_GENERATION_ENABLED", "true")).strip().lower() not in {"false", "0", "off"}
```

（确认文件已 `import os`，没有则补。）

- [ ] **Step 8.4: 在两个生成入口加检查**

`chat_router.py:95`（`chat_supervisor_endpoint`）和 `:228`（`chat_supervisor_stream_endpoint`）
两个函数体的**第一行**加：

```python
        if not _generation_enabled():
            raise HTTPException(
                status_code=503,
                detail="服务临时维护中，报告生成已暂停，请稍后再试",
            )
```

（确认文件已 `from fastapi import HTTPException`，没有则补。）

- [ ] **Step 8.5: 运行测试确认通过 + 提交（需主人同意）**

```bash
python -m pytest backend/tests/test_emergency_kill_switch.py backend/tests/ -k "chat" -v
git add backend/api/chat_router.py backend/tests/test_emergency_kill_switch.py
git commit -m "feat(security): emergency kill switch REPORTS_GENERATION_ENABLED (P0-8)"
```

---

## 完成检查清单

全部 8 个任务完成后：

- [ ] 运行后端全量测试：`python -m pytest backend/tests/ -x -q`
- [ ] 前端构建：`cd frontend && npm run build`
- [ ] 更新 goal 记忆文件的执行状态（P0-1 ~ P0-8 打勾）
- [ ] 更新路线图文档：P0 各项标记完成状态
- [ ] 向主人汇报：哪些做完、哪些有偏差、测试结果
