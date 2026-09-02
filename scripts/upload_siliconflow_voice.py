#!/usr/bin/env python3
"""上传参考音频到硅基流动，拿到 speech:… 音色 uri。

用法（在插件根或任意目录）:
  set SILICONFLOW_API_KEY=sk-...
  python scripts/upload_siliconflow_voice.py path/to/ref.mp3 --text "参考音频里说的原话" --name aemeath

说明:
  - 官网一般没有「上传模型」按钮；CosyVoice 是平台托管模型，你只上传 8~10 秒参考人声。
  - 自定义音色通常需要实名认证。
  - 成功后把打印的 uri 填进 AstrBot 面板「语音音色ID」。
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path


def main() -> int:
    p = argparse.ArgumentParser(description="Upload reference voice to SiliconFlow")
    p.add_argument("audio", type=Path, help="参考音频路径（mp3/wav，建议 8~10 秒）")
    p.add_argument("--text", required=True, help="参考音频对应的口播原文（必须对齐）")
    p.add_argument("--name", default="aemeath", help="自定义音色名 customName")
    p.add_argument(
        "--model",
        default="FunAudioLLM/CosyVoice2-0.5B",
        help="TTS 模型名",
    )
    p.add_argument(
        "--base",
        default=os.getenv("SILICONFLOW_BASE_URL", "https://api.siliconflow.cn/v1"),
        help="API 根地址",
    )
    p.add_argument(
        "--key",
        default=os.getenv("SILICONFLOW_API_KEY", ""),
        help="API Key（默认读环境变量 SILICONFLOW_API_KEY）",
    )
    args = p.parse_args()

    if not args.key.strip():
        print("缺少 API Key：设 SILICONFLOW_API_KEY 或传 --key", file=sys.stderr)
        return 2
    if not args.audio.is_file():
        print(f"找不到音频: {args.audio}", file=sys.stderr)
        return 2

    raw = args.audio.read_bytes()
    mime = mimetypes.guess_type(str(args.audio))[0] or "audio/mpeg"
    # multipart 手写太烦，用 JSON+base64（官方也支持）
    import base64

    b64 = base64.b64encode(raw).decode("ascii")
    payload = {
        "model": args.model,
        "customName": args.name,
        "text": args.text,
        "audio": f"data:{mime};base64,{b64}",
    }
    url = args.base.rstrip("/") + "/uploads/audio/voice"
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "Authorization": f"Bearer {args.key.strip()}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")
        print(f"HTTP {e.code}: {detail}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"failed: {e}", file=sys.stderr)
        return 1

    uri = data.get("uri") or ""
    print(json.dumps(data, ensure_ascii=False, indent=2))
    if uri:
        print("\n把下面这一行填进面板「语音音色ID」:")
        print(uri)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
