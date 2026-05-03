# RAG 三层架构（长期 KB / Working Set / 对话记忆）改造 TODO

更新时间：2026-03-08
状态：首版已落地（持续迭代中）
适用范围：FinSight Chat、DeepSearch、RAG、检索编排、知识库治理、RAG Inspector

---

## 0. 当前进度（2026-03-08）

### 0.1 已完成

- [x] 后端新增三层 collection 解析：`memory / ws / kb`
- [x] 普通执行链支持 `ws` 写入、`kb` 候选晋升、`ws + kb` 联合检索
- [x] DeepSearch working set 切到 `ws:deepsearch:*`，并支持 `kb:stock:*` 晋升/补查
- [x] `rag_documents_v2` 补充 `layer / entity_scope / entity_key / ingest_source / promotion_status / doc_fingerprint / parent_collection / parent_run_id`
- [x] Observability / retrieval hits 已记录 layer、collection_kind、entity 语义
- [x] RAG Inspector 已支持 layer badge、search path、collection 深链、selected collection 高亮
- [x] DB Browser 已支持 `layer` 过滤
- [x] 前端构建通过，后端定向测试通过

### 0.2 进行中

- [ ] 将更多普通 Chat 流量统一接入三层检索编排
- [ ] 继续细化长期 KB 晋升门槛与人工治理入口
- [ ] 为长期 KB / Working Set / 对话记忆补更细的 UI 指导说明

### 0.3 未开始

- [ ] 人工上传长期 KB 文档入口
- [ ] 定时抓取官方资料并直写长期 KB
- [ ] 历史存量文档回填和 fingerprint 去重迁移
- [ ] 审计权限、晋升审批、删除治理闭环

### 0.4 本轮验证

- [x] `npm --prefix frontend run build`
- [x] `pytest backend/tests/test_rag_v2_service.py backend/tests/test_trace_and_session_security.py backend/tests/test_rag_observability_store.py backend/tests/test_rag_observability_system_router.py backend/tests/test_rag_observability_execute_plan.py backend/tests/test_live_tools_evidence.py -q`

---

## 1. 冻结目标

- [ ] 将当前混合型 RAG 拆分为三层：`对话记忆`、`Working Set`、`长期 KB`
- [ ] 明确区分“聊天上下文”“本次任务材料”“长期可复用知识”三类数据
- [ ] 普通 Chat 默认不自动写入长期 KB
- [ ] DeepSearch / 研报 / 财报解读支持将高质量材料晋升为长期 KB
- [ ] 长期 KB 采用股票级 / 主题级 collection，而不是单一用户大桶
- [ ] 检索顺序调整为：`对话记忆 -> Working Set -> 长期 KB -> 实时工具 / Web`
- [ ] 所有写入、晋升、命中都必须可观测、可回放、可解释

---

## 2. 背景与问题

### 2.1 当前现象

- [ ] 当前系统里 `RAG` 同时承担了“本次工作流资料筐”和“可复用知识库”两种职责
- [ ] `DeepSearch` 与普通 Chat 的 `collection` 规则不同，复用路径不清晰
- [ ] 用户很难回答“这条内容为什么会在库里”“为什么这次查到了它”
- [ ] 聊天上下文、agent evidence、网页抓取、财报原文在概念上混在一起
- [ ] Inspector 能看表，但还不能自然表达“三层语义”

### 2.2 根因结论

- [ ] 现在最大问题不是“有没有向量库”，而是“缺少层级边界”
- [ ] 现在最大问题不是“有没有数据”，而是“没有明确的入层规则、晋升规则和检索顺序”
- [ ] 如果不先拆层，后面继续加功能只会让 `collection / source_id / run_id` 更难理解

---

## 3. 目标架构

### 3.1 三层定义

#### 3.1.1 对话记忆层（Conversation Memory）

- [ ] 负责保存会话态信息，而不是长期知识
- [ ] 只存：线程摘要、用户偏好、active symbol、最近上下文、指代消解信息
- [ ] 不存：大段网页原文、财报全文、长篇 research 文档

#### 3.1.2 Working Set 层（Session / Run Working Set）

- [ ] 负责保存“本次任务手上的资料”
- [ ] 只存：本轮网页抓取、新闻片段、agent evidence、临时摘要、短期切块结果
- [ ] 允许短期复用，但必须有 TTL / 软删除 / 清理策略

#### 3.1.3 长期 KB 层（Durable Knowledge Base）

- [ ] 负责保存“跨会话、跨任务可复用的稳定资料”
- [ ] 只存：财报、10-K / 10-Q、电话会、官方公告、研究纪要、人工上传 PDF、定时抓取文档
- [ ] 必须支持去重、版本化、来源审计、长期检索

### 3.2 推荐 collection 命名

- [ ] 对话记忆：`mem:thread:<thread_id>`
- [ ] 对话记忆：`mem:user:<user_id>`
- [ ] Working Set：`ws:thread:<thread_id>`
- [ ] Working Set：`ws:run:<run_id>`
- [ ] Working Set：`ws:deepsearch:<run_id>`
- [ ] 长期 KB：`kb:stock:GOOGL`
- [ ] 长期 KB：`kb:stock:MSFT`
- [ ] 长期 KB：`kb:theme:ai_capex`
- [ ] 长期 KB：`kb:macro:fed`

### 3.3 推荐检索顺序

- [ ] 先读对话记忆：解决“它 / 这家公司 / 刚才那份财报”指代问题
- [ ] 再读 Working Set：优先使用本次任务已找到的材料
- [ ] 再读长期 KB：补稳定背景知识、历史资料、公司长期材料
- [ ] 最后再补实时工具 / Web：获取最新价格、最新新闻、最新公告

---

## 4. 数据模型改造 TODO

### 4.1 基础字段

- [ ] 为 RAG 文档补充 `layer` 字段：`memory / ws / kb`
- [ ] 为 RAG 文档补充 `ingest_source` 字段：`manual_upload / scheduled_fetch / deepsearch / chat_evidence / promotion`
- [ ] 为 RAG 文档补充 `promotion_status` 字段：`none / candidate / promoted / rejected`
- [ ] 为 RAG 文档补充 `doc_fingerprint` 字段，用于长期 KB 去重
- [ ] 为 RAG 文档补充 `durability` 或 `is_durable` 字段，区分短期和长期材料
- [ ] 为 RAG 文档补充 `entity_scope` 字段，用于区分 `stock / theme / macro / generic`

### 4.2 观测字段

- [ ] 在 observability 记录里标出“这条数据属于哪一层”
- [ ] 在 observability 记录里标出“为什么写入这一层”
- [ ] 在 observability 记录里标出“是原始写入还是晋升写入”
- [ ] 在 observability 记录里标出“查询时先查了哪一层、命中了哪一层”

---

## 5. 写入判定策略 TODO

### 5.1 对话记忆层

- [ ] 闲聊、问候、感谢、元问题只更新对话记忆，不写入 Working Set 或长期 KB
- [ ] 普通问答里的“最近主题 / 当前 ticker / 当前文档引用”写入对话记忆摘要
- [ ] 对话记忆只保留轻量摘要，不做大段向量化入库

### 5.2 Working Set 层

- [ ] 普通 Chat 如产生 evidence，则默认只写 Working Set
- [ ] 新闻问答如抓取网页 / 新闻片段，则默认只写 Working Set
- [ ] DeepSearch 默认把抓到的材料先写入 Working Set
- [ ] agent 生成的 evidence / snapshot 默认只写入 Working Set
- [ ] Working Set 文档必须有 TTL，禁止无限增长

### 5.3 长期 KB 层

- [ ] 财报 / 10-K / 10-Q / 电话会文本支持直接写入长期 KB
- [ ] 人工上传 PDF / DOC / 纪要支持直接写入长期 KB
- [ ] 定时抓取的官方资料支持直接写入长期 KB
- [ ] DeepSearch / investment_report 的高质量材料允许“晋升到长期 KB”
- [ ] 普通 Chat 默认不自动写入长期 KB

---

## 6. 长期 KB 入库通道 TODO

### 6.1 人工上传通道

- [ ] 新增“上传文档到长期 KB”入口
- [ ] 支持 PDF / DOC / TXT / Markdown 等格式
- [ ] 支持选择目标 scope：`stock / theme / macro`
- [ ] 支持上传后预览原文、切块结果、元数据，再确认入库

### 6.2 定时抓取通道

- [ ] 新增官方资料定时拉取任务：SEC / 交易所 / IR 官网 / Earnings Call
- [ ] 为定时任务建立来源白名单和失败重试策略
- [ ] 抓取后统一走解析、去重、切块、入长期 KB 流程

### 6.3 晋升通道

- [ ] 从 Working Set 到长期 KB 增加“晋升”动作
- [ ] 支持自动晋升策略：高质量来源 + 高相关性 + 非重复
- [ ] 支持人工晋升按钮：从 Inspector / DB Browser 一键加入长期 KB
- [ ] 所有晋升行为都要记录审计日志

---

## 7. 晋升门槛与去重 TODO

### 7.1 晋升门槛

- [ ] 来源必须可信：SEC / IR / 交易所 / 人工上传 / 已认可研究来源
- [ ] 内容必须完整：不是一句碎片、不是纯标题、不是空摘要
- [ ] 对象必须明确：能清晰归属某股票 / 某主题 / 某宏观事件
- [ ] 元数据必须足够：至少应包含标题、来源、时间、URL 或上传信息
- [ ] 必须通过重复检测，不能把同一文档反复写入长期 KB

### 7.2 去重策略

- [ ] 定义 `doc_fingerprint` 算法：标题 + URL + 发布时间 + 正文指纹
- [ ] 同一 `kb scope + fingerprint` 默认更新，不重复新增
- [ ] 同 URL 但内容明显更新时，建立版本或更新时间链路
- [ ] 对电话会 / 财报等定期文档，支持按报告期维度唯一化

### 7.3 TTL 策略

- [ ] 对话记忆按线程摘要保留，不走长期 TTL 清理逻辑
- [ ] Working Set 默认保留 `1~30 天`
- [ ] 长期 KB 默认长期保留，不做短 TTL 自动过期
- [ ] 过期清理需要先软删除，再异步物理清理

---

## 8. 检索编排改造 TODO

### 8.1 查询顺序

- [ ] 先走对话记忆，完成 ticker / 文档 / 指代绑定
- [ ] 再查 Working Set，优先复用本轮和本线程材料
- [ ] 再查长期 KB，补稳定背景知识
- [ ] 如仍不足，再调用实时工具 / Web 搜索

### 8.2 RAGPriority 改造

- [ ] 让 `RAGPriority` 不只决定“查不查”，还要决定“先查哪层、查几层”
- [ ] `SKIP`：完全不查 RAG
- [ ] `SECONDARY`：先实时工具，再补 Working Set / 长期 KB
- [ ] `PRIMARY`：先 Working Set / 长期 KB，再补实时工具
- [ ] `PARALLEL`：按策略并发查询 Working Set / 长期 KB / live tools

### 8.3 普通 Chat / DeepSearch 对齐

- [ ] 普通 Chat 默认优先查 `ws:thread:<thread_id>`
- [ ] 普通 Chat 可按股票自动补查 `kb:stock:<ticker>`
- [ ] DeepSearch 默认优先查 `ws:run:<run_id>`
- [ ] DeepSearch 可在 Working Set 不足时补查 `kb:stock:<ticker>`

---

## 9. UI / Inspector / 可观测性 TODO

### 9.1 Inspector 展示

- [ ] 在 Inspector 中明确显示每条数据属于 `对话记忆 / Working Set / 长期 KB`
- [ ] 在 Inspector 中显示“写入原因”“写入来源”“晋升状态”
- [ ] 在 Inspector 中显示“本次查询实际先查了哪一层、命中了哪一层”
- [ ] 在 Inspector 中显示“这条长期 KB 是怎么来的（上传 / 抓取 / 晋升）”

### 9.2 DB Browser 增强

- [ ] 支持按 `layer` 过滤浏览 `rag_documents_v2`
- [ ] 支持按 `stock / theme / source / ingest_source / promotion_status` 过滤
- [ ] 支持按 `run_id / thread_id / collection` 追踪同一条数据的上下游
- [ ] 支持从一条 chunk 直接跳转到原文和命中记录

### 9.3 查询回放

- [ ] 展示本次查询的“层级检索路径”
- [ ] 展示各层命中数、召回数、重排数
- [ ] 展示哪些命中来自 `Working Set`，哪些来自 `长期 KB`
- [ ] 展示最终答案所引用的 chunk 和原文

---

## 10. 权限与治理 TODO

- [ ] 明确谁能读 Working Set
- [ ] 明确谁能读长期 KB
- [ ] 明确谁能执行“晋升到长期 KB”
- [ ] 长期 KB 默认只读，写权限收紧到管理员或显式授权用户
- [ ] 所有手动上传 / 晋升 / 删除操作记录审计日志

---

## 11. 历史数据迁移 TODO

- [ ] 盘点现有 `rag_documents_v2` 中哪些是临时 Working Set 文档
- [ ] 盘点现有 `rag_documents_v2` 中哪些具备长期 KB 候选资格
- [ ] 编写历史回填脚本，为旧文档补 `layer / ingest_source / promotion_status / fingerprint`
- [ ] 为历史 collection 做重命名 / 重新归档策略
- [ ] 先对 `GOOGL / MSFT / 财报 / 会议纪要` 做小样本迁移验证

---

## 12. 验收标准

- [ ] 能回答“这条数据为什么在这一层”
- [ ] 能回答“这次查询先查了哪几层”
- [ ] 能回答“这条长期 KB 文档是怎么进来的”
- [ ] 能证明普通 Chat 不会把闲聊和垃圾 evidence 自动灌进长期 KB
- [ ] 能证明 DeepSearch 的高质量文档可以被后续普通问答稳定复用
- [ ] 能在 Inspector 中完整回放：原文 -> chunk -> vector_doc -> retrieval_hit -> rerank_hit -> answer

---

## 13. 推荐实施顺序

### Phase 1：术语与规则冻结

- [ ] 冻结三层定义
- [ ] 冻结 collection 命名规范
- [ ] 冻结入库门槛 / 晋升门槛 / TTL 策略

### Phase 2：数据模型与写入判定

- [ ] 补层级字段和来源字段
- [ ] 从写入逻辑上拆开 `memory / ws / kb`
- [ ] 保证普通 Chat 默认不写长期 KB

### Phase 3：长期 KB 三条入库通道

- [ ] 人工上传入库
- [ ] 定时抓取入库
- [ ] Working Set 晋升入库

### Phase 4：检索编排与 UI

- [ ] 改检索顺序
- [ ] 改 RAGPriority 与层级联动
- [ ] 补齐 Inspector / DB Browser / 查询回放

### Phase 5：回填与验收

- [ ] 历史数据回填
- [ ] 样本回归测试
- [ ] 全链路实测验收

---

## 14. 一句话设计原则

- [ ] 对话记忆只回答“你刚才说了什么”
- [ ] Working Set 只回答“这次任务手里有什么材料”
- [ ] 长期 KB 只回答“以后很多次都值得复用什么”
- [ ] 用结构约束复杂度，而不是让所有材料都混进一个桶里
