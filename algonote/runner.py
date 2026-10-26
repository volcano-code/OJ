"""Docker-only execution, with output comparison outside the submitted program.

No subprocess in this module ever executes submitted Python or C++ on the
application host. If Docker or the prepared image is missing, running fails
closed with an explicit `runner_unavailable` result.
"""
from __future__ import annotations

from collections import Counter
import json
import math
import os
import re
import selectors
import shutil
import signal
import subprocess
import tempfile
import threading
import time
from typing import Any
import uuid

from .harness import build_source


_RUN_SLOTS = threading.BoundedSemaphore(2)
_IMAGE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/:@-]{0,200}$")


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _equal(actual: Any, expected: Any, tolerant: bool = False) -> bool:
    if _is_number(actual) and _is_number(expected):
        try:
            if not math.isfinite(actual) or not math.isfinite(expected):
                return False
            return math.isclose(actual, expected, rel_tol=1e-6, abs_tol=1e-6) if tolerant else actual == expected
        except OverflowError:
            return actual == expected and not tolerant
    if type(actual) is not type(expected):
        return False
    if isinstance(actual, list):
        return len(actual) == len(expected) and all(_equal(a, b, tolerant) for a, b in zip(actual, expected))
    if isinstance(actual, dict):
        return actual.keys() == expected.keys() and all(_equal(actual[k], expected[k], tolerant) for k in actual)
    return actual == expected


def _canonical(value: Any) -> str:
    if isinstance(value, bool):
        return "b:" + str(value)
    if _is_number(value):
        if isinstance(value, float) and value.is_integer():
            value = int(value)
        return "n:" + str(value)
    if value is None:
        return "null"
    if isinstance(value, list):
        return "a:" + json.dumps([_canonical(x) for x in value], ensure_ascii=False)
    if isinstance(value, dict):
        return "o:" + json.dumps({k: _canonical(v) for k, v in sorted(value.items())}, ensure_ascii=False)
    return "s:" + json.dumps(value, ensure_ascii=False)


def compare_output(actual: Any, expected: Any, comparison: str = "exact", *, mode: str = "function") -> bool:
    """Compare using documented rules, never Python eval or executable checkers.

    `unordered` ignores only outer-array order and preserves multiplicity.
    `tokens` ignores whitespace between stdin/stdout tokens.
    `float` applies 1e-6 relative/absolute tolerance to numeric values.
    Exact stdin comparison normalizes CRLF and terminal newlines only.
    """
    if comparison == "tokens":
        return isinstance(actual, str) and isinstance(expected, str) and actual.split() == expected.split()
    if comparison == "unordered":
        return isinstance(actual, list) and isinstance(expected, list) and Counter(map(_canonical, actual)) == Counter(map(_canonical, expected))
    if comparison == "float":
        if mode == "stdin" and isinstance(actual, str) and isinstance(expected, str):
            left, right = actual.split(), expected.split()
            if len(left) != len(right):
                return False
            for a, b in zip(left, right):
                try:
                    if not _equal(float(a), float(b), True):
                        return False
                except ValueError:
                    if a != b:
                        return False
            return True
        return _equal(actual, expected, True)
    if comparison != "exact":
        raise ValueError("未知输出比较规则。")
    if mode == "stdin" and isinstance(actual, str) and isinstance(expected, str):
        return actual.replace("\r\n", "\n").rstrip("\n") == expected.replace("\r\n", "\n").rstrip("\n")
    return _equal(actual, expected)


def _capture(command: list[str], payload: bytes, timeout: float) -> dict:
    """Bound the Docker client's output, even if container code attacks its pipes."""
    started = time.monotonic()
    output_limit = 8 * 1024 * 1024
    with tempfile.TemporaryFile() as stdin_file:
        stdin_file.write(payload)
        stdin_file.seek(0)
        process = subprocess.Popen(command, stdin=stdin_file, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, start_new_session=True)
        buffers = {"stdout": bytearray(), "stderr": bytearray()}
        selector = selectors.DefaultSelector()
        selector.register(process.stdout, selectors.EVENT_READ, "stdout")
        selector.register(process.stderr, selectors.EVENT_READ, "stderr")
        status = "ok"
        try:
            while selector.get_map():
                if time.monotonic() - started >= timeout:
                    status = "time_limit"
                    break
                for key, _ in selector.select(0.05):
                    chunk = os.read(key.fileobj.fileno(), 32768)
                    if not chunk:
                        selector.unregister(key.fileobj)
                        continue
                    room = output_limit - sum(map(len, buffers.values()))
                    buffers[key.data].extend(chunk[:max(0, room)])
                    if len(chunk) > room:
                        status = "output_limit"
                        break
                if status != "ok":
                    break
            if status == "ok":
                try:
                    process.wait(timeout=max(0.01, timeout - (time.monotonic() - started)))
                except subprocess.TimeoutExpired:
                    status = "time_limit"
            if process.poll() is None:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait(timeout=3)
        finally:
            selector.close()
            process.stdout.close()
            process.stderr.close()
            if process.poll() is None:
                process.kill()
        return {"status": status, "returncode": process.returncode,
                "stdout": buffers["stdout"].decode("utf-8", errors="replace"),
                "stderr": buffers["stderr"].decode("utf-8", errors="replace")}


class DockerRunner:
    def __init__(self, image: str = "algonote-runner:0.1") -> None:
        if not _IMAGE_NAME.fullmatch(image):
            raise ValueError("执行镜像名称无效。")
        self.image = image

    def health(self) -> dict:
        if not shutil.which("docker"):
            return {"available": False, "detail": "未找到 Docker。安装并启动 Docker 后，在项目目录执行 .venv/bin/python -m algonote prepare-runner。"}
        try:
            checked = subprocess.run(["docker", "image", "inspect", "--format", "{{.Id}}", self.image],
                                     capture_output=True, text=True, timeout=4)
        except (OSError, subprocess.TimeoutExpired):
            return {"available": False, "detail": "无法连接 Docker，请确认 Docker 服务及当前用户权限。"}
        if checked.returncode:
            return {"available": False, "detail": f"Docker 服务或执行镜像 {self.image} 尚未就绪，请先运行项目启动脚本。"}
        return {"available": True, "detail": "执行镜像已就绪；每次提交将在独立容器中运行。"}

    def _command(self, name: str) -> list[str]:
        return [
            "docker", "run", "--rm", "--pull=never", "--name", name,
            "--hostname", "algonote-sandbox", "--network", "none",
            "--read-only", "--cap-drop", "ALL", "--security-opt", "no-new-privileges:true",
            "--user", "65534:65534", "--cpus", "1", "--memory", "512m", "--memory-swap", "512m",
            "--pids-limit", "64", "--ulimit", "nofile=64:64", "--ulimit", "core=0:0",
            "--tmpfs", "/work:rw,exec,nosuid,nodev,size=96m,uid=65534,gid=65534,mode=700",
            "--tmpfs", "/tmp:rw,noexec,nosuid,nodev,size=32m,uid=65534,gid=65534,mode=700",
            "--init", "-i", self.image,
        ]

    def _invoke(self, command: list[str], payload: bytes, timeout: float) -> dict:
        return _capture(command, payload, timeout)

    def _remove(self, name: str) -> None:
        try:
            subprocess.run(["docker", "rm", "--force", name], stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL, timeout=5)
        except (OSError, subprocess.TimeoutExpired):
            pass

    @staticmethod
    def _failure(status: str, summary: str, compile_output: str = "") -> dict:
        return {"status": status, "summary": summary, "results": [], "compile_output": compile_output}

    def run(self, *, language: str, code: str, mode: str, signature: dict | None,
            tests: list[dict], comparison: str) -> dict:
        if not tests:
            return self._failure("no_tests", "这道题尚未配置测试，添加样例后即可运行。")
        if len(tests) > 50:
            return self._failure("infrastructure_error", "单次提交最多运行 50 个测试。")
        available = self.health()
        if not available["available"]:
            return self._failure("runner_unavailable", available["detail"])
        if not _RUN_SLOTS.acquire(blocking=False):
            return self._failure("infrastructure_error", "已有两个执行任务，请等待当前任务结束后重试。")
        name = "algonote-" + uuid.uuid4().hex
        started_container = False
        try:
            source = build_source(language, code, mode, signature)
            payload = json.dumps({"language": language, "mode": mode, "source": source,
                                  "tests": [{"input": t["input"]} for t in tests]},
                                 ensure_ascii=False, allow_nan=False).encode("utf-8")
            if len(payload) > 8 * 1024 * 1024:
                return self._failure("infrastructure_error", "运行数据过大，请缩小测试输入。")
            started_container = True
            executed = self._invoke(self._command(name), payload, timeout=40 + len(tests) * 2.5)
            if executed["status"] in ("time_limit", "output_limit"):
                return self._failure("infrastructure_error", "执行容器超过整体时间或输出限制，任务已停止。")
            if executed["returncode"] != 0:
                return self._failure("infrastructure_error", "执行容器未正常完成，请检查 Docker 服务和资源。", executed["stderr"][:2000])
            try:
                result = json.loads(executed["stdout"], parse_constant=lambda value: (_ for _ in ()).throw(ValueError("Non-finite output")))
            except (ValueError, TypeError):
                return self._failure("infrastructure_error", "执行服务没有返回合法结果。", executed["stderr"][:2000])
            if not isinstance(result, dict):
                return self._failure("infrastructure_error", "执行服务返回了意外的数据结构。")
            if result.get("status") == "compile_error":
                return self._failure("compile_error", "编译或语法检查失败。", str(result.get("compile_output", ""))[:65536])
            if result.get("status") != "ok" or not isinstance(result.get("results"), list) or len(result["results"]) != len(tests):
                return self._failure("infrastructure_error", "执行任务未能完成全部测试。", str(result.get("detail", ""))[:1000])
            cases = []
            for testcase, execution in zip(tests, result["results"]):
                if not isinstance(execution, dict) or execution.get("status") not in {"ok", "runtime_error", "time_limit", "output_limit"}:
                    return self._failure("infrastructure_error", "执行服务返回了无效的测试状态。")
                if execution["status"] == "ok" and "actual" not in execution:
                    return self._failure("infrastructure_error", "执行服务遗漏了函数或程序的实际输出。")
                status = execution["status"]
                actual = execution.get("actual")
                if status == "ok":
                    status = "accepted" if compare_output(actual, testcase["expected"], comparison, mode=mode) else "wrong_answer"
                cases.append({"name": testcase.get("name", f"测试 {len(cases) + 1}"), "status": status,
                              "actual": actual, "expected": testcase["expected"],
                              "stdout": str(execution.get("stdout", ""))[:65536],
                              "stderr": str(execution.get("stderr", ""))[:65536],
                              "time_ms": execution.get("time_ms", 0)})
            passed = sum(item["status"] == "accepted" for item in cases)
            final = "accepted" if passed == len(cases) else next(item["status"] for item in cases if item["status"] != "accepted")
            return {"status": final, "summary": f"通过已有测试 {passed}/{len(cases)}。", "results": cases,
                    "compile_output": str(result.get("compile_output", ""))[:65536]}
        except (ValueError, TypeError, KeyError) as error:
            return self._failure("infrastructure_error", "执行配置或输入有误：" + str(error)[:500])
        except (OSError, subprocess.SubprocessError):
            return self._failure("infrastructure_error", "无法启动或读取 Docker 执行任务。")
        finally:
            if started_container:
                self._remove(name)
            _RUN_SLOTS.release()
