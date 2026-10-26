#!/usr/bin/env bash
set -euo pipefail
umask 077
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"

if [[ ! -w . ]]; then
  printf '%s\n' '项目目录不可写。请将项目放在当前账户的可写目录，例如 ~/projects/AlgoNote，再启动。'
  exit 1
fi
if [[ ! -x .venv/bin/python ]]; then
  algonote_python="${ALGONOTE_PYTHON:-python3}"
  "$algonote_python" -c 'import sys; sys.exit(0 if sys.version_info >= (3,11) else "需要 Python 3.11 或更新版本；可用 ALGONOTE_PYTHON 指定解释器")'
  "$algonote_python" -m venv .venv
fi
.venv/bin/python -c 'import sys; sys.exit(0 if sys.version_info >= (3,11) else "项目 .venv 中的 Python 版本过旧，需要 3.11 或更新版本")'
.venv/bin/python -m pip install -r requirements.txt
if [[ ! -f .env ]]; then
  cp .env.example .env
fi

.venv/bin/python -m algonote prepare-runner --optional
.venv/bin/python -m algonote doctor
exec .venv/bin/python -m algonote serve
