#!/usr/bin/env bash
set -euo pipefail

# ── Build Tailwind CSS from source partials ──

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
INPUT="${SCRIPT_DIR}/amrita/plugins/webui/service/static/css/tailwind.css"
OUTPUT="${SCRIPT_DIR}/amrita/plugins/webui/service/static/css/dist.css"

if [ ! -f "${SCRIPT_DIR}/tailwindcss" ]; then
  echo "==> Downloading Tailwind CSS CLI v3.4.19 ..."
  curl -sLo "${SCRIPT_DIR}/tailwindcss" \
    https://github.com/tailwindlabs/tailwindcss/releases/download/v3.4.19/tailwindcss-linux-x64
  chmod +x "${SCRIPT_DIR}/tailwindcss"
fi

echo "==> Building Tailwind CSS ..."
"${SCRIPT_DIR}/tailwindcss" \
  -i "$INPUT" \
  -o "$OUTPUT" \
  --minify

echo "==> Done — ${OUTPUT}"
