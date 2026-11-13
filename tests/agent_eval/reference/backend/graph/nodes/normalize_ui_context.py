# -*- coding: utf-8 -*-
from __future__ import annotations

from backend.graph.state import GraphState


def normalize_ui_context(state: GraphState) -> dict:
    """
    Normalize UI context (ephemeral) fields.
    - Deduplicate selections by (type, id)
    - Normalize selection types (legacy compatibility)
    """
    ui = state.get("ui_context") or {}
    selections = ui.get("selections") or []
    if not isinstance(selections, list):
        selections = []

    uniq = []
    seen = set()
    for sel in selections:
        if not isinstance(sel, dict):
            continue
        raw_type = sel.get("type")
        normalized_type = raw_type.strip().lower() if isinstance(raw_type, str) else raw_type
        # Legacy: `report` used to mean "input document". Normalize to `doc`.
        if normalized_type == "report":
            normalized_type = "doc"

        normalized_sel = {**sel, "type": normalized_type} if normalized_type is not None else dict(sel)
        key = (normalized_sel.get("type"), normalized_sel.get("id"))
        if key in seen:
            continue
        seen.add(key)
        uniq.append(normalized_sel)

    ui = {**ui, "selections": uniq}
    return {"ui_context": ui}
