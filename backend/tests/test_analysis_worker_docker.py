"""需显式启用的真实 Linux Docker 隔离验收，不以裸子进程降级。"""
from __future__ import annotations

import os
import uuid
import asyncio
import json
import time
from pathlib import Path

import pytest

from backend.analysis_worker.dispatcher import Dispatcher, Settings, LABEL
from backend.analysis_worker.protocol import JobRequest


pytestmark = pytest.mark.skipif(os.getenv("FINSIGHT_ANALYSIS_DOCKER_TEST") != "1",
                                reason="需要显式启用并预建 compute job 镜像的 Linux Docker 宿主")


def record_observation(name: str, value: dict) -> None:
    directory = os.getenv("FINSIGHT_ANALYSIS_TEST_ARTIFACT_DIR")
    if directory:
        Path(directory, name + ".json").write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


async def assert_no_job_resources(dispatcher: Dispatcher):
    label = f"label={LABEL}={dispatcher.settings.worker_id}"
    assert not (await dispatcher.checked(["container", "ls", "--all", "--filter", label, "--format", "{{.Names}}"])).strip()
    assert not (await dispatcher.checked(["volume", "ls", "--filter", label, "--format", "{{.Name}}"])).strip()


async def wait_for_child_process(dispatcher: Dispatcher, task: asyncio.Task) -> str:
    label = f"label={LABEL}={dispatcher.settings.worker_id}"
    deadline = time.monotonic() + 10
    while not task.done() and time.monotonic() < deadline:
        names = (await dispatcher.checked(["container", "ls", "--filter", label, "--format", "{{.Names}}"])).decode().splitlines()
        for name in names:
            if name.endswith("-run"):
                code, stdout, _ = await dispatcher.cli.command(["container", "top", name, "-eo", "pid,comm"])
                if code == 0 and b"sleep" in stdout:
                    return stdout.decode()
        await asyncio.sleep(0.05)
    raise AssertionError("没有观察到实际运行的作业子进程")


@pytest.mark.asyncio
async def test_real_container_isolation_and_cross_job_filesystem():
    dispatcher = Dispatcher(Settings(enabled=True, token="integration-test-token-00000000000",
                                     image=os.getenv("FINSIGHT_ANALYSIS_JOB_IMAGE", "finsight-compute-job:local"),
                                     worker_id="test-" + uuid.uuid4().hex))
    await dispatcher.initialize()
    assert dispatcher.ready, dispatcher.error
    code = '''
import os, socket
from pathlib import Path
def writable(path):
    try:
        with open(path, 'a') as target: target.write('x')
        return True
    except OSError: return False
try:
    with socket.create_connection(('1.1.1.1', 53), timeout=0.2):
        network = True
except OSError:
    network = False
Path('/tmp/job-marker').write_text('private')
result = {'uid': os.getuid(), 'network': network,
          'socket': Path('/var/run/docker.sock').exists(),
          'secret': bool(os.getenv('FINSIGHT_ANALYSIS_WORKER_TOKEN')),
          'input_writable': writable('/input/request.json'),
          'root_writable': writable('/etc/passwd'),
          'mean': float(pd.DataFrame(datasets['fixture'])['value'].mean())}
'''
    result = await dispatcher.run(JobRequest(code, {"fixture": [{"value": 1}, {"value": 3}]}))
    assert result["status"] == "ok", result
    assert result["result"] == {"uid": 65532, "network": False, "socket": False, "secret": False,
                                "input_writable": False, "root_writable": False, "mean": 2.0}
    following = await dispatcher.run(JobRequest("from pathlib import Path\nresult = Path('/tmp/job-marker').exists()",
                                                 {"fixture": [1]}))
    assert following["status"] == "ok" and following["result"] is False
    await assert_no_job_resources(dispatcher)
    record_observation("isolation", {"first": result, "next_job": following})


@pytest.mark.asyncio
async def test_real_timeout_kills_child_processes():
    dispatcher = Dispatcher(Settings(enabled=True, token="integration-test-token-00000000000",
                                     image=os.getenv("FINSIGHT_ANALYSIS_JOB_IMAGE", "finsight-compute-job:local"),
                                     worker_id="test-" + uuid.uuid4().hex))
    await dispatcher.initialize()
    assert dispatcher.ready, dispatcher.error
    task = asyncio.create_task(dispatcher.run(JobRequest("import subprocess, time\nsubprocess.Popen(['sleep','60'])\ntime.sleep(60)",
                                                          {"fixture": [1]}, timeout_seconds=5)))
    processes = await wait_for_child_process(dispatcher, task)
    result = await task
    assert result["error"] == "analysis_timeout"
    assert dispatcher.ready
    await assert_no_job_resources(dispatcher)
    record_observation("timeout", {"result": result, "processes_observed_before_timeout": processes,
                                    "remaining_job_resources": 0})


@pytest.mark.asyncio
async def test_real_cancellation_kills_child_processes():
    dispatcher = Dispatcher(Settings(enabled=True, token="integration-test-token-00000000000",
                                     image=os.getenv("FINSIGHT_ANALYSIS_JOB_IMAGE", "finsight-compute-job:local"),
                                     worker_id="test-" + uuid.uuid4().hex))
    await dispatcher.initialize()
    assert dispatcher.ready, dispatcher.error
    task = asyncio.create_task(dispatcher.run(JobRequest("import subprocess, time\nsubprocess.Popen(['sleep','60'])\ntime.sleep(60)",
                                                          {"fixture": [1]})))
    processes = await wait_for_child_process(dispatcher, task)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert dispatcher.ready
    await assert_no_job_resources(dispatcher)
    record_observation("cancellation", {"processes_observed_before_cancellation": processes,
                                         "remaining_job_resources": 0})


@pytest.mark.asyncio
@pytest.mark.parametrize("memory_mb", [128, 192, 256])
async def test_real_pandas_capacity_and_peak_memory(memory_mb):
    dispatcher = Dispatcher(Settings(enabled=True, token="integration-test-token-00000000000",
                                     image=os.getenv("FINSIGHT_ANALYSIS_JOB_IMAGE", "finsight-compute-job:local"),
                                     memory_mb=memory_mb, worker_id="test-" + uuid.uuid4().hex))
    started = time.monotonic()
    await dispatcher.initialize()
    startup_ms = round((time.monotonic() - started) * 1000)
    assert dispatcher.ready, dispatcher.error
    code = '''
import resource
from pathlib import Path
frame = pd.DataFrame(datasets['fixture'])
frame['rolling_mean'] = frame['value'].rolling(20).mean()
result = {'rows': len(frame), 'mean': float(frame['value'].mean()),
          'process_peak_rss_kb': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
          'cgroup_peak_memory_bytes': int(Path('/sys/fs/cgroup/memory.peak').read_text()),
          'cgroup_memory_limit_bytes': int(Path('/sys/fs/cgroup/memory.max').read_text())}
'''
    result = await dispatcher.run(JobRequest(code, {"fixture": [{"value": n} for n in range(10000)]}))
    assert result["status"] == "ok", result
    assert result["result"]["rows"] == 10000 and result["result"]["mean"] == 4999.5
    assert result["result"]["cgroup_memory_limit_bytes"] == memory_mb * 1024 * 1024
    assert result["result"]["cgroup_peak_memory_bytes"] < memory_mb * 1024 * 1024
    await assert_no_job_resources(dispatcher)
    record_observation(f"pandas-{memory_mb}mb", {"dispatcher_init_ms": startup_ms, "result": result})


@pytest.mark.asyncio
async def test_real_memavailable_gate_creates_no_resources_when_reserve_is_unavailable():
    # 使用真实 /proc/meminfo 和保守保留值触发拒绝，不消耗宿主内存制造故障。
    raw = Path("/proc/meminfo").read_text()
    total_mb = int(next(line.split()[1] for line in raw.splitlines() if line.startswith("MemTotal:"))) // 1024
    dispatcher = Dispatcher(Settings(enabled=True, token="integration-test-token-00000000000",
                                     image=os.getenv("FINSIGHT_ANALYSIS_JOB_IMAGE", "finsight-compute-job:local"),
                                     reserve_memory_mb=total_mb - 512, worker_id="test-" + uuid.uuid4().hex))
    await dispatcher.initialize()
    assert dispatcher.ready, dispatcher.error
    result = await dispatcher.run(JobRequest("result = 1", {"fixture": [1]}))
    assert result["error"] == "analysis_capacity_insufficient"
    assert result["available_memory_mb"] < result["required_memory_mb"]
    await assert_no_job_resources(dispatcher)
    record_observation("capacity-rejection", {"result": result, "remaining_job_resources": 0})


@pytest.mark.asyncio
async def test_real_small_job_dataframe_and_recoverable_code_error():
    dispatcher = Dispatcher(Settings(enabled=True, token="integration-test-token-00000000000",
        image=os.getenv("FINSIGHT_ANALYSIS_JOB_IMAGE", "finsight-compute-job:local"),
        memory_mb=128, reserve_memory_mb=128, worker_id="test-" + uuid.uuid4().hex))
    await dispatcher.initialize()
    assert dispatcher.ready, dispatcher.error
    datasets = {"prices": {"status": "ok", "data": [{"close": 100}, {"close": 110}, {"close": 120}]}}
    result = await dispatcher.run(JobRequest("frame=get_frame('prices')\nresult={'mean':float(frame['close'].mean())}", datasets))
    assert result["status"] == "ok" and result["result"]["mean"] == 110
    failure = await dispatcher.run(JobRequest("frame=get_frame('prices')\nresult=frame['missing'].mean()", datasets))
    assert failure["error"] == "analysis_code_failed"
    assert failure["code_error"]["type"] == "KeyError" and failure["code_error"]["line"] == 2
    assert "missing" in failure["code_error"]["message"]
    await assert_no_job_resources(dispatcher)
    record_observation("small-job-and-error", {"result": result, "failure": failure, "remaining_job_resources": 0})


@pytest.mark.asyncio
async def test_real_debug_output_survives_missing_result_and_payload_can_be_read():
    dispatcher = Dispatcher(Settings(enabled=True, token="integration-test-token-00000000000",
        image=os.getenv("FINSIGHT_ANALYSIS_JOB_IMAGE", "finsight-compute-job:local"),
        memory_mb=128, reserve_memory_mb=128, worker_id="test-" + uuid.uuid4().hex))
    await dispatcher.initialize()
    assert dispatcher.ready, dispatcher.error
    payload = {'period_ends': ['2026-07-26', '2026-04-26'], 'revenue': [96221000000, 81615000000],
               'warnings': [], 'metric_gaps': ['eps']}
    debug = await dispatcher.run(JobRequest("frame=get_frame(datasets['sec'])\nprint(frame.columns.tolist())", {'sec': payload}))
    assert debug['error'] == 'analysis_result_missing' and 'revenue' in debug['logs']
    result = await dispatcher.run(JobRequest("frame=get_frame(datasets['sec'])\nresult={'difference':int(frame.revenue.iloc[0]-frame.revenue.iloc[1])}", {'sec': payload}))
    assert result['status'] == 'ok' and result['result']['difference'] == 14606000000
    await assert_no_job_resources(dispatcher)
    record_observation('debug-recovery', {'debug': debug, 'calculation': result})


@pytest.mark.asyncio
async def test_real_financial_table_alias_and_numpy_scalars_serialize_without_float_coercion():
    dispatcher = Dispatcher(Settings(enabled=True, token="integration-test-token-00000000000",
        image=os.getenv("FINSIGHT_ANALYSIS_JOB_IMAGE", "finsight-compute-job:local"),
        memory_mb=128, reserve_memory_mb=128, worker_id="test-" + uuid.uuid4().hex))
    await dispatcher.initialize()
    assert dispatcher.ready, dispatcher.error
    payload = {'period_ends': ['2026-07-26', '2026-04-26'], 'revenue': [96221000000, 81615000000], 'currency': 'USD'}
    code = """df=get_frame('sec',table='companyfacts').sort_values('period_end')
a,b=df.iloc[0],df.iloc[1]
result={'difference':b.revenue-a.revenue,'latest':b.period_end,'currency':b.currency,'date':pd.Timestamp('2026-07-26')}
"""
    result = await dispatcher.run(JobRequest(code, {'sec': payload}))
    assert result['status'] == 'ok', result
    assert result['result'] == {'difference': 14606000000, 'latest': '2026-07-26', 'currency': 'USD', 'date': '2026-07-26T00:00:00'}
    assert type(result['result']['difference']) is int
    invalid = await dispatcher.run(JobRequest("result={'value':np.float64('nan')}", {'sec': payload}))
    assert invalid['status'] == 'error'
    await assert_no_job_resources(dispatcher)
    record_observation('financial-alias-and-scalars', {'calculation': result, 'nonfinite_rejected': invalid['status']=='error'})


@pytest.mark.asyncio
async def test_real_dataframe_results_preserve_values_and_output_limits():
    dispatcher = Dispatcher(Settings(enabled=True, token="integration-test-token-00000000000",
        image=os.getenv("FINSIGHT_ANALYSIS_JOB_IMAGE", "finsight-compute-job:local"),
        memory_mb=128, reserve_memory_mb=128, worker_id="test-" + uuid.uuid4().hex))
    await dispatcher.initialize()
    assert dispatcher.ready, dispatcher.error
    code = """result = pd.DataFrame({
    'PE': [15,20,25,30,35], 'EPS_6': [90,120,150,180,210],
    'EPS_8': [120,160,200,240,280], 'EPS_10': [150,200,250,300,350],
    'EPS_12': [180,240,300,360,420],
})"""
    grid = await dispatcher.run(JobRequest(code, {}))
    assert grid["status"] == "ok", grid
    assert grid["result"] == [{"PE": pe, "EPS_6": 6 * pe, "EPS_8": 8 * pe,
                               "EPS_10": 10 * pe, "EPS_12": 12 * pe} for pe in (15, 20, 25, 30, 35)]
    nested = await dispatcher.run(JobRequest(
        "result={'rows':[pd.DataFrame({'revenue':[np.int64(96221000000)], 'period_end':[pd.Timestamp('2026-07-26')]})]}", {}))
    assert nested["status"] == "ok", nested
    assert nested["result"] == {"rows": [[{"revenue": 96221000000, "period_end": "2026-07-26T00:00:00"}]]}
    invalid = await dispatcher.run(JobRequest("result=pd.DataFrame({'value':[np.float64('nan')]})", {}))
    assert invalid["status"] == "error" and invalid["error"] == "analysis_code_or_result_invalid"
    oversized = await dispatcher.run(JobRequest("result=pd.DataFrame({'value':['x'*(1024*1024)]})", {}))
    assert oversized["status"] == "error" and oversized["error"] == "analysis_output_limit"
    await assert_no_job_resources(dispatcher)
    record_observation("dataframe-result-encoding", {"grid": grid, "nested": nested,
        "nonfinite_rejected": invalid["status"] == "error", "oversized_rejected": oversized["status"] == "error",
        "remaining_job_resources": 0})
