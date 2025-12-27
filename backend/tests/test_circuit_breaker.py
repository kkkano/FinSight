# -*- coding: utf-8 -*-
"""
Step 1.4 测试 - CircuitBreaker 单元测试
验证熔断/恢复的核心行为。
"""

import os
import sys
import time

# 添加项目根目录到路径
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from backend.services import CircuitBreaker


def test_open_after_threshold():
    """连续失败达到阈值后应进入 OPEN 状态并拒绝调用"""
    cb = CircuitBreaker(failure_threshold=2, recovery_timeout=10)

    assert cb.can_call("alpha")
    cb.record_failure("alpha")
    assert cb.can_call("alpha"), "未达到阈值前仍可调用"

    cb.record_failure("alpha")
    state = cb.get_state("alpha")
    assert state["state"] == "OPEN"
    assert cb.can_call("alpha") is False, "OPEN 状态下应短路调用"

    print("[OK] 达到阈值后进入 OPEN 状态")
    return True


def test_recover_after_timeout():
    """超时后应进入 HALF_OPEN，成功一次即关闭"""
    cb = CircuitBreaker(failure_threshold=1, recovery_timeout=1, half_open_success_threshold=1)
    cb.record_failure("beta")

    assert cb.can_call("beta") is False
    time.sleep(1.1)
    assert cb.can_call("beta"), "超时后应允许探测调用 (HALF_OPEN)"

    cb.record_success("beta")
    state = cb.get_state("beta")
    assert state["state"] == "CLOSED"
    assert cb.can_call("beta")

    print("[OK] 超时后探测成功自动关闭")
    return True


def test_reset_on_success():
    """成功应重置失败计数和状态"""
    cb = CircuitBreaker(failure_threshold=3, recovery_timeout=5)
    cb.record_failure("gamma")
    cb.record_success("gamma")

    state = cb.get_state("gamma")
    assert state["state"] == "CLOSED"
    assert state["failures"] == 0
    assert cb.can_call("gamma")

    print("[OK] 成功调用后状态重置")
    return True


def run_all_tests():
    """运行全部测试"""
    print("=" * 60)
    print("CircuitBreaker 单元测试")
    print("=" * 60)
    print()

    tests = [
        ("达到阈值后打开", test_open_after_threshold),
        ("超时探测恢复", test_recover_after_timeout),
        ("成功重置计数", test_reset_on_success),
    ]

    results = {}
    for name, func in tests:
        try:
            results[name] = func()
        except Exception as exc:
            print(f"[FAIL] {name} 失败: {exc}")
            import traceback
            traceback.print_exc()
            results[name] = False

    print()
    print("=" * 60)
    print("测试结果汇总")
    print("=" * 60)
    for name, ok in results.items():
        print(f"  {name}: {'PASS' if ok else 'FAIL'}")

    all_passed = all(results.values())
    if all_passed:
        print("\nCircuitBreaker 测试全部通过")
    else:
        print("\n部分测试未通过")

    return all_passed


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
