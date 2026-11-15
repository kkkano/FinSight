import logging
from typing import Any, Optional
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

from backend.security.ssrf import is_safe_url
logger = logging.getLogger(__name__)


def _pdf_document(url: str, final_url: str, body: bytes, max_length: int) -> Optional[dict[str, Any]]:
    """公告/财报常以 PDF 发布；抽取正文而不是把二进制当 HTML 交给模型。"""
    import io
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(body))
    parts: list[str] = []
    size = 0
    for page in reader.pages:
        text = (page.extract_text() or "").replace("\x00", "")
        lines = [line.strip() for line in text.split("\n") if line.strip()]
        if lines:
            parts.append("\n".join(lines))
            size += len(parts[-1])
        if size >= max_length:
            break
    text = "\n".join(parts)
    if not text.strip():
        logger.info(f"[fetch_url_content] PDF 无可抽取文本: {url}")
        return None
    if len(text) > max_length:
        text = text[:max_length] + "..."
    parsed = urlparse(final_url)
    metadata_title = str((reader.metadata or {}).get("/Title") or "").strip()
    return {"url": url, "final_url": final_url, "title": metadata_title or parsed.path.rsplit("/", 1)[-1] or parsed.netloc,
            "source": parsed.netloc, "description": "", "content": text}


def fetch_url_document(url: str, max_length: int = 5000) -> Optional[dict[str, Any]]:
    """Fetch a safe URL and return normalized page metadata plus readable text."""
    try:
        if not is_safe_url(url):
            logger.info(f"[fetch_url_content] Blocked unsafe url: {url}")
            return None
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
        }

        response = requests.get(url, headers=headers, timeout=8, allow_redirects=True)
        if response.url and not is_safe_url(response.url):
            logger.info(f"[fetch_url_content] Blocked unsafe redirect: {response.url}")
            return None
        response.raise_for_status()

        content_type = str(response.headers.get("Content-Type") or "").lower()
        body = response.content or b""
        if "application/pdf" in content_type or body[:5] == b"%PDF-":
            return _pdf_document(url, str(response.url or url), body, max_length)
        if content_type and not any(kind in content_type for kind in ("html", "xml", "text", "json")):
            # 图片/压缩包等二进制不能作为正文；返回空让工具如实报告不可读
            logger.info(f"[fetch_url_content] 非文本内容 {content_type}: {url}")
            return None

        soup = BeautifulSoup(response.text, "html.parser")
        title = ""
        title_tag = soup.find("title")
        if title_tag:
            title = title_tag.get_text(separator=" ", strip=True)
        if not title:
            og_title = soup.find("meta", property="og:title")
            if og_title is not None:
                title = str(og_title.get("content") or "").strip()

        description = ""
        for attrs in ({"name": "description"}, {"property": "og:description"}):
            tag = soup.find("meta", attrs=attrs)
            if tag is not None:
                description = str(tag.get("content") or "").strip()
                if description:
                    break

        for tag in soup(["script", "style", "nav", "footer", "header", "aside", "iframe", "noscript"]):
            tag.decompose()

        main_content = None
        for selector in ["article", "main", ".article-content", ".post-content", ".entry-content", "#content", ".content"]:
            main_content = soup.select_one(selector)
            if main_content:
                break

        if not main_content:
            main_content = soup.body if soup.body else soup

        text = main_content.get_text(separator="\n", strip=True)
        lines = [line.strip() for line in text.split("\n") if line.strip()]
        text = "\n".join(lines)
        if len(text) > max_length:
            text = text[:max_length] + "..."

        logger.info(f"[fetch_url_content] 成功抓取 {url[:50]}... ({len(text)} 字符)")
        final_url = str(response.url or url)
        parsed = urlparse(final_url)
        return {
            "url": url,
            "final_url": final_url,
            "title": title or parsed.netloc or url,
            "source": parsed.netloc,
            "description": description,
            "content": text,
        }

    except requests.exceptions.Timeout:
        logger.info(f"[fetch_url_content] 超时: {url}")
        return None
    except requests.exceptions.RequestException as e:
        logger.info(f"[fetch_url_content] 请求失败: {url}, error: {e}")
        return None
    except Exception as e:
        logger.info(f"[fetch_url_content] 解析失败: {url}, error: {e}")
        return None


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
    doc = fetch_url_document(url, max_length=max_length)
    if not isinstance(doc, dict):
        return None
    content = doc.get("content")
    return str(content) if isinstance(content, str) and content.strip() else None
