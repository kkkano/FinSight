#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
流式输出功能测试
测试日期: 2025-12-27
"""
import asyncio
import httpx
import json


async def test_stream_endpoint():
    """测试 /chat/stream 端点"""
    print("=" * 60)
    print("[TEST] Streaming API Test")
    print("=" * 60)

    url = "http://127.0.0.1:8000/chat/stream"
    payload = {"query": "What is the price of AAPL?"}

    print(f"\nRequest: POST {url}")
    print(f"Payload: {payload}")
    print("\nResponse stream:")
    print("-" * 40)

    token_count = 0
    full_content = ""

    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            async with client.stream("POST", url, json=payload) as response:
                if response.status_code != 200:
                    print(f"[FAIL] HTTP Error: {response.status_code}")
                    return False

                async for line in response.aiter_lines():
                    if line.startswith("data: "):
                        try:
                            data = json.loads(line[6:])
                            event_type = data.get("type", "unknown")

                            if event_type == "token":
                                content = data.get("content", "")
                                print(content, end="", flush=True)
                                full_content += content
                                token_count += 1
                            elif event_type == "tool_start":
                                print(f"\n[Tool: {data.get('name', 'unknown')}]", flush=True)
                            elif event_type == "tool_end":
                                print("[Tool done]", flush=True)
                            elif event_type == "done":
                                print("\n[DONE]", flush=True)
                            elif event_type == "error":
                                print(f"\n[ERROR] {data.get('message', 'unknown')}", flush=True)
                                return False
                        except json.JSONDecodeError:
                            pass

        print("\n" + "-" * 40)
        print(f"\n[PASS] Test passed!")
        print(f"   - Received {token_count} tokens")
        print(f"   - Total chars: {len(full_content)}")
        return True

    except httpx.ConnectError:
        print("[FAIL] Cannot connect to backend, please ensure it is running")
        return False
    except Exception as e:
        print(f"[FAIL] Test failed: {e}")
        return False


if __name__ == "__main__":
    print("\n[TEST] FinSight Streaming Test\n")
    result = asyncio.run(test_stream_endpoint())
    print("\n" + "=" * 60)
    if result:
        print("[PASS] All tests passed!")
    else:
        print("[FAIL] Tests failed, please check backend")
    print("=" * 60)
