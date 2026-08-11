#!/usr/bin/env bash
#
# AmritaBot — WebUI 前端构建脚本（项目顶层入口）
#
# 从 uv 项目根触发前端构建，内部使用 Bun 工具链（frontend/ 的技术栈）。
# 产物输出到 amrita/plugins/webui/service/static/，随 pip 打包分发。
#
# 用法（项目根目录）：
#   bash scripts/build-frontend.sh          # 构建（含类型检查）
#   bash scripts/build-frontend.sh --skip-typecheck   # 跳过类型检查
#   bash scripts/build-frontend.sh --outdir=...       # 自定义输出目录
#
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
FRONTEND_DIR="${ROOT_DIR}/frontend"
DEFAULT_OUTDIR="${ROOT_DIR}/amrita/plugins/webui/service/static"

SKIP_TYPECHECK=0
OUTDIR="${DEFAULT_OUTDIR}"

for arg in "$@"; do
  case "${arg}" in
    --skip-typecheck) SKIP_TYPECHECK=1 ;;
    --outdir=*) OUTDIR="${arg#*=}" ;;
    -h|--help)
      echo "用法: bash scripts/build-frontend.sh [--skip-typecheck] [--outdir=PATH]"
      exit 0
      ;;
  esac
done

if [ ! -d "${FRONTEND_DIR}" ]; then
  echo "❌ 未找到 frontend/ 目录: ${FRONTEND_DIR}" >&2
  exit 1
fi

if [ ! -d "${FRONTEND_DIR}/node_modules" ]; then
  echo "==> 安装前端依赖（bun install）..."
  (cd "${FRONTEND_DIR}" && bun install)
fi

echo "==> 1/2 Typecheck ..."
if [ "${SKIP_TYPECHECK}" -eq 0 ]; then
  (cd "${FRONTEND_DIR}" && bun run typecheck)
fi

echo "==> 2/2 Building WebUI -> ${OUTDIR}"
(cd "${FRONTEND_DIR}" && bun run build.ts \
  --outdir="${OUTDIR}" \
  --splitting \
  --minify \
  --public-path=/static/)

echo ""
echo "✅ WebUI 构建完成: ${OUTDIR}/index.html"
