"""Independent health checks and SMTP delivery use local state and fake senders."""

from __future__ import annotations

import copy
import io
import json
import logging
from datetime import datetime, timedelta, timezone
from urllib.error import HTTPError, URLError

import pytest

from scripts import prediction_watchdog as watchdog


NOW = datetime(2026, 10, 2, 13, 26, tzinfo=timezone.utc)


def health(status="ok", accepted=40, *, enabled=True, alert_required=False, http_status=200, batch_date="2026-10-02"):
    return watchdog.Observation(http_status, {"components": {"prediction_collection": {
        "enabled": enabled, "status": status, "batch_date": batch_date,
        "latest_batch_date": batch_date, "expected": 40, "accepted": accepted,
        "attempts": 40, "counts": {}, "last_update": "2026-10-02T13:18:00Z",
        "deadline_at": "2026-10-02T13:20:00Z", "alert_at": "2026-10-02T13:25:00Z",
        "alert_required": alert_required,
    }}})


class FakeSender:
    def __init__(self, outcomes=None):
        self.calls = []
        self.outcomes = list(outcomes or [])

    def __call__(self, recipient, subject, text):
        self.calls.append((recipient, subject, text))
        outcome = self.outcomes.pop(0) if self.outcomes else watchdog.Delivery(True)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def check(path, observation, sender, *, now=NOW, recipient="owner@example.test"):
    return watchdog.check_once(
        state_path=path, health_url="http://health.invalid/health", recipient=recipient,
        now=now, fetch=lambda _url: observation, sender=sender,
    )


@pytest.mark.parametrize("status,accepted,enabled", [
    ("disabled", 0, False), ("not_due", 0, True), ("collecting", 2, True),
    ("partial", 38, True), ("partial", 30, True), ("ok", 40, True),
])
def test_normal_states_do_not_send(tmp_path, status, accepted, enabled):
    sender = FakeSender()
    summary = check(tmp_path / "state.json", health(status, accepted, enabled=enabled), sender)
    assert not sender.calls and not summary["deliveries"]
    assert summary["prediction_status"] == status and summary["consecutive_failures"] == 0


@pytest.mark.parametrize("status,accepted", [("low_coverage", 29), ("missing", 0)])
def test_low_coverage_or_missing_batch_sends_once_and_survives_restart(tmp_path, status, accepted):
    path = tmp_path / "state.json"
    sender = FakeSender()
    observation = health(status, accepted, alert_required=True)
    first = check(path, observation, sender)
    restarted = FakeSender()
    second = check(path, observation, restarted, now=NOW + timedelta(minutes=5))
    assert first["deliveries"][0]["status"] == "sent" and not second["deliveries"]
    assert len(sender.calls) == 1 and not restarted.calls
    assert sender.calls[0][0] == "owner@example.test"
    assert f"{accepted}/40" in sender.calls[0][2]
    assert watchdog.load_state(path)["events"]["coverage:2026-10-02"]["attempts"] == 1


def test_coverage_dedup_uses_batch_not_error_label_and_allows_next_date(tmp_path):
    path = tmp_path / "state.json"
    sender = FakeSender()
    check(path, health("missing", 0, alert_required=True), sender)
    check(path, health("low_coverage", 29, alert_required=True), sender, now=NOW + timedelta(minutes=5))
    assert len(sender.calls) == 1
    check(path, health("missing", 0, alert_required=True, batch_date="2026-10-05"), sender, now=NOW + timedelta(days=3))
    assert len(sender.calls) == 2


def test_alert_requires_backend_time_eligibility(tmp_path):
    sender = FakeSender()
    check(tmp_path / "state.json", health("low_coverage", 29, alert_required=False), sender)
    assert not sender.calls


def test_two_consecutive_unreachable_checks_then_one_notification(tmp_path):
    path = tmp_path / "state.json"
    sender = FakeSender()
    failed = watchdog.Observation(error_code="health_unreachable")
    first = check(path, failed, sender)
    assert first["consecutive_failures"] == 1 and not sender.calls
    second = check(path, failed, sender, now=NOW + timedelta(minutes=5))
    assert second["consecutive_failures"] == 2 and len(sender.calls) == 1
    assert second["deliveries"][0]["kind"] == "availability"
    check(path, failed, sender, now=NOW + timedelta(minutes=10))
    assert len(sender.calls) == 1


def test_recovery_resets_failures_and_new_event_obeys_cooldown(tmp_path):
    path = tmp_path / "state.json"
    sender = FakeSender()
    failed = watchdog.Observation(error_code="health_unreachable")
    check(path, failed, sender)
    check(path, failed, sender, now=NOW + timedelta(minutes=5))
    recovered = check(path, health(), sender, now=NOW + timedelta(minutes=10))
    assert recovered["consecutive_failures"] == 0
    check(path, failed, sender, now=NOW + timedelta(minutes=15))
    check(path, failed, sender, now=NOW + timedelta(minutes=20))
    assert len(sender.calls) == 1
    assert any(entry["status"] == "cooldown" for entry in watchdog.load_state(path)["events"].values())
    check(path, failed, sender, now=NOW + timedelta(hours=7))
    assert len(sender.calls) == 2


def test_http_503_still_checks_component_and_tracks_availability(tmp_path):
    path = tmp_path / "state.json"
    sender = FakeSender()
    response = health("low_coverage", 29, alert_required=True, http_status=503)
    first = check(path, response, sender)
    assert first["prediction_status"] == "low_coverage" and first["consecutive_failures"] == 1
    assert first["deliveries"][0]["kind"] == "coverage"
    second = check(path, response, sender, now=NOW + timedelta(minutes=5))
    assert second["deliveries"][0]["kind"] == "availability" and len(sender.calls) == 2


@pytest.mark.parametrize("observation,code", [
    (watchdog.Observation(200, {"status": "ok"}), "health_component_missing"),
    (watchdog.Observation(200, {"components": {"prediction_collection": {"status": "ok"}}}), "health_component_invalid"),
    (watchdog.Observation(200, error_code="health_invalid_json"), "health_invalid_json"),
])
def test_missing_or_bad_monitoring_protocol_is_not_success(tmp_path, observation, code):
    path = tmp_path / "state.json"
    sender = FakeSender()
    summary = check(path, observation, sender)
    assert summary["error_code"] == code and summary["consecutive_failures"] == 1
    check(path, observation, sender, now=NOW + timedelta(minutes=5))
    assert len(sender.calls) == 1


def test_smtp_failure_has_three_persistent_attempts_then_exhausts(tmp_path):
    path = tmp_path / "state.json"
    failures = [watchdog.Delivery(False, "smtp_transient")] * 4
    sender = FakeSender(failures)
    observation = health("low_coverage", 29, alert_required=True)
    for i in range(2):
        check(path, observation, sender, now=NOW + timedelta(minutes=5 * i))
    restarted = FakeSender(failures)
    check(path, observation, restarted, now=NOW + timedelta(minutes=10))
    summary = check(path, observation, restarted, now=NOW + timedelta(minutes=15))
    assert len(sender.calls) == 2 and len(restarted.calls) == 1
    entry = watchdog.load_state(path)["events"]["coverage:2026-10-02"]
    assert entry["attempts"] == 3 and entry["status"] == "exhausted" and entry["sent_at"] is None
    assert summary["deliveries"][0]["error_code"] == "smtp_transient"


def test_failed_smtp_can_succeed_next_poll_but_not_same_instant(tmp_path):
    path = tmp_path / "state.json"
    sender = FakeSender([watchdog.Delivery(False, "smtp_transient"), watchdog.Delivery(True)])
    observation = health("missing", 0, alert_required=True)
    check(path, observation, sender)
    check(path, observation, sender)
    assert len(sender.calls) == 1
    check(path, observation, sender, now=NOW + timedelta(minutes=5))
    assert len(sender.calls) == 2
    assert watchdog.load_state(path)["events"]["coverage:2026-10-02"]["status"] == "sent"


def test_resolved_coverage_does_not_retry_old_failed_email(tmp_path):
    path = tmp_path / "state.json"
    sender = FakeSender([watchdog.Delivery(False, "smtp_transient")])
    check(path, health("low_coverage", 29, alert_required=True), sender)
    check(path, health("partial", 30), sender, now=NOW + timedelta(minutes=5))
    assert len(sender.calls) == 1


def test_missing_recipient_is_explicit_and_not_assumed_sent(tmp_path):
    path = tmp_path / "state.json"
    sender = FakeSender()
    summary = check(path, health("missing", 0, alert_required=True), sender, recipient=None)
    entry = watchdog.load_state(path)["events"]["coverage:2026-10-02"]
    assert not sender.calls and entry["attempts"] == 0 and entry["sent_at"] is None
    assert summary["deliveries"][0]["error_code"] == "recipient_unconfigured"


def test_missing_smtp_config_does_not_consume_network_attempts(tmp_path):
    path = tmp_path / "state.json"
    sender = FakeSender([watchdog.Delivery(False, "smtp_unconfigured", attempted=False)])
    summary = check(path, health("missing", 0, alert_required=True), sender)
    entry = watchdog.load_state(path)["events"]["coverage:2026-10-02"]
    assert entry["attempts"] == 0 and entry["status"] == "unconfigured"
    assert summary["deliveries"][0]["error_code"] == "smtp_unconfigured"


def test_attempt_is_saved_before_sender_runs_and_exceptions_stay_safe(tmp_path):
    path = tmp_path / "state.json"

    def sender(*_args):
        entry = watchdog.load_state(path)["events"]["coverage:2026-10-02"]
        assert entry["attempts"] == 1 and entry["status"] == "sending"
        raise RuntimeError("SMTP_PASSWORD=SECRET https://private-provider.invalid")

    summary = check(path, health("missing", 0, alert_required=True), sender)
    output = path.read_text(encoding="utf-8") + json.dumps(summary)
    assert "SECRET" not in output and "private-provider" not in output and "owner@example.test" not in output
    assert summary["deliveries"][0]["error_code"] == "smtp_failed"


def test_state_transition_is_pure_and_atomic_file_has_no_temporary_residue(tmp_path):
    initial = {"version": 1, "events": {}, "consecutive_failures": 0}
    before = copy.deepcopy(initial)
    updated, active = watchdog.advance_state(initial, health("missing", 0, alert_required=True), NOW)
    assert initial == before and active == ["coverage:2026-10-02"]
    path = tmp_path / "nested" / "watchdog.json"
    watchdog.save_state(path, updated)
    assert watchdog.load_state(path) == updated and list(path.parent.iterdir()) == [path]


def test_invalid_saved_state_is_not_silently_reset(tmp_path):
    path = tmp_path / "state.json"
    path.write_text("broken JSON", encoding="utf-8")
    sender = FakeSender()
    with pytest.raises(ValueError):
        check(path, health("missing", 0, alert_required=True), sender)
    assert not sender.calls and path.read_text(encoding="utf-8") == "broken JSON"


def test_fetch_parses_http_error_json_without_real_http(monkeypatch):
    payload = health("partial", 38).payload
    error = HTTPError("http://private.invalid", 503, "Service Unavailable", {}, io.BytesIO(json.dumps(payload).encode()))

    def unavailable(*_args, **_kwargs):
        raise error

    monkeypatch.setattr(watchdog, "urlopen", unavailable)
    observed = watchdog.fetch_health("http://health.invalid")
    assert observed.http_status == 503 and observed.payload == payload


def test_fetch_network_exception_returns_safe_code(monkeypatch):
    def unreachable(*_args, **_kwargs):
        raise URLError("SECRET private url")

    monkeypatch.setattr(watchdog, "urlopen", unreachable)
    observed = watchdog.fetch_health("http://health.invalid")
    assert observed.error_code == "health_unreachable" and observed.payload is None


def test_cli_loads_dotenv_before_checking_and_uses_environment(tmp_path, monkeypatch, capsys):
    import dotenv
    calls = []
    state_path = tmp_path / "configured.json"

    def load(_path):
        monkeypatch.setenv("PREDICTION_WATCHDOG_STATE", str(state_path))
        monkeypatch.setenv("PREDICTION_ALERT_EMAIL", "configured@example.test")
        monkeypatch.setenv("PREDICTION_HEALTH_URL", "http://fixture.invalid/health")

    monkeypatch.setattr(dotenv, "load_dotenv", load)
    monkeypatch.setattr(watchdog, "check_once", lambda **kwargs: calls.append(kwargs) or {"prediction_status": "ok"})
    assert watchdog.main(["--once"]) == 0
    assert calls[0]["state_path"] == state_path and calls[0]["recipient"] == "configured@example.test"
    assert calls[0]["health_url"] == "http://fixture.invalid/health" and calls[0]["retry_interval_seconds"] == 300
    assert json.loads(capsys.readouterr().out)["prediction_status"] == "ok"


def test_smtp_adapter_uses_tls_and_hides_provider_details(monkeypatch, caplog):
    calls = []
    for key, value in {"SMTP_SERVER":"smtp.example.test", "SMTP_USER":"sender@example.test", "SMTP_PASSWORD":"fixture-password", "SMTP_PORT":"587"}.items():
        monkeypatch.setenv(key, value)
    class FakeSMTP:
        def __init__(self, host, port, **kwargs):
            assert host == "smtp.example.test" and port == 587 and kwargs["timeout"] == 20
        def __enter__(self): return self
        def __exit__(self, *_): pass
        def starttls(self, **_): calls.append("tls")
        def login(self, *_):
            assert calls == ["tls"]
            calls.append("login")
        def send_message(self, message):
            calls.append(message)
            raise watchdog.smtplib.SMTPResponseException(451, b"SECRET provider exception")
    monkeypatch.setattr(watchdog.smtplib, "SMTP", FakeSMTP)
    with caplog.at_level(logging.ERROR):
        result = watchdog.send_notification("owner@example.test", "subject", "<plain text>")
    assert result == watchdog.Delivery(False, "smtp_transient")
    assert calls[2]["To"] == "owner@example.test"
    assert calls[2].get_content().strip() == "<plain text>" and "SECRET" not in caplog.text


def test_smtp_adapter_detects_unconfigured_service_without_sending(monkeypatch):
    monkeypatch.delenv("SMTP_PASSWORD", raising=False)
    monkeypatch.setattr(watchdog.smtplib, "SMTP", lambda *args, **kwargs: pytest.fail("must not connect"))
    result = watchdog.send_notification("owner@example.test", "subject", "text")
    assert result == watchdog.Delivery(False, "smtp_unconfigured", attempted=False)


def test_cli_defaults_to_config_dir_and_missing_recipient_stays_missing(tmp_path, monkeypatch, capsys):
    import dotenv
    calls = []
    monkeypatch.setattr(dotenv, "load_dotenv", lambda *_: None)
    for name in ("PREDICTION_WATCHDOG_STATE", "PREDICTION_ALERT_EMAIL", "PREDICTION_HEALTH_URL"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("FINSIGHT_CONFIG_DIR", str(tmp_path))
    monkeypatch.setattr(watchdog, "check_once", lambda **kwargs: calls.append(kwargs) or {"prediction_status": "disabled"})
    assert watchdog.main(["--once"]) == 0
    assert calls[0]["state_path"] == tmp_path / "prediction_watchdog.json"
    assert calls[0]["recipient"] is None and calls[0]["health_url"] == "http://127.0.0.1:8000/health"
    assert json.loads(capsys.readouterr().out)["prediction_status"] == "disabled"
