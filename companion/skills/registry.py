from __future__ import annotations

from pathlib import Path
from typing import Any

from ..tools.jm_intent import extract_comic_id, is_jm_context, is_jm_search_intent
from ..tools.link_intent import extract_urls, has_http_url
from ..tools.mute_intent import is_mute_intent
from ..tools.reminder_intent import is_reminder_intent
from ..tools.setu_intent import is_setu_intent, parse_llm_setu_tags
from ..voice.intent import is_song_tool_intent

_SKILLS_ROOT = Path(__file__).resolve().parent

# (id, branch, relative path) — branch: "" | "astrbot" | "mcp"
_SKILL_FILES: tuple[tuple[str, str, str], ...] = (
    ("protocol", "", "protocol.md"),
    ("music", "astrbot", "astrbot/music.md"),
    ("setu", "astrbot", "astrbot/setu.md"),
    ("jmcomic", "astrbot", "astrbot/jmcomic.md"),
    ("image_search", "astrbot", "astrbot/image_search.md"),
    ("reminder", "astrbot", "astrbot/reminder.md"),
    ("mute", "astrbot", "astrbot/mute.md"),
    ("fetch_web", "mcp", "mcp/fetch_web.md"),
    ("mcp_generic", "mcp", "mcp/_generic.md"),
)

# 目录短句：只写何时用，不解释工具是什么
_CATALOG_BLURB: dict[str, str] = {
    "music": "要点歌/放歌/来一首时",
    "setu": "要涩图/「来点XX」插画时",
    "jmcomic": "搜本子或下本子 ID 时",
    "image_search": "有图且问出处/作者时",
    "reminder": "要闹钟/N分钟后提醒/到点喊我时",
    "mute": "要禁言/闭嘴/解禁某人时",
    "fetch_web": "消息里有链接要打开/概括时",
    "mcp_generic": "明确要搜/查且无更贴专用技能时",
}

_SEARCH_HELP_KW = ("搜", "查", "搜索", "帮我查", "查一下", "搜一下")


class SkillRegistry:
    def __init__(self, root: Path | None = None):
        self.root = root or _SKILLS_ROOT
        self._bodies: dict[str, str] | None = None
        self._meta: dict[str, tuple[str, str]] = {
            sid: (branch, rel) for sid, branch, rel in _SKILL_FILES
        }

    def _load(self) -> dict[str, str]:
        if self._bodies is not None:
            return self._bodies
        bodies: dict[str, str] = {}
        for sid, _branch, rel in _SKILL_FILES:
            path = self.root / rel
            if path.is_file():
                bodies[sid] = path.read_text(encoding="utf-8-sig").strip()
        self._bodies = bodies
        return bodies

    def select(
        self,
        perception: Any,
        *,
        available_names: set[str],
        tool_plan: Any | None,
        specs: list[Any] | None = None,
    ) -> list[str]:
        """按意图 + 可见工具选出要展开的 skill id（含 protocol）。闲聊返回 []。"""
        text = getattr(perception, "text", None) or ""
        order = (getattr(tool_plan, "order", None) if tool_plan else "chat") or "chat"
        names = {n.lower() for n in available_names}
        has_image = bool(getattr(perception, "has_image", False))

        business: list[str] = []

        if is_song_tool_intent(text) and "play_song_by_name" in names:
            business.append("music")

        reminder_hit = is_reminder_intent(text) and (
            "schedule_reminder" in names or "cancel_reminder" in names
        )
        mute_hit = is_mute_intent(text) and (
            "mute_group_member" in names or "unmute_group_member" in names
        )
        if reminder_hit:
            business.append("reminder")
        if mute_hit:
            business.append("mute")

        # 禁言/提醒回合不要因 @QQ 数字误展开 jmcomic / setu
        if not mute_hit and not reminder_hit:
            if is_setu_intent(text) and "setu_send_image" in names:
                business.append("setu")

            if any(n.startswith("jmcomic_") for n in names) and (
                is_jm_search_intent(text) or is_jm_context(text)
            ):
                business.append("jmcomic")

        if has_image and any(n.startswith("image_search_") for n in names):
            business.append("image_search")

        if has_http_url(text):
            business.append("fetch_web")

        mcp_names = [
            getattr(s, "name", "")
            for s in (specs or [])
            if getattr(s, "origin", "") == "mcp" and getattr(s, "name", "")
        ]
        dedicated = {
            "music",
            "setu",
            "jmcomic",
            "image_search",
            "reminder",
            "mute",
            "fetch_web",
        }
        if (
            mcp_names
            and any(k in text for k in _SEARCH_HELP_KW)
            and not (dedicated & set(business))
        ):
            business.append("mcp_generic")

        # 纯闲聊：整块借力不注入
        if order == "chat" and not business:
            return []

        bodies = self._load()
        out: list[str] = []
        seen: set[str] = set()
        for sid in ["protocol", *business]:
            if sid in seen or sid not in bodies:
                continue
            seen.add(sid)
            out.append(sid)
        return out

    def visible_catalog_ids(self, specs: list[Any]) -> list[tuple[str, str]]:
        """本回合可见工具 → (skill_id, branch)，用于目录树。"""
        names = {getattr(s, "name", "").lower() for s in specs if getattr(s, "name", "")}
        mcp_names = [
            getattr(s, "name", "")
            for s in specs
            if getattr(s, "origin", "") == "mcp" and getattr(s, "name", "")
        ]
        out: list[tuple[str, str]] = []
        if "play_song_by_name" in names:
            out.append(("music", "astrbot"))
        if "setu_send_image" in names:
            out.append(("setu", "astrbot"))
        if any(n.startswith("jmcomic_") for n in names):
            out.append(("jmcomic", "astrbot"))
        if any(n.startswith("image_search_") for n in names):
            out.append(("image_search", "astrbot"))
        if "schedule_reminder" in names or "cancel_reminder" in names:
            out.append(("reminder", "astrbot"))
        if "mute_group_member" in names or "unmute_group_member" in names:
            out.append(("mute", "astrbot"))
        if any("fetch" in n for n in names):
            out.append(("fetch_web", "mcp"))
        # 其它 MCP：有则列 mcp_generic 作为入口；具体名在目录行里带上
        other_mcp = [n for n in mcp_names if "fetch" not in n.lower()]
        if other_mcp:
            out.append(("mcp_generic", "mcp"))
        return out

    def render_catalog(self, specs: list[Any]) -> str:
        items = self.visible_catalog_ids(specs)
        if not items:
            return ""
        mcp_names = [
            getattr(s, "name", "")
            for s in specs
            if getattr(s, "origin", "") == "mcp" and getattr(s, "name", "")
        ]
        other_mcp = [n for n in mcp_names if "fetch" not in n.lower()]

        astrbot: list[str] = []
        mcp: list[str] = []
        for sid, branch in items:
            blurb = _CATALOG_BLURB.get(sid, sid)
            if sid == "mcp_generic" and other_mcp:
                names_s = "、".join(other_mcp[:10])
                line = f"  - other（{names_s}）：{blurb}"
            else:
                label = sid
                line = f"  - {label}：{blurb}"
            if branch == "astrbot":
                astrbot.append(line)
            else:
                mcp.append(line)

        parts = ["- 目录"]
        if astrbot:
            parts.append("  - astrbot")
            for line in astrbot:
                # line is "  - music：…" → make "    - music：…"
                parts.append("  " + line)
        if mcp:
            parts.append("  - mcp")
            for line in mcp:
                parts.append("  " + line)
        return "\n".join(parts)

    def render(
        self,
        skill_ids: list[str],
        *,
        vars: dict[str, str] | None = None,
        catalog: str = "",
    ) -> str:
        if not skill_ids:
            return ""
        bodies = self._load()
        mapping = dict(vars or {})
        protocol_body = ""
        expand_astrbot: list[str] = []
        expand_mcp: list[str] = []

        for sid in skill_ids:
            raw = bodies.get(sid)
            if not raw:
                continue
            text = raw
            for k, v in mapping.items():
                text = text.replace("{" + k + "}", v)
            branch = self._meta.get(sid, ("", ""))[0]
            if sid == "protocol" or branch == "":
                protocol_body = text
            elif branch == "astrbot":
                expand_astrbot.append(f"  - {sid}：{text}")
            elif branch == "mcp":
                label = "other" if sid == "mcp_generic" else sid
                expand_mcp.append(f"  - {label}：{text}")

        parts: list[str] = ["【借力】"]
        if catalog:
            parts.append(catalog)
        if protocol_body:
            parts.append(f"- 约定：{protocol_body}")
        if expand_astrbot or expand_mcp:
            parts.append("- 展开")
            if expand_astrbot:
                parts.append("  - astrbot")
                for line in expand_astrbot:
                    parts.append("  " + line)
            if expand_mcp:
                parts.append("  - mcp")
                for line in expand_mcp:
                    parts.append("  " + line)
        return "\n".join(parts)


def _jm_hint(text: str) -> str:
    comic_id = extract_comic_id(text)
    if is_jm_search_intent(text):
        return "本条偏搜索，优先 jmcomic_search。"
    if comic_id:
        return f'本条 ID={comic_id}，调 jmcomic_download，comic_id="{comic_id}"。'
    return "有数字 ID 用 download；搜关键词用 search。"


def _tag_hint(text: str, card: Any | None = None) -> str:
    character_tag = ""
    if card is not None:
        ext = getattr(card, "companion_ext", None) or {}
        character_tag = str(
            ext.get("setu_tag") or getattr(card, "display_name", "") or getattr(card, "id", "")
        ).strip()
    if character_tag:
        return f"tags 由你按语义填写；你扮演 {character_tag}，勿机械拆原话"
    return "tags 由你按语义填写，勿机械拆用户原话"


def build_tool_skill_hint(
    perception: Any,
    *,
    specs: list[Any],
    tool_plan: Any | None,
    card: Any | None = None,
    registry: SkillRegistry | None = None,
) -> str:
    """Express 入口：闲聊空；借力回合 = 目录 + 约定 + 命中展开。"""
    reg = registry or SkillRegistry()
    names = {getattr(s, "name", "") for s in specs if getattr(s, "name", "")}
    names_l = {n.lower() for n in names}
    ids = reg.select(
        perception,
        available_names=names_l,
        tool_plan=tool_plan,
        specs=specs,
    )
    if not ids:
        return ""

    text = getattr(perception, "text", None) or ""
    character_tag = ""
    if card is not None:
        ext = getattr(card, "companion_ext", None) or {}
        character_tag = str(
            ext.get("setu_tag") or getattr(card, "display_name", "") or getattr(card, "id", "")
        ).strip()
    urls = extract_urls(text, limit=3)
    url_list = "、".join(urls) if urls else "消息里的链接"
    mcp_names = [
        getattr(s, "name", "")
        for s in specs
        if getattr(s, "origin", "") == "mcp" and getattr(s, "name", "")
    ]
    mcp_line = "、".join(mcp_names[:12]) if mcp_names else "（无）"

    return reg.render(
        ids,
        vars={
            "urls": url_list,
            "tag_hint": _tag_hint(text, card),
            "character_tag": character_tag,
            "jm_hint": _jm_hint(text),
            "mcp_names": mcp_line,
        },
        catalog=reg.render_catalog(specs),
    )