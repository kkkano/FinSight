# -*- coding: utf-8 -*-
"""
DataValidator - 数据验证中间件
在工具返回数据后、传给 LLM 前执行验证
"""

from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field


@dataclass
class ValidationResult:
    """验证结果"""
    is_valid: bool
    confidence: float  # 0.0 - 1.0
    issues: List[str] = field(default_factory=list)      # 严重问题（导致无效）
    warnings: List[str] = field(default_factory=list)    # 警告（不影响有效性）
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'is_valid': self.is_valid,
            'confidence': self.confidence,
            'issues': self.issues,
            'warnings': self.warnings,
        }


class DataValidator:
    """
    数据验证器
    
    作为中间件在工具返回数据后执行，验证数据一致性和合理性
    """
    
    def validate(self, data_type: str, data: Any) -> ValidationResult:
        """
        验证数据
        
        Args:
            data_type: 数据类型（price, company_info, financials 等）
            data: 要验证的数据
            
        Returns:
            ValidationResult 验证结果
        """
        validators = {
            'price': self._validate_price,
            'company_info': self._validate_company_info,
            'financials': self._validate_financials,
            'news': self._validate_news,
        }
        
        validator = validators.get(data_type, self._validate_generic)
        return validator(data)
    
    def _validate_price(self, data: Any) -> ValidationResult:
        """验证股价数据"""
        issues = []
        warnings = []
        
        if not isinstance(data, dict):
            # 如果是字符串格式（当前工具返回格式），尝试解析
            if isinstance(data, str):
                if "Error" in data or "error" in data.lower():
                    return ValidationResult(
                        is_valid=False,
                        confidence=0.0,
                        issues=["数据获取失败: " + data[:100]]
                    )
                # 字符串格式的价格数据，基本验证
                if "$" in data:
                    return ValidationResult(
                        is_valid=True,
                        confidence=0.8,
                        warnings=["数据为字符串格式，建议转换为结构化数据"]
                    )
            
            return ValidationResult(
                is_valid=False,
                confidence=0.0,
                issues=["无效的数据格式"]
            )
        
        # 结构化数据验证
        price = data.get('price', 0)
        if price <= 0:
            issues.append(f"股价无效: {price}")
        elif price > 100000:
            warnings.append(f"股价异常高: ${price}，请核实")
        
        change_pct = data.get('change_percent', 0)
        if abs(change_pct) > 20:
            warnings.append(f"涨跌幅异常: {change_pct}%，可能是熔断或数据错误")
        
        return ValidationResult(
            is_valid=len(issues) == 0,
            confidence=1.0 if not issues and not warnings else 0.7,
            issues=issues,
            warnings=warnings
        )
    
    def _validate_company_info(self, data: Any) -> ValidationResult:
        """验证公司信息"""
        issues = []
        warnings = []
        
        if isinstance(data, str):
            if "Error" in data or "error" in data.lower():
                return ValidationResult(
                    is_valid=False,
                    confidence=0.0,
                    issues=["公司信息获取失败"]
                )
            # 有内容即视为有效
            if len(data) > 50:
                return ValidationResult(is_valid=True, confidence=0.8)
        
        if isinstance(data, dict):
            if not data.get('name'):
                issues.append("缺少公司名称")
            if not data.get('market_cap'):
                warnings.append("缺少市值数据")
        
        return ValidationResult(
            is_valid=len(issues) == 0,
            confidence=0.9 if not warnings else 0.7,
            issues=issues,
            warnings=warnings
        )
    
    def _validate_financials(self, data: Any) -> ValidationResult:
        """验证财务数据"""
        issues = []
        warnings = []
        
        if isinstance(data, str):
            if "Error" in data or "error" in data.lower():
                return ValidationResult(
                    is_valid=False,
                    confidence=0.0,
                    issues=["财务数据获取失败"]
                )
            return ValidationResult(is_valid=True, confidence=0.7)
        
        if isinstance(data, dict):
            # P/E 合理性检查
            pe = data.get('pe_ratio')
            if pe is not None:
                if pe < 0:
                    warnings.append(f"P/E 为负 ({pe})，公司可能亏损")
                elif pe > 200:
                    warnings.append(f"P/E 异常高 ({pe})，可能是成长股或数据异常")
            
            # 交叉验证：市值 ≈ 股价 × 股数
            market_cap = data.get('market_cap')
            shares = data.get('shares_outstanding')
            price = data.get('price')
            
            if all([market_cap, shares, price]):
                calculated_cap = price * shares
                if market_cap > 0:
                    diff = abs(market_cap - calculated_cap) / market_cap
                    if diff > 0.1:  # 10% 误差
                        issues.append(
                            f"市值数据不一致: 报告 {market_cap:,.0f}, 计算 {calculated_cap:,.0f}"
                        )
        
        return ValidationResult(
            is_valid=len(issues) == 0,
            confidence=0.9 if not warnings else 0.7,
            issues=issues,
            warnings=warnings
        )
    
    def _validate_news(self, data: Any) -> ValidationResult:
        """验证新闻数据"""
        if isinstance(data, str):
            if "Error" in data or "error" in data.lower():
                return ValidationResult(
                    is_valid=False,
                    confidence=0.0,
                    issues=["新闻获取失败"]
                )
            if len(data) > 20:
                return ValidationResult(is_valid=True, confidence=0.8)
        
        return ValidationResult(is_valid=True, confidence=0.6)
    
    def _validate_generic(self, data: Any) -> ValidationResult:
        """通用验证"""
        if data is None:
            return ValidationResult(
                is_valid=False,
                confidence=0.0,
                issues=["数据为空"]
            )
        
        if isinstance(data, str):
            if "Error" in data or "error" in data.lower():
                return ValidationResult(
                    is_valid=False,
                    confidence=0.0,
                    issues=["数据获取失败"]
                )
        
        return ValidationResult(is_valid=True, confidence=0.7)

