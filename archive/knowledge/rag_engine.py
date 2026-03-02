"""
RAGEngine - 检索增强生成引擎
封装文档切片、向量化入库和相似度检索
"""
from typing import List, Dict, Any, Optional
from datetime import datetime
import hashlib
import re

from backend.knowledge.vector_store import VectorStore


class RAGEngine:
    """RAG 检索增强生成引擎"""

    # 默认切片参数
    DEFAULT_CHUNK_SIZE = 512
    DEFAULT_CHUNK_OVERLAP = 50

    def __init__(self, vector_store: VectorStore = None):
        self.vector_store = vector_store or VectorStore()

    def chunk_text(
        self,
        text: str,
        chunk_size: int = None,
        chunk_overlap: int = None
    ) -> List[Dict[str, Any]]:
        """
        将文本切分为重叠的块
        返回: [{"content": str, "index": int, "start": int, "end": int}, ...]
        """
        chunk_size = chunk_size or self.DEFAULT_CHUNK_SIZE
        chunk_overlap = chunk_overlap or self.DEFAULT_CHUNK_OVERLAP

        if not text or len(text) < chunk_size:
            return [{"content": text, "index": 0, "start": 0, "end": len(text)}] if text else []

        chunks = []
        start = 0
        index = 0

        while start < len(text):
            end = min(start + chunk_size, len(text))

            # 尝试在句子边界切分
            if end < len(text):
                # 查找最近的句子结束符
                for sep in ['. ', '。', '！', '？', '\n\n', '\n']:
                    last_sep = text.rfind(sep, start, end)
                    if last_sep > start + chunk_size // 2:
                        end = last_sep + len(sep)
                        break

            chunk_text = text[start:end].strip()
            if chunk_text:
                chunks.append({
                    "content": chunk_text,
                    "index": index,
                    "start": start,
                    "end": end
                })
                index += 1

            # 下一个块的起始位置（考虑重叠）
            start = end - chunk_overlap if end < len(text) else len(text)

        return chunks

    def ingest_document(
        self,
        collection_name: str,
        content: str,
        metadata: Dict[str, Any] = None,
        chunk_size: int = None,
        chunk_overlap: int = None
    ) -> Dict[str, Any]:
        """
        将文档切片并入库
        返回: {"success": bool, "chunks_count": int, "collection": str}
        """
        if not content:
            return {"success": False, "error": "Empty content", "chunks_count": 0}

        # 切片
        chunks = self.chunk_text(content, chunk_size, chunk_overlap)
        if not chunks:
            return {"success": False, "error": "No chunks generated", "chunks_count": 0}

        # 准备文档和元数据
        documents = []
        metadatas = []
        ids = []

        base_meta = metadata or {}
        doc_hash = hashlib.md5(content[:1000].encode()).hexdigest()[:8]

        for chunk in chunks:
            documents.append(chunk["content"])
            metadatas.append({
                **base_meta,
                "chunk_index": chunk["index"],
                "chunk_start": chunk["start"],
                "chunk_end": chunk["end"],
                "ingested_at": datetime.now().isoformat()
            })
            ids.append(f"{doc_hash}_{chunk['index']}")

        # 入库
        success = self.vector_store.add_documents(
            collection_name=collection_name,
            documents=documents,
            metadatas=metadatas,
            ids=ids
        )

        return {
            "success": success,
            "chunks_count": len(chunks),
            "collection": collection_name,
            "doc_hash": doc_hash
        }

    def ingest_documents(
        self,
        collection_name: str,
        documents: List[Dict[str, Any]],
        chunk_size: int = None
    ) -> Dict[str, Any]:
        """
        批量入库多个文档
        documents: [{"content": str, "metadata": dict}, ...]
        """
        total_chunks = 0
        success_count = 0
        errors = []

        for i, doc in enumerate(documents):
            content = doc.get("content", "")
            metadata = doc.get("metadata", {})
            metadata["doc_index"] = i

            result = self.ingest_document(
                collection_name=collection_name,
                content=content,
                metadata=metadata,
                chunk_size=chunk_size
            )

            if result["success"]:
                success_count += 1
                total_chunks += result["chunks_count"]
            else:
                errors.append({"doc_index": i, "error": result.get("error")})

        return {
            "success": success_count > 0,
            "documents_processed": success_count,
            "total_chunks": total_chunks,
            "errors": errors if errors else None
        }

    def query(
        self,
        collection_name: str,
        query: str,
        top_k: int = 5,
        min_relevance: float = 0.3,
        where: Dict[str, Any] = None
    ) -> List[Dict[str, Any]]:
        """
        检索相关文档片段
        返回: [{"content": str, "metadata": dict, "relevance": float}, ...]
        """
        results = self.vector_store.query(
            collection_name=collection_name,
            query_text=query,
            n_results=top_k,
            where=where
        )

        # 过滤低相关度结果
        filtered = [r for r in results if r.get("relevance", 0) >= min_relevance]

        return filtered

    def query_with_context(
        self,
        collection_name: str,
        query: str,
        top_k: int = 5,
        context_window: int = 1
    ) -> str:
        """
        检索并返回格式化的上下文字符串
        用于直接注入 LLM prompt
        """
        results = self.query(collection_name, query, top_k)

        if not results:
            return ""

        context_parts = []
        for i, r in enumerate(results, 1):
            content = r.get("content", "")
            source = r.get("metadata", {}).get("source", "unknown")
            relevance = r.get("relevance", 0)

            context_parts.append(
                f"[{i}] (relevance: {relevance:.2f}, source: {source})\n{content}"
            )

        return "\n\n---\n\n".join(context_parts)

    def create_ephemeral_collection(self, prefix: str = "temp") -> str:
        """创建临时集合（用于 DeepSearch 工作台）"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        name = f"{prefix}_{timestamp}"
        self.vector_store.get_or_create_collection(name, ephemeral=True)
        return name

    def cleanup_collection(self, collection_name: str) -> bool:
        """清理集合（任务结束后调用）"""
        return self.vector_store.delete_collection(collection_name)

    def get_collection_stats(self, collection_name: str) -> Dict[str, Any]:
        """获取集合统计信息"""
        collection = self.vector_store.get_or_create_collection(collection_name)
        if not collection:
            return {"exists": False}

        try:
            count = collection.count()
            return {
                "exists": True,
                "name": collection_name,
                "document_count": count
            }
        except Exception as e:
            return {"exists": True, "error": str(e)}
