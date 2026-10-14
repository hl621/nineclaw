#!/usr/bin/env bash
# 在 WSL 中启动 NineClaw Manager（使用 Linux 虚拟环境，支持远程 Docker SSH）
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export UV_PROJECT_ENVIRONMENT="${UV_PROJECT_ENVIRONMENT:-$HOME/.venvs/nineclaw-manager}"

if ! command -v uv >/dev/null 2>&1; then
  echo "未找到 uv，请先安装: curl -LsSf https://astral.sh/uv/install.sh | sh"
  exit 1
fi

cd "$ROOT"
uv sync
echo "Manager: http://127.0.0.1:8000"
exec uv run run.py
