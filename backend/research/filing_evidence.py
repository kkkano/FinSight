"""公告去重只合并同主体、同申报身份的资料，正文不会被索引覆盖。"""
from __future__ import annotations

import json
from typing import Any


def disclosure_sections(payload: dict[str, Any]) -> dict[str, str]:
    """读取成功标记与实际非空章节必须同时存在。"""
    if payload.get("content_read") is not True:
        return {}
    sections = payload.get("content_sections")
    if not isinstance(sections, dict):
        return {}
    return {str(name): text.strip() for name, text in sections.items() if isinstance(text, str) and text.strip()}


def _payload(item: dict[str, Any]) -> dict[str, Any]:
    structured = item.get("structured_data") if isinstance(item.get("structured_data"), dict) else {}
    return {**structured, **{key: item[key] for key in ("content_read", "content_sections", "content_excerpt") if key in item}}


def is_filing_evidence(item: dict[str, Any]) -> bool:
    payload = _payload(item)
    return item.get("type") == "filing" or bool(payload.get("form") and (payload.get("accession_number") or payload.get("accession") or payload.get("filing_date")))


def filing_identity(item: dict[str, Any]) -> tuple[str, ...] | None:
    payload = _payload(item)
    meta = item.get("meta") if isinstance(item.get("meta"), dict) else {}
    subject = str(item.get("subject") or meta.get("subject") or meta.get("ticker") or payload.get("ticker") or "").strip().upper()
    url = str(item.get("url") or payload.get("filing_url") or "").strip()
    form = str(payload.get("form") or item.get("form") or "").strip().upper()
    accession = str(payload.get("accession_number") or payload.get("accession") or "").strip()
    report_date = str(payload.get("report_date") or payload.get("period_end") or item.get("period_end") or "").strip()
    filing_date = str(payload.get("filing_date") or item.get("filing_date") or "").strip()
    if not subject or not url or not (accession or form and (report_date or filing_date)):
        return None
    return subject, url, form, accession, report_date, filing_date


def _provenance(item: dict[str, Any], plural: str, singular: str) -> list[str]:
    values = list(item.get(plural) or []) if isinstance(item.get(plural), list) else []
    if item.get(singular):
        values.append(item[singular])
    return [str(value).strip() for value in values if str(value).strip()]


def merge_filing_evidence(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    """主体、URL和申报身份一致后，择正文并合并不同读取器取得的章节。"""
    identity = filing_identity(left)
    if identity is None or identity != filing_identity(right):
        raise ValueError("filing_evidence_identity_mismatch")

    def rank(item):
        sections = disclosure_sections(_payload(item))
        return (bool(sections), len(sections), sum(len(text) for text in sections.values()),
                str(item.get("source_id") or item.get("id") or ""), json.dumps(item, sort_keys=True, ensure_ascii=False, default=str))

    secondary, preferred = sorted((left, right), key=rank)
    merged = {**secondary, **preferred}
    payload = {**_payload(secondary), **_payload(preferred)}
    sections: dict[str, str] = {}
    for item in (left, right):
        for name, text in disclosure_sections(_payload(item)).items():
            if (len(text), text) > (len(sections.get(name, "")), sections.get(name, "")):
                sections[name] = text
    if sections:
        sections = {name: sections[name] for name in sorted(sections)}
        excerpt = "\n\n".join(f"{name}: {text}" for name, text in sections.items())
        payload.update(content_read=True, content_sections=sections, content_excerpt=excerpt)
        payload.pop("content_error", None)
        merged.update(content_read=True, content_sections=sections, content_excerpt=excerpt, snippet=excerpt)
        if "text" in merged:
            merged["text"] = excerpt
    merged["structured_data"] = payload
    merged["meta"] = {**(secondary.get("meta") or {}), **(preferred.get("meta") or {})}
    for plural, singular in (("task_ids", "task_id"), ("step_ids", "step_id"), ("source_ids", "source_id")):
        values = sorted(set(_provenance(left, plural, singular) + _provenance(right, plural, singular)))
        if values:
            merged[plural] = values
    return merged


__all__ = ["disclosure_sections", "filing_identity", "is_filing_evidence", "merge_filing_evidence"]
