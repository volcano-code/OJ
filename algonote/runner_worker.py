"""Trusted container entrypoint. This module is never used as a host runner.

The Docker image executes it as an unprivileged user with a read-only root
filesystem. It limits each child independently in addition to Docker's outer
CPU, memory, process, filesystem and network restrictions.
"""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
import resource
import selectors
import signal
import stat
import subprocess
import sys
import tempfile
import time

OUTPUT_LIMIT = 65536
RESULT_LIMIT = 65536
TIME_LIMIT = 2.0
COMPILE_LIMIT = 25.0


def _kill_group(process: subprocess.Popen) -> None:
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


def execute(command: list[str], stdin: str, *, timeout: float, compile_step: bool = False) -> dict:
    def limits() -> None:
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        # One sentinel byte lets the worker distinguish an oversized function
        # result from a legitimate result of exactly RESULT_LIMIT bytes.
        resource.setrlimit(resource.RLIMIT_FSIZE, (16 * 1024 * 1024 if compile_step else RESULT_LIMIT + 1,) * 2)
        resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))
        resource.setrlimit(resource.RLIMIT_CPU, (math.ceil(timeout), math.ceil(timeout) + 1))
        if not compile_step:
            resource.setrlimit(resource.RLIMIT_AS, (256 * 1024 * 1024,) * 2)

    env = {
        "PATH": "/usr/local/bin:/usr/bin:/bin",
        "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8", "PYTHONIOENCODING": "utf-8",
        "PYTHONDONTWRITEBYTECODE": "1", "ALGONOTE_RESULT_PATH": "/work/algonote-result.json",
    }
    started = time.monotonic()
    with tempfile.TemporaryFile() as input_file:
        input_file.write(stdin.encode("utf-8"))
        input_file.seek(0)
        process = subprocess.Popen(command, stdin=input_file, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, cwd="/work", env=env,
                                   start_new_session=True, preexec_fn=limits)
        collected = {"stdout": bytearray(), "stderr": bytearray()}
        selector = selectors.DefaultSelector()
        selector.register(process.stdout, selectors.EVENT_READ, "stdout")
        selector.register(process.stderr, selectors.EVENT_READ, "stderr")
        status = "ok"
        try:
            while selector.get_map():
                if time.monotonic() - started > timeout:
                    status = "time_limit"
                    _kill_group(process)
                    break
                events = selector.select(min(0.05, max(0.001, timeout - (time.monotonic() - started))))
                for key, _ in events:
                    chunk = os.read(key.fileobj.fileno(), 8192)
                    if not chunk:
                        selector.unregister(key.fileobj)
                        continue
                    destination = collected[key.data]
                    remaining = OUTPUT_LIMIT - sum(map(len, collected.values()))
                    destination.extend(chunk[:max(0, remaining)])
                    if len(chunk) > remaining:
                        status = "output_limit"
                        _kill_group(process)
                        break
                if status != "ok":
                    break
            if status == "ok":
                try:
                    process.wait(timeout=max(0.01, timeout - (time.monotonic() - started)))
                except subprocess.TimeoutExpired:
                    status = "time_limit"
                    _kill_group(process)
            # Kill any descendants that outlived the original program.
            _kill_group(process)
            process.wait(timeout=2)
        finally:
            selector.close()
            process.stdout.close()
            process.stderr.close()
            _kill_group(process)
        if status == "ok":
            if process.returncode == 0:
                status = "ok"
            elif process.returncode == -signal.SIGXCPU:
                status = "time_limit"
            elif process.returncode == -signal.SIGXFSZ:
                status = "output_limit"
            else:
                status = "runtime_error"
        return {
            "status": status,
            "returncode": process.returncode,
            "stdout": collected["stdout"].decode("utf-8", errors="replace"),
            "stderr": collected["stderr"].decode("utf-8", errors="replace"),
            "time_ms": round((time.monotonic() - started) * 1000, 2),
        }


def _read_function_result(path: str = "/work/algonote-result.json") -> object:
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode):
            raise ValueError("函数结果不是普通文件")
        if info.st_size > RESULT_LIMIT:
            raise OverflowError("函数结果超过 64 KiB")
        with os.fdopen(descriptor, "rb", closefd=False) as stream:
            raw = stream.read(RESULT_LIMIT + 1)
        if len(raw) > RESULT_LIMIT:
            raise OverflowError("函数结果超过 64 KiB")
        return json.loads(raw.decode("utf-8"), parse_constant=lambda value: (_ for _ in ()).throw(ValueError("函数返回值必须是有限 JSON 数值")))
    finally:
        os.close(descriptor)


def _oversized_function_result(path: Path) -> bool:
    """Inspect without following a program-created symlink or reading its data."""
    try:
        info = path.lstat()
        return stat.S_ISREG(info.st_mode) and info.st_size > RESULT_LIMIT
    except OSError:
        return False


def run_payload(payload: dict) -> dict:
    if payload.get("language") not in ("python", "cpp") or payload.get("mode") not in ("function", "stdin"):
        raise ValueError("Unsupported execution request")
    tests = payload.get("tests", [])
    if not isinstance(tests, list) or not 0 < len(tests) <= 50:
        raise ValueError("Invalid test count")
    source = payload.get("source", "")
    if not isinstance(source, str) or len(source.encode("utf-8")) > 512000:
        raise ValueError("Source too large")
    result = {"compile_output": "", "results": []}
    filename = "program.cpp" if payload["language"] == "cpp" else "program.py"
    Path("/work", filename).write_text(source, encoding="utf-8")
    if payload["language"] == "cpp":
        compiled = execute(["g++", "-std=c++17", "-O2", "-pipe", "/work/program.cpp", "-o", "/work/program"], "", timeout=COMPILE_LIMIT, compile_step=True)
    else:
        # compile() validates semantic syntax such as `return` outside a
        # function, which ast.parse() alone accepts. It does not execute code.
        compiled = execute(["python3", "-I", "-c", "compile(open('/work/program.py', encoding='utf-8').read(), '/work/program.py', 'exec')"], "", timeout=5, compile_step=True)
    result["compile_output"] = (compiled["stdout"] + compiled["stderr"])[:OUTPUT_LIMIT]
    if compiled["status"] != "ok":
        result["status"] = "compile_error"
        if not result["compile_output"]:
            result["compile_output"] = "编译/语法检查失败：" + compiled["status"]
        return result
    command = ["/work/program"] if payload["language"] == "cpp" else ["python3", "-I", "-B", "/work/program.py"]
    for test in tests:
        result_path = Path("/work/algonote-result.json")
        try:
            result_path.unlink(missing_ok=True)
        except OSError as error:
            result["results"].append({"status": "runtime_error", "stdout": "", "stderr": "无法清理函数结果：" + str(error), "time_ms": 0})
            continue
        input_text = json.dumps(test["input"], ensure_ascii=False, allow_nan=False) if payload["mode"] == "function" else test["input"]
        if not isinstance(input_text, str):
            raise ValueError("Standard input must be a string")
        execution = execute(command, input_text, timeout=TIME_LIMIT)
        if payload["mode"] == "function" and execution["status"] == "runtime_error" and _oversized_function_result(result_path):
            execution["status"] = "output_limit"
            execution["stderr"] += "\n函数结果超过 64 KiB。"
        if execution["status"] == "ok" and payload["mode"] == "function":
            try:
                execution["actual"] = _read_function_result()
            except OverflowError as error:
                execution["status"] = "output_limit"
                execution["stderr"] += "\n" + str(error)
            except (OSError, ValueError, UnicodeError) as error:
                execution["status"] = "runtime_error"
                execution["stderr"] += "\n未得到合法的函数返回值：" + str(error)
        elif execution["status"] == "ok":
            execution["actual"] = execution["stdout"]
        result["results"].append(execution)
    result["status"] = "ok"
    return result


def main() -> None:
    try:
        raw = sys.stdin.buffer.read(8 * 1024 * 1024 + 1)
        if len(raw) > 8 * 1024 * 1024:
            raise ValueError("Execution payload too large")
        payload = json.loads(raw)
        result = run_payload(payload)
    except Exception as error:
        result = {"status": "infrastructure_error", "compile_output": "", "results": [], "detail": str(error)[:1000]}
    sys.stdout.write(json.dumps(result, ensure_ascii=False, allow_nan=False))


if __name__ == "__main__":
    main()
