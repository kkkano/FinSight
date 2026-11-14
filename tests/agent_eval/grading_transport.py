"""只读评分的有界连接重试；整次响应成功后交给读者，不重抽已成功分数。"""
import asyncio
import os
import time

from backend.agent_runtime.model import BudgetedModel, ModelProtocolError
from agent_eval.grade_apikl_budgeted import quota_transport_class


class EvaluationBudgetedModel(BudgetedModel):
    """沿用预约、配额和结算合同；只读评分单次网络等待允许 240 秒。"""

    async def stream(self, messages, tools, **kwargs):
        rt, usage, reservation, started_network, finished = self.runtime, None, None, False, False
        started, status = time.monotonic(), "error"
        amount = await rt.budget.reserve(self.reservation_tokens(messages, tools, **kwargs))
        try:
            async with rt.limiter.slot("model", rt.context.owner,
                    max(1, int(os.getenv("FINSIGHT_AGENT_MODEL_CONCURRENCY", "2"))),
                    timeout=rt.context.remaining_seconds, ttl=rt.context.remaining_seconds + 15):
                spacing = max(0, float(os.getenv("FINSIGHT_AGENT_MIN_REQUEST_INTERVAL_SECONDS", "0")))
                while spacing and await asyncio.to_thread(rt.limiter.reserve_window,
                        "pace:" + self.config.provider_identity(), 0, maximum=1, requests=1, window=spacing) is None:
                    rt.context.guard()
                    await asyncio.sleep(min(1, rt.context.remaining_seconds))
                reservation = await asyncio.to_thread(rt.limiter.reserve_window,
                    "provider:" + self.config.provider_identity(), amount,
                    maximum=int(os.getenv("FINSIGHT_AGENT_TPM_LIMIT", "250000")),
                    requests=int(os.getenv("FINSIGHT_AGENT_RPM_LIMIT", "30")))
                if reservation is None:
                    raise ModelProtocolError("provider_local_quota_exhausted")
                kwargs["timeout"] = rt.context.timeout(min(240, kwargs.get("timeout", 240)))
                started_network = True
                async for chunk in self.target.stream(messages, tools, **kwargs):
                    rt.context.guard()
                    usage = chunk.get("usage") or usage
                    finished |= any(choice.get("finish_reason") is not None for choice in chunk.get("choices", []))
                    yield chunk
                if not finished:
                    raise ModelProtocolError("model_incomplete_response")
                status = "success"
        finally:
            if status == "success":
                rt.model_duration_seconds[self.spec.agent_id] = time.monotonic() - started
            prompt, completion = int((usage or {}).get("prompt_tokens", 0)), int((usage or {}).get("completion_tokens", 0))
            actual = prompt + completion if usage is not None else None if started_network else 0
            await rt.budget.settle(amount, actual)
            if reservation is not None:
                await asyncio.to_thread(rt.limiter.settle_window, reservation, actual)
            if started_network:
                from backend.services.llm_usage import LLMAttribution
                rt.context.usage.add(self.config.model, prompt, completion)
                rt.context.usage.add_attributed_attempt(model=self.config.model, status=status,
                    duration_ms=int((time.monotonic() - started) * 1000), prompt=prompt, completion=completion,
                    attribution=LLMAttribution(agent=self.spec.role, layer="agent_runtime"), usage_reported=usage is not None)


def evaluation_transport_class(shared_quota, attempts):
    return quota_transport_class(shared_quota, attempts, budgeted_model_class=EvaluationBudgetedModel,
                                 context_seconds=360)


def retrying_quota_transport_class(shared_quota, attempts, retry_events, *, maximum_attempts=3, retry_delay=1,
                                   transport_factory=evaluation_transport_class):
    base = transport_factory(shared_quota, attempts)

    class GradingTransport(base):
        async def stream(self, messages, tools, **kwargs):
            deadline = time.monotonic() + 360
            for index in range(maximum_attempts):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise ModelProtocolError('model_timeout')
                request = {**kwargs, 'timeout': min(kwargs.get('timeout', 240), remaining)}
                buffered = []
                try:
                    async for chunk in super().stream(messages, tools, **request):
                        buffered.append(chunk)
                except ModelProtocolError as error:
                    if error.code != 'model_connection_error' or index + 1 >= maximum_attempts:
                        raise
                    retry_events.append({'error_code': error.code, 'attempt': index + 1,
                                         'discarded_incomplete_chunks': len(buffered),
                                         'same_input_retried': True})
                    await asyncio.sleep(min(retry_delay * (index + 1), max(0, deadline - time.monotonic())))
                    continue
                for chunk in buffered:
                    yield chunk
                return

    return GradingTransport
