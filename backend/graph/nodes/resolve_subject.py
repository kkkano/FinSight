# -*- coding: utf-8 -*-
from __future__ import annotations

from backend.graph.state import GraphState


def resolve_subject(state: GraphState) -> dict:
    """
    Deterministic subject resolution.
    Priority: selection > query ticker > active_symbol > unknown

    Rationale:
    - If the user explicitly mentions a different ticker/company in the query,
      it should override a potentially stale UI `active_symbol`.
    - If the query uses pronouns (no explicit ticker), `active_symbol` still
      provides the correct fallback.
    """
    ui = state.get("ui_context") or {}
    selections = ui.get("selections") or []
    active_symbol = ui.get("active_symbol")
    query = (state.get("query") or "").strip()

    subject_type = "unknown"
    tickers: list[str] = []
    selection_ids: list[str] = []
    selection_types: list[str] = []
    selection_payload: list[dict] = []

    if isinstance(selections, list) and selections:
        selection_ids = [str(s.get("id")) for s in selections if isinstance(s, dict) and s.get("id")]
        selection_types = [str(s.get("type")) for s in selections if isinstance(s, dict) and s.get("type")]
        selection_payload = [s for s in selections if isinstance(s, dict)]

        if len(selections) == 1:
            first = selection_types[:1]
            if first == ["news"]:
                subject_type = "news_item"
            elif first == ["filing"]:
                subject_type = "filing"
            else:
                # Includes `doc` and any legacy/unknown selection types.
                subject_type = "research_doc"
        else:
            # Multi-select defaults to a set; type can still be mixed.
            if all(t == "news" for t in selection_types):
                subject_type = "news_set"
            elif all(t == "filing" for t in selection_types):
                subject_type = "filing"
            else:
                subject_type = "research_doc"

        # Carry ticker context for downstream tools/agents even when selection is present.
        # Priority: explicit tickers in query > active_symbol.
        if query:
            try:  # pragma: no cover
                from backend.config.ticker_mapping import extract_tickers

                meta = extract_tickers(query)
                found = meta.get("tickers") if isinstance(meta, dict) else []
                found = [str(t).strip().upper() for t in (found or []) if str(t).strip()]
                if found:
                    tickers = found
            except Exception:
                pass
        if not tickers and isinstance(active_symbol, str) and active_symbol.strip():
            tickers = [active_symbol.strip().upper()]

    elif query:
        # Fallback: resolve subject from query tickers (e.g. pronoun-resolved "AAPL 的行情").
        try:  # pragma: no cover - guard against mapping import issues
            from backend.config.ticker_mapping import extract_tickers

            meta = extract_tickers(query)
            found = meta.get("tickers") if isinstance(meta, dict) else []
            found = [str(t).strip().upper() for t in (found or []) if str(t).strip()]
            if found:
                subject_type = "company"
                tickers = found
        except Exception:
            pass

    if subject_type == "unknown" and isinstance(active_symbol, str) and active_symbol.strip():
        subject_type = "company"
        tickers = [active_symbol.strip().upper()]

    return {
        "subject": {
            "subject_type": subject_type,
            "tickers": tickers,
            "selection_ids": selection_ids,
            "selection_types": selection_types,
            "selection_payload": selection_payload,
        }
    }
