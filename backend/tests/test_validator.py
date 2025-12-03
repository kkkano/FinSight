# -*- coding: utf-8 -*-
"""
Step 1.4 测试 - DataValidator 单元测试
验证数据验证中间件的核心功能
"""

import sys
import os

# 添加项目根目录到路径
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PROJECT_ROOT)

from backend.orchestration import DataValidator, ValidationResult


def test_validator_init():
    """测试验证器初始化"""
    validator = DataValidator()
    assert validator is not None
    print("✅ 验证器初始化测试通过")
    return True


def test_validation_result_structure():
    """测试 ValidationResult 结构"""
    result = ValidationResult(
        is_valid=True,
        confidence=0.9,
        issues=["issue1"],
        warnings=["warning1"]
    )
    
    assert result.is_valid == True
    assert result.confidence == 0.9
    assert len(result.issues) == 1
    assert len(result.warnings) == 1
    
    # 测试 to_dict
    d = result.to_dict()
    assert 'is_valid' in d
    assert 'confidence' in d
    
    print("✅ ValidationResult 结构测试通过")
    return True


def test_price_validation_valid():
    """测试有效的价格数据验证"""
    validator = DataValidator()
    
    # 测试字符串格式的有效价格
    result = validator.validate('price', "AAPL Current Price: $150.00 | Change: $2.50 (+1.69%)")
    
    assert result.is_valid == True
    assert result.confidence > 0.5
    
    print("✅ 有效价格数据验证测试通过")
    return True


def test_price_validation_error():
    """测试错误的价格数据验证"""
    validator = DataValidator()
    
    # 测试包含错误的价格数据
    result = validator.validate('price', "Error: Too Many Requests. Rate limited.")
    
    assert result.is_valid == False
    assert len(result.issues) > 0
    
    print("✅ 错误价格数据验证测试通过")
    return True


def test_price_validation_dict():
    """测试字典格式的价格数据验证"""
    validator = DataValidator()
    
    # 有效数据
    valid_data = {'price': 150.0, 'change_percent': 1.5}
    result = validator.validate('price', valid_data)
    assert result.is_valid == True
    
    # 无效数据（负价格）
    invalid_data = {'price': -10.0}
    result = validator.validate('price', invalid_data)
    assert result.is_valid == False
    
    # 异常高价格（应有警告）
    high_price = {'price': 150000.0}
    result = validator.validate('price', high_price)
    assert len(result.warnings) > 0
    
    # 异常涨跌幅（应有警告）
    extreme_change = {'price': 100.0, 'change_percent': 25.0}
    result = validator.validate('price', extreme_change)
    assert len(result.warnings) > 0
    
    print("✅ 字典格式价格数据验证测试通过")
    return True


def test_company_info_validation():
    """测试公司信息验证"""
    validator = DataValidator()
    
    # 有效的公司信息字符串
    valid_info = """Company Profile (AAPL):
    - Name: Apple Inc
    - Sector: Technology
    - Market Cap: $2,500,000,000,000"""
    
    result = validator.validate('company_info', valid_info)
    assert result.is_valid == True
    
    # 错误的公司信息
    error_info = "Error: Unable to fetch company info"
    result = validator.validate('company_info', error_info)
    assert result.is_valid == False
    
    print("✅ 公司信息验证测试通过")
    return True


def test_financials_validation():
    """测试财务数据验证"""
    validator = DataValidator()
    
    # 有效的财务数据
    valid_financials = {
        'pe_ratio': 25.5,
        'market_cap': 2500000000000,
        'shares_outstanding': 16000000000,
        'price': 156.25
    }
    result = validator.validate('financials', valid_financials)
    assert result.is_valid == True
    
    # 负 P/E（应有警告，但仍有效）
    negative_pe = {'pe_ratio': -15.0}
    result = validator.validate('financials', negative_pe)
    assert len(result.warnings) > 0
    
    # 异常高 P/E（应有警告）
    high_pe = {'pe_ratio': 500.0}
    result = validator.validate('financials', high_pe)
    assert len(result.warnings) > 0
    
    print("✅ 财务数据验证测试通过")
    return True


def test_financials_cross_validation():
    """测试财务数据交叉验证"""
    validator = DataValidator()
    
    # 市值与计算值不一致（应有 issue）
    inconsistent_data = {
        'market_cap': 2500000000000,       # 报告的市值
        'shares_outstanding': 16000000000,  # 流通股数
        'price': 100.0                      # 股价（计算市值应为 1.6T，与报告的 2.5T 不一致）
    }
    result = validator.validate('financials', inconsistent_data)
    
    # 10% 以上的误差应该报告 issue
    assert len(result.issues) > 0 or len(result.warnings) > 0
    
    print("✅ 财务数据交叉验证测试通过")
    return True


def test_news_validation():
    """测试新闻数据验证"""
    validator = DataValidator()
    
    # 有效新闻
    valid_news = """Latest News (AAPL):
    1. [2025-11-30] Apple announces new product
    2. [2025-11-29] Apple stock rises 2%"""
    
    result = validator.validate('news', valid_news)
    assert result.is_valid == True
    
    # 错误新闻
    error_news = "Error: Unable to fetch news"
    result = validator.validate('news', error_news)
    assert result.is_valid == False
    
    print("✅ 新闻数据验证测试通过")
    return True


def test_generic_validation():
    """测试通用验证"""
    validator = DataValidator()
    
    # 有效数据
    result = validator.validate('unknown_type', "Some valid data")
    assert result.is_valid == True
    
    # None 数据
    result = validator.validate('unknown_type', None)
    assert result.is_valid == False
    
    # 包含错误的数据
    result = validator.validate('unknown_type', "Error: Something went wrong")
    assert result.is_valid == False
    
    print("✅ 通用验证测试通过")
    return True


def test_empty_string():
    """测试空字符串验证"""
    validator = DataValidator()
    
    # 空字符串
    result = validator.validate('price', "")
    # 空字符串应该无效或有警告
    assert result.confidence < 1.0
    
    print("✅ 空字符串验证测试通过")
    return True


def test_validation_confidence_levels():
    """测试验证置信度级别"""
    validator = DataValidator()
    
    # 完美数据应该有高置信度
    perfect_data = "AAPL Current Price: $150.00 | Change: $2.50 (+1.69%)"
    result = validator.validate('price', perfect_data)
    assert result.confidence >= 0.7
    
    # 有警告的数据置信度应该较低
    warning_data = {'price': 150000.0}  # 异常高
    result = validator.validate('price', warning_data)
    if result.warnings:
        assert result.confidence < 1.0
    
    print("✅ 验证置信度级别测试通过")
    return True


def run_all_tests():
    """运行所有测试"""
    print("=" * 60)
    print("Step 1.4 测试 - DataValidator 单元测试")
    print("=" * 60)
    print()
    
    tests = [
        ("验证器初始化", test_validator_init),
        ("ValidationResult 结构", test_validation_result_structure),
        ("有效价格数据验证", test_price_validation_valid),
        ("错误价格数据验证", test_price_validation_error),
        ("字典格式价格验证", test_price_validation_dict),
        ("公司信息验证", test_company_info_validation),
        ("财务数据验证", test_financials_validation),
        ("财务数据交叉验证", test_financials_cross_validation),
        ("新闻数据验证", test_news_validation),
        ("通用验证", test_generic_validation),
        ("空字符串验证", test_empty_string),
        ("验证置信度级别", test_validation_confidence_levels),
    ]
    
    results = {}
    for test_name, test_func in tests:
        try:
            result = test_func()
            results[test_name] = result
        except Exception as e:
            print(f"❌ {test_name} 测试失败: {e}")
            import traceback
            traceback.print_exc()
            results[test_name] = False
    
    print()
    print("=" * 60)
    print("测试结果汇总")
    print("=" * 60)
    
    passed = sum(1 for v in results.values() if v)
    total = len(results)
    
    for test_name, result in results.items():
        status = "✅ 通过" if result else "❌ 失败"
        print(f"  {test_name}: {status}")
    
    print()
    print(f"总计: {passed}/{total} 测试通过")
    
    if passed == total:
        print("\n🎉 Step 1.4 DataValidator 测试全部通过！")
        return True
    else:
        print("\n⚠️ 部分测试失败，请修复后再继续。")
        return False


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)

