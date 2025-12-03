# -*- coding: utf-8 -*-
"""
Step 1.2 测试 - DataCache 单元测试
验证缓存的核心功能
"""

import sys
import os
import time

# 添加项目根目录到路径
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PROJECT_ROOT)

from backend.orchestration.cache import DataCache, CacheEntry


def test_basic_set_get():
    """测试基本的 set/get 操作"""
    cache = DataCache()
    
    # 设置缓存
    cache.set("test_key", {"price": 150.0}, data_type="price")
    
    # 获取缓存
    result = cache.get("test_key")
    
    assert result is not None, "缓存应该存在"
    assert result["price"] == 150.0, "缓存值应该正确"
    
    print("✅ 基本 set/get 测试通过")
    return True


def test_cache_miss():
    """测试缓存未命中"""
    cache = DataCache()
    
    result = cache.get("non_existent_key")
    
    assert result is None, "不存在的键应返回 None"
    
    print("✅ 缓存未命中测试通过")
    return True


def test_ttl_expiration():
    """测试 TTL 过期机制"""
    cache = DataCache()
    
    # 设置一个 1 秒过期的缓存
    cache.set("short_ttl", {"data": "test"}, ttl=1)
    
    # 立即获取，应该存在
    result1 = cache.get("short_ttl")
    assert result1 is not None, "立即获取应该存在"
    
    # 等待 1.5 秒
    time.sleep(1.5)
    
    # 再次获取，应该过期
    result2 = cache.get("short_ttl")
    assert result2 is None, "过期后应返回 None"
    
    print("✅ TTL 过期测试通过")
    return True


def test_default_ttl_by_type():
    """测试不同数据类型的默认 TTL"""
    cache = DataCache()
    
    # 验证默认 TTL 配置
    assert cache.DEFAULT_TTL['price'] == 60, "price TTL 应为 60 秒"
    assert cache.DEFAULT_TTL['company_info'] == 86400, "company_info TTL 应为 24 小时"
    assert cache.DEFAULT_TTL['news'] == 1800, "news TTL 应为 30 分钟"
    
    print("✅ 默认 TTL 配置测试通过")
    return True


def test_cache_stats():
    """测试缓存统计功能"""
    cache = DataCache()
    
    # 初始状态
    stats = cache.get_stats()
    assert stats['hits'] == 0, "初始 hits 应为 0"
    assert stats['misses'] == 0, "初始 misses 应为 0"
    
    # 设置一个缓存
    cache.set("test_stats", {"value": 1})
    
    # 命中
    cache.get("test_stats")
    stats = cache.get_stats()
    assert stats['hits'] == 1, "命中后 hits 应为 1"
    
    # 未命中
    cache.get("non_existent")
    stats = cache.get_stats()
    assert stats['misses'] == 1, "未命中后 misses 应为 1"
    
    # 验证命中率
    assert "%" in stats['hit_rate'], "命中率应该是百分比格式"
    
    print("✅ 缓存统计测试通过")
    return True


def test_cache_delete():
    """测试缓存删除功能"""
    cache = DataCache()
    
    cache.set("to_delete", {"data": "test"})
    assert cache.get("to_delete") is not None
    
    # 删除
    result = cache.delete("to_delete")
    assert result == True, "删除成功应返回 True"
    
    # 验证已删除
    assert cache.get("to_delete") is None, "删除后应返回 None"
    
    # 删除不存在的键
    result = cache.delete("non_existent")
    assert result == False, "删除不存在的键应返回 False"
    
    print("✅ 缓存删除测试通过")
    return True


def test_cache_clear():
    """测试清空缓存功能"""
    cache = DataCache()
    
    # 添加多个缓存
    cache.set("key1", {"data": 1})
    cache.set("key2", {"data": 2})
    cache.set("key3", {"data": 3})
    
    assert len(cache) == 3, "应该有 3 个缓存项"
    
    # 清空
    cache.clear()
    
    assert len(cache) == 0, "清空后应该为空"
    
    print("✅ 清空缓存测试通过")
    return True


def test_cache_contains():
    """测试 'in' 操作符"""
    cache = DataCache()
    
    cache.set("exists", {"data": "test"})
    
    assert "exists" in cache, "'exists' 应该在缓存中"
    assert "not_exists" not in cache, "'not_exists' 不应在缓存中"
    
    print("✅ 'in' 操作符测试通过")
    return True


def test_cleanup_expired():
    """测试过期缓存清理"""
    cache = DataCache()
    
    # 添加一些短 TTL 和长 TTL 的缓存
    cache.set("short1", {"data": 1}, ttl=1)
    cache.set("short2", {"data": 2}, ttl=1)
    cache.set("long", {"data": 3}, ttl=3600)
    
    assert len(cache) == 3
    
    # 等待短 TTL 过期
    time.sleep(1.5)
    
    # 清理过期缓存
    cleaned = cache.cleanup_expired()
    
    assert cleaned == 2, "应该清理 2 个过期缓存"
    assert len(cache) == 1, "应该剩余 1 个缓存"
    assert cache.get("long") is not None, "长 TTL 缓存应该还在"
    
    print("✅ 过期缓存清理测试通过")
    return True


def test_thread_safety():
    """测试线程安全性"""
    import threading
    
    cache = DataCache()
    errors = []
    
    def writer():
        for i in range(100):
            try:
                cache.set(f"key_{threading.current_thread().name}_{i}", {"value": i})
            except Exception as e:
                errors.append(e)
    
    def reader():
        for i in range(100):
            try:
                cache.get(f"key_writer_{i}")
            except Exception as e:
                errors.append(e)
    
    # 创建多个线程
    threads = []
    for i in range(5):
        t = threading.Thread(target=writer, name=f"writer_{i}")
        threads.append(t)
        t = threading.Thread(target=reader, name=f"reader_{i}")
        threads.append(t)
    
    # 启动所有线程
    for t in threads:
        t.start()
    
    # 等待完成
    for t in threads:
        t.join()
    
    assert len(errors) == 0, f"不应该有线程安全错误: {errors}"
    
    print("✅ 线程安全测试通过")
    return True


def run_all_tests():
    """运行所有测试"""
    print("=" * 60)
    print("Step 1.2 测试 - DataCache 单元测试")
    print("=" * 60)
    print()
    
    tests = [
        ("基本 set/get", test_basic_set_get),
        ("缓存未命中", test_cache_miss),
        ("TTL 过期", test_ttl_expiration),
        ("默认 TTL 配置", test_default_ttl_by_type),
        ("缓存统计", test_cache_stats),
        ("缓存删除", test_cache_delete),
        ("清空缓存", test_cache_clear),
        ("'in' 操作符", test_cache_contains),
        ("过期缓存清理", test_cleanup_expired),
        ("线程安全", test_thread_safety),
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
        print("\n🎉 Step 1.2 DataCache 测试全部通过！")
        return True
    else:
        print("\n⚠️ 部分测试失败，请修复后再继续。")
        return False


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)

