"""一次研究内共享外部数据：线程安全去重，不跨用户或运行缓存。"""
from __future__ import annotations

from concurrent.futures import Future
from contextlib import contextmanager
from contextvars import ContextVar
import copy
import inspect
import json
from threading import Lock
from typing import Any, Callable


class RequestData:
    def __init__(self):
        self._lock = Lock()
        self._values: dict[str, Future] = {}
        self.calls = 0
        self.reused = 0

    @staticmethod
    def _key(name: str, inputs: dict[str, Any]) -> str:
        return name + ":" + json.dumps(inputs, sort_keys=True, ensure_ascii=False, default=str)

    def call(self, name: str, inputs: dict[str, Any], fetch: Callable[[], Any]) -> Any:
        key = self._key(name, inputs)
        with self._lock:
            future = self._values.get(key)
            owner = future is None
            if owner:
                future = self._values[key] = Future()
                self.calls += 1
            else:
                self.reused += 1
        if owner:
            try:
                future.set_result(fetch())
            except BaseException as error:
                future.set_exception(error)
        return copy.deepcopy(future.result())


_current: ContextVar[RequestData | None] = ContextVar("research_request_data", default=None)


@contextmanager
def request_data_scope():
    data = RequestData()
    token = _current.set(data)
    try:
        yield data
    finally:
        _current.reset(token)


def current_request_data() -> RequestData | None:
    return _current.get()


class SharedToolView:
    """Agent 获得工具视图；真正取数共享同一请求的数据缓存。"""
    def __init__(self, module: Any, data: RequestData | None):
        self._module, self._data = module, data

    def __getattr__(self, name: str):
        function = getattr(self._module, name)
        if self._data is None or not callable(function) or inspect.isclass(function):
            return function

        def invoke(*args, **kwargs):
            bound = inspect.signature(function).bind(*args, **kwargs)
            bound.apply_defaults()
            return self._data.call(name, dict(bound.arguments), lambda: function(*args, **kwargs))
        return invoke
