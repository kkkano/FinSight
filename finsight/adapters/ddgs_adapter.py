"""
DuckDuckGo Search 适配器 - 实现 SearchPort

使用 DuckDuckGo 执行网络搜索。
"""

import time
from typing import Dict, List, Any, Optional

from ddgs import DDGS

from finsight.ports.interfaces import (
    SearchPort,
    DataUnavailableError,
    RateLimitError,
)


class DDGSAdapter(SearchPort):
    """
    DuckDuckGo Search 适配器

    实现 SearchPort 接口，提供网络搜索功能。
    """

    def __init__(
        self,
        timeout: int = 20,
        max_retries: int = 3,
        proxy: Optional[str] = None
    ):
        """
        初始化适配器

        Args:
            timeout: 请求超时时间（秒）
            max_retries: 最大重试次数
            proxy: 代理服务器地址（可选）
        """
        self.timeout = timeout
        self.max_retries = max_retries
        self.proxy = proxy
        self.source = "DuckDuckGo"

    def search(
        self,
        query: str,
        max_results: int = 5
    ) -> List[Dict[str, Any]]:
        """
        执行网络搜索

        Args:
            query: 搜索查询
            max_results: 最大结果数

        Returns:
            List[Dict]: 搜索结果列表，每个结果包含:
                - title: 标题
                - body: 摘要
                - url: 链接
                - source: 来源
        """
        for attempt in range(self.max_retries):
            try:
                ddgs = DDGS(timeout=self.timeout)
                if self.proxy:
                    ddgs.proxies = self.proxy

                with ddgs:
                    raw_results = list(ddgs.text(query, max_results=max_results))

                if not raw_results:
                    return []

                results = []
                for res in raw_results:
                    # 确保内容为 UTF-8 编码
                    title = res.get('title', '无标题')
                    body = res.get('body', '')
                    url = res.get('href', '')

                    title = title.encode('utf-8', 'ignore').decode('utf-8')
                    body = body.encode('utf-8', 'ignore').decode('utf-8')

                    results.append({
                        'title': title,
                        'body': body[:300] if body else '',
                        'url': url,
                        'source': self.source,
                    })

                return results

            except Exception as e:
                print(f"搜索尝试 {attempt + 1} 失败: {e}")
                if attempt < self.max_retries - 1:
                    time.sleep(2 ** attempt)  # 指数退避

        raise DataUnavailableError(
            "搜索失败: 已超出最大重试次数",
            source=self.source
        )

    def search_news(
        self,
        query: str,
        max_results: int = 5,
        time_range: str = "d"  # d=day, w=week, m=month
    ) -> List[Dict[str, Any]]:
        """
        搜索新闻

        Args:
            query: 搜索查询
            max_results: 最大结果数
            time_range: 时间范围

        Returns:
            List[Dict]: 新闻结果列表
        """
        for attempt in range(self.max_retries):
            try:
                ddgs = DDGS(timeout=self.timeout)
                if self.proxy:
                    ddgs.proxies = self.proxy

                with ddgs:
                    raw_results = list(ddgs.news(
                        query,
                        max_results=max_results,
                        timelimit=time_range
                    ))

                if not raw_results:
                    return []

                results = []
                for res in raw_results:
                    results.append({
                        'title': res.get('title', ''),
                        'body': res.get('body', ''),
                        'url': res.get('url', ''),
                        'source': res.get('source', ''),
                        'date': res.get('date', ''),
                    })

                return results

            except Exception as e:
                print(f"新闻搜索尝试 {attempt + 1} 失败: {e}")
                if attempt < self.max_retries - 1:
                    time.sleep(2 ** attempt)

        raise DataUnavailableError(
            "新闻搜索失败: 已超出最大重试次数",
            source=self.source
        )
