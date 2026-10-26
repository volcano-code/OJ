from __future__ import annotations

import hashlib
import io
import json
import logging
import os
import re
import sqlite3
import tempfile
import uuid
import zipfile
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .models import ProblemInput


_UNSET = object()
NOTEBOOK_FILES = ("problem.json", "statement.md", "reference.py", "reference.cpp", "explanation.python.md", "explanation.cpp.md", "tests.json")


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, allow_nan=False)


def _timestamp(value: Any, default: str) -> str:
    if value is None:
        return default
    if not isinstance(value, str):
        raise ValueError("历史记录的时间格式无效")
    try:
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc).isoformat()
    except (ValueError, OverflowError):
        raise ValueError("历史记录的时间需要是 ISO 日期时间") from None


def fingerprint(problem: dict, language: str) -> str:
    value = {"statement": problem["statement"], "code": problem["references"].get(language, ""), "signature": problem.get("signature"), "mode": problem["mode"], "tests": problem["tests"], "comparison": problem["comparison"]}
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


class NotFound(Exception):
    pass


class Conflict(Exception):
    pass


class NotebookSyncError(Exception):
    pass


class Store:
    def __init__(self, path: str | Path, notebook_dir: str | Path):
        self.path = Path(path)
        self.notebook_dir = Path(notebook_dir)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.notebook_dir.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS problems (
                    id TEXT PRIMARY KEY, revision INTEGER NOT NULL, data TEXT NOT NULL,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS versions (
                    problem_id TEXT NOT NULL REFERENCES problems(id) ON DELETE CASCADE,
                    revision INTEGER NOT NULL, snapshot TEXT NOT NULL, created_at TEXT NOT NULL,
                    PRIMARY KEY(problem_id,revision)
                );
                CREATE TABLE IF NOT EXISTS explanations (
                    id TEXT PRIMARY KEY, problem_id TEXT NOT NULL REFERENCES problems(id) ON DELETE CASCADE,
                    language TEXT NOT NULL, content TEXT NOT NULL, origin TEXT NOT NULL,
                    problem_revision INTEGER NOT NULL, source_hash TEXT NOT NULL, created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS drafts (
                    problem_id TEXT NOT NULL REFERENCES problems(id) ON DELETE CASCADE,
                    language TEXT NOT NULL, code TEXT NOT NULL, problem_revision INTEGER NOT NULL,
                    updated_at TEXT NOT NULL, PRIMARY KEY(problem_id,language)
                );
                CREATE TABLE IF NOT EXISTS attempts (
                    id TEXT PRIMARY KEY, problem_id TEXT NOT NULL REFERENCES problems(id) ON DELETE CASCADE,
                    data TEXT NOT NULL, created_at TEXT NOT NULL
                );
                PRAGMA user_version=1;
            """)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            with db:
                yield db
        finally:
            db.close()

    @staticmethod
    def _get(db, problem_id: str) -> dict:
        row = db.execute("SELECT data FROM problems WHERE id=?", (problem_id,)).fetchone()
        if row is None:
            raise NotFound("题目不存在")
        return json.loads(row["data"])

    def get(self, problem_id: str) -> dict:
        with self.connect() as db:
            return self._get(db, problem_id)

    def list(self, q="", source="", tag="", mastery="") -> list[dict]:
        with self.connect() as db:
            rows = db.execute("SELECT data FROM problems ORDER BY updated_at DESC,id").fetchall()
        items = []
        for row in rows:
            p = json.loads(row["data"])
            text = " ".join([p["title"], *p["tags"], p["notes"]]).casefold()
            if q.casefold() not in text or (source and p["source"] != source) or (tag and tag not in p["tags"]) or (mastery and p["mastery"] != mastery):
                continue
            items.append({key: p[key] for key in ("id", "revision", "title", "source", "source_url", "difficulty", "tags", "mode", "mastery", "created_at", "updated_at")} | {"languages": [lang for lang, code in p["references"].items() if code.strip()], "test_count": len(p["tests"])})
        return items

    def create(self, fields: dict) -> dict:
        stamp = now()
        p = ProblemInput.model_validate(fields).model_dump() | {"id": uuid.uuid4().hex, "revision": 1, "created_at": stamp, "updated_at": stamp}
        with self.connect() as db:
            self._insert_problem(db, p)
        self.sync_notebook(p["id"])
        return p

    @staticmethod
    def _insert_problem(db, p: dict):
        db.execute("INSERT INTO problems VALUES(?,?,?,?,?)", (p["id"], p["revision"], dumps(p), p["created_at"], p["updated_at"]))
        db.execute("INSERT INTO versions VALUES(?,?,?,?)", (p["id"], p["revision"], dumps(p), p["updated_at"]))

    def update(self, problem_id: str, fields: dict, revision: int) -> dict:
        clean = ProblemInput.model_validate(fields).model_dump()
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            old = self._get(db, problem_id)
            if old["revision"] != revision:
                raise Conflict("题目已在其他页面修改，请刷新后再保存；当前编辑内容仍保留在页面中")
            p = clean | {"id": problem_id, "revision": revision + 1, "created_at": old["created_at"], "updated_at": now()}
            db.execute("UPDATE problems SET revision=?,data=?,updated_at=? WHERE id=?", (p["revision"], dumps(p), p["updated_at"], problem_id))
            db.execute("INSERT INTO versions VALUES(?,?,?,?)", (problem_id, p["revision"], dumps(p), p["updated_at"]))
        self.sync_notebook(problem_id)
        return p

    def delete(self, problem_id: str, revision: int):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if self._get(db, problem_id)["revision"] != revision:
                raise Conflict("题目版本已变化，请刷新后再删除")
            db.execute("DELETE FROM problems WHERE id=?", (problem_id,))
        # The same serialized mirror path also handles deletion. A concurrent
        # import of this ID must not have its newly written files removed here.
        self.sync_notebook(problem_id)

    def versions(self, problem_id: str) -> list[dict]:
        with self.connect() as db:
            self._get(db, problem_id)
            return [{"revision": r["revision"], "snapshot": json.loads(r["snapshot"]), "created_at": r["created_at"]} for r in db.execute("SELECT * FROM versions WHERE problem_id=? ORDER BY revision DESC", (problem_id,))]

    def explanations(self, problem_id: str) -> list[dict]:
        with self.connect() as db:
            problem = self._get(db, problem_id)
            rows = db.execute("SELECT * FROM explanations WHERE problem_id=? ORDER BY created_at DESC,rowid DESC", (problem_id,)).fetchall()
        result, seen = [], set()
        for row in rows:
            item = dict(row)
            if item["language"] in seen:
                continue
            seen.add(item["language"])
            item["stale"] = item["source_hash"] != fingerprint(problem, item["language"])
            result.append(item)
        return result

    def save_explanation(self, problem_id: str, language: str, content: str, revision: int, origin: str) -> dict:
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            p = self._get(db, problem_id)
            if p["revision"] != revision:
                raise Conflict("题目已更新，请基于最新参考答案重新生成或保存解析")
            if not p["references"].get(language, "").strip():
                raise ValueError("请先保存这个语言的参考答案")
            item = {"id": uuid.uuid4().hex, "problem_id": problem_id, "language": language, "content": content, "origin": origin, "problem_revision": revision, "source_hash": fingerprint(p, language), "created_at": now()}
            db.execute("INSERT INTO explanations VALUES(:id,:problem_id,:language,:content,:origin,:problem_revision,:source_hash,:created_at)", item)
        self.sync_notebook(problem_id)
        return item | {"stale": False}

    def get_draft(self, problem_id: str, language: str) -> dict:
        with self.connect() as db:
            p = self._get(db, problem_id)
            r = db.execute("SELECT * FROM drafts WHERE problem_id=? AND language=?", (problem_id, language)).fetchone()
            return dict(r) if r else {"code": "", "updated_at": None, "problem_revision": p["revision"]}

    def save_draft(self, problem_id: str, language: str, code: str, revision: int, expected_updated_at: str | None | object = _UNSET) -> dict:
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            p = self._get(db, problem_id)
            if revision > p["revision"]:
                raise Conflict("草稿的题目版本不存在")
            current = db.execute("SELECT updated_at FROM drafts WHERE problem_id=? AND language=?", (problem_id, language)).fetchone()
            previous_stamp = current["updated_at"] if current else None
            if expected_updated_at is not _UNSET and expected_updated_at != previous_stamp:
                raise Conflict("草稿已在其他页面保存，请先查看最新草稿；当前编辑内容仍保留，请勿直接覆盖")
            stamp = now()
            if previous_stamp:
                # CAS stamps must never repeat, including very fast saves and a
                # system clock that moved backwards. Existing old backups may
                # have nonstandard stamps; a fresh ISO stamp replaces those.
                try:
                    previous = datetime.fromisoformat(previous_stamp)
                    if previous.tzinfo is None:
                        previous = previous.replace(tzinfo=timezone.utc)
                    current_time = datetime.fromisoformat(stamp)
                    if current_time <= previous:
                        stamp = (previous + timedelta(microseconds=1)).isoformat()
                except ValueError:
                    pass
            item = {"problem_id": problem_id, "language": language, "code": code, "problem_revision": revision, "updated_at": stamp}
            db.execute("INSERT INTO drafts VALUES(:problem_id,:language,:code,:problem_revision,:updated_at) ON CONFLICT(problem_id,language) DO UPDATE SET code=excluded.code,problem_revision=excluded.problem_revision,updated_at=excluded.updated_at", item)
        return item

    def save_attempt(self, problem_id: str, data: dict) -> dict:
        item = data | {"id": uuid.uuid4().hex, "problem_id": problem_id, "created_at": now()}
        with self.connect() as db:
            self._get(db, problem_id)
            db.execute("INSERT INTO attempts VALUES(?,?,?,?)", (item["id"], problem_id, dumps(item), item["created_at"]))
        return item

    def attempts(self, problem_id: str) -> list[dict]:
        with self.connect() as db:
            self._get(db, problem_id)
            return [json.loads(r[0]) for r in db.execute("SELECT data FROM attempts WHERE problem_id=? ORDER BY created_at DESC,rowid DESC LIMIT 100", (problem_id,))]

    def backup(self) -> dict:
        with self.connect() as db:
            # One read transaction gives a consistent snapshot while other requests save.
            db.execute("BEGIN")
            problems = [json.loads(r[0]) for r in db.execute("SELECT data FROM problems ORDER BY id")]
            versions = [{"problem_id": r["problem_id"], "revision": r["revision"], "snapshot": json.loads(r["snapshot"]), "created_at": r["created_at"]} for r in db.execute("SELECT * FROM versions ORDER BY problem_id,revision")]
            explanations = [dict(r) for r in db.execute("SELECT * FROM explanations ORDER BY created_at,rowid")]
            drafts = [dict(r) for r in db.execute("SELECT * FROM drafts")]
            attempts = [json.loads(r[0]) for r in db.execute("SELECT data FROM attempts ORDER BY created_at,rowid")]
        return {"format": "algonote-backup", "version": 1, "exported_at": now(), "problems": problems, "versions": versions, "explanations": explanations, "drafts": drafts, "attempts": attempts}

    def export_zip(self) -> bytes:
        backup = self.backup()
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("backup.json", json.dumps(backup, ensure_ascii=False, indent=2, allow_nan=False))
            archive.writestr("README.txt", "AlgoNote 备份\nbackup.json 可以通过网页的导入功能恢复题目、解析、草稿、历史版本和提交记录。\nproblems/ 下是便于阅读和提交到 Git 的 Markdown、源码与测试数据。\n")
            for problem in backup["problems"]:
                explanations = [x for x in backup["explanations"] if x["problem_id"] == problem["id"]]
                for name, content in self._files(problem, explanations).items():
                    archive.writestr(f"problems/{problem['id']}/{name}", content)
        return stream.getvalue()

    @staticmethod
    def _files(problem: dict, explanations: list[dict]) -> dict[str, str]:
        files = {"problem.json": json.dumps(problem, ensure_ascii=False, indent=2), "statement.md": problem["statement"], "tests.json": json.dumps(problem["tests"], ensure_ascii=False, indent=2)}
        for lang, code in problem["references"].items():
            if code.strip():
                files["reference.py" if lang == "python" else "reference.cpp"] = code
        for explanation in sorted(explanations, key=lambda e: e["created_at"]):
            stale = explanation["source_hash"] != fingerprint(problem, explanation["language"])
            notice = "> 参考答案已修改，这份题解对应旧版本。\n\n" if stale else ""
            files[f"explanation.{explanation['language']}.md"] = notice + explanation["content"]
        return files

    def sync_notebook(self, problem_id: str):
        if not isinstance(problem_id, str) or not re.fullmatch(r"[0-9a-f]{32}", problem_id):
            raise ValueError("题目 ID 无效")
        try:
            self._sync_notebook(problem_id)
        except OSError as error:
            logging.getLogger("algonote").exception("Database saved, but notebook mirror failed")
            raise NotebookSyncError("数据库修改已完成，但题目文件同步失败。请检查 notebook 目录的空间和写入权限，刷新可查看已保存内容；仍可通过导出按钮备份。") from error

    def _sync_notebook(self, problem_id: str):
        # Serialize both the snapshot and the filesystem replacement against all
        # DB writers, including another server process using this SQLite file.
        # A delayed older request therefore always mirrors the newest commit.
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            directory = self.notebook_dir / "problems" / problem_id
            try:
                problem = self._get(db, problem_id)
            except NotFound:
                for name in NOTEBOOK_FILES:
                    (directory / name).unlink(missing_ok=True)
                try:
                    directory.rmdir()
                except FileNotFoundError:
                    pass
                except OSError:
                    # Additional user-created files belong to the user.
                    if directory.exists() and not any(directory.iterdir()):
                        raise
                return
            rows = db.execute("SELECT * FROM explanations WHERE problem_id=? ORDER BY created_at,rowid", (problem_id,)).fetchall()
            files = self._files(problem, [dict(row) for row in rows])
            directory.mkdir(parents=True, exist_ok=True)
            # The metadata file is written last, so a partially failed sync does
            # not first announce a newer revision alongside older source files.
            for name in [n for n in files if n != "problem.json"] + ["problem.json"]:
                fd, tmp = tempfile.mkstemp(dir=directory, prefix=".save-")
                try:
                    with os.fdopen(fd, "w", encoding="utf-8") as f:
                        f.write(files[name])
                    os.replace(tmp, directory / name)
                finally:
                    Path(tmp).unlink(missing_ok=True)
            for name in ("reference.py", "reference.cpp"):
                if name not in files:
                    (directory / name).unlink(missing_ok=True)

    def import_bundle(self, bundle: dict) -> dict:
        """Validate completely before opening a write transaction. Never overwrite existing IDs."""
        if not isinstance(bundle, dict) or not isinstance(bundle.get("problems"), list):
            raise ValueError("导入文件需要包含 problems 数组")
        if len(bundle["problems"]) > 2000:
            raise ValueError("一次最多导入 2000 道题")
        if "format" in bundle and bundle["format"] != "algonote-backup":
            raise ValueError("不支持这个备份格式；普通题目导入请使用仅含 problems 的对象")
        full = bundle.get("format") == "algonote-backup"
        if not full and any(key in bundle for key in ("versions", "explanations", "drafts", "attempts")):
            raise ValueError("包含历史记录的备份需要声明 algonote-backup 格式")
        if full and bundle.get("version") != 1:
            raise ValueError("不支持这个备份版本")
        prepared, ids = [], set()
        stamp = now()
        for raw in bundle["problems"]:
            clean = ProblemInput.model_validate(raw).model_dump()
            pid = raw.get("id", uuid.uuid4().hex)
            if not isinstance(pid, str) or not re.fullmatch(r"[0-9a-f]{32}", pid) or pid in ids:
                raise ValueError("题目 ID 无效或重复")
            ids.add(pid)
            revision = raw.get("revision", 1)
            if type(revision) is not int or not 1 <= revision <= 1_000_000:
                raise ValueError("题目版本无效")
            prepared.append(clean | {"id": pid, "revision": revision, "created_at": _timestamp(raw.get("created_at"), stamp), "updated_at": _timestamp(raw.get("updated_at"), stamp)})
        by_id = {p["id"]: p for p in prepared}
        histories = {key: bundle.get(key, []) if full else [] for key in ("versions", "explanations", "drafts", "attempts")}
        history_ids = {"versions": set(), "explanations": set(), "drafts": set(), "attempts": set()}
        snapshots = {(p["id"], p["revision"]): p for p in prepared}
        for key, items in histories.items():
            if not isinstance(items, list) or len(items) > 100_000:
                raise ValueError(f"{key} 历史数据格式无效")
            validated = []
            for raw_item in items:
                if not isinstance(raw_item, dict) or not isinstance(raw_item.get("problem_id"), str) or raw_item["problem_id"] not in ids:
                    raise ValueError(f"{key} 引用了不存在的题目")
                item = dict(raw_item)
                pid = item["problem_id"]
                rev = item.get("revision" if key == "versions" else "problem_revision")
                if type(rev) is not int or not 1 <= rev <= by_id[pid]["revision"]:
                    raise ValueError(f"{key} 的版本号无效")
                if key == "versions":
                    raw_snapshot = item.get("snapshot", {})
                    snapshot = ProblemInput.model_validate(raw_snapshot).model_dump()
                    if raw_snapshot.get("id", pid) != pid or raw_snapshot.get("revision", rev) != rev:
                        raise ValueError("历史版本快照与题目 ID 或版本号不一致")
                    if rev == by_id[pid]["revision"] and snapshot != ProblemInput.model_validate(by_id[pid]).model_dump():
                        raise ValueError("备份中当前题目与同版本历史快照不一致")
                    item["snapshot"] = snapshot | {"id": pid, "revision": rev, "created_at": _timestamp(raw_snapshot.get("created_at"), stamp), "updated_at": _timestamp(raw_snapshot.get("updated_at"), stamp)}
                    snapshots[(pid, rev)] = item["snapshot"]
                else:
                    if item.get("language") not in ("cpp", "python"):
                        raise ValueError("历史记录包含不支持的编程语言")
                    if key == "explanations":
                        if not isinstance(item.get("content"), str) or len(item["content"]) > 200_000 or not re.fullmatch(r"[0-9a-f]{64}", str(item.get("source_hash", ""))) or item.get("origin") not in ("ai", "manual", "example"):
                            raise ValueError("题解历史格式无效")
                    elif not isinstance(item.get("code"), str) or len(item["code"]) > 60_000:
                        raise ValueError("代码历史格式无效")
                    if key == "attempts":
                        statuses = {"accepted", "wrong_answer", "compile_error", "runtime_error", "time_limit", "output_limit", "runner_unavailable", "no_tests", "infrastructure_error"}
                        if item.get("purpose") not in {"reference", "practice"} or item.get("scope") not in {"samples", "all"} or item.get("status") not in statuses:
                            raise ValueError("提交历史缺少有效的用途、范围或结果状态")
                        if not isinstance(item.get("summary"), str) or not isinstance(item.get("compile_output", ""), str) or not isinstance(item.get("results"), list) or len(item["results"]) > 30:
                            raise ValueError("提交历史结果格式无效")
                        for result in item["results"]:
                            if not isinstance(result, dict) or result.get("status") not in statuses:
                                raise ValueError("提交历史包含无效的测试结果")
                    if key in ("explanations", "attempts") and (not isinstance(item.get("id"), str) or not re.fullmatch(r"[0-9a-f]{32}", item["id"])):
                        raise ValueError("历史记录 ID 无效")
                identity = (pid, rev) if key == "versions" else (pid, item["language"]) if key == "drafts" else item["id"]
                if identity in history_ids[key]:
                    raise ValueError(f"{key} 包含无效或重复的历史记录")
                history_ids[key].add(identity)
                timestamp_key = "updated_at" if key == "drafts" else "created_at"
                item[timestamp_key] = _timestamp(item.get(timestamp_key), stamp)
                validated.append(item)
            histories[key] = validated
        for key in ("explanations", "drafts", "attempts"):
            if any((item["problem_id"], item["problem_revision"]) not in snapshots for item in histories[key]):
                raise ValueError(f"{key} 引用的历史题目版本未包含在备份中")
        imported, skipped = [], 0
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            for p in prepared:
                if db.execute("SELECT 1 FROM problems WHERE id=?", (p["id"],)).fetchone():
                    skipped += 1
                    continue
                self._insert_problem(db, p)
                imported.append(p["id"])
            imported_set = set(imported)
            for key in ("explanations", "attempts"):
                for item in histories[key]:
                    if item["problem_id"] in imported_set and db.execute(f"SELECT 1 FROM {key} WHERE id=?", (item["id"],)).fetchone():
                        raise ValueError("备份的历史记录 ID 与现有记录冲突，本批新题目未导入")
            for item in histories["versions"]:
                if item["problem_id"] in imported_set:
                    db.execute("INSERT OR IGNORE INTO versions VALUES(?,?,?,?)", (item["problem_id"], item["revision"], dumps(item["snapshot"]), str(item.get("created_at", stamp))[:100]))
            for item in histories["explanations"]:
                if item["problem_id"] in imported_set:
                    db.execute("INSERT INTO explanations VALUES(?,?,?,?,?,?,?,?)", tuple(item[k] for k in ("id", "problem_id", "language", "content", "origin", "problem_revision", "source_hash")) + (str(item.get("created_at", stamp))[:100],))
            for item in histories["drafts"]:
                if item["problem_id"] in imported_set:
                    db.execute("INSERT INTO drafts VALUES(?,?,?,?,?)", tuple(item[k] for k in ("problem_id", "language", "code", "problem_revision")) + (str(item.get("updated_at", stamp))[:100],))
            for item in histories["attempts"]:
                if item["problem_id"] in imported_set:
                    db.execute("INSERT INTO attempts VALUES(?,?,?,?)", (item["id"], item["problem_id"], dumps(item), str(item.get("created_at", stamp))[:100]))
        # Retrying a previously committed import after a disk/permission failure
        # must also repair skipped IDs; their current DB content stays authoritative.
        for pid in by_id:
            self.sync_notebook(pid)
        return {"imported": len(imported), "skipped": skipped, "ids": imported}
