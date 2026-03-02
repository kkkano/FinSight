"""
VectorStore - ChromaDB 向量数据库封装
支持临时集合（DeepSearch 工作台）和持久化集合（用户记忆）
"""

import logging
import os
from typing import List, Dict, Any, Optional
from datetime import datetime

logger = logging.getLogger(__name__)


# ChromaDB 延迟导入
_chromadb = None
_SentenceTransformer = None

def _get_chromadb():
    global _chromadb
    if _chromadb is None:
        try:
            import chromadb
            _chromadb = chromadb
        except ImportError:
            logger.info("[VectorStore] chromadb not installed, run: pip install chromadb")
    return _chromadb

def _get_embedding_model():
    global _SentenceTransformer
    if _SentenceTransformer is None:
        try:
            from sentence_transformers import SentenceTransformer
            _SentenceTransformer = SentenceTransformer
        except ImportError:
            logger.info("[VectorStore] sentence-transformers not installed")
    return _SentenceTransformer


class VectorStore:
    """ChromaDB 向量存储单例"""

    _instance = None
    _client = None
    _embedding_model = None

    # 默认存储路径
    DEFAULT_PATH = os.path.join(os.path.dirname(__file__), "../../data/chroma_db")

    def __new__(cls, persist_path: str = None):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self, persist_path: str = None):
        if self._initialized:
            return

        self.persist_path = persist_path or self.DEFAULT_PATH
        self._collections: Dict[str, Any] = {}
        self._initialized = True

        # 延迟初始化客户端
        self._init_client()

    def _init_client(self):
        """初始化 ChromaDB 客户端"""
        chromadb = _get_chromadb()
        if chromadb is None:
            logger.info("[VectorStore] ChromaDB not available")
            return

        try:
            # 确保目录存在
            os.makedirs(self.persist_path, exist_ok=True)

            # 使用持久化客户端
            self._client = chromadb.PersistentClient(path=self.persist_path)
            logger.info(f"[VectorStore] Initialized with path: {self.persist_path}")
        except Exception as e:
            logger.info(f"[VectorStore] Failed to init client: {e}")
            # 回退到内存模式
            try:
                self._client = chromadb.Client()
                logger.info("[VectorStore] Using in-memory mode")
            except Exception as e2:
                logger.info(f"[VectorStore] Failed to init in-memory client: {e2}")

    def _get_embedding_fn(self):
        """获取 embedding 函数"""
        if self._embedding_model is None:
            SentenceTransformer = _get_embedding_model()
            if SentenceTransformer:
                try:
                    # 使用轻量级多语言模型
                    self._embedding_model = SentenceTransformer('paraphrase-multilingual-MiniLM-L12-v2')
                    logger.info("[VectorStore] Loaded embedding model: paraphrase-multilingual-MiniLM-L12-v2")
                except Exception as e:
                    logger.info(f"[VectorStore] Failed to load embedding model: {e}")
        return self._embedding_model

    def _embed_texts(self, texts: List[str]) -> List[List[float]]:
        """将文本转换为向量"""
        model = self._get_embedding_fn()
        if model is None:
            # 无模型时返回空，让 ChromaDB 使用默认 embedding
            return None
        try:
            embeddings = model.encode(texts, convert_to_numpy=True)
            return embeddings.tolist()
        except Exception as e:
            logger.info(f"[VectorStore] Embedding failed: {e}")
            return None

    def get_or_create_collection(self, name: str, ephemeral: bool = False) -> Any:
        """获取或创建集合"""
        if not self._client:
            return None

        if name in self._collections:
            return self._collections[name]

        try:
            collection = self._client.get_or_create_collection(
                name=name,
                metadata={"ephemeral": str(ephemeral), "created_at": datetime.now().isoformat()}
            )
            self._collections[name] = collection
            return collection
        except Exception as e:
            logger.info(f"[VectorStore] Failed to create collection {name}: {e}")
            return None

    def add_documents(
        self,
        collection_name: str,
        documents: List[str],
        metadatas: List[Dict[str, Any]] = None,
        ids: List[str] = None
    ) -> bool:
        """添加文档到集合"""
        collection = self.get_or_create_collection(collection_name)
        if not collection:
            return False

        try:
            # 生成 ID
            if ids is None:
                ids = [f"doc_{i}_{datetime.now().timestamp()}" for i in range(len(documents))]

            # 生成 embedding
            embeddings = self._embed_texts(documents)

            if embeddings:
                collection.add(
                    documents=documents,
                    embeddings=embeddings,
                    metadatas=metadatas or [{}] * len(documents),
                    ids=ids
                )
            else:
                # 让 ChromaDB 使用默认 embedding
                collection.add(
                    documents=documents,
                    metadatas=metadatas or [{}] * len(documents),
                    ids=ids
                )

            logger.info(f"[VectorStore] Added {len(documents)} docs to {collection_name}")
            return True
        except Exception as e:
            logger.info(f"[VectorStore] Failed to add documents: {e}")
            return False

    def query(
        self,
        collection_name: str,
        query_text: str,
        n_results: int = 5,
        where: Dict[str, Any] = None
    ) -> List[Dict[str, Any]]:
        """查询相似文档"""
        collection = self.get_or_create_collection(collection_name)
        if not collection:
            return []

        try:
            # 生成查询向量
            query_embedding = self._embed_texts([query_text])

            if query_embedding:
                results = collection.query(
                    query_embeddings=query_embedding,
                    n_results=n_results,
                    where=where
                )
            else:
                results = collection.query(
                    query_texts=[query_text],
                    n_results=n_results,
                    where=where
                )

            # 格式化结果
            formatted = []
            if results and results.get("documents"):
                docs = results["documents"][0] if results["documents"] else []
                metas = results["metadatas"][0] if results.get("metadatas") else [{}] * len(docs)
                distances = results["distances"][0] if results.get("distances") else [0] * len(docs)

                for i, doc in enumerate(docs):
                    formatted.append({
                        "content": doc,
                        "metadata": metas[i] if i < len(metas) else {},
                        "distance": distances[i] if i < len(distances) else 0,
                        "relevance": 1 - (distances[i] if i < len(distances) else 0)
                    })

            return formatted
        except Exception as e:
            logger.info(f"[VectorStore] Query failed: {e}")
            return []

    def delete_collection(self, name: str) -> bool:
        """删除集合（用于清理临时工作台）"""
        if not self._client:
            return False

        try:
            self._client.delete_collection(name)
            if name in self._collections:
                del self._collections[name]
            logger.info(f"[VectorStore] Deleted collection: {name}")
            return True
        except Exception as e:
            logger.info(f"[VectorStore] Failed to delete collection {name}: {e}")
            return False

    def list_collections(self) -> List[str]:
        """列出所有集合"""
        if not self._client:
            return []
        try:
            return [c.name for c in self._client.list_collections()]
        except Exception as e:
            logger.info(f"[VectorStore] Failed to list collections: {e}")
            return []