# 2026-05-02 前端 RAG Inspector 三层可观测

状态：已完成前端小批次

## 本批范围

- RAG Inspector 深链支持 `run_id + collection + layer`，复制链接后能回到同一条 run 与集合上下文。
- 查询详情请求增加 runId 防串保护，切换 run 时先清空旧 bundle，避免慢请求把旧详情写回当前视图。
- 查询总览、命中、原始文档、chunk 和 collection 卡片展示 `layer / collection_kind / entity_scope / entity_key`。
- 新增“三层命中占比”视图，优先用实时 hits 汇总，缺失时回退到 run metadata 的 `layer_hit_breakdown`。
- DB Browser 支持 `layer` 过滤，并将三层字段提前到表格优先列。

## 验证

```powershell
npx vitest run src/pages/ragInspectorStatus.test.ts
npx vitest run src
npm run build
```

结果：

```text
src/pages/ragInspectorStatus.test.ts: 2 passed
npx vitest run src: 9 passed
npm run build: passed
```

说明：本批只收口 Inspector 前端展示与深链，不提交文档归档清理、`.omx/`、截图或后端 agent 文件的既有脏改动。
