"""独立空闲窗口的合成容量/PNG能力探针；真实用量单独记录，不宣称官方最大值。"""
import argparse
import asyncio
import base64
from io import BytesIO
import hashlib
import importlib.util
import json
import os
from pathlib import Path
from unittest.mock import patch

from dotenv import dotenv_values
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("quota_probe", Path(__file__).with_name("grade_apikl_budgeted.py"))
quota = importlib.util.module_from_spec(spec)
spec.loader.exec_module(quota)
from backend.agent_runtime.context import tokens


def capacity_messages():
    prefix = "以下是无敏感内容的容量测试，合成序列不需要分析。读完后仅回复OK。\n"
    pattern = "alpha beta gamma delta epsilon zeta eta theta\n"
    lower, upper = 0, 30000
    while lower + 1 < upper:
        middle = (lower + upper) // 2
        candidate = [{"role": "user", "content": prefix + pattern * middle + "\n仅回复OK。"}]
        if tokens(candidate) <= 126000:
            lower = middle
        else:
            upper = middle
    messages = [{"role": "user", "content": prefix + pattern * lower + "\n仅回复OK。"}]
    return messages, {"pattern": pattern, "repetitions": lower, "configured_input_token_estimate": tokens(messages),
        "input_utf8_bytes": len(messages[0]["content"].encode()),
        "input_sha256": hashlib.sha256(messages[0]["content"].encode()).hexdigest(), "sensitive_content": False}


def vision_messages():
    image = Image.new("RGB", (96, 96), "white")
    draw = ImageDraw.Draw(image)
    colors = {"top_left": "blue", "top_right": "yellow", "bottom_left": "magenta", "bottom_right": "cyan"}
    boxes = {"top_left": (2, 2, 45, 45), "top_right": (50, 2, 93, 45),
             "bottom_left": (2, 50, 45, 93), "bottom_right": (50, 50, 93, 93)}
    for name, color in colors.items():
        draw.rectangle(boxes[name], fill=color)
    stream = BytesIO()
    image.save(stream, format="PNG")
    raw = stream.getvalue()
    messages = [{"role": "user", "content": [{"type": "text", "text": "识别图中四个象限色块的颜色，只调用submit_vision提交英文颜色名。"},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64," + base64.b64encode(raw).decode()}}]}]
    schema = {"type": "function", "function": {"name": "submit_vision", "description": "提交实际图片四个象限的颜色。",
        "parameters": {"type": "object", "properties": {name: {"type": "string", "enum": ["red", "green", "blue", "yellow", "cyan", "magenta", "black", "white"]} for name in colors},
                       "required": list(colors), "additionalProperties": False}}}
    return messages, schema, colors, {"width": 96, "height": 96, "image_bytes": len(raw),
        "image_sha256": hashlib.sha256(raw).hexdigest(), "sensitive_content": False}


async def main(args):
    output = ROOT / "tests/agent_eval/results/m0_apikl_terra_capacity_vision_20261113.json"
    if output.exists():
        raise ValueError("capacity_vision_probe_already_recorded")
    settings = dotenv_values(ROOT / ".env.runtime.local")
    if settings["FINSIGHT_EVAL_APIKL_MODEL"] != "gpt-6.1-terra":
        raise ValueError("terra_probe_configuration_changed")
    model = quota.ModelConfig("gpt-6.1-terra", settings["FINSIGHT_EVAL_APIKL_API_BASE"], settings["FINSIGHT_EVAL_APIKL_API_KEY"],
                              context_window=131072, max_output=512)
    attempts, rows = [], []
    transport = quota.quota_transport_class(Path(args.shared_quota), attempts)(model)
    environment = {"FINSIGHT_AGENT_MODEL_CONCURRENCY": "2", "FINSIGHT_AGENT_RPM_LIMIT": "30",
        "FINSIGHT_AGENT_TPM_LIMIT": "250000", "FINSIGHT_AGENT_MIN_REQUEST_INTERVAL_SECONDS": "10",
        "FINSIGHT_AGENT_TOKEN_BUDGET": "160000"}
    with patch.dict(os.environ, environment):
        for kind in ("capacity", "vision"):
            if kind == "capacity":
                messages, metadata = capacity_messages()
                tools, choice = [], None
            else:
                messages, schema, expected, metadata = vision_messages()
                tools, choice = [schema], {"type": "function", "function": {"name": "submit_vision"}}
            row = {"probe": kind, **metadata}
            calls, text, usage = {}, "", {}
            try:
                async for chunk in transport.stream(messages, tools, max_tokens=64 if kind == "capacity" else 512,
                                                     tool_choice=choice, timeout=120):
                    usage = chunk.get("usage") or usage
                    for item in chunk.get("choices", []):
                        if item.get("finish_reason"):
                            row["finish_reason"] = item["finish_reason"]
                        delta = item.get("delta") or {}
                        text += delta.get("content") or ""
                        for call in delta.get("tool_calls", []):
                            target = calls.setdefault(call.get("index", 0), {"name": "", "arguments": ""})
                            target["name"] += (call.get("function") or {}).get("name") or ""
                            target["arguments"] += (call.get("function") or {}).get("arguments") or ""
                row["usage"] = usage
                if kind == "capacity":
                    row["passed"] = text.strip() == "OK" and bool(usage.get("prompt_tokens"))
                    row["actual_reported_input_tokens"] = usage.get("prompt_tokens")
                    row["largest_tested_input_only_not_official_maximum"] = True
                else:
                    call = next(iter(calls.values())) if len(calls) == 1 else {}
                    answer = json.loads(call.get("arguments", "{}"))
                    row.update(actual_answer=answer, expected_colors=expected,
                               passed=call.get("name") == "submit_vision" and answer == expected)
            except Exception as exc:
                row.update(passed=False, error_code=getattr(exc, "code", type(exc).__name__))
            rows.append(row)
            report = {"model": model.model, "probes": rows, "quota_attempts": attempts,
                      "probe_source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                      "official_context_output_or_image_limits_verified": False,
                      "financial_chart_ocr_accuracy_measured": False}
            output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            print(json.dumps(row, ensure_ascii=False), flush=True)
    return 0 if all(row["passed"] for row in rows) else 2


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--shared-quota", required=True)
    raise SystemExit(asyncio.run(main(parser.parse_args())))
