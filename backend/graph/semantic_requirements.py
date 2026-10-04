"""先抽取开放的用户要求，再由 compiler 校验与投影执行能力。"""
from __future__ import annotations

import json
import re
from copy import deepcopy
from typing import Any, Literal

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import AliasChoices, BaseModel, ConfigDict, Field

from backend.services.llm_response import completion_metadata, final_completion_text
from backend.services.llm_response import LLMCompletionError
from backend.services.llm_retry import LLMCallContext, ainvoke_configured_llm, classify_llm_error
from backend.services.llm_usage import LLMAttribution, reset_llm_attribution, set_llm_attribution
from backend.utils.env import env_int


class SemanticTimeScope(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["fiscal_quarter", "fiscal_year", "trading_sessions", "calendar_window", "latest_quote", "none"] = "none"
    selection: Literal["latest_complete", "latest", "explicit"] = "latest"
    count: int | None = None
    completed_only: bool = False
    source_text: str = ""
    direction: Literal["past", "future", "none"] = "none"
    unit: str | None = None
    as_of: str | None = None
    period_start: str | None = None
    period_end: str | None = None


class SemanticConstraint(BaseModel):
    model_config = ConfigDict(extra="forbid")
    constraint_type: Literal["exclude_dimension", "exclude_comparison", "source_policy", "scenario_separation", "other"]
    source_text: str
    dimension: str | None = None
    description: str = ""
    source_requirement: Literal["primary", "attributed", "traceable", "unspecified"] = "unspecified"
    subject_refs: list[str] = Field(default_factory=list, validation_alias=AliasChoices("subject_refs", "scope_refs"),
                                   description="约束应用的真实subject IDs，空列表为全局；不得将一个主体的排除项扩展到其他主体。")


class SemanticRequirement(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_text: str
    description: str
    kind: Literal["fact_attribute", "calculation", "explanation", "comparison", "event_window", "constraint", "input_dependency"]
    dimension: str = "unknown"
    metric: str = "unknown"
    metric_text: str = ""
    measurement: str = "other"
    price_role: str = "none"
    data_frequency: str = "unspecified"
    subject: str | None = None
    subject_refs: list[str] = Field(default_factory=list)
    time_scope: SemanticTimeScope = Field(default_factory=SemanticTimeScope)
    components: list[str] = Field(default_factory=list, description="仅列需要实际采集或计算的规范数值指标；币种、源时间和收益口径放attributes，定性传导对象独立为explanation要求。")
    attributes: list[str] = Field(default_factory=list)
    evidence_kinds: list[str] = Field(default_factory=list)
    requires_analysis: bool = False
    requires_explicit_binding: bool = True
    capability_status: Literal["supported", "unsupported", "input_missing"] = "supported"
    input_dependencies: list[str] = Field(default_factory=list)
    constraints: list[SemanticConstraint] = Field(default_factory=list)


class SemanticSubject(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    type: str = "company"
    label: str
    tickers: list[str] = Field(default_factory=list)


class SemanticRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    subjects: list[SemanticSubject]
    relation: Literal["single", "compare", "rank", "impact", "continuation", "none"] = "single"
    requirements: list[SemanticRequirement]
    constraints: list[SemanticConstraint] = Field(default_factory=list)


class RequiredInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    input_key: Literal["analysis_subject", "previous_report", "source_document", "document_url", "report_text", "position_cost_basis", "portfolio_positions", "comparison_target", "other"]
    source_text: str
    source_ref: str | None = None


class ExtractedRequirement(BaseModel):
    """模型只提供语义；能力、维度、证据和稳定 ID 全部由 compiler 决定。"""
    model_config = ConfigDict(extra="ignore")
    source_text: str
    description: str
    kind: Literal["fact_attribute", "calculation", "explanation", "comparison", "event_window", "constraint", "input_dependency"]
    metric: str = Field(description="开放指标名；quote表示当前报价、最近完整收盘价和窗口终点价格。金额/日期/币种/时间等属性附在对应指标，确实未知的指标保留unknown。")
    metric_text: str = ""
    measurement: Literal["price", "return", "drawdown", "volume", "cash_amount", "share_count", "date", "ratio", "qualitative", "other"] = Field(default="other", description="原始要求的测量对象，独立于工具能力；价格含即时报价、收盘价、窗口起终点。")
    price_role: Literal["current", "window_start", "window_end", "latest_completed_close", "none"] = Field(default="none", description="测量价格在原要求中的身份；窗口终点或最近收盘应使用quote，不能因不是即时报价标成unknown。")
    data_frequency: Literal["daily", "weekly", "monthly", "intraday", "unspecified"] = Field(default="unspecified", description="数据采样频率；日线daily不表示N交易日窗口，不将频率放进attributes或time_scope.count。")
    subject: str | None = None
    subject_refs: list[str] = Field(default_factory=list)
    time_scope: SemanticTimeScope = Field(default_factory=SemanticTimeScope)
    components: list[str] = Field(default_factory=list, description="需要实际取数的规范指标列表；例如现金覆盖的组成量或宏观指标，不包含定性因果对象、币种、时间或口径属性。")
    attributes: list[str] = Field(default_factory=list)
    requires_analysis: bool = False
    input_dependencies: list[RequiredInput] = Field(default_factory=list)
    constraints: list[SemanticConstraint] = Field(default_factory=list)


class ExtractedRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    subjects: list[SemanticSubject]
    relation: Literal["single", "compare", "rank", "impact", "continuation", "none"] = "single"
    requirements: list[ExtractedRequirement]
    constraints: list[SemanticConstraint] = Field(default_factory=list)


def requires_semantic_extraction(query: str, *, output_mode: str = "chat") -> bool:
    """只有明确的社交和单一即时报价可绕过开放要求抽取。"""
    text = str(query or "").strip()
    if output_mode == "investment_report":
        return True
    if re.fullmatch(r"(?:你好|您好|谢谢|謝謝|多谢|嗨|hello|hi|thanks|thank you)[！!。.?？\s]*", text, re.I):
        return False
    if re.fullmatch(r"(?:[A-Za-z0-9.^=\-]+|[\u4e00-\u9fff]{1,8})\s*(?:现在|当前|最新)?(?:股价|价格|报价)(?:是多少|多少|如何)?[？?。\s]*", text):
        return False
    if re.fullmatch(r"(?:what(?:'s| is)\s+)?(?:the\s+)?(?:current\s+)?(?:price|quote)(?:\s+(?:of|for))?\s+[A-Za-z0-9.^=\-]+[？?。\s]*", text, re.I):
        return False
    return True


_SYSTEM_PROMPT = """你负责提取用户原始请求，不负责回答或选择工具。返回符合 schema 的对象。
requirements 是所有原始要求的唯一事实源。逐项保存每个肯定要求、计算、解释、属性、时间窗口、输入依赖和明确约束；不要合并掉不同指标或不同财期，不得根据已有工具能力删减要求。
source_text 必须是当前用户原文中连续的非空片段。subject_refs 引用 subjects.id；subject 是确切 ticker 或 null。沿用解析主体和历史绑定，但比较上下文里的竞品不是新增主研究对象。
每个明确指标单独一项；components 仅保存该指标的必要子项。最新已完成季度与最新完整财年是不同时间范围；20交易日不是20自然日。时间限制必须逐项保留到 time_scope；calendar_window 的 count/unit/direction 保留原单位。
measurement 表示测量对象，price_role表示价格身份：quote统一涵盖当前报价、最近完整收盘价和窗口终点收盘价；这些是价格测量，不是未支持的新指标。终点收盘价可作为cumulative_return的end_close属性，也可单列quote/measurement=price/price_role=window_end。未知本体用measurement=other、metric=unknown，不得按能力目录删要求。
可识别的 metric 示例：quote,cumulative_return,max_drawdown,volume_breakout,operating_cash_flow,capital_expenditure,free_cash_flow,dividends_paid,repurchases_paid,capital_allocation_surplus,shares_outstanding,net_share_change,dividend_coverage,dividend_announcement,debt_burden,revenue,net_income,operating_income,earnings_date,macro_data；一般研究指标可用 business_model,competition,fundamental_quality,valuation_reasonableness,risk_level,news_catalysts,macro_impact,technical_quality,trend_quality,earnings_performance,earnings_impact,investment_attractiveness,holdings_ownership,external_impact；已有指定文档的摘要/问答用document_summary/document_question。
宏观数值指标规范为nonfarm_payroll_change（非农就业人数相邻月增量，不是就业存量）、unemployment、cpi、fed_rate、gdp_growth、treasury_10y、yield_spread。可以分别为metric，也可作为macro_data/macro_impact需要实际取数的components；单位、源时间、发布时刻放attributes。定性因果传导目标分成独立explanation要求并引用原文，不能作为数值components。
已实现技术指标用rsi14（rsi同义）、macd、support、resistance、support_resistance；日线使用data_frequency=daily，未指定N时time_scope.kind=none，指标采用各自既有定义窗口。不能把日线采样误写为无count的trading_sessions，也不能因这些指标不是报价而标unknown。
这些示例不是有限工具目录。未知要求必须保留 metric=unknown、metric_text=用户原词。不要输出dimension、evidence_kinds或capability_status，这些是代码的职责。
需要明确的公司、上一份报告、买入成本、持仓等输入时，input_dependencies 用结构对象，input_key须为schema枚举，source_text引用原文，source_ref仅指向输入里实际存在的引用，缺失则null；不能填随机字符或虚构已有报告。报告更新/检查旧结论的指标可用document_question并列出previous_report输入依赖；公司未绑定须同时保留analysis_subject依赖。
最新完整季度kind=fiscal_quarter，财年kind=fiscal_year；最新收盘报价kind=latest_quote、selection=latest_complete；已结束交易日窗口kind=trading_sessions，count为真实交易日数。latest/latest_complete不生成日期占位符，as_of、period_start/end没有明确ISO日期就null。
属性保留在对应指标attributes：currency,source_timestamp,market_session,end_close,price_basis,dividends_included,confirmation_status。收益是否计入分红、收益口径和终点收盘价是cumulative_return属性，不能另造unknown/methodology要求。若单列quote最新终点收盘，使用latest_quote/latest_complete而不是1交易日收益窗口。公告派息与实际季度现金支付须分开。
属性是规范identifier，不添加冒号、反引号或timeframe:daily等键值表达式。定性质量/估值/风险/因果判断始终需要解释；准确数值和技术指标可按标准定义确定性展示。
纯数值、按标准定义计算收益或回撤、列出币种时间及计算口径属于fact_attribute/calculation，不需要研究解释。只有解释因果、判断投资意义、比较优劣等使用explanation/comparison；说明是否计入分红用attributes=dividends_included和price_basis，不要丢掉属性。
解释、判断、因果、比较设置 requires_analysis=true。约束独立保存 constraint 项并在 constraints 标记类型（exclude_dimension/exclude_comparison/source_policy/scenario_separation/other）。不查新闻等否定要求不是肯定新闻要求。
source_policy的source_requirement：仅公司/官方原始声明用primary，媒体归因材料用attributed，可追溯链接用traceable，未限制用unspecified；不能把媒体转述当成用户要求的官方原始声明。
约束subject_refs引用真实subjects.id；空为全局，非空只应用这些主体。独立constraint要求继承约束主体范围，不得把一个主体的排除维度应用到其他主体。
kind=constraint 时不产生数据采集义务。业务质量/估值判断应保留所需口径，而不是仅保存一个泛化报告维度。不得填充默认研究维度替代明确要求。
"""


async def extract_semantic_requirements(state: dict[str, Any], seed: dict[str, Any]) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    context = LLMCallContext.create(stage="request_requirements", agent="request_compiler", layer="understanding")
    attribution = set_llm_attribution(LLMAttribution(agent="request_compiler", layer="understanding"))
    ui = state.get("ui_context") if isinstance(state.get("ui_context"), dict) else {}
    history = ui.get("session_history") or state.get("messages") or []
    history_rows = []
    for item in history[-6:]:
        if isinstance(item, dict):
            history_rows.append({"role": item.get("role"), "content": str(item.get("content") or "")[:4000]})
        else:
            history_rows.append({"role": getattr(item, "type", ""), "content": str(getattr(item, "content", ""))[:4000]})
    payload = {"query": str(state.get("query") or ""), "output_mode": state.get("output_mode", "chat"),
               "resolved_subject": seed.get("subject"), "bound_tasks": [
                   {key: task.get(key) for key in ("subject_type", "subject_label", "tickers", "request_text", "selection_ids", "selection_types")}
                   for task in seed.get("tasks", [])], "recent_history": history_rows,
               "available_input_refs": {"memory_context": state.get("memory_context") or {}, "selections": ui.get("selections") or []}}
    diagnostics: dict[str, Any] = {"status": "unconfirmed", "source": "selected_model_semantic_extraction"}
    try:
        messages = [SystemMessage(content=_SYSTEM_PROMPT), HumanMessage(content=json.dumps(payload, ensure_ascii=False))]
        for attempt in range(2):
            response = await ainvoke_configured_llm(
                messages, context=context, temperature=0.0, acquire_token=True,
                max_tokens=env_int("LANGGRAPH_REQUEST_MAX_TOKENS", 65536),
                request_timeout=env_int("LANGGRAPH_REQUEST_TIMEOUT_SEC", 1200),
                acquire_timeout_seconds=env_int("LANGGRAPH_REQUEST_ACQUIRE_TIMEOUT_SEC", 120),
                client_transform=lambda client: client.with_structured_output(ExtractedRequest, method="json_schema", include_raw=True),
            )
            diagnostics.update(completion_metadata(response))
            try:
                if isinstance(response, dict) and "raw" in response:
                    if completion_metadata(response)["finish_reason"].lower() in {"length", "max_tokens", "max_output_tokens"}:
                        raise LLMCompletionError("llm_output_truncated")
                    parsed = response.get("parsed")
                    if parsed is None:
                        parsed = json.loads(final_completion_text(response))
                    elif not getattr(response["raw"], "tool_calls", None):
                        final_completion_text(response)
                elif isinstance(response, (dict, BaseModel)):
                    parsed = response
                else:
                    parsed = json.loads(final_completion_text(response).strip().removeprefix("```json").removesuffix("```").strip())
                if isinstance(parsed, BaseModel):
                    parsed = parsed.model_dump()
                if isinstance(parsed, dict):
                    diagnostics["raw_semantic"] = {key: deepcopy(parsed[key]) for key in ("subjects", "relation", "requirements", "constraints") if key in parsed}
                    diagnostics.setdefault("semantic_attempts", []).append(deepcopy(diagnostics["raw_semantic"]))
                request = ExtractedRequest.model_validate(parsed)
                raw = request.model_dump()
                diagnostics["raw_semantic"] = raw
                if not request.requirements:
                    raise ValueError("request_requirements_empty")
                if any(row.kind in {"fact_attribute", "calculation"} and row.metric == "unknown"
                       and row.time_scope.kind == "latest_quote" and row.measurement != "price"
                       and not row.input_dependencies for row in request.requirements):
                    raise ValueError("request_quote_measurement_inconsistent")
                from backend.graph.request_compiler import compile_semantic_contract
                compile_semantic_contract({**deepcopy(seed), "query": payload["query"]}, raw, {}, input_context=state)
                diagnostics["status"] = "confirmed"
                diagnostics["schema_correction_attempts"] = attempt
                return raw, diagnostics
            except LLMCompletionError:
                raise
            except (ValueError, TypeError, KeyError) as exc:
                diagnostics["validation_code"] = str(exc) if str(exc).startswith("request_") else "request_requirements_schema_invalid"
                diagnostics.setdefault("validation_attempts", []).append(diagnostics["validation_code"])
                if attempt or context.budget.remaining <= 0:
                    raise
                messages.append(HumanMessage(content="上一对象未通过结构校验：" + diagnostics["validation_code"] + "。按原始请求完整重写一次，修正主体引用、输入依赖和时间字段；不要删掉原始要求。"))
    except Exception as exc:
        diagnostics.update(error_code="request_contract_unconfirmed", cause_code=classify_llm_error(exc).code,
                           exception_type=type(exc).__name__)
        return None, diagnostics
    finally:
        diagnostics.update(provider_attempts=context.budget.provider_attempts_used,
                           call_parameters=dict(context.call_parameters), failure_diagnostics=list(context.failure_diagnostics))
        reset_llm_attribution(attribution)
