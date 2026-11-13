"""完整评测输入的外部判分绑定；哈希校验不证明声明身份的真实性。"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .scoring import ContentScore, EXTERNAL_JUDGE, SCORE_FIELDS, judge_prompt
from .tapes import canonical_json


class ExternalJudgmentError(ValueError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


class ExternalIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    model: Literal["gpt-6.1-sol"]
    provider: Literal["codex-native"]
    role: Literal["verifier"]
    protocol: Literal["external"]
    base_url: None
    context_window: None
    max_output: None


class ExternalJudgment(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    request_sha256: str = Field(pattern="^[0-9a-f]{64}$")
    judge: ExternalIdentity
    score: ContentScore


def checksum(value) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def request_document(case: dict, row: dict, recordings: list[dict]) -> dict:
    if row["model"] == EXTERNAL_JUDGE["model"]:
        raise ExternalJudgmentError("judge_must_differ_from_subject")
    payload = {"case": deepcopy(case), "answers": deepcopy(row["turns"]), "recordings": deepcopy(recordings)}
    prompt = judge_prompt("external")
    bindings = {key + "_sha256": checksum(value) for key, value in payload.items()}
    bindings.update(prompt_sha256=hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
                    judge_sha256=checksum(EXTERNAL_JUDGE), subject_model_sha256=checksum(row["model"]))
    return {"schema_version": 1, "case_id": case["id"], "subject_model": row["model"],
            "judge": deepcopy(EXTERNAL_JUDGE), "prompt": prompt, "input": payload,
            "response_schema": ExternalJudgment.model_json_schema(), "bindings": bindings}


def write_request(case: dict, row: dict, recordings: list[dict], eval_dir: Path, run_id: str) -> dict:
    root = (eval_dir / "requests").resolve()
    target = (root / run_id / (case["id"] + ".json")).resolve()
    if not target.is_relative_to(root):
        raise ExternalJudgmentError("external_judge_request_path_invalid")
    request = request_document(case, row, recordings)
    digest = checksum(request)
    if target.exists():
        try:
            previous = json.loads(target.read_text(encoding="utf-8"))
        except ValueError:
            raise ExternalJudgmentError("external_judge_request_invalid") from None
        if checksum(previous) != digest:
            raise ExternalJudgmentError("external_judge_request_already_exists")
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(canonical_json(request) + "\n", encoding="utf-8")
    return {"request_path": target.relative_to(eval_dir.parent.parent.resolve()).as_posix(),
            "request_sha256": digest}


def bound_recordings(case: dict, snapshot: list[dict], current: list[dict]) -> list[dict]:
    """核验当时绑定的资料；迟到记录留在最终库，不倒灌到原评分输入。"""
    records = {record["key"]: record for record in current}
    bound = []
    for record in snapshot:
        if record.get("injected") is not True:
            actual = records.get(record.get("key"))
            if actual is None or checksum(actual) != checksum(record):
                raise ExternalJudgmentError("external_judge_request_mismatch")
            bound.append(actual)
            continue
        declared = case.get("tool_faults", {}).get(record.get("tool"))
        fields = {key: value for key, value in record.items() if key != "checksum"}
        raw = record.get("raw_output", {})
        if (not declared or record.get("checksum") != checksum(fields)
                or record.get("key") != checksum({"tool": record["tool"], "arguments": record["arguments"]})
                or record.get("result", {}).get("status") != declared["status"]
                or raw.get("status") != declared["status"]
                or (declared["status"] == "error" and raw.get("error_code") != declared.get("code", "injected_tool_error"))
                or (declared["status"] == "empty" and raw.get("data") != [])):
            raise ExternalJudgmentError("external_judge_injected_record_mismatch")
        bound.append(record)
    return bound


def import_judgment(case: dict, row: dict, recordings: list[dict], eval_dir: Path, judgments_dir: Path) -> dict:
    reference = row.get("external_judge")
    if not isinstance(reference, dict) or set(reference) != {"request_path", "request_sha256"}:
        raise ExternalJudgmentError("external_judge_request_reference_invalid")
    root = (eval_dir / "requests").resolve()
    path = (eval_dir.parent.parent / reference["request_path"]).resolve()
    if not path.is_relative_to(root):
        raise ExternalJudgmentError("external_judge_request_path_invalid")
    if not path.is_file():
        raise ExternalJudgmentError("external_judge_request_missing")
    try:
        stored = json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        raise ExternalJudgmentError("external_judge_request_invalid") from None
    restored = bound_recordings(case, stored.get("input", {}).get("recordings", []), recordings)
    expected = request_document(case, row, restored)
    expected_hash = checksum(expected)
    if checksum(stored) != reference["request_sha256"] or expected_hash != reference["request_sha256"]:
        raise ExternalJudgmentError("external_judge_request_mismatch")
    score_path = (judgments_dir / (case["id"] + ".json")).resolve()
    if not score_path.is_relative_to(judgments_dir.resolve()):
        raise ExternalJudgmentError("external_judgment_path_invalid")
    if not score_path.is_file():
        raise ExternalJudgmentError("external_judgment_missing")
    try:
        judgment = ExternalJudgment.model_validate_json(score_path.read_text(encoding="utf-8"))
    except ValidationError:
        raise ExternalJudgmentError("external_judgment_invalid") from None
    if judgment.request_sha256 != expected_hash or judgment.judge.model_dump() != EXTERNAL_JUDGE:
        raise ExternalJudgmentError("external_judgment_mismatch")
    score = judgment.score.model_dump()
    accepted = {**score, "total": sum(score[field] for field in SCORE_FIELDS),
                "model": EXTERNAL_JUDGE["model"], "request_sha256": expected_hash}
    if row.get("score") is not None and row["score"] != accepted:
        raise ExternalJudgmentError("external_judgment_existing_score_mismatch")
    return accepted
