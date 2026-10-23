#!/usr/bin/env bash
# Iconify 搜索 / 下载 SVG（免费、20 万+ 图标、统一风格）
# 用法:
#   ./iconify.sh search "wifi" [limit]
#   ./iconify.sh get lucide/wifi out/icon_wifi.svg [64] [#EAF2FF]
set -euo pipefail
case "${1:-}" in
  search)
    q="${2:?usage: iconify.sh search <query> [limit]}"; n="${3:-12}"
    curl -s "https://api.iconify.design/search?query=$(python3 -c "import urllib.parse,sys;print(urllib.parse.quote(sys.argv[1]))" "$q")&limit=$n" \
      | python3 -c "import json,sys;d=json.load(sys.stdin);print('\n'.join(d.get('icons',[])))" ;;
  get)
    icon="${2:?usage: iconify.sh get <prefix/name> <out.svg> [px] [color]}"
    out="${3:?out path}"; px="${4:-64}"; color="${5:-#EAF2FF}"
    # '#' 在 URL 里会被当作 fragment 截断，统一编码成 %23
    case "$color" in \#*) color="%23${color#\#}" ;; esac
    mkdir -p "$(dirname "$out")"
    curl -s "https://api.iconify.design/${icon}.svg?height=${px}&color=${color}" -o "$out"
    echo "saved $out"; head -c 120 "$out"; echo ;;
  *) echo "usage: iconify.sh search|get ..."; exit 2 ;;
esac
