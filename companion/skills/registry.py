from __future__ import annotations

from pathlib import Path
from typing import Any

from ..tools.continuation_intent import is_another_one_intent
from ..tools.jm_intent import extract_comic_id, is_jm_search_intent
from ..tools.link_intent import extract_urls

_SKILLS_ROOT = Path(__file__).resolve().parent

# (id, branch, relative path) — branch: "" | "astrbot" | "mcp"
_SKILL_FILES: tuple[tuple[str, str, str], ...] = (
    ("protocol", "", "protocol.md"),
    ("music", "astrbot", "astrbot/music.md"),
    ("setu", "astrbot", "astrbot/setu.md"),
    ("jmcomic", "astrbot", "astrbot/jmcomic.md"),
    ("image_search", "astrbot", "astrbot/image_search.md"),
    ("reminder", "astrbot", "astrbot/reminder.md"),
    ("mention", "astrbot", "astrbot/mention.md"),
    ("web_search", "astrbot", "astrbot/web_search.md"),
    ("fetch_web", "mcp", "mcp/fetch_web.md"),
    ("mcp_generic", "mcp", "mcp/_generic.md"),
)

# 目录短句：只写何时用，不解释工具是什么
_CATALOG_BLURB: dict[str, str] = {
    "music": "要点歌/放歌/来一首时",
    "setu": "要涩图/「来点XX」插画时",
    "jmcomic": "要本子时（搜、下、随机、换一本均由你判断）",
    "image_search": "有图且问出处/作者时",
    "reminder": "要闹钟/N分钟后提醒/到点喊我时",
    "mention": "要真@/艾特/点名/喊某人出来时",
    "web_search": "不确定的实时事实或对方要搜/查时（优先内置搜索）",
    "fetch_web": "消息里有链接要打开/概括时",
    "mcp_generic": "无内置搜索且明确要搜/查时才用 MCP",
}


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
        """按本回合可见工具展开 skill（含 protocol）。无关键词闸门，由模型理解意图。"""
        reason = str(getattr(tool_plan, "reason", None) or "") if tool_plan else ""
        if reason in ("voice_speak_no_tools", "tools_disabled", "tools_off"):
            return []

        names = {n.lower() for n in available_names}
        if not names:
            return []

        business: list[str] = []
        if "play_song_by_name" in names:
            business.append("music")
        if "setu_send_image" in names:
            business.append("setu")
        if any(n.startswith("jmcomic_") for n in names):
            business.append("jmcomic")
        if any(n.startswith("image_search_") for n in names):
            business.append("image_search")
        if "schedule_reminder" in names or "cancel_reminder" in names:
            business.append("reminder")
        if "mention_group_member" in names:
            business.append("mention")
        if any(n.startswith("web_search") for n in names):
            business.append("web_search")
        if any("fetch" in n for n in names) or any(
            n in names for n in ("tavily_extract_web_page", "firecrawl_extract_web_page")
        ):
            business.append("fetch_web")

        has_builtin_search = any(n.startswith("web_search") for n in names)
        mcp_names = [
            getattr(s, "name", "")
            for s in (specs or [])
            if getattr(s, "origin", "") == "mcp" and getattr(s, "name", "")
        ]
        other_mcp = []
        for n in mcp_names:
            low = n.lower()
            if "fetch" in low:
                continue
            if has_builtin_search and any(
                k in low for k in ("search", "duckduckgo", "ddg")
            ):
                continue
            other_mcp.append(n)
        if other_mcp:
            business.append("mcp_generic")

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
        if "mention_group_member" in names:
            out.append(("mention", "astrbot"))
        if any(n.startswith("web_search") for n in names):
            out.append(("web_search", "astrbot"))
        if any("fetch" in n for n in names) or any(
            n in names for n in ("tavily_extract_web_page", "firecrawl_extract_web_page")
        ):
            out.append(("fetch_web", "mcp"))
        # 其它 MCP：有则列 mcp_generic；已有内置搜索时不把搜索类 MCP 当入口
        has_builtin_search = any(n.startswith("web_search") for n in names)
        other_mcp = []
        for n in mcp_names:
            low = n.lower()
            if "fetch" in low:
                continue
            if has_builtin_search and any(
                k in low for k in ("search", "duckduckgo", "ddg")
            ):
                continue
            other_mcp.append(n)
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
    if comic_id:
        return f"本条有 ID={comic_id} → download。"
    if is_another_one_intent(text):
        return "本条是再来/换一本 → 继续 search 后 download，勿闲聊。"
    if is_jm_search_intent(text):
        return "本条偏搜 → search。"
    return "搜用 search，下用 download。"


def _tag_hint(text: str, card: Any | None = None) -> str:
    character_tag = ""
    if card is not None:
        ext = getattr(card, "companion_ext", None) or {}
        character_tag = str(
            ext.get("setu_tag") or getattr(card, "display_name", "") or getattr(card, "id", "")
        ).strip()
    if character_tag:
        return f"角色检索词可用 {character_tag}。"
    return ""


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