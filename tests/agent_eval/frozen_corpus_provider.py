"""同一冻结资料上的真实全文检索与已捕获生产者重执行；不调用网络、不理解问题意图。"""
from contextlib import ExitStack, contextmanager
from copy import deepcopy
from dataclasses import replace
from datetime import date, datetime, timezone
import hashlib
import inspect
import json
from pathlib import Path, PurePosixPath, PureWindowsPath
import os
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
from agent_eval.capture import _arguments
from agent_eval.materialize import SecSnapshots, _sec_json_url, blocked_network, file_sha
from agent_eval.tapes import ToolTape, _hash, canonical_json, _error
from backend.rag.embedder import lexical_search_text, _tokenize


def checksum(value):
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


def build_corpus(source_root, output_root):
    source_root, output_root = Path(source_root), Path(output_root)
    output_root.mkdir(parents=True, exist_ok=True)
    database = output_root / "corpus.sqlite"
    if database.exists():
        raise ValueError("existing_frozen_corpus_must_not_be_overwritten")
    origins, documents, records, producers = [], {}, [], []
    for path in sorted(source_root.rglob("*.json")):
        record = ToolTape(path.parent, "replay")._read(path)
        source = {"path": str(path.resolve()), "sha256": file_sha(path), "recorded_at": record["recorded_at"]}
        origins.append(source)
        records.append({"key": record["key"], "tool": record["tool"], "arguments": record["arguments"], **source})
        for ordinal, producer in enumerate(record.get("producer_outputs", [])):
            if producer.get("status") != "captured":
                continue
            producers.append({"producer": producer["producer"], "method": producer["method"],
                "arguments": producer.get("arguments", {}), "producer_index": ordinal,
                "producer_sha256": checksum(producer), **source})
            data = producer.get("data")
            endpoint = (producer.get("arguments") or {}).get("url", "")
            articles = []
            kind = None
            if producer["producer"] == "requests.Response" and producer["method"] == "json" and isinstance(data, dict):
                if endpoint in {"https://api.exa.ai/search", "https://api.tavily.com/search"}:
                    articles, kind = data.get("results", []), "search_response"
            if producer["producer"] == "market_data_gateway" and producer["method"] == "get_news" and isinstance(data, dict):
                articles, kind = data.get("data", []), "news_response"
            for index, article in enumerate(articles if isinstance(articles, list) else []):
                if not isinstance(article, dict):
                    continue
                # 这些键来自已捕获供应商的有限JSON协议，不是业务意图匹配。
                text = article.get("text") or article.get("raw_content") or article.get("content") or article.get("snippet") or article.get("summary")
                url = article.get("url") or article.get("link")
                if not isinstance(text, str) or not text.strip() or not isinstance(url, str):
                    continue
                identity = hashlib.sha256(text.encode()).hexdigest()
                document = documents.setdefault(identity, {"id": identity, "content_sha256": identity, "content": text,
                    "title": article.get("title", ""), "url": url,
                    "published_at": article.get("publishedDate") or article.get("published_at") or article.get("datetime"),
                    "observed_at": record["recorded_at"], "original_article": article, "origins": [],
                    "entity_provenance": [], "capture_boundary": "exactly_as_returned_by_captured_provider"})
                document["origins"].append({**source, "producer_index": ordinal, "article_index": index, "kind": kind,
                    "url": url, "title": article.get("title"),
                    "published_at": article.get("publishedDate") or article.get("published_at") or article.get("datetime")})
                if article.get("ticker") or article.get("related"):
                    document["entity_provenance"].append({"origin": "provider_article_metadata", "ticker": article.get("ticker"), "related": article.get("related")})
        raw = record.get("raw_output")
        if record["tool"] == "fetch_url_content" and isinstance(raw, str) and raw.strip():
            url = record["arguments"].get("url")
            if isinstance(url, str):
                identity = hashlib.sha256(raw.encode()).hexdigest()
                document = documents.setdefault(identity, {"id": identity, "content_sha256": identity, "content": raw,
                    "title": url, "url": url, "published_at": None, "observed_at": record["recorded_at"],
                    "original_article": None, "origins": [], "entity_provenance": [],
                    "capture_boundary": "complete_captured_return_value; upstream_page_completeness_unknown"})
                document["origins"].append({**source, "kind": "captured_url_return", "arguments": record["arguments"], "url": url})
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE records (key TEXT,tool TEXT,arguments TEXT,path TEXT,sha TEXT,observed TEXT)")
        connection.execute("CREATE INDEX record_key_index ON records(key,observed,path)")
        connection.execute("CREATE TABLE producers (producer TEXT,method TEXT,arguments TEXT,path TEXT,idx INTEGER,sha TEXT,observed TEXT)")
        connection.execute("CREATE INDEX producer_identity ON producers(producer,method,arguments,observed,path)")
        connection.execute("CREATE TABLE documents (id TEXT PRIMARY KEY,payload TEXT,url TEXT,observed TEXT)")
        connection.execute("CREATE TABLE document_urls (id TEXT,url TEXT)")
        connection.execute("CREATE VIRTUAL TABLE document_fts USING fts5(id UNINDEXED,title,body)")
        for record in records:
            connection.execute("INSERT INTO records VALUES (?,?,?,?,?,?)", (record["key"], record["tool"], canonical_json(record["arguments"]), record["path"], record["sha256"], record["recorded_at"]))
        for producer in producers:
            connection.execute("INSERT INTO producers VALUES (?,?,?,?,?,?,?)", (producer["producer"], producer["method"], canonical_json(producer["arguments"]), producer["path"], producer["producer_index"], producer["producer_sha256"], producer["recorded_at"]))
        for document in documents.values():
            connection.execute("INSERT INTO documents VALUES (?,?,?,?)", (document["id"], canonical_json(document), document["url"], document["observed_at"]))
            connection.execute("INSERT INTO document_fts VALUES (?,?,?)", (document["id"], lexical_search_text(str(document["title"])), lexical_search_text(document["content"])))
            for url in sorted({origin["url"] for origin in document["origins"]}):
                connection.execute("INSERT INTO document_urls VALUES (?,?)", (document["id"], url))
    manifest = {"version": 1, "provider": "frozen_corpus", "created_at": datetime.now(timezone.utc).isoformat(),
        "retrieval": "SQLite FTS5 BM25; existing RAG lexical_search_text tokenizer",
        "records": records, "producers": producers,
        "documents": [{key: value for key, value in document.items() if key not in {"content", "original_article"}} for document in documents.values()],
        "source_files": origins, "source_root": str(source_root.resolve()),
        "provider_source_sha256": file_sha(Path(__file__)), "database_sha256": file_sha(database),
        "boundary": "Only captured originals; missing fields/HTTP parameters remain gaps; no live network claims",
        "selection": "All captured documents, content SHA dedup; equal keys use earliest observed original, not best model answer"}
    (output_root / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


class FrozenCorpus:
    def __init__(self, folder):
        self.folder = Path(folder)
        self.manifest = json.loads((self.folder / "manifest.json").read_text(encoding="utf-8"))
        self.identity = file_sha(self.folder / "manifest.json")
        self.database = self.folder / "corpus.sqlite"
        if file_sha(self.database) != self.manifest["database_sha256"]:
            raise ValueError("frozen_corpus_database_changed")
        self.mount_manifest = None
        mapping_path = os.getenv("FINSIGHT_EVAL_CORPUS_MOUNT_MANIFEST")
        if mapping_path:
            mapping = json.loads(Path(mapping_path).read_text(encoding="utf-8"))
            if (mapping["corpus_manifest_sha256"] != self.identity
                    or mapping["database_sha256"] != self.manifest["database_sha256"]
                    or mapping["recorded_source_root"] != self.manifest["source_root"]):
                raise ValueError("frozen_corpus_mount_binding_changed")
            self.mount_manifest = mapping | {"mapping_manifest_sha256": file_sha(Path(mapping_path))}

    def source_path(self, recorded):
        if self.mount_manifest is None:
            return Path(recorded)
        mapping = self.mount_manifest
        path_type = PureWindowsPath if PureWindowsPath(mapping["recorded_source_root"]).drive else PurePosixPath
        relative = path_type(recorded).relative_to(path_type(mapping["recorded_source_root"]))
        root = Path(mapping["mounted_source_root"]).resolve()
        physical = root.joinpath(*relative.parts).resolve()
        if not physical.is_relative_to(root):
            raise ValueError("frozen_corpus_source_outside_mount")
        return physical

    def query(self, sql, arguments=()):
        with sqlite3.connect("file:" + str(self.database) + "?mode=ro", uri=True) as connection:
            return connection.execute(sql, arguments).fetchall()

    def exact(self, name, arguments):
        key = _hash({"tool": name, "arguments": arguments})
        found = self.query("SELECT path,sha FROM records WHERE key=? ORDER BY observed,path LIMIT 1", (key,))
        if not found:
            return None
        path, sha = found[0]
        path = self.source_path(path)
        if file_sha(path) != sha:
            raise ValueError("original_capture_changed")
        return ToolTape(path.parent, "replay")._read(path)

    def search(self, query, top_k=10):
        wanted = list(dict.fromkeys(_tokenize(query)))
        if not wanted:
            return []
        expression = " OR ".join('"' + token.replace('"', '""') + '"' for token in wanted)
        found = self.query("SELECT d.payload FROM document_fts f JOIN documents d ON d.id=f.id WHERE document_fts MATCH ? ORDER BY bm25(document_fts,0,2,1),d.id LIMIT ?", (expression, top_k))
        return [json.loads(row[0]) for row in found]

    def by_url(self, url):
        found = self.query("SELECT d.payload FROM documents d JOIN document_urls u ON d.id=u.id WHERE u.url=? ORDER BY d.observed,d.id", (url,))
        return [json.loads(row[0]) for row in found]

    def document(self, identity):
        found = self.query("SELECT payload FROM documents WHERE id=?", (identity,))
        if not found:
            raise ValueError("corpus_document_unknown")
        return json.loads(found[0][0])

    def original_record(self, index):
        if type(index) is not int or not 0 <= index < len(self.manifest["records"]):
            raise ValueError("corpus_record_index_invalid")
        reference = self.manifest["records"][index]
        path = self.source_path(reference["path"])
        if file_sha(path) != reference["sha256"]:
            raise ValueError("original_corpus_record_changed")
        return ToolTape(path.parent, "replay")._read(path)

    def complete_index(self):
        return {"manifest_sha256": self.identity, "provider": "frozen_corpus",
                "record_columns": ["index", "tool", "original_arguments"],
                "records": [[index, row["tool"], row["arguments"]] for index, row in enumerate(self.manifest["records"])],
                "document_count": len(self.manifest["documents"]), "document_catalogue_fields": ["id", "title", "url", "published_at", "observed_at", "content_sha256", "origins"],
                "document_catalogue_fully_readable": True, "original_fields_fully_readable": True,
                "boundary": self.manifest["boundary"]}

    def snapshot(self, producer, method, arguments):
        found = self.query("SELECT path,idx,sha FROM producers WHERE producer=? AND method=? AND arguments=? ORDER BY observed,path LIMIT 1", (producer, method, canonical_json(arguments)))
        if not found:
            return None
        path, index, sha = found[0]
        path = self.source_path(path)
        record = ToolTape(path.parent, "replay")._read(path)
        item = record["producer_outputs"][index]
        if checksum(item) != sha:
            raise ValueError("producer_snapshot_changed")
        return deepcopy(item)

    def marker(self, provenance):
        return {"provider": "frozen_corpus", "corpus_manifest_sha256": self.identity,
                "network_access": False, "data_boundary": self.manifest["boundary"],
                "source_mount_manifest_sha256": self.mount_manifest["mapping_manifest_sha256"] if self.mount_manifest else None,
                **provenance}

    def retrieve(self, name, arguments, callback):
        if name == "search":
            documents = self.search(arguments["query"])
            raw = {"source": "frozen_corpus", "status": "ok" if documents else "empty", "query": arguments["query"],
                   "results": [{"title": doc["title"], "url": doc["url"], "text": doc["content"][:2000],
                       "published_at": doc["published_at"], "observed_at": doc["observed_at"],
                       "content_sha256": doc["content_sha256"], "frozen_document_id": doc["id"],
                       "complete_capture_characters": len(doc["content"]), "preview_only": True} for doc in documents]}
            return raw, self.marker({"kind": "real_frozen_fulltext_retrieval", "document_ids": [doc["id"] for doc in documents]})
        exact = self.exact(name, arguments)
        if exact is not None:
            return deepcopy(exact["raw_output"]), self.marker({"kind": "exact_original_snapshot", "original_record_checksum": exact["checksum"], "observed_at": exact["recorded_at"], "original_record_key": exact["key"]})
        if name == "fetch_url_content":
            found = self.by_url(arguments["url"])
            if found:
                # 按固定观测次序选择原件；不把未知未抓取内容补成完整网页。
                doc = found[0]
                requested = arguments.get("max_length", 5000)
                return {"status": "ok", "url": doc["url"], "text": doc["content"][:requested],
                    "source": "frozen_corpus", "published_at": doc["published_at"], "observed_at": doc["observed_at"],
                    "capture_boundary": doc["capture_boundary"], "available_original_chars": len(doc["content"]),
                    "requested_max_length": requested}, self.marker({"kind": "captured_document_read", "document_id": doc["id"]})
        if name == "get_sec_company_facts_quarterly":
            wanted = str(arguments.get("ticker", "")).upper()
            rows = [record for record in self.manifest["records"] if record["tool"] == name and str(record["arguments"].get("ticker", "")).upper() == wanted]
            rows.sort(key=lambda row: (row["recorded_at"], row["path"]))
            if rows:
                sources = [self.source_path(rows[0]["path"])]
                ticker_rows = [row for row in self.manifest["records"] if row["tool"] == name]
                for row in sorted(ticker_rows, key=lambda row: (row["recorded_at"], row["path"])):
                    source = self.source_path(row["path"])
                    record = ToolTape(source.parent, "replay")._read(source)
                    if any(item.get("producer") == "requests.Response" and (item.get("arguments") or {}).get("url") == "https://www.sec.gov/files/company_tickers.json" for item in record.get("producer_outputs", [])):
                        sources.append(source)
                        break
                try:
                    snapshots = SecSnapshots(list(dict.fromkeys(sources)), date.fromisoformat(rows[0]["recorded_at"][:10]))
                    derived = snapshots.derive(arguments)
                    if derived["status"] == "derived":
                        return derived["raw_output"], self.marker({"kind": "actual_sec_production_function_offline_reexecution", "http_snapshots": derived["http_snapshots"], "source_inputs": snapshots.sources})
                except (ValueError, RuntimeError, TypeError) as exc:
                    return self.gap(name, arguments, str(exc))
        return self.reexecute(name, arguments, callback)

    def gap(self, name, arguments, reason):
        return {"status": "error", "error": "frozen_corpus_gap", "error_code": "frozen_corpus_gap",
                "source": "frozen_corpus", "summary": "冻结资料未具备此调用的完整可重执行来源；未联网，也未补造数据。"}, self.marker({"kind": "structured_data_gap", "tool": name, "arguments": arguments, "reason": reason})

    def reexecute(self, name, arguments, callback):
        from backend.services.market_data_gateway import MarketDataGateway
        from yfinance.base import TickerBase
        used, gaps = [], []
        targets = [(MarketDataGateway, "get_quote", "market_data_gateway", ("symbol",)),
                   (MarketDataGateway, "get_kline", "market_data_gateway", ("symbol",)),
                   (MarketDataGateway, "get_news", "market_data_gateway", ("symbol",)),
                   (TickerBase, "get_info", "yfinance.TickerBase", ()),
                   (TickerBase, "history", "yfinance.TickerBase", ("period",))]
        corpus = self
        def replacement(producer, method, positional):
            def read(instance, *args, **kwargs):
                selected = _arguments(instance, args, kwargs, positional)
                if len(args) > len(positional) or any(key not in selected and value is not None for key, value in kwargs.items()):
                    gaps.append({"producer": producer, "method": method, "reason": "original_request_parameters_not_captured", "requested_parameters": sorted(kwargs)})
                    raise RuntimeError("frozen_producer_parameters_incomplete")
                item = corpus.snapshot(producer, method, selected)
                if item is None:
                    gaps.append({"producer": producer, "method": method, "arguments": selected, "reason": "producer_snapshot_missing"})
                    raise RuntimeError("frozen_producer_snapshot_missing")
                used.append({"producer": producer, "method": method, "arguments": selected, "sha256": checksum(item)})
                data = deepcopy(item["data"])
                if item["data_format"] == "dataframe_split":
                    import pandas as pd
                    frame = pd.DataFrame(data["data"], columns=data["columns"], index=pd.to_datetime(data["index"]))
                    frame.index.names = data.get("index_names", [None])
                    return frame
                return data
            return read
        try:
            with ExitStack() as stack:
                for cls, method, producer, positional in targets:
                    stack.enter_context(__import__("unittest.mock", fromlist=["patch"]).patch.object(cls, method, replacement(producer, method, positional)))
                with blocked_network() as network:
                    raw = callback(deepcopy(arguments))
            if gaps or network["attempts"]:
                return self.gap(name, arguments, canonical_json({"missing": gaps, "network_attempts_blocked": network["attempts"]}))
            if not used:
                return self.gap(name, arguments, "no_complete_producer_used_for_data_result")
            return raw, self.marker({"kind": "actual_production_function_offline_reexecution", "producer_inputs": used})
        except Exception as exc:
            return self.gap(name, arguments, canonical_json({"missing": gaps, "exception_type": type(exc).__name__}))
