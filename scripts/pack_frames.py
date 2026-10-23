#!/usr/bin/env python3
"""JPEG/PNG 序列 → 固件可读的 GPJM media.bin（与 esp32/*/main/media.c 格式一致）。

特性升级（2026-10-22）：
  1. 对 .jpg/.png 统一强制校验分辨率、强制转 Baseline DCT JPEG（防 ESP32-S31 硬解因 Progressive SOF2 报错）
  2. 支持 --crossfade N：自动将尾部 N 帧与头部 N 帧做线性 Alpha 融合，彻底消除 AI 视频循环接缝跳帧
  3. 自动计算并输出首末帧接缝误差（seam_mae，0~255 像素差均值），写入 media.bin.json 供 CI 门禁校验

格式（小端）:
  b'GPJM' | u32 theme_count | per theme: char name[16] | u32 frame_count | (u32 len + jpeg_bytes)*

用法:
  ./pack_frames.py frames/ --name aurora --out media.bin
  ./pack_frames.py frames/ --name aurora --out media.bin --resize 480x480 --crossfade 6
  ./pack_frames.py --theme aurora=frames_aurora --theme rainy=frames_rainy --out media.bin
"""
import argparse, io, json, os, struct, sys, zlib
from pathlib import Path
import numpy as np
from PIL import Image

MAGIC = b"GPJM"

def load_images(d: Path, resize: str | None) -> list[Image.Image]:
    exts = {".jpg", ".jpeg", ".png", ".webp"}
    files = sorted(p for p in d.iterdir() if p.suffix.lower() in exts)
    if not files:
        sys.exit(f"目录里没有图片: {d}")
    target_size = None
    if resize:
        w, h = map(int, resize.lower().split("x"))
        target_size = (w, h)
    imgs = []
    for p in files:
        im = Image.open(p)
        if im.mode in ("RGBA", "LA"):
            # 合成到深空底色 #04060D，避免透明通道转 RGB 出现黑/白噪边
            bg = Image.new("RGB", im.size, (4, 6, 13))
            bg.paste(im, mask=im.split()[-1])
            im = bg
        else:
            im = im.convert("RGB")
        if target_size and im.size != target_size:
            im = im.resize(target_size, Image.LANCZOS)
        imgs.append(im)
    # 校验同主题内所有帧尺寸一致且为偶数（硬件 JPEG 解码要求）
    w0, h0 = imgs[0].size
    if (w0 % 2 != 0) or (h0 % 2 != 0):
        sys.exit(f"分辨率必须为偶数（ESP32-S31 JPEG 硬解限制）: 当前 {w0}x{h0}")
    for i, im in enumerate(imgs):
        if im.size != (w0, h0):
            sys.exit(f"第 {i} 帧尺寸 {im.size} 与首帧 {(w0, h0)} 不一致，请加 --resize {w0}x{h0}")
    return imgs

def apply_crossfade(imgs: list[Image.Image], k: int) -> list[Image.Image]:
    """将尾部 k 帧淡入到头部 k 帧，输出完美无缝闭环的 N-k 帧序列。"""
    if k <= 0:
        return imgs
    if len(imgs) < k * 2 + 2:
        sys.exit(f"总帧数 {len(imgs)} 太少，无法做 --crossfade {k}（至少需要 {k*2+2} 帧）")
    head = imgs[:k]
    middle = imgs[k:-k]
    tail = imgs[-k:]
    blended_head = []
    for i in range(k):
        # i=0 时 tail[0] 权重高，逐渐过渡到 head[i]
        alpha = (i + 1) / (k + 1)
        blended_head.append(Image.blend(tail[i], head[i], alpha))
    return blended_head + middle

def encode_baseline_jpeg(im: Image.Image, quality: int) -> bytes:
    buf = io.BytesIO()
    # 严禁 progressive=True，确保输出 SOF0 Baseline DCT 供 ESP32-S31 硬件解码
    im.save(buf, "JPEG", quality=quality, subsampling=2, optimize=True, progressive=False)
    data = buf.getvalue()
    # 双重校验不存在 SOF2 (0xFFC2) 标记
    if b"\xff\xc2" in data[:512]:
        sys.exit("检测到 Progressive JPEG (SOF2)，硬件解码器不支持")
    return data

def calc_seam_mae(imgs: list[Image.Image]) -> float:
    if len(imgs) < 2:
        return 0.0
    a = np.asarray(imgs[0], dtype=np.float32)
    b = np.asarray(imgs[-1], dtype=np.float32)
    return float(np.abs(a - b).mean())

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("frames", nargs="?", help="单主题帧目录")
    ap.add_argument("--name", default="theme", help="单主题名（≤15 字节）")
    ap.add_argument("--theme", action="append", default=[], help="name=dir，可重复")
    ap.add_argument("--out", required=True)
    ap.add_argument("--quality", type=int, default=75)
    ap.add_argument("--resize", default=None, help="强制缩放到 WxH，例如 480x480 或 180x180")
    ap.add_argument("--crossfade", type=int, default=0, help="首尾交叉淡化帧数（消除视频循环跳帧，建议 4~8）")
    ap.add_argument("--max-frames", type=int, default=96)
    ap.add_argument("--budget-mb", type=float, default=8.0)
    args = ap.parse_args()

    themes = []
    if args.theme:
        for spec in args.theme:
            name, _, d = spec.partition("=")
            themes.append((name, Path(d)))
    elif args.frames:
        themes.append((args.name, Path(args.frames)))
    else:
        sys.exit("需要 frames 目录或 --theme name=dir")

    blob = bytearray(MAGIC)
    blob += struct.pack("<I", len(themes))
    index = {"format": "GPJM/2-baseline-checked", "themes": []}
    for name, d in themes:
        imgs = load_images(d, args.resize)
        raw_seam = calc_seam_mae(imgs)
        if args.crossfade > 0:
            imgs = apply_crossfade(imgs, args.crossfade)
        final_seam = calc_seam_mae(imgs)
        if len(imgs) > args.max_frames:
            sys.exit(f"{name}: {len(imgs)} 帧 > max {args.max_frames}（固件缓冲区上限）")
        w0, h0 = imgs[0].size
        frames = [encode_baseline_jpeg(im, args.quality) for im in imgs]
        raw = name.encode()[:15].ljust(16, b"\0")
        blob += raw + struct.pack("<I", len(frames))
        entries = []
        for i, data in enumerate(frames):
            blob += struct.pack("<I", len(data)) + data
            entries.append({"i": i, "bytes": len(data), "crc32": zlib.crc32(data)})
        total = sum(e["bytes"] for e in entries)
        index["themes"].append({
            "name": name,
            "resolution": f"{w0}x{h0}",
            "frames": len(frames),
            "bytes": total,
            "crossfade_frames": args.crossfade,
            "seam_mae_before": round(raw_seam, 2),
            "seam_mae_after": round(final_seam, 2),
            "entries": entries,
        })
        print(
            f"  {name} ({w0}x{h0}): {len(frames)} 帧, {total/1024:.1f} KB, "
            f"平均 {total/len(frames)/1024:.1f} KB/帧, "
            f"首尾接缝差 MAE: {raw_seam:.2f} -> {final_seam:.2f}/255"
        )

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(blob)
    index["total_bytes"] = len(blob)
    out.with_suffix(out.suffix + ".json").write_text(json.dumps(index, ensure_ascii=False, indent=1))
    mb = len(blob) / 1024 / 1024
    print(f"-> {out}  {mb:.3f} MB  ({len(themes)} 主题)")
    if mb > args.budget_mb:
        sys.exit(f"超出预算 {args.budget_mb} MB")

if __name__ == "__main__":
    main()
