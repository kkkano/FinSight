"""Quick test for supervisor stream endpoint"""
import asyncio
import aiohttp
import json
import sys

# 设置 stdout 编码
if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

async def test_stream():
    url = 'http://localhost:8000/chat/supervisor/stream'
    payload = {'query': '苹果股票现在多少钱'}
    
    print('Testing stream endpoint...')
    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=120)) as resp:
                print(f'Status: {resp.status}')
                if resp.status == 200:
                    event_count = 0
                    async for line in resp.content:
                        decoded = line.decode('utf-8').strip()
                        if decoded.startswith('data: '):
                            event_count += 1
                            try:
                                data = json.loads(decoded[6:])
                                event_type = data.get('type', 'unknown')
                                print(f'[{event_count}] Event: {event_type}')
                                if event_type == 'thinking':
                                    print(f"  Stage: {data.get('stage')}, Message: {data.get('message', '')[:100]}")
                                elif event_type == 'token':
                                    content = data.get('content', '')
                                    if len(content) <= 30:
                                        print(f"  Token: {content}")
                                    else:
                                        print(f"  Token: {content[:30]}... (len={len(content)})")
                                elif event_type == 'done':
                                    print(f'[OK] Done event received!')
                                    print(f'  Keys: {list(data.keys())}')
                                    print(f'  Success: {data.get("success")}')
                                    print(f'  Intent: {data.get("intent")}')
                                    print(f'  Response len: {len(str(data.get("response", "")))}')
                                    print(f'  Thinking steps: {len(data.get("thinking", []))}')
                                    print(f'  Has report: {data.get("report") is not None}')
                                    if data.get("errors"):
                                        print(f'  Errors: {data.get("errors")}')
                                    break
                                elif event_type == 'error':
                                    print(f'[ERROR] Error: {data.get("message")}')
                            except json.JSONDecodeError as e:
                                print(f'Invalid JSON: {decoded[:100]}... Error: {e}')
                else:
                    print(f'Error: {await resp.text()}')
        except asyncio.TimeoutError:
            print('[TIMEOUT] Request timed out after 120 seconds!')
        except Exception as e:
            print(f'Request failed: {type(e).__name__}: {e}')

if __name__ == '__main__':
    asyncio.run(test_stream())
