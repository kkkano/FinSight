import logging
from typing import Optional

import requests
from bs4 import BeautifulSoup

from backend.security.ssrf import is_safe_url
from .http import _http_get

logger = logging.getLogger(__name__)

def fetch_url_content(url: str, max_length: int = 5000) -> Optional[str]:
    """
    抓取 URL 内容并提取正文文本
    用于从新闻链接中提取内容供上下文分析

    Args:
        url: 要抓取的 URL
        max_length: 返回内容的最大长度

    Returns:
        提取的文本内容，失败返回 None
    """
    try:
        if not is_safe_url(url):
            logger.info(f"[fetch_url_content] Blocked unsafe url: {url}")
            return None
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
        }

        response = _http_get(url, headers=headers, timeout=15, allow_redirects=True)
        if response.url and not is_safe_url(response.url):
            logger.info(f"[fetch_url_content] Blocked unsafe redirect: {response.url}")
            return None
        response.raise_for_status()

        # 使用 BeautifulSoup 解析 HTML
        soup = BeautifulSoup(response.text, "html.parser")

        # 移除脚本和样式
        for tag in soup(["script", "style", "nav", "footer", "header", "aside", "iframe", "noscript"]):
            tag.decompose()

        # 尝试找到主要内容区域
        main_content = None
        for selector in ["article", "main", ".article-content", ".post-content", ".entry-content", "#content", ".content"]:
            main_content = soup.select_one(selector)
            if main_content:
                break

        # 如果没找到主要内容，使用 body
        if not main_content:
            main_content = soup.body if soup.body else soup

        # 提取文本
        text = main_content.get_text(separator="\n", strip=True)

        # 清理多余空白
        lines = [line.strip() for line in text.split("\n") if line.strip()]
        text = "\n".join(lines)

        # 截断到最大长度
        if len(text) > max_length:
            text = text[:max_length] + "..."

        logger.info(f"[fetch_url_content] 成功抓取 {url[:50]}... ({len(text)} 字符)")
        return text

    except requests.exceptions.Timeout:
        logger.info(f"[fetch_url_content] 超时: {url}")
        return None
    except requests.exceptions.RequestException as e:
        logger.info(f"[fetch_url_content] 请求失败: {url}, error: {e}")
        return None
    except Exception as e:
        logger.info(f"[fetch_url_content] 解析失败: {url}, error: {e}")
        return None
