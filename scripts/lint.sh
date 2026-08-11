#!/usr/bin/env bash
# =============================================================================
# Amrita 代码质量检查脚本
#
# 流程（按顺序，任一失败即中止）：
#   1. uv run ruff check          —— Python lint（静态检查）
#   2. uv run ruff format .       —— Python 格式化（幂等，格式化后无 diff）
#   3. prettier frontend/         —— 前端格式化（--check 验证，--write 修复）
#   4. tailwindcss 编译检查       —— CSS lint（验证 Tailwind v4 语法/类检测可编译）
#
# 用法：
#   bash scripts/lint.sh          # 完整检查（prettier 会实际修复格式）
#   bash scripts/lint.sh --check  # 只检查不修改（prettier 用 --check，ruff 仅 format --check）
# =============================================================================

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CHECK_ONLY=false
if [[ "${1:-}" == "--check" ]]; then
  CHECK_ONLY=true
  echo "🔍 检查模式（--check）：只报告不修改"
fi

cd "$ROOT"

echo ""
echo "1️⃣  ruff check"
uv run ruff check .
echo "  ✅ ruff check 通过"

echo ""
echo "2️⃣  ruff format"
if [[ "$CHECK_ONLY" == true ]]; then
  uv run ruff format --check .
else
  uv run ruff format .
fi
echo "  ✅ ruff format 通过"

echo ""
echo "3️⃣  prettier (frontend/)"
cd "$ROOT/frontend"
if [[ "$CHECK_ONLY" == true ]]; then
  bunx prettier --check .
else
  bunx prettier --write .
fi
echo "  ✅ prettier 通过"

echo ""
echo "4️⃣  tailwindcss 编译检查 (CSS lint)"
# 编译 globals.css 到临时文件，验证 Tailwind v4 语法与类检测可正常编译
bunx tailwindcss -i styles/globals.css -o /tmp/amrita-tailwind-lint.css --minify
rm -f /tmp/amrita-tailwind-lint.css
echo "  ✅ tailwindcss 编译通过"

echo ""
echo "🎉 全部检查通过"
