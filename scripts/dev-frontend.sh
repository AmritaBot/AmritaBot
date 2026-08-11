#!/usr/bin/env bash
# =============================================================================
# Amrita 前端开发环境一键启动脚本
#
# 流程：
#   1. 清理构建产物（scripts/cleanup.sh）
#   2. 后台启动后端（uv run ambot run）
#   3. 前台启动前端 dev server（bun run dev，含 /api 代理与 WS 桥接）
#   4. 退出（Ctrl+C / 关闭终端）时自动杀死后端进程
#
# 用法：
#   bash scripts/dev-frontend.sh          # 完整流程
#   bash scripts/dev-frontend.sh --skip-clean   # 跳过清理
# =============================================================================

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SKIP_CLEAN=false
BACKEND_PID=""

for arg in "$@"; do
  case "$arg" in
    --skip-clean) SKIP_CLEAN=true ;;
    *) echo "未知参数: $arg" && exit 1 ;;
  esac
done

# 退出时清理：杀死后台后端（前端 bun run dev 前台运行，Ctrl+C 时随脚本一起结束）
cleanup() {
  if [[ -n "$BACKEND_PID" ]] && kill -0 "$BACKEND_PID" 2>/dev/null; then
    echo ""
    echo "🧹 停止后端 (PID $BACKEND_PID)..."
    kill "$BACKEND_PID" 2>/dev/null || true
    wait "$BACKEND_PID" 2>/dev/null || true
  fi
  echo "👋 已退出"
}
trap cleanup EXIT INT TERM

echo "🚀 Amrita dev 环境启动"
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

# 2. 后台启动后端（先释放 11451 端口）
echo ""
echo "🤖 [2/3] 启动后端 (uv run ambot run)..."
if command -v fuser >/dev/null 2>&1 && fuser 11451/tcp >/dev/null 2>&1; then
  echo "  检测到已运行的后端，正在停止..."
  fuser -k 11451/tcp 2>/dev/null || true
  sleep 1
fi
cd "$ROOT"
uv run ambot run &
BACKEND_PID=$!
echo "  后端 PID: $BACKEND_PID"

# 等待后端就绪（最多 60s）
echo "  等待后端就绪..."
for _ in $(seq 1 60); do
  if curl -s -o /dev/null --max-time 1 http://127.0.0.1:11451/ 2>/dev/null; then
    echo "  ✅ 后端已就绪 (http://127.0.0.1:11451)"
    break
  fi
  if ! kill -0 "$BACKEND_PID" 2>/dev/null; then
    echo "  ❌ 后端启动失败，查看上方日志"
    exit 1
  fi
  sleep 1
done

# 3. 前台启动前端 dev server（Ctrl+C 退出时 trap 清理后端）
echo ""
echo "🎨 [3/3] 启动前端 dev server (bun run dev)..."
echo "  访问 http://localhost:3000  (API/WS 代理到 127.0.0.1:11451)"
echo "  Ctrl+C 退出并停止后端"
echo "────────────────────────"
cd "$ROOT/frontend"
bun run dev
