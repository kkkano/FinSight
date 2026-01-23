"""Quick API test for report generation after cleanup."""
import requests
import json

def test_health():
    """Test health endpoint."""
    try:
        resp = requests.get("http://127.0.0.1:8000/health", timeout=5)
        print(f"[Health] Status: {resp.status_code}")
        print(f"[Health] Response: {resp.json()}")
        return resp.status_code == 200
    except Exception as e:
        print(f"[Health] Error: {e}")
        return False

def test_chat():
    """Test simple chat."""
    try:
        resp = requests.post(
            "http://127.0.0.1:8000/chat",
            json={"query": "你好", "mode": "chat"},
            timeout=30
        )
        print(f"[Chat] Status: {resp.status_code}")
        data = resp.json()
        print(f"[Chat] Response type: {data.get('type')}")
        print(f"[Chat] Response preview: {data.get('response', '')[:200]}...")
        return resp.status_code == 200
    except Exception as e:
        print(f"[Chat] Error: {e}")
        return False

def test_report():
    """Test report generation."""
    try:
        print("\n[Report] Sending request for AAPL analysis...")
        resp = requests.post(
            "http://127.0.0.1:8000/chat",
            json={"query": "分析 AAPL", "mode": "report"},
            timeout=300  # 5 minutes for report generation
        )
        print(f"[Report] Status: {resp.status_code}")
        data = resp.json()
        print(f"[Report] Response type: {data.get('type')}")
        report = data.get('response', '')
        print(f"[Report] Length: {len(report)} chars")
        print(f"[Report] Preview:\n{report[:500]}...")
        return resp.status_code == 200
    except Exception as e:
        print(f"[Report] Error: {e}")
        return False

if __name__ == "__main__":
    print("=" * 60)
    print("API Test After Report Handler Cleanup")
    print("=" * 60)
    
    # Test health
    print("\n--- Testing Health Endpoint ---")
    health_ok = test_health()
    
    if not health_ok:
        print("\n❌ Health check failed. Is the server running?")
        exit(1)
    
    # Test chat
    print("\n--- Testing Chat Endpoint ---")
    chat_ok = test_chat()
    
    # Test report
    print("\n--- Testing Report Generation ---")
    report_ok = test_report()
    
    print("\n" + "=" * 60)
    print("Summary:")
    print(f"  Health: {'✅' if health_ok else '❌'}")
    print(f"  Chat:   {'✅' if chat_ok else '❌'}")
    print(f"  Report: {'✅' if report_ok else '❌'}")
    print("=" * 60)
