#!/usr/bin/env bash
# =============================================================================
# Amrita WebUI 构建产物清理脚本
#
# 清理内容：
#   1. amrita/plugins/webui/service/static/    —— 前端构建产物（.js/.css/.html/.map）
#   2. frontend/dist/                          —— build:local 本地构建输出
#   3. dist/                                   —— uv build 后端包输出（wheel + sdist）
#   4. build/ 与 *.egg-info                    —— Python 包构建中间产物与元数据
#   5. logs/realtime.jsonl                     —— 实时日志临时文件（下次启动自动重建）
#
# 用法：
#   bash scripts/cleanup.sh            # 执行清理
#   bash scripts/cleanup.sh --dry-run  # 仅列出将删除的内容，不实际删除
# =============================================================================

set -euo pipefail

# 项目根目录（脚本位于 <root>/scripts/）
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

DRY_RUN=false
if [[ "${1:-}" == "--dry-run" ]]; then
  DRY_RUN=true
  echo "🔍 预演模式（--dry-run）：仅列出将删除的内容"
fi

TARGETS=(
  "$ROOT/amrita/plugins/webui/service/static"
  "$ROOT/frontend/dist"
  "$ROOT/dist"
  "$ROOT/build"
)

# 查找所有 .egg-info 目录（构建元数据）
mapfile -t EGG_INFOS < <(find "$ROOT" -maxdepth 2 -type d -name "*.egg-info" 2>/dev/null || true)
TARGETS+=("${EGG_INFOS[@]}")

# 实时日志临时文件（仅保留 git 中的 event.json 等追溯数据）
REALTIME_LOG="$ROOT/logs/realtime.jsonl"
if [[ -f "$REALTIME_LOG" ]]; then
  TARGETS+=("$REALTIME_LOG")
fi

rm_target() {
  local target="$1"
  if [[ ! -e "$target" ]]; then
    return
  fi
  # 保护 static/images（logo 资源，git 跟踪）
  if [[ "$target" == "$ROOT/amrita/plugins/webui/service/static" ]]; then
    find "$target" -mindepth 1 -maxdepth 1 ! -name "images" -exec rm -rf {} +
    if [[ "$DRY_RUN" == true ]]; then
      echo "  🗑️  将删除: amrita/plugins/webui/service/static/（保留 images/）"
    else
      echo "  🗑️  已删除: amrita/plugins/webui/service/static/（保留 images/）"
    fi
    return
  fi
  if [[ "$DRY_RUN" == true ]]; then
    echo "  🗑️  将删除: ${target#$ROOT/}"
  else
    rm -rf "$target"
    echo "  🗑️  已删除: ${target#$ROOT/}"
  fi
}

echo ""
echo "📦 Amrita 构建产物清理"
echo "────────────────────────"
COUNT=0
for t in "${TARGETS[@]}"; do
  if [[ -n "$t" && -e "$t" ]]; then
    rm_target "$t"
    COUNT=$((COUNT + 1))
  fi
done

if [[ "$COUNT" -eq 0 ]]; then
  echo "  ✅ 没有需要清理的构建产物"
else
  echo "────────────────────────"
  if [[ "$DRY_RUN" == true ]]; then
    echo "  共 $COUNT 项将被清理（运行 bash scripts/cleanup.sh 实际执行）"
  else
    echo "  已清理 $COUNT 项构建产物"
  fi
fi

# 重新创建 static 目录（保持目录结构，避免后端挂载报错）
if [[ "$DRY_RUN" == false ]]; then
  mkdir -p "$ROOT/amrita/plugins/webui/service/static"
fi
# 确保 images 存在（logo 静态资源，git 跟踪）
mkdir -p "$ROOT/amrita/plugins/webui/service/static/images"
echo "✅ 完成"
