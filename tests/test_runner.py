import json
import os
import signal
import subprocess
import sys

import pytest

from algonote.runner import DockerRunner, _capture, compare_output
from algonote import runner_worker


def test_comparison_contract():
    assert compare_output([0, 1], [1, 0], "unordered")
    assert not compare_output([1, 1], [1, 2], "unordered")
    assert not compare_output(True, 1)
    assert not compare_output([True], [1], "unordered")
    assert compare_output(1.0, 1)
    assert compare_output("1\n2\n", "1 2", "tokens", mode="stdin")
    assert not compare_output("1  2\n", "1 2", "exact", mode="stdin")
    assert compare_output("3\r\n", "3", "exact", mode="stdin")
    assert compare_output([0.33333334], [1/3], "float")
    assert not compare_output([1.1], [1.0], "float")
    assert not compare_output("nan", "nan", "float", mode="stdin")
    assert not compare_output(float("inf"), float("inf"), "float")


def test_missing_docker_fails_closed(monkeypatch):
    monkeypatch.setattr("algonote.runner.shutil.which", lambda name: None)
    result = DockerRunner().run(language="python", code="print('must never execute')", mode="stdin", signature=None,
                                tests=[{"input": "", "expected": ""}], comparison="exact")
    assert result["status"] == "runner_unavailable"
    assert result["results"] == []


def test_empty_tests_do_not_claim_acceptance():
    result = DockerRunner().run(language="cpp", code="", mode="stdin", signature=None, tests=[], comparison="exact")
    assert result["status"] == "no_tests"


def test_docker_security_flags():
    command = DockerRunner()._command("algonote-test")
    for option, expected in [("--network", "none"), ("--user", "65534:65534"), ("--cap-drop", "ALL"),
                             ("--pids-limit", "64"), ("--memory", "512m"), ("--security-opt", "no-new-privileges:true")]:
        assert command[command.index(option)+1] == expected
    assert "--read-only" in command
    assert "--privileged" not in command
    assert "--mount" not in command and "-v" not in command
    assert command[-1] == "algonote-runner:0.1"
    with pytest.raises(ValueError):
        DockerRunner("--privileged")


def ready_runner(monkeypatch, worker_result):
    runner = DockerRunner()
    monkeypatch.setattr(runner, "health", lambda: {"available": True})
    captured = {}
    def invoke(command, payload, timeout):
        captured.update(command=command, payload=json.loads(payload), timeout=timeout)
        return {"status": "ok", "returncode": 0, "stdout": json.dumps(worker_result), "stderr": ""}
    monkeypatch.setattr(runner, "_invoke", invoke)
    monkeypatch.setattr(runner, "_remove", lambda name: captured.update(cleaned=name))
    return runner, captured


def test_real_verdicts_are_computed_outside_worker(monkeypatch):
    worker = {"status": "ok", "compile_output": "", "results": [
        {"status": "ok", "actual": "3\n", "stdout": "3\n", "stderr": "", "time_ms": 4},
        {"status": "ok", "actual": "8\n", "stdout": "8\n", "stderr": "", "time_ms": 3}]}
    runner, captured = ready_runner(monkeypatch, worker)
    result = runner.run(language="python", code="print(sum(map(int,input().split())))", mode="stdin", signature=None,
                        tests=[{"name": "one", "input": "1 2", "expected": "3"}, {"name": "two", "input": "4 5", "expected": "9"}], comparison="tokens")
    assert result["status"] == "wrong_answer"
    assert "1/2" in result["summary"]
    assert result["results"][0]["status"] == "accepted"
    assert all("expected" not in test for test in captured["payload"]["tests"])
    assert captured["cleaned"].startswith("algonote-")


@pytest.mark.parametrize("worker,expected", [
    ({"status": "compile_error", "compile_output": "syntax error", "results": []}, "compile_error"),
    ({"status": "ok", "results": []}, "infrastructure_error"),
    ({"status": "infrastructure_error", "detail": "worker failed", "results": []}, "infrastructure_error"),
    ({"status": "ok", "results": [{"status": "time_limit", "time_ms": 2000}]}, "time_limit"),
    ({"status": "ok", "results": [{"status": "runtime_error", "stderr": "bad index"}]}, "runtime_error"),
    ({"status": "ok", "results": [{"status": "output_limit"}]}, "output_limit"),
])
def test_error_statuses_and_cleanup(monkeypatch, worker, expected):
    runner, captured = ready_runner(monkeypatch, worker)
    result = runner.run(language="python", code="print(1)", mode="stdin", signature=None,
                        tests=[{"input": "", "expected": "1"}], comparison="exact")
    assert result["status"] == expected
    assert "cleaned" in captured


def test_capture_limits_a_trusted_test_process():
    result = _capture([sys.executable, "-c", "import time; time.sleep(2)"], b"", 0.1)
    assert result["status"] == "time_limit"
    normal = _capture([sys.executable, "-c", "import sys; print(sys.stdin.read())"], b"fixture", 3)
    assert normal["status"] == "ok" and normal["stdout"].strip() == "fixture"


@pytest.fixture
def trusted_worker_fixture(monkeypatch, tmp_path):
    """Redirect only fixed test subprocesses; no production host-run fallback.

    Docker isolation is not exercised by these process/limit regression tests.
    """
    original_popen = subprocess.Popen
    def launch(command, *args, **kwargs):
        kwargs["cwd"] = tmp_path
        kwargs["env"] = {**kwargs["env"], "ALGONOTE_RESULT_PATH": str(tmp_path / "result.json")}
        return original_popen(command, *args, **kwargs)
    monkeypatch.setattr(runner_worker.subprocess, "Popen", launch)
    return tmp_path


@pytest.mark.parametrize("resource_signal,expected", [
    (signal.SIGXCPU, "time_limit"),
    (signal.SIGXFSZ, "output_limit"),
])
def test_worker_classifies_kernel_limit_signals(trusted_worker_fixture, resource_signal, expected):
    fixture = f"import os,signal; signal.signal({int(resource_signal)},signal.SIG_DFL); os.kill(os.getpid(),{int(resource_signal)})"
    result = runner_worker.execute([sys.executable, "-I", "-c", fixture], "", timeout=2)
    assert result["status"] == expected, result


def test_worker_result_file_limit_is_detectable(trusted_worker_fixture):
    fixture = "import os; open(os.environ['ALGONOTE_RESULT_PATH'],'w').write('x'*100000)"
    result = runner_worker.execute([sys.executable, "-I", "-c", fixture], "", timeout=2)
    path = trusted_worker_fixture / "result.json"
    assert result["returncode"] != 0
    assert runner_worker._oversized_function_result(path)
    with pytest.raises(OverflowError):
        runner_worker._read_function_result(str(path))
    path.write_bytes(b"x" * runner_worker.RESULT_LIMIT)
    assert not runner_worker._oversized_function_result(path)
    link = trusted_worker_fixture / "link.json"
    link.symlink_to(path)
    assert not runner_worker._oversized_function_result(link)


def test_worker_semantic_syntax_check_does_not_execute(trusted_worker_fixture):
    # ast.parse accepts this source; Python compilation correctly rejects it.
    result = runner_worker.execute([sys.executable, "-I", "-c", "compile('return 1', 'solution.py', 'exec')"], "", timeout=2, compile_step=True)
    assert result["returncode"] != 0
    assert "SyntaxError" in result["stderr"]


@pytest.mark.skipif(os.environ.get("ALGONOTE_DOCKER_TESTS") != "1", reason="Set ALGONOTE_DOCKER_TESTS=1 after building the runner image to verify real Docker execution")
@pytest.mark.parametrize("language,code", [
    ("python", "a,b=map(int,input().split());print(a+b)"),
    ("cpp", "#include <iostream>\nint main(){long long a,b;std::cin>>a>>b;std::cout<<a+b;}")
])
def test_live_docker_stdin(language, code):
    runner = DockerRunner()
    assert runner.health()["available"], "Docker integration explicitly requested but unavailable"
    result = runner.run(language=language, code=code, mode="stdin", signature=None,
                        tests=[{"input": "3 4", "expected": "7"}, {"input": "-2 2", "expected": "0"}], comparison="tokens")
    assert result["status"] == "accepted", result


@pytest.mark.skipif(os.environ.get("ALGONOTE_DOCKER_TESTS") != "1", reason="Real Docker integration is opt-in")
def test_live_docker_function_and_limits():
    runner = DockerRunner()
    assert runner.health()["available"]
    signature = {"name": "plus", "class_name": "Solution", "parameters": [{"name": "a", "type": "int"}], "returns": "int"}
    result = runner.run(language="python", code="class Solution:\n    def plus(self,a):\n        print('debug')\n        return a+1", mode="function", signature=signature,
                        tests=[{"input": [3], "expected": 4}], comparison="exact")
    assert result["status"] == "accepted", result
    timeout = runner.run(language="python", code="while True: pass", mode="stdin", signature=None,
                         tests=[{"input": "", "expected": ""}], comparison="exact")
    assert timeout["status"] == "time_limit", timeout
    flood = runner.run(language="python", code="print('x'*200000)", mode="stdin", signature=None,
                       tests=[{"input": "", "expected": ""}], comparison="exact")
    assert flood["status"] == "output_limit", flood
    result_flood = runner.run(language="python", code="class Solution:\n    def plus(self,a):\n        return 'x'*100000", mode="function", signature={**signature, "returns": "str"},
                              tests=[{"input": [3], "expected": ""}], comparison="exact")
    assert result_flood["status"] == "output_limit", result_flood
    syntax = runner.run(language="python", code="return 1", mode="stdin", signature=None,
                        tests=[{"input": "", "expected": ""}], comparison="exact")
    assert syntax["status"] == "compile_error", syntax


@pytest.mark.skipif(os.environ.get("ALGONOTE_DOCKER_TESTS") != "1", reason="Real Docker isolation checks are opt-in")
def test_live_docker_minimum_isolation():
    runner = DockerRunner()
    assert runner.health()["available"]
    probe = """import os, socket
print(os.getuid())
try:
    open('/etc/algonote-test', 'w')
    print('writable')
except OSError:
    print('readonly')
s=socket.socket();s.settimeout(0.5)
try:
    s.connect(('1.1.1.1',443))
    print('network')
except OSError:
    print('isolated')
finally:
    s.close()
"""
    result = runner.run(language="python", code=probe, mode="stdin", signature=None,
                        tests=[{"input": "", "expected": "65534 readonly isolated"}], comparison="tokens")
    assert result["status"] == "accepted", result
