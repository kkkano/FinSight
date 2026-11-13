"""只加载研究运行时的私有配置，不改变 US20 的服务端模型。"""
from __future__ import annotations

import os
from dataclasses import dataclass, field, replace
from pathlib import Path
from dotenv import load_dotenv

# 官方规格与运行输出预算分开：最大输出不是每次请求都要预留的额度。
# https://api-docs.deepseek.com/zh-cn/quick_start/pricing
# https://huggingface.co/deepseek-ai/DeepSeek-V4.1-Flash-1017/raw/main/config.json
# https://www.alibabacloud.com/help/en/model-studio/qwen3-8-flash
# https://platform.stepfun.com/docs/zh/guides/models/step-5-preview
MODEL_LIMITS = {
    "deepseek-v4.1-flash-1017": (1048576, 393216),
    "qwen3.8-flash": (1000000, 131072),
    "step-5-preview": (1000000, 65536),
}


def model_budgets(model: str) -> tuple[int, int]:
    limits = MODEL_LIMITS.get(model)
    return (limits[0], min(16384, limits[1])) if limits else (32768, 8192)


def load_local_config() -> None:
    """仅启动命令显式加载；测试/模块导入不读取用户私有配置。"""
    load_dotenv(Path(__file__).resolve().parents[2] / ".env.runtime.local", override=False)
    from backend.config.settings import clear_settings_caches
    clear_settings_caches()


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

    def public_metadata(self) -> dict:
        """公开诊断投影显式省略凭据；调用模型仍持有内存中的原密钥。"""
        from urllib.parse import urlsplit, urlunsplit
        try:
            uri = urlsplit(self.base_url)
            base = urlunsplit((uri.scheme, uri.netloc.rsplit("@", 1)[-1], uri.path, "", ""))
        except ValueError:
            base = ""
        return {"model": self.model, "base_url": base, "endpoint_name": self.endpoint_name,
                "context_window": self.context_window, "max_output": self.max_output, "effort": self.effort}




def configured_model():
    from backend.config.settings import providers_settings, runtime_settings
    providers = providers_settings()
    if not providers.agent_model.strip():
        return None
    runtime = runtime_settings()
    model = providers.agent_model.strip()
    window, output = model_budgets(model)
    return ModelConfig(
        model=model,
        base_url=providers.agent_api_base.rstrip("/"),
        api_key=providers.agent_api_key,
        context_window=max(4096, runtime.context_window if runtime.context_window is not None else window),
        max_output=max(512, runtime.max_output_tokens if runtime.max_output_tokens is not None else output),
    )


def stepfun_research_model(effort: str = "medium") -> ModelConfig | None:
    """研究界面的按量 API 选项，不参与冻结预测的默认端点选择。"""
    key = os.getenv("FINSIGHT_AGENT_STEPFUN_API_KEY", "").strip()
    if not key:
        return None
    window, output = model_budgets("step-5-preview")
    return ModelConfig("step-5-preview", "https://api.stepfun.com/v1", key,
                       "research-stepfun-api", window, output, effort)


def qwen_research_model() -> ModelConfig | None:
    """用户授权的研究备用选项；密钥不参与冻结预测的默认解析。"""
    key = os.getenv("FINSIGHT_AGENT_QWEN_API_KEY", "").strip()
    if not key:
        return None
    window, output = model_budgets("qwen3.8-flash")
    return ModelConfig("qwen3.8-flash", "https://api.kunyou.asia/v1", key,
                       "research-qwen-api", window, output)


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

