#!/usr/bin/env python3
"""ASTRO 深空宇航员页资产打包：把 Chromium 同源烘焙的 space 背景替换进 EVA4 资产包。

用法：
    ./scripts/bake_space_asset.py                 # 生成 main/assets/eva_face3.bin（备份旧包）
    ./scripts/bake_space_asset.py --out /tmp/eva.bin

输入（已由 render_frame.sh 渲染）：
    out/space_480_baked_bg.png   正常态背景（?mode=bake_bg）
    out/space_480_warp_bg.png    跃迁态背景（?mode=bake_bg&warp=1）

输出：
    <demo_main>/assets/eva_face3.bin  EVA4：bg0=正常态 / bg1=跃迁态 / orb 帧沿用旧包
"""
from __future__ import annotations

import argparse
import shutil
import struct
import sys
from pathlib import Path

import numpy as np
from PIL import Image

PIPE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PIPE_DIR / "scripts"))
import bake_to_lvgl as bake  # noqa: E402

UI_W = UI_H = 480
BG_SZ = UI_W * UI_H * 2


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=None, help="输出 eva bin 路径（默认写固件 assets）")
    ap.add_argument("--demo-main", default=None, help="固件 main 目录")
    args = ap.parse_args()

    demo_main = Path(args.demo_main).resolve() if args.demo_main else bake.find_demo_main()
    assets = demo_main / "assets"
    old = assets / "eva_face3.bin"
    if not old.is_file():
        print(f"缺少旧资产包（提供 orb 帧）：{old}", file=sys.stderr)
        return 2
    raw = old.read_bytes()
    if raw[:4] != b"EVA4" or len(raw) < 16 + 2 * BG_SZ:
        print("旧资产包不是 EVA4 格式", file=sys.stderr)
        return 2
    orb = raw[16 + 2 * BG_SZ:]
    header = raw[4:16]
    w, h, ow, oh, on, bgs = struct.unpack("<HHHHHH", header)
    print(f"[space] 旧包: {w}x{h} orb={ow}x{oh}x{on} bg_count={bgs} orb_bytes={len(orb)}")

    normal = PIPE_DIR / "out" / "space_480_baked_bg.png"
    warp = PIPE_DIR / "out" / "space_480_warp_bg.png"
    for p in (normal, warp):
        if not p.is_file():
            print(f"缺少输入：{p}（先跑 render_frame.sh）", file=sys.stderr)
            return 2

    bgs_bytes = []
    for name, p in (("normal", normal), ("warp", warp)):
        im = Image.open(p).convert("RGB")
        if im.size != (UI_W, UI_H):
            print(f"{p} 尺寸 {im.size} != 480x480", file=sys.stderr)
            return 2
        rgb = np.asarray(im).astype(np.int16)
        c565 = bake.rgb888_to_rgb565_dither(rgb).astype("<u2")
        bgs_bytes.append(c565.tobytes())
        print(f"[space] {name}: {p.name} -> RGB565 dithered {len(bgs_bytes[-1])/1024:.1f}KB")

    out = Path(args.out).resolve() if args.out else assets / "eva_face3.bin"
    if out == old:
        backup = out.with_suffix(".bin.bak-eva-design")
        if not backup.exists():
            shutil.copy2(old, backup)
            print(f"[space] 已备份旧 EVA 设计资产: {backup}")
    data = b"EVA4" + header + bgs_bytes[0] + bgs_bytes[1] + orb
    out.write_bytes(data)
    print(f"[space] 写入 {out}: {len(data)/1024:.1f}KB (2x bg + {len(orb)/1024:.1f}KB orb)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
