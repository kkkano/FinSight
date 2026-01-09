#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tests for RSS parsing helpers.
"""

from datetime import datetime

from backend import tools


def test_parse_rss_items_filters_recent():
    xml_text = """<?xml version="1.0" encoding="UTF-8"?>
    <rss version="2.0">
      <channel>
        <item>
          <title>Old Item</title>
          <link>https://example.com/old</link>
          <pubDate>Mon, 01 Jan 2024 10:00:00 GMT</pubDate>
        </item>
        <item>
          <title>Recent Item</title>
          <link>https://example.com/recent</link>
          <pubDate>Thu, 09 Jan 2026 08:00:00 GMT</pubDate>
        </item>
      </channel>
    </rss>
    """
    now = datetime(2026, 1, 9, 12, 0, 0)
    lines, ok = tools._parse_rss_items(xml_text, limit=5, max_age_days=2, now=now)
    assert ok is True
    assert any("Recent Item" in line for line in lines)
    assert all("Old Item" not in line for line in lines)
