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
