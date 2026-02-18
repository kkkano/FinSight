import logging
import os
import re
import time
from typing import List

from .env import EXA_API_KEY, TAVILY_API_KEY
from .utils import _normalize_published_date

logger = logging.getLogger(__name__)

_SEARCH_QUOTA_COOLDOWN_SECONDS = int(os.getenv("SEARCH_QUOTA_COOLDOWN_SECONDS", "1800"))
_EXA_QUOTA_BLOCKED_UNTIL = 0.0
_TAVILY_QUOTA_BLOCKED_UNTIL = 0.0


def _is_quota_error(message: str) -> bool:
    text = (message or "").lower()
    return any(
        key in text
        for key in (
            "no_more_credits",
            "exceeded your credits limit",
            "usage limit",
            "forbiddenerror",
            "status code 402",
        )
    )


def _is_provider_blocked(blocked_until: float) -> bool:
    return blocked_until > time.time()

# Search dependencies (optional)
try:
    from ddgs import DDGS
    DDGS_AVAILABLE = True
except ImportError:
    try:
        from duckduckgo_search import DDGS
        DDGS_AVAILABLE = True
        logger.info("[Warning] Prefer 'pip install ddgs' over 'duckduckgo_search'")
    except ImportError:
        DDGS = None
        DDGS_AVAILABLE = False
        logger.info("[Warning] DuckDuckGo search unavailable: install ddgs or duckduckgo_search")

try:
    from tavily import TavilyClient
    TAVILY_AVAILABLE = True
except ImportError:
    TavilyClient = None
    TAVILY_AVAILABLE = False
    logger.info("[Warning] Tavily search unavailable: install tavily-python")

try:
    from exa_py import Exa
    EXA_AVAILABLE = True
except ImportError:
    Exa = None
    EXA_AVAILABLE = False
    logger.info("[Warning] Exa search unavailable: install exa-py")

try:
    import wikipedia
    wikipedia.set_lang("zh")
    WIKIPEDIA_AVAILABLE = True
except ImportError:
    wikipedia = None
    WIKIPEDIA_AVAILABLE = False
    logger.info("[Warning] Wikipedia search unavailable: install wikipedia")

def search(query: str) -> str:
    """
    使用多数据源策略执行网页搜索并合并结果。
    策略A：串行搜索 + 智能检测
    优先级：Exa > Tavily > Wikipedia > DuckDuckGo

    Args:
        query: 搜索查询字符串

    Returns:
        格式化的合并搜索结果
    """
    global _EXA_QUOTA_BLOCKED_UNTIL, _TAVILY_QUOTA_BLOCKED_UNTIL

    all_results = []
    sources_used = []

    # 0. 尝试 Exa Search (语义搜索，优先级最高)
    if EXA_API_KEY and EXA_AVAILABLE and not _is_provider_blocked(_EXA_QUOTA_BLOCKED_UNTIL):
        try:
            exa_result = _search_with_exa(query)
            if exa_result and len(exa_result) > 200:  # 确保结果足够长
                logger.info(f"[Search] ✅ Exa 搜索成功: {query[:50]}...")
                # 检查信息充足性 (简单启发式)
                # 如果是深度查询，且 Exa 返回了丰富内容，直接返回
                if len(exa_result) > 1000:
                    logger.info("[Search] 🚀 Exa 结果充足，跳过其他搜索源")
                    return f"""🔍 综合搜索结果 (来自 Exa):
{'='*60}

{exa_result}

{'='*60}
"""

                all_results.append({
                    'source': 'Exa',
                    'content': exa_result
                })
                sources_used.append('Exa')
        except Exception as e:
            error_msg = str(e) if e else "未知错误"
            if _is_quota_error(error_msg):
                _EXA_QUOTA_BLOCKED_UNTIL = time.time() + max(60, _SEARCH_QUOTA_COOLDOWN_SECONDS)
                logger.warning(
                    "[Search] Exa quota exhausted, disable for %ss",
                    max(60, _SEARCH_QUOTA_COOLDOWN_SECONDS),
                )
            logger.info(f"[Search] Exa 搜索失败: {error_msg}")

    # 1.尝试 Tavily Search (AI搜索)
    # 如果 Exa 失败或结果不足，尝试 Tavily
    if TAVILY_API_KEY and TAVILY_AVAILABLE and not _is_provider_blocked(_TAVILY_QUOTA_BLOCKED_UNTIL):
        try:
            tavily_result = _search_with_tavily(query)
            if tavily_result and len(tavily_result) > 50:
                all_results.append({
                    'source': 'Tavily',
                    'content': tavily_result
                })
                sources_used.append('Tavily')
                logger.info(f"[Search] ✅ Tavily 搜索成功: {query[:50]}...")

                # 如果已有两个高质量源，停止搜索
                if len(sources_used) >= 2:
                    logger.info("[Search] 🚀 已有两个高质量源，跳过后续搜索")
                    return _merge_search_results(all_results, query)

        except Exception as e:
            error_msg = str(e) if e else "未知错误"
            if _is_quota_error(error_msg):
                _TAVILY_QUOTA_BLOCKED_UNTIL = time.time() + max(60, _SEARCH_QUOTA_COOLDOWN_SECONDS)
                logger.warning(
                    "[Search] Tavily quota exhausted, disable for %ss",
                    max(60, _SEARCH_QUOTA_COOLDOWN_SECONDS),
                )
            # 忽略 Tavily 错误，继续尝试下一个源
            logger.info(f"[Search] Tavily 搜索失败: {error_msg}")

    # 2. 尝试维基百科（仅用于非金融查询）
    query_lower = query.lower()
    has_ticker = bool(re.search(r"\$?[A-Z]{1,5}(?:\.[A-Z]{1,2})?\b", query))
    is_financial_query = has_ticker or any(kw in query_lower for kw in [
        'stock', 'price', 'market', 'trading', 'aapl', 'msft', 'googl', 'tsla', 'nvda',
        'nasdaq', 's&p', 'dow', 'sentiment', 'news', 'headline', 'earnings', 'revenue',
        'risk', 'trend', 'analysis', 'investment', 'portfolio', '^', '$',
        # Chinese finance/news keywords
        '股票', '股价', '股市', '行情', '财报', '业绩', '营收', '利润', '市值', '投资', '基金',
        'etf', '债券', '汇率', '期货', '期权', '指数', '宏观', '经济', '通胀', '利率', '美联储',
        '央行', '新闻', '资讯', '消息', '头条', '快讯', '公告', '财讯'
    ])
    if WIKIPEDIA_AVAILABLE and not is_financial_query:
        try:
            wiki_result = _search_with_wikipedia(query)
            if wiki_result and len(wiki_result) > 100:
                all_results.append({
                    'source': 'Wikipedia',
                    'content': wiki_result
                })
                sources_used.append('Wikipedia')
                logger.info(f"[Search] ✅ 维基百科获取信息成功: {query[:50]}...")
        except Exception as e:
            logger.info(f"[Search] 维基百科搜索失败: {e}")

    # 3. 尝试 DuckDuckGo (最后兜底)
    # 如果之前所有尝试都失败，或者结果太少
    if (not all_results) and DDGS_AVAILABLE and DDGS is not None:
        try:
            ddgs_result = _search_with_duckduckgo(query)
            if ddgs_result and len(ddgs_result) > 50:
                all_results.append({
                    'source': 'DuckDuckGo',
                    'content': ddgs_result
                })
                sources_used.append('DuckDuckGo')
                logger.info(f"[Search] ✅ DuckDuckGo 搜索成功: {query[:50]}...")
        except Exception as e:
            logger.info(f"[Search] DuckDuckGo 搜索失败: {e}")

    # 4. 合并所有结果
    if not all_results:
        return "Search error: 所有搜索源均失败，无法获取搜索结果。"

    # 合并结果
    combined_result = _merge_search_results(all_results, query)

    logger.info(f"[Search] ✅ 最终使用 {len(sources_used)} 个搜索源: {', '.join(sources_used)}")
    return combined_result



def _search_with_duckduckgo(query: str) -> str:
    """使用 DuckDuckGo 搜索"""
    if not DDGS_AVAILABLE or DDGS is None:
        raise Exception("DuckDuckGo 不可用")
    
    for attempt in range(3):  # 增加重试次数
        try:
            ddgs = DDGS()
            
            try:
                results = list(ddgs.text(query, max_results=10, safesearch='moderate'))
            except TypeError:
                results = list(ddgs.text(query, max_results=10))
            
            if not results:
                if attempt < 2:
                    time.sleep(2)
                    continue
                return None
            
            # 验证结果相关性
            query_lower = query.lower()
            relevant_results = []
            for res in results:
                title = res.get('title', '')
                body = res.get('body', '')
                title_lower = title.lower()
                body_lower = body.lower()
                
                query_words = [w for w in query_lower.split() if len(w) > 2 and w not in ['the', 'and', 'or', 'for', 'with', 'from']]
                is_relevant = any(word in title_lower or word in body_lower for word in query_words) if query_words else True
                
                if is_relevant or len(relevant_results) < 3:
                    relevant_results.append(res)
            
            if not relevant_results:
                if attempt < 2:
                    time.sleep(2)
                    continue
                relevant_results = results[:3]
            
            formatted = []
            for i, res in enumerate(relevant_results[:10], 1):
                title = res.get('title', 'No title')
                body = res.get('body', 'No summary')
                href = res.get('href', 'No link')
                
                title = title.encode('utf-8', 'ignore').decode('utf-8').strip()
                body = body.encode('utf-8', 'ignore').decode('utf-8').strip()
                
                if not title or not body:
                    continue
                    
                formatted.append(f"{i}. {title}\n   {body[:200]}...\n   {href}")
            
            if formatted:
                return "Search Results (DuckDuckGo):\n" + "\n\n".join(formatted)
            else:
                return None
                
        except Exception as e:
            if attempt < 2:
                time.sleep(2)
            else:
                raise e
    
    return None



def _merge_search_results(results: list, query: str) -> str:
    """
    合并多个搜索源的结果
    
    Args:
        results: 搜索结果列表，每个元素包含 'source' 和 'content'
        query: 原始查询
        
    Returns:
        合并后的搜索结果文本
    """
    if not results:
        return "No search results found."
    
    # 如果只有一个结果，直接返回
    if len(results) == 1:
        return results[0]['content']
    
    # 合并多个结果
    merged_parts = []
    merged_parts.append(f"🔍 综合搜索结果 (来自 {len(results)} 个数据源):\n")
    merged_parts.append("=" * 60 + "\n\n")
    
    # 按优先级排序：Exa > Wikipedia > Tavily > DuckDuckGo
    source_priority = {'Exa': 0, 'Wikipedia': 1, 'Tavily': 2, 'DuckDuckGo': 3}
    results_sorted = sorted(results, key=lambda x: source_priority.get(x['source'], 99))
    
    for i, result in enumerate(results_sorted, 1):
        source = result['source']
        content = result['content']
        
        merged_parts.append(f"【数据源 {i}: {source}】\n")
        merged_parts.append("-" * 60 + "\n")
        
        # 提取主要内容（去除标题和格式）
        if source == 'Wikipedia':
            # 维基百科结果已经格式化好了
            merged_parts.append(content)
        elif source == 'Tavily':
            # Tavily 结果也格式化好了
            merged_parts.append(content)
        else:
            # DuckDuckGo 结果
            merged_parts.append(content)
        
        merged_parts.append("\n\n")
    
    merged_parts.append("=" * 60 + "\n")
    merged_parts.append(f"💡 提示: 以上结果来自多个搜索源，请综合参考以获得最准确的信息。\n")
    
    return "".join(merged_parts)



def _search_with_wikipedia(query: str) -> str:
    """
    使用维基百科搜索（免费，不需要API key）
    
    优先使用维基百科，因为：
    - 内容准确、权威
    - 结构化信息
    - 免费，无限制
    - 特别适合查询指数成分股、公司信息等
    """
    if not WIKIPEDIA_AVAILABLE or wikipedia is None:
        raise Exception("维基百科不可用（未安装 wikipedia）")
    
    try:
        # 尝试搜索页面（增加搜索结果数量）
        search_results = wikipedia.search(query, results=5)
        
        if not search_results:
            return None
        
        # 尝试多个搜索结果，找到最相关的
        best_result = None
        for page_title in search_results:
            try:
                page = wikipedia.page(page_title, auto_suggest=False)
                
                # 获取页面摘要和主要内容
                summary = page.summary
                content = page.content[:5000]  # 增加内容长度
                
                # 检查内容是否相关（包含查询关键词）
                query_lower = query.lower()
                content_lower = (summary + content).lower()
                
                # 如果内容包含查询关键词，认为是相关结果
                if any(keyword in content_lower for keyword in query_lower.split() if len(keyword) > 2):
                    best_result = {
                        'title': page_title,
                        'summary': summary,
                        'content': content,
                        'url': page.url
                    }
                    break
                    
            except wikipedia.exceptions.DisambiguationError as e:
                # 如果有歧义，尝试使用第一个选项
                if e.options:
                    try:
                        page = wikipedia.page(e.options[0], auto_suggest=False)
                        summary = page.summary
                        content = page.content[:5000]
                        best_result = {
                            'title': e.options[0],
                            'summary': summary,
                            'content': content,
                            'url': page.url
                        }
                        break
                    except:
                        continue
                        
            except wikipedia.exceptions.PageError:
                continue
            except Exception as e:
                logger.info(f"[Search] 维基百科获取页面 {page_title} 失败: {e}")
                continue
        
        # 如果没找到相关结果，使用第一个搜索结果
        if not best_result and search_results:
            try:
                page = wikipedia.page(search_results[0], auto_suggest=False)
                best_result = {
                    'title': search_results[0],
                    'summary': page.summary,
                    'content': page.content[:5000],
                    'url': page.url
                }
            except:
                return None
        
        if best_result:
            # 格式化结果
            result = f"""Wikipedia Results for "{best_result['title']}":

Summary:
{best_result['summary']}

Detailed Information:
{best_result['content']}

URL: {best_result['url']}"""
            return result
        
        return None
            
    except Exception as e:
        logger.info(f"[Search] 维基百科搜索出错: {e}")
        return None



def _search_with_tavily(query: str) -> str:
    """
    使用 Tavily Search API 进行AI搜索

    Tavily 是一个专门为AI应用设计的搜索API，提供：
    - 更准确的搜索结果
    - 结构化的数据格式
    - 更好的上下文理解
    """
    if not TAVILY_API_KEY:
        raise Exception("Tavily API key not configured")

    if not TAVILY_AVAILABLE or TavilyClient is None:
        raise Exception("Tavily 客户端不可用（未安装 tavily-python）")

    try:
        client = TavilyClient(api_key=TAVILY_API_KEY)

        # 执行搜索
        response = client.search(
            query=query,
            search_depth="advanced",  # basic 或 advanced
            max_results=10,
            include_answer=True,  # 包含AI生成的答案摘要
            include_raw_content=False,  # 不包含原始内容（节省token）
        )

        # 格式化结果
        formatted = []

        # 如果有AI生成的答案，优先显示
        if response.get('answer'):
            formatted.append(f"📊 AI摘要:\n{response['answer']}\n")

        # 显示搜索结果
        results = response.get('results', [])
        if results:
            formatted.append("搜索结果:")
            for i, res in enumerate(results, 1):
                title = res.get('title', 'No title')
                content = res.get('content', 'No content')
                url = res.get('url', 'No link')
                score = res.get('score', 0)

                formatted.append(
                    f"{i}. {title} (相关性: {score:.2f})\n"
                    f"   {content[:200]}...\n"
                    f"   {url}"
                )
        else:
            formatted.append("未找到相关搜索结果。")

        return "\n\n".join(formatted)

    except Exception as e:
        error_msg = str(e) if e else "未知错误"
        error_type = type(e).__name__
        logger.info(f"[Search] Tavily API 错误 ({error_type}): {error_msg}")

        # 如果是 API key 相关错误，给出更明确的提示
        if "api" in error_msg.lower() or "key" in error_msg.lower() or "auth" in error_msg.lower():
            logger.info(f"[Search] 提示: 请检查 TAVILY_API_KEY 是否正确配置")

        raise Exception(f"Tavily API 错误: {error_msg}")



def _search_with_exa(query: str) -> str:
    """
    使用 Exa Search API 进行语义搜索

    Exa 是一个专门为AI应用设计的语义搜索API，提供：
    - 神经网络驱动的语义搜索
    - 高质量的内容提取
    - 更好的上下文理解
    """
    if not EXA_API_KEY:
        raise Exception("Exa API key not configured")

    if not EXA_AVAILABLE or Exa is None:
        raise Exception("Exa 客户端不可用（未安装 exa-py）")

    try:
        exa = Exa(api_key=EXA_API_KEY)

        # 执行搜索
        response = exa.search_and_contents(
            query=query,
            type="neural",  # neural 或 keyword
            num_results=10,
            text=True,  # 包含文本内容
            highlights=True,  # 包含高亮片段
        )

        # 格式化结果
        formatted = []
        formatted.append("Search Results (Exa):")

        if response.results:
            for i, res in enumerate(response.results, 1):
                title = res.title or 'No title'
                url = res.url or 'No link'

                # 获取高亮或文本内容
                content = ""
                if hasattr(res, 'highlights') and res.highlights:
                    content = " ".join(res.highlights[:2])
                elif hasattr(res, 'text') and res.text:
                    content = res.text[:300]

                published = (
                    getattr(res, "published_date", None)
                    or getattr(res, "published_at", None)
                    or getattr(res, "date", None)
                    or getattr(res, "created_at", None)
                )
                date_str = _normalize_published_date(published)
                if date_str:
                    content = f"{date_str} {content}".strip()

                formatted.append(
                    f"{i}. {title}\n"
                    f"   {content}...\n"
                    f"   {url}"
                )

            return "\n\n".join(formatted)
        else:
            return None

    except Exception as e:
        raise Exception(f"Exa search failed: {str(e)}")

# ============================================
# 股价获取 - 多数据源策略
# ============================================
