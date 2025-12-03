#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""测试实际可用的导入"""

print("=" * 50)
print("测试导入可用性")
print("=" * 50)

# 测试 ddgs
print("\n1. 测试 ddgs:")
try:
    from ddgs import DDGS
    ddgs = DDGS()
    print("✅ ddgs 可用，使用: from ddgs import DDGS")
    DDGS_SOURCE = "ddgs"
except ImportError as e:
    print(f"❌ ddgs 不可用: {e}")
    DDGS_SOURCE = None
    try:
        from duckduckgo_search import DDGS
        ddgs = DDGS()
        print("✅ duckduckgo_search 可用，使用: from duckduckgo_search import DDGS")
        DDGS_SOURCE = "duckduckgo_search"
    except ImportError as e2:
        print(f"❌ duckduckgo_search 也不可用: {e2}")
        DDGS_SOURCE = None

# 测试 Tavily
print("\n2. 测试 Tavily:")
try:
    from tavily import TavilyClient
    print("✅ tavily 可用，使用: from tavily import TavilyClient")
    TAVILY_AVAILABLE = True
except ImportError as e:
    print(f"❌ tavily 不可用: {e}")
    TAVILY_AVAILABLE = False

# 测试 LangChain Tavily
print("\n3. 测试 LangChain Tavily:")
try:
    from langchain_community.tools.tavily_search import TavilySearchResults
    print("✅ langchain_community.tools.tavily_search 可用")
    LANGCHAIN_TAVILY_AVAILABLE = True
except ImportError as e:
    print(f"❌ langchain_community.tools.tavily_search 不可用: {e}")
    LANGCHAIN_TAVILY_AVAILABLE = False

print("\n" + "=" * 50)
print("总结:")
print("=" * 50)
print(f"DDGS 来源: {DDGS_SOURCE}")
print(f"Tavily 可用: {TAVILY_AVAILABLE}")
print(f"LangChain Tavily 可用: {LANGCHAIN_TAVILY_AVAILABLE}")

