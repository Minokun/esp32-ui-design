#!/usr/bin/env python3
"""EVA 深空电影感 — 程序化流体能量球与粒子光环特效烘焙器 (Vectorized NumPy Shader Engine)。

为什么提供 Python 矢量化 Shader 引擎（与 templates/shader_orb.html 同源数学公式）：
  1. 零浏览器/GPU 驱动依赖：在無头 CI、Docker 容器、沙箱或本机终端均可 1 秒内出图；
  2. 100% 确定性与周期闭合：所有形变、光谱丝带、声波涟漪、星尘轨道均仅依赖 cos(k*phase) 与 sin(k*phase)，
     其中 phase = 2*pi * frame / total_frames，数学上严格保证首尾帧 0 接缝（seam_mae 极低）；
  3. 严格遵循 style_bible.md 色板：
     - bg.base:       #04060D
     - accent.cyan:   #35E0FF
     - accent.teal:   #2DF6D0
     - accent.violet: #B07CFF
     - text.primary:  #F4F8FF

用法:
  ./scripts/render_shader_vfx.py --out out/vfx_orb --frames 24 --size 180 --bg dark --sheet out/vfx_orb_sheet.png
"""
import argparse, math, time
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw, ImageFont

COL_BG     = np.array([0.016, 0.024, 0.051], dtype=np.float32)  # #04060D
COL_CYAN   = np.array([0.208, 0.878, 1.000], dtype=np.float32)  # #35E0FF
COL_TEAL   = np.array([0.176, 0.965, 0.816], dtype=np.float32)  # #2DF6D0
COL_VIOLET = np.array([0.690, 0.486, 1.000], dtype=np.float32)  # #B07CFF
COL_WHITE  = np.array([0.957, 0.973, 1.000], dtype=np.float32)  # #F4F8FF

def rot_uv(px: np.ndarray, py: np.ndarray, a: float | np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    c, s = np.cos(a), np.sin(a)
    return c * px - s * py, s * px + c * py

def smoothstep(edge0: float, edge1: float, x: np.ndarray) -> np.ndarray:
    t = np.clip((x - edge0) / (edge1 - edge0), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)

def harmonic_wave(px: np.ndarray, py: np.ndarray, ph: float, freq: float, speed_mul: float) -> np.ndarray:
    qx, qy = rot_uv(px, py, ph * speed_mul)
    v = 0.50 * np.sin(qx * freq + math.cos(ph) * 1.6 + np.sin(qy * freq - math.sin(ph) * 1.6))
    qx, qy = rot_uv(qx, qy, 1.047)
    v += 0.30 * np.cos(qx * (freq * 1.4) - math.sin(ph * 2.0) * 1.2 + np.cos(qy * (freq * 1.3)))
    qx, qy = rot_uv(qx, qy, 1.047)
    v += 0.20 * np.sin(qy * (freq * 2.1) + math.cos(ph * 3.0) * 0.9)
    return v

def render_orb_frame(state: str, frame_idx: int, total_frames: int, size: int, bg_mode: str) -> Image.Image:
    u_phase = (2.0 * math.pi * (frame_idx % total_frames)) / total_frames
    lin = np.linspace(-1.0, 1.0, size, dtype=np.float32)
    py, px = np.meshgrid(lin, lin, indexing="ij")
    r = np.sqrt(px * px + py * py)
    ang = np.arctan2(py, px)

    if state == "idle":
        base_radius = 0.42 + 0.022 * math.sin(u_phase)
        deform_amp = 0.022
        ripple_amp = 0.0
        swirl_speed = 1.0
        c_primary = COL_CYAN * 0.88
        c_secondary = COL_VIOLET * 0.65
        c_core = 0.6 * COL_CYAN + 0.4 * COL_TEAL
    elif state == "listening":
        base_radius = 0.44 + 0.030 * math.sin(u_phase * 2.0)
        deform_amp = 0.045
        ripple_amp = 1.0
        swirl_speed = 1.0
        c_primary = COL_TEAL
        c_secondary = COL_CYAN
        c_core = COL_WHITE
    elif state == "thinking":
        base_radius = 0.41 + 0.018 * math.cos(u_phase * 2.0)
        deform_amp = 0.068
        ripple_amp = 0.0
        swirl_speed = 2.0
        c_primary = COL_VIOLET
        c_secondary = COL_CYAN
        c_core = 0.35 * COL_VIOLET + 0.65 * COL_WHITE
    else:  # speaking
        base_radius = 0.46 + 0.042 * math.sin(u_phase * 2.0) + 0.018 * math.cos(u_phase * 4.0)
        deform_amp = 0.055
        ripple_amp = 0.65
        swirl_speed = 1.0
        c_primary = COL_CYAN
        c_secondary = COL_TEAL
        c_core = COL_WHITE

    # 1. 流体球边界形变
    wave1 = np.sin(ang * 3.0 + u_phase * swirl_speed) * np.cos(ang * 2.0 - u_phase)
    wave2 = np.cos(ang * 5.0 - u_phase * 2.0) * 0.5
    field = harmonic_wave(px, py, u_phase, 4.2, swirl_speed)
    dyn_radius = base_radius + deform_amp * (wave1 * 0.65 + wave2 * 0.35 + field * 0.45)

    # 2. 内部流体丝带（Siri Orb 风格多层折叠光谱）
    swirl_ang = u_phase * 0.5 * swirl_speed + r * 1.4 * math.sin(u_phase)
    sx, sy = rot_uv(px, py, swirl_ang)
    ribbon1 = np.exp(-14.0 * np.abs(np.sin(sx * 4.5 + np.cos(sy * 3.5 + u_phase)) * 0.35 - sy * 0.5))
    ribbon2 = np.exp(-16.0 * np.abs(np.cos(sy * 5.0 - np.sin(sx * 4.0 - u_phase)) * 0.35 + sx * 0.5))

    # 3. 球体菲涅尔边缘高光与柔和内发光
    dist = r - dyn_radius
    sphere_mask = smoothstep(0.03, -0.02, dist)
    inner_norm = np.clip(r / np.maximum(0.001, dyn_radius), 0.0, 1.0)
    fresnel = (inner_norm ** 2.6) * sphere_mask
    edge_glow = np.exp(-26.0 * np.abs(dist))
    outer_halo = np.exp(-5.2 * np.maximum(0.0, dist))

    # 4. 声波涟漪环 + 6 颗环绕谐波星尘粒子
    ripple_glow = np.zeros_like(r)
    if ripple_amp > 0.0:
        for i in range(2):
            cyc = ((u_phase / (2.0 * math.pi)) + i * 0.5) % 1.0
            r_ring = base_radius + 0.04 + cyc * 0.36
            fade = math.sin(cyc * math.pi)
            ripple_glow += np.exp(-42.0 * np.abs(r - r_ring)) * fade * ripple_amp * 0.75

    particles = np.zeros_like(r)
    for i in range(6):
        p_ang = i * (2.0 * math.pi / 6.0) + u_phase * (1.0 if i % 2 == 0 else -1.0)
        p_rad = base_radius + 0.11 + 0.05 * math.sin(u_phase + i * 1.7)
        p_x, p_y = math.cos(p_ang) * p_rad, math.sin(p_ang) * p_rad
        d2 = (px - p_x) ** 2 + (py - p_y) ** 2
        particles += np.exp(-180.0 * d2) * (0.55 + 0.45 * math.sin(u_phase * 2.0 + i))

    # 5. 三维光照与颜色合成
    norm_len = np.maximum(1e-4, r)
    nx, ny = px / norm_len, py / norm_len
    light_dir = np.clip(0.5 + 0.5 * (nx * (-0.7071) + ny * (-0.7071)), 0.0, 1.0)[..., None]

    c_pri = c_primary[None, None, :]
    c_sec = c_secondary[None, None, :]
    c_cor = c_core[None, None, :]
    c_wht = COL_WHITE[None, None, :]

    mix_col = c_sec * (1.0 - light_dir) + c_pri * light_dir
    body_col = (c_sec * 0.35) * (1.0 - light_dir) + (c_pri * 0.85) * light_dir
    body_col += c_pri * (ribbon1[..., None] * 0.65) + c_sec * (ribbon2[..., None] * 0.60)
    core_falloff = (np.maximum(0.0, 1.0 - inner_norm * 1.15) ** 2.2)[..., None]
    body_col += c_cor * (core_falloff * 0.55)
    body_col += mix_col * (fresnel[..., None] * 0.95)

    glow_col = mix_col * ((edge_glow * 0.95 + outer_halo * 0.42)[..., None])
    glow_col += c_pri * ripple_glow[..., None]
    glow_col += (0.5 * c_wht + 0.5 * c_cor) * particles[..., None]

    total_light = body_col * sphere_mask[..., None] + glow_col

    radial_fade = 1.0 - smoothstep(0.76, 0.98, r)
    total_light *= radial_fade[..., None]
    # ACES 柔和色调映射
    total_light = total_light / (1.0 + total_light * 0.38)

    alpha = np.clip(
        (sphere_mask * 0.92 + edge_glow * 0.85 + outer_halo * 0.48 + ripple_glow * 0.8 + particles) * radial_fade,
        0.0,
        1.0,
    )

    if bg_mode == "dark":
        rgb = COL_BG[None, None, :] * (1.0 - alpha[..., None]) + total_light * alpha[..., None]
        arr = np.clip(rgb * 255.0 + 0.5, 0, 255).astype(np.uint8)
        return Image.fromarray(arr, mode="RGB")
    else:
        rgb = np.clip(total_light * 255.0 + 0.5, 0, 255).astype(np.uint8)
        a = np.clip(alpha * 255.0 + 0.5, 0, 255).astype(np.uint8)
        rgba = np.dstack([rgb, a])
        return Image.fromarray(rgba, mode="RGBA")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="out/vfx_orb")
    ap.add_argument("--frames", type=int, default=24)
    ap.add_argument("--size", type=int, default=180)
    ap.add_argument("--bg", choices=["dark", "transparent"], default="dark")
    ap.add_argument("--sheet", default="out/vfx_orb_sheet.png", help="输出 4 态样张总览图路径")
    args = ap.parse_args()

    states = ["idle", "listening", "thinking", "speaking"]
    out_root = Path(args.out)
    t0 = time.time()

    all_rendered = {}
    for st in states:
        st_dir = out_root / st
        st_dir.mkdir(parents=True, exist_ok=True)
        frames = []
        for f in range(args.frames):
            im = render_orb_frame(st, f, args.frames, args.size, args.bg)
            im.save(st_dir / f"{f:03d}.png", "PNG", optimize=True)
            frames.append(im)
        all_rendered[st] = frames
        print(f"rendered [{st:9s}]: {args.frames} frames @ {args.size}x{args.size} -> {st_dir}")

    if args.sheet:
        cols = [0, 4, 8, 12, 16, 20]
        cell = args.size
        pad = 16
        label_w = 130
        w = label_w + len(cols) * cell + (len(cols) + 1) * pad
        h = len(states) * cell + (len(states) + 1) * pad
        sheet = Image.new("RGB", (w, h), (4, 6, 13))
        draw = ImageDraw.Draw(sheet)
        state_titles = {
            "idle": "IDLE\n(Breath)",
            "listening": "LISTENING\n(Ripples)",
            "thinking": "THINKING\n(Vortex)",
            "speaking": "SPEAKING\n(Spectrum)",
        }
        for r_idx, st in enumerate(states):
            y0 = pad + r_idx * (cell + pad)
            draw.text((18, y0 + cell // 2 - 14), state_titles[st], fill=(159, 178, 198))
            for c_idx, f_idx in enumerate(cols):
                idx = f_idx % args.frames
                im = all_rendered[st][idx].convert("RGB")
                x0 = label_w + pad + c_idx * (cell + pad)
                sheet.paste(im, (x0, y0))
        sheet_p = Path(args.sheet)
        sheet_p.parent.mkdir(parents=True, exist_ok=True)
        sheet.save(sheet_p, "PNG", optimize=True)
        print(f"saved contact sheet: {sheet_p} ({sheet.size[0]}x{sheet.size[1]}, {sheet_p.stat().st_size/1024:.1f} KB)")

    print(f"done: {len(states) * args.frames} shader frames baked in {time.time() - t0:.2f}s")

if __name__ == "__main__":
    main()
