import pytest
import time
from backend.services.circuit_breaker import CircuitBreaker, CLOSED, OPEN, HALF_OPEN

class TestCircuitBreaker:

    def test_initial_state(self):
        cb = CircuitBreaker()
        assert cb.can_call("test_source") == True
        state = cb.get_state("test_source")
        assert state["state"] == CLOSED
        assert state["failures"] == 0

    def test_open_circuit(self):
        # 设置阈值为 2 次失败
        cb = CircuitBreaker(failure_threshold=2, recovery_timeout=10)

        # 第一次失败
        cb.record_failure("test_source")
        assert cb.can_call("test_source") == True # 还没达到阈值
        assert cb.get_state("test_source")["state"] == CLOSED

        # 第二次失败 -> 触发熔断
        cb.record_failure("test_source")
        assert cb.can_call("test_source") == False
        assert cb.get_state("test_source")["state"] == OPEN

    def test_recovery_flow(self):
        # 设置极短的恢复时间用于测试
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=0.1, half_open_success_threshold=1)

        # 1. 触发熔断
        cb.record_failure("source_a")
        assert cb.can_call("source_a") == False
        assert cb.get_state("source_a")["state"] == OPEN

        # 2. 等待冷却时间
        time.sleep(0.2)

        # 3. 再次检查 -> 应该进入 HALF_OPEN
        # 注意：can_call 会触发状态变更
        assert cb.can_call("source_a") == True
        assert cb.get_state("source_a")["state"] == HALF_OPEN

        # 4. 模拟探测成功 -> 恢复 CLOSED
        cb.record_success("source_a")
        assert cb.get_state("source_a")["state"] == CLOSED
        assert cb.get_state("source_a")["failures"] == 0

    def test_half_open_failure(self):
        # 测试半开状态下再次失败
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=0.1)

        # 触发熔断
        cb.record_failure("source_b")
        time.sleep(0.2)

        # 进入半开
        assert cb.can_call("source_b") == True
        assert cb.get_state("source_b")["state"] == HALF_OPEN

        # 探测失败 -> 立即重回 OPEN
        cb.record_failure("source_b")
        assert cb.get_state("source_b")["state"] == OPEN
        assert cb.can_call("source_b") == False

    def test_multi_source_isolation(self):
        # 测试不同源的状态隔离
        cb = CircuitBreaker(failure_threshold=1)

        cb.record_failure("bad_source")
        cb.record_success("good_source")

        assert cb.can_call("bad_source") == False
        assert cb.can_call("good_source") == True
