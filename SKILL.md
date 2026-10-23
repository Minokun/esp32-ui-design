---
name: esp32-ui-design
description: ESP32/LVGL 界面美术与 1:1 上屏工作流（无设计师、AI 出稿）：Chromium 渲染 HTML/CSS 视觉真值 → ?mode=bake_bg 分层烘焙底图 → 8×8 Bayer 抖动 RGB565 → 同源字重 4bpp 字库 → 宿主机真实 LVGL 帧缓冲 1:1 验真（MAE 门禁 + 差分墨迹框 dx/dy 报告）→ 设备端 mmap 零拷贝 + 局部脏区刷新。当用户要做设计稿/界面美化/1:1 复刻/上板还原/新增页面/图标/背景图/动效/素材包/换肤，或提到 art pipeline、美术、素材、生成图片/视频时使用。
---

# esp32-ui-design — ESP32/LVGL 界面美术与 1:1 上屏技能

> 本技能是独立仓库/独立目录，可安装到 `~/.dsh/skills/esp32-ui-design`。
> 它负责「设计 → 资产 → 验真」；**固件工程（`esp32/s31_smooth_demo`）在宿主项目里**，通过 `EVA_PROJECT_ROOT` 指定（或从当前目录自动向上搜索）。

## 何时用

- 要做/改界面设计稿、把 HTML 设计稿 1:1 复刻进 LVGL 固件、新增一个功能页面
- 要出图标、背景图、语音能量球特效、循环视频素材，并打包进固件
- 用户说"太丑了""没设计感""上板之后跟设计稿不一样""圆屏被切边了"

## 七条铁律

1. **HTML/CSS 是唯一视觉真源**：设计稿只写在 `templates/*.html`（480×480，1:1）；要改风格先改 `style_bible.md`，不在 C 代码里凭感觉调。
2. **烘焙必须与真值同源**：用 Chromium 渲染同一份 HTML 的 `?mode=bake_bg` 作为烘焙底图（背景 MAE=0）；`bake_layers.py` 的 Python 方程烘焙只是无浏览器时的降级路径（MAE≈5.9~16.5）。
3. **动态元素必须显式标记**：会由 LVGL 绘制的文字/图标，在 HTML 里加 `data-lvgl="dynamic"` **或** `class="dyn-fg"`（两份模板都支持），`?mode=bake_bg` 才会隐藏它们；否则底图会"印死"文字。
4. **MCU 不实时做重计算**：禁止实时高斯模糊/多重径向渐变/大光晕，这些一律烘进底图；设备端只叠文字、贴小图、刷局部脏区。
5. **RGB565 必须 8×8 Bayer 有序抖动**，禁止直接截断低位（暗部极光会出水波纹色带）。
6. **字重必须对齐 CSS**：`bake_to_lvgl.py` 按 `font-weight` 选 Avenir/Hiragino face（300/400/500/600/700）；改字体/字号要同步改 `font_specs()`。
7. **坐标用差分墨迹框校正**：跑 `compare` 拿 `metrics.json.regions[].dx/dy`，改固件 `lvgl_ui.c` 的 `lv_obj_set_pos`，重跑直到 0 偏移；禁止直接抄 CSS 的 `top/left`（含半行距）。
8. **动态文案必须落在字体字符表内**：4bpp 字库是子集字体，任意中文回复直接 `lv_label_set_text` 到子集字体的 label 会整行变豆腐块（实测把 WS 原文塞进 23px 标题 = 一整行方框）。状态文案只用固定字表里的串，或改用覆盖面足够的字体。

## 目录

```
SKILL.md / style_bible.md / README.md
templates/screen_480.html        主表盘 480×480 设计真值稿（?mode=bake_bg / ?shape=circle / ?debug=safe_area）
templates/screen_menu_480.html   控制中心菜单设计真值稿（?mode=bake_bg）
templates/space_480.html         ASTRO 深空宇航员单页（圆屏安全区；?mode=bake_bg&warp=1 出跃迁变体）
scripts/bake_to_lvgl.py          主入口：build（Chromium 真值/烘焙 + RGB565 + 字库）/ compare（看板+metrics+门禁）
scripts/host_render.sh           找到宿主项目的 host_render 并渲染真实 LVGL 帧缓冲
scripts/bake_space_asset.py      EVA4 资产替换示例：新页背景(正常+跃迁)替换进 eva bin，保留 orb 帧
scripts/bake_layers.py           纯 Python 降级烘焙 + 圆屏设计稿生成
scripts/render_frame.sh          HTML → 480×480 PNG（Playwright/Chromium；找不到浏览器明确报错）
scripts/gen_lvgl_font.py         单字体 4bpp 字库生成器
scripts/render_shader_vfx.py     四态语音球 NumPy 烘焙器（96 帧 / 1.2s）
scripts/render_shader_vfx.cjs    WebGL 版（headless 无 webgl2，实验性）
scripts/pack_frames.py           帧序列 → GPJM media.bin（Baseline 校验 + CRC32 + crossfade）
scripts/validate_frame.py        diff / 体积 / 圆屏门禁
scripts/iconify.sh               Iconify 搜索/下载 SVG（颜色参数自动 URL 编码）
scripts/svg2png.cjs              SVG → PNG
scripts/gen_image.py             百炼 Qwen-Image（默认 dry-run）
scripts/gen_video.py             百炼 Wan（默认 dry-run）
scripts/install_skill.sh         安装/更新本技能到 DSH（软链，移除旧 ai-art-pipeline）
out/                             所有产物 + metrics.json + build.json（git 忽略）
```

## 环境

- Python 3.10+：`numpy`、`Pillow`
- Node + Playwright：`npm i -g playwright && npx playwright install chromium`（或 `export PLAYWRIGHT_CLI=...`）
- `ffmpeg`（视频抽帧时）
- 字体：默认 macOS 系统字体（DIN Condensed Bold / Avenir Next / Hiragino Sans GB）。**出货必须换可商用字体**，可用 `EVA_FONT_DIN/EVA_FONT_AVENIR/EVA_FONT_HIRA` 指向自有字体。

## 标准 SOP（改完设计稿后的 3 条命令）

```bash
SKILL_DIR="$(cd ~/.dsh/skills/esp32-ui-design 2>/dev/null && pwd -P || cd "$(dirname "$0")" && pwd -P)"
cd "$SKILL_DIR"

# 固件工程根目录（会话 CWD 已经是 edge_voice_assistant 时可省略）
export EVA_PROJECT_ROOT=/path/to/edge_voice_assistant

# ① 渲染真值 + 烘焙底图 + 编译 RGB565 资产/字库（写到 <EVA_PROJECT_ROOT>/esp32/s31_smooth_demo/main/）
./scripts/bake_to_lvgl.py build

# ② 宿主机跑真实 LVGL 9.5 + 真 lvgl_ui.c，导出 RGB565 帧缓冲（秒级）
./scripts/host_render.sh out

# ③ 每页三联看板 + metrics.json + MAE 门禁（>12/255 exit 1，禁止上板）
./scripts/bake_to_lvgl.py compare
```

- 只评估不落盘：`build --dry-run`（干净目录也可用，缺失输入会临时渲染到 `/tmp`）
- 无浏览器降级：`build --bake-source python`（真值图仍需 Chromium）
- 上板：`"$EVA_PROJECT_ROOT/esp32/s31_smooth_demo/flash_menu_ui.sh"`（需要设备串口）

## 新增 / 修改页面

修改现有页面：改 `templates/*.html` → 3 条命令 → 按 `metrics.json.regions[].dx/dy` 修 `lvgl_ui.c` 坐标 → 门禁通过。

**新增页面**（本技能不生成布局 C，需要手写）：
1. 复制 `templates/screen_480.html`（或 `screen_menu_480.html`）→ `templates/<page>.html`，改 CSS；动态元素打 `data-lvgl="dynamic"` 或 `class="dyn-fg"`；
2. 在 `bake_to_lvgl.py` 的 `PAGES` 表登记（html / truth / baked / lvgl 文件名 + card_box）；
3. 在固件 `esp32/s31_smooth_demo/main/lvgl_ui.c` 写 `build_<page>()`：贴烘焙底图 + 摆动态控件；
4. 在 `host_render/render_main.c` 加渲染入口，输出 `<page>_lvgl.png`；
5. 在页面注册表 / `app_ui` 挂导航入口；
6. build → render → compare 迭代到门禁通过。

## 产物与指标

- `out/<page>_html_vs_lvgl_1to1.png`：每页三联看板（真值 / LVGL / |diff|×4 热力图）；`html_vs_lvgl_1to1.png` 是 home 兼容名
- `out/metrics.json`：每页 MAE/还原度/PSNR/≤1 阶比例/逐区域 dx-dy/门禁结果
- `out/build.json`：资产体积、sha256、字库位图大小、脏区占比
- 固件侧：`main/assets/eva_face3.bin`（EVA4：2×480×480 RGB565 + 16×88×88 RGB565A8）、`main/fonts/ui_font_eva_pack.c`（11 档 4bpp）
- 基线（`edge_voice_assistant`，2026-10-23）：主表盘 MAE 5.27 / 97.94%，菜单 3.71 / 98.55%；S31 实机渲染循环 ~18ms、动画 20~21fps、flush 8,040px/帧

## 常见坑

- 找不到 Playwright：显式 `export PLAYWRIGHT_CLI=.../playwright/cli.js` 或全局安装；`render_frame.sh` 会直接报错，不会静默改渲染别的东西。
- `bake_to_lvgl.py` 未知参数会被 argparse 拒绝（exit 2），不会误跑生产管线；担心误写固件资产用 `--dry-run`。
- 模板里加 CSS 动画会导致渲染不确定；烘焙用模板请保持静态。
- macOS 系统字体只适合本地验证；`/tmp/pylibs`（pypng/lz4）是临时方案，建议项目内 `pip install --target`。
- `templates/shader_orb.html` + `render_shader_vfx.cjs` 的 WebGL 路径在 headless 下不可用；正式特效走 `render_shader_vfx.py`。
- 单页替换（例如整机只留 ASTRO 深空页）：改 `templates/space_480.html` → `render_frame.sh` 出正常/跃迁两张烘焙图 → `bake_space_asset.py` 替换 eva bin 的 bg0/bg1（orb 帧沿用）→ 固件只 build 这一页；参考 assets/astro_page_device_fb.png。

## 安装 / 更新本技能

```bash
./scripts/install_skill.sh          # 软链到 ~/.dsh/skills/esp32-ui-design，并移除旧 ai-art-pipeline
./scripts/install_skill.sh --check  # 只校验
```
