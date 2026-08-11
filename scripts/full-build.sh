#!/usr/bin/env bash
# =============================================================================
# Amrita 完整构建脚本
#
# 流程：
#   1. 清理构建产物（scripts/cleanup.sh）
#   2. 构建前端（scripts/build-frontend.sh，含 typecheck）→ static/
#   3. 构建后端（uv build）→ dist/（wheel + sdist）
#
# 用法：
#   bash scripts/full-build.sh                  # 完整流程
#   bash scripts/full-build.sh --skip-typecheck # 构建前端时跳过类型检查
# =============================================================================

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SKIP_TYPECHECK=false

for arg in "$@"; do
  case "$arg" in
    --skip-typecheck) SKIP_TYPECHECK=true ;;
    *) echo "未知参数: $arg" && exit 1 ;;
  esac
done

echo "🏗️  Amrita full-build 启动"
echo "──────────────────────────"

# 1. 清理构建产物
echo ""
echo "📦 [1/3] 清理构建产物..."
bash "$ROOT/scripts/cleanup.sh"

# 2. 构建前端
echo ""
echo "🎨 [2/3] 构建前端..."
BUILD_ARGS=""
if [[ "$SKIP_TYPECHECK" == true ]]; then
  BUILD_ARGS="--skip-typecheck"
fi
bash "$ROOT/scripts/build-frontend.sh" $BUILD_ARGS

# 3. 构建后端（wheel + sdist）
echo ""
echo "🐍 [3/3] 构建后端包（uv build）..."
cd "$ROOT"
uv build

echo ""
echo "✅ full-build 完成"
echo "   - 前端产物: amrita/plugins/webui/service/static/"
echo "   - 后端包:   dist/（wheel + sdist）"
