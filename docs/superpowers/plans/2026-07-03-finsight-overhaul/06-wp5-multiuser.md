# WP5 多用户隔离与成本护栏 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复 SEC-01/SEC-02：后端校验 Supabase JWT 得到 `user_id`，portfolio / conversations / monitor 三类业务数据按 user_id 隔离，聊天与报告执行按用户设每日成本配额。老部署（单人自用）行为不变。

**Architecture:** 三层：`supabase_auth.py`（JWT 校验，HS256 legacy secret 或 JWKS 二选一自动探测）→ `security_gate` 里解析出 `request.state.user_id`（未登录=固定 `"public"`）→ 各 store 加 `user_id` 列 + 各 router 透传。开关 `SUPABASE_AUTH_REQUIRED`（默认 `false`：允许匿名，匿名归入 `public` 桶——与现状兼容；`true`：非白名单路径必须带有效 JWT）。

**Tech Stack:** PyJWT（确认 `requirements.txt` 是否已有：`grep -i "pyjwt\|jose" requirements.txt`；没有则批准后加 `PyJWT[crypto]==2.*`）。

## Global Constraints

- SQLite 迁移必须幂等（`PRAGMA table_info` 探测后 `ALTER TABLE ADD COLUMN`），老库无损升级。
- 匿名/存量数据统一归属 `user_id='public'`；`SUPABASE_AUTH_REQUIRED=false` 时一切行为与今天一致。
- 每个 router 改动都配隔离测试：A 用户看不到 B 用户的数据。

---

### Task 1: supabase_auth 模块

**Files:**
- Create: `backend/security/supabase_auth.py`
- Test: `backend/tests/test_supabase_auth.py`

**Interfaces:**

```python
@dataclass
class AuthenticatedUser:
    user_id: str
    email: str = ""

def verify_supabase_jwt(token: str) -> AuthenticatedUser:
    """SUPABASE_JWT_SECRET 存在 → HS256 校验（aud='authenticated'，容忍 30s 时钟偏移）；
    否则 SUPABASE_URL 存在 → 用 {SUPABASE_URL}/auth/v1/.well-known/jwks.json 的缓存 JWKS 做 RS256/ES256；
    两者都缺 → raise AuthConfigurationError。无效/过期 → raise InvalidTokenError。
    sub claim → user_id，email claim → email。JWKS 缓存 10 分钟，拉取失败用旧缓存。"""

def resolve_request_user(request: Request) -> AuthenticatedUser | None:
    """从 Authorization: Bearer 提取并校验；无头或校验失败返回 None（是否放行由调用方定）。"""
```

- [x] **Step 1: 写失败测试**（用 `jwt.encode` 现造 HS256 token 正/负用例：有效、过期、错 secret、缺 sub）：

```python
import time
import jwt
import pytest


SECRET = "test-secret"


def make_token(sub="user-1", exp_delta=3600, secret=SECRET):
    return jwt.encode({"sub": sub, "aud": "authenticated", "email": "a@b.c",
                       "exp": int(time.time()) + exp_delta}, secret, algorithm="HS256")


def test_valid_token(monkeypatch):
    monkeypatch.setenv("SUPABASE_JWT_SECRET", SECRET)
    from backend.security.supabase_auth import verify_supabase_jwt
    user = verify_supabase_jwt(make_token())
    assert user.user_id == "user-1" and user.email == "a@b.c"


def test_expired_token_rejected(monkeypatch):
    monkeypatch.setenv("SUPABASE_JWT_SECRET", SECRET)
    from backend.security.supabase_auth import verify_supabase_jwt, InvalidTokenError
    with pytest.raises(InvalidTokenError):
        verify_supabase_jwt(make_token(exp_delta=-100))


def test_wrong_secret_rejected(monkeypatch):
    monkeypatch.setenv("SUPABASE_JWT_SECRET", SECRET)
    from backend.security.supabase_auth import verify_supabase_jwt, InvalidTokenError
    with pytest.raises(InvalidTokenError):
        verify_supabase_jwt(make_token(secret="other"))
```

- [x] **Step 2-4:** 实现（按契约）→ 测试绿 → Commit：

```bash
git commit -am "feat(auth): supabase JWT verification module (HS256 secret / JWKS auto-detect)"
```

---

### Task 2: security_gate 接入 user 身份

**Files:**
- Modify: `backend/api/main.py` 的 `security_gate`（WP3 完成则是 `backend/api/security_gate.py`；锚点 `grep -rn "async def security_gate" backend/api`）
- Modify: `.env.server.example`
- Test: `backend/tests/test_security_gate_user.py`

- [x] **Step 1: 写失败测试**（`fastapi.testclient`：带有效 JWT 的请求 → 下游能读到 `request.state.user_id`；`SUPABASE_AUTH_REQUIRED=true` 时无 token 的非白名单请求 → 401；`=false` 时无 token → `user_id == "public"`）。
- [x] **Step 2: 实现**——`security_gate` 在现有 API key 检查之后插入：

```python
    user = resolve_request_user(request)
    if user is None and _env_bool("SUPABASE_AUTH_REQUIRED", "false") and not _is_allowlisted_path(request.url.path):
        return JSONResponse(status_code=401, content={"detail": "登录后才能使用，请先登录。"})
    request.state.user_id = user.user_id if user else "public"
    request.state.user_email = user.email if user else ""
```

限流 `client_id` 优先用 `f"user:{request.state.user_id}"`（非 public 时），public 保持按 IP。`.env.server.example` 登记 `SUPABASE_AUTH_REQUIRED/SUPABASE_JWT_SECRET/SUPABASE_URL`。
- [x] **Step 3:** 测试绿 + 金样零 diff + Commit：

```bash
git commit -am "feat(auth): security_gate resolves supabase user; per-user rate bucket; optional auth-required mode"
```

---

### Task 3: 三个 store 的 user_id 隔离

**Files:**
- Create: `backend/data/migrations.py`（幂等迁移助手）
- Modify: `backend/services/portfolio_store.py`、`backend/services/conversation_store.py`、`backend/services/monitor_store.py`
- Modify: `backend/api/portfolio_router.py`、`backend/api/conversation_router.py`、`backend/api/monitor_router.py`（+ 这些 store 的其他调用方：`grep -rln "portfolio_store\|conversation_store\|monitor_store" backend --include="*.py"`）
- Test: `backend/tests/test_multiuser_isolation.py`

**Interfaces:**

```python
# migrations.py
def ensure_column(conn: sqlite3.Connection, table: str, column: str, ddl: str) -> None:
    """PRAGMA table_info 探测；缺列则 ALTER TABLE {table} ADD COLUMN {ddl}。幂等。"""
# 三个 store 的每个公开函数增加关键字参数 user_id: str = "public"（排最后，默认值保证旧调用不炸），
# 所有 SELECT/UPDATE/DELETE 追加 "AND user_id = ?"，所有 INSERT 写入 user_id。
```

- [x] **Step 1: 写失败测试**

```python
def test_portfolio_isolated_between_users(tmp_path, monkeypatch):
    monkeypatch.setenv("FINSIGHT_DATA_DIR", str(tmp_path))  # 若 store 用固定路径，按其实际定位方式 monkeypatch
    from backend.services import portfolio_store
    portfolio_store.save_position(ticker="AAPL", quantity=10, user_id="alice")
    portfolio_store.save_position(ticker="TSLA", quantity=5, user_id="bob")
    alice = portfolio_store.list_positions(user_id="alice")
    assert [p["ticker"] for p in alice] == ["AAPL"]
    assert portfolio_store.list_positions(user_id="public") == []
```

（函数名以 store 实际公开面为准——先 `grep -n "^def " backend/services/portfolio_store.py` 列全，测试覆盖 list/save/delete 三类。conversation/monitor 各写同型测试。）
- [x] **Step 2: 实现**：迁移助手 → 三 store 的 `_ensure_tables` 里 `ensure_column(conn, t, "user_id", "user_id TEXT NOT NULL DEFAULT 'public'")` + 建索引 `CREATE INDEX IF NOT EXISTS idx_{t}_user ON {t}(user_id)` → 全函数加参改 SQL。
- [x] **Step 3: router 透传**：三个 router 每个 endpoint 加 `request: Request` 形参（已有则复用），调用 store 时传 `user_id=getattr(request.state, "user_id", "public")`。
- [x] **Step 4:** 隔离测试绿 + 全量绿 + 手工验证：两个浏览器（一个登录一个匿名）互看不到对方持仓/会话。
- [x] **Step 5: Commit**

```bash
git commit -am "feat(multiuser): user_id isolation for portfolio/conversation/monitor stores with idempotent sqlite migration"
```

---

### Task 4: 每用户每日成本配额（SEC-02 缓解）

**Files:**
- Modify: `backend/services/cost_audit.py`（增查询函数）、`backend/api/chat_router.py` 与 `backend/api/execution_router.py`（入口检查）
- Test: `backend/tests/test_cost_quota.py`

**Interfaces:**

```python
# cost_audit.py 新增
def today_cost_usd(user_id: str) -> float:
    """当日（UTC 日界）该 user_id 的 LLM 成本合计。cost_audit 表若无 user_id 列，
    先用 Task 3 的 ensure_column 补列（历史行归 'public'）。"""

# chat/execution 入口（发起新生成之前）：
def check_user_quota(user_id: str) -> None:
    limit = env_float("USER_DAILY_COST_LIMIT_USD", 1.0)
    if limit > 0 and user_id != "admin" and today_cost_usd(user_id) >= limit:
        raise HTTPException(status_code=429, detail=f"今日 AI 分析额度已用完（{limit:.2f} USD/天），明天再来或联系管理员提额。")
```

同时把 user_id 写进 LLM 用量埋点：`grep -rn "ContextVar" backend/services/llm_usage.py` 找到 run 级累加器，run 开始时挂上 user_id，落库带上。

- [x] **Step 1:** 失败测试（预写两条今日成本记录 → 超限用户请求 429，未超限用户 200，`USER_DAILY_COST_LIMIT_USD=0` 关闭配额）。
- [x] **Step 2-3:** 实现 → 绿 → `.env.server.example` 登记 → Commit：

```bash
git commit -am "feat(quota): per-user daily LLM cost limit on chat/execution entrypoints"
```

---

### Task 5: 部署文档与公开演示模式说明

**Files:**
- Modify: `docs/11_PRODUCTION_RUNBOOK.md`、`README_CN.md`/`README.md`

- [ ] **Step 1:** 运维手册新增小节"多用户与配额"：三种部署姿势的 env 组合表——
  1. 个人自用（默认）：全关，行为同旧版；
  2. 公开演示：`SUPABASE_AUTH_REQUIRED=false` + `USER_DAILY_COST_LIMIT_USD=0.5`（匿名共享 public 桶但有 IP 限流 + 总量兜底——明确写出"匿名数据全站共享"的告示义务）；
  3. 多用户：`SUPABASE_AUTH_REQUIRED=true` + secret/URL + 配额。
- [ ] **Step 2:** README 数据层描述修正（架构审查发现 README 宣称 PostgreSQL 存业务数据与实现不符）：改为"PostgreSQL（LangGraph checkpoint，可选）+ SQLite（业务数据）"。
- [ ] **Step 3: Commit**

```bash
git commit -am "docs(deploy): multiuser/quota deployment modes; correct data-layer claims in README"
```

---

## WP5 完成门禁

- [ ] `python -m pytest backend/tests -x -q` 全绿（含 4 组新测试）
- [ ] 手工验证矩阵：
  - `SUPABASE_AUTH_REQUIRED=false` + 匿名：功能与旧版完全一致（回归）
  - `=true` + 无 token：业务 API 401、`/health` 正常
  - 双账号：持仓/会话/监控互不可见
  - 单账号刷到配额上限：聊天 429 且报错文案友好，次日恢复
