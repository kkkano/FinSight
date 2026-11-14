"""离线进程的 Linux 内核网络边界；不改父进程，不请求额外 capabilities。"""
from __future__ import annotations

import ctypes
import errno
import platform
from pathlib import Path
import socket
import sys
from threading import Thread


def install_network_filter():
    if sys.platform != "linux":
        return {"installed": False, "kind": "non_linux_python_guard_only"}
    if platform.machine() != "x86_64":
        raise RuntimeError("offline_seccomp_architecture_unsupported")
    if len(list(Path("/proc/self/task").iterdir())) != 1:
        raise RuntimeError("offline_seccomp_must_precede_worker_threads")

    class Instruction(ctypes.Structure):
        _fields_ = [("code", ctypes.c_ushort), ("jt", ctypes.c_ubyte),
                    ("jf", ctypes.c_ubyte), ("k", ctypes.c_uint)]

    class Program(ctypes.Structure):
        _fields_ = [("length", ctypes.c_ushort), ("instructions", ctypes.POINTER(Instruction))]

    # seccomp_data 的 arch/nr/args[0]；x86_64 socket/socketpair/三项 io_uring 系统调用。
    instructions = [
        (0x20, 0, 0, 4), (0x15, 1, 0, 0xC000003E), (0x06, 0, 0, 0x80000000),
        (0x20, 0, 0, 0), (0x45, 9, 0, 0x40000000), (0x15, 5, 0, 41), (0x15, 4, 0, 53),
        (0x15, 6, 0, 425), (0x15, 5, 0, 426), (0x15, 4, 0, 427),
        (0x06, 0, 0, 0x7FFF0000), (0x20, 0, 0, 16),
        (0x15, 0, 1, socket.AF_UNIX), (0x06, 0, 0, 0x7FFF0000),
        (0x06, 0, 0, 0x00050000 | errno.EPERM),
    ]
    array = (Instruction * len(instructions))(*(Instruction(*row) for row in instructions))
    program = Program(len(instructions), array)
    libc = ctypes.CDLL(None, use_errno=True)
    libc.prctl.argtypes = [ctypes.c_int, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulong]
    libc.prctl.restype = ctypes.c_int
    if libc.prctl(38, 1, 0, 0, 0) != 0:
        raise OSError(ctypes.get_errno(), "offline_no_new_privileges_failed")
    if libc.prctl(22, 2, ctypes.addressof(program), 0, 0) != 0:
        raise OSError(ctypes.get_errno(), "offline_seccomp_install_failed")
    status = {}
    for line in Path("/proc/self/status").read_text().splitlines():
        key, _, value = line.partition(":")
        if key in {"NoNewPrivs", "Seccomp", "Seccomp_filters"}:
            status[key] = value.strip()
    return {"installed": True, "kind": "linux_seccomp_no_new_privs", "architecture": "x86_64",
            "allowed_socket_families": ["AF_UNIX"], "denied_errno": errno.EPERM,
            "io_uring_denied": True, "installed_before_production_imports": True,
            "new_threads_inherit": True, "extra_capabilities_requested": False,
            "kernel_status": status}


def probe_network_filter(local_probe_url):
    """用真实 libc/libcurl 与后生线程观察内核结果；仅接收本机 HTTP 正向对照地址。"""
    from urllib.parse import urlsplit
    parsed = urlsplit(local_probe_url)
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "::1", "localhost"}:
        raise ValueError("offline_probe_requires_local_http_positive_control")
    libc = ctypes.CDLL(None, use_errno=True)
    libc.socket.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_int]
    libc.socket.restype = ctypes.c_int

    def native_socket(family):
        ctypes.set_errno(0)
        result = libc.socket(family, socket.SOCK_STREAM, 0)
        error = ctypes.get_errno()
        if result >= 0:
            libc.close(result)
        return {"family": family, "result": result, "errno": error}

    sockets = [native_socket(socket.AF_INET), native_socket(socket.AF_INET6)]
    thread_result = []
    thread = Thread(target=lambda: thread_result.append(native_socket(socket.AF_INET)))
    thread.start()
    thread.join(timeout=5)
    left, right = socket.socketpair(socket.AF_UNIX)
    try:
        left.sendall(b"local-ipc")
        unix_passed = right.recv(9) == b"local-ipc"
    finally:
        left.close()
        right.close()
    from curl_cffi import Curl, CurlInfo, CurlOpt
    curl = Curl()
    curl.setopt(CurlOpt.URL, local_probe_url)
    curl.setopt(CurlOpt.TIMEOUT_MS, 2000)
    curl.setopt(CurlOpt.PROXY, "")
    # 直接调用 CFFI 暴露的原生 libcurl，先取原生 errno，再执行 Python 侧清理。
    from curl_cffi.curl import ffi, lib
    ffi.errno = 0
    native_return = lib.curl_easy_perform(curl._curl)
    native_ffi_errno = ffi.errno
    native_errno = curl.getinfo(CurlInfo.OS_ERRNO)
    curl.close()
    denied = all(row["result"] == -1 and row["errno"] == errno.EPERM for row in sockets + thread_result)
    return {"libc_socket": sockets, "thread_libc_socket": thread_result, "unix_socketpair_passed": unix_passed,
            "libcurl_return": native_return, "libcurl_ffi_errno": native_ffi_errno,
            "libcurl_os_errno": native_errno,
            "passed": denied and len(thread_result) == 1 and unix_passed and native_return == 7
                      and native_ffi_errno == errno.EPERM}
