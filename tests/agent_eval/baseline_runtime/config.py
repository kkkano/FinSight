"""只加载研究运行时的私有配置，不改变 US20 的服务端模型。"""
from __future__ import annotations

import os
from dataclasses import dataclass, field, replace
from pathlib import Path
from dotenv import load_dotenv

# 官方规格与运行输出预算分开：最大输出不是每次请求都要预留的额度。
# https://api-docs.deepseek.com/zh-cn/quick_start/pricing
# https://huggingface.co/deepseek-ai/DeepSeek-V4.1-Flash-1017/raw/main/config.json
MODEL_LIMITS = {"deepseek-v4.1-flash-1017": (1048576, 393216)}


def model_budgets(model: str) -> tuple[int, int]:
    limits = MODEL_LIMITS.get(model)
    return (limits[0], min(16384, limits[1])) if limits else (32768, 8192)


def load_local_config() -> None:
    """仅启动命令显式加载；测试/模块导入不读取用户私有配置。"""
    load_dotenv(Path(__file__).resolve().parents[2] / ".env.runtime.local", override=False)


@dataclass(frozen=True)
class ModelConfig:
    model: str
    base_url: str
    api_key: str = field(repr=False)
    endpoint_name: str = "agent-default"
    context_window: int = 32768
    max_output: int = 8192
    effort: str | None = None

    def identity(self) -> str:
        import hashlib
        return hashlib.sha256((self.base_url + self.model + self.api_key + str(self.effort)).encode()).hexdigest()

    def provider_identity(self) -> str:
        """供应商账号配额不因切换同账号模型或推理档位而重新计数。"""
        import hashlib
        return hashlib.sha256((self.base_url + "\0" + self.api_key).encode()).hexdigest()


def enabled() -> bool:
    return os.getenv("FINSIGHT_RESEARCH_RUNTIME", "agent").lower() == "agent"


def configured_model():
    if not os.getenv("FINSIGHT_AGENT_MODEL", "").strip():
        return None
    model = os.environ["FINSIGHT_AGENT_MODEL"].strip()
    window, output = model_budgets(model)
    return ModelConfig(
        model=model,
        base_url=os.getenv("FINSIGHT_AGENT_API_BASE", "").rstrip("/"),
        api_key=os.getenv("FINSIGHT_AGENT_API_KEY", ""),
        context_window=max(4096, int(os.getenv("FINSIGHT_AGENT_CONTEXT_WINDOW", str(window)))),
        max_output=max(512, int(os.getenv("FINSIGHT_AGENT_MAX_OUTPUT_TOKENS", str(output)))),
    )


def resolve_model() -> ModelConfig:
    from backend.services.model_selection import current_model
    selected = current_model()
    configured = configured_model()
    # 显式用户选择优先，不静默借用系统模型。
    if selected is not None:
        if (configured is not None and selected.source == "system" and selected.model == configured.model
                and selected.base_url.rstrip("/") == configured.base_url.rstrip("/")):
            return replace(configured, effort=selected.effort)
        window, output = model_budgets(selected.model)
        return ModelConfig(selected.model, selected.base_url.rstrip("/"), selected.api_key,
                           selected.endpoint_name, window, output, selected.effort)
    if configured is not None:
        return configured
    from backend.services.model_selection import resolve_default_model
    selected = resolve_default_model()
    window, output = model_budgets(selected.model)
    return ModelConfig(selected.model, selected.base_url.rstrip("/"), selected.api_key,
                       selected.endpoint_name, window, output, selected.effort)

