# FinSight-audit 项目边界

## 当前架构

- `backend/graph/planning/`：请求理解后的计划生成、依赖与策略约束。
- `backend/graph/policy/`：执行前的能力、证据和安全边界。
- `backend/graph/execution/`：计划执行、工具证据收集与执行观测。
- `backend/graph/synthesis/`、`backend/graph/renderers/`：结果合成和不同回答形态的渲染。
- `backend/agents/`：专项研究能力；公共质量合同应集中复用，避免各 Agent 自建协议。
- `backend/rag/`：memory / working set / knowledge base 的摄取、检索与观测。
- `frontend/src/`：用户交互、状态和诊断界面；后端契约变化必须同步类型与测试。

## 修改规则

- 先确认当前请求属于 planning、policy、execution、synthesis 或 rendering，再修改对应边界。
- 不恢复已迁移的 `*_stub.py` 或旧节点实现；需要兼容时使用薄适配层。
- 不把历史变更日志继续追加到本文件；历史说明已归档到 `docs/archive/2026-07-overhaul-closeout/superseded/agents-architecture-history.md`。
- 保留用户未提交改动，不执行无关格式化、批量重命名或顺手重构。
- 面向人的注释、文档和日志使用中文；代码标识符使用英文。

## 验证

- Python 改动先运行受影响的定向 pytest；跨层契约再运行对应集成测试。
- 前端改动先运行相关单测；涉及交互时再使用 Playwright 验证关键路径。
- 同一失败命令最多原样重试一次；失败后根据错误定位根因。
- 未经用户明确要求，不提交、推送或重置 Git。
