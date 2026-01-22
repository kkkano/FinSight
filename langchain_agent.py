"""Compatibility shim for legacy imports.

Prefer importing from backend.langchain_agent going forward.
"""

from backend.langchain_agent import LangChainFinancialAgent, create_financial_agent

__all__ = ["LangChainFinancialAgent", "create_financial_agent"]
