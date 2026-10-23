#!/usr/bin/env bash
# 在宿主项目里调用真实的 LVGL 宿主机渲染器（esp32/s31_smooth_demo/host_render/render.sh）
#
# 用法:
#   ./scripts/host_render.sh [输出目录]     # 默认用本技能目录下的 out/
#
# 项目根定位顺序：
#   1. $EVA_PROJECT_ROOT
#   2. 当前工作目录向上搜索 esp32/s31_smooth_demo/host_render
#   3. 本技能目录向上搜索（技能放在项目内时）
set -euo pipefail

SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
OUT="${1:-$SKILL_DIR/out}"
mkdir -p "$OUT"
OUT_ABS="$(cd "$OUT" && pwd -P)"

find_project_root() {
  local seeds=()
  [[ -n "${EVA_PROJECT_ROOT:-}" ]] && seeds+=("$(cd "$EVA_PROJECT_ROOT" && pwd -P)")
  seeds+=("$(pwd -P)" "$SKILL_DIR")
  local seed base
  for seed in "${seeds[@]}"; do
    base="$seed"
    while :; do
      [[ -x "$base/esp32/s31_smooth_demo/host_render/render.sh" ]] && { echo "$base"; return 0; }
      [[ "$base" == "/" ]] && break
      base="$(dirname "$base")"
    done
  done
  return 1
}

ROOT="$(find_project_root)" || {
  cat >&2 <<'EOF'
host_render.sh: 找不到固件工程（需要 <project>/esp32/s31_smooth_demo/host_render/render.sh）。
请设置：export EVA_PROJECT_ROOT=/path/to/edge_voice_assistant
EOF
  exit 2
}

echo "[host_render] project=$ROOT  out=$OUT_ABS"
exec "$ROOT/esp32/s31_smooth_demo/host_render/render.sh" "$OUT_ABS"
