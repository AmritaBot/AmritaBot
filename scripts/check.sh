#!/usr/bin/env bash
# =============================================================================
# Amrita CI 检查脚本（GitHub Actions 入口）
#
# 流程（按顺序，任一失败即中止）：
#   1. uv run pyright              —— Python 类型检查
#   2. bash scripts/lint.sh --check —— 代码质量检查（ruff + prettier + tailwind）
#   3. bash scripts/full-build.sh  —— 完整构建（前端 typecheck + 构建 + uv build）
#
# 用法：
#   bash scripts/check.sh                    # 完整 CI 检查
#   bash scripts/check.sh --skip-build       # 跳过构建（仅类型 + lint）
# =============================================================================

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SKIP_BUILD=false
if [[ "${1:-}" == "--skip-build" ]]; then
  SKIP_BUILD=true
  echo "🔍 跳过构建（--skip-build）"
fi

cd "$ROOT"

echo ""
echo "1️⃣  pyright"
uv run pyright
echo "  ✅ pyright 通过"

echo ""
echo "2️⃣  lint (ruff + prettier + tailwindcss)"
bash "$ROOT/scripts/lint.sh" --check

if [[ "$SKIP_BUILD" == true ]]; then
  echo ""
  echo "🎉 检查通过（已跳过构建）"
  exit 0
fi

echo ""
echo "3️⃣  full build (frontend typecheck + build + uv build)"
bash "$ROOT/scripts/full-build.sh"

echo ""
echo "🎉 全部检查通过"
