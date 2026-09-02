"""SillyTavern 风格 Character Book（轻量）：关键词命中才注入设定条目。

兼容 chara_card_v2 / ST World Info 常见字段子集：
keys / content / enabled / insertion_order / case_sensitive /
selective / secondary_keys / constant / position / name / priority

V1 不做：递归扫描、复杂 selectiveLogic 枚举、正则 key、跨卡全局书。
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Any, Iterable

import yaml

from .sanitize import sanitize

logger = logging.getLogger("astrbot")


@dataclass
class BookEntry:
    keys: list[str] = field(default_factory=list)
    content: str = ""
    enabled: bool = True
    insertion_order: int = 100
    case_sensitive: bool = False
    selective: bool = False
    secondary_keys: list[str] = field(default_factory=list)
    constant: bool = False
    position: str = "after_char"  # before_char | after_char
    name: str = ""
    priority: int = 10  # 越大越优先保留（预算不足时）
    id: int | str | None = None


@dataclass
class CharacterBook:
    name: str = ""
    description: str = ""
    scan_depth: int = 6  # 扫描「本条 + 近邻上文」条数上限
    # ST 叫 token_budget；本插件按「注入汉字/字符」预算使用（CJK 友好）
    token_budget: int = 800
    recursive_scanning: bool = False
    entries: list[BookEntry] = field(default_factory=list)
    extensions: dict[str, Any] = field(default_factory=dict)


def load_character_book(path: str, *, max_bytes: int = 80000) -> CharacterBook | None:
    """从 yaml/json 文件加载；失败返回 None（不阻断卡加载）。"""
    if not path or not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = f.read()
        raw = sanitize(raw, max_bytes=max_bytes)
        data = yaml.safe_load(raw) or {}
    except Exception as e:
        logger.warning("角色书加载失败 path=%s err=%s", path, e)
        return None

    if not isinstance(data, dict):
        return None

    # 兼容：整卡 chara_card_v2 里嵌套的 data.character_book
    if "entries" not in data and isinstance(data.get("data"), dict):
        nested = data["data"].get("character_book")
        if isinstance(nested, dict):
            data = nested

    entries_raw = data.get("entries")
    entries: list[BookEntry] = []
    if isinstance(entries_raw, list):
        for i, item in enumerate(entries_raw):
            ent = _parse_entry(item, fallback_id=i)
            if ent is not None:
                entries.append(ent)
    elif isinstance(entries_raw, dict):
        # ST 内部有时是 uid → entry
        for i, (_uid, item) in enumerate(entries_raw.items()):
            ent = _parse_entry(item, fallback_id=i)
            if ent is not None:
                entries.append(ent)

    return CharacterBook(
        name=str(data.get("name") or ""),
        description=str(data.get("description") or ""),
        scan_depth=max(0, int(data.get("scan_depth") or 6)),
        token_budget=max(64, int(data.get("token_budget") or 800)),
        recursive_scanning=bool(data.get("recursive_scanning") or False),
        entries=entries,
        extensions=dict(data.get("extensions") or {}) if isinstance(data.get("extensions"), dict) else {},
    )


def _parse_entry(item: Any, *, fallback_id: int) -> BookEntry | None:
    if not isinstance(item, dict):
        return None
    # ST 内部字段别名
    keys = item.get("keys") or item.get("key") or []
    if isinstance(keys, str):
        keys = [k.strip() for k in keys.replace("，", ",").split(",") if k.strip()]
    else:
        keys = [str(k).strip() for k in keys if str(k).strip()]

    secondary = item.get("secondary_keys") or item.get("keysecondary") or []
    if isinstance(secondary, str):
        secondary = [k.strip() for k in secondary.replace("，", ",").split(",") if k.strip()]
    else:
        secondary = [str(k).strip() for k in secondary if str(k).strip()]

    content = str(item.get("content") or "").strip()
    if not content:
        return None
    if not keys and not item.get("constant"):
        return None

    pos = str(item.get("position") or "after_char")
    if pos not in ("before_char", "after_char"):
        # ST 数字 position 等：一律当 after
        pos = "after_char"

    raw_id = item.get("id")
    if raw_id is None:
        eid: int | str | None = fallback_id
    elif isinstance(raw_id, bool):
        eid = fallback_id
    elif isinstance(raw_id, int):
        eid = raw_id
    else:
        eid = str(raw_id).strip() or fallback_id

    # 作者常用 id 当条目名；无 name 时用 id / 首 key
    display = str(item.get("name") or item.get("comment") or "").strip()
    if not display and isinstance(eid, str):
        display = eid

    return BookEntry(
        keys=keys,
        content=content,
        enabled=bool(item.get("enabled", True)),
        insertion_order=int(item.get("insertion_order") or item.get("order") or 100),
        case_sensitive=bool(item.get("case_sensitive") or False),
        selective=bool(item.get("selective") or False),
        secondary_keys=secondary,
        constant=bool(item.get("constant") or False),
        position=pos,
        name=display,
        priority=int(item.get("priority") if item.get("priority") is not None else 10),
        id=eid,
    )


def build_scan_text(
    current: str,
    nearby_before: Iterable[dict[str, str]] | None = None,
    *,
    scan_depth: int = 6,
) -> str:
    """拼扫描语料：本条优先，再拼近邻上文（条数受 scan_depth 限制）。"""
    parts: list[str] = []
    cur = (current or "").strip()
    if cur:
        parts.append(cur)
    depth = max(0, int(scan_depth))
    # 本条占 1；其余给上文
    remain = max(0, depth - (1 if cur else 0))
    before = list(nearby_before or [])
    if remain and before:
        for item in before[-remain:]:
            tx = (item.get("text") or "").strip()
            if tx:
                parts.append(tx)
    return "\n".join(parts)


def select_entries(
    book: CharacterBook | None,
    scan_text: str,
    *,
    max_chars: int | None = None,
    max_entries: int = 8,
) -> list[BookEntry]:
    """按关键词筛选并做预算裁剪。"""
    if book is None or not book.entries:
        return []

    budget = int(max_chars if max_chars is not None else book.token_budget)
    budget = max(64, budget)
    max_n = max(1, int(max_entries))

    matched: list[BookEntry] = []
    for ent in book.entries:
        if not ent.enabled:
            continue
        if not (ent.content or "").strip():
            continue
        if ent.constant or _entry_matches(ent, scan_text):
            matched.append(ent)

    # insertion_order 升序；同序看 priority 降序
    matched.sort(key=lambda e: (e.insertion_order, -e.priority, str(e.id if e.id is not None else "")))

    chosen: list[BookEntry] = []
    used = 0
    for ent in matched:
        if len(chosen) >= max_n:
            break
        chunk = ent.content.strip()
        if used + len(chunk) > budget and chosen:
            # 预算紧：跳过低优先（已按 order 排好；后面的更靠后）
            continue
        if used + len(chunk) > budget and not chosen:
            # 至少塞一条时截断
            ent = BookEntry(
                keys=ent.keys,
                content=chunk[:budget],
                enabled=ent.enabled,
                insertion_order=ent.insertion_order,
                case_sensitive=ent.case_sensitive,
                selective=ent.selective,
                secondary_keys=ent.secondary_keys,
                constant=ent.constant,
                position=ent.position,
                name=ent.name,
                priority=ent.priority,
                id=ent.id,
            )
            chosen.append(ent)
            break
        chosen.append(ent)
        used += len(chunk) + 1
    return chosen


def _entry_matches(ent: BookEntry, scan_text: str) -> bool:
    if not ent.keys:
        return False
    if not _any_key_in(ent.keys, scan_text, ent.case_sensitive):
        return False
    if not ent.selective or not ent.secondary_keys:
        return True
    # V1：selective = 主 key 命中 AND 任一 secondary 命中（ST AND ANY）
    return _any_key_in(ent.secondary_keys, scan_text, ent.case_sensitive)


def _any_key_in(keys: list[str], text: str, case_sensitive: bool) -> bool:
    if not text:
        return False
    hay = text if case_sensitive else text.lower()
    for key in keys:
        if not key:
            continue
        needle = key if case_sensitive else key.lower()
        if needle in hay:
            return True
    return False


def format_book_block(
    entries: list[BookEntry],
    *,
    position: str | None = None,
) -> str:
    """格式化为 system 注入块。position 过滤 before_char / after_char；None=全部。"""
    if not entries:
        return ""
    filtered = [e for e in entries if position is None or e.position == position]
    if not filtered:
        return ""
    lines = [
        "【角色书·动态设定】（仅当本轮关键词相关才出现；当背景知道即可，勿主动念说明书）"
    ]
    for ent in filtered:
        label = (ent.name or (ent.keys[0] if ent.keys else "")).strip()
        body = ent.content.strip()
        if label:
            lines.append(f"- {label}：{body}")
        else:
            lines.append(f"- {body}")
    return "\n".join(lines)
