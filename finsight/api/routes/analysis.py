"""
分析路由 - 核心业务 API

提供股票分析、资产对比、市场情绪等功能的 API 端点。
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from typing import Optional
import uuid

from finsight.api.schemas import (
    AnalyzeRequest,
    CompareRequest,
    StockQueryRequest,
    ClarifyResponse,
    AnalysisResponse,
    ErrorResponse,
    ResponseModeEnum,
    ReportFormatEnum,
    analysis_result_to_response,
)
from finsight.api.dependencies import (
    get_orchestrator,
    get_report_writer,
)
from finsight.domain.models import (
    AnalysisRequest as DomainRequest,
    ResponseMode,
    Intent,
)
from finsight.orchestrator import Orchestrator
from finsight.presentation import ReportWriter, ReportFormat


router = APIRouter(prefix="/api/v1", tags=["Analysis"])


@router.post(
    "/analyze",
    response_model=AnalysisResponse,
    responses={
        400: {"model": ErrorResponse, "description": "请求参数错误"},
        500: {"model": ErrorResponse, "description": "服务器内部错误"},
    },
    summary="智能分析",
    description="""
    智能分析接口 - 自动识别用户意图并返回相应分析结果。

    支持的查询类型：
    - 股票分析："分析苹果股票"、"AAPL 怎么样"
    - 价格查询："特斯拉现在多少钱"、"TSLA price"
    - 新闻查询："英伟达最新新闻"
    - 市场情绪："市场情绪如何"、"fear and greed"
    - 资产对比："比较 AAPL 和 MSFT"
    - 经济日历："近期有什么重要经济数据"
    """
)
async def analyze(
    request: AnalyzeRequest,
    orchestrator: Orchestrator = Depends(get_orchestrator),
    report_writer: ReportWriter = Depends(get_report_writer),
) -> AnalysisResponse:
    """执行智能分析"""
    try:
        # 构建领域请求
        domain_request = DomainRequest(
            query=request.query,
            mode=ResponseMode(request.mode.value),
            request_id=str(uuid.uuid4()),
            ticker=request.ticker,
        )

        # 执行分析
        result = orchestrator.process(domain_request)

        # 如果需要报告但没有生成，使用 ReportWriter 生成
        if not result.report and result.success:
            result.report = report_writer.generate(
                result,
                format=ReportFormat(request.format.value)
            )

        # 转换为 API 响应
        return analysis_result_to_response(result, request.format.value)

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"分析过程中发生错误: {str(e)}"
        )


@router.post(
    "/clarify",
    response_model=AnalysisResponse,
    summary="提交追问回答",
    description="当系统返回需要追问时，使用此接口提交用户的回答"
)
async def clarify(
    response: ClarifyResponse,
    orchestrator: Orchestrator = Depends(get_orchestrator),
) -> AnalysisResponse:
    """处理用户对追问的回答"""
    try:
        # TODO: 实现追问回答处理逻辑
        # 目前简单地将用户回答作为新查询处理
        domain_request = DomainRequest(
            query=response.answer,
            mode=ResponseMode.DEEP,
            request_id=response.request_id,
        )

        result = orchestrator.process(domain_request)
        return analysis_result_to_response(result)

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"处理回答时发生错误: {str(e)}"
        )


@router.get(
    "/stock/{ticker}/price",
    response_model=AnalysisResponse,
    summary="获取股票价格",
    description="获取指定股票的实时价格信息"
)
async def get_stock_price(
    ticker: str,
    mode: ResponseModeEnum = Query(default=ResponseModeEnum.SUMMARY),
    orchestrator: Orchestrator = Depends(get_orchestrator),
) -> AnalysisResponse:
    """获取股票价格"""
    try:
        domain_request = DomainRequest(
            query=f"{ticker} stock price",
            mode=ResponseMode(mode.value),
            request_id=str(uuid.uuid4()),
            ticker=ticker.upper(),
            intent_hint=Intent.STOCK_PRICE,
        )

        result = orchestrator.process(domain_request)
        return analysis_result_to_response(result)

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"获取价格失败: {str(e)}"
        )


@router.get(
    "/stock/{ticker}/news",
    response_model=AnalysisResponse,
    summary="获取股票新闻",
    description="获取指定股票的最新新闻"
)
async def get_stock_news(
    ticker: str,
    limit: int = Query(default=10, ge=1, le=50),
    mode: ResponseModeEnum = Query(default=ResponseModeEnum.SUMMARY),
    orchestrator: Orchestrator = Depends(get_orchestrator),
) -> AnalysisResponse:
    """获取股票新闻"""
    try:
        domain_request = DomainRequest(
            query=f"{ticker} news",
            mode=ResponseMode(mode.value),
            request_id=str(uuid.uuid4()),
            ticker=ticker.upper(),
            intent_hint=Intent.STOCK_NEWS,
        )

        result = orchestrator.process(domain_request)
        return analysis_result_to_response(result)

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"获取新闻失败: {str(e)}"
        )


@router.get(
    "/stock/{ticker}/analysis",
    response_model=AnalysisResponse,
    summary="深度股票分析",
    description="获取指定股票的完整投资分析报告"
)
async def get_stock_analysis(
    ticker: str,
    mode: ResponseModeEnum = Query(default=ResponseModeEnum.DEEP),
    orchestrator: Orchestrator = Depends(get_orchestrator),
    report_writer: ReportWriter = Depends(get_report_writer),
) -> AnalysisResponse:
    """深度股票分析"""
    try:
        domain_request = DomainRequest(
            query=f"分析 {ticker} 股票",
            mode=ResponseMode(mode.value),
            request_id=str(uuid.uuid4()),
            ticker=ticker.upper(),
            intent_hint=Intent.STOCK_ANALYSIS,
        )

        result = orchestrator.process(domain_request)

        # 确保生成报告
        if not result.report and result.success:
            result.report = report_writer.generate(result, ReportFormat.MARKDOWN)

        return analysis_result_to_response(result)

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"分析失败: {str(e)}"
        )


@router.post(
    "/compare",
    response_model=AnalysisResponse,
    summary="资产对比",
    description="比较多个资产的表现"
)
async def compare_assets(
    request: CompareRequest,
    orchestrator: Orchestrator = Depends(get_orchestrator),
) -> AnalysisResponse:
    """资产对比"""
    try:
        tickers_str = " vs ".join(request.tickers)
        domain_request = DomainRequest(
            query=f"比较 {tickers_str}",
            mode=ResponseMode(request.mode.value),
            request_id=str(uuid.uuid4()),
            tickers=request.tickers,
            intent_hint=Intent.COMPARE_ASSETS,
        )

        result = orchestrator.process(domain_request)
        return analysis_result_to_response(result)

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"对比失败: {str(e)}"
        )


@router.get(
    "/market/sentiment",
    response_model=AnalysisResponse,
    summary="市场情绪",
    description="获取当前市场情绪指标（CNN Fear & Greed Index）"
)
async def get_market_sentiment(
    mode: ResponseModeEnum = Query(default=ResponseModeEnum.SUMMARY),
    orchestrator: Orchestrator = Depends(get_orchestrator),
) -> AnalysisResponse:
    """获取市场情绪"""
    try:
        domain_request = DomainRequest(
            query="market sentiment fear greed",
            mode=ResponseMode(mode.value),
            request_id=str(uuid.uuid4()),
            intent_hint=Intent.MARKET_SENTIMENT,
        )

        result = orchestrator.process(domain_request)
        return analysis_result_to_response(result)

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"获取市场情绪失败: {str(e)}"
        )


@router.get(
    "/market/events",
    response_model=AnalysisResponse,
    summary="经济日历",
    description="获取近期重要经济事件日历"
)
async def get_economic_events(
    days_ahead: int = Query(default=30, ge=1, le=90),
    mode: ResponseModeEnum = Query(default=ResponseModeEnum.SUMMARY),
    orchestrator: Orchestrator = Depends(get_orchestrator),
) -> AnalysisResponse:
    """获取经济日历"""
    try:
        domain_request = DomainRequest(
            query="economic calendar",
            mode=ResponseMode(mode.value),
            request_id=str(uuid.uuid4()),
            intent_hint=Intent.MACRO_EVENTS,
        )

        result = orchestrator.process(domain_request)
        return analysis_result_to_response(result)

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"获取经济日历失败: {str(e)}"
        )
