import pytest
from fastapi.testclient import TestClient
import sys
import os

# 将项目根目录添加到sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from fastapi_service import app

client = TestClient(app)

def test_read_root():
    """
    测试根路径是否返回成功响应。
    """
    response = client.get("/")
    assert response.status_code == 200
    assert response.json() == {"message": "Welcome to the Finsight API"}

@pytest.mark.skip(reason="跳过需要LLM的测试，因为LLM尚未初始化")
def test_analyze_endpoint():
    """
    测试/analyze端点。
    注意：此测试需要一个正在运行的LLM实例。
    """
    response = client.post("/analyze", json={"query": "分析一下苹果公司最近的财报"})
    assert response.status_code == 200
    # 在这里可以添加更多关于响应内容的断言
    assert "result" in response.json()

@pytest.mark.skip(reason="跳过需要LLM的测试，因为LLM尚未初始化")
def test_enhanced_analysis_endpoint():
    """
    测试新的/enhanced_analysis端点。
    注意：此测试需要一个正在运行的LLM实例。
    """
    response = client.post(
        "/enhanced_analysis",
        json={"company_name": "特斯拉", "user_query": "最近有什么关于特斯拉自动驾驶的新闻？"}
    )
    assert response.status_code == 200
    assert "result" in response.json()

def test_llm_not_initialized_error_analyze():
    """
    测试在LLM未初始化时/analyze端点是否返回正确的错误。
    """
    # 假设llm是"YOUR_LLM_INSTANCE_HERE"表示未初始化
    response = client.post("/analyze", json={"query": "测试查询"})
    assert response.status_code == 500
    assert response.json() == {"detail": "LLM not initialized"}

def test_llm_not_initialized_error_enhanced_analysis():
    """
    测试在LLM未初始化时/enhanced_analysis端点是否返回正确的错误。
    """
    response = client.post(
        "/enhanced_analysis",
        json={"company_name": "测试公司", "user_query": "测试查询"}
    )
    assert response.status_code == 500
    assert response.json() == {"detail": "LLM not initialized"}
