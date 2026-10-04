# 2026-10-04 请求、证据与完整性修复

本目录是一次性实施与验收记录，不替代当前架构文档。

- [修复与原因](REPAIR.md)
- [验收、发布与后续动作](ACCEPTANCE.md)
- [原12题组合回归评分](regression-scores.json)
- [组合回归回答原文](regression-answers.md)
- [第二批独立题首轮评分](holdout-scores.json)与[回答](holdout-answers.md)
- [最终发布与新题冻结快照差异](release-vs-holdout.json)
- [发布与真实账号交付](RELEASE.md)
- 原始首次基线保存在 [独立验收归档](../2026-10-04-independent-acceptance/README.md)。

基线、修复后的回归、新问题首次验收必须分别解读。相同旧题不能再次算独立泛化成绩，模型调用成功也不能替代内容正确。

完整执行状态、工具原始输出、冻结源码和私有浏览器截图保留在本地 `.omx/acceptance/2026-10-04-contract-quality-repair/`，不进入 Git。这里仅归档测试题、模型生成的公开金融回答和脱敏评分，不含账号凭据或生产配置。
