# -*- coding: utf-8 -*-
"""
Trace normalization utilities.
Re-exports from trace_schema for backward compatibility.
"""
from backend.orchestration.trace_schema import normalize_to_v1, create_trace_event

# Backward compatible alias
normalize_trace = normalize_to_v1
