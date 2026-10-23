#!/usr/bin/env bash
# HTML/CSS 设计稿 → 1:1 PNG（无头 Chromium / Playwright）
#
# 用法:
#   ./scripts/render_frame.sh templates/screen_480.html out/screen_480.png [480] [480] [query]
#   ./scripts/render_frame.sh "templates/screen_480.html?mode=bake_bg" out/screen_480_baked_bg.png
#   RENDER_TIMEOUT_MS=3000 ./scripts/render_frame.sh templates/x.html /tmp/x.png
#
# 行为约定（2026-10-23 起）:
#   1. 只做一件事：用真实 Chromium 渲染 HTML，不做任何"降级烘焙"；
#   2. 找不到 Playwright/Chromium 时报错退出（exit 2），不会静默改渲染别的东西；
#   3. 不改写 PATH；可用 PLAYWRIGHT_CLI 显式指定 cli.js 路径；
#   4. 输出路径的父目录会自动创建，并校验输出尺寸符合预期。
set -euo pipefail

RAW_HTML="${1:?usage: render_frame.sh <html[?query]> [out.png] [w] [h] [query]}"
HTML_FILE="${RAW_HTML%%\?*}"
INLINE_QUERY=""
if [[ "$RAW_HTML" == *\?* ]]; then
  INLINE_QUERY="${RAW_HTML#*\?}"
fi
OUT="${2:-${HTML_FILE%.html}.png}"
W="${3:-480}"; H="${4:-480}"
EXTRA_QUERY="${5:-$INLINE_QUERY}"
RENDER_TIMEOUT_MS="${RENDER_TIMEOUT_MS:-2000}"

[[ -f "$HTML_FILE" ]] || { echo "render_frame.sh: HTML 不存在: $HTML_FILE" >&2; exit 2; }

find_playwright_cli() {
  if [[ -n "${PLAYWRIGHT_CLI:-}" && -f "${PLAYWRIGHT_CLI}" ]]; then
    echo "$PLAYWRIGHT_CLI"; return 0
  fi
  local candidates=()
  # 1) 当前 PATH 里的 playwright/npm（不要重排 PATH，否则 nvm 会被 homebrew 顶掉）
  if command -v playwright >/dev/null 2>&1; then
    local pw; pw="$(command -v playwright)"
    candidates+=("$(dirname "$(dirname "$pw")")/lib/node_modules/playwright/cli.js")
  fi
  if command -v npm >/dev/null 2>&1; then
    local root; root="$(npm root -g 2>/dev/null || true)"
    [[ -n "$root" ]] && candidates+=("$root/playwright/cli.js")
  fi
  # 2) 常见安装位置兜底（nvm / homebrew / 系统 node）
  local nvm_root
  for nvm_root in "${NVM_DIR:-$HOME/.nvm}"/versions/node/*/lib/node_modules; do
    candidates+=("$nvm_root/playwright/cli.js")
  done
  candidates+=(
    "/opt/homebrew/lib/node_modules/playwright/cli.js"
    "/usr/local/lib/node_modules/playwright/cli.js"
    "$HOME/Library/pnpm/global/5/node_modules/playwright/cli.js"
  )
  local c
  for c in "${candidates[@]}"; do
    [[ -f "$c" ]] && { echo "$c"; return 0; }
  done
  return 1
}

CLI="$(find_playwright_cli)" || {
  cat >&2 <<'EOF'
render_frame.sh: 找不到可用的 Playwright。
请任选其一修复：
  - npm i -g playwright && npx playwright install chromium
  - 或 export PLAYWRIGHT_CLI=/path/to/node_modules/playwright/cli.js
  - 或先跑 docs/design/art_pipeline/scripts/bake_to_lvgl.py build --python-bake（无浏览器降级路径）
EOF
  exit 2
}

ABS_HTML="$(cd "$(dirname "$HTML_FILE")" && pwd)/$(basename "$HTML_FILE")"
URL="file://$ABS_HTML"
if [[ -n "$EXTRA_QUERY" ]]; then
  URL="${URL}?${EXTRA_QUERY#\?}"
fi

mkdir -p "$(dirname "$OUT")"
node "$CLI" screenshot \
  --viewport-size="${W},${H}" \
  --wait-for-timeout="$RENDER_TIMEOUT_MS" \
  "$URL" "$OUT" >/dev/null

python3 - "$OUT" "$EXTRA_QUERY" "$W" "$H" <<'PY'
import sys
from PIL import Image
p, q, w, h = sys.argv[1], sys.argv[2], int(sys.argv[3]), int(sys.argv[4])
im = Image.open(p)
if im.size != (w, h):
    sys.exit(f"render_frame.sh: 输出尺寸 {im.size} != 期望 {(w, h)}")
print(f"rendered {p}  {im.size[0]}x{im.size[1]}  {len(open(p,'rb').read())/1024:.1f} KB  (query={q or 'default'})")
PY
