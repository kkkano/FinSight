# -*- coding: utf-8 -*-
"""
Phase 4 API 测试
测试 FastAPI 后端功能
"""

import sys
import os
from datetime import datetime

# 添加项目根目录
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# 使用 TestClient 进行测试
from fastapi.testclient import TestClient


def print_header(title: str):
    print("\n" + "=" * 60)
    print(title)
    print("=" * 60)


def print_result(name: str, passed: bool, detail: str = ""):
    status = "✅" if passed else "❌"
    print(f"  {status} {name}")
    if detail:
        print(f"      {detail}")


def run_api_tests():
    """运行 API 测试"""
    print_header("Phase 4 API 测试")
    print(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    results = []
    
    try:
        # 导入并创建 TestClient
        from backend.api.main import app
        client = TestClient(app)
        results.append(("API 模块导入", True, ""))
    except Exception as e:
        print(f"\n❌ API 模块导入失败: {e}")
        return False
    
    # === 健康检查测试 ===
    print("\n🏥 健康检查测试...")
    print("-" * 50)
    
    try:
        response = client.get("/")
        passed = response.status_code == 200 and response.json().get("status") == "healthy"
        results.append(("根路径健康检查", passed, f"状态码: {response.status_code}"))
    except Exception as e:
        results.append(("根路径健康检查", False, str(e)))
    
    try:
        response = client.get("/health")
        passed = response.status_code == 200
        results.append(("/health 端点", passed, ""))
    except Exception as e:
        results.append(("/health 端点", False, str(e)))
    
    # === 对话 API 测试 ===
    print("\n💬 对话 API 测试...")
    print("-" * 50)
    
    session_id = None
    
    try:
        response = client.post("/chat/supervisor", json={"query": "AAPL 股价多少"})
        passed = response.status_code == 200
        data = response.json()
        session_id = data.get("session_id")
        results.append((
            "POST /chat/supervisor 基本调用",
            passed and data.get("success"),
            f"意图: {data.get('intent')}"
        ))
    except Exception as e:
        results.append(("POST /chat/supervisor 基本调用", False, str(e)))
    
    # 测试多轮对话
    if session_id:
        try:
            response = client.post("/chat/supervisor", json={
                "query": "它最近新闻",
                "session_id": session_id
            })
            passed = response.status_code == 200
            data = response.json()
            results.append((
                "多轮对话（使用会话ID）",
                passed and data.get("session_id") == session_id,
                f"意图: {data.get('intent')}"
            ))
        except Exception as e:
            results.append(("多轮对话", False, str(e)))
    
    # 测试意图识别
    intent_tests = [
        ("分析 TSLA", "report", "报告请求"),
        ("帮我盯着 NVDA", "alert", "监控请求"),
    ]
    
    for query, expected_intent, desc in intent_tests:
        try:
            response = client.post("/chat/supervisor", json={"query": query})
            data = response.json()
            intent = data.get("intent")
            passed = intent == expected_intent
            results.append((f"意图识别: {desc}", passed, f"意图: {intent}"))
        except Exception as e:
            results.append((f"意图识别: {desc}", False, str(e)))
    
    # === 分析 API 测试 ===
    print("\n📊 分析 API 测试...")
    print("-" * 50)
    
    try:
        response = client.post("/analyze", json={
            "ticker": "AAPL",
            "depth": "quick"
        })
        passed = response.status_code == 200
        data = response.json()
        results.append((
            "POST /analyze quick",
            passed and data.get("success"),
            f"报告长度: {len(data.get('report', ''))}"
        ))
    except Exception as e:
        results.append(("POST /analyze quick", False, str(e)))
    
    try:
        response = client.post("/analyze", json={
            "ticker": "TSLA",
            "depth": "standard"
        })
        passed = response.status_code == 200
        results.append(("POST /analyze standard", passed, ""))
    except Exception as e:
        results.append(("POST /analyze standard", False, str(e)))
    
    # === 会话管理测试 ===
    print("\n🔄 会话管理测试...")
    print("-" * 50)
    
    if session_id:
        try:
            response = client.get(f"/session/{session_id}")
            passed = response.status_code == 200
            data = response.json()
            results.append((
                "GET /session/{id}",
                passed,
                f"轮数: {data.get('turns')}"
            ))
        except Exception as e:
            results.append(("GET /session/{id}", False, str(e)))
        
        try:
            response = client.post(f"/session/{session_id}/reset")
            passed = response.status_code == 200
            results.append(("POST /session/{id}/reset", passed, ""))
        except Exception as e:
            results.append(("POST /session/{id}/reset", False, str(e)))
        
        try:
            response = client.delete(f"/session/{session_id}")
            passed = response.status_code == 200
            results.append(("DELETE /session/{id}", passed, ""))
        except Exception as e:
            results.append(("DELETE /session/{id}", False, str(e)))
    
    # === 统计 API 测试 ===
    print("\n📈 统计 API 测试...")
    print("-" * 50)
    
    try:
        response = client.get("/stats")
        passed = response.status_code == 200
        data = response.json()
        results.append((
            "GET /stats",
            passed,
            f"总查询: {data.get('total_queries')}"
        ))
    except Exception as e:
        results.append(("GET /stats", False, str(e)))
    
    # === 错误处理测试 ===
    print("\n⚠️ 错误处理测试...")
    print("-" * 50)
    
    try:
        response = client.post("/chat/supervisor", json={"query": ""})
        # 空查询应该返回 422 验证错误
        passed = response.status_code == 422
        results.append(("空查询验证", passed, f"状态码: {response.status_code}"))
    except Exception as e:
        results.append(("空查询验证", False, str(e)))
    
    try:
        response = client.get("/session/nonexistent")
        passed = response.status_code == 404
        results.append(("不存在的会话", passed, f"状态码: {response.status_code}"))
    except Exception as e:
        results.append(("不存在的会话", False, str(e)))
    
    # === 汇总结果 ===
    print_header("API 测试结果汇总")
    
    all_passed = True
    for name, passed, detail in results:
        print_result(name, passed, detail)
        if not passed:
            all_passed = False
    
    passed_count = sum(1 for r in results if r[1])
    total_count = len(results)
    
    print(f"\n总计: {passed_count}/{total_count} 测试通过")
    
    if all_passed:
        print("\n🎉🎉🎉🎉🎉🎉🎉🎉🎉🎉🎉🎉🎉🎉🎉🎉🎉🎉🎉🎉")
        print("🎉 Phase 4 API 测试全部通过！")
        print("🎉 FastAPI 后端已准备就绪")
        print("🎉 启动: uvicorn backend.api.main:app --reload")
        print("🎉🎉🎉🎉🎉🎉🎉🎉🎉🎉🎉🎉🎉🎉🎉🎉🎉🎉🎉🎉")
    else:
        print("\n⚠️ 部分测试未通过")
    
    return all_passed


if __name__ == "__main__":
    success = run_api_tests()
    sys.exit(0 if success else 1)

