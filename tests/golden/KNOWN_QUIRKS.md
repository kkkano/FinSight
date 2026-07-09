# 金样快照审读——已知怪癖（基线 4a1c055 现状，只记录不修）

录制环境：LLM router 不可用（走确定性 fallback 规则）+ executor dry-run。

1. **cn_ticker（"600036 走势如何"）：route=research 但 tasks=[] 且 plan_steps=[]**
   A股裸 6 位代码在规则 fallback 路径下没有产生任何公司任务——research 空转。
   预期归宿：WP2 T3 意图管线重排后由 signals.extract_signals 统一识别；若仍空，升级为 bug 修复。
2. **greeting（"你好"）：route=None**
   chat_respond 提前终止路径不写 understanding.route。行为正确，但 route 语义缺失，
   WP2 T3 的 IntentFrame 会给 direct 一个显式 route 值（预期 diff，记录在案）。
3. **multi_question：任务分解正确（compare + 2×investment_opinion + macro）**，
   但渲染端不分节（ORC-11）——WP2 T10 的靶子，改后 v2 快照预期在渲染层出现差异（本切片不含渲染文本，应零 diff）。

---

## WP2 Task11 收尾审读（2026-07-08）

金样确定性环境已固定四 flag 全 on（LLM-off 下新旧路径逐字节一致，无独立 v2 快照目录）。
上述怪癖均属 **LLM 不可用时的 fallback 规则路径**，在新引擎下的状态：

1. cn_ticker 空转：fallback 路径仍保留（快照未变）——LLM router 可用时由 hints 正常产任务；
   fallback 侧行为在 WP3-T3 已随关键词瀑布**物理搬家**至 `backend/graph/intent/legacy_engine.py`
   （零行为变更约束，怪癖原样保留）；行为级修复留待带行为预算的任务（09/WP6 范畴）。
2. greeting route=None：仍是 chat_respond 提前终止路径，行为正确，保持现状。
3. multi_question 渲染不分节：**已修**（WP2-T10 render_task_sections）——但仅在
   task_results 按 task id 聚合且 ≥2 个非空 subject_label 时生效（LLM hints 路径）；
   fallback 路径的 task_results 仍按 primary_company 等分组键聚合，不触发分节。
