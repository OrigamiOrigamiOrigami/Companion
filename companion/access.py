"""Access control: who companion will ignore entirely."""

from __future__ import annotations

from typing import Any


def _id_set(raw: Any) -> set[str]:
    out: set[str] = set()
    if not isinstance(raw, (list, tuple, set)):
        return out
    for x in raw:
        s = str(x).strip()
        if s:
            out.add(s)
    return out


def ignored_user_ids(config: dict[str, Any]) -> set[str]:
    access = config.get("access") or {}
    return _id_set(access.get("ignored_user_ids"))


def super_user_ids(config: dict[str, Any]) -> set[str]:
    adm = config.get("admins") or {}
    return _id_set(adm.get("super"))


def is_user_ignored(user_id: str | int | None, config: dict[str, Any]) -> bool:
    """True → companion 全入口静默丢弃。超管 QQ 永不命中。"""
    uid = str(user_id or "").strip()
    if not uid:
        return False
    if uid in super_user_ids(config):
        return False
    return uid in ignored_user_ids(config)
