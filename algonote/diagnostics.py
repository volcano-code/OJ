"""Small local deployment checks. No model calls or notebook mutations."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

from . import __version__
from .explanations import ExplanationService
from .models import Settings
from .runner import DockerRunner

RUNNER_LABEL = "org.algonote.runner.source"


def project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def runner_digest(root: Path | None = None) -> str:
    root = root or project_root()
    digest = hashlib.sha256()
    for relative in ("Dockerfile.runner", "algonote/runner_worker.py"):
        digest.update(relative.encode())
        digest.update(b"\0")
        digest.update((root / relative).read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def prepare_runner(settings: Settings, *, optional: bool = False, root: Path | None = None) -> dict:
    """Build the configured image when the image's actual worker source is stale."""
    DockerRunner(image=settings.runner_image)  # Validate the configured image name before invoking Docker.
    if not shutil.which("docker"):
        return {"status": "skipped" if optional else "error", "detail": "未找到 Docker；题库存储可用，代码执行尚未启用。"}
    try:
        daemon = subprocess.run(["docker", "info", "--format", "{{.ServerVersion}}"], capture_output=True, text=True, timeout=6)
    except (OSError, subprocess.TimeoutExpired):
        return {"status": "skipped" if optional else "error", "detail": "Docker 服务暂时不可访问，请检查服务状态和当前账户权限。"}
    if daemon.returncode:
        return {"status": "skipped" if optional else "error", "detail": "当前账户无法使用 Docker；请先让 docker info 正常返回。"}
    root = root or project_root()
    digest = runner_digest(root)
    try:
        inspected = subprocess.run(["docker", "image", "inspect", "--format", '{{ index .Config.Labels "' + RUNNER_LABEL + '" }}', settings.runner_image], capture_output=True, text=True, timeout=6)
    except (OSError, subprocess.TimeoutExpired):
        return {"status": "error", "detail": "无法读取执行镜像状态，请重试。"}
    if inspected.returncode == 0 and inspected.stdout.strip() == digest:
        return {"status": "ready", "detail": f"执行镜像 {settings.runner_image} 与当前代码一致。"}
    # No shell, no credentials printed, and no volumes mounted. This is an explicit local build.
    try:
        built = subprocess.run(["docker", "build", "--label", f"{RUNNER_LABEL}={digest}", "-t", settings.runner_image, "-f", str(root / "Dockerfile.runner"), str(root)], check=False)
    except OSError:
        return {"status": "error", "detail": "无法启动镜像构建，请检查 Docker。"}
    if built.returncode:
        return {"status": "error", "detail": "执行镜像构建失败；修复构建错误后重试，旧镜像不会被当作本次更新成功。"}
    return {"status": "built", "detail": f"已构建执行镜像 {settings.runner_image}。"}


def storage_check(settings: Settings) -> dict:
    """Check write access without creating problems or changing an existing database."""
    try:
        for location in (settings.data_dir, settings.notebook_dir):
            directory = Path(location)
            directory.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryFile(dir=directory) as probe:
                probe.write(b"algonote-write-check")
                probe.flush()
        database = Path(settings.data_dir) / "algonote.sqlite3"
        if database.exists():
            descriptor = os.open(database, os.O_RDWR)
            os.close(descriptor)
    except OSError:
        return {"name": "storage", "status": "error", "detail": "数据或题目目录不可写。请使用当前账户拥有写入权限的目录，或修改 ALGONOTE_DATA_DIR / ALGONOTE_NOTEBOOK_DIR。"}
    return {"name": "storage", "status": "ok", "detail": "数据库目录与题目文件目录可写。"}


def smoke_cases() -> list[dict]:
    """Known fixtures only, still executed through the same Docker-only runner."""
    signature = {"name": "plusOne", "class_name": "Solution", "parameters": [{"name": "value", "type": "int"}], "returns": "int"}
    cases = [
        {"name": "python_stdin", "language": "python", "mode": "stdin", "signature": None, "code": "a,b=map(int,input().split());print(a+b)", "comparison": "tokens", "tests": [{"name": "求和", "input": "3 4", "expected": "7"}, {"name": "负数", "input": "-5 2", "expected": "-3"}]},
        {"name": "cpp_stdin", "language": "cpp", "mode": "stdin", "signature": None, "code": "#include <iostream>\nint main(){long long a,b;std::cin>>a>>b;std::cout<<a+b;}", "comparison": "tokens", "tests": [{"name": "求和", "input": "3 4", "expected": "7"}, {"name": "负数", "input": "-5 2", "expected": "-3"}]},
        {"name": "python_function", "language": "python", "mode": "function", "signature": signature, "code": "class Solution:\n    def plusOne(self, value):\n        print('debug')\n        return value + 1\n", "comparison": "exact", "tests": [{"name": "函数与调试输出", "input": [4], "expected": 5}]},
        {"name": "cpp_function", "language": "cpp", "mode": "function", "signature": signature, "code": 'class Solution { public: int plusOne(int value) { cout << "debug"; return value+1; } };', "comparison": "exact", "tests": [{"name": "函数与调试输出", "input": [4], "expected": 5}]},
    ]
    return cases


def diagnose(settings: Settings, *, run_check: bool = False, runner=None) -> dict:
    checks = [{"name": "python", "status": "ok" if sys.version_info >= (3, 11) else "error", "detail": f"Python {sys.version.split()[0]}，需要 3.11 或更新版本。"}, storage_check(settings)]
    runner = runner or DockerRunner(image=settings.runner_image)
    health = runner.health()
    checks.append({"name": "runner", "status": "ok" if health["available"] else "error" if run_check else "warning", "detail": health["detail"]})
    ai = ExplanationService(base_url=settings.ai_base_url, api_key=settings.ai_api_key, model=settings.ai_model)
    ai_detail = "已填写 AI 配置，尚未调用模型验证。" if ai.configured else "未配置 AI；可保存题目、重做和手写题解，自动生成暂未启用。"
    checks.append({"name": "ai", "status": "configured" if ai.configured else "warning", "detail": ai_detail})
    smoke = []
    if run_check and health["available"]:
        for case in smoke_cases():
            name = case.pop("name")
            try:
                result = runner.run(**case)
                smoke.append({"name": name, "status": "ok" if result["status"] == "accepted" else "error", "detail": result.get("summary", ""), "verdict": result["status"]})
            except Exception:
                smoke.append({"name": name, "status": "error", "detail": "执行服务未能完成自检，未判定通过。", "verdict": "infrastructure_error"})
    if run_check and not health["available"]:
        smoke = [{"name": "execution_smoke", "status": "blocked", "detail": "Docker 或执行镜像未就绪，没有运行任何编译执行检查。"}]
    ready = not any(c["status"] in {"error", "blocked"} for c in checks + smoke)
    return {"version": __version__, "ok": ready, "run_check_requested": run_check, "checks": checks, "smoke": smoke}


def render_report(report: dict, *, as_json: bool = False):
    if as_json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return
    print(f"AlgoNote {report['version']} 自检")
    labels = {"ok": "通过", "configured": "已配置/未实测", "warning": "提示", "error": "未通过", "blocked": "未执行"}
    for check in report["checks"] + report["smoke"]:
        print(f"[{labels[check['status']]}] {check['name']}: {check['detail']}")
    print("自检完成。" if report["ok"] else "请先处理上述未通过或未执行的检查。")
