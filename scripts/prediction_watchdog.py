#!/usr/bin/env python3
"""Independent prediction health watchdog; run separately from the API process.

Examples: python scripts/prediction_watchdog.py --once
          python scripts/prediction_watchdog.py

Configure PREDICTION_HEALTH_URL, PREDICTION_ALERT_EMAIL and optionally
PREDICTION_WATCHDOG_STATE. No collection or scheduler module is imported.
"""

from __future__ import annotations

import argparse
import copy
import json
import logging
import os
import sys
import tempfile
import time
import smtplib
import ssl
from email.message import EmailMessage
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
POLL_INTERVAL_SECONDS = 300
AVAILABILITY_COOLDOWN_SECONDS = 6 * 60 * 60
MAX_DELIVERY_ATTEMPTS = 3
_COMPONENT_STATUSES = {"disabled", "not_due", "collecting", "ok", "partial", "missing", "low_coverage"}
_SAFE_SEND_CODES = {"smtp_unconfigured", "smtp_transient", "smtp_permanent", "smtp_configuration", "smtp_failed"}


@dataclass(frozen=True)
class Observation:
    http_status: int | None = None
    payload: dict[str, Any] | None = None
    error_code: str | None = None


@dataclass(frozen=True)
class Delivery:
    success: bool
    error_code: str | None = None
    attempted: bool = True


def _iso(now: datetime) -> str:
    return now.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _elapsed(now: datetime, timestamp: str | None) -> float:
    if not timestamp:
        return float("inf")
    return (now - datetime.fromisoformat(timestamp.replace("Z", "+00:00"))).total_seconds()


def fetch_health(url: str, timeout: float = 10.0) -> Observation:
    """Read JSON even on HTTP 503; never expose the URL or exception text."""
    request = Request(url, headers={"Accept": "application/json", "User-Agent": "FinSight-Prediction-Watchdog/1"})
    try:
        try:
            response = urlopen(request, timeout=timeout)
        except HTTPError as exc:
            response = exc
        with response:
            status = response.status
            raw = response.read(1_000_001)
        if len(raw) > 1_000_000:
            return Observation(status, error_code="health_invalid_json")
        payload = json.loads(raw.decode("utf-8"))
        if not isinstance(payload, dict):
            return Observation(status, error_code="health_invalid_json")
        return Observation(status, payload)
    except (URLError, OSError, TimeoutError):
        return Observation(error_code="health_unreachable")
    except (UnicodeError, ValueError):
        return Observation(error_code="health_invalid_json")


def _component(observation: Observation) -> tuple[dict[str, Any] | None, str | None]:
    if observation.error_code:
        return None, observation.error_code
    components = (observation.payload or {}).get("components")
    candidate = components.get("prediction_collection") if isinstance(components, dict) else None
    if not isinstance(candidate, dict):
        return None, "health_component_missing"
    if (
        type(candidate.get("enabled")) is not bool
        or candidate.get("status") not in _COMPONENT_STATUSES
        or type(candidate.get("alert_required")) is not bool
        or type(candidate.get("accepted")) is not int
        or type(candidate.get("expected")) is not int
        or candidate["expected"] != 40
        or not 0 <= candidate["accepted"] <= 40
    ):
        return None, "health_component_invalid"
    batch_date = candidate.get("batch_date")
    if batch_date is not None:
        try:
            if not isinstance(batch_date, str) or date.fromisoformat(batch_date).isoformat() != batch_date:
                raise ValueError
        except ValueError:
            return None, "health_component_invalid"
    if candidate["alert_required"] and not batch_date:
        return None, "health_component_invalid"
    return {key: candidate.get(key) for key in (
        "enabled", "status", "batch_date", "expected", "accepted", "alert_required",
    )}, None


def advance_state(state: dict[str, Any], observation: Observation, now: datetime) -> tuple[dict[str, Any], list[str]]:
    """Pure transition: decide which active events require delivery without sending."""
    updated = copy.deepcopy(state)
    updated.setdefault("version", 1)
    events = updated.setdefault("events", {})
    component, protocol_error = _component(observation)
    unavailable = protocol_error is not None or observation.http_status != 200
    error_code = protocol_error or ("health_http_unavailable" if unavailable else None)
    updated["last_checked_at"] = _iso(now)
    updated["last_health"] = {
        "http_status": observation.http_status,
        "error_code": error_code,
        "prediction_status": component["status"] if component else "unknown",
        "batch_date": component["batch_date"] if component else None,
        "accepted": component["accepted"] if component else None,
        "expected": component["expected"] if component else 40,
    }
    active: list[str] = []

    def event(key: str, kind: str, **details: Any) -> dict[str, Any]:
        entry = events.setdefault(key, {
            "kind": kind, "created_at": _iso(now), "attempts": 0,
            "status": "pending", "last_error": None, "sent_at": None,
        })
        entry.update(details)
        return entry

    if unavailable:
        updated["consecutive_failures"] = updated.get("consecutive_failures", 0) + 1
        if not updated.get("failure_event"):
            updated["failure_event"] = "availability:" + _iso(now)
        if updated["consecutive_failures"] >= 2:
            key = updated["failure_event"]
            entry = event(key, "availability", error_code=error_code)
            if entry["status"] != "sent" and _elapsed(now, updated.get("last_availability_sent_at")) < AVAILABILITY_COOLDOWN_SECONDS:
                entry["status"] = "cooldown"
            else:
                active.append(key)
    else:
        updated["consecutive_failures"] = 0
        updated["failure_event"] = None

    # The backend owns calendar/time eligibility. The watchdog cannot start or backfill a batch.
    if (
        component and component["enabled"] and component["alert_required"]
        and component["status"] in {"missing", "low_coverage"}
        and component["accepted"] < 30
    ):
        key = "coverage:" + component["batch_date"]
        event(key, "coverage", batch_date=component["batch_date"], accepted=component["accepted"],
              expected=component["expected"], prediction_status=component["status"])
        active.append(key)
    return updated, active


def load_state(path: Path) -> dict[str, Any]:
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"version": 1, "events": {}, "consecutive_failures": 0}
    if not isinstance(state, dict) or state.get("version") != 1 or not isinstance(state.get("events"), dict):
        raise ValueError("invalid watchdog state")
    return state


def save_state(path: Path, state: dict[str, Any]) -> None:
    """Atomic same-directory replacement keeps restart deduplication durable."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, prefix=path.name + ".", suffix=".tmp", delete=False) as handle:
            temporary_path = Path(handle.name)
            json.dump(state, handle, ensure_ascii=False, indent=2, allow_nan=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def send_notification(recipient: str, subject: str, text: str) -> Delivery:
    """使用环境中的 SMTP 配置；不依赖 API 进程或已移除的通知服务。"""
    host = os.getenv("SMTP_SERVER", "").strip()
    user = os.getenv("SMTP_USER", "").strip()
    password = os.getenv("SMTP_PASSWORD", "")
    if not host or not user or not password:
        return Delivery(False, "smtp_unconfigured", attempted=False)
    try:
        port = int(os.getenv("SMTP_PORT", "587"))
        message = EmailMessage()
        message["From"] = os.getenv("EMAIL_FROM", "").strip() or user
        message["To"] = recipient
        message["Subject"] = subject
        message.set_content(text)
    except (TypeError, ValueError):
        return Delivery(False, "smtp_configuration", attempted=False)
    try:
        context = ssl.create_default_context()
        client = smtplib.SMTP_SSL(host, port, timeout=20, context=context) if port == 465 else smtplib.SMTP(host, port, timeout=20)
        with client:
            if port != 465:
                client.starttls(context=context)
            client.login(user, password)
            refused = client.send_message(message)
        return Delivery(not refused, "smtp_permanent" if refused else None)
    except smtplib.SMTPResponseException as exc:
        return Delivery(False, "smtp_permanent" if exc.smtp_code >= 500 else "smtp_transient")
    except (OSError, smtplib.SMTPException):
        return Delivery(False, "smtp_transient")
    except Exception:
        return Delivery(False, "smtp_failed")


def _message(event: dict[str, Any]) -> tuple[str, str]:
    if event["kind"] == "coverage":
        return (
            f"FinSight 预测采集告警：{event['batch_date']}",
            f"交易日 {event['batch_date']} 的预测采集状态为 {event['prediction_status']}。\n"
            f"有效预测：{event['accepted']}/{event['expected']}；低于告警阈值 30/40。\n"
            "请检查预测任务及持久化采集记录。此检查器不会补采或更改预测。",
        )
    return (
        "FinSight 后端可用性告警",
        "连续两次健康检查未能确认后端及预测监测组件可用。\n"
        f"状态：{event['error_code']}。请检查后端进程和健康接口。",
    )


def check_once(
    *, state_path: Path, health_url: str, recipient: str | None,
    now: datetime | None = None, fetch: Callable[[str], Observation] = fetch_health,
    sender: Callable[[str, str, str], Delivery] = send_notification,
    retry_interval_seconds: float = POLL_INTERVAL_SECONDS,
) -> dict[str, Any]:
    """Persist the check and each delivery attempt; print only the returned safe summary."""
    now = now or datetime.now(timezone.utc)
    state, active = advance_state(load_state(state_path), fetch(health_url), now)
    save_state(state_path, state)
    deliveries = []
    for key in active:
        entry = state["events"][key]
        if entry["status"] == "sent":
            continue
        if entry["attempts"] >= MAX_DELIVERY_ATTEMPTS:
            entry["status"] = "exhausted"
        elif not recipient or not recipient.strip():
            entry.update(status="unconfigured", last_error="recipient_unconfigured")
        elif _elapsed(now, entry.get("last_attempt_at")) < retry_interval_seconds:
            continue
        else:
            entry.update(status="sending", attempts=entry["attempts"] + 1, last_attempt_at=_iso(now))
            save_state(state_path, state)  # A restart must not regain a send attempt.
            try:
                outcome = sender(recipient.strip(), *_message(entry))
            except Exception:
                outcome = Delivery(False, "smtp_failed")
            if outcome.success:
                entry.update(status="sent", sent_at=_iso(now), last_error=None)
                if entry["kind"] == "availability":
                    state["last_availability_sent_at"] = _iso(now)
            else:
                if not outcome.attempted:
                    entry["attempts"] -= 1
                code = outcome.error_code if outcome.error_code in _SAFE_SEND_CODES else "smtp_failed"
                status = "exhausted" if entry["attempts"] >= MAX_DELIVERY_ATTEMPTS else "failed"
                entry.update(status=status if outcome.attempted else "unconfigured", last_error=code)
        deliveries.append({"kind": entry["kind"], "status": entry["status"], "attempts": entry["attempts"], "error_code": entry["last_error"]})
        save_state(state_path, state)
    return {
        "checked_at": state["last_checked_at"], **state["last_health"],
        "consecutive_failures": state.get("consecutive_failures", 0), "deliveries": deliveries,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true", help="check once and exit")
    parser.add_argument("--interval", type=float, default=POLL_INTERVAL_SECONDS, help="poll interval in seconds (default: 300)")
    args = parser.parse_args(argv)
    if args.interval <= 0:
        parser.error("--interval must be positive")
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
    configured_root = Path(os.getenv("FINSIGHT_CONFIG_DIR") or ROOT / "data")
    state_path = Path(os.getenv("PREDICTION_WATCHDOG_STATE") or configured_root / "prediction_watchdog.json")
    health_url = os.getenv("PREDICTION_HEALTH_URL", "http://127.0.0.1:8000/health")
    recipient = os.getenv("PREDICTION_ALERT_EMAIL")
    while True:
        try:
            summary = check_once(state_path=state_path, health_url=health_url, recipient=recipient,
                                 retry_interval_seconds=args.interval)
            exit_code = 0
        except (OSError, ValueError, TypeError, KeyError):
            summary = {"error_code": "watchdog_state_error"}
            exit_code = 1
        print(json.dumps(summary, ensure_ascii=False), flush=True)
        if args.once:
            return exit_code
        try:
            time.sleep(args.interval)
        except KeyboardInterrupt:
            return 0


if __name__ == "__main__":
    raise SystemExit(main())
