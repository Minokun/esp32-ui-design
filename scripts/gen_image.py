#!/usr/bin/env python3
"""百炼（DashScope）Qwen-Image 文生图 → 本地 PNG。**默认 dry-run，加 --run 才真实调用（计费）。**

价格参考（本机百炼账户 2026-10）：Qwen-Image-3.0 约 ¥0.18/张，turbo 系列约 ¥0.10/张。
endpoint/model 以百炼控制台「API 调用」页为准（2026-10 可能已变）。

用法:
  export DASHSCOPE_API_KEY=...        # 或放在项目根 .env
  ./gen_image.py "prompt" -o out/a.png                    # 只打印请求
  ./gen_image.py "prompt" -o out/a.png --size 1024*1024 --n 2 --run
  ./gen_image.py "prompt" -o out/a.png --model qwen-image-2.1-turbo --run

图生图/参考图：需要公网可访问的图片 URL（可先把参考图传到 OSS，项目 .env 已有 OSS 配置）。
"""
import argparse, json, os, sys, time, urllib.request
from pathlib import Path

BASE = os.environ.get("DASHSCOPE_BASE", "https://dashscope.aliyuncs.com")
PATH_IMG = os.environ.get(
    "DASHSCOPE_IMAGE_PATH",
    "/api/v1/services/aigc/multimodal-generation/generation",
)

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

def http_json(url, payload, key, timeout=120, async_mode=False):
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
    ap.add_argument("--model", default="qwen-image-3.0")
    ap.add_argument("--size", default="1024*1024")
    ap.add_argument("--n", type=int, default=1)
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--ref", default=None, help="参考图公网 URL（图生图）")
    ap.add_argument("--async-call", action="store_true", help="启用 X-DashScope-Async: enable 异步任务头")
    ap.add_argument("--run", action="store_true", help="真实调用（默认 dry-run）")
    args = ap.parse_args()

    payload = {
        "model": args.model,
        "input": {"messages": [{"role": "user", "content": [{"text": args.prompt}]}]},
        "parameters": {"size": args.size, "n": args.n},
    }
    if args.seed is not None:
        payload["parameters"]["seed"] = args.seed
    if args.ref:
        payload["input"]["messages"][0]["content"].append({"image": args.ref})

    use_async = args.async_call or ("text2image" in PATH_IMG)
    print(f"[{'RUN' if args.run else 'DRY-RUN'}] POST {BASE}{PATH_IMG} (async={use_async})")
    print(json.dumps(payload, ensure_ascii=False, indent=1)[:1200])
    if not args.run:
        print(f"\n预计费用: ¥{0.18*args.n:.2f}（按 ¥0.18/张估，以控制台为准）。确认后加 --run。")
        return

    key = api_key()
    resp = http_json(BASE + PATH_IMG, payload, key, async_mode=use_async)
    # 异步任务轮询
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
        sys.exit("没有拿到图片 URL，原始响应:\n" + json.dumps(resp, ensure_ascii=False)[:1500])
    out = Path(args.out)
    for i, u in enumerate(urls):
        p = out if i == 0 else out.with_name(f"{out.stem}_{i}{out.suffix}")
        download(u, p)

if __name__ == "__main__":
    main()
