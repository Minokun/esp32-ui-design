#!/usr/bin/env python3
"""
gen_lvgl_font.py — 零外部依赖的 LVGL 9.x 字体生成器（支持 CSS 字体栈中英混排 Fallback）
直接读取 macOS/Linux 的 .ttf / .ttc 字体，按指定字表生成 4bpp 抗锯齿 lv_font_t C 源码。

特性:
  - 支持主字体 (--font) + 中文回退字体 (--fallback-font)，1:1 还原 CSS font-family 混排规则
  - 2x 超采样灰度抗锯齿 + Gamma 校正，贴合 macOS CoreText (-webkit-font-smoothing: antialiased)
  - 产出标准 LVGL 9.x lv_font_fmt_txt_dsc_t (4bpp, SPARSE_TINY cmap)

用法:
  ./scripts/gen_lvgl_font.py \
    --font "/System/Library/Fonts/Avenir Next.ttc" --face-index 5 \
    --fallback-font "/System/Library/Fonts/Hiragino Sans GB.ttc" --fallback-index 0 \
    --size 23 --name ui_font_eva_23 \
    --symbols "0123456789:.-°%·EVAONLINELISTENING在听你说…试着把客厅的灯关掉多云体感湿度" \
    --out ../../esp32/s31_smooth_demo/main/fonts/ui_font_eva_23.c
"""
import argparse
import math
import os
import sys
import numpy as np
from PIL import Image, ImageDraw, ImageFont


def is_cjk_or_fullwidth(cp: int) -> bool:
    return (
        0x2E80 <= cp <= 0x9FFF
        or 0x3000 <= cp <= 0x303F
        or 0xFF00 <= cp <= 0xFFEF
    )


def render_glyph_4bpp(ch: str, font_main, font_fb, size: int, ss: int = 2, gamma: float = 0.88):
    cp = ord(ch)
    use_fb = font_fb is not None and is_cjk_or_fullwidth(cp)
    f = font_fb if use_fb else font_main

    ascent_s, descent_s = f.getmetrics()
    ascent = int(math.ceil(ascent_s / ss))
    descent = int(math.ceil(descent_s / ss))

    # 获取高精度 advance
    adv_s = f.getlength(ch)
    adv_px = adv_s / ss
    adv_fp4 = max(1, int(round(adv_px * 16)))

    if ch == " " or ch == "\u00a0":
        return {
            "cp": cp,
            "ch": ch,
            "adv_w": adv_fp4,
            "box_w": 0,
            "box_h": 0,
            "ofs_x": 0,
            "ofs_y": 0,
            "ascent": ascent,
            "descent": descent,
            "nibbles": [],
        }

    # 在超采样画布上以 (pad_x, baseline_y) 为基线锚点 (`anchor="ls"`) 绘制
    pad_s = max(size * ss, 64)
    cw = pad_s * 3
    ch_h = pad_s * 3
    orig_x = pad_s
    orig_y = pad_s * 2  # baseline y in supersampled canvas

    canvas = Image.new("L", (cw, ch_h), 0)
    draw = ImageDraw.Draw(canvas)
    try:
        draw.text((orig_x, orig_y), ch, fill=255, font=f, anchor="ls")
    except ValueError:
        # fallback if anchor="ls" unsupported
        draw.text((orig_x, orig_y - ascent_s), ch, fill=255, font=f)

    # 缩回 1x 尺寸
    tw = cw // ss
    th = ch_h // ss
    base_x = orig_x // ss
    base_y = orig_y // ss
    img_1x = canvas.resize((tw, th), Image.Resampling.BOX)
    arr = np.asarray(img_1x, dtype=np.float32) / 255.0
    if gamma != 1.0:
        arr = np.power(np.clip(arr, 0.0, 1.0), gamma)
    q15 = np.clip(np.rint(arr * 15.0), 0, 15).astype(np.uint8)

    nz_y, nz_x = np.nonzero(q15 > 0)
    if len(nz_x) == 0:
        return {
            "cp": cp,
            "ch": ch,
            "adv_w": adv_fp4,
            "box_w": 0,
            "box_h": 0,
            "ofs_x": 0,
            "ofs_y": 0,
            "ascent": ascent,
            "descent": descent,
            "nibbles": [],
        }

    x0, x1 = int(nz_x.min()), int(nz_x.max()) + 1
    y0, y1 = int(nz_y.min()), int(nz_y.max()) + 1
    box_w = x1 - x0
    box_h = y1 - y0
    ofs_x = x0 - base_x
    # LVGL ofs_y: 基线(base_y)到字形框底边(y1)的向上偏移，底边在基线上方为正，下方为负
    ofs_y = base_y - y1

    sub = q15[y0:y1, x0:x1].flatten().tolist()
    return {
        "cp": cp,
        "ch": ch,
        "adv_w": adv_fp4,
        "box_w": box_w,
        "box_h": box_h,
        "ofs_x": ofs_x,
        "ofs_y": ofs_y,
        "ascent": ascent,
        "descent": descent,
        "nibbles": sub,
    }


def pack_nibbles(nibbles):
    out = []
    n = len(nibbles)
    for i in range(0, n, 2):
        hi = nibbles[i] & 0x0F
        lo = (nibbles[i + 1] & 0x0F) if (i + 1 < n) else 0
        out.append((hi << 4) | lo)
    return out


def main():
    ap = argparse.ArgumentParser(description="Generate LVGL 9.x 4bpp C font from TTF/TTC")
    ap.add_argument("--font", required=True, help="Primary TTF/TTC path")
    ap.add_argument("--face-index", type=int, default=0, help="Primary TTC face index")
    ap.add_argument("--fallback-font", default=None, help="Fallback TTF/TTC for CJK glyphs")
    ap.add_argument("--fallback-index", type=int, default=0, help="Fallback TTC face index")
    ap.add_argument("--size", type=int, required=True, help="Font pixel size")
    ap.add_argument("--name", required=True, help="C symbol name for lv_font_t")
    ap.add_argument("--symbols", default="", help="Characters to include")
    ap.add_argument("--ascii", action="store_true", help="Include printable ASCII 0x20..0x7E")
    ap.add_argument("--gamma", type=float, default=0.88, help="AA gamma correction (default 0.88)")
    ap.add_argument("--out", required=True, help="Output .c file path")
    args = ap.parse_args()

    ss = 2
    font_main = ImageFont.truetype(args.font, args.size * ss, index=args.face_index)
    font_fb = (
        ImageFont.truetype(args.fallback_font, args.size * ss, index=args.fallback_index)
        if args.fallback_font
        else None
    )

    chars = set(args.symbols)
    chars.add(" ")
    if args.ascii:
        for cp in range(0x20, 0x7F):
            chars.add(chr(cp))

    sorted_cps = sorted(ord(c) for c in chars if 0x20 <= ord(c) <= 0xFFFF)
    glyphs = []
    max_ascent = 0
    max_descent = 0

    for cp in sorted_cps:
        g = render_glyph_4bpp(chr(cp), font_main, font_fb, args.size, ss=ss, gamma=args.gamma)
        glyphs.append(g)
        if g["box_h"] > 0:
            top_from_base = g["ofs_y"] + g["box_h"]
            bot_from_base = -g["ofs_y"]
            max_ascent = max(max_ascent, top_from_base, g["ascent"])
            max_descent = max(max_descent, bot_from_base, g["descent"])

    if max_ascent == 0:
        max_ascent = args.size
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

    macro_guard = args.name.upper()
    bmp_lines = []
    for i in range(0, len(bitmap_bytes), 12):
        chunk = ", ".join(f"0x{b:02x}" for b in bitmap_bytes[i : i + 12])
        bmp_lines.append("    " + chunk)

    rel_lines = []
    for i in range(0, len(rel_cps), 10):
        chunk = ", ".join(rel_cps[i : i + 10])
        rel_lines.append("    " + chunk)

    c_code = f"""/*******************************************************************************
 * Generated by docs/design/art_pipeline/scripts/gen_lvgl_font.py
 * Font: {os.path.basename(args.font)} (index {args.face_index})
 * Fallback: {os.path.basename(args.fallback_font) if args.fallback_font else 'None'}
 * Size: {args.size} px, Bpp: 4, Glyphs: {len(glyphs)}
 ******************************************************************************/

#include "lvgl.h"

#ifndef {macro_guard}
#define {macro_guard} 1
#endif

#if {macro_guard}

static LV_ATTRIBUTE_LARGE_CONST const uint8_t glyph_bitmap[] = {{
{",\n".join(bmp_lines)}
}};

static const lv_font_fmt_txt_glyph_dsc_t glyph_dsc[] = {{
{",\n".join(dsc_entries)}
}};

static const uint16_t unicode_list_0[] = {{
{",\n".join(rel_lines)}
}};

static const lv_font_fmt_txt_cmap_t cmaps[] = {{
    {{
        .range_start = {min_cp}, .range_length = {range_len}, .glyph_id_start = 1,
        .unicode_list = unicode_list_0, .glyph_id_ofs_list = NULL,
        .list_length = {len(sorted_cps)}, .type = LV_FONT_FMT_TXT_CMAP_SPARSE_TINY
    }}
}};

static const lv_font_fmt_txt_dsc_t font_dsc = {{
    .glyph_bitmap = glyph_bitmap,
    .glyph_dsc = glyph_dsc,
    .cmaps = cmaps,
    .kern_dsc = NULL,
    .kern_scale = 0,
    .cmap_num = 1,
    .bpp = 4,
    .kern_classes = 0,
    .bitmap_format = 0,
}};

const lv_font_t {args.name} = {{
    .get_glyph_dsc = lv_font_get_glyph_dsc_fmt_txt,
    .get_glyph_bitmap = lv_font_get_bitmap_fmt_txt,
    .line_height = {line_height},
    .base_line = {base_line},
    .subpx = LV_FONT_SUBPX_NONE,
    .underline_position = -2,
    .underline_thickness = 1,
    .dsc = &font_dsc,
    .fallback = NULL,
    .user_data = NULL,
}};

#endif /* {macro_guard} */
"""
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(c_code)
    print(
        f"[gen_lvgl_font] Wrote {args.out}: {len(glyphs)} glyphs, "
        f"bitmap={len(bitmap_bytes)/1024:.1f}KB, line_height={line_height}, base_line={base_line}"
    )


if __name__ == "__main__":
    main()
