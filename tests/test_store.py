from __future__ import annotations

import copy
import json
import threading
from concurrent.futures import ThreadPoolExecutor, TimeoutError

import pytest

from algonote.store import Conflict, NotebookSyncError, Store


def fields(**overrides):
    return {"title": "A+B", "source": "nowcoder", "statement": "读入两个整数并求和。", "mode": "stdin", "references": {"python": "a, b = map(int, input().split())\nprint(a + b)\n", "cpp": "#include <iostream>\nint main(){long long a,b;std::cin>>a>>b;std::cout<<a+b;}\n"}, "comparison": "tokens", "tests": [{"name": "示例", "input": "1 2\n", "expected": "3\n", "sample": True}], "tags": ["输入输出"]} | overrides


@pytest.fixture
def store(tmp_path):
    return Store(tmp_path / "data" / "notes.db", tmp_path / "notebook")


def attempt(problem, index=0):
    return {"language": "python", "code": f"print({index})", "scope": "all", "purpose": "practice", "problem_revision": problem["revision"], "status": "wrong_answer", "summary": "未通过已有测试", "results": [], "compile_output": ""}


def test_notebook_exports_exact_code_and_removes_deleted_language(store):
    p = store.create(fields())
    directory = store.notebook_dir / "problems" / p["id"]
    assert (directory / "reference.py").read_text() == p["references"]["python"]
    assert json.loads((directory / "problem.json").read_text())["signature"] is None
    store.update(p["id"], fields(references={"cpp": p["references"]["cpp"]}), 1)
    assert not (directory / "reference.py").exists()
    assert (directory / "reference.cpp").read_text() == p["references"]["cpp"]


def test_parallel_edits_enforce_optimistic_revision(store):
    p = store.create(fields())

    def edit(title):
        try:
            return store.update(p["id"], fields(title=title), 1)["revision"]
        except Conflict:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(edit, ["Edit A", "Edit B"]))
    assert sorted(outcomes, key=str) == [2, "conflict"]
    assert len(store.versions(p["id"])) == 2
    exported = json.loads((store.notebook_dir / "problems" / p["id"] / "problem.json").read_text())
    assert exported["revision"] == 2


def test_backup_keeps_all_attempts_beyond_recent_ui_limit(store, tmp_path):
    p = store.create(fields())
    for i in range(105):
        store.save_attempt(p["id"], attempt(p, i))
    assert len(store.attempts(p["id"])) == 100
    backup = store.backup()
    assert len(backup["attempts"]) == 105
    restored = Store(tmp_path / "restored.db", tmp_path / "restored-notes")
    assert restored.import_bundle(backup)["imported"] == 1
    assert len(restored.backup()["attempts"]) == 105


def test_deletion_cascades_and_preserves_unrelated_manual_file(store):
    p = store.create(fields())
    store.save_draft(p["id"], "python", "draft", 1)
    store.save_attempt(p["id"], attempt(p))
    store.save_explanation(p["id"], "python", "手写说明", 1, "manual")
    directory = store.notebook_dir / "problems" / p["id"]
    extra = directory / "my-extra-notes.txt"
    extra.write_text("保留这个额外文件")
    store.delete(p["id"], 1)
    backup = store.backup()
    for key in ("problems", "versions", "explanations", "drafts", "attempts"):
        assert backup[key] == []
    assert extra.read_text() == "保留这个额外文件"
    assert not (directory / "reference.py").exists()


def test_old_explanation_history_survives_regeneration_and_exports_latest(store):
    p = store.create(fields())
    store.save_explanation(p["id"], "python", "第一版", 1, "manual")
    store.save_explanation(p["id"], "python", "第二版", 1, "manual")
    assert store.explanations(p["id"])[0]["content"] == "第二版"
    assert len(store.backup()["explanations"]) == 2
    assert (store.notebook_dir / "problems" / p["id"] / "explanation.python.md").read_text() == "第二版"
    store.update(p["id"], fields(statement="新的题面要求"), 1)
    assert store.explanations(p["id"])[0]["stale"]
    assert "旧版本" in (store.notebook_dir / "problems" / p["id"] / "explanation.python.md").read_text()


def test_path_traversal_identifier_is_rejected_before_any_write(store):
    with pytest.raises(ValueError):
        store.import_bundle({"problems": [fields(), fields(id="../../outside")]})
    assert store.list() == []


def test_duplicate_history_id_does_not_partially_import(store, tmp_path):
    original = store.create(fields())
    store.save_attempt(original["id"], attempt(original))
    backup = store.backup()
    backup["attempts"].append(copy.deepcopy(backup["attempts"][0]))
    target = Store(tmp_path / "target.db", tmp_path / "target-notes")
    with pytest.raises(ValueError):
        target.import_bundle(backup)
    assert target.list() == []


def test_malformed_history_in_mixed_batch_is_atomic(store):
    pid = "a" * 32
    backup = {"format": "algonote-backup", "version": 1, "problems": [fields(id=pid)], "versions": [{"problem_id": pid, "revision": 1, "snapshot": fields(references={})}]}
    with pytest.raises(ValueError):
        store.import_bundle(backup)
    assert store.list() == []


def test_draft_cas_rejects_stale_tab_and_keeps_current_code(store):
    p = store.create(fields())
    first = store.save_draft(p["id"], "python", "tab A first", 1, expected_updated_at=None)
    current = store.save_draft(p["id"], "python", "tab A newer", 1, expected_updated_at=first["updated_at"])
    with pytest.raises(Conflict, match="其他页面"):
        store.save_draft(p["id"], "python", "tab B old edits", 1, expected_updated_at=first["updated_at"])
    assert store.get_draft(p["id"], "python")["code"] == "tab A newer"
    assert store.get_draft(p["id"], "python")["updated_at"] == current["updated_at"]
    # An explicit null is not the same as the legacy omitted argument.
    with pytest.raises(Conflict):
        store.save_draft(p["id"], "python", "another first save", 1, expected_updated_at=None)
    assert store.save_draft(p["id"], "python", "legacy save", 1)["code"] == "legacy save"


def test_draft_first_save_race_is_atomic(store):
    p = store.create(fields())
    start = threading.Barrier(2)

    def save(code):
        start.wait(timeout=3)
        try:
            return store.save_draft(p["id"], "python", code, 1, expected_updated_at=None)["code"]
        except Conflict:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(save, ["first tab", "second tab"]))
    assert outcomes.count("conflict") == 1
    assert store.get_draft(p["id"], "python")["code"] in outcomes


def test_draft_cas_stamp_does_not_repeat_when_clock_is_frozen(store, monkeypatch):
    p = store.create(fields())
    monkeypatch.setattr("algonote.store.now", lambda: "2026-10-26T12:00:00+00:00")
    first = store.save_draft(p["id"], "python", "first", 1, expected_updated_at=None)
    second = store.save_draft(p["id"], "python", "second", 1, expected_updated_at=first["updated_at"])
    third = store.save_draft(p["id"], "python", "third", 1, expected_updated_at=second["updated_at"])
    assert len({first["updated_at"], second["updated_at"], third["updated_at"]}) == 3
    with pytest.raises(Conflict):
        store.save_draft(p["id"], "python", "stale first token", 1, expected_updated_at=first["updated_at"])


@pytest.mark.parametrize("next_operation", ["update", "delete"])
def test_mirror_serializes_delayed_write_with_newer_edit_or_delete(store, monkeypatch, next_operation):
    p = store.create(fields())
    entered, release, next_started = threading.Event(), threading.Event(), threading.Event()
    original_files = store._files

    def paused_files(problem, explanations):
        if problem["revision"] == 2:
            entered.set()
            assert release.wait(timeout=5), "test did not release paused mirror"
        return original_files(problem, explanations)

    monkeypatch.setattr(store, "_files", paused_files)

    def next_write():
        next_started.set()
        if next_operation == "delete":
            return store.delete(p["id"], 2)
        return store.update(p["id"], fields(title="latest revision"), 2)

    with ThreadPoolExecutor(max_workers=2) as pool:
        old_write = pool.submit(store.update, p["id"], fields(title="older revision"), 1)
        assert entered.wait(timeout=3)
        newer_write = pool.submit(next_write)
        assert next_started.wait(timeout=3)
        try:
            # The old mirror owns the DB write lock, including across Store
            # instances/processes; a newer mutation cannot pass it and then be
            # overwritten by the old snapshot.
            with pytest.raises(TimeoutError):
                newer_write.result(timeout=0.15)
        finally:
            release.set()
        assert old_write.result(timeout=3)["revision"] == 2
        newer_write.result(timeout=3)
    directory = store.notebook_dir / "problems" / p["id"]
    if next_operation == "delete":
        assert store.list() == []
        assert not directory.exists()
    else:
        mirrored = json.loads((directory / "problem.json").read_text())
        assert mirrored["revision"] == 3
        assert mirrored["title"] == "latest revision"


def test_failed_mirror_keeps_database_and_can_be_repaired(store, monkeypatch):
    p = store.create(fields())
    original_files = store._files

    def broken_files(*_):
        raise PermissionError("disk permission failure")

    monkeypatch.setattr(store, "_files", broken_files)
    with pytest.raises(NotebookSyncError, match="数据库修改已完成"):
        store.update(p["id"], fields(title="saved in database"), 1)
    assert store.get(p["id"])["revision"] == 2
    assert store.backup()["problems"][0]["title"] == "saved in database"
    monkeypatch.setattr(store, "_files", original_files)
    store.sync_notebook(p["id"])
    mirrored = json.loads((store.notebook_dir / "problems" / p["id"] / "problem.json").read_text())
    assert mirrored["revision"] == 2


def test_retry_import_repairs_files_even_when_database_ids_are_skipped(store, monkeypatch):
    bundle = {"problems": [fields(id="a" * 32), fields(id="b" * 32, title="第二题")]}
    original_sync = store._sync_notebook

    def broken_sync(_):
        raise OSError("disk full")

    monkeypatch.setattr(store, "_sync_notebook", broken_sync)
    with pytest.raises(NotebookSyncError):
        store.import_bundle(bundle)
    assert len(store.list()) == 2
    monkeypatch.setattr(store, "_sync_notebook", original_sync)
    result = store.import_bundle(bundle)
    assert result["imported"] == 0 and result["skipped"] == 2
    for pid in ("a" * 32, "b" * 32):
        assert (store.notebook_dir / "problems" / pid / "reference.py").exists()


def test_import_rejects_history_id_collision_with_existing_other_problem(store, tmp_path):
    existing = store.create(fields())
    existing_attempt = store.save_attempt(existing["id"], attempt(existing))
    source = Store(tmp_path / "source.db", tmp_path / "source-notes")
    incoming = source.create(fields(title="new incoming problem"))
    source.save_attempt(incoming["id"], attempt(incoming))
    backup = source.backup()
    backup["attempts"][0]["id"] = existing_attempt["id"]
    with pytest.raises(ValueError, match="冲突"):
        store.import_bundle(backup)
    assert [p["id"] for p in store.list()] == [existing["id"]]
    assert len(store.backup()["attempts"]) == 1


def test_import_rejects_mismatched_current_snapshot_without_mutating_bundle(store, tmp_path):
    source = Store(tmp_path / "source.db", tmp_path / "source-notes")
    source.create(fields())
    backup = source.backup()
    backup["versions"][0]["snapshot"]["statement"] = "这个同版本快照与当前题面不一致"
    original = copy.deepcopy(backup)
    with pytest.raises(ValueError, match="不一致"):
        store.import_bundle(backup)
    assert store.list() == []
    assert backup == original


def test_import_rejects_history_without_referenced_snapshot(store, tmp_path):
    source = Store(tmp_path / "source.db", tmp_path / "source-notes")
    p = source.create(fields())
    source.save_attempt(p["id"], attempt(p))
    source.update(p["id"], fields(title="version 2"), 1)
    backup = source.backup()
    backup["versions"] = [v for v in backup["versions"] if v["revision"] == 2]
    with pytest.raises(ValueError, match="历史题目版本"):
        store.import_bundle(backup)
    assert store.list() == []


def test_unknown_backup_format_does_not_silently_drop_histories(store):
    with pytest.raises(ValueError, match="备份格式"):
        store.import_bundle({"format": "different-backup", "problems": [fields()]})
    assert store.list() == []
    with pytest.raises(ValueError, match="声明"):
        store.import_bundle({"problems": [fields()], "attempts": []})
    assert store.list() == []


def test_equal_timestamp_explanations_restore_latest_consistently(store, tmp_path, monkeypatch):
    p = store.create(fields())
    monkeypatch.setattr("algonote.store.now", lambda: "2026-10-26T12:00:00+00:00")
    store.save_explanation(p["id"], "python", "first explanation", 1, "manual")
    store.save_explanation(p["id"], "python", "second explanation", 1, "manual")
    target = Store(tmp_path / "target.db", tmp_path / "target-notes")
    target.import_bundle(store.backup())
    assert target.explanations(p["id"])[0]["content"] == "second explanation"
    assert (target.notebook_dir / "problems" / p["id"] / "explanation.python.md").read_text() == "second explanation"
