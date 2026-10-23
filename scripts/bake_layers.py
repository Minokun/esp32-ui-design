#!/usr/bin/env python3
"""bake_layers.py —— 纯 Python 分层烘焙（Chromium 不可用时的降级路径 / 圆屏设计稿生成器）。

【首选路径不是本脚本】标准流程请用 `bake_to_lvgl.py build`：
Chromium 直接渲染 templates/*.html?mode=bake_bg，与设计真值像素级同源（MAE=0）。
本脚本用 CSS 方程在 Python 里重新实现同一套极光/毛玻璃/斜切高光，属于离线降级路径
（实测与 Chromium 原稿背景 MAE≈5.9，菜单页≈16.5；仅在无浏览器环境使用）。

可生成：
  1. out/screen_480_baked_bg.png       —— 主表盘烘焙底图（Python 方程版，降级用）
  2. out/screen_menu_480_baked_bg.png  —— 控制中心菜单烘焙底图（Python 方程版，降级用）
  3. out/screen_480_circle.png         —— 480×480 圆屏设计稿（?shape=circle 的 Python 版）
  4. out/screen_480_circle_debug.png   —— 叠加 R=240 物理边界与 R=206 安全区参考线的检视稿

注意：菜单页真值图 out/screen_menu_480.png 由 render_frame.sh 渲染，不在本脚本内生成。
"""
import argparse
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

SCRIPT_DIR = Path(__file__).resolve().parent
PIPE_DIR = SCRIPT_DIR.parent


def alpha_over(dst_rgb: np.ndarray, src_rgb: np.ndarray, src_a: np.ndarray) -> np.ndarray:
    """标准 CSS straight-alpha source-over 合成 (H,W,3) float 0..255。"""
    a = src_a[..., None] if src_a.ndim == 2 else src_a
    return dst_rgb * (1.0 - a) + src_rgb * a


def _bake_aurora_stage(w: int = 480, h: int = 480, seed: int = 42) -> np.ndarray:
    """生成 480x480 深空极光 + 58px 高斯模糊光斑 + 胶片噪点基底 (float32 HxWx3)。"""
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)

    # 1. linear-gradient(180deg, #04060D 0%, #0B1826 100%)
    t = yy / (h - 1.0)
    rgb = (
        np.array([4.0, 6.0, 13.0])[None, None, :] * (1.0 - t[..., None])
        + np.array([11.0, 24.0, 38.0])[None, None, :] * t[..., None]
    )

    # 2. 3 层 CSS radial-gradient
    radials = [
        (w * 0.22, h * 1.00, 420.0, 300.0, np.array([30.0, 200.0, 190.0]), 0.30, 0.70),
        (w * 0.92, h * 0.62, 460.0, 420.0, np.array([120.0, 70.0, 210.0]), 0.50, 0.68),
        (w * 0.18, h * 0.08, 420.0, 360.0, np.array([40.0, 170.0, 220.0]), 0.55, 0.65),
    ]
    for cx, cy, rx, ry, col, a0, stop in radials:
        d = np.sqrt(((xx - cx) / rx) ** 2 + ((yy - cy) / ry) ** 2)
        k = np.clip(1.0 - d / stop, 0.0, 1.0)
        rgb = alpha_over(rgb, col[None, None, :], a0 * k)

    # 3. .aurora 光斑: filter: blur(58px); opacity: .55
    pad = 180
    blobs = [
        (-60, 30, 340, 260, np.array([50.0, 190.0, 240.0]), 0.55 * 0.55),
        (w - 380 + 90, 180, 380, 320, np.array([130.0, 80.0, 220.0]), 0.50 * 0.55),
        (60, h - 200 + 40, 320, 200, np.array([30.0, 200.0, 190.0]), 0.35 * 0.55),
    ]
    for left, top, bw, bh, col, eff_a in blobs:
        m = Image.new("L", (w + pad * 2, h + pad * 2), 0)
        x0, y0 = left + pad, top + pad
        ImageDraw.Draw(m).ellipse([x0, y0, x0 + bw, y0 + bh], fill=255)
        m = m.filter(ImageFilter.GaussianBlur(radius=58))
        ma = (np.asarray(m, dtype=np.float32)[pad : pad + h, pad : pad + w] / 255.0) * eff_a
        rgb = alpha_over(rgb, col[None, None, :], ma)

    # 4. .grain (胶片微噪点)
    rng = np.random.default_rng(seed)
    rgb = np.clip(rgb + rng.normal(0.0, 2.2, size=(h, w, 1)).astype(np.float32), 0.0, 255.0)
    return rgb


def _bake_glass_box(
    rgb: np.ndarray,
    box: tuple[int, int, int, int],
    radius: int,
    tint_rgb: tuple[float, float, float] = (255.0, 255.0, 255.0),
    tint_alpha: float = 0.055,
    border_rgb: tuple[float, float, float] = (255.0, 255.0, 255.0),
    border_alpha: float = 0.15,
    shadow_alpha: float = 0.55,
    shadow_dy: int = 18,
    shadow_blur: int = 24,
    glow_rgb: tuple[float, float, float] | None = None,
    glow_alpha: float = 0.0,
) -> np.ndarray:
    """在 rgb 画布上烘焙一个具有 backdrop-filter: blur(18px) saturate(130%)、斜切高光、描边与投影的毛玻璃容器。"""
    h, w, _ = rgb.shape
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    gx0, gy0, gx1, gy1 = box
    gr = radius
    ss = 4

    card_m_ss = Image.new("L", (w * ss, h * ss), 0)
    ImageDraw.Draw(card_m_ss).rounded_rectangle([gx0 * ss, gy0 * ss, gx1 * ss, gy1 * ss], radius=gr * ss, fill=255)
    card_mask = np.asarray(card_m_ss.resize((w, h), Image.Resampling.BOX), dtype=np.float32) / 255.0

    if shadow_alpha > 0:
        sh_m = Image.new("L", (w + 160, h + 160), 0)
        ImageDraw.Draw(sh_m).rounded_rectangle(
            [gx0 + 80, gy0 + shadow_dy + 80, gx1 + 80, gy1 + shadow_dy + 80], radius=gr, fill=255
        )
        sh_a = (
            np.asarray(sh_m.filter(ImageFilter.GaussianBlur(radius=shadow_blur)), dtype=np.float32)[
                80 : 80 + h, 80 : 80 + w
            ]
            / 255.0
            * shadow_alpha
            * (1.0 - card_mask)
        )
        rgb = alpha_over(rgb, np.array([0.0, 0.0, 12.0])[None, None, :], sh_a)

    if glow_rgb is not None and glow_alpha > 0:
        gl_m = Image.new("L", (w + 120, h + 120), 0)
        ImageDraw.Draw(gl_m).rounded_rectangle([gx0 + 60, gy0 + 60, gx1 + 60, gy1 + 60], radius=gr, fill=255)
        gl_a = (
            np.asarray(gl_m.filter(ImageFilter.GaussianBlur(radius=14)), dtype=np.float32)[60 : 60 + h, 60 : 60 + w]
            / 255.0
            * glow_alpha
            * (1.0 - card_mask * 0.5)
        )
        rgb = alpha_over(rgb, np.array(glow_rgb, dtype=np.float32)[None, None, :], gl_a)

    stage_im = Image.fromarray(np.clip(rgb + 0.5, 0, 255).astype(np.uint8), "RGB")
    blurred = stage_im.filter(ImageFilter.GaussianBlur(radius=18))
    saturated = ImageEnhance.Color(blurred).enhance(1.30)
    glass_rgb = np.asarray(saturated, dtype=np.float32)
    glass_rgb = alpha_over(
        glass_rgb, np.array(tint_rgb, dtype=np.float32)[None, None, :], np.full((h, w), tint_alpha, dtype=np.float32)
    )

    ang = np.deg2rad(123.0 - 90.0)
    span = max(120.0, float((gx1 - gx0) + (gy1 - gy0)))
    proj = ((xx - gx0) * np.cos(ang) + (yy - gy0) * np.sin(ang)) / span
    sheen_a = np.clip(1.0 - proj / 0.58, 0.0, 1.0) * 0.13
    glass_rgb = alpha_over(glass_rgb, np.array([255.0, 255.0, 255.0])[None, None, :], sheen_a)

    rgb = rgb * (1.0 - card_mask[..., None]) + glass_rgb * card_mask[..., None]

    inner_m_ss = Image.new("L", (w * ss, h * ss), 0)
    ImageDraw.Draw(inner_m_ss).rounded_rectangle(
        [(gx0 + 1) * ss, (gy0 + 1) * ss, (gx1 - 1) * ss, (gy1 - 1) * ss], radius=max(1, (gr - 1) * ss), fill=255
    )
    inner_mask = np.asarray(inner_m_ss.resize((w, h), Image.Resampling.BOX), dtype=np.float32) / 255.0
    border_ring = np.clip(card_mask - inner_mask, 0.0, 1.0)
    top_boost = np.clip(1.0 - (yy - gy0) / 16.0, 0.0, 1.0) * 0.12
    rgb = alpha_over(rgb, np.array(border_rgb, dtype=np.float32)[None, None, :], border_ring * (border_alpha + top_boost))
    return rgb


def make_exact_css_baked_bg(
    w: int = 480,
    h: int = 480,
    card_box: tuple[int, int, int, int] = (36, 296, 444, 446),
    card_radius: int = 30,
    include_top_dot: bool = True,
    include_rail_line: bool = True,
    seed: int = 42,
) -> Image.Image:
    """1:1 复现 templates/screen_480.html?mode=bake_bg 的完整 CSS 视觉合成链路。"""
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    rgb = _bake_aurora_stage(w, h, seed=seed)

    # 5. .clock-glow: 预烘焙大号时钟背后的青色环境柔光与深色投影
    cg_mask = Image.new("L", (w + 120, h + 120), 0)
    ImageDraw.Draw(cg_mask).rounded_rectangle([42 + 60, 72 + 60, 285 + 60, 184 + 60], radius=28, fill=210)
    cg_cyan = np.asarray(cg_mask.filter(ImageFilter.GaussianBlur(radius=36)), dtype=np.float32)[60 : 60 + h, 60 : 60 + w] / 255.0
    cg_dark = np.asarray(cg_mask.filter(ImageFilter.GaussianBlur(radius=24)), dtype=np.float32)[54 : 54 + h, 60 : 60 + w] / 255.0
    rgb = alpha_over(rgb, np.array([0.0, 0.0, 20.0])[None, None, :], cg_dark * 0.35)
    rgb = alpha_over(rgb, np.array([80.0, 220.0, 255.0])[None, None, :], cg_cyan * 0.24)

    # 6. 顶部发光状态圆点 (.dot: 7x7 #2DF6D0 + 10px 柔光)
    if include_top_dot:
        dot_m = Image.new("L", (w, h), 0)
        ImageDraw.Draw(dot_m).ellipse([44, 38, 51, 45], fill=255)
        dot_glow = np.asarray(dot_m.filter(ImageFilter.GaussianBlur(radius=6)), dtype=np.float32) / 255.0
        rgb = alpha_over(rgb, np.array([45.0, 246.0, 208.0])[None, None, :], np.clip(dot_glow * 1.1, 0.0, 1.0))
        dot_core = np.asarray(dot_m.filter(ImageFilter.GaussianBlur(radius=0.6)), dtype=np.float32) / 255.0
        rgb = alpha_over(rgb, np.array([45.0, 246.0, 208.0])[None, None, :], dot_core)

    # 7. .glass 毛玻璃卡片
    rgb = _bake_glass_box(
        rgb,
        box=card_box,
        radius=card_radius,
        tint_alpha=0.055,
        border_alpha=0.15,
        shadow_alpha=0.60,
        shadow_dy=24,
        shadow_blur=28,
    )

    # 8. .rail .line (1px 底部细分割线)
    if include_rail_line:
        rgb[454:455, 36:444] = alpha_over(
            rgb[454:455, 36:444], np.array([255.0, 255.0, 255.0])[None, None, :], np.full((1, 408), 0.08, dtype=np.float32)
        )

    # 9. .vignette 暗角
    dv = np.sqrt(((xx - w * 0.50) / (w * 1.20)) ** 2 + ((yy - h * 0.45) / (h * 1.00)) ** 2)
    vig_a = np.clip((dv - 0.42) / (1.0 - 0.42), 0.0, 1.0) * 0.62
    rgb = alpha_over(rgb, np.array([0.0, 0.0, 6.0])[None, None, :], vig_a)

    return Image.fromarray(np.clip(rgb + 0.5, 0, 255).astype(np.uint8), mode="RGB")


def _draw_menu_vector_icons_ss(w: int = 480, h: int = 480) -> Image.Image:
    """4x 超采样绘制控制菜单页的所有发光徽章底座、矢量图标与滑杆凹槽轨道。"""
    ss = 4
    W, H = w * ss, h * ss
    im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)

    # 1. 顶部返回箭头 (< at left:38, top:31, 16x16) 與右上在线绿点 (384, 35, 7x7)
    cyan = (53, 224, 255, 255)
    mint = (45, 246, 208, 255)
    ink = (6, 18, 28, 255)

    # Back chevron: M10 3.5 L5.5 8 L10 12.5 inside (38, 31)
    ox, oy = 38 * ss, 31 * ss
    pts = [(ox + int(10 * ss), oy + int(3.5 * ss)), (ox + int(5.5 * ss), oy + int(8 * ss)), (ox + int(10 * ss), oy + int(12.5 * ss))]
    d.line(pts, fill=cyan, width=int(2.2 * ss), joint="curve")
    for px, py in pts:
        r = int(1.1 * ss)
        d.ellipse([px - r, py - r, px + r, py + r], fill=cyan)

    # Header online dot at (384, 35, 7x7)
    d.ellipse([384 * ss, 35 * ss, 391 * ss, 42 * ss], fill=mint)

    # 2. 四个磁贴的 44x44 渐变圆形徽章 + 内部图标
    badges = [
        # (left, top, col_top, col_bot, glow_col, kind)
        (42, 96, (140, 246, 255), (28, 168, 200), (53, 224, 255), "mic"),
        (262, 96, (184, 164, 255), (91, 66, 214), (123, 97, 255), "sun"),
        (42, 210, (142, 255, 223), (20, 168, 134), (45, 246, 208), "wind"),
        (262, 210, (255, 216, 138), (216, 123, 24), (255, 184, 77), "timer"),
    ]
    for bx, by, ct, cb, gc, kind in badges:
        # 圆形渐变核心 (44x44)
        bsz = 44 * ss
        yy, xx = np.mgrid[0:bsz, 0:bsz].astype(np.float32)
        cx, cy, r = bsz * 0.5, bsz * 0.5, 22.0 * ss
        dist = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2)
        cov = np.clip(r + 0.5 - dist, 0.0, 1.0)
        fx, fy = bsz * 0.35, bsz * 0.30
        t = np.clip(np.sqrt((xx - fx) ** 2 + (yy - fy) ** 2) / (bsz * 0.75), 0.0, 1.0)[..., None]
        c_arr = np.array(ct, dtype=np.float32) * (1.0 - t) + np.array(cb, dtype=np.float32) * t
        patch = np.zeros((bsz, bsz, 4), dtype=np.uint8)
        patch[..., :3] = np.clip(c_arr + 0.5, 0, 255).astype(np.uint8)
        patch[..., 3] = np.clip(cov * 255.0 + 0.5, 0, 255).astype(np.uint8)
        im.alpha_composite(Image.fromarray(patch, "RGBA"), (bx * ss, by * ss))

        # 内部 22x22 图标 (居中于 bx+11, by+11)
        ix, iy = (bx + 11) * ss, (by + 11) * ss
        u = 22.0 * ss / 24.0
        sw = int(round(2.2 * u))
        if kind == "mic":
            d.rounded_rectangle([ix + 8 * u, iy + 2 * u, ix + 16 * u, iy + 14 * u], radius=int(4 * u), fill=ink)
            d.arc([ix + 5 * u, iy + 4 * u, ix + 19 * u, iy + 18 * u], start=0, end=180, fill=ink, width=sw)
            d.line([(ix + 12 * u, iy + 18 * u), (ix + 12 * u, iy + 22 * u)], fill=ink, width=sw)
        elif kind == "sun":
            d.ellipse([ix + 7 * u, iy + 7 * u, ix + 17 * u, iy + 17 * u], fill=ink)
            for ang_deg in range(0, 360, 45):
                rad = np.deg2rad(ang_deg)
                x0 = ix + 12 * u + np.cos(rad) * 7.2 * u
                y0 = iy + 12 * u + np.sin(rad) * 7.2 * u
                x1 = ix + 12 * u + np.cos(rad) * 10.0 * u
                y1 = iy + 12 * u + np.sin(rad) * 10.0 * u
                d.line([(x0, y0), (x1, y1)], fill=ink, width=sw)
        elif kind == "wind":
            d.line([(ix + 4 * u, iy + 9 * u), (ix + 16 * u, iy + 9 * u)], fill=ink, width=sw)
            d.arc([ix + 13.5 * u, iy + 4 * u, ix + 18.5 * u, iy + 9 * u], start=270, end=90, fill=ink, width=sw)
            d.line([(ix + 3 * u, iy + 13 * u), (ix + 18 * u, iy + 13 * u)], fill=ink, width=sw)
            d.arc([ix + 15.5 * u, iy + 13 * u, ix + 20.5 * u, iy + 18 * u], start=270, end=90, fill=ink, width=sw)
            d.line([(ix + 5 * u, iy + 17 * u), (ix + 13 * u, iy + 17 * u)], fill=ink, width=sw)
        elif kind == "timer":
            d.ellipse([ix + 4.5 * u, iy + 5.5 * u, ix + 19.5 * u, iy + 20.5 * u], outline=ink, width=sw)
            d.line([(ix + 12 * u, iy + 9 * u), (ix + 12 * u, iy + 13 * u), (ix + 14.8 * u, iy + 15 * u)], fill=ink, width=sw)
            d.line([(ix + 9.5 * u, iy + 3 * u), (ix + 14.5 * u, iy + 3 * u)], fill=ink, width=sw)

    # 3. 滑杆区左侧扬声器图标 (44, 320, 20x20) 与太阳亮度图标 (44, 366, 20x20)
    # Speaker icon
    sx, sy = 44 * ss, 320 * ss
    su = 20.0 * ss / 24.0
    d.polygon(
        [
            (sx + 2 * su, sy + 9 * su),
            (sx + 6 * su, sy + 9 * su),
            (sx + 11 * su, sy + 5 * su),
            (sx + 11 * su, sy + 19 * su),
            (sx + 6 * su, sy + 15 * su),
            (sx + 2 * su, sy + 15 * su),
        ],
        fill=cyan,
    )
    d.arc([sx + 10 * su, sy + 7 * su, sx + 17 * su, sy + 17 * su], start=300, end=60, fill=cyan, width=int(2.0 * su))
    d.arc([sx + 8 * su, sy + 4 * su, sx + 21 * su, sy + 20 * su], start=300, end=60, fill=cyan, width=int(2.0 * su))

    # Brightness sun icon
    bx0, by0 = 44 * ss, 366 * ss
    d.ellipse([bx0 + 7.5 * su, by0 + 7.5 * su, bx0 + 16.5 * su, by0 + 16.5 * su], fill=mint)
    for ang_deg in range(0, 360, 45):
        rad = np.deg2rad(ang_deg)
        x0 = bx0 + 12 * su + np.cos(rad) * 6.8 * su
        y0 = by0 + 12 * su + np.sin(rad) * 6.8 * su
        x1 = bx0 + 12 * su + np.cos(rad) * 9.5 * su
        y1 = by0 + 12 * su + np.sin(rad) * 9.5 * su
        d.line([(x0, y0), (x1, y1)], fill=mint, width=int(2.0 * su))

    # 4. 两条滑杆深色凹槽背景轨道 (left:118, width:264, height:10, top:325 & 371)
    for ty in (325, 371):
        d.rounded_rectangle(
            [118 * ss, ty * ss, (118 + 264) * ss, (ty + 10) * ss],
            radius=5 * ss,
            fill=(6, 12, 22, 185),
            outline=(255, 255, 255, 24),
            width=ss,
        )

    return im.resize((w, h), Image.Resampling.BOX)


def make_exact_menu_baked_bg(w: int = 480, h: int = 480, seed: int = 42) -> Image.Image:
    """1:1 烘焙 templates/screen_menu_480.html?mode=bake_bg 的静态毛玻璃底图。"""
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    rgb = _bake_aurora_stage(w, h, seed=seed)

    # 1. 顶部返回胶囊 (28, 22, 136, 56, r=17)
    rgb = _bake_glass_box(rgb, (28, 22, 136, 56), radius=17, tint_alpha=0.06, border_alpha=0.15, shadow_alpha=0.45, shadow_dy=10, shadow_blur=16)

    # 2. 2x2 毛玻璃磁贴卡片 (204x100, r=22)
    tiles = [
        (28, 68, 232, 168),
        (248, 68, 452, 168),
        (28, 182, 232, 282),
        (248, 182, 452, 282),
    ]
    for tbox in tiles:
        rgb = _bake_glass_box(rgb, tbox, radius=22, tint_alpha=0.06, border_alpha=0.15, shadow_alpha=0.55, shadow_dy=16, shadow_blur=22)

    # 3. 滑杆控制毛玻璃卡片 (28, 296, 452, 408, r=24)
    rgb = _bake_glass_box(rgb, (28, 296, 452, 408), radius=24, tint_alpha=0.058, border_alpha=0.15, shadow_alpha=0.58, shadow_dy=18, shadow_blur=24)

    # 4. 底部三联导航胶囊 (top:422, h:36, w:132, r=18)
    rgb = _bake_glass_box(rgb, (28, 422, 160, 458), radius=18, tint_alpha=0.05, border_alpha=0.13, shadow_alpha=0.40, shadow_dy=8, shadow_blur=14)
    rgb = _bake_glass_box(
        rgb,
        (174, 422, 306, 458),
        radius=18,
        tint_rgb=(70.0, 195.0, 255.0),
        tint_alpha=0.18,
        border_rgb=(53.0, 224.0, 255.0),
        border_alpha=0.52,
        shadow_alpha=0.45,
        shadow_dy=8,
        shadow_blur=14,
        glow_rgb=(53.0, 224.0, 255.0),
        glow_alpha=0.26,
    )
    rgb = _bake_glass_box(rgb, (320, 422, 452, 458), radius=18, tint_alpha=0.05, border_alpha=0.13, shadow_alpha=0.40, shadow_dy=8, shadow_blur=14)

    # 5. 四个磁贴徽章柔光晕
    badge_glows = [
        (42, 96, (53.0, 224.0, 255.0), 0.42),
        (262, 96, (123.0, 97.0, 255.0), 0.42),
        (42, 210, (45.0, 246.0, 208.0), 0.40),
        (262, 210, (255.0, 184.0, 77.0), 0.40),
    ]
    for bx, by, gcol, ga in badge_glows:
        gm = Image.new("L", (w, h), 0)
        ImageDraw.Draw(gm).ellipse([bx, by, bx + 44, by + 44], fill=255)
        g_blur = np.asarray(gm.filter(ImageFilter.GaussianBlur(radius=9)), dtype=np.float32) / 255.0
        rgb = alpha_over(rgb, np.array(gcol, dtype=np.float32)[None, None, :], g_blur * ga)

    # 6. 叠加 4x 超采样矢量图标、徽章与滑杆凹槽轨道
    icons_rgba = np.asarray(_draw_menu_vector_icons_ss(w, h), dtype=np.float32)
    rgb = alpha_over(rgb, icons_rgba[..., :3], icons_rgba[..., 3] / 255.0)

    # 7. .vignette 暗角
    dv = np.sqrt(((xx - w * 0.50) / (w * 1.20)) ** 2 + ((yy - h * 0.45) / (h * 1.00)) ** 2)
    vig_a = np.clip((dv - 0.42) / (1.0 - 0.42), 0.0, 1.0) * 0.62
    rgb = alpha_over(rgb, np.array([0.0, 0.0, 6.0])[None, None, :], vig_a)

    return Image.fromarray(np.clip(rgb + 0.5, 0, 255).astype(np.uint8), mode="RGB")


def load_font(size: int, condensed: bool = False):
    candidates = (
        [
            "/System/Library/Fonts/Supplemental/DIN Condensed Bold.ttf",
            "/System/Library/Fonts/Avenir Next Condensed.ttc",
            "/System/Library/Fonts/HelveticaNeue.ttc",
        ]
        if condensed
        else [
            "/System/Library/Fonts/PingFang.ttc",
            "/System/Library/Fonts/Hiragino Sans GB.ttc",
            "/System/Library/Fonts/STHeiti Medium.ttc",
            "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
        ]
    )
    for p in candidates:
        if Path(p).exists():
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                pass
    return ImageFont.load_default()


def build_circle_screen(baked_circle_bg: Image.Image, debug_guides: bool = False) -> Image.Image:
    """在已烘焙的圆形底图上绘制严格处于 R=206 安全区内的 UI 前景，并在 R=240 外置零。"""
    im = baked_circle_bg.convert("RGBA")
    draw = ImageDraw.Draw(im)

    f_top = load_font(12)
    f_clock = load_font(126, condensed=True)
    f_temp = load_font(38)
    f_desc = load_font(15)
    f_sub = load_font(12)
    f_kicker = load_font(11)
    f_title = load_font(20)

    draw.ellipse([134, 55, 141, 62], fill=(45, 246, 208, 255))
    draw.text((148, 51), "EVA  ONLINE", fill=(244, 248, 255, 240), font=f_top)
    draw.text((284, 51), "THU 10.22", fill=(53, 224, 255, 245), font=f_top)
    draw.text((68, 96), "09:41", fill=(244, 248, 255, 255), font=f_clock)
    draw.text((332, 104), "16°", fill=(244, 248, 255, 255), font=f_temp)
    draw.text((352, 150), "多云", fill=(159, 178, 198, 245), font=f_desc)
    draw.text((294, 174), "体感 14° · 68%", fill=(159, 178, 198, 210), font=f_sub)

    draw.ellipse([94, 298, 142, 346], fill=(42, 212, 240, 255), outline=(140, 246, 255, 200), width=2)
    draw.rounded_rectangle([114, 310, 122, 324], radius=4, fill=(6, 18, 28, 255))
    draw.text((158, 290), "LISTENING", fill=(53, 224, 255, 255), font=f_kicker)
    draw.text((158, 308), "在听你说…", fill=(244, 248, 255, 255), font=f_title)
    draw.text((158, 338), "试着说：把客厅的灯关掉", fill=(159, 178, 198, 225), font=f_sub)

    bars = [12, 24, 36, 22, 14]
    for i, bh in enumerate(bars):
        bx = 348 + i * 8
        by0 = 324 - bh // 2
        draw.rounded_rectangle([bx, by0, bx + 4, by0 + bh], radius=2, fill=(85, 228, 255, 230))

    draw.text((168, 414), "ESP32-S31 · 78%", fill=(159, 178, 198, 190), font=f_kicker)

    arr = np.asarray(im.convert("RGB"), dtype=np.uint8).copy()
    yy, xx = np.mgrid[0:480, 0:480]
    outside = ((xx - 240) ** 2 + (yy - 240) ** 2) > (239 ** 2)
    arr[outside] = np.array([4, 6, 13], dtype=np.uint8)
    res = Image.fromarray(arr, mode="RGB")

    if debug_guides:
        g_draw = ImageDraw.Draw(res)
        g_draw.ellipse([1, 1, 479, 479], outline=(255, 84, 112), width=2)
        g_draw.ellipse([34, 34, 446, 446], outline=(45, 246, 208), width=2)
    return res


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="纯 Python 分层烘焙（Chromium 不可用时的降级路径 / 圆屏设计稿生成器）",
        epilog="首选路径：bake_to_lvgl.py build（Chromium 渲染 ?mode=bake_bg，像素级同源）",
    )
    ap.add_argument("--out", default=str(PIPE_DIR / "out"), help="输出目录（默认本技能 out/）")
    ap.add_argument("--dry-run", action="store_true", help="只打印将生成的文件，不写盘")
    args = ap.parse_args(argv)
    out_dir = Path(args.out)
    if args.dry_run:
        for n in ("screen_480_baked_bg.png", "screen_menu_480_baked_bg.png",
                  "screen_480_circle.png", "screen_480_circle_debug.png"):
            print(f"[dry-run] would write {out_dir / n}")
        return 0
    out_dir.mkdir(parents=True, exist_ok=True)

    baked_sq = make_exact_css_baked_bg(480, 480, card_box=(36, 296, 444, 446), card_radius=30)
    baked_sq_path = out_dir / "screen_480_baked_bg.png"
    baked_sq.save(baked_sq_path, "PNG", optimize=True)
    print(f"baked {baked_sq_path}  480x480  {baked_sq_path.stat().st_size/1024:.1f} KB")

    baked_menu = make_exact_menu_baked_bg(480, 480)
    baked_menu_path = out_dir / "screen_menu_480_baked_bg.png"
    baked_menu.save(baked_menu_path, "PNG", optimize=True)
    print(f"baked {baked_menu_path}  480x480  {baked_menu_path.stat().st_size/1024:.1f} KB")

    baked_cir_bg = make_exact_css_baked_bg(
        480, 480, card_box=(76, 272, 404, 376), card_radius=28, include_top_dot=False, include_rail_line=False
    )
    cir_clean = build_circle_screen(baked_cir_bg, debug_guides=False)
    cir_clean_path = out_dir / "screen_480_circle.png"
    cir_clean.save(cir_clean_path, "PNG", optimize=True)
    print(f"baked {cir_clean_path}  480x480  {cir_clean_path.stat().st_size/1024:.1f} KB")

    cir_dbg = build_circle_screen(baked_cir_bg, debug_guides=True)
    cir_dbg_path = out_dir / "screen_480_circle_debug.png"
    cir_dbg.save(cir_dbg_path, "PNG", optimize=True)
    print(f"baked {cir_dbg_path}  480x480  {cir_dbg_path.stat().st_size/1024:.1f} KB")


if __name__ == "__main__":
    raise SystemExit(main())
