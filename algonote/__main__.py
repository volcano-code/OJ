from __future__ import annotations

import argparse
import json
from pathlib import Path

from .models import Settings
from .store import Store


def main():
    parser = argparse.ArgumentParser(description="AlgoNote — 个人刷题手记")
    sub = parser.add_subparsers(dest="command")
    serve = sub.add_parser("serve", help="启动网页")
    serve.add_argument("--host")
    serve.add_argument("--port", type=int)
    importing = sub.add_parser("import", help="导入单题 JSON、题目数组或备份")
    importing.add_argument("file")
    exporting = sub.add_parser("export", help="导出完整备份 ZIP")
    exporting.add_argument("file")
    doctor = sub.add_parser("doctor", help="检查配置、目录权限与代码执行服务")
    doctor.add_argument("--run-check", action="store_true", help="在 Docker 内实际编译执行 C++/Python 的函数和输入输出样例")
    doctor.add_argument("--json", action="store_true", help="输出不含凭据的 JSON 自检报告")
    preparing = sub.add_parser("prepare-runner", help="按当前源代码准备或更新执行镜像")
    preparing.add_argument("--optional", action="store_true", help="Docker 未就绪时允许先使用题库功能")
    args = parser.parse_args()
    settings = Settings.from_env()
    if args.command in (None, "serve"):
        from .app import create_app
        import uvicorn
        host = getattr(args, "host", None) or settings.host
        if host not in {"127.0.0.1", "localhost", "::1"} and not settings.token:
            parser.error("对外提供服务前，请在 .env 中设置 ALGONOTE_TOKEN 个人访问口令")
        uvicorn.run(create_app(settings), host=host, port=getattr(args, "port", None) or settings.port, access_log=False)
        return
    if args.command == "doctor":
        from .diagnostics import diagnose, render_report
        report = diagnose(settings, run_check=args.run_check)
        render_report(report, as_json=args.json)
        raise SystemExit(0 if report["ok"] else 1)
    if args.command == "prepare-runner":
        from .diagnostics import prepare_runner
        result = prepare_runner(settings, optional=args.optional)
        print(result["detail"])
        raise SystemExit(1 if result["status"] == "error" else 0)
    store = Store(Path(settings.data_dir) / "algonote.sqlite3", settings.notebook_dir)
    if args.command == "import":
        path = Path(args.file)
        if path.stat().st_size > 16 * 1024 * 1024:
            parser.error("导入文件超过 16 MiB，请分批导入")
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, list):
            data = {"problems": data}
        elif "problems" not in data:
            data = {"problems": [data]}
        result = store.import_bundle(data)
        print(f"导入 {result['imported']} 道题，跳过已有 ID {result['skipped']} 道题")
    elif args.command == "export":
        path = Path(args.file)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(store.export_zip())
        print(f"已导出：{path.resolve()}")


if __name__ == "__main__":
    main()
