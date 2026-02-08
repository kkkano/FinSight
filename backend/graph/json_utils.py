# -*- coding: utf-8 -*-
from __future__ import annotations

import json
from datetime import date, datetime, time as dt_time
from typing import Any


def _json_default(value: object) -> str:
    if isinstance(value, (datetime, date, dt_time)):
        return value.isoformat()
    return str(value)


def json_dumps_safe(obj: Any, **kwargs: Any) -> str:
    """
    JSON dump helper that tolerates datetime/date/time and other non-JSON-native types.
    """
    return json.dumps(obj, default=_json_default, **kwargs)

