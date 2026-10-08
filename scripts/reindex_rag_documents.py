"""恢复模型后分批补齐存量向量；每批独立提交，可中断后重跑。"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.rag.embedder import EmbeddingUnavailable
from backend.rag.hybrid_service import get_rag_service


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--collection")
    parser.add_argument("--batch-size", type=int, default=4, choices=range(1, 9))
    parser.add_argument("--max-batches", type=int, default=100)
    args = parser.parse_args()
    service = get_rag_service()
    try:
        for _ in range(max(1, args.max_batches)):
            result = service.reindex_pending(batch_size=args.batch_size, collection=args.collection)
            print(json.dumps(result, ensure_ascii=False), flush=True)
            if not result["updated"]:
                break
    except EmbeddingUnavailable:
        print(json.dumps({"status": "lexical_only", "reason": "embedding_unavailable", **service.index_status()}))
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
