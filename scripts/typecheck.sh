#!/usr/bin/env bash
# =============================================================================
# 前端 TypeScript 检查脚本（CI 与本地共用）
#
# 流程：
#   1. bun install（frontend/node_modules 缺失时自动安装）
#   2. bun run typecheck（tsc --noEmit，覆盖全部源码含 build.ts / index.ts）
#
# 用法：
#   bash scripts/typecheck.sh
# =============================================================================

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FRONTEND_DIR="$ROOT/frontend"

if [[ ! -d "$FRONTEND_DIR/node_modules" ]]; then
  echo "==> 安装前端依赖（bun install）..."
  (cd "$FRONTEND_DIR" && bun install)
fi

echo "==> Typecheck (tsc --noEmit) ..."
(cd "$FRONTEND_DIR" && bun run typecheck)

echo ""
echo "✅ TypeScript 类型检查通过"
