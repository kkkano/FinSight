# FinSight RAG 架构升级计划 (ChromaDB + Sentence Transformers)

> 📅 **规划日期**: 2025-12-28
> 📅 **更新日期**: 2026-01-12
> 🎯 **核心目标**: 引入向量数据库与 RAG 技术，突破 Context 限制，赋予 Agent "阅读长文" 和 "长期记忆" 的能力。

---

## 0. 当前状态（2026-01-12）✅ 基础设施已完成

- **VectorStore** (`backend/knowledge/vector_store.py`): ChromaDB 封装已完成
- **RAGEngine** (`backend/knowledge/rag_engine.py`): 切片+检索引擎已完成
- **Embedding**: 使用 `paraphrase-multilingual-MiniLM-L12-v2` 本地多语言模型
- **依赖**: `chromadb>=0.4.0`, `sentence-transformers>=2.2.0` 已添加到 requirements.txt
- 下一步：集成到 DeepSearchAgent 作为临时工作台

## 1. 技术选型决策

### 1.1 向量数据库：Chroma (本地模式)
**决策理由**:
1.  **隐私第一**: FinSight 定位为个人金融助手，用户的持仓、偏好及研报数据应尽可能留在本地 (`./data/chroma_db`)，避免敏感数据上云。
2.  **轻量级**: 无需 Docker，`pip install chromadb` 即可运行，非常适合单体/小团队部署。
3.  **生态友好**: 与 LangChain 和 LlamaIndex 集成成熟。

### 1.2 Embedding 模型：Sentence Transformers (本地)
**决策理由**:
1.  **隐私优先**: 本地运行，无需调用外部 API，敏感金融数据不出本地。
2.  **多语言支持**: `paraphrase-multilingual-MiniLM-L12-v2` 支持中英文混合场景。
3.  **轻量高效**: 模型体积小，推理速度快，适合实时检索。

### 1.3 RAG 引擎：自研 RAGEngine
**决策理由**:
1.  **简洁可控**: 不依赖 LlamaIndex 复杂抽象，代码可读性高。
2.  **定制灵活**: 切片策略、检索参数可根据金融场景调优。
3.  **依赖精简**: 仅需 `chromadb` + `sentence-transformers`，无额外框架。

---

## 2. 核心应用场景

我们将分两个阶段引入 RAG 能力：

### 2.1 场景 A：DeepSearchAgent 的 "短期工作台" (Working Memory)
*   **痛点**: 研报通常为 20+ 页的 PDF，直接通过 LLM 处理 Token 消耗巨大且易丢失细节。
*   **流程**:
    1.  `DeepSearchAgent` 抓取 PDF/URL。
    2.  使用 **LlamaIndex** 解析并切片 (Chunking)。
    3.  存入 **临时 Collection** (TTL = 任务周期)。
    4.  Agent 针对具体问题 (Query) 检索相关片段 (Top-k)。
    5.  LLM 基于检索内容生成观点。
    6.  任务结束后**销毁**该 Collection，释放资源。

### 2.2 场景 B：UserContext 的 "长期海马体" (Long-term Memory)
*   **痛点**: 用户偏好散落在历史对话中，传统 Prompt 注入无法覆盖长周期的记忆。
*   **流程**:
    1.  将用户的关键陈述 ("我不喜欢白酒股"、"只关注美股科技") 向量化存入 **持久化 Collection**。
    2.  每次生成投资建议前，根据当前 Ticker/Sector 检索相关的历史偏好。
    3.  将检索到的 "Memory Highlights" 注入 System Prompt。

---

## 3. 实施路线图

### 阶段 2.5 (穿插在当前阶段) ✅ 已完成
- [x] 引入 `chromadb` 和 `sentence-transformers` 依赖
- [x] 实现 `VectorStore` 单例封装 (`backend/knowledge/vector_store.py`)
- [x] 实现 `RAGEngine` 切片+检索引擎 (`backend/knowledge/rag_engine.py`)

### 阶段 2.6 (下一步)
- [ ] 在 `DeepSearchAgent` 中集成 RAGEngine 作为临时工作台
- [ ] 实现长文研报的向量化入库与检索

### 阶段 3 (风控与主动服务)
- [ ] 实现基于 Chroma 的长期记忆模块 `VectorMemoryService`

---

## 4. 目录结构（已实现）

```
backend/knowledge/
├── __init__.py          # 模块导出 (VectorStore, RAGEngine)
├── vector_store.py      # ChromaDB 单例封装
│   ├── _get_chromadb()           # 延迟导入 ChromaDB
│   ├── _get_embedding_model()    # 延迟导入 SentenceTransformer
│   └── class VectorStore         # 单例模式
│       ├── add_documents()       # 添加文档到集合
│       ├── query()               # 相似度检索
│       ├── delete_collection()   # 删除集合
│       └── list_collections()    # 列出所有集合
└── rag_engine.py        # RAG 引擎封装
    └── class RAGEngine
        ├── chunk_text()              # 智能切片（句子边界）
        ├── ingest_document()         # 单文档入库
        ├── ingest_documents()        # 批量入库
        ├── query()                   # 检索相关片段
        ├── query_with_context()      # 返回格式化上下文
        ├── create_ephemeral_collection()  # 创建临时集合
        ├── cleanup_collection()      # 清理集合
        └── get_collection_stats()    # 获取统计信息

data/chroma_db/          # ChromaDB 持久化存储目录
```
