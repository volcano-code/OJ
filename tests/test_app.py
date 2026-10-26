from __future__ import annotations

import copy
import io
import json
import zipfile

import pytest
from fastapi.testclient import TestClient

from algonote.app import create_app
from algonote.explanations import ExplanationService
from algonote.models import Settings


def problem_fields(**overrides):
    data = {
        "title": "两数之和",
        "source": "leetcode",
        "source_url": "https://leetcode.com/problems/two-sum/",
        "difficulty": "easy",
        "tags": [" 哈希表 ", "数组", "数组"],
        "statement": "返回两个不同元素的下标。",
        "mode": "function",
        "references": {"python": "class Solution:\n    def twoSum(self, nums, target):\n        return [0, 1]\n", "cpp": "class Solution { public: vector<int> twoSum(vector<int>& nums, int target) { return {0,1}; } };"},
        "templates": {"python": "class Solution:\n    def twoSum(self, nums, target):\n        pass\n"},
        "signature": {"name": "twoSum", "class_name": "Solution", "parameters": [{"name": "nums", "type": "int[]"}, {"name": "target", "type": "int"}], "returns": "int[]"},
        "comparison": "unordered",
        "tests": [
            {"name": "样例", "input": [[2, 7], 9], "expected": [0, 1], "sample": True},
            {"name": "补充", "input": [[2, 3, 6], 9], "expected": [1, 2], "sample": False},
        ],
        "notes": "注意重复元素",
        "mastery": "new",
    }
    return data | overrides


class FakeRunner:
    def __init__(self, status="accepted", raises=False):
        self.calls = []
        self.status = status
        self.raises = raises

    def health(self):
        return {"available": self.status != "runner_unavailable", "detail": "test fake"}

    def run(self, **kwargs):
        self.calls.append(copy.deepcopy(kwargs))
        if self.raises:
            raise RuntimeError("provider internal failure")
        return {"status": self.status, "summary": "通过已有测试" if self.status == "accepted" else "未通过测试", "results": [{"name": c["name"], "status": self.status, "actual": c["expected"], "expected": c["expected"], "stdout": "", "stderr": "", "time_ms": 1} for c in kwargs["tests"]], "compile_output": ""}


class FakeAI:
    configured = True

    def __init__(self):
        self.calls = []

    def generate(self, problem, language, verification=None):
        self.calls.append((copy.deepcopy(problem), language, copy.deepcopy(verification)))
        return "## 核心思路\n逐个检查，解释基于用户参考代码。\n\n## 复杂度\n以实际代码为准。"


@pytest.fixture
def setup(tmp_path):
    settings = Settings(data_dir=str(tmp_path / "data"), notebook_dir=str(tmp_path / "notebook"))
    runner, ai = FakeRunner(), FakeAI()
    app = create_app(settings, runner=runner, explanation_service=ai)
    with TestClient(app) as client:
        yield client, settings, runner, ai, app.state.store


def create(client, **overrides):
    response = client.post("/api/problems", json=problem_fields(**overrides))
    assert response.status_code == 201, response.text
    return response.json()


def test_create_edit_persistence_revision_and_source_filters(setup):
    client, settings, runner, ai, store = setup
    first = create(client)
    second = create(client, title="牛客练习", source="nowcoder", mastery="review")
    assert first["tags"] == ["哈希表", "数组"]
    assert client.get("/api/problems", params={"q": "重复元素", "source": "nowcoder", "tag": "哈希表", "mastery": "review"}).json()["items"][0]["id"] == second["id"]
    assert client.get("/api/problems", params={"q": "不存在的关键词"}).json()["total"] == 0
    saved = client.put(f"/api/problems/{first['id']}", json=first | {"title": "更新后的题目"})
    assert saved.status_code == 200
    assert saved.json()["revision"] == 2
    stale = client.put(f"/api/problems/{first['id']}", json=first | {"title": "旧页面内容"})
    assert stale.status_code == 409
    assert client.get(f"/api/problems/{first['id']}").json()["title"] == "更新后的题目"
    versions = client.get(f"/api/problems/{first['id']}/versions").json()["items"]
    assert [v["revision"] for v in versions] == [2, 1]
    assert versions[-1]["snapshot"]["references"] == first["references"]
    assert ai.calls == []


def test_drafts_survive_restart_and_are_scoped_to_problem_and_language(setup):
    client, settings, runner, ai, store = setup
    first, second = create(client), create(client, title="另一个题目")
    for pid, lang, code in [(first["id"], "python", "print('a')"), (first["id"], "cpp", "int main() {}"), (second["id"], "python", "print('b')")]:
        response = client.put(f"/api/problems/{pid}/drafts/{lang}", json={"code": code, "problem_revision": 1})
        assert response.status_code == 200
    with TestClient(create_app(settings, runner=runner, explanation_service=ai)) as restarted:
        assert restarted.get(f"/api/problems/{first['id']}/drafts/python").json()["code"] == "print('a')"
        assert restarted.get(f"/api/problems/{first['id']}/drafts/cpp").json()["code"] == "int main() {}"
        assert restarted.get(f"/api/problems/{second['id']}/drafts/python").json()["code"] == "print('b')"
        assert restarted.get(f"/api/problems/{second['id']}/drafts/cpp").json()["code"] == ""
    assert client.put(f"/api/problems/{first['id']}/drafts/python", json={"code": "", "problem_revision": 999}).status_code == 409


def test_browser_draft_compare_and_swap_prevents_stale_tabs(setup):
    client, settings, runner, ai, store = setup
    p = create(client)
    path = f"/api/problems/{p['id']}/drafts/python"
    initial = {"code": "first tab", "problem_revision": 1, "expected_updated_at": None}
    first = client.put(path, json=initial)
    assert first.status_code == 200
    assert client.put(path, json=initial | {"code": "late first write"}).status_code == 409
    second = client.put(path, json=initial | {"code": "latest text", "expected_updated_at": first.json()["updated_at"]})
    assert second.status_code == 200
    assert client.put(path, json=initial | {"code": "stale second tab", "expected_updated_at": first.json()["updated_at"]}).status_code == 409
    assert client.get(path).json()["code"] == "latest text"


def test_samples_vs_all_and_reference_uses_saved_code(setup):
    client, settings, runner, ai, store = setup
    p = create(client)
    path = f"/api/problems/{p['id']}/run"
    practice = client.post(path, json={"language": "python", "code": "my practice code", "revision": 1, "scope": "samples"})
    assert practice.status_code == 200
    assert practice.json()["status"] == "accepted"
    assert runner.calls[-1]["code"] == "my practice code"
    assert [case["name"] for case in runner.calls[-1]["tests"]] == ["样例"]
    reference = client.post(path, json={"language": "cpp", "code": "must not be used", "revision": 1, "scope": "all", "purpose": "reference"})
    assert reference.status_code == 200
    assert reference.json()["code"] == p["references"]["cpp"]
    assert len(runner.calls[-1]["tests"]) == 2
    history = client.get(f"/api/problems/{p['id']}/attempts").json()["items"]
    assert history[0]["purpose"] == "reference"
    assert history[1]["code"] == "my practice code"
    assert client.post(path, json={"language": "python", "code": "old version", "revision": 2}).status_code == 409
    assert len(runner.calls) == 2


@pytest.mark.parametrize("status", ["runner_unavailable", "wrong_answer", "compile_error", "time_limit", "runtime_error", "output_limit"])
def test_failed_execution_never_becomes_accepted(setup, status):
    client, settings, runner, ai, store = setup
    p = create(client)
    runner.status = status
    response = client.post(f"/api/problems/{p['id']}/run", json={"language": "python", "code": "submitted", "revision": 1})
    assert response.status_code == 200
    assert response.json()["status"] == status
    assert store.attempts(p["id"])[0]["status"] == status


def test_no_tests_and_infrastructure_failure_do_not_claim_judgement(setup):
    client, settings, runner, ai, store = setup
    empty = create(client, tests=[])
    response = client.post(f"/api/problems/{empty['id']}/run", json={"language": "python", "code": "submitted", "revision": 1})
    assert response.json()["status"] == "no_tests"
    assert runner.calls == []
    p = create(client)
    runner.raises = True
    response = client.post(f"/api/problems/{p['id']}/run", json={"language": "python", "code": "submitted", "revision": 1})
    assert response.json()["status"] == "infrastructure_error"
    assert "provider internal failure" not in response.text


def test_ai_is_explicit_persisted_and_stale_after_code_or_test_changes(setup):
    client, settings, runner, ai, store = setup
    p = create(client)
    ep = f"/api/problems/{p['id']}/explanations"
    assert client.get(ep).json() == {"items": []}
    assert ai.calls == []
    generated = client.post(ep, json={"language": "python", "revision": 1})
    assert generated.status_code == 200
    assert generated.json()["origin"] == "ai"
    assert not generated.json()["stale"]
    for _ in range(2):
        assert client.get(ep).json()["items"][0]["content"] == generated.json()["content"]
    assert len(ai.calls) == 1
    revised = client.put(f"/api/problems/{p['id']}", json=p | {"references": p["references"] | {"python": "class Solution:\n    def twoSum(self, nums, target):\n        return [1, 0]\n"}}).json()
    assert client.get(ep).json()["items"][0]["stale"]
    assert len(ai.calls) == 1
    assert client.post(ep, json={"language": "python", "revision": 1}).status_code == 409
    assert client.post(ep, json={"language": "python", "revision": 2}).status_code == 200
    revised["tests"][0]["input"] = [[3, 6], 9]
    assert client.put(f"/api/problems/{p['id']}", json=revised).status_code == 200
    assert client.get(ep).json()["items"][0]["stale"]
    assert len(ai.calls) == 2


def test_ai_receives_reference_evidence_and_manual_revision_is_preserved(setup):
    client, settings, runner, ai, store = setup
    p = create(client)
    root = f"/api/problems/{p['id']}"
    runner.status = "wrong_answer"
    reference = client.post(root + "/run", json={"language": "python", "purpose": "reference", "scope": "all", "revision": 1}).json()
    assert client.post(root + "/explanations", json={"language": "python", "revision": 1}).status_code == 200
    assert ai.calls[-1][2]["id"] == reference["id"]
    manual = client.put(root + "/explanations/python", json={"content": "我的补充笔记", "revision": 1})
    assert manual.status_code == 200
    assert manual.json()["origin"] == "manual"
    assert client.get(root + "/explanations").json()["items"][0]["content"] == "我的补充笔记"
    assert len(store.backup()["explanations"]) == 2


def test_unconfigured_ai_does_not_save_placeholder(setup):
    client, settings, runner, ai, store = setup
    p = create(client)
    with TestClient(create_app(settings, runner=runner, explanation_service=ExplanationService())) as offline:
        response = offline.post(f"/api/problems/{p['id']}/explanations", json={"language": "python", "revision": 1})
        assert response.status_code == 503
        assert offline.get(f"/api/problems/{p['id']}/explanations").json()["items"] == []


def test_export_restore_all_content_and_duplicate_import_skips(setup, tmp_path):
    client, settings, runner, ai, store = setup
    p = create(client)
    root = f"/api/problems/{p['id']}"
    client.put(root + "/drafts/python", json={"code": "unsaved practice", "problem_revision": 1})
    client.post(root + "/run", json={"language": "python", "code": "attempt code", "revision": 1})
    client.put(root + "/explanations/python", json={"content": "手写题解", "revision": 1})
    client.put(root, json=p | {"notes": "后来补充"})
    response = client.get("/api/export")
    assert response.status_code == 200
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        assert archive.read(f"problems/{p['id']}/reference.py").decode() == p["references"]["python"]
        assert archive.read(f"problems/{p['id']}/explanation.python.md").decode() == "手写题解"
        backup = json.loads(archive.read("backup.json"))
    restored_settings = Settings(data_dir=str(tmp_path / "restored-data"), notebook_dir=str(tmp_path / "restored-notes"))
    restored_app = create_app(restored_settings, runner=runner, explanation_service=ai)
    with TestClient(restored_app) as restored:
        result = restored.post("/api/import", json=backup)
        assert result.status_code == 200, result.text
        assert result.json()["imported"] == 1
        assert restored.get(root).json()["notes"] == "后来补充"
        assert restored.get(root + "/drafts/python").json()["code"] == "unsaved practice"
        assert restored.get(root + "/attempts").json()["items"][0]["code"] == "attempt code"
        assert len(restored.get(root + "/versions").json()["items"]) == 2
        assert restored.get(root + "/explanations").json()["items"][0]["content"] == "手写题解"
        duplicate = restored.post("/api/import", json=backup).json()
        assert duplicate["imported"] == 0 and duplicate["skipped"] == 1
        assert len(restored_app.state.store.backup()["attempts"]) == 1


def test_malformed_history_import_is_rejected_before_any_write(setup):
    client, settings, runner, ai, store = setup
    pid = "a" * 32
    backup = {"format": "algonote-backup", "version": 1, "problems": [problem_fields() | {"id": pid, "revision": 1}], "attempts": [{"id": "b" * 32, "problem_id": pid, "problem_revision": 1, "language": "python", "code": "x", "status": "accepted"}]}
    response = client.post("/api/import", json=backup)
    assert response.status_code == 422, response.text
    assert store.list() == []


def test_valid_and_invalid_problem_import_is_atomic(setup):
    client, settings, runner, ai, store = setup
    response = client.post("/api/import", json={"problems": [problem_fields(), problem_fields(references={})]})
    assert response.status_code == 422
    assert client.get("/api/problems").json()["total"] == 0


def test_language_validation_and_safe_source_url(setup):
    client, settings, runner, ai, store = setup
    assert client.post("/api/problems", json=problem_fields(references={"java": "class Solution {}"})).status_code == 422
    assert client.post("/api/problems", json=problem_fields(source_url="javascript:alert(1)")).status_code == 422
    assert client.post("/api/problems", json=problem_fields(source_url="http://[invalid")).status_code == 422
    p = create(client)
    assert client.post(f"/api/problems/{p['id']}/run", json={"language": "bash", "code": "x", "revision": 1}).status_code == 422
    assert client.get(f"/api/problems/{p['id']}/drafts/java").status_code == 422
    assert client.post("/api/infer", json={"language": "java", "code": "x"}).status_code == 422


def test_token_auth_and_cross_origin_write_guards(tmp_path):
    settings = Settings(data_dir=str(tmp_path / "data"), notebook_dir=str(tmp_path / "notes"), token="my-test-token")
    with TestClient(create_app(settings, runner=FakeRunner(), explanation_service=FakeAI())) as client:
        health = client.get("/api/health")
        assert health.status_code == 200 and health.json()["auth_required"]
        assert "my-test-token" not in health.text
        assert client.get("/api/problems").status_code == 401
        assert client.get("/api/problems", headers={"Authorization": "Bearer wrong"}).status_code == 401
        auth = {"Authorization": "Bearer my-test-token"}
        assert client.get("/api/problems", headers=auth).status_code == 200
        assert client.post("/api/problems", json=problem_fields(), headers=auth | {"Origin": "https://unrelated.example"}).status_code == 403
        assert client.post("/api/problems", json=problem_fields(), headers=auth | {"Origin": "http://testserver"}).status_code == 201


def test_body_limit_checks_actual_stream_not_declared_length(setup, monkeypatch):
    client, settings, runner, ai, store = setup
    monkeypatch.setattr("algonote.app.MAX_BODY", 1024)
    response = client.post("/api/import", content=b'{"problems": []}' + b" " * 1100, headers={"Content-Length": "10", "Content-Type": "application/json"})
    assert response.status_code == 413
    assert store.list() == []


def test_delete_checks_revision_and_removes_children(setup):
    client, settings, runner, ai, store = setup
    p = create(client)
    root = f"/api/problems/{p['id']}"
    client.put(root + "/drafts/python", json={"code": "draft", "problem_revision": 1})
    assert client.delete(root, params={"revision": 2}).status_code == 409
    assert client.delete(root, params={"revision": 1}).status_code == 200
    assert client.get(root).status_code == 404
    assert store.backup()["drafts"] == []
