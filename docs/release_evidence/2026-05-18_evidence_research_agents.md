# Evidence Research Agents 发布证据

日期：2026-05-18  
分支：`feature/evidence-research-agents`  
基线：`ac70158807f8d01513b6846b370a2d9122ec45c3` (`main`)  
范围：`main..feature/evidence-research-agents`

## 变更摘要

- 新增 Evidence Ledger 合同与 artifact builder，统一 claim/source/uncertainty/contradiction/coverage 结构。
- 在 `execute_plan -> research_debate -> synthesize` 主链路中接入可开关的多空辩论节点。
- DeepSearch 新增阶段化 flow facade，并把新 working set 命名收敛到 `ws:deepsearch:*`。
- 新增 US-only SEC 13F / Form 4 公开持仓工具、持仓意图规划和组合 overlap 入口。
- 报告页新增 Evidence Ledger、Debate Scorecard、Holdings Watch 与 query coverage warning。
- 新增只读研究 API、MCP facade、A2A agent card/long-task adapter；协议适配默认关闭。
- 新增 Evidence Research eval 数据集和 smoke runner。

## 主要提交

- `907fcd3` docs: add evidence research agent plan
- `2e0c5bb` chore: normalize README casing
- `5c931f2` feat: add evidence ledger contract
- `1e61286` feat: add SEC holdings tools
- `40f0220` feat: show evidence ledger and debate panels
- `8186c3c` feat: add query coverage contract
- `d659ccb` feat: extract agent claim metadata
- `5d29bac` feat: plan holdings-aware research tasks
- `ca06d01` feat: build evidence ledger from execution artifacts
- `3e0e3fe` feat: add evidence-based research debate node
- `8365641` feat: structure deep research flow around evidence ledger
- `241063c` test: add evidence research evaluation gate
- `e644006` feat: add read-only MCP protocol server
- `d0c24af` feat: expose read-only research artifacts
- `a52c346` feat: add protocol-ready A2A adapter

## 验证记录

| 命令 | 结果 |
|---|---|
| `python -m pytest backend\tests\test_evidence_ledger_contract.py backend\tests\test_evidence_ledger_execute_plan.py backend\tests\test_query_coverage_contract.py backend\tests\test_agent_claim_extractor.py backend\tests\test_deep_research_flow.py backend\tests\test_research_debate.py backend\tests\test_sec_holdings_tools.py backend\tests\test_holdings_planning.py backend\tests\test_research_router.py -q` | `37 passed` |
| `python -m pytest backend\tests\test_understand_request.py backend\tests\test_langgraph_skeleton.py backend\tests\test_policy_gate.py backend\tests\test_reply_contract_lanes.py backend\tests\test_evidence_diagnostics_gate.py -q` | `82 passed`；`test_langgraph_skeleton.py` 已更新预期节点顺序，包含 `research_debate` |
| `python -m pytest tests\rag_qualityV2\test_gate_v2.py -q` | `5 passed` |
| `npm --prefix frontend run test:unit` | `6 passed` test files，`25 passed` tests |
| `npm --prefix frontend run build` | 退出码 0，Vite build 完成；仅提示 browserslist 数据较旧 |
| `python -m pytest backend\tests\test_evidence_research_eval_smoke.py -q` | `2 passed` |
| `python scripts\evidence_research_eval.py --dataset tests\eval\evidence_research_cases.json --run-id local-evidence` | `8 PASS, 0 FAIL` |
| `python -m pytest backend\tests\test_mcp_server_contract.py -q` | `4 passed` |
| `python -m compileall backend` | 退出码 0 |
| `python -m pytest backend\tests\test_a2a_contract.py backend\tests\test_execution_stage_events.py backend\tests\test_streaming_sse.py -q` | `11 passed` |

## Chat Router Eval 状态

命令：

```powershell
python scripts\chat_ux_router_eval.py --dataset tests\eval\chat_router_100.json --run-id evidence-branch
```

当前环境结果：退出码 1，`71 PASS / 2 REVIEW / 27 FAIL`。运行日志反复出现：

```text
No LLM endpoint configured. Provide user_config.llm_endpoints[] or llm_api_key/llm_api_base, or set OPENAI_COMPATIBLE_API_KEY / GEMINI_PROXY_API_KEY.
```

结论：

- 本次不把 `docs/qa/chat-router-100-eval.*` 当作通过证据提交。
- 当前失败属于未配置 LLM endpoint 下的真实阻塞状态，不能声明 chat UX gate 通过。
- 配置 `OPENAI_COMPATIBLE_API_KEY` / `GEMINI_PROXY_API_KEY` 或 `user_config.llm_endpoints[]` 后，需要用 `--run-id evidence-final` 重新跑 100-query gate。

## Feature Flags

默认启用：

- `RESEARCH_LEDGER_ENABLED=true`
- `QUERY_COVERAGE_ENABLED=true`

默认关闭：

- `DEBATE_GRAPH_ENABLED=false`
- `SEC_HOLDINGS_ENABLED=false`
- `MCP_SERVER_ENABLED=false`
- `A2A_SERVER_ENABLED=false`
- `A2A_PUBLIC_URL=`

## 边界与风险

- 13F 是季度披露且有延迟，不能当实时交易信号。
- Form 4 只表示公开披露交易记录，不推断隐藏意图，不构成投资建议。
- MCP/A2A 当前是只读 protocol-ready facade，不做跨厂商 Agent 委派，也不执行写操作。
- `scripts/evidence_research_eval.py` 是 contract smoke，主要验证 artifact shape 和安全边界，不替代真实 graph/API 端到端评估。
- 前端 `test:unit` 已限定到 `src`，E2E 仍由 `npm --prefix frontend run test:e2e` 独立负责。
