# -*- coding: utf-8 -*-
"""Tool-output normalization for the execution evidence pipeline."""
from __future__ import annotations

import json
from typing import Any

from backend.graph.json_utils import json_dumps_safe
from backend.graph.intent_contract import canonical_evidence_kinds, evidence_registry
from backend.graph.request_task_contract import output_is_error_like
from backend.utils.quote import parse_quote_payload


def evidence_is_global(raw: dict[str, Any], producer_name: str = "") -> bool:
    meta = raw.get("meta") if isinstance(raw.get("meta"), dict) else {}
    if raw.get("subject") or raw.get("ticker") or meta.get("subject") or meta.get("ticker"):
        return False
    source = str(raw.get("source") or raw.get("source_name") or meta.get("source") or "").strip().lower()
    return bool(meta.get("indicator_key") or producer_name == "macro_agent"
                or source in {"fred", "market_sentiment", "cnn fear & greed"})


def evidence_contract_metadata(
    raw: dict[str, Any],
    *,
    producer_name: str = "",
    producer_kind: str = "",
    required_evidence: list[str] | None = None,
    quote_payload: Any = None,
) -> dict[str, Any]:
    """保留原始证据，补齐执行层与合成合同共同消费的来源元数据。"""
    result = dict(raw)
    meta = dict(raw.get("meta") or {}) if isinstance(raw.get("meta"), dict) else {}
    if "meta" in raw:
        result["meta"] = meta
    source_id = raw.get("source_id") or meta.get("source_id") or raw.get("id")
    if source_id:
        result["source_id"] = source_id

    registry = evidence_registry()
    kind = None
    for value in (raw.get("kind"), meta.get("evidence_kind"), meta.get("kind")):
        if value == "unknown":
            kind = "unknown"
            break
        canonical = canonical_evidence_kinds([value]) if isinstance(value, str) else []
        if canonical:
            kind = canonical[0]
            break
    if kind is None:
        candidates = {
            key for key, definition in registry.items()
            if producer_name in (definition.agents if producer_kind == "agent" else definition.tools)
        }
        if producer_kind == "tool" and producer_name == "get_stock_price":
            kind = "price_snapshot"
        elif producer_kind == "agent" and producer_name == "price_agent":
            kind = "price_snapshot"
        else:
            selected = candidates.intersection(canonical_evidence_kinds(required_evidence))
            if len(selected) == 1:
                kind = next(iter(selected))
            elif len(candidates) == 1:
                kind = next(iter(candidates))
            else:
                kind = "unknown"
    result["kind"] = kind
    if producer_kind == "agent" and producer_name:
        result.setdefault("agent_name", producer_name)
    if meta.get("source_time_status") == "unknown":
        for time_field in ("as_of", "timestamp", "published_date"):
            result[time_field] = None
    for key, values in {
        "as_of": (raw.get("as_of"), meta.get("as_of"), raw.get("timestamp"), meta.get("timestamp"), raw.get("published_date")),
        "source_name": (raw.get("source_name"), meta.get("source_name"), raw.get("source"), producer_name),
        "market_price": (raw.get("market_price"), meta.get("market_price")),
    }.items():
        if key == "as_of" and meta.get("source_time_status") == "unknown":
            result["as_of"] = None
            continue
        value = next((item for item in values if item not in (None, "")), None)
        if value is not None:
            result[key] = value
    if producer_kind == "tool" and producer_name == "get_stock_price":
        quote = parse_quote_payload(quote_payload)
        if quote:
            result["market_price"] = quote["price"]
            for key in ("as_of", "currency", "quality", "market_session", "source_timestamp", "source_time_precision", "source_time_status"):
                if quote.get(key) is not None:
                    result[key] = quote[key]
            result["meta"] = {**meta, **{key: quote[key] for key in ("market_session", "source_timestamp", "source_time_precision", "source_time_status") if quote.get(key) is not None}}
            if quote.get("source"):
                result["source_name"] = quote["source"]
    return result


def _contract_fields(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return {}
    fields = {
        key: raw[key] for key in (
            "source_id", "kind", "as_of", "market_price", "source_name", "agent_name", "meta",
            "price", "current_price", "close", "timestamp",
            "event_quality", "supporting_reports", "retrieval_kind", "published_at", "published_at_precision",
            "subject", "metric", "period_start", "period_end", "frequency", "unit", "currency", "usage", "structured_data",
            "coverage_window", "request_window", "content_read", "content_sections", "market_session", "source_time_status",
        ) if key in raw
    }
    if raw.get("url") or raw.get("filing_url") or raw.get("source_url"):
        fields.setdefault("structured_data", dict(raw))
    return fields


def _append_tool_evidence(
    evidence_pool: list[dict[str, Any]],
    tool_name: str,
    step_id: str,
    output: Any,
) -> None:
    if output is None:
        return
    if isinstance(output, dict) and output.get("skipped"):
        return

    # Some tools return JSON text (e.g. get_company_news). Try to parse.
    if isinstance(output, str):
        try:
            parsed = json.loads(output)
            output = parsed
        except Exception:
            pass
    if output_is_error_like(output):
        return

    # Special-case: make technical snapshot readable in evidence list.
    if tool_name == "get_technical_snapshot" and isinstance(output, dict):
        if output.get("error"):
            evidence_pool.append(
                {
                    **_contract_fields(output),
                    "title": f"Technical snapshot ({output.get('ticker','N/A')})",
                    "url": None,
                    "snippet": f"error={output.get('error')} points={output.get('points','N/A')}",
                    "source": tool_name,
                    "published_date": output.get("as_of"),
                    "confidence": 0.7,
                    "type": "tool",
                    "id": output.get("id") or f"{tool_name}:{step_id}",
                }
            )
            return

        parts = []
        if output.get("close") is not None:
            parts.append(f"close={output.get('close')}")
        if output.get("ma20") is not None:
            parts.append(f"MA20={output.get('ma20')}")
        if output.get("ma50") is not None:
            parts.append(f"MA50={output.get('ma50')}")
        if output.get("rsi14") is not None:
            parts.append(f"RSI14={output.get('rsi14')}({output.get('rsi_state')})")
        if output.get("macd") is not None and output.get("macd_signal") is not None:
            parts.append(f"MACD={output.get('macd')} vs {output.get('macd_signal')}({output.get('momentum')})")
        if output.get("trend"):
            parts.append(f"trend={output.get('trend')}")

        evidence_pool.append(
            {
                **_contract_fields(output),
                "title": f"Technical snapshot ({output.get('ticker','N/A')})",
                "url": None,
                "snippet": " | ".join(parts) if parts else None,
                "source": output.get("source") or tool_name,
                "published_date": output.get("as_of"),
                "confidence": 0.75,
                "type": "tool",
                "id": output.get("id") or f"{tool_name}:{step_id}",
            }
        )
        return

    if tool_name in ("get_sec_filings", "get_sec_material_events", "get_sec_risk_factors") and isinstance(output, dict):
        filings = output.get("filings") or output.get("events") or []
        company_name = output.get("company_name") or output.get("ticker") or ""
        for i, filing in enumerate(filings[:10]):
            if not isinstance(filing, dict):
                continue
            form_type = str(filing.get("form") or "SEC").strip() or "SEC"
            filing_url = str(filing.get("filing_url") or "").strip()
            filing_date = str(filing.get("filing_date") or "").strip() or None
            description = str(filing.get("primary_doc_description") or form_type).strip()
            evidence_pool.append(
                {
                    **_contract_fields(filing),
                    "title": f"{company_name} {form_type} ({filing_date or 'N/A'})".strip(),
                    "url": filing_url or None,
                    "snippet": str(filing.get("content_excerpt") or f"SEC EDGAR {form_type} filing. Filed: {filing_date or 'N/A'}. {description}"),
                    "source": "sec_edgar",
                    "published_date": filing_date,
                    "confidence": 0.85,
                    "type": "filing",
                    "id": f"{tool_name}:{step_id}:{i+1}",
                }
            )

        risk_excerpt = str(output.get("risk_factors_excerpt") or "").strip()
        if risk_excerpt:
            selected = output.get("selected_filing") if isinstance(output.get("selected_filing"), dict) else {}
            evidence_pool.append(
                {
                    **_contract_fields(selected),
                    "title": f"{company_name} Risk Factors (Item 1A)".strip(),
                    "url": str(selected.get("filing_url") or "").strip() or None,
                    "snippet": risk_excerpt[:800],
                    "source": "sec_edgar",
                    "published_date": selected.get("filing_date"),
                    "confidence": 0.9,
                    "type": "filing",
                    "id": f"{tool_name}:{step_id}:risk",
                }
            )
        return

    if tool_name == "get_local_market_filings" and isinstance(output, dict):
        filings = output.get("filings") or []
        ticker = str(output.get("ticker") or "").strip()
        market = str(output.get("market") or "").strip().upper()
        for i, filing in enumerate(filings[:10]):
            if not isinstance(filing, dict):
                continue
            form_type = str(filing.get("form") or "filing").strip() or "filing"
            filing_url = str(filing.get("filing_url") or filing.get("url") or "").strip()
            filing_date = str(filing.get("filing_date") or filing.get("published_date") or "").strip() or None
            title = str(filing.get("title") or "").strip()
            description = str(
                filing.get("primary_doc_description") or filing.get("snippet") or title or form_type
            ).strip()
            evidence_pool.append(
                {
                    **_contract_fields(filing),
                    "title": title or f"{ticker} {form_type} ({filing_date or 'N/A'})".strip(),
                    "url": filing_url or None,
                    "snippet": f"{market} local disclosure {form_type}. Filed: {filing_date or 'N/A'}. {description}",
                    "source": filing.get("source") or "local_disclosure",
                    "published_date": filing_date,
                    "confidence": filing.get("confidence", 0.8),
                    "type": "filing",
                    "id": f"{tool_name}:{step_id}:{i+1}",
                }
            )
        return

    if tool_name == "get_authoritative_media_news" and isinstance(output, dict):
        articles = output.get("articles") or []
        for i, article in enumerate(articles[:10]):
            if not isinstance(article, dict):
                continue
            title = str(article.get("title") or "").strip()
            url = str(article.get("url") or "").strip()
            snippet = str(article.get("snippet") or title).strip()
            article_text = f"{title} {snippet} {url}".lower()
            if "cpi" in article_text and (
                "london stock exchange:cpi" in article_text
                or "lse:cpi" in article_text
                or "capita" in article_text
            ):
                continue
            if not title and not url:
                continue
            evidence_pool.append(
                {
                    **_contract_fields(article),
                    "title": title or f"authoritative media {i+1}",
                    "url": url or None,
                    "snippet": snippet[:800],
                    "source": article.get("source") or "authoritative_feed",
                    "published_date": article.get("published_date"),
                    "confidence": article.get("confidence", 0.78),
                    "type": "news",
                    "id": article.get("id") or f"{tool_name}:{step_id}:{i+1}",
                }
            )
        return

    if tool_name == "get_official_macro_releases" and isinstance(output, dict):
        releases = output.get("releases") or []
        for i, release in enumerate(releases[:10]):
            if not isinstance(release, dict):
                continue
            title = str(release.get("title") or "").strip()
            url = str(release.get("url") or "").strip()
            snippet = str(release.get("snippet") or title).strip()
            if not title and not url:
                continue
            evidence_pool.append(
                {
                    **_contract_fields(release),
                    "title": title or f"macro release {i+1}",
                    "url": url or None,
                    "snippet": snippet[:800],
                    "source": release.get("source") or "macro_official_feeds",
                    "published_date": release.get("published_date"),
                    "confidence": release.get("confidence", 0.82 if release.get("is_official") else 0.65),
                    "type": release.get("type") or "macro_release",
                    "id": release.get("id") or f"{tool_name}:{step_id}:{i+1}",
                }
            )
        return

    if tool_name == "get_earnings_call_transcripts" and isinstance(output, dict):
        transcripts = output.get("transcripts") or output.get("articles") or []
        for i, item in enumerate(transcripts[:10]):
            if not isinstance(item, dict):
                continue
            title = str(item.get("title") or "").strip()
            url = str(item.get("url") or "").strip()
            snippet = str(item.get("snippet") or title).strip()
            if not title and not url:
                continue
            evidence_pool.append(
                {
                    **_contract_fields(item),
                    "title": title or f"earnings transcript {i+1}",
                    "url": url or None,
                    "snippet": snippet[:800],
                    "source": item.get("source") or "earnings_transcript",
                    "published_date": item.get("published_date"),
                    "confidence": item.get("confidence", 0.8),
                    "type": "transcript",
                    "id": item.get("id") or f"{tool_name}:{step_id}:{i+1}",
                }
            )
        return

    if tool_name == "fetch_url_content" and isinstance(output, dict):
        title = str(output.get("title") or output.get("url") or "URL content").strip()
        url = str(output.get("final_url") or output.get("url") or "").strip()
        snippet = str(output.get("description") or output.get("content") or output.get("error") or "").strip()
        evidence_pool.append(
            {
                **_contract_fields(output),
                "title": title,
                "url": url or None,
                "snippet": snippet[:1200],
                "source": output.get("source") or "url",
                "published_date": None,
                "confidence": 0.75 if output.get("content") else 0.45,
                "type": "url",
                "id": output.get("id") or f"{tool_name}:{step_id}",
            }
        )
        return

    if isinstance(output, list):
        for i, item in enumerate(output[:10]):
            if not isinstance(item, dict):
                continue
            evidence_pool.append(
                {
                    **_contract_fields(item),
                    "title": item.get("title") or item.get("headline") or f"{tool_name} result {i+1}",
                    "url": item.get("url"),
                    "snippet": item.get("snippet") or item.get("summary") or item.get("content"),
                    "source": item.get("source") or tool_name,
                    "published_date": item.get("published_date") or item.get("published_at") or item.get("datetime"),
                    "confidence": item.get("confidence", 0.6),
                    "type": item.get("type") or "tool",
                    "id": item.get("id") or f"{tool_name}:{step_id}:{i+1}",
                }
            )
        return

    snippet = json_dumps_safe(output, ensure_ascii=False) if isinstance(output, dict) else str(output)
    evidence_pool.append(
        {
            **_contract_fields(output),
            "title": f"{tool_name} output",
            "url": None,
            "snippet": snippet[:800],
            "source": tool_name,
            "published_date": None,
            "confidence": 0.6,
            "type": "tool",
            "id": f"{tool_name}:{step_id}",
            }
        )


def append_tool_evidence(
    evidence_pool: list[dict[str, Any]],
    tool_name: str,
    step_id: str,
    output: Any,
    *,
    required_evidence: list[str] | None = None,
) -> None:
    before_count = len(evidence_pool)
    _append_tool_evidence(evidence_pool, tool_name, step_id, output)
    quote_payload = output
    if isinstance(output, str) and tool_name == "get_stock_price":
        try:
            quote_payload = json.loads(output)
        except (TypeError, ValueError):
            pass
    for evidence in evidence_pool[before_count:]:
        evidence.update(evidence_contract_metadata(
            evidence,
            producer_name=tool_name,
            producer_kind="tool",
            required_evidence=required_evidence,
            quote_payload=quote_payload,
        ))
