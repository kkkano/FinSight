"""财务输入的中性叶子合同；不导入旧图或解析用户意图。"""
from __future__ import annotations


FINANCIAL_DEFINITIONS = {
    "revenue": "目标报表口径下的营业收入，不是现金收款",
    "net_income": "目标报表口径下的净利润，不替换成归母净利润",
    "operating_income": "营业利润",
    "operating_cash_flow": "经营活动产生的现金流量净额",
    "capital_expenditure": "购建固定资产、无形资产和其他长期资产支付的现金，正数现金支出",
    "dividends_paid": "实际支付的股利现金，不是宣告派息或与利息合并的现金项目",
    "repurchases_paid": "实际支付的股份回购现金，不是授权额度",
}
FINANCIAL_INPUTS = {
    "free_cash_flow": ("operating_cash_flow", "capital_expenditure"),
    "capital_allocation_surplus": ("operating_cash_flow", "capital_expenditure", "dividends_paid", "repurchases_paid"),
    "dividend_coverage": ("operating_cash_flow", "capital_expenditure", "dividends_paid"),
}


def financial_metric_inputs(metrics):
    return tuple(dict.fromkeys(part for metric in metrics for part in FINANCIAL_INPUTS.get(metric, (metric,))))


__all__ = ["FINANCIAL_DEFINITIONS", "FINANCIAL_INPUTS", "financial_metric_inputs"]
