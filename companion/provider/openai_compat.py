from __future__ import annotations

import asyncio
import json
import logging
import random
import re
import ssl
import urllib.error
import urllib.request
from typing import Any

logger = logging.getLogger("astrbot")

# MiniMax / 部分 OpenAI 兼容 API 会把思考链标签漏进 content
_THINK_BLOCK_RE = re.compile(
    r"<mm:think>[\s\S]*?</mm:think>"
    r"|<think>[\s\S]*?</think>"
    r"|<thinking>[\s\S]*?</thinking>"
    r"|<think>[\s\S]*?</think>"
    r"|<redacted_reasoning>[\s\S]*?</redacted_reasoning>"
    r"|<think>[\s\S]*$"
    r"|<redacted_reasoning>[\s\S]*$",
    re.IGNORECASE,
)
_THINK_TAG_RE = re.compile(
    r"</?mm:think>|</?think(?:ing)?>|</?redacted_thinking>|</?redacted_reasoning>",
    re.IGNORECASE,
)
# MiniMax 部分模型会把思考链包在 ]<]minimax[>[…]<]minimax[>[ 里漏出
_MINIMAX_MARKER = r"\]<]minimax\[>\["
_MINIMAX_BLOCK_RE = re.compile(
    _MINIMAX_MARKER + r"[\s\S]*?" + _MINIMAX_MARKER,
    re.IGNORECASE,
)
_MINIMAX_TRAILING_RE = re.compile(_MINIMAX_MARKER + r"[\s\S]*$", re.IGNORECASE)
_MINIMAX_ORPHAN_RE = re.compile(_MINIMAX_MARKER, re.IGNORECASE)
# 思考链里偶发落的情绪/控制字段元数据
_THINK_META_RE = re.compile(
    r"\[情绪落点[：:][^\]\n]{0,80}\]|^情绪落点[：:].*$",
    re.IGNORECASE | re.MULTILINE,
)

# 链路抖动 / 代理掐连接时常见，可安全重试
_TRANSIENT_MARKERS = (
    "UNEXPECTED_EOF",
    "EOF occurred in violation of protocol",
    "SSLEOFError",
    "SSLV3_ALERT",
    "WRONG_VERSION_NUMBER",
    "Connection reset",
    "Connection aborted",
    "Broken pipe",
    "timed out",
    "Temporary failure",
    "Remote end closed connection",
    "Busy",
    "overloaded",
)


def sanitize_visible_text(text: str) -> str:
    """去掉模型思考链标签，避免 </mm:think> / MiniMax 思考块等漏到用户可见回复。"""
    if not text:
        return ""
    out = _THINK_BLOCK_RE.sub("", text)
    out = _THINK_TAG_RE.sub("", out)
    # MiniMax 成对标记可能嵌套/重复，循环剥到干净
    while True:
        nxt = _MINIMAX_BLOCK_RE.sub("", out)
        if nxt == out:
            break
        out = nxt
    out = _MINIMAX_TRAILING_RE.sub("", out)
    out = _MINIMAX_ORPHAN_RE.sub("", out)
    out = _THINK_META_RE.sub("", out)
    out = re.sub(r"\n{3,}", "\n\n", out)
    return out.strip()


def _is_transient(exc: BaseException) -> bool:
    msg = f"{type(exc).__name__}: {exc}"
    if any(m.lower() in msg.lower() for m in _TRANSIENT_MARKERS):
        return True
    if isinstance(exc, urllib.error.HTTPError) and exc.code in (408, 425, 500, 502, 503, 504):
        return True
    cause = getattr(exc, "__cause__", None) or getattr(exc, "__context__", None)
    if cause is not None and cause is not exc:
        return _is_transient(cause)
    return False


def is_rate_limit_error(exc: BaseException) -> bool:
    """HTTP 429 / QPM 限流；同 Provider 不应连打重试，应切换备模型。"""
    if isinstance(exc, urllib.error.HTTPError) and exc.code == 429:
        return True
    msg = str(exc)
    if "HTTP 429" in msg or "RateLimitExceeded" in msg or "qpm limit" in msg.lower():
        return True
    cause = getattr(exc, "__cause__", None) or getattr(exc, "__context__", None)
    if cause is not None and cause is not exc:
        return is_rate_limit_error(cause)
    return False


def _retry_after_sec(exc: BaseException, *, attempt: int = 1, default: float = 5.0) -> float:
    """指数退避 + 抖动；若响应带 Retry-After 则以其为下限。"""
    base = default
    http = exc if isinstance(exc, urllib.error.HTTPError) else getattr(exc, "__cause__", None)
    if isinstance(http, urllib.error.HTTPError):
        raw = http.headers.get("Retry-After") or http.headers.get("retry-after")
        if raw:
            try:
                base = max(float(raw), 1.0)
            except ValueError:
                pass
    # attempt 从 1 起：1s、2s、4s… 再加 0–40% jitter
    exp = min(8.0, float(base) * (2 ** max(0, attempt - 1)))
    jitter = exp * random.uniform(0.0, 0.4)
    return max(0.5, exp + jitter)


def _ssl_context() -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    # 部分中间盒对 TLS1.3 握手不稳，优先协商到可用套件即可
    try:
        ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    except Exception:
        pass
    return ctx


async def chat_completions_raw(
    *,
    base_url: str,
    api_key: str,
    model: str,
    messages: list[dict[str, Any]],
    timeout_sec: int = 60,
    tools: list[dict[str, Any]] | None = None,
    tool_choice: str | dict[str, Any] = "auto",
    retries: int = 3,
) -> dict[str, Any]:
    url = base_url.rstrip("/") + "/chat/completions"
    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
    }
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = tool_choice

    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
        # Cloudflare 对默认 Python-urllib UA 会直接 403/1010
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/131.0.0.0 Safari/537.36"
        ),
        "Connection": "close",
    }
    ctx = _ssl_context()

    def _post() -> dict[str, Any]:
        req = urllib.request.Request(url, data=body, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=timeout_sec, context=ctx) as resp:
            return json.loads(resp.read().decode("utf-8"))

    attempts = max(1, int(retries))
    last_err: BaseException | None = None
    for attempt in range(1, attempts + 1):
        try:
            return await asyncio.to_thread(_post)
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8", errors="replace")
            wrapped: BaseException = RuntimeError(f"HTTP {e.code}: {err_body[:500]}")
            wrapped.__cause__ = e
            last_err = wrapped
            # 429：同 Provider 不重试，交给上层切备模型或整回合降级
            if e.code == 429:
                raise wrapped from e
            if not _is_transient(e) or attempt >= attempts:
                raise wrapped from e
            logger.warning(
                "companion LLM HTTP %s 可重试，第 %s/%s 次",
                e.code,
                attempt,
                attempts,
            )
            await asyncio.sleep(_retry_after_sec(wrapped, attempt=attempt))
            continue
        except Exception as e:
            last_err = e
            if is_rate_limit_error(e):
                raise RuntimeError(str(e)) from e
            if not _is_transient(e) or attempt >= attempts:
                raise RuntimeError(str(e)) from e
            logger.warning(
                "companion LLM 瞬时错误（%s），第 %s/%s 次重试",
                e,
                attempt,
                attempts,
            )
            await asyncio.sleep(_retry_after_sec(e, attempt=attempt))
            continue

    raise RuntimeError(str(last_err) if last_err else "llm failed")


async def chat_completions(
    *,
    base_url: str,
    api_key: str,
    model: str,
    messages: list[dict[str, Any]],
    timeout_sec: int = 60,
    retries: int = 3,
) -> str:
    data = await chat_completions_raw(
        base_url=base_url,
        api_key=api_key,
        model=model,
        messages=messages,
        timeout_sec=timeout_sec,
        retries=retries,
    )
    try:
        content = data["choices"][0]["message"]["content"]
        return _content_to_text(content).strip()
    except (KeyError, IndexError, TypeError) as e:
        raise RuntimeError(f"invalid chat response: {data!r}") from e


def _content_to_text(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return sanitize_visible_text(content)
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(str(block.get("text") or ""))
        return sanitize_visible_text("\n".join(p for p in parts if p))
    return sanitize_visible_text(str(content))
