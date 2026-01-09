#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tests for chart generation triggers.
"""

from backend.api.chart_detector import ChartTypeDetector


def test_should_generate_chart_for_hangqing_query():
    assert ChartTypeDetector.should_generate_chart("\u8c37\u6b4c\u6700\u8fd1\u884c\u60c5\u5982\u4f55") is True
