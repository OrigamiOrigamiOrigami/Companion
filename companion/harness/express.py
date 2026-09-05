from __future__ import annotations

import logging
import re
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from ..card.loader import CharacterCard
from ..card.character_book import (
    build_scan_text,
    format_book_block,
    select_entries,
)
from ..stickers.tags import glossary_for
from ..provider.openai_compat import sanitize_visible_text
from ..skills import build_tool_skill_hint
from ..tools.loop import ToolLoopRunner
from ..voice.emotion import extract_voice_emotion
from ..voice.intent import extract_voice_speak_line
from ..canned import pick_fallback
from .media import extract_vision_images
from .outbound_sanitize import resolve_style_limits
from .types import Decision, ExpressResult, InnerState, Perception, ToolPlan

logger = logging.getLogger("astrbot")

_INTENT_RE = re.compile(r"sticker_intent\s*[:=]\s*([a-z_]+)", re.I)
_EMOTION_RE = re.compile(r"emotion\s*[:=]\s*([a-z_]+)", re.I)
_POKE_WANTED_RE = re.compile(r"poke_wanted\s*[:=]\s*(true|false|yes|no|1|0)", re.I)
_WANTED_RE = re.compile(r"sticker_wanted\s*[:=]\s*(true|false|yes|no|1|0)", re.I)
_VOICE_EMO_RE = re.compile(r"voice_emotion\s*[:=]\s*([a-zA-Z_\u4e00-\u9fff]+)", re.I)

LLMCall = Callable[[list[dict[str, Any]]], Awaitable[str]]


class Expressor:
    def __init__(
        self,
        config: dict[str, Any],
        llm_call: LLMCall,
        tool_loop: ToolLoopRunner | None = None,
    ):
        self.config = config
        self.llm_call = llm_call
        self.tool_loop = tool_loop

    async def run(
        self,
        card: CharacterCard,
        state: InnerState,
        perception: Perception,
        memory_block: str,
        decision: Decision,
        allow_tags: list[str],
        *,
        event: Any = None,
        tool_plan: ToolPlan | None = None,
        send_preface: Callable[[str], Awaitable[None]] | None = None,
        preface_sink: list[str] | None = None,
        force_voice: bool = False,
        nearby: dict[str, list[dict[str, str]]] | None = None,
        recent_sticker_intents: list[str] | None = None,
    ) -> ExpressResult:
        vision_urls: list[str] = []
        if event is not None and perception.has_image and self._vision_enabled():
            try:
                vision_urls = await extract_vision_images(event, max_images=1)
            except Exception as e:
                logger.warning("companion 视觉图片提取失败: %s", e)
            if perception.has_image and not vision_urls:
                logger.warning(
                    "companion 视觉：消息含图但未拿到像素（下载失败或过大），模型将看不见画面"
                )

        messages = self._build_messages(
            card,
            state,
            perception,
            memory_block,
            decision,
            allow_tags,
            vision_urls=vision_urls,
            tool_plan=tool_plan,
            force_voice=force_voice,
            nearby=nearby,
            recent_sticker_intents=recent_sticker_intents,
        )
        fallback = ((self.config.get("express") or {}).get("fallback_message")) or pick_fallback()
        tools_used: list[str] = []
        llm_trace: list[dict[str, Any]] = []
        if self.tool_loop is not None:
            try:
                self.tool_loop.provider.begin_turn()
            except Exception:
                pass

        async def _on_preface(text: str) -> None:
            for bubble in split_preface_bubbles(text):
                if preface_sink is not None:
                    preface_sink.append(bubble)
                if send_preface is not None:
                    await send_preface(bubble)

        try:
            raw = await self._generate(
                messages,
                card,
                decision,
                event=event,
                tools_used=tools_used,
                llm_trace=llm_trace,
                on_preface=_on_preface if send_preface or preface_sink else None,
                tool_plan=tool_plan,
            )
            if not (raw or "").strip():
                if tools_used or preface_sink:
                    from ..tools.loop import ack_aware_outro

                    line = ack_aware_outro(llm_trace)
                    result = ExpressResult(
                        bubbles=[line] if line else [],
                        degraded=bool(line),
                        tools_used=tools_used,
                        llm_trace=llm_trace,
                        prompt_messages=messages,
                        raw_response=raw or line or "",
                    )
                    if self.tool_loop is not None:
                        result.tool_invocations = self.tool_loop.bridge.drain_invocations()
                    if preface_sink:
                        result.preface_bubbles = list(preface_sink)
                    if tool_plan:
                        result.tool_order = tool_plan.order
                    return result
                raise ValueError("empty response")
            result = parse_express(raw, allow_tags, always_sticker=True)
            result.tools_used = tools_used
            result.raw_response = raw
            result.llm_trace = llm_trace
            result.prompt_messages = messages
            if self.tool_loop is not None:
                result.tool_invocations = self.tool_loop.bridge.drain_invocations()
            if preface_sink:
                result.preface_bubbles = list(preface_sink)
            if tool_plan:
                result.tool_order = tool_plan.order
            return result
        except Exception as e:
            logger.warning("companion 表达降级: %s", e)
            partial = bool(tools_used or preface_sink)
            if partial:
                from ..tools.loop import ack_aware_outro

                line = ack_aware_outro(llm_trace)
                result = ExpressResult(
                    bubbles=[line] if line else [],
                    degraded=True,
                    tools_used=tools_used,
                    llm_trace=llm_trace,
                    prompt_messages=messages,
                    error=str(e),
                    preface_bubbles=list(preface_sink) if preface_sink else [],
                )
            else:
                result = ExpressResult(
                    bubbles=[fallback],
                    degraded=True,
                    tools_used=tools_used,
                    llm_trace=llm_trace,
                    prompt_messages=messages,
                    error=str(e),
                    preface_bubbles=list(preface_sink) if preface_sink else [],
                )
            if self.tool_loop is not None:
                result.tool_invocations = self.tool_loop.bridge.drain_invocations()
            return result

    def _vision_enabled(self) -> bool:
        return bool((self.config.get("providers") or {}).get("vision_enabled", True))

    async def _generate(
        self,
        messages: list[dict[str, Any]],
        card: CharacterCard,
        decision: Decision,
        *,
        event: Any,
        tools_used: list[str],
        llm_trace: list[dict[str, Any]],
        on_preface: Callable[[str], Awaitable[None]] | None = None,
        tool_plan: ToolPlan | None = None,
    ) -> str:
        tools_cfg = self.config.get("tools") or {}
        # 默认挂全量工具，由模型理解意图决定是否调用。
        reason = getattr(tool_plan, "reason", "") if tool_plan else ""
        tools_ok = reason != "voice_speak_no_tools"
        use_tools = (
            tools_ok
            and self.tool_loop is not None
            and tools_cfg.get("enabled", True)
            and decision.allow_tools
            and event is not None
        )
        if use_tools and self.tool_loop.bridge.openai_tools(card=card):
            raw, used, trace = await self.tool_loop.run(
                messages,
                event=event,
                card=card,
                on_preface=on_preface,
                tool_plan=tool_plan,
            )
            tools_used.extend(used)
            llm_trace.extend(trace)
            return raw
        raw = await self.llm_call(messages)
        llm_trace.append({"mode": "direct", "raw_response": raw})
        return raw

    def _build_messages(
        self,
        card: CharacterCard,
        state: InnerState,
        perception: Perception,
        memory_block: str,
        decision: Decision,
        allow_tags: list[str],
        *,
        vision_urls: list[str] | None = None,
        tool_plan: ToolPlan | None = None,
        force_voice: bool = False,
        nearby: dict[str, list[dict[str, str]]] | None = None,
        recent_sticker_intents: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        form_meta = ((card.companion_ext.get("forms") or {}).get(state.active_form) or {})
        overlay = card.forms.get(state.active_form, "")
        # 语气标签来自角色卡；双态旧卡可写 label，未写则不注入
        tone_hint = str(form_meta.get("label") or "")
        style = form_meta.get("style_hints") or {}
        expr = self.config.get("express") or {}
        max_bubbles, max_chars = resolve_style_limits(style, expr)
        tag_gloss = glossary_for(allow_tags) if allow_tags else "none"
        recent = [x for x in (recent_sticker_intents or []) if x and x != "none"]
        recent_line = "、".join(recent[-5:]) if recent else "无"
        form_soft = ""
        if (state.active_form or "").lower() in ("default", "pink"):
            form_soft = "当前形态偏外向时更常 playful/tease/warm/shy；"
        elif (state.active_form or "").lower() == "black":
            form_soft = "当前形态偏克制时更常 quiet/speechless/sad；"
        allow_asterisk = bool(card.companion_ext.get("allow_asterisk_actions", True))
        if allow_asterisk:
            action_rule = (
                "- `*…*` 只写可被摄像机拍到的动作，每条回复最多 2 处；不写心理独白。\n"
            )
        else:
            action_rule = (
                "- **禁止**输出任何 `*…*` 旁白或肢体动作描写（如 `*笑*`、`*叹气*`）。"
                "情绪与神态只靠语气、标点、`~`、颜文字表达。\n"
            )

        tool_hint = ""
        if (
            self.tool_loop
            and decision.allow_tools
            and (self.config.get("tools") or {}).get("enabled", True)
        ):
            specs = self.tool_loop.bridge.list_tools(card=card)
            tool_hint = build_tool_skill_hint(
                perception, specs=specs, tool_plan=tool_plan, card=card
            )
            if tool_plan and tool_plan.hint:
                tool_hint = (
                    f"{tool_hint} {tool_plan.hint}".strip()
                    if tool_hint
                    else tool_plan.hint
                )

        voice_hint = self._voice_capability_hint(
            force_voice=force_voice,
            speak_line=extract_voice_speak_line(perception.text or ""),
        )

        from ..tools.continuation_intent import is_another_one_intent

        focus_hint = ""
        if force_voice:
            focus_hint = (
                "【本回合焦点】只回应【本条】当前这句话。"
                "上文仅作称呼/气氛参考；若本条是「用语音说某句话」，就念那句话（可加极短反应），"
                "不要回聊上文的 TTS/模型/技术话题，也不要点歌，除非本条明确在问或要歌。"
            )
        elif is_another_one_intent(perception.text or ""):
            focus_hint = (
                "【本回合焦点】本条是接续上文的『再来一个/换一个』："
                "必须延续上一轮任务（本子/涩图等）并调用对应工具；"
                "禁止当成新闲聊只回表情或空口答应。"
            )
        else:
            focus_hint = (
                "【本回合焦点】优先回应【本条】；上文仅作接话参考，勿把上一轮长话题当成这轮问题。"
            )
        if vision_urls:
            focus_hint += (
                "本条带了图片：必须先根据画面内容回应；"
                "禁止无视图片。"
            )
        media_hint = ""
        if vision_urls:
            media_hint = (
                "【视觉】本条用户消息附带了图片，你可以直接看到画面内容。"
                "请根据画面自然回应；不要说「看不见图」「收不到图片」。"
                "若对方只说「这个」而配了图，图就是所指对象。"
            )
        elif perception.has_visual:
            media_hint = (
                "【媒体】对方发了图片或表情，但本条未能解析出图像数据，你现在看不见画面。"
                "请明确说没看清/请重发，禁止根据上文臆测图里是什么。"
            )
        elif perception.record_count:
            media_hint = "【媒体】对方发了语音，你暂时听不了内容，可请对方打字。"

        book_before = ""
        book_after = ""
        book = getattr(card, "character_book", None)
        if book and book.entries:
            ext = card.companion_ext or {}
            max_chars = int(ext.get("character_book_max_chars") or book.token_budget or 800)
            max_entries = int(ext.get("character_book_max_entries") or 8)
            scan = build_scan_text(
                perception.text or "",
                (nearby or {}).get("before"),
                scan_depth=int(ext.get("character_book_scan_depth") or book.scan_depth or 6),
            )
            # 语音念白回合仍允许命中（本条常含要念的词），但预算更紧
            if force_voice:
                max_chars = min(max_chars, 400)
                max_entries = min(max_entries, 3)
            picked = select_entries(
                book, scan, max_chars=max_chars, max_entries=max_entries
            )
            book_before = format_book_block(picked, position="before_char")
            book_after = format_book_block(picked, position="after_char")
            if picked:
                logger.info(
                    "角色书命中 条数=%s 关键词=%s",
                    len(picked),
                    [e.name or (e.keys[:1] or [""])[0] for e in picked],
                )

        # A → B → D → C → 状态/时间/记忆 → 工具媒体语音 → 输出约定
        system = "\n\n".join(
            [
                p
                for p in [
                    card.prompt.strip(),
                    book_before,
                    (
                        f"【语气与表达】\n{card.tone_reference}".strip()
                        if (card.tone_reference or "").strip()
                        else ""
                    ),
                    (
                        f"【语气锚点】\n{card.anchors}".strip()
                        if (card.anchors or "").strip()
                        else ""
                    ),
                    book_after,
                    (
                        f"【此刻语气】{tone_hint}\n{overlay}".strip()
                        if tone_hint or overlay
                        else ""
                    ),
                    f"【状态】熟悉={state.familiarity} 心情={state.mood} 精力={state.energy}",
                    _format_now_context(cfg=self.config),
                    (memory_block or "").strip(),
                    focus_hint,
                    media_hint,
                    tool_hint,
                    voice_hint,
                    (
                        "【输出约定】\n"
                        f"- 口语短句，最多 {max_bubbles} 段（换行分段）；每段尽量 ≤{max_chars} 字，"
                        "宁可一段稍长说完，也别拆成半截编号列表。\n"
                        f"{action_rule}"
                        "- 禁止 Markdown：不要用加粗星号、井号标题、反引号代码、也不要用「1. 2. 3.」或「-」列点；"
                        "QQ 气泡不会排版，只会露出符号。用口语一两段说完即可。\n"
                        "- 不要自称 AI，不要输出数值好感。\n"
                        "- 不要提系统设定、内部状态名或「切换模式」等元信息；凭心情自然说话。\n"
                        "- 口癖（诶？/嘛~/好啦）自然穿插，勿每句同位置机械复读；"
                        "也勿与【她最近说过】原句或近义复读。\n"
                        "- 颜文字偶尔点缀即可，按情绪轮换，勿连续多轮只用同一个"
                        "（尤其别刷同一个经典款）；多数短句不配颜文字也正常。\n"
                        "- 【角色书】仅作背景；提到相关话题时可自然带一句，勿整段宣读设定。\n"
                        "- 【表情包】你能在文字后附带一张表情图。系统会读你末行控制字段发图，"
                        "你本人看不到文件名，也不要说「发不出来」「没反应」。\n"
                        "- 【末行必写字段】每轮回复末尾必须单独一行写齐："
                        f"emotion=<tag> sticker_wanted=true sticker_intent=<tag> poke_wanted=true/false；"
                        f"tag∈[{tag_gloss}]（emotion 与 sticker_intent 用同一 tag）。\n"
                        "- 每轮都必须发一张表情包：禁止 sticker_wanted=false；"
                        "按本条语气选最贴的情绪 tag，文案与 intent 同向。\n"
                        "- poke_wanted：多数写 false；调侃/tease/playful、熟人犯贱、"
                        "或刚被戳时可写 true 戳回对方；勿每轮都戳。\n"
                        "- 【群聊@】要点名时优先调 mention_group_member（外号/QQ）；"
                        "ACK 成功后再口语接一句。正文写 @外号 只是降级兜底。\n"
                        f"- {form_soft}不要输出文件名/路径。\n"
                        f"- 最近已发过的表情意图（尽量别连发同一情绪）：{recent_line}\n"
                    ),
                ]
                if p
            ]
        ).strip()

        user_text = _format_user_turn(
            perception,
            decision,
            with_image=bool(vision_urls),
            nearby=nearby,
            force_voice=force_voice,
        )
        user_content: Any
        if vision_urls:
            # 图在前、文在后：降低「先读完击破队上文再瞥一眼图」的偏置
            user_content = []
            for url in vision_urls:
                user_content.append({"type": "image_url", "image_url": {"url": url}})
            user_content.append({"type": "text", "text": user_text})
        else:
            user_content = user_text

        return [
            {"role": "system", "content": system},
            {"role": "user", "content": user_content},
        ]

    def _voice_capability_hint(
        self,
        *,
        force_voice: bool,
        speak_line: str = "",
    ) -> str:
        voice = self.config.get("voice") or {}
        if not voice.get("enabled"):
            return ""
        emo_line = (
            "需要发语音时末行写 voice_emotion=<情绪>，"
            "可选：happy/sad/angry/fearful/disgusted/surprised/calm "
            "（也可写中文：开心/难过/生气/害怕/惊讶/平静）。"
            "悲伤就选 sad，别默认 happy。"
            "需要笑声叹气时可在正文插入英文标签如 (laughs)(sighs)(breath)(emm)。"
        )
        if force_voice:
            line_bit = ""
            if speak_line:
                line_bit = (
                    f"- 对方要你念的内容大意是：「{speak_line}」。"
                    "正文就围绕这句话自然说出来（可极短铺垫），不要换成别的话题。\n"
                )
            return (
                "【本回合语音】对方要听你说话。系统会把你的完整回复合成语音发出；"
                "请用适合朗读的自然口语，少用*动作描写*和中文括号旁白，也不要写「正在发语音」之类元话语。\n"
                "- 这是 TTS 念白，不是点歌：禁止调用 play_song_by_name，"
                "也不要把要念的句子或口癖（如「旅途愉快」）当成歌名。\n"
                f"{line_bit}"
                f"- {emo_line}\n"
                "- 本回合必须根据内容选一个 voice_emotion。"
            )
        return (
            "【语音能力】你可以把回复念成语音。平时默认只打字；"
            "对方说「语音」「念一下」「听听」等时，系统会把该回合完整回复合成语音。\n"
            "- 「用语音说某句」≠ 点歌；没有明确点歌/放歌时不要调 play_song_by_name。\n"
            f"- {emo_line}\n"
            "- 未要求语音时不要写 voice_emotion。"
            "知道有这能力即可，不要主动推销，也不要假装已经发出语音。"
        )


def _format_now_context(*, tz_name: str = "Asia/Shanghai", cfg: dict | None = None) -> str:
    """注入当前时间，便于模型区分早晚、今天/昨天等。"""
    try:
        now = datetime.now(ZoneInfo(tz_name))
        tz_label = "东八区" if tz_name == "Asia/Shanghai" else tz_name
    except Exception:
        now = datetime.now().astimezone()
        tz_label = str(now.tzinfo or "本地")
    weekdays = ("星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日")
    period = _time_period(now.hour)
    lines = [
        f"【当前时间】{now.strftime('%Y-%m-%d %H:%M')} "
        f"{weekdays[now.weekday()]} {period}（{tz_label}）\n"
        "以上时间为准；不要根据语气、群聊梗或「刚睡醒」等自行推断钟点，"
        "也勿把「02」之类数字当成凌晨两点。"
    ]
    from .presence import is_night_hours, night_prompt_hint

    if is_night_hours(cfg, hour=now.hour):
        lines.append(night_prompt_hint())
    return "\n".join(lines)


def _time_period(hour: int) -> str:
    if hour < 6:
        return "凌晨"
    if hour < 9:
        return "早上"
    if hour < 12:
        return "上午"
    if hour < 14:
        return "中午"
    if hour < 18:
        return "下午"
    if hour < 22:
        return "晚上"
    return "深夜"


def _is_image_deixis(text: str) -> bool:
    """短指代：这个/那个/看看 + 图时，紧邻上文极易把指代绑错。"""
    t = re.sub(r"\s+", "", (text or "").strip())
    if not t:
        return True
    if len(t) > 24:
        return False
    cues = (
        "这个",
        "那个",
        "这啥",
        "那啥",
        "看看",
        "看下",
        "瞧瞧",
        "啥意思",
        "什么意思",
        "怎么看",
        "咋看",
        "怎么样",
        "咋样",
        "这是",
        "那是",
    )
    if t in cues or t in {c + "？" for c in cues} or t in {c + "?" for c in cues}:
        return True
    # 「这个嘛」「那个啊」等极短
    if len(t) <= 8 and any(t.startswith(c) for c in ("这个", "那个", "看看", "看下", "这是", "那是")):
        return True
    return False


def _format_user_turn(
    perception: Perception,
    decision: Decision,
    *,
    with_image: bool = False,
    nearby: dict[str, list[dict[str, str]]] | None = None,
    force_voice: bool = False,
) -> str:
    text = (perception.text or "").strip()
    if with_image:
        if text:
            body = text
        else:
            body = "（对方发来一张图，没有文字）"
    else:
        media = (perception.media_note or "").strip()
        if text and media:
            body = f"{text}\n（{media}）"
        elif media:
            body = f"（{media}，没有附带文字）"
        elif text:
            body = text
        else:
            body = "（对方看着你，没说话）"

    chunks: list[str] = []
    who = (perception.sender_name or "").strip()
    uid = str(perception.user_id or "").strip()
    if who or uid:
        label = who or uid
        if uid:
            chunks.append(
                f"【对方】本群称呼/昵称：{label}（QQ={uid}）。"
                f"可自然这样叫对方；要真@对方时写 @{label} 或 @[qq:{uid}]。"
                "别每句硬喊，也别改成别的外号（除非对方刚说过）。"
            )
        else:
            chunks.append(
                f"【对方】本群称呼/昵称：{label}。"
                "可自然这样叫对方，别每句硬喊，也别改成别的外号（除非对方刚说过）。"
            )

    before = (nearby or {}).get("before") or []
    after = (nearby or {}).get("after") or []
    deixis = with_image and _is_image_deixis(text)

    # 有图：先写本条，再（可选）弱上文，避免「什么队→这个」绑死指代
    if with_image:
        chunks.append(f"【本条·{who}·含配图】" if who else "【本条·含配图】")
        if deixis:
            chunks.append("（短指代默认指配图；先回应画面，勿用上文话题顶替图意）")
        else:
            chunks.append("（有配图：先看画面再回话；上文仅气氛参考）")
        if force_voice:
            speak = extract_voice_speak_line(text)
            if speak:
                chunks.append(f"（请用语音念出大意：「{speak}」；可极短反应，勿换话题）")
        if decision.action == "SHORT":
            chunks.append(f"（简短回应）{body}")
        else:
            chunks.append(body)
        # 短指代：不塞紧邻上文 / 她最近说过（system 里画像近况仍在）
        if before and not deixis and not force_voice:
            show_n = min(2, len(before))
            chunks.append(
                "【紧邻上文】（弱参考；与画面冲突时以画面为准）"
            )
            for item in before[-show_n:]:
                sp = item.get("speaker") or "?"
                tx = item.get("text") or ""
                chunks.append(f"- {sp}: {tx}")
        return "\n".join(chunks)

    if before:
        show_n = min(len(before), 3 if force_voice else len(before))
        chunks.append("【紧邻上文】（请接着这些话理解本条，勿装作没看见；本条优先）")
        for item in before[-show_n:]:
            sp = item.get("speaker") or "?"
            tx = item.get("text") or ""
            chunks.append(f"- {sp}: {tx}")
            if not force_voice and item.get("reply"):
                reply = (item.get("reply") or "")[:80]
                chunks.append(f"  └ 她当时回: {reply}")
    chunks.append(f"【本条·{who}】" if who else "【本条】")
    if force_voice:
        speak = extract_voice_speak_line(text)
        if speak:
            chunks.append(f"（请用语音念出大意：「{speak}」；可极短反应，勿换话题）")
    if decision.action == "SHORT":
        chunks.append(f"（简短回应）{body}")
    else:
        chunks.append(body)
    if after and not force_voice:
        chunks.append("【她最近说过】（语气可衔接，勿原句复读）")
        for item in after:
            chunks.append(f"- {item.get('text') or ''}")
    return "\n".join(chunks)


def parse_express(
    raw: str,
    allow_tags: list[str],
    *,
    always_sticker: bool = True,
) -> ExpressResult:
    raw = sanitize_visible_text(raw or "")
    lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
    wanted = False
    intent = "none"
    poke_wanted = False
    voice_emotion = ""
    body: list[str] = []
    for ln in lines:
        emo, ln2 = extract_voice_emotion(ln)
        if emo and not voice_emotion:
            voice_emotion = emo
        ln = ln2
        if not ln:
            continue
        emotion_m = _EMOTION_RE.search(ln)
        wm = _WANTED_RE.search(ln)
        im = _INTENT_RE.search(ln)
        pm = _POKE_WANTED_RE.search(ln)
        if emotion_m:
            intent = emotion_m.group(1).lower()
        if wm or im or emotion_m or pm:
            if wm:
                wanted = wm.group(1).lower() in ("true", "yes", "1")
            if im:
                intent = im.group(1).lower()
            if pm:
                poke_wanted = pm.group(1).lower() in ("true", "yes", "1")
            cleaned = _POKE_WANTED_RE.sub(
                "",
                _EMOTION_RE.sub(
                    "",
                    _INTENT_RE.sub("", _WANTED_RE.sub("", ln)),
                ),
            ).strip(" |;,.，。")
            if cleaned:
                body.append(cleaned)
            continue
        if _VOICE_EMO_RE.fullmatch(ln.strip()):
            continue
        body.append(ln)
    if intent not in allow_tags:
        intent = "none"
    if always_sticker:
        if intent in allow_tags:
            wanted = True
        else:
            wanted = True
            intent = _default_sticker_intent(allow_tags)
    elif not wanted:
        intent = "none"
    return ExpressResult(
        bubbles=body[:3],
        sticker_wanted=wanted,
        sticker_intent=intent,
        poke_wanted=poke_wanted,
        voice_emotion=voice_emotion,
    )


def _default_sticker_intent(allow_tags: list[str]) -> str:
    for pick in ("playful", "warm", "happy", "tease"):
        if pick in allow_tags:
            return pick
    return allow_tags[0] if allow_tags else "playful"


def split_preface_bubbles(text: str, *, max_bubbles: int = 2) -> list[str]:
    """同轮 tool_calls 前的短句，去掉 sticker 行。"""
    text = sanitize_visible_text(text or "")
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    out: list[str] = []
    for ln in lines:
        if (
            _WANTED_RE.search(ln)
            or _INTENT_RE.search(ln)
            or _EMOTION_RE.search(ln)
            or _POKE_WANTED_RE.search(ln)
        ):
            continue
        cleaned = _POKE_WANTED_RE.sub(
            "",
            _EMOTION_RE.sub(
                "",
                _INTENT_RE.sub("", _WANTED_RE.sub("", ln)),
            ),
        ).strip(" |;,.，。")
        if cleaned:
            out.append(cleaned)
        if len(out) >= max_bubbles:
            break
    return out
