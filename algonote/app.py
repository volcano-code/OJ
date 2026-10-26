from __future__ import annotations

import hmac
import json
import logging
import sqlite3
import threading
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError

from . import __version__
from .explanations import ExplanationError, ExplanationService
from .inference import infer
from .models import DraftInput, ExplanationRequest, InferRequest, Language, ManualExplanation, ProblemInput, ProblemUpdate, RunRequest, Settings
from .runner import DockerRunner
from .store import Conflict, NotFound, NotebookSyncError, Store

LOGGER = logging.getLogger("algonote")
STATIC = Path(__file__).with_name("static")
MAX_BODY = 16 * 1024 * 1024


def create_app(settings: Settings | None = None, *, runner=None, explanation_service=None) -> FastAPI:
    settings = settings or Settings.from_env()
    store = Store(Path(settings.data_dir) / "algonote.sqlite3", settings.notebook_dir)
    runner = runner or DockerRunner(image=settings.runner_image)
    ai = explanation_service or ExplanationService(base_url=settings.ai_base_url, api_key=settings.ai_api_key, model=settings.ai_model)
    run_slots, ai_slots = threading.BoundedSemaphore(2), threading.BoundedSemaphore(2)
    app = FastAPI(title="AlgoNote 刷题手记", version=__version__, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.store, app.state.settings = store, settings

    @app.middleware("http")
    async def guard(request: Request, call_next):
        is_api = request.url.path.startswith("/api/")
        local_hosts = {"localhost", "127.0.0.1", "::1", "testserver"}
        if not settings.token and request.url.hostname not in local_hosts:
            return JSONResponse({"detail": "非本机访问需要先配置 ALGONOTE_TOKEN"}, status_code=403)
        if is_api and request.url.path != "/api/health" and settings.token:
            expected = "Bearer " + settings.token
            if not hmac.compare_digest(request.headers.get("authorization", "").encode(), expected.encode()):
                return JSONResponse({"detail": "请输入设置的个人访问口令"}, status_code=401)
        if is_api and request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            origin = request.headers.get("origin")
            if origin:
                parts = urlsplit(origin)
                if (parts.scheme, parts.netloc) != (request.url.scheme, request.url.netloc):
                    return JSONResponse({"detail": "不接受来自其他网站的写入请求"}, status_code=403)
            content_length = request.headers.get("content-length", "0")
            if not content_length.isdecimal() or int(content_length) > MAX_BODY:
                return JSONResponse({"detail": "请求内容超过 16 MiB，请分批导入"}, status_code=413)
            # Read the stream with an actual bound; Content-Length is not trusted.
            size, chunks = 0, []
            async for chunk in request.stream():
                size += len(chunk)
                if size > MAX_BODY:
                    return JSONResponse({"detail": "请求内容超过 16 MiB，请分批导入"}, status_code=413)
                chunks.append(chunk)
            request._body = b"".join(chunks)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
        if is_api:
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(NotFound)
    async def not_found(_request, error):
        return JSONResponse({"detail": str(error)}, status_code=404)

    @app.exception_handler(Conflict)
    async def conflict(_request, error):
        return JSONResponse({"detail": str(error)}, status_code=409)

    @app.exception_handler(NotebookSyncError)
    async def mirror_failed(_request, error):
        return JSONResponse({"detail": str(error), "saved_to_database": True}, status_code=507)

    @app.exception_handler(ValueError)
    async def invalid(_request, error):
        return JSONResponse({"detail": str(error)[:1000]}, status_code=422)

    @app.exception_handler(RequestValidationError)
    async def invalid_request(_request, error):
        messages = [e["msg"].replace("Value error, ", "") for e in error.errors()]
        return JSONResponse({"detail": "；".join(dict.fromkeys(messages))[:2000]}, status_code=422)

    @app.exception_handler(ExplanationError)
    async def ai_error(_request, error):
        return JSONResponse({"detail": error.message}, status_code=error.status_code)

    @app.get("/api/health")
    def health():
        return {"status": "ok", "version": __version__, "runner": runner.health(), "ai": {"configured": ai.configured, "model": settings.ai_model}, "auth_required": bool(settings.token)}

    @app.get("/api/problems")
    def list_problems(q: str = "", source: str = "", tag: str = "", mastery: str = ""):
        items = store.list(q=q[:200], source=source, tag=tag, mastery=mastery)
        return {"items": items, "total": len(items)}

    @app.post("/api/problems", status_code=201)
    def create_problem(body: ProblemInput):
        return store.create(body.model_dump())

    @app.get("/api/problems/{problem_id}")
    def get_problem(problem_id: str):
        return store.get(problem_id)

    @app.put("/api/problems/{problem_id}")
    def update_problem(problem_id: str, body: ProblemUpdate):
        return store.update(problem_id, body.model_dump(exclude={"revision"}), body.revision)

    @app.delete("/api/problems/{problem_id}")
    def delete_problem(problem_id: str, revision: int):
        store.delete(problem_id, revision)
        return {"ok": True}

    @app.post("/api/infer")
    def infer_code(body: InferRequest):
        return infer(body.language, body.code)

    @app.get("/api/problems/{problem_id}/versions")
    def list_versions(problem_id: str):
        return {"items": store.versions(problem_id)}

    @app.get("/api/problems/{problem_id}/explanations")
    def list_explanations(problem_id: str):
        return {"items": store.explanations(problem_id)}

    @app.post("/api/problems/{problem_id}/explanations")
    def generate_explanation(problem_id: str, body: ExplanationRequest):
        problem = store.get(problem_id)
        if problem["revision"] != body.revision:
            raise Conflict("题目版本已经变化，请刷新后重新生成")
        if not problem["references"].get(body.language, "").strip():
            raise HTTPException(422, "请先提供这个语言的参考答案")
        if not ai_slots.acquire(blocking=False):
            raise HTTPException(429, "已有题解正在生成，请稍后再试")
        try:
            verification = next((a for a in store.attempts(problem_id) if a["purpose"] == "reference" and a["language"] == body.language and a["problem_revision"] == problem["revision"]), None)
            content = ai.generate(problem, body.language, verification=verification)
            if not content.strip() or len(content) > 200_000:
                raise HTTPException(502, "模型返回的题解为空或过长，请重试")
            return store.save_explanation(problem_id, body.language, content, body.revision, "ai")
        finally:
            ai_slots.release()

    @app.put("/api/problems/{problem_id}/explanations/{language}")
    def save_explanation(problem_id: str, language: Language, body: ManualExplanation):
        return store.save_explanation(problem_id, language, body.content, body.revision, "manual")

    @app.get("/api/problems/{problem_id}/drafts/{language}")
    def get_draft(problem_id: str, language: Language):
        return store.get_draft(problem_id, language)

    @app.put("/api/problems/{problem_id}/drafts/{language}")
    def save_draft(problem_id: str, language: Language, body: DraftInput):
        options = {"expected_updated_at": body.expected_updated_at} if "expected_updated_at" in body.model_fields_set else {}
        return store.save_draft(problem_id, language, body.code, body.problem_revision, **options)

    @app.post("/api/problems/{problem_id}/run")
    def run(problem_id: str, body: RunRequest):
        problem = store.get(problem_id)
        if problem["revision"] != body.revision:
            raise Conflict("题目或测试已更新，请刷新后再运行；练习代码可先保存为草稿")
        code = problem["references"].get(body.language, "") if body.purpose == "reference" else body.code
        if not code.strip():
            raise HTTPException(422, "请先填写代码")
        tests = [t for t in problem["tests"] if body.scope == "all" or t["sample"]]
        if not run_slots.acquire(blocking=False):
            raise HTTPException(429, "已有两次运行正在进行，请稍后再试")
        try:
            if not tests:
                result = {"status": "no_tests", "summary": "当前范围没有测试用例，请先在题目编辑页添加", "results": [], "compile_output": ""}
            else:
                try:
                    result = runner.run(language=body.language, code=code, mode=problem["mode"], signature=problem["signature"], tests=tests, comparison=problem["comparison"])
                except Exception:
                    LOGGER.exception("Execution service failed")
                    result = {"status": "infrastructure_error", "summary": "执行服务发生错误，未作出判题结论，请检查服务后重试", "results": [], "compile_output": ""}
            return store.save_attempt(problem_id, result | {"language": body.language, "code": code, "scope": body.scope, "purpose": body.purpose, "problem_revision": body.revision})
        finally:
            run_slots.release()

    @app.get("/api/problems/{problem_id}/attempts")
    def list_attempts(problem_id: str):
        return {"items": store.attempts(problem_id)}

    @app.get("/api/export")
    def export():
        return Response(store.export_zip(), media_type="application/zip", headers={"Content-Disposition": 'attachment; filename="algonote-backup.zip"'})

    @app.post("/api/import")
    def import_data(body: dict):
        try:
            return store.import_bundle(body)
        except ValidationError as error:
            raise HTTPException(422, "导入题目格式有误：" + "；".join(e["msg"] for e in error.errors())[:1000])
        except (KeyError, TypeError):
            raise HTTPException(422, "备份内容不完整，请使用 AlgoNote 导出的 backup.json")
        except sqlite3.IntegrityError:
            raise HTTPException(422, "备份中的历史记录与现有数据冲突，本次导入已回滚，原数据保持不变")

    @app.get("/")
    def index():
        return FileResponse(STATIC / "index.html")

    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    return app
