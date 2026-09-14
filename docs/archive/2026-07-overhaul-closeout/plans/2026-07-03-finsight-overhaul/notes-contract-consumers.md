# 双轨表示消费方清单（WP2-T4 盘点，供 WP3 清理时用）

## 关键事实修正
spec T4 假设 `intent_contract_mode()` 默认 shadow（实验态）——**实际默认 enforce（生产现役）**：
`backend/graph/intent_contract.py:299` 默认 "enforce"。request_frame/intent_contract 是当前
required_evidence 机制的现役实现，不是影子。强改默认值=破坏行为，T4 不动它。
其归宿改判：WP3-T3 时把 intent_contract 收编进 backend/graph/intent/ 包（作为
IntentTask.required_evidence 的编译器），enforce 分支保留。

## understanding_v2（已冻结 off）
- 写入方: understand_request.py:3243（默认已改 off）
- 消费方: 无（grep 全仓仅 trace/诊断读取）→ WP3 可安全删除 build_understanding_v2

## intent_contract / request_frame(s) 消费方（enforce 现役，WP3 收编时逐一处理）
- policy_gate.py:369-372（request_frames 读取）、:622（intent_contract.required_evidence）
- synthesize.py:1622-1631、:2637（is_research_compare_contract）
- planner_stub.py（task required_evidence 透传）
- chat_renderer.py / render_stub.py / compare_gate.py / coverage_validator.py / reset_turn_state.py
- 新管线注意：FINSIGHT_INTENT_FRAME=on 的 LLM-hints 路径暂不产 request_frame/intent_contract
  （fallback 路径产）→ on 模式灰度观察期需盯 policy_gate 的 required_evidence 覆盖率
