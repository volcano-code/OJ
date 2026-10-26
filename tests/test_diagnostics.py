from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from algonote import diagnostics
from algonote.diagnostics import diagnose, prepare_runner, render_report, runner_digest, storage_check
from algonote.models import Settings


@pytest.fixture
def settings(tmp_path):
    return Settings(data_dir=str(tmp_path / "data"), notebook_dir=str(tmp_path / "notebook"), runner_image="my-algonote:local")


@pytest.fixture
def image_source(tmp_path):
    root = tmp_path / "project"
    (root / "algonote").mkdir(parents=True)
    (root / "Dockerfile.runner").write_text("FROM example\n")
    (root / "algonote/runner_worker.py").write_text("print('version 1')\n")
    return root


def test_prepare_runner_honors_config_and_rebuilds_missing_or_changed_image(monkeypatch, settings, image_source):
    calls = []
    monkeypatch.setattr(diagnostics.shutil, "which", lambda name: "/usr/bin/docker")

    def fake_run(command, **kwargs):
        calls.append(command)
        if command[1] == "info":
            return SimpleNamespace(returncode=0, stdout="version")
        if command[1] == "image":
            return SimpleNamespace(returncode=0, stdout="old-fingerprint")
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(diagnostics.subprocess, "run", fake_run)
    result = prepare_runner(settings, root=image_source)
    assert result["status"] == "built"
    build = calls[-1]
    assert build[build.index("-t") + 1] == "my-algonote:local"
    assert build[build.index("--label") + 1] == diagnostics.RUNNER_LABEL + "=" + runner_digest(image_source)
    old = runner_digest(image_source)
    (image_source / "algonote/runner_worker.py").write_text("print('version 2')\n")
    assert runner_digest(image_source) != old


def test_prepare_runner_reuses_matching_image_without_a_build(monkeypatch, settings, image_source):
    calls = []
    monkeypatch.setattr(diagnostics.shutil, "which", lambda name: "/usr/bin/docker")

    def fake_run(command, **kwargs):
        calls.append(command)
        return SimpleNamespace(returncode=0, stdout=runner_digest(image_source))

    monkeypatch.setattr(diagnostics.subprocess, "run", fake_run)
    assert prepare_runner(settings, root=image_source)["status"] == "ready"
    assert not any(command[1] == "build" for command in calls)


def test_optional_preparation_does_not_claim_missing_docker_is_ready(monkeypatch, settings):
    monkeypatch.setattr(diagnostics.shutil, "which", lambda name: None)
    assert prepare_runner(settings, optional=True)["status"] == "skipped"
    assert prepare_runner(settings)["status"] == "error"


def test_failed_build_is_error_even_when_preparation_is_optional(monkeypatch, settings, image_source):
    monkeypatch.setattr(diagnostics.shutil, "which", lambda name: "/usr/bin/docker")

    def fake_run(command, **kwargs):
        return SimpleNamespace(returncode=0 if command[1] == "info" else 1, stdout="")

    monkeypatch.setattr(diagnostics.subprocess, "run", fake_run)
    assert prepare_runner(settings, root=image_source, optional=True)["status"] == "error"


def test_storage_check_reports_permissions_and_leaves_database_bytes_untouched(monkeypatch, settings):
    assert storage_check(settings)["status"] == "ok"
    database = Path(settings.data_dir) / "algonote.sqlite3"
    database.write_bytes(b"existing fixture bytes")
    assert storage_check(settings)["status"] == "ok"
    assert database.read_bytes() == b"existing fixture bytes"
    assert list(Path(settings.notebook_dir).iterdir()) == []

    def denied(*args, **kwargs):
        raise PermissionError("fixture permission denied")

    monkeypatch.setattr(diagnostics.tempfile, "TemporaryFile", denied)
    assert storage_check(settings)["status"] == "error"


class ProbeRunner:
    def __init__(self, available=True, verdict="accepted"):
        self.available, self.verdict, self.calls = available, verdict, []

    def health(self):
        return {"available": self.available, "detail": "test fixture state"}

    def run(self, **kwargs):
        self.calls.append(kwargs)
        return {"status": self.verdict, "summary": "fixture verdict"}


def test_diagnostics_are_configuration_only_unless_smoke_requested(settings):
    runner = ProbeRunner()
    report = diagnose(settings, runner=runner)
    assert report["ok"] is True
    assert runner.calls == []
    assert report["smoke"] == []


def test_smoke_checks_both_languages_and_both_modes(settings):
    runner = ProbeRunner()
    report = diagnose(settings, run_check=True, runner=runner)
    assert report["ok"] is True
    assert {(x["language"], x["mode"]) for x in runner.calls} == {("cpp", "stdin"), ("cpp", "function"), ("python", "stdin"), ("python", "function")}
    assert len(report["smoke"]) == 4


def test_requested_execution_check_is_blocked_without_docker(settings):
    runner = ProbeRunner(available=False)
    assert diagnose(settings, runner=runner)["ok"] is True  # The notebook can run without the execution service.
    report = diagnose(settings, run_check=True, runner=runner)
    assert report["ok"] is False
    assert report["smoke"][0]["status"] == "blocked"
    assert runner.calls == []


def test_failed_smoke_does_not_pass_and_secrets_are_not_in_report(settings, capsys):
    settings.ai_base_url = "http://localhost:9999/v1"
    settings.ai_model = "configured-model"
    settings.ai_api_key = "DO-NOT-PRINT-API-SECRET"
    settings.token = "DO-NOT-PRINT-ACCESS-TOKEN"
    report = diagnose(settings, run_check=True, runner=ProbeRunner(verdict="compile_error"))
    render_report(report, as_json=True)
    output = capsys.readouterr().out
    assert json.loads(output)["ok"] is False
    assert "DO-NOT-PRINT" not in output
    assert next(c for c in report["checks"] if c["name"] == "ai")["status"] == "configured"


def test_empty_or_invalid_image_name_does_not_reach_docker(monkeypatch, settings):
    settings.runner_image = "--privileged"
    with pytest.raises(ValueError):
        prepare_runner(settings)
