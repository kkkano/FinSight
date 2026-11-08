"""公开战绩的只读范围投影；复用冻结账本统计，不改变预测、对账或版本分组。"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import timedelta
import hashlib
import json
import os
from typing import get_args

from backend.services.prediction_calendar import NY, utc_now, window_for_date, timestamp
from backend.services.prediction_store import PredictionStore, TICKERS, STRATEGY_VERSION
from backend.research.prediction_contract import PredictionType


class _ReportView(PredictionStore):
    def __init__(self, rows, base_coverage):
        self.rows, self.base_coverage = rows, base_coverage

    def _rows(self):
        return self.rows

    def coverage(self, batch_date=None):
        selected_date = batch_date or (max(row["batch_date"] for row in self.rows) if self.rows else None)
        rows = [row for row in self.rows if row["batch_date"] == selected_date]
        return {"batch_date": selected_date, "exists": bool(rows), "expected": len(rows),
                "accepted": sum(bool(row.get("payload")) for row in rows), "counts": dict(Counter(row["status"] for row in rows)),
                "attempts": sum(int(row.get("attempts") or 0) for row in rows),
                "last_update": self.base_coverage.get("last_update") if self.base_coverage.get("batch_date") == selected_date else None}


def track_record_view(store: PredictionStore, *, enabled=False, limit=50, offset=0,
                      ticker=None, status=None, prediction_type=None, days=None, now=None) -> dict:
    now = now or utc_now()
    end_date = now.astimezone(NY).date()
    cutoff = (end_date - timedelta(days=days - 1)).isoformat() if days else None
    rows = [row for row in store._rows() if (not cutoff or cutoff <= row["batch_date"] <= end_date.isoformat())
            and (not ticker or row["ticker"] == ticker) and (not prediction_type or row["prediction_type"] == prediction_type)]
    original_coverage = store.coverage()
    result = _ReportView(rows, original_coverage).public_report(enabled=enabled, limit=limit, offset=offset,
                                                            ticker=ticker, status=status, prediction_type=prediction_type)
    cohorts = {}
    daily = defaultdict(lambda: defaultdict(lambda: [0, 0, 0]))
    by_id = {row["id"]: row for row in rows}
    versions, scorers = set(), set()
    for row in rows:
        context = json.loads(row["context_json"])
        prediction = json.loads(row["payload"]) if row.get("payload") else {}
        audit = prediction.get("metadata") or {}
        if prediction.get("strategy_version"):
            versions.add(prediction["strategy_version"])
        if context.get("scorer_version"):
            scorers.add(context["scorer_version"])
        if row["prediction_type"] != "direction" or not audit.get("model_confirmed") or not row.get("outcome_json"):
            continue
        outcome = json.loads(row["outcome_json"])
        cohort = {"agent": row["agent"], "prediction_type": row["prediction_type"], "actual_model": str(audit.get("actual_model") or "unknown"),
                  "model_confirmed": True, "prompt_version": prediction.get("prompt_version", ""),
                  "strategy_version": prediction.get("strategy_version", STRATEGY_VERSION), "scorer_version": context["scorer_version"]}
        key = hashlib.sha256(json.dumps(cohort, sort_keys=True).encode()).hexdigest()[:16]
        cohorts[key] = cohort
        bucket = daily[key][row["batch_date"]]
        bucket[0] += 1; bucket[1] += int(outcome["hit"]); bucket[2] += int(outcome["baseline_hit"])
    series = []
    for key, dates in daily.items():
        cumulative = [0, 0, 0]
        for day, counts in sorted(dates.items()):
            cumulative = [old + added for old, added in zip(cumulative, counts)]
            n, hits, baseline = cumulative
            series.append({"date": day, "n": n, "hits": hits, "baseline_hits": baseline,
                           "hit_rate": hits / n, "baseline_hit_rate": baseline / n, "cohort_key": key, **cohorts[key]})
    for record in result["records"]:
        row = by_id[record["id"]]
        prediction = json.loads(row["payload"]) if row.get("payload") else {}
        context = json.loads(row["context_json"])
        record.update(confidence=prediction.get("confidence"), strategy_version=prediction.get("strategy_version"),
                      scorer_version=context.get("scorer_version"))
    settled_ids = [row["id"] for row in result["records"] if row.get("outcome")]
    if settled_ids:
        with store.connection() as conn:
            placeholders = ",".join("?" for _ in settled_ids)
            market = {row[0]: json.loads(row[1]) for row in conn.execute(
                f"SELECT opportunity_id,market_json FROM prediction_settlements WHERE opportunity_id IN ({placeholders})", settled_ids)}
        for record in result["records"]:
            if record["id"] in market:
                record["settlement_bars"] = [{key: bar[key] for key in
                    ("time", "date", "open", "high", "low", "close", "volume", "source", "currency", "price_basis") if key in bar}
                    for bar in market[record["id"]] if isinstance(bar, dict)]
    window = next((candidate for offset in range(8) if (candidate := window_for_date(end_date - timedelta(days=offset))) is not None), None)
    metadata = result["metadata"]
    pending_ends = [timestamp(json.loads(row["context_json"])["window_end"]) for row in rows
                    if row["status"] in {"pending", "awaiting_data"} and row.get("payload")]
    next_end = min(pending_ends) if pending_ends else None
    metadata.update({"frequency": "trading_day", "expected_symbols": len(TICKERS),
                     "prediction_types_per_symbol": len(get_args(PredictionType)),
                     "min_sample_size": max(1, int(os.getenv("TRACK_RECORD_MIN_SAMPLE_SIZE", "30"))),
                     "direction_baseline": "always_up", "interpretation_rule_version": "track-record-display-v1",
                     "strategy_version": STRATEGY_VERSION, "strategy_versions": sorted(versions), "scorer_versions": sorted(scorers),
                     "range": {"days": days, "start": cutoff, "end": end_date.isoformat()}, "status_filter_scope": "records_only",
                     "daily_series_scope": "confirmed_direction_per_model_and_rule_version"})
    metadata["next_settlement_date"] = next_end.astimezone(NY).date().isoformat() if next_end else None
    metadata["overdue_records_count"] = sum(end <= now for end in pending_ends)
    if window:
        metadata.update(collection_start_et=timestamp(window.collection_at).astimezone(NY).strftime("%H:%M"),
                        collection_deadline_et=timestamp(window.deadline_at).astimezone(NY).strftime("%H:%M"),
                        calendar_version=window.calendar_version, scorer_version=window.context(TICKERS[0])["scorer_version"])
    result["daily_series"] = series
    return result
