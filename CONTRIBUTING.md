# FinSight 贡献指南

更新：2026-11-13。当前研究实现是 `backend/agent_runtime/`。本文适用于当前源码，实际生产版本和验收状态见[运行手册](docs/11_PRODUCTION_RUNBOOK.md)。

## 环境与启动

使用 Python 3.11+、Node.js 20.19+ 或 22.12+、npm，以及 PostgreSQL 16/pgvector。Node 范围取自当前锁定的 Vite 包；前端以 `frontend/package-lock.json` 和 `npm ci` 为准。

```bash
python -m venv .venv
# Windows：.venv/Scripts/python；macOS/Linux：.venv/bin/python
python -m pip install -r requirements.txt
```

开发配置放入被 Git 忽略的 `.env.runtime.local`。研究模型至少提供 `FINSIGHT_AGENT_API_BASE`、`FINSIGHT_AGENT_MODEL`、`FINSIGHT_AGENT_API_KEY`；核心业务使用 `FINSIGHT_POSTGRES_DSN` 和已迁移的数据库，前后端登录配置指向同一个 Supabase 项目。

```bash
# 先把选定开发数据库的 DSN 提供给环境，再运行迁移。
python -m alembic upgrade head
python scripts/run_agent_runtime.py --env-file .env.runtime.local --host 127.0.0.1 --port 8000
npm ci --prefix frontend
npm run dev --prefix frontend
```

Alembic 使用根目录 `alembic.ini` 与 `migrations/`。应用启动验证 schema，不通过隐式 DDL 修复生产数据库。配置项和默认值以 [settings.py](backend/config/settings.py)、[开发模板](.env.example)和[服务端模板](.env.server.example)为准。

完整容器环境沿用 `docker compose --env-file .env.server`。默认运行 PostgreSQL、API 和前端；`compute`、`local-ml`、`predictions` 是独立可选 profile，启用条件见运行手册。真实密钥不进入源码、前端变量、构建参数或提交。

## 代码边界

| 位置 | 责任 |
|---|---|
| `backend/api/` | 认证、参数、owner、额度、受理与 SSE 订阅 |
| `agent_runtime/loop.py` | 主研究员与专业角色共用原生模型流和工具事务 |
| `registry.py`、`envelope.py`、`adapters/` | 实际 schema、角色权限、统一结果与资料登记 |
| `verifier.py`、`finalize.py` | 只读核查、交付覆盖、有界追加及保留旧版本的修订 |
| `data.py`、`citations.py`、`compactor.py` | 原始资料、整数引用、回读和上下文压缩 |
| `backend/analysis_worker/` | 独立 Docker 作业和 finsight 计算库 |
| `backend/rag/` | 按用户/会话/知识 scope 摄取、检索与观测 |
| `backend/services/` | 持久化、独立预测、行情和公共服务 |
| `frontend/src/api/`、`store/` | 分域 API、SSE、OpenAPI 类型及按域组合的用户状态 |
| `tests/agent_eval/` | 固定题集、资料录制/回放、独立评分和冻结历史对照 |

模型依据问题和真实工具结果选择下一步。禁止用用户原话或模型正文的正则、关键词分支决定研究意图、补发工具或套答案模板。确定性代码执行机器协议、数据口径、权限、额度和持久化合同。

主研究员最多委派一层专业角色，共享本轮数据和额度，不能扩大权限。模型失败、工具失败、资料不足、预算耗尽与核查不可用保留各自结构状态。已流出的正文保留，核查标注与新版本分开。

固定 US20 的 forecast、依赖、输入窗口、模型和 strategy_version 是冻结实验协议；按[清单](tests/agent_eval/reference/manifest.json)核对 27 个 protected files。用户 Prediction/Outcome 与公开账本分开，研究配置不改变冻结预测默认。退役源码只用于评测，不恢复生产旧图。

## 验证

先运行受影响的协议或集成测试，避免为每种自然语言措辞写实现镜像测试。

```bash
python -m pytest backend/tests/test_agent_runtime.py backend/tests/test_runtime_envelope.py -q
npm run test:unit --prefix frontend
npm run build --prefix frontend
```

跨层变更覆盖相关 SSE、持久化、身份和前端测试。发布前必要广泛验证最多一轮，失败定位后只重跑对应范围。Playwright 配置启动 `127.0.0.1:4273`；夹具覆盖与真实登录、行情、生产验收分别记录。

答案质量由[评测入口](tests/agent_eval/README.md)的 60 题同模型、同资料、同调度回放和独立评分衡量；核查另测正确/注错配对样本。48 项产品验收逐项保存输入、运行或截图和结论。跳过、未知传输失败、缺评分和未执行不能记作通过。

前端产物不得包含测试 fixtures、模型密钥或退役执行面板。图表通过真实字段和 artifact 合同生成，ECharts 按需加载；主题、涨跌色与成功/失败色各自独立。

## 文档、提交与发布

改边界或协议时同步架构、事件合同、模型/RAG/预测规范、OpenAPI 类型和 Mermaid。新增当前文档同步 [DOCS_INDEX.md](docs/DOCS_INDEX.md)；旧规范归档并记录原路径、原因和替代入口，不把历史实测改为当前成绩。

`prompts/*.md`、`skills/*.md` 是运行时输入；修改属于模型行为变更，需要重建候选并重新绑定评测。固定题集和冻结清单也不能按当前失败结果篡改。

提交采用可解释的原子变更，例如 `refactor(runtime): unify native tool execution` 或 `docs: reconcile current architecture`。保留已有改动；只有用户授权时提交、推送、删除、迁移或部署。发布关联实际源码、镜像摘要、模型/配置和验证报告，按运行手册执行质量、容量、备份、回滚、真实身份与观察门槛。
