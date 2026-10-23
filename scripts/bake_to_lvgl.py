#!/usr/bin/env python3
"""
bake_to_lvgl.py — HTML/CSS 设计稿 → LVGL 9.5 RGB565 资产编译 + 1:1 像素验真

子命令：
  build
    ① Chromium 渲染 480x480 真值图（screen_480.png / screen_menu_480.png）
    ② Chromium 渲染 ?mode=bake_bg 分层烘焙底图（与真值像素级同源；无浏览器时降级 python 方程烘焙）
    ③ RGB888→RGB565 8x8 Bayer 有序抖动 + 16 帧 88x88 麦克风能量球 → eva_face3.bin (EVA4)
    ④ 同源 Avenir/Hiragino 字库（字重与 CSS font-weight 对齐）→ ui_font_eva_pack.c
    产物同时写 out/build.json（体积 / sha256 / 字体位图大小），供文档引用、避免手抄数字漂移。

  compare
    ① 生成 out/html_vs_lvgl_1to1.png 三联看板（真值 / LVGL 真实 RGB565 帧缓冲 / 4x 误差热力图）
    ② 差分墨迹框逐区域偏移报告（dx/dy，用于把 lvgl_ui.c 的坐标修到 1:1）
    ③ 写 out/metrics.json 并执行 MAE 门禁（默认 <= 12/255，超限 exit 1，禁止盲上板）

改完 HTML 模板后的标准闭环（3 条命令）：
  ./scripts/bake_to_lvgl.py build
  ../../esp32/s31_smooth_demo/host_render/render.sh out
  ./scripts/bake_to_lvgl.py compare
"""
import argparse
import hashlib
import json
import math
import os
import shutil
import struct
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

SCRIPT_DIR = Path(__file__).resolve().parent
PIPE_DIR = SCRIPT_DIR.parent
REPO_ROOT = PIPE_DIR.parent.parent.parent


def find_demo_main() -> Path:
    """定位 ESP32-S31 固件工程目录（esp32/s31_smooth_demo/main）。

    技能可以作为独立仓库安装（例如 ~/.dsh/skills/esp32-ui-design），此时在技能
    目录里向上找不到固件工程，因此支持：
      1. EVA_PROJECT_ROOT=<edge_voice_assistant 根目录>（或 EVA_DEMO_MAIN=<main 目录>）
      2. 从当前工作目录向上搜索 esp32/s31_smooth_demo/main
      3. 从技能目录向上搜索（技能放在项目内时）
    """
    env_root = os.environ.get("EVA_PROJECT_ROOT")
    env_main = os.environ.get("EVA_DEMO_MAIN")
    if env_main:
        m = Path(env_main).expanduser().resolve()
        if (m / "assets").is_dir() or m.name == "main":
            return m
    seeds: list[Path] = []
    if env_root:
        seeds.append(Path(env_root).expanduser().resolve())
    seeds += [Path.cwd().resolve(), PIPE_DIR.resolve()]
    for seed in seeds:
        for base in (seed, *seed.parents):
            cand = base / "esp32" / "s31_smooth_demo" / "main"
            if cand.is_dir():
                return cand
    return REPO_ROOT / "esp32" / "s31_smooth_demo" / "main"

sys.path.insert(0, str(SCRIPT_DIR))
from gen_lvgl_font import render_glyph_4bpp, pack_nibbles
from bake_layers import make_exact_css_baked_bg, make_exact_menu_baked_bg


def rgb888_to_rgb565_trunc(rgb: np.ndarray) -> np.ndarray:
    r = rgb[..., 0].astype(np.uint16)
    g = rgb[..., 1].astype(np.uint16)
    b = rgb[..., 2].astype(np.uint16)
    return ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)


def rgb565_to_rgb888(c565: np.ndarray) -> np.ndarray:
    r5 = (c565 >> 11) & 0x1F
    g6 = (c565 >> 5) & 0x3F
    b5 = c565 & 0x1F
    r8 = ((r5 * 255 + 15) // 31).astype(np.uint8)
    g8 = ((g6 * 255 + 31) // 63).astype(np.uint8)
    b8 = ((b5 * 255 + 15) // 31).astype(np.uint8)
    return np.stack([r8, g8, b8], axis=-1)


def rgb888_to_rgb565_dither(rgb: np.ndarray) -> np.ndarray:
    bayer2 = np.array([[0, 2], [3, 1]], dtype=np.float32)
    bayer4 = np.block([[4 * bayer2 + 0, 4 * bayer2 + 2], [4 * bayer2 + 3, 4 * bayer2 + 1]])
    bayer8 = (
        np.block([[4 * bayer4 + 0, 4 * bayer4 + 2], [4 * bayer4 + 3, 4 * bayer4 + 1]]) / 64.0
        - 0.5
    )
    h, w, _ = rgb.shape
    tiled = np.tile(bayer8, (h // 8 + 1, w // 8 + 1))[:h, :w]

    f = rgb.astype(np.float32)
    r5 = np.clip(np.rint((f[..., 0] + tiled * 7.5) * 31.0 / 255.0), 0, 31).astype(np.uint16)
    g6 = np.clip(np.rint((f[..., 1] + tiled * 3.8) * 63.0 / 255.0), 0, 63).astype(np.uint16)
    b5 = np.clip(np.rint((f[..., 2] + tiled * 7.5) * 31.0 / 255.0), 0, 31).astype(np.uint16)
    return (r5 << 11) | (g6 << 5) | b5


def draw_mic_icon_rgba(size: int = 88, scale_icon: float = 1.0) -> Image.Image:
    ss = 4
    S = size * ss
    im = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    cx, cy = S * 0.5, S * 0.5
    u = ss * scale_icon
    ox = cx - 12.0 * u
    oy = cy - 13.0 * u
    ink = (6, 18, 28, 255)

    d.rounded_rectangle([ox + 8 * u, oy + 1 * u, ox + 16 * u, oy + 14 * u], radius=int(4 * u), fill=ink)
    sw = max(2, int(round(2.1 * u)))
    d.arc([ox + 4 * u, oy + 3.5 * u, ox + 20 * u, oy + 19.5 * u], start=0, end=180, fill=ink, width=sw)
    rc = sw * 0.48
    for px, py in [(ox + 4 * u, oy + 11.5 * u), (ox + 20 * u, oy + 11.5 * u)]:
        d.ellipse([px - rc, py - rc, px + rc, py + rc], fill=ink)
    d.line([(ox + 12 * u, oy + 19.5 * u), (ox + 12 * u, oy + 23.5 * u)], fill=ink, width=sw)
    for px, py in [(ox + 12 * u, oy + 19.5 * u), (ox + 12 * u, oy + 23.5 * u)]:
        d.ellipse([px - rc, py - rc, px + rc, py + rc], fill=ink)

    return im.resize((size, size), Image.Resampling.BOX)


def make_mic_orb_frame(size: int = 88, frame_idx: int = 0, total_frames: int = 16) -> np.ndarray:
    yy, xx = np.mgrid[0:size, 0:size].astype(np.float32)
    cx, cy = size * 0.5, size * 0.5
    phi = 2.0 * math.pi * frame_idx / total_frames

    pulse = 1.0 if frame_idx == 0 else (1.0 + 0.045 * math.sin(phi))
    r_sphere = 28.0 * pulse
    dist = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2)

    glow_rad = 11.0 * (1.0 if frame_idx == 0 else (1.0 + 0.14 * math.sin(phi)))
    disk_im = Image.new("L", (size, size), 0)
    r_i = int(round(r_sphere))
    ImageDraw.Draw(disk_im).ellipse([cx - r_i, cy - r_i, cx + r_i, cy + r_i], fill=255)
    glow_blur = np.asarray(disk_im.filter(ImageFilter.GaussianBlur(radius=glow_rad)), dtype=np.float32) / 255.0
    edge_fade = np.clip((size * 0.5 - 1.5 - dist) / 7.0, 0.0, 1.0)
    glow_a = glow_blur * (0.58 if frame_idx == 0 else (0.58 + 0.10 * math.sin(phi))) * edge_fade

    out_rgb = np.zeros((size, size, 3), dtype=np.float32)
    out_a = np.zeros((size, size), dtype=np.float32)

    glow_col = np.array([53.0, 224.0, 255.0], dtype=np.float32) / 255.0
    out_rgb[:] = glow_col[None, None, :]
    out_a[:] = glow_a

    sphere_cov = np.clip(r_sphere + 0.5 - dist, 0.0, 1.0)
    fx = cx - r_sphere + 2.0 * r_sphere * 0.34
    fy = cy - r_sphere + 2.0 * r_sphere * 0.28
    rd = np.sqrt((xx - fx) ** 2 + (yy - fy) ** 2) / (r_sphere * 1.42)
    if frame_idx > 0:
        ang = np.arctan2(yy - cy, xx - cx)
        wave = 0.07 * np.sin(3.0 * ang - phi) + 0.05 * np.cos(4.0 * rd - phi)
        rd = np.clip(rd + wave, 0.0, 1.0)
    else:
        rd = np.clip(rd, 0.0, 1.0)

    c0 = np.array([0x8C, 0xF6, 0xFF], dtype=np.float32) / 255.0
    c1 = np.array([0x2A, 0xD4, 0xF0], dtype=np.float32) / 255.0
    c2 = np.array([0x0C, 0x86, 0xA8], dtype=np.float32) / 255.0

    m_low = rd <= 0.42
    t_low = np.clip(rd / 0.42, 0.0, 1.0)[..., None]
    t_hi = np.clip((rd - 0.42) / 0.58, 0.0, 1.0)[..., None]
    s_rgb = np.where(m_low[..., None], c0 * (1.0 - t_low) + c1 * t_low, c1 * (1.0 - t_hi) + c2 * t_hi)

    rim = np.clip(1.0 - np.abs(dist - (r_sphere - 0.8)), 0.0, 1.0) * np.clip((cy - yy) / r_sphere, 0.0, 1.0) * 0.48
    s_rgb = s_rgb * (1.0 - rim[..., None]) + 1.0 * rim[..., None]

    sa = sphere_cov
    da = out_a
    oa = sa + da * (1.0 - sa)
    eps = 1e-6
    out_rgb = np.where(
        oa[..., None] > eps,
        (s_rgb * sa[..., None] + out_rgb * da[..., None] * (1.0 - sa[..., None])) / np.maximum(oa[..., None], eps),
        0.0,
    )
    out_a = oa

    mic_im = draw_mic_icon_rgba(size=size, scale_icon=1.0)
    mic_arr = np.asarray(mic_im, dtype=np.float32) / 255.0
    ma = mic_arr[..., 3]
    oa2 = ma + out_a * (1.0 - ma)
    out_rgb = np.where(
        oa2[..., None] > eps,
        (mic_arr[..., :3] * ma[..., None] + out_rgb * out_a[..., None] * (1.0 - ma[..., None]))
        / np.maximum(oa2[..., None], eps),
        0.0,
    )
    out_a = oa2

    res = np.zeros((size, size, 4), dtype=np.float32)
    res[..., :3] = np.clip(out_rgb, 0.0, 1.0)
    res[..., 3] = np.clip(out_a, 0.0, 1.0)
    return res


def rgba_to_rgb565a8_bytes(rgba01: np.ndarray) -> bytes:
    a8 = np.clip(np.rint(rgba01[..., 3] * 255.0), 0, 255).astype(np.uint8)
    rgb8 = np.clip(np.rint(rgba01[..., :3] * 255.0), 0, 255).astype(np.uint8)
    c565 = rgb888_to_rgb565_dither(rgb8)
    return c565.astype("<u2").tobytes() + a8.tobytes()


def build_font_c_struct(
    name: str,
    font_path: str,
    face_index: int,
    size: int,
    symbols: str,
    fallback_path: str = None,
    fallback_index: int = 0,
    gamma: float = 0.85,
):
    ss = 2
    font_main = ImageFont.truetype(font_path, size * ss, index=face_index)
    font_fb = ImageFont.truetype(fallback_path, size * ss, index=fallback_index) if fallback_path else None

    chars = set(symbols)
    chars.add(" ")
    sorted_cps = sorted(ord(c) for c in chars if 0x20 <= ord(c) <= 0xFFFF)

    glyphs = []
    max_ascent = 0
    max_descent = 0
    glyph_map = {}

    for cp in sorted_cps:
        g = render_glyph_4bpp(chr(cp), font_main, font_fb, size, ss=ss, gamma=gamma)
        glyphs.append(g)
        glyph_map[chr(cp)] = g
        if g["box_h"] > 0:
            top_from_base = g["ofs_y"] + g["box_h"]
            bot_from_base = -g["ofs_y"]
            max_ascent = max(max_ascent, top_from_base, g["ascent"])
            max_descent = max(max_descent, bot_from_base, g["descent"])

    if max_ascent == 0:
        max_ascent = size
    line_height = max_ascent + max_descent
    base_line = max_descent

    bitmap_bytes = []
    dsc_entries = [
        "    {.bitmap_index = 0, .adv_w = 0, .box_w = 0, .box_h = 0, .ofs_x = 0, .ofs_y = 0} /* id = 0 reserved */"
    ]
    for g in glyphs:
        b_idx = len(bitmap_bytes)
        packed = pack_nibbles(g["nibbles"])
        bitmap_bytes.extend(packed)
        safe_ch = g["ch"].replace("\\", "\\\\").replace('"', '\\"')
        dsc_entries.append(
            f'    {{.bitmap_index = {b_idx}, .adv_w = {g["adv_w"]}, .box_w = {g["box_w"]}, '
            f'.box_h = {g["box_h"]}, .ofs_x = {g["ofs_x"]}, .ofs_y = {g["ofs_y"]}}} /* U+{g["cp"]:04X} "{safe_ch}" */'
        )
    if not bitmap_bytes:
        bitmap_bytes = [0]

    min_cp = sorted_cps[0]
    max_cp = sorted_cps[-1]
    range_len = max_cp - min_cp + 1
    rel_cps = [f"0x{cp - min_cp:x}" for cp in sorted_cps]

    bmp_lines = [
        "    " + ", ".join(f"0x{b:02x}" for b in bitmap_bytes[i : i + 12])
        for i in range(0, len(bitmap_bytes), 12)
    ]
    rel_lines = [
        "    " + ", ".join(rel_cps[i : i + 10])
        for i in range(0, len(rel_cps), 10)
    ]

    c_snippet = f"""
/* ==================== {name} ({size}px, {len(glyphs)} glyphs, {len(bitmap_bytes)/1024:.1f}KB) ==================== */
static LV_ATTRIBUTE_LARGE_CONST const uint8_t {name}_bmp[] = {{
{",\n".join(bmp_lines)}
}};

static const lv_font_fmt_txt_glyph_dsc_t {name}_gdsc[] = {{
{",\n".join(dsc_entries)}
}};

static const uint16_t {name}_ulist[] = {{
{",\n".join(rel_lines)}
}};

static const lv_font_fmt_txt_cmap_t {name}_cmaps[] = {{
    {{
        .range_start = {min_cp}, .range_length = {range_len}, .glyph_id_start = 1,
        .unicode_list = {name}_ulist, .glyph_id_ofs_list = NULL,
        .list_length = {len(sorted_cps)}, .type = LV_FONT_FMT_TXT_CMAP_SPARSE_TINY
    }}
}};

static const lv_font_fmt_txt_dsc_t {name}_fdsc = {{
    .glyph_bitmap = {name}_bmp,
    .glyph_dsc = {name}_gdsc,
    .cmaps = {name}_cmaps,
    .kern_dsc = NULL,
    .kern_scale = 0,
    .cmap_num = 1,
    .bpp = 4,
    .kern_classes = 0,
    .bitmap_format = 0,
}};

const lv_font_t {name} = {{
    .get_glyph_dsc = lv_font_get_glyph_dsc_fmt_txt,
    .get_glyph_bitmap = lv_font_get_bitmap_fmt_txt,
    .line_height = {line_height},
    .base_line = {base_line},
    .subpx = LV_FONT_SUBPX_NONE,
    .underline_position = -2,
    .underline_thickness = 1,
    .dsc = &{name}_fdsc,
    .fallback = NULL,
    .user_data = NULL,
}};
"""
    return {
        "name": name,
        "line_height": line_height,
        "base_line": base_line,
        "ascent": line_height - base_line,
        "glyph_map": glyph_map,
        "bytes": len(bitmap_bytes),
        "c_code": c_snippet,
    }


# ============================================================================
# 页面清单：每个页面的 HTML 真值稿 / 真值截图 / 烘焙底图 / LVGL 宿主渲染图
# ============================================================================
PAGES = {
    "home": {
        "label": "主表盘 face3",
        "html": "templates/screen_480.html",
        "truth": "screen_480.png",
        "baked": "screen_480_baked_bg.png",
        "lvgl": "face3_lvgl_static.png",
        "card_box": (36, 296, 444, 446),
        "card_radius": 30,
    },
    "menu": {
        "label": "控制菜单 face4",
        "html": "templates/screen_menu_480.html",
        "truth": "screen_menu_480.png",
        "baked": "screen_menu_480_baked_bg.png",
        "lvgl": "face4_lvgl_menu.png",
        "card_box": None,
        "card_radius": None,
    },
}

# 差分墨迹框对齐的观测区域（页面坐标系 480x480）。
# 名称与 lvgl_ui.c 里的控件含义对应，只用于"测量偏移"，不参与生成。
INK_REGIONS = {
    "home": [
        ("brand",   (52, 26, 104, 52)),
        ("state",   (104, 26, 180, 52)),
        ("day",     (350, 22, 396, 52)),
        ("date",    (396, 22, 470, 52)),
        ("clock_hh", (24, 54, 156, 212)),
        ("clock_colon", (156, 54, 180, 216)),
        ("clock_mm", (180, 54, 352, 216)),
        ("wx_temp", (362, 82, 436, 152)),
        ("wx_deg",  (424, 74, 458, 132)),
        ("wx_desc", (392, 148, 472, 186)),
        ("wx_sub",  (318, 186, 474, 214)),
        ("copy_k",  (128, 320, 272, 347)),
        ("copy_t",  (126, 346, 352, 388)),
        ("copy_h",  (126, 388, 384, 416)),
        ("rail_l",  (28, 438, 260, 472)),
        ("rail_r",  (404, 438, 474, 472)),
    ],
    "menu": [
        ("back_txt", (48, 20, 150, 52)),
        ("hdr_ctrl", (180, 20, 280, 52)),
        ("hdr_time", (380, 20, 460, 52)),
        ("tile1_kick", (98, 78, 205, 102)),
        ("tile1_title", (94, 100, 250, 126)),
        ("tile1_sub", (94, 126, 250, 150)),
        ("tile2_kick", (318, 78, 426, 102)),
        ("tile2_title", (314, 100, 470, 126)),
        ("tile2_sub", (314, 126, 470, 150)),
        ("tile3_kick", (98, 192, 205, 216)),
        ("tile3_title", (94, 214, 250, 240)),
        ("tile3_sub", (94, 240, 250, 264)),
        ("tile4_kick", (318, 192, 426, 216)),
        ("tile4_title", (314, 214, 470, 240)),
        ("tile4_sub", (314, 240, 470, 264)),
        ("sl_vol_lbl", (60, 310, 110, 342)),
        ("sl_vol_val", (386, 310, 450, 342)),
        ("sl_brt_lbl", (60, 356, 110, 388)),
        ("sl_brt_val", (386, 356, 450, 388)),
        ("dock1", (54, 420, 180, 452)),
        ("dock2", (196, 420, 290, 452)),
        ("dock3", (340, 420, 460, 452)),
    ],
}

# 脏区常量（与 lvgl_ui.c 里的 88x88 球 + 5 根 4px 柱一致）
DIRTY_BALL_PX = 88 * 88
DIRTY_BARS_PX = (5 * 4 + 4 * 5) * 42  # 5 根 4px 柱 + 4 个 5px 间隙 = 40px 宽
FULL_FRAME_PX = 480 * 480


# ============================================================================
# 渲染 / 输入准备
# ============================================================================
def _run_render_frame(html_rel: str, out_png: Path) -> None:
    """调用 render_frame.sh 用真实 Chromium 渲染一帧；失败抛出明确异常。"""
    cmd = [str(SCRIPT_DIR / "render_frame.sh"), html_rel, str(out_png)]
    proc = subprocess.run(cmd, cwd=str(PIPE_DIR), capture_output=True, text=True)
    if proc.returncode != 0:
        tail = (proc.stdout or "") + (proc.stderr or "")
        raise RuntimeError(
            f"Chromium 渲染失败（{html_rel} -> {out_png.name}）:\n{tail.strip()[-1200:]}"
        )


def _python_bake(page: dict, out_png: Path) -> None:
    """无浏览器降级路径：用 bake_layers.py 的 CSS 方程烘焙底图（精度低于 Chromium）。"""
    from bake_layers import make_exact_css_baked_bg, make_exact_menu_baked_bg

    if page["card_box"] is not None:
        im = make_exact_css_baked_bg(
            480, 480, card_box=page["card_box"], card_radius=page["card_radius"]
        )
    else:
        im = make_exact_menu_baked_bg(480, 480)
    im.save(out_png, "PNG", optimize=True)
    print(f"[bake] (python fallback) {out_png.name} 480x480")


def prepare_pages(
    out_dir: Path,
    bake_source: str,
    do_render: bool,
    only_missing: bool = False,
) -> None:
    """准备每个页面的 ①真值截图 ②烘焙底图。

    - 真值截图：必须由 Chromium 渲染（screen_480.png / screen_menu_480.png）
    - 烘焙底图：Chromium 的 ?mode=bake_bg（像素级同源）优先，python 方程烘焙兜底
    - only_missing=True：只渲染缺失文件（供 --dry-run 在干净目录用临时目录时复用已有产物）
    """
    missing_truth, missing_baked = [], []
    for key, page in PAGES.items():
        truth = out_dir / page["truth"]
        baked = out_dir / page["baked"]
        if do_render:
            need_truth = not (only_missing and truth.exists())
            need_baked = not (only_missing and baked.exists())
            if need_truth:
                want_browser_truth = bake_source in ("auto", "browser")
                if want_browser_truth:
                    try:
                        _run_render_frame(page["html"], truth)
                    except RuntimeError as e:
                        if bake_source == "browser":
                            raise
                        print(f"[bake][warn] Chromium 不可用，沿用已有真值图: {e}")
                elif not truth.exists():
                    raise SystemExit(
                        f"[bake] --no-render 但缺少真值图 {truth}；先跑 render_frame.sh "
                        f"或去掉 --no-render"
                    )
            if need_baked:
                if bake_source == "python":
                    _python_bake(page, baked)
                else:
                    try:
                        _run_render_frame(page["html"] + "?mode=bake_bg", baked)
                    except RuntimeError as e:
                        if bake_source == "browser":
                            raise
                        print(f"[bake][warn] Chromium 烘焙不可用，降级 python 方程烘焙: {e}")
                        _python_bake(page, baked)

        if not truth.exists():
            missing_truth.append(str(truth))
        if not baked.exists():
            missing_baked.append(str(baked))

    if missing_truth or missing_baked:
        raise SystemExit(
            "[bake] 缺少输入：\n  truth: " + ", ".join(missing_truth) +
            "\n  baked: " + ", ".join(missing_baked)
        )


# ============================================================================
# 字体规格（与 templates/*.html 的 CSS font-weight 对齐）
#   Avenir Next.ttc face: 0=Bold(700) 2=DemiBold(600) 5=Medium(500) 7=Regular(400)
#   Hiragino Sans GB.ttc face: 0=W3(300) 2=W6(600)
# ============================================================================
def font_paths() -> tuple[str, str, str]:
    din = os.environ.get(
        "EVA_FONT_DIN", "/System/Library/Fonts/Supplemental/DIN Condensed Bold.ttf"
    )
    avenir = os.environ.get("EVA_FONT_AVENIR", "/System/Library/Fonts/Avenir Next.ttc")
    hira = os.environ.get("EVA_FONT_HIRA", "/System/Library/Fonts/Hiragino Sans GB.ttc")
    missing = [p for p in (din, avenir, hira) if not os.path.exists(p)]
    if missing:
        raise SystemExit(
            "[font] 缺少字体文件：\n  " + "\n  ".join(missing) +
            "\n请安装 macOS 系统字体，或设置 EVA_FONT_DIN / EVA_FONT_AVENIR / EVA_FONT_HIRA 指向可用字体。"
        )
    return din, avenir, hira


def font_specs() -> list[tuple]:
    DIN_PATH, AVENIR_PATH, HIRA_PATH = font_paths()
    menu_kicker = "0123456789.:·-%ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    menu_zh = "0123456789:·-°C%连续对话客厅灯光全屋恒温专注模式返回表盘语音主屏控制菜单太空表盘" \
              "已开启聆听极光就绪音量亮度按键节能静音关闭暖金强劲制冷待机中专注完成"
    weather_zh = "0123456789:.-°C%多云晴雨阴雪雷阵风微优朗连续对话极光客厅灯光全屋恒温专注模式静音勿扰暖阳新风节能"
    body_13 = ("0123456789.:·°%ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
               "体感湿度试着说：把客厅的灯关掉明早七点叫醒我返回表盘语音主屏控制菜单太空表盘"
               "已开启自动聆听按键关闭亮度舒适除湿强劲制冷待机中轻触启动专注中完成音量极光暖金就绪"
               "紫外线弱空气优降水概率")
    return [
        # (name, 主字体, primary_face, size, charset, fallback, fallback_face, gamma)
        ("ui_font_eva_din_170", DIN_PATH, 0, 170, "0123456789-", None, 0, 0.82),
        ("ui_font_eva_din_150", DIN_PATH, 0, 150, ":", None, 0, 0.82),
        # .wx .t font-weight:500 → Avenir Medium
        ("ui_font_eva_46", AVENIR_PATH, 5, 46, "0123456789-°C", None, 0, 0.85),
        ("ui_font_eva_32", AVENIR_PATH, 5, 32, "°C", None, 0, 0.85),
        # .copy .t font-weight:400 → Avenir Regular（旧版错用 Medium，中文回退 W3 正确）
        ("ui_font_eva_23", AVENIR_PATH, 7, 23,
         "0123456789.:…在听你说正在思考回答中已把客厅灯光调暗请问还有什么可以帮您打开氛围灯轻触光球唤醒EVA",
         HIRA_PATH, 0, 0.85),
        # .wx .d font-weight:400 → Avenir Regular；CJK 回退 W3
        ("ui_font_eva_16", AVENIR_PATH, 7, 16, weather_zh, HIRA_PATH, 0, 0.85),
        # 菜单页：标题 + 时间 font-weight:600 → Avenir DemiBold + Hiragino W6
        ("ui_font_eva_16_bold", AVENIR_PATH, 2, 16, menu_zh, HIRA_PATH, 2, 0.85),
        # .date/.rail/.copy .h/.t-sub 正文 400 → Avenir Regular + Hiragino W3
        ("ui_font_eva_13", AVENIR_PATH, 7, 13, body_13, HIRA_PATH, 0, 0.85),
        # .brand / .copy .k / .hdr-title font-weight:600 → Avenir DemiBold
        ("ui_font_eva_12_bold", AVENIR_PATH, 2, 12,
         "0123456789.:·-%ABCDEFGHIJKLMNOPQRSTUVWXYZ", None, 0, 0.85),
        # 菜单 tile kicker font-weight:700 → Avenir Bold
        ("ui_font_eva_10_bold", AVENIR_PATH, 0, 10, menu_kicker, None, 0, 0.85),
        # .state / .rail font-weight:400 → Avenir Regular
        ("ui_font_eva_10", AVENIR_PATH, 7, 10,
         "0123456789.:·-%ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz", HIRA_PATH, 0, 0.85),
    ]


# ============================================================================
# build：烘焙底图 → RGB565 资产 + 同源字库
# ============================================================================
def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def build_assets(
    out_dir: Path,
    assets_dir: Path,
    fonts_dir: Path,
    dry_run: bool = False,
) -> dict:
    """生成 eva_face3.bin 与 ui_font_eva_pack.c；dry_run 只计算并打印，不落盘。"""
    report: dict = {"generated_at": _now_iso(), "dry_run": dry_run, "files": {}}

    # 1) RGB565 Bayer 抖动底图
    baked_home = Image.open(out_dir / PAGES["home"]["baked"]).convert("RGB")
    baked_menu = Image.open(out_dir / PAGES["menu"]["baked"]).convert("RGB")
    if baked_home.size != (480, 480) or baked_menu.size != (480, 480):
        raise SystemExit("[bake] 烘焙底图尺寸不是 480x480，请检查模板 viewport/查询参数")
    c565_home = rgb888_to_rgb565_dither(np.asarray(baked_home, dtype=np.uint8))
    c565_menu = rgb888_to_rgb565_dither(np.asarray(baked_menu, dtype=np.uint8))

    # 2) 16 帧 88x88 RGB565A8 麦克风能量球
    orb_frames_bytes = [
        rgba_to_rgb565a8_bytes(make_mic_orb_frame(size=88, frame_idx=i, total_frames=16))
        for i in range(16)
    ]

    # 3) 打包 eva_face3.bin（EVA4: 2 张 480x480 底图 + 16 帧 88x88 精灵）
    bin_headers = struct.pack("<HHHHHH", 480, 480, 88, 88, 16, 2)
    bg_home_bytes = c565_home.astype("<u2").tobytes()
    bg_menu_bytes = c565_menu.astype("<u2").tobytes()
    eva_bin_path = assets_dir / "eva_face3.bin"
    bin_total = 16 + len(bg_home_bytes) + len(bg_menu_bytes) + sum(
        len(x) for x in orb_frames_bytes
    )
    print(
        f"[Asset Pack] {'(dry-run) ' if dry_run else ''}{eva_bin_path}: total={bin_total/1024:.1f}KB "
        f"(2x bg={2*len(bg_home_bytes)/1024:.1f}KB + 16x 88x88 orb="
        f"{sum(len(x) for x in orb_frames_bytes)/1024:.1f}KB)"
    )
    if not dry_run:
        assets_dir.mkdir(parents=True, exist_ok=True)
        with open(eva_bin_path, "wb") as f:
            f.write(b"EVA4")
            f.write(bin_headers)
            f.write(bg_home_bytes)
            f.write(bg_menu_bytes)
            for fb in orb_frames_bytes:
                f.write(fb)
        report["files"]["eva_face3.bin"] = {
            "bytes": eva_bin_path.stat().st_size,
            "sha256": _sha256(eva_bin_path),
        }

    # 4) 同源 4bpp 字库包
    built_fonts = {}
    c_chunks = [
        """/*******************************************************************************
 * ui_font_eva_pack.c — Auto-generated by docs/design/art_pipeline/scripts/bake_to_lvgl.py
 * 同源字体栈：Avenir Next (主) + Hiragino Sans GB (中文回退)，与 templates 目录 HTML 的 CSS 字重对齐
 ******************************************************************************/
#include "lvgl.h"
"""
    ]
    total_font_bytes = 0
    specs = font_specs()
    for name, fpath, fidx, sz, syms, fbpath, fbidx, gam in specs:
        info = build_font_c_struct(name, fpath, fidx, sz, syms, fbpath, fbidx, gam)
        built_fonts[name] = {
            "px": sz,
            "glyphs": len(info["glyph_map"]),
            "bitmap_bytes": info["bytes"],
            "primary_face": fidx,
            "fallback_face": fbidx,
        }
        c_chunks.append(info["c_code"])
        total_font_bytes += info["bytes"]

    font_pack_path = fonts_dir / "ui_font_eva_pack.c"
    print(
        f"[Font Pack] {'(dry-run) ' if dry_run else ''}{font_pack_path}: "
        f"{len(specs)} fonts, total bitmap={total_font_bytes/1024:.1f}KB"
    )
    if not dry_run:
        fonts_dir.mkdir(parents=True, exist_ok=True)
        with open(font_pack_path, "w", encoding="utf-8") as f:
            f.write("\n".join(c_chunks))
        report["files"]["ui_font_eva_pack.c"] = {
            "bytes": font_pack_path.stat().st_size,
            "sha256": _sha256(font_pack_path),
        }
    report["fonts"] = built_fonts
    report["font_bitmap_total_bytes"] = total_font_bytes
    report["dirty_region_px"] = DIRTY_BALL_PX + DIRTY_BARS_PX
    report["dirty_region_pct"] = round(
        (DIRTY_BALL_PX + DIRTY_BARS_PX) / FULL_FRAME_PX * 100, 2
    )

    if not dry_run:
        (out_dir / "build.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"[Build] wrote {out_dir / 'build.json'}")
    return report


# ============================================================================
# compare：1:1 验真看板 + metrics.json + 阈值门禁
# ============================================================================
def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _load_rgb(path: Path) -> np.ndarray:
    return np.asarray(Image.open(path).convert("RGB"), dtype=np.float64)


def _fg_mask(img: np.ndarray, bg: np.ndarray, thr: float = 26.0) -> np.ndarray:
    """前景（动态层）掩膜：只取"比底图更亮"的像素。

    烘焙底图在 ?mode=bake_bg 时会额外画 .clock-glow 等烘焙层，若用 abs(diff)
    会把这类"底图更亮"的区域误判成前景墨迹；动态文字/图标一律比底图亮，
    因此用带符号的差值可以干净地提取墨迹。
    """
    return (img - bg).max(axis=2) > thr


def _bbox(mask: np.ndarray, box: tuple[int, int, int, int]) -> tuple | None:
    x0, y0, x1, y1 = box
    sub = mask[y0:y1, x0:x1]
    ys, xs = np.where(sub)
    if len(xs) == 0:
        return None
    return (x0 + int(xs.min()), y0 + int(ys.min()), x0 + int(xs.max()), y0 + int(ys.max()))


def _region_report(page_key: str, truth: np.ndarray, baked: np.ndarray, lvgl: np.ndarray) -> list[dict]:
    """差分墨迹框：分别提取"设计稿动态层"与"LVGL 渲染动态层"的墨迹 bbox，给出所需偏移。"""
    bg565 = rgb565_to_rgb888(rgb888_to_rgb565_dither(baked.astype(np.uint8))).astype(np.float64)
    design_fg = _fg_mask(truth, baked)
    lvgl_fg = _fg_mask(lvgl, bg565)
    rows = []
    for name, box in INK_REGIONS[page_key]:
        db = _bbox(design_fg, box)
        lb = _bbox(lvgl_fg, box)
        if db is None or lb is None:
            rows.append({"region": name, "design": db, "lvgl": lb, "dx": None, "dy": None})
            continue
        rows.append(
            {
                "region": name,
                "design": db,
                "lvgl": lb,
                # 正数 = LVGL 需要往右下移动才能与设计稿重合
                "dx": int(db[0] - lb[0]),
                "dy": int(db[1] - lb[1]),
            }
        )
    return rows


def _page_metrics(truth: np.ndarray, lvgl: np.ndarray) -> dict:
    d = np.abs(truth - lvgl)
    mae = float(d.mean())
    mse = float((d ** 2).mean())
    psnr = 10.0 * math.log10((255.0 ** 2) / max(mse, 1e-9))
    within8 = float((d.max(axis=2) <= 8.0).mean() * 100.0)
    return {
        "mae": round(mae, 3),
        "fidelity_pct": round(100.0 - mae * 100.0 / 255.0, 2),
        "psnr_db": round(psnr, 2),
        "within8_pct": round(within8, 2),
        "rmse": round(math.sqrt(mse), 2),
        "max_abs_diff": int(d.max()),
    }


def _draw_board(
    out_path: Path,
    truth_im: Image.Image,
    lvgl_im: Image.Image,
    metrics: dict,
    page_label: str,
) -> None:
    """三联看板：① HTML 真值 ② LVGL RGB565 真实帧缓冲 ③ 4x 误差热力图。"""
    try:
        f_title = ImageFont.truetype("/System/Library/Fonts/Hiragino Sans GB.ttc", 16, index=0)
        f_meta = ImageFont.truetype("/System/Library/Fonts/Hiragino Sans GB.ttc", 12, index=0)
    except OSError:
        f_title = f_meta = ImageFont.load_default()
    margin, gap, top, bottom = 28, 24, 86, 54
    W = margin * 2 + 480 * 3 + gap * 2
    H = top + 480 + bottom
    board = Image.new("RGB", (W, H), (8, 12, 20))
    d = ImageDraw.Draw(board)

    truth = np.asarray(truth_im.convert("RGB"), dtype=np.float64)
    lvgl = np.asarray(lvgl_im.convert("RGB"), dtype=np.float64)
    heat = np.clip(np.abs(truth - lvgl) * 4.0, 0, 255).astype(np.uint8)
    heat_im = Image.fromarray(heat, "RGB")

    panels = [
        (truth_im, "① HTML/CSS 真值稿（Chromium 24-bit RGB888）"),
        (lvgl_im, "② LVGL 9.5 设备端真实帧缓冲（RGB565）"),
        (heat_im, "③ 像素误差热力图（|diff| x4）"),
    ]
    for i, (im, cap) in enumerate(panels):
        x = margin + i * (480 + gap)
        board.paste(im.convert("RGB"), (x, top))
        d.text((x, top - 24), cap, fill=(230, 240, 255), font=f_meta)

    d.text(
        (margin, 18),
        f"{page_label} 1:1 像素级复刻验收 — MAE {metrics['mae']:.2f}/255"
        f" · 还原度 {metrics['fidelity_pct']:.1f}% · PSNR {metrics['psnr_db']:.2f}dB"
        f" · ≤1 阶 {metrics['within8_pct']:.1f}%",
        fill=(240, 248, 255), font=f_title,
    )
    d.text(
        (margin, 42),
        "③ 热力图越暗越好；红/绿/蓝亮边=通道误差（文字偏移/字重差异/渐变量化误差）",
        fill=(120, 180, 210), font=f_meta,
    )
    d.text(
        (margin, H - 34),
        "生成：bake_to_lvgl.py compare（指标同时写入 out/metrics.json）",
        fill=(120, 180, 210), font=f_meta,
    )
    board.save(out_path, "PNG", optimize=True)


def _write_menu_preview(out_dir: Path) -> Path | None:
    """控制菜单三联预览（默认态 / 交互态 / 主表盘），供人工目检。"""
    home, menu0, menu1 = (
        out_dir / "face3_lvgl_static.png",
        out_dir / "face4_lvgl_menu.png",
        out_dir / "face4_lvgl_menu_interacted.png",
    )
    if not (home.exists() and menu0.exists() and menu1.exists()):
        return None
    try:
        f_title = ImageFont.truetype("/System/Library/Fonts/Hiragino Sans GB.ttc", 15, index=0)
        f_sub = ImageFont.truetype("/System/Library/Fonts/Hiragino Sans GB.ttc", 12, index=0)
    except OSError:
        f_title = f_sub = ImageFont.load_default()
    board = Image.new("RGB", (480 * 3 + 60, 560), (8, 12, 20))
    d = ImageDraw.Draw(board)
    panels = [
        (home, "1. LVGL 主表盘 (face3 · RGB565)", "静态帧 / face3_lvgl_static.png"),
        (menu0, "2. LVGL 控制中心菜单 (face4 · 默认态)", "face4_lvgl_menu.png"),
        (menu1, "3. LVGL 控制中心菜单 (触控交互态)", "face4_lvgl_menu_interacted.png"),
    ]
    for i, (p, t1, t2) in enumerate(panels):
        x = 15 + i * 495
        board.paste(Image.open(p).convert("RGB"), (x, 64))
        d.text((x + 6, 12), t1, fill=(244, 248, 255), font=f_title)
        d.text((x + 6, 36), t2, fill=(53, 224, 255), font=f_sub)
    out = out_dir / "eva_ui_system_preview.png"
    board.save(out, "PNG", optimize=True)
    return out


def compare(args) -> int:
    out_dir = Path(args.out).resolve() if args.out else PIPE_DIR / "out"
    if not out_dir.exists():
        print(f"[compare] 输出目录不存在: {out_dir}", file=sys.stderr)
        return 2

    page_results: dict = {}
    board_inputs: dict = {}
    for key, page in PAGES.items():
        truth_p = out_dir / page["truth"]
        baked_p = out_dir / page["baked"]
        lvgl_p = out_dir / page["lvgl"]
        if not (truth_p.exists() and baked_p.exists()):
            print(
                f"[compare] 缺少 {key} 的输入：{truth_p.name} / {baked_p.name}；"
                f"先跑 `bake_to_lvgl.py build`",
                file=sys.stderr,
            )
            return 2
        if not lvgl_p.exists():
            if key == "home":
                print(
                    f"[compare] 缺少 {lvgl_p.name}；先跑 "
                    f"`../../esp32/s31_smooth_demo/host_render/render.sh <out_dir>`",
                    file=sys.stderr,
                )
                return 2
            print(f"[compare][warn] 跳过 {key}：缺少 {lvgl_p.name}", file=sys.stderr)
            continue

        truth = _load_rgb(truth_p)
        baked = _load_rgb(baked_p)
        lvgl = _load_rgb(lvgl_p)
        if truth.shape != lvgl.shape:
            print(f"[compare] {key} 尺寸不一致: {truth.shape} vs {lvgl.shape}", file=sys.stderr)
            return 2
        metrics = _page_metrics(truth, lvgl)
        regions = _region_report(key, truth, baked, lvgl)
        passed = metrics["mae"] <= args.max_mae
        page_results[key] = {
            "label": page["label"],
            "inputs": {
                "truth": {"file": truth_p.name, "bytes": truth_p.stat().st_size, "sha256": _sha256(truth_p)},
                "baked": {"file": baked_p.name, "bytes": baked_p.stat().st_size, "sha256": _sha256(baked_p)},
                "lvgl": {"file": lvgl_p.name, "bytes": lvgl_p.stat().st_size, "sha256": _sha256(lvgl_p)},
            },
            "metrics": metrics,
            "regions": regions,
            "gate": {"max_mae": args.max_mae, "pass": passed},
        }
        board_inputs[key] = (Image.open(truth_p).convert("RGB"), Image.open(lvgl_p).convert("RGB"))

        print(f"\n[{key}] {page['label']}")
        print(
            f"  MAE={metrics['mae']:.2f}/255  还原度={metrics['fidelity_pct']:.2f}%  "
            f"PSNR={metrics['psnr_db']:.2f}dB  ≤8/255={metrics['within8_pct']:.2f}%  "
            f"{'PASS' if passed else 'FAIL'}"
        )
        for r in regions:
            if r["dx"] is None:
                print(f"  {r['region']:12s} 未检出墨迹（跳过）")
            else:
                print(
                    f"  {r['region']:12s} 建议偏移 dx={r['dx']:+d} dy={r['dy']:+d}"
                    f"  design={r['design']}  lvgl={r['lvgl']}"
                )

    # 每个页面各出一张三联看板；home 额外保留历史文件名 html_vs_lvgl_1to1.png
    for key, res in page_results.items():
        if key not in board_inputs:
            continue
        board_path = out_dir / f"{key}_html_vs_lvgl_1to1.png"
        _draw_board(
            board_path,
            board_inputs[key][0],
            board_inputs[key][1],
            res["metrics"],
            res["label"],
        )
        print(f"[compare] wrote {board_path}")
        if key == "home":
            legacy = out_dir / "html_vs_lvgl_1to1.png"
            shutil.copyfile(board_path, legacy)
            print(f"[compare] wrote {legacy}（home 兼容名）")
    preview = _write_menu_preview(out_dir)
    if preview:
        print(f"[compare] wrote {preview}")

    gate_pass = all(p["gate"]["pass"] for p in page_results.values()) if page_results else False
    metrics_doc = {
        "generated_at": _now_iso(),
        "generator": "bake_to_lvgl.py compare",
        "thresholds": {"max_mae": args.max_mae},
        "pages": page_results,
        "gate_pass": gate_pass,
        "dirty_region": {
            "px": DIRTY_BALL_PX + DIRTY_BARS_PX,
            "pct": round((DIRTY_BALL_PX + DIRTY_BARS_PX) / FULL_FRAME_PX * 100, 2),
            "note": "88x88 orb + 5x4px bars(40px span)@42px height，与 lvgl_ui.c 一致",
        },
    }
    (out_dir / "metrics.json").write_text(
        json.dumps(metrics_doc, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"[compare] wrote {out_dir / 'metrics.json'}")

    if not gate_pass:
        if args.no_gate:
            print(
                f"\n[GATE][warn] MAE 超过 {args.max_mae}/255，但 --no-gate 已放行",
                file=sys.stderr,
            )
            return 0
        print(
            f"\n[GATE][FAIL] 存在页面 MAE > {args.max_mae}/255，禁止上板；"
            f"按上面的 dx/dy 建议修 lvgl_ui.c 后重跑",
            file=sys.stderr,
        )
        return 1
    print(f"\n[GATE][PASS] 全部页面 MAE <= {args.max_mae}/255")
    return 0


# ============================================================================
# CLI
# ============================================================================
def _parse_args(argv: list[str]):
    parser = argparse.ArgumentParser(
        prog="bake_to_lvgl.py",
        description="HTML/CSS 设计稿 → LVGL 9.5 RGB565 资产编译 + 1:1 像素验真",
        epilog="示例：\n"
        "  bake_to_lvgl.py build            # 渲染真值/烘焙底图 → 写 eva_face3.bin + 字库\n"
        "  bake_to_lvgl.py build --dry-run  # 只计算与打印，不落盘\n"
        "  bake_to_lvgl.py compare          # 生成看板 + metrics.json 并执行 MAE 门禁\n"
        "\n（旧用法 `--compare` 仍然兼容）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="cmd")

    b = sub.add_parser("build", help="烘焙并写入固件资产（eva_face3.bin / ui_font_eva_pack.c）")
    b.add_argument("--dry-run", action="store_true", help="只计算、打印体积，不写任何文件")
    b.add_argument(
        "--bake-source",
        choices=["auto", "browser", "python"],
        default="auto",
        help="烘焙底图来源：browser=Chromium ?mode=bake_bg（像素级同源，推荐）；"
        "python=bake_layers.py 方程烘焙（无浏览器时兜底）；auto=优先 browser",
    )
    b.add_argument("--no-render", action="store_true", help="跳过 HTML 渲染，使用 out/ 已有真值与底图")
    b.add_argument("--out", default=None, help="输出目录（默认 docs/design/art_pipeline/out）")
    b.add_argument("--demo-main", default=None, help="固件 main/ 目录（默认 esp32/s31_smooth_demo/main）")

    c = sub.add_parser("compare", help="生成 1:1 验真看板 + metrics.json，并执行 MAE 门禁")
    c.add_argument("--out", default=None, help="输出目录（默认 docs/design/art_pipeline/out）")
    c.add_argument("--max-mae", type=float, default=12.0, help="整屏 MAE 上限（默认 12/255）")
    c.add_argument("--no-gate", action="store_true", help="只报告，不因超阈值返回非 0")

    argv = list(argv)
    # 兼容旧用法：`bake_to_lvgl.py`（无参数）→ build；`bake_to_lvgl.py --compare` → compare
    if not argv or argv[0].startswith("-"):
        if argv[:1] == ["--compare"]:
            argv = ["compare"] + argv[1:]
        else:
            argv = ["build"] + argv
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv if argv is not None else sys.argv[1:])
    if args.cmd == "compare":
        return compare(args)

    out_dir = Path(args.out).resolve() if args.out else PIPE_DIR / "out"
    demo_main = Path(args.demo_main).resolve() if args.demo_main else find_demo_main()
    assets_dir = demo_main / "assets"
    fonts_dir = demo_main / "fonts"
    print(f"[build] pipe_dir={PIPE_DIR}")
    print(f"[build] out_dir={out_dir}")
    print(f"[build] demo_main={assets_dir.parent}")

    if args.dry_run:
        # dry-run 不写 out/ 与固件目录：把已有输入复制到临时目录，缺失的临时渲染，算完即删
        tmp_dir = Path(tempfile.mkdtemp(prefix="eva_art_dryrun_"))
        try:
            for _key, page in PAGES.items():
                for name in (page["truth"], page["baked"]):
                    src = out_dir / name
                    if src.exists():
                        shutil.copy2(src, tmp_dir / name)
            print(f"[build] DRY-RUN：输入缓存 {tmp_dir}（缺失项临时渲染，结束后删除）")
            prepare_pages(tmp_dir, args.bake_source, do_render=True, only_missing=True)
            report = build_assets(tmp_dir, assets_dir, fonts_dir, dry_run=True)
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)
        print(
            f"[build] DRY-RUN 完成（未写任何文件）："
            f"字库 bitmap={report['font_bitmap_total_bytes']/1024:.1f}KB, "
            f"脏区={report['dirty_region_pct']:.2f}%"
        )
        return 0

    out_dir.mkdir(parents=True, exist_ok=True)
    prepare_pages(
        out_dir,
        args.bake_source,
        do_render=not args.no_render,
    )
    report = build_assets(out_dir, assets_dir, fonts_dir, dry_run=args.dry_run)
    print(
        f"[build] {'DRY-RUN 完成（未写任何文件）' if args.dry_run else '完成'}："
        f"{len(report['files'])} 个固件文件, 字库 bitmap={report['font_bitmap_total_bytes']/1024:.1f}KB, "
        f"脏区={report['dirty_region_pct']:.2f}%"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
