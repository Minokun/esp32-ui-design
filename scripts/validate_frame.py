#!/usr/bin/env python3
"""设计稿 ↔ 实现截图 像素比对 + 素材预算检查 + 圆形屏安全区越界检查。

用法:
  ./validate_frame.py design.png render.png                           # 比对（差异比例默认阈值 3%）
  ./validate_frame.py --size 480x480 --budget-kb 300 shot.png         # 单图体检
  ./validate_frame.py --safe-circle 240 shot.png                      # 检查 R=240 圆外是否有高对比 UI 像素被物理裁切
"""
import argparse, sys
from pathlib import Path
import numpy as np
from PIL import Image

def load(p):
    return np.asarray(Image.open(p).convert("RGB"), dtype=np.int16)

def check_safe_circle(arr: np.ndarray, radius: int, lum_threshold: int = 85) -> tuple[float, int]:
    """检测距离画布中心 > radius 的区域内，亮度高于阈值的 UI 前景像素占比。"""
    h, w, _ = arr.shape
    cy, cx = h / 2.0, w / 2.0
    yy, xx = np.ogrid[:h, :w]
    dist = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2)
    outside = dist > radius
    # 计算感知亮度
    lum = 0.299 * arr[:, :, 0] + 0.587 * arr[:, :, 1] + 0.114 * arr[:, :, 2]
    clipped_fg = outside & (lum > lum_threshold)
    cnt = int(clipped_fg.sum())
    ratio = float(cnt / max(1, int(outside.sum())))
    return ratio, cnt

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("a"); ap.add_argument("b", nargs="?")
    ap.add_argument("--threshold", type=int, default=14, help="单通道差 > 该值算不同像素")
    ap.add_argument("--max-diff", type=float, default=0.03, help="允许的差异像素比例")
    ap.add_argument("--size", default=None, help="WxH")
    ap.add_argument("--budget-kb", type=float, default=None)
    ap.add_argument("--safe-circle", type=int, default=None, help="校验圆屏安全半径 R（如 240 或 206），检测圆外是否有高亮 UI 文字/元素被裁切")
    args = ap.parse_args()

    pa = Path(args.a)
    if not pa.exists():
        sys.exit(f"文件不存在: {pa}")
    ia = Image.open(pa)
    kb = pa.stat().st_size / 1024
    print(f"A: {pa}  {ia.size[0]}x{ia.size[1]}  {kb:.1f} KB")
    if args.size:
        w, h = map(int, args.size.lower().split("x"))
        if ia.size != (w, h):
            sys.exit(f"尺寸不符: 期望 {w}x{h}")
    if args.budget_kb is not None and kb > args.budget_kb:
        sys.exit(f"体积超预算: {kb:.1f} > {args.budget_kb} KB")

    arr_a = load(pa)
    if args.safe_circle is not None:
        ratio, cnt = check_safe_circle(arr_a, args.safe_circle)
        print(f"圆屏安全区检查 (R={args.safe_circle}px): 圆外高亮前景像素 = {cnt} px ({ratio*100:.2f}%)")
        if cnt > 120:
            sys.exit(f"未通过圆屏安全区检查: R={args.safe_circle}px 外存在 {cnt} 个高亮 UI 像素，上圆屏会被物理切边！请使用 ?shape=circle 布局。")

    if not args.b:
        q = ia.convert("RGB").quantize(colors=8, method=Image.MEDIANCUT).convert("RGB")
        cols = q.getcolors()
        print("主色:", ", ".join(f"#{r:02X}{g:02X}{b:02X}×{n}" for n, (r, g, b) in sorted(cols, reverse=True)[:6]))
        print("PASS")
        return

    pb = Path(args.b); ib = Image.open(pb)
    print(f"B: {pb}  {ib.size[0]}x{ib.size[1]}  {pb.stat().st_size/1024:.1f} KB")
    if ia.size != ib.size:
        sys.exit(f"尺寸不同: {ia.size} vs {ib.size}")
    a, b = arr_a, load(pb)
    d = np.abs(a - b).max(axis=2)
    ratio = float((d > args.threshold).mean())
    print(f"差异像素 {ratio*100:.2f}%  平均绝对差 {np.abs(a-b).mean():.2f}/255")
    if ratio > args.max_diff:
        sys.exit(f"未通过: 差异 {ratio*100:.2f}% > {args.max_diff*100:.1f}%（检查布局/颜色/字体）")
    print("PASS")

if __name__ == "__main__":
    main()
