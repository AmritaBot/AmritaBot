#!/usr/bin/env bash
# =============================================================================
# Amrita 一键开发运行脚本
#
# 流程：
#   1. 清理构建产物（scripts/cleanup.sh）
#   2. 构建前端（scripts/build-frontend.sh，含 typecheck）
#   3. 运行后端（uv run ambot run）
#
# 用法：
#   bash scripts/devrun.sh                    # 完整流程（清理 + 构建 + 运行）
#   bash scripts/devrun.sh --skip-clean       # 跳过清理，直接构建 + 运行
#   bash scripts/devrun.sh --skip-typecheck   # 构建时跳过类型检查
#   bash scripts/devrun.sh --no-restart       # 不重启已运行的后端（仅清理 + 构建）
# =============================================================================

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SKIP_CLEAN=false
SKIP_TYPECHECK=false
NO_RESTART=false

for arg in "$@"; do
  case "$arg" in
    --skip-clean) SKIP_CLEAN=true ;;
    --skip-typecheck) SKIP_TYPECHECK=true ;;
    --no-restart) NO_RESTART=true ;;
    *) echo "未知参数: $arg" && exit 1 ;;
  esac
done

echo "🚀 Amrita devrun 启动"
echo "────────────────────────"

# 1. 清理构建产物
if [[ "$SKIP_CLEAN" == false ]]; then
  echo ""
  echo "📦 [1/3] 清理构建产物..."
  bash "$ROOT/scripts/cleanup.sh"
else
  echo ""
  echo "📦 [1/3] 跳过清理（--skip-clean）"
fi

# 2. 构建前端
echo ""
echo "🎨 [2/3] 构建前端..."
BUILD_ARGS=""
if [[ "$SKIP_TYPECHECK" == true ]]; then
  BUILD_ARGS="--skip-typecheck"
fi
bash "$ROOT/scripts/build-frontend.sh" $BUILD_ARGS

# 3. 运行后端
echo ""
echo "🤖 [3/3] 启动后端..."
if [[ "$NO_RESTART" == true ]]; then
  echo "  跳过重启（--no-restart）。前端已就绪。"
  echo "✅ 完成"
  exit 0
fi

# 若有正在运行的后端，先停止（避免端口占用）
if command -v fuser >/dev/null 2>&1 && fuser 11451/tcp >/dev/null 2>&1; then
  echo "  检测到已运行的后端，正在停止..."
  fuser -k 11451/tcp 2>/dev/null || true
  sleep 1
fi

cd "$ROOT"
exec uv run ambot run
