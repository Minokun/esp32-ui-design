#!/usr/bin/env bash
# 安装/更新 esp32-ui-design 技能到 DSH
#
# 单一真源 = 本仓库目录；用软链安装，避免"安装副本与仓库版漂移"。
# 会同时移除旧技能名 ai-art-pipeline（用户级 + 项目级，若存在）。
#
# 用法:
#   ./scripts/install_skill.sh           # 创建/修复软链并校验，移除旧技能
#   ./scripts/install_skill.sh --check   # 只校验，不改动
set -euo pipefail

SKILL_SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
CHECK_ONLY=0
[[ "${1:-}" == "--check" ]] && CHECK_ONLY=1

fail() { echo "✗ $*" >&2; exit 1; }
ok() { echo "✓ $*"; }

# 1) frontmatter: name 必须是 esp32-ui-design，且 kebab-case
SKILL_MD="$SKILL_SRC/SKILL.md"
[[ -f "$SKILL_MD" ]] || fail "缺少 $SKILL_MD"
name="$(/usr/bin/env python3 - "$SKILL_MD" <<'PY'
import re, sys
text = open(sys.argv[1], encoding="utf-8").read()
m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
if not m:
    sys.exit("no frontmatter")
body = m.group(1)
name = re.search(r"^name:\s*(\S+)\s*$", body, re.M)
desc = re.search(r"^description:", body, re.M)
if not name or not desc:
    sys.exit("frontmatter requires name and description")
print(name.group(1))
PY
)" || fail "SKILL.md frontmatter 不合法（DSH 要求 name + description）"
[[ "$name" =~ ^[a-z0-9]+(-[a-z0-9]+)*$ ]] || fail "name 必须是 kebab-case：$name"
[[ "$name" == "esp32-ui-design" ]] || fail "name 必须是 esp32-ui-design，当前是 $name"
ok "frontmatter: name=$name"

# 2) 清理旧技能 ai-art-pipeline（用户级 + 项目级）
for old in "$HOME/.dsh/skills/ai-art-pipeline" "$(pwd -P)/.dsh/skills/ai-art-pipeline"; do
  if [[ -L "$old" ]]; then
    [[ $CHECK_ONLY -eq 1 ]] || { rm "$old"; ok "已删除旧软链: $old"; }
  elif [[ -d "$old" ]]; then
    if [[ $CHECK_ONLY -eq 1 ]]; then
      echo "! 发现旧目录副本（会造成漂移）: $old"
    else
      mv "$old" "$old.bak-$(date +%Y%m%d-%H%M%S)"
      ok "旧目录副本已备份并移除: $old"
    fi
  fi
done

# 3) 安装/修复本技能软链
target="$HOME/.dsh/skills/$name"
if [[ -L "$target" ]]; then
  cur="$(readlink "$target")"
  resolved="$(cd "$(dirname "$target")" && cd "$(dirname "$cur")" 2>/dev/null && cd "$(basename "$cur")" 2>/dev/null && pwd -P || true)"
  if [[ "$cur" == "$SKILL_SRC" || "$resolved" == "$SKILL_SRC" ]]; then
    ok "软链已就绪: $target -> $cur"
  else
    [[ $CHECK_ONLY -eq 1 ]] && fail "软链指向错误: $target -> $cur"
    rm "$target"; ln -s "$SKILL_SRC" "$target"; ok "修复软链: $target -> $SKILL_SRC"
  fi
elif [[ -d "$target" ]]; then
  [[ $CHECK_ONLY -eq 1 ]] && fail "存在旧目录副本: $target"
  mv "$target" "$target.bak-$(date +%Y%m%d-%H%M%S)"
  ln -s "$SKILL_SRC" "$target"; ok "旧副本备份并改为软链: $target"
else
  [[ $CHECK_ONLY -eq 1 ]] && fail "未安装: $target"
  mkdir -p "$(dirname "$target")"
  ln -s "$SKILL_SRC" "$target"; ok "已创建软链: $target -> $SKILL_SRC"
fi

# 4) 关键文件校验
for f in SKILL.md style_bible.md scripts/bake_to_lvgl.py scripts/render_frame.sh scripts/host_render.sh; do
  [[ -r "$SKILL_SRC/$f" ]] || fail "技能缺少文件: $f"
done
ok "关键文件齐全"
echo
echo "完成。DSH 会在新会话/文件变更事件后重新发现技能（name: esp32-ui-design）。"
echo "更新方式：cd $SKILL_SRC && git pull && ./scripts/install_skill.sh"
