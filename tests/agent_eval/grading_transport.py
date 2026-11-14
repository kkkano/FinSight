"""只读评分的有界连接重试；整次响应成功后交给读者，不重抽已成功分数。"""
import asyncio
import time

from backend.agent_runtime.model import ModelProtocolError
from agent_eval.grade_apikl_budgeted import quota_transport_class


def retrying_quota_transport_class(shared_quota, attempts, retry_events, *, maximum_attempts=3, retry_delay=1,
                                   transport_factory=quota_transport_class):
    base = transport_factory(shared_quota, attempts)

    class GradingTransport(base):
        async def stream(self, messages, tools, **kwargs):
            deadline = time.monotonic() + 180
            for index in range(maximum_attempts):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise ModelProtocolError('model_timeout')
                request = {**kwargs, 'timeout': min(kwargs.get('timeout', 90), remaining)}
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
