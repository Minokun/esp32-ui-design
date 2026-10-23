#!/usr/bin/env python3
"""百炼（DashScope）万相 Wan 文生视频/图生视频 → 本地 MP4。**默认 dry-run，加 --run 才真实调用（计费）。**

价格参考（本机百炼账户 2026-10）：Wan3.0-Video 480P 约 ¥0.3/秒，720P ¥0.6/秒。
endpoint/model 以百炼控制台「API 调用」页为准（2026-10 可能已变）。

用法:
  export DASHSCOPE_API_KEY=...        # 或放在项目根 .env
  ./gen_video.py "prompt" -o out/a.mp4                    # 只打印请求
  ./gen_video.py "prompt" -o out/a.mp4 --duration 5 --resolution 480P --run
  ./gen_video.py "prompt" -o out/a.mp4 --image https://.../first.png --last-frame https://.../first.png --run

图生视频/首尾同帧闭环：需要公网可访问的图片 URL（可先把参考图传到 OSS，项目 .env 已有 OSS 配置）。
"""
import argparse, json, os, sys, time, urllib.request
from pathlib import Path

BASE = os.environ.get("DASHSCOPE_BASE", "https://dashscope.aliyuncs.com")
PATH_VID = os.environ.get(
    "DASHSCOPE_VIDEO_PATH",
    "/api/v1/services/aigc/video-generation/video-synthesis",
)  # 注意：绝不回落到 DASHSCOPE_IMAGE_PATH，否则视频请求会被 POST 到图像 endpoint

def api_key():
    k = os.environ.get("DASHSCOPE_API_KEY")
    if k:
        return k
    env = Path(__file__).resolve().parents[4] / ".env"
    if env.exists():
        for line in env.read_text(errors="ignore").splitlines():
            if line.startswith("DASHSCOPE_API_KEY="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    sys.exit("缺少 DASHSCOPE_API_KEY（环境变量或项目根 .env）")

def http_json(url, payload, key, timeout=120, async_mode=True):
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {key}",
    }
    if async_mode:
        headers["X-DashScope-Async"] = "enable"
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode(), headers=headers
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())

def download(url, out: Path):
    out.parent.mkdir(parents=True, exist_ok=True)
    urllib.request.urlretrieve(url, out)
    print(f"saved {out}  {out.stat().st_size/1024:.1f} KB")

def extract_urls(resp):
    out = resp.get("output") or {}
    urls = []
    for ch in (out.get("choices") or []):
        for c in (ch.get("message") or {}).get("content") or []:
            if isinstance(c, dict) and c.get("image"):
                urls.append(c["image"])
    for r in (out.get("results") or []):
        if r.get("url"):
            urls.append(r["url"])
    if out.get("video_url"):
        urls.append(out["video_url"])
    return urls

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("prompt")
    ap.add_argument("-o", "--out", required=True)
    ap.add_argument("--model", default="wan3.0-video")
    ap.add_argument("--resolution", default="480P")
    ap.add_argument("--duration", type=int, default=5)
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--image", "--first-frame", dest="image", default=None, help="首帧图公网 URL（图生视频）")
    ap.add_argument("--last-frame", default=None, help="尾帧图公网 URL（首尾同图可强制无缝循环闭环）")
    ap.add_argument("--run", action="store_true", help="真实调用（默认 dry-run）")
    args = ap.parse_args()

    payload = {
        "model": args.model,
        "input": {"prompt": args.prompt},
        "parameters": {"resolution": args.resolution, "duration": args.duration},
    }
    if args.seed is not None:
        payload["parameters"]["seed"] = args.seed
    if args.image:
        payload["input"]["img_url"] = args.image
    if args.last_frame:
        payload["input"]["last_frame_url"] = args.last_frame

    print(f"[{'RUN' if args.run else 'DRY-RUN'}] POST {BASE}{PATH_VID} (X-DashScope-Async: enable)")
    print(json.dumps(payload, ensure_ascii=False, indent=1)[:1200])
    if not args.run:
        print(f"\n预计费用: ¥{0.3*args.duration:.2f}（按 480P ¥0.3/秒估，以控制台为准）。确认后加 --run。")
        if args.image or args.last_frame:
            print("⚠ 首尾帧字段（img_url / last_frame_url）请以百炼控制台当前 API 文档为准，"
                  "首次 --run 建议先用最短时长验证一次。")
        return

    key = api_key()
    resp = http_json(BASE + PATH_VID, payload, key, async_mode=True)
    # 异步任务
    if (resp.get("output") or {}).get("task_id"):
        tid = resp["output"]["task_id"]
        print("task:", tid)
        for _ in range(120):
            time.sleep(3)
            req = urllib.request.Request(f"{BASE}/api/v1/tasks/{tid}",
                                         headers={"Authorization": f"Bearer {key}"})
            with urllib.request.urlopen(req, timeout=60) as f:
                r = json.loads(f.read().decode())
            st = (r.get("output") or {}).get("task_status")
            if st in ("SUCCEEDED", "FAILED", "CANCELED"):
                resp = r
                break
        else:
            sys.exit("任务超时")

    urls = extract_urls(resp)
    if not urls:
        sys.exit("没有拿到视频 URL，原始响应:\n" + json.dumps(resp, ensure_ascii=False)[:1500])
    out = Path(args.out)
    for i, u in enumerate(urls):
        p = out if i == 0 else out.with_name(f"{out.stem}_{i}{out.suffix}")
        download(u, p)

if __name__ == "__main__":
    main()
