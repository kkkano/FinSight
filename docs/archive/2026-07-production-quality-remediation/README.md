# 2026-07 生产质量修复归档

本目录保存 2026-07-14 至 2026-07-15 的 FinSight 生产质量审计、WP0-WP6 实施规范和一次性发布证据。

## 原路径映射

- `12_PRODUCTION_QUALITY_REMEDIATION_SPEC.md`：原 `docs/12_PRODUCTION_QUALITY_REMEDIATION_SPEC.md`，完成实现、灰度、正式部署与一次性验收后归档。

## 归档边界

- 本目录不作为当前运行时事实源，不应被新代码依赖。
- 当前架构以 `docs/01_ARCHITECTURE.md`、`docs/LANGGRAPH_FLOW.md` 与 `docs/LANGGRAPH_PIPELINE_DEEP_DIVE.md` 为准。
- 当前部署、冒烟和回滚方法以 `docs/11_PRODUCTION_RUNBOOK.md` 为准。
- 归档证据只记录非敏感摘要，不包含主机、账号、密码、token、Cookie、代理凭据或完整私有端点。

## 收口说明

WP0-WP6 已实现并部署到正式环境。归档 Spec 第 20 节记录了 canary、正式冒烟、浏览器验收、容量清理、回滚标签与已知限制；其中 24 小时连续观察和实施前已存在的 910/900 静态门禁偏差未伪装为完成。
