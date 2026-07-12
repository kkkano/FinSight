# Task 9 全链路署名盘点

## 执行日志

- `AgentWorkLog` 的运行数据只有 Agent key，身份展示此前来自前端 `userMessageMapper.AGENT_DISPLAY_NAMES` 硬编码。
- 仓库不存在 spec 提到的 `src/config/agentLabels.ts`；本任务按代码事实改为读取 `/api/agents`，并以用户身份为缓存键，避免把租户战绩跨账号复用。
- API 暂不可用时只回退展示规范化 key，不伪造中文身份。

## 监控发现

- L1 `Finding` 没有 Agent 身份；真实归属字段是 `trigger_type`，对应价格异动、集中度风险、舆情突变、财报临近、宏观事件五类确定性规则。
- L2 `agent_analysis.agent` 才是实际执行深析的 Agent key，可用 `/api/agents` 档案展示 glyph、中文姓名与色彩。
- 因此 L1 卡片标注“由{规则名}规则发现”，L2 分析区块按真实 Agent 署名；不把 L1 规则发现冒充为 Agent 发现。

## 晨报

- 当前晨报无论 Graph 路径还是直接 fallback，都是零 LLM 的价格/新闻工具聚合；现有 `highlights` 不带 Agent 产出归属。
- 前端合同只增加可选 `highlight.analyst` 快照，并仅在后端明确附带时显示 `short_zh` chip。
- 现有确定性晨报保持无 Agent chip，避免伪造署名；未来若晨报真正消费 Agent 输出，可直接随要点传入同源档案快照。
