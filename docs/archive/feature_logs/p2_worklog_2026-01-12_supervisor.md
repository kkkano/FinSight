# Supervisor Agent 架构重构日志

> 日期: 2026-01-12
> 作者: AI Assistant (幽浮喵)

---

## 背景

用户指出：成熟的多Agent系统都是用 LLM 做路由/协调，而不是写死关键词。需要重构为业界标准的 **Supervisor Agent** 模式。

### 问题分析

| 场景 | 不分类（直接Tool Calling） | 先分类再处理 |
|------|---------------------------|-------------|
| "你好" | 调用LLM + 传工具列表 = 贵 | 规则匹配直接回复 = 免费 |
| "分析苹果" | LLM可能选错工具 | 明确走REPORT流程 |
| 出错排查 | 不知道哪里错了 | 知道是哪个意图的问题 |

---

## 架构设计（三层混合方案）

### 核心流程

```
用户输入
    ↓
┌─────────────────────────────────────┐
│ 第一层：规则匹配（快速通道）          │
│ - "你好/帮助/退出" → 直接处理         │
│ - 多 ticker → 自动识别为对比         │
└─────────────────────────────────────┘
    ↓ 没匹配到
┌─────────────────────────────────────┐
│ 第二层：Embedding相似度 + 关键词加权  │
│ - 计算与各意图例句的相似度            │
│ - 关键词命中 → 加权 +0.12           │
│ - 相似度 >= 0.75 → 直接分类          │
└─────────────────────────────────────┘
    ↓ 置信度不够
┌─────────────────────────────────────┐
│ 第三层：LLM Router（兜底）           │
│ - 把候选意图告诉LLM                  │
│ - LLM做最终决策                      │
└─────────────────────────────────────┘
```

---

## v0.6.1 代码重构 (2026-01-12 下午)

### 新增文件

1. `backend/config/keywords.py` - 集中化关键词配置
   - Intent 枚举类
   - GREETING_PATTERNS（问候正则）
   - KEYWORD_BOOST（关键词加权映射）
   - INTENT_EXAMPLES（意图例句）
   - KeywordConfig 单例配置管理器

2. `backend/config/ticker_mapping.py` - 集中化 Ticker 映射
   - COMPANY_MAP（公司名映射）
   - CN_TO_TICKER（中文名映射）
   - INDEX_ALIASES（指数别名）
   - KNOWN_TICKERS（已知有效 ticker）
   - COMMON_WORDS（常见词过滤）
   - `extract_tickers()` 共享提取函数

3. `backend/api/schemas.py` - Pydantic V2 模型
   - 请求模型：ChatRequest, AnalysisRequest, SubscriptionRequest 等
   - 响应模型：ChatResponse, SupervisorResponse, ClassificationInfo 等
   - 字段验证器和配置

### 修改文件

1. `backend/orchestration/intent_classifier.py`
   - 从 `backend.config.keywords` 导入配置
   - 删除重复的枚举和常量定义
   - 注释转为英文，保持用户响应中文

2. `backend/conversation/router.py`
   - 从 `backend.config.ticker_mapping` 导入映射
   - 删除 ~100 行重复的映射定义
   - `_extract_metadata()` 使用共享的 `extract_tickers()`

3. `backend/orchestration/supervisor_agent.py`
   - 注释和文档字符串转为英文
   - 提示词转为英文（含 "Always respond in Chinese"）

4. `backend/tools.py`
   - EXA_API_KEY 从硬编码改为环境变量读取

### 归档文件

- `backend/_archive/smart_router.py` - 未使用
- `backend/_archive/smart_dispatcher.py` - 未使用

---

## 测试结果

```
=== Hybrid IntentClassifier Test ===
[PASS] "hello" -> greeting (method: rule, conf: 0.98)
[PASS] "AAPL price" -> price (method: embedding+keyword, conf: 0.87)
[PASS] "TSLA news" -> news (method: embedding+keyword, conf: 0.85)
[PASS] "market sentiment" -> sentiment (method: embedding, conf: 0.82)
[PASS] "AAPL technical analysis" -> technical (method: embedding+keyword, conf: 0.89)
[PASS] "AAPL EPS" -> fundamental (method: embedding+keyword, conf: 0.86)
[PASS] "detailed analysis AAPL" -> report (method: embedding+keyword, conf: 0.88)
[PASS] "compare AAPL MSFT" -> comparison (method: rule, conf: 0.90)
[PASS] "CPI data" -> macro (method: embedding+keyword, conf: 0.84)

Total: 9 passed, 0 failed
```

---

## 优势总结

1. **省钱**: 简单问题用规则/Embedding处理，不调用 LLM
2. **准确**: Embedding 语义相似度 + 关键词加权，准确率 80-90%
3. **可控**: 明确知道每个意图走什么流程
4. **可追溯**: 出错时知道是哪个意图/Agent 的问题
5. **可扩展**: 新增意图只需添加例句和处理函数
6. **可维护**: 集中化配置，避免重复代码

---

## 依赖

```
sentence-transformers>=2.2.0  # 可选，不安装则回退到关键词模式
pydantic>=2.0.0               # API 模型验证
```

---

## 后续计划

- [ ] 添加用户反馈循环优化关键词权重
- [ ] 实现意图置信度阈值，低置信度时询问用户
- [ ] 添加意图分类的 LangSmith 追踪
- [ ] 微调专用分类模型（大规模生产时）
