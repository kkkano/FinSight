# -*- coding: utf-8 -*-
"""
项目诊断工具
检查当前环境、依赖版本和API配置
"""

import sys
import subprocess
import importlib.util

def check_python_version():
    """检查Python版本"""
    version = sys.version_info
    print(f"Python版本: {version.major}.{version.minor}.{version.micro}")
    if version.major < 3 or (version.major == 3 and version.minor < 9):
        print("[警告] 建议使用Python 3.9+")
        return False
    return True

def check_package_version(package_name, min_version=None):
    """检查包是否安装及其版本"""
    try:
        spec = importlib.util.find_spec(package_name)
        if spec is None:
            print(f"[缺失] {package_name} 未安装")
            return False

        module = importlib.import_module(package_name)
        version = getattr(module, '__version__', 'unknown')
        print(f"[已安装] {package_name} 版本: {version}")
        return True
    except Exception as e:
        print(f"[错误] 检查 {package_name} 时出错: {str(e)}")
        return False

def check_api_keys():
    """检查API密钥配置"""
    try:
        from config import LLM_CONFIGS
        for provider, config in LLM_CONFIGS.items():
            api_key = config.get('api_key', '')
            if api_key and api_key != 'YOUR_API_KEY_HERE':
                print(f"[配置] {provider}: API密钥已设置")
            else:
                print(f"[警告] {provider}: API密钥未配置")
    except ImportError:
        print("[警告] config.py 不存在或无法导入")
    except Exception as e:
        print(f"[错误] 检查API配置时出错: {str(e)}")

def main():
    """运行完整诊断"""
    print("="*60)
    print("FinSight AI 项目诊断")
    print("="*60)

    # 检查Python版本
    print("\n1. Python环境检查")
    print("-"*60)
    check_python_version()

    # 检查关键依赖
    print("\n2. 依赖包检查")
    print("-"*60)
    packages = [
        'langchain',
        'langchain_core',
        'langchain_openai',
        'langchain_community',
        'yfinance',
        'requests',
        'beautifulsoup4',
        'pandas',
        'finnhub'
    ]

    for pkg in packages:
        check_package_version(pkg)

    # 检查API配置
    print("\n3. API配置检查")
    print("-"*60)
    check_api_keys()

    print("\n" + "="*60)
    print("诊断完成")
    print("="*60)

if __name__ == "__main__":
    main()