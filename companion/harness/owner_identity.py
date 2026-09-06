"""超管 = 阿漂（漂泊者）身份提示，供 Express 注入。"""

from __future__ import annotations

from typing import Any


def owner_callname(config: dict[str, Any] | None) -> str:
    admins = (config or {}).get("admins") or {}
    name = str(admins.get("owner_callname") or "阿漂").strip()
    return name or "阿漂"


def super_ids(config: dict[str, Any] | None) -> set[str]:
    raw = ((config or {}).get("admins") or {}).get("super") or []
    return {str(x).strip() for x in raw if str(x).strip()}


def is_owner_user(user_id: str, config: dict[str, Any] | None) -> bool:
    uid = str(user_id or "").strip()
    return bool(uid) and uid in super_ids(config)


def format_counterpart_hint(
    *,
    sender_name: str,
    user_id: str,
    is_private: bool,
    config: dict[str, Any] | None,
) -> str:
    """【对方】一行：群名片 + 是否阿漂。"""
    who = (sender_name or "").strip()
    uid = str(user_id or "").strip()
    if not who and not uid:
        return ""
    label = who or uid
    call = owner_callname(config)
    owner = is_owner_user(uid, config)

    if uid:
        base = (
            f"【对方】本群称呼/昵称：{label}（QQ={uid}）。"
            f"可自然这样叫对方；要真@对方时写 @{label} 或 @[qq:{uid}]。"
        )
    else:
        base = f"【对方】本群称呼/昵称：{label}。"

    if owner:
        return (
            f"{base}"
            f"对方就是{call}（漂泊者／超管）；群名片即使写成别的字，对内仍叫「你 / {call}」，"
            f"不要当成路人或陌生人。"
        )

    if is_private:
        return (
            f"{base}"
            f"对方不是{call}；对人设里的{call}只用在真正的超管身上。"
            "别每句硬喊外号，也别改成别的称呼（除非对方刚说过）。"
        )

    return (
        f"{base}"
        f"对方不是{call}。{call}只指超管；对本条说话人用昵称/外号，"
        f"禁止把每个群友都叫成{call}。别每句硬喊，也别乱改外号（除非对方刚说过）。"
    )
