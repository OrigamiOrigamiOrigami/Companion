from __future__ import annotations

import json
import logging
import os
import time
from typing import Any

from ..provider.safety_refuse import is_upstream_safety_refusal, scrub_memory_item

logger = logging.getLogger("astrbot")


class MemoryStore:
    def __init__(
        self,
        data_dir: str,
        character_ns: str = "companion",
        memory_cfg: dict[str, Any] | None = None,
    ):
        self.root = os.path.join(data_dir, "memory", character_ns)
        self.memory_cfg = memory_cfg or {}
        os.makedirs(self.root, exist_ok=True)

    def _user_dir(self, user_id: str) -> str:
        p = os.path.join(self.root, "users", str(user_id))
        os.makedirs(os.path.join(p, "episodic"), exist_ok=True)
        return p

    def _episodic_path(self, user_id: str, channel: str) -> str:
        safe = channel.replace(":", "_")
        return os.path.join(self._user_dir(user_id), "episodic", f"{safe}.json")

    def _group_tape_path(self, group_id: str) -> str:
        safe = str(group_id).replace(":", "_")
        groups_dir = os.path.join(self.root, "groups")
        os.makedirs(groups_dir, exist_ok=True)
        return os.path.join(groups_dir, f"group_{safe}.json")

    def load_portrait(self, user_id: str) -> dict[str, Any]:
        path = os.path.join(self._user_dir(user_id), "portrait.json")
        if not os.path.isfile(path):
            return empty_portrait()
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.warning("画像加载失败: %s", e)
            return empty_portrait()

    def save_portrait(self, user_id: str, data: dict[str, Any]) -> None:
        path = os.path.join(self._user_dir(user_id), "portrait.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def append_episodic(
        self,
        user_id: str,
        channel: str,
        item: dict[str, Any],
        quota: int = 500,
        *,
        mark_dirty: bool = True,
    ) -> None:
        cleaned = scrub_memory_item(item)
        if cleaned is None:
            logger.info("companion 记忆跳过上游安全拒答（episodic）")
            return
        path = self._episodic_path(user_id, channel)
        items = self._load_episodic_file(path)
        items.append(cleaned)
        items = self._prune_episodic(items, quota=quota)
        self._save_episodic_file(path, items)
        if mark_dirty and not cleaned.get("observed") and cleaned.get("reply"):
            self._mark_dirty(user_id)

    def append_group_tape(
        self, group_id: str, item: dict[str, Any], quota: int | None = None
    ) -> None:
        cleaned = scrub_memory_item(item)
        if cleaned is None:
            logger.info("companion 记忆跳过上游安全拒答（group_tape）")
            return
        path = self._group_tape_path(group_id)
        cap = quota if quota is not None else int(
            self.memory_cfg.get("group_tape_quota") or 200
        )
        items = self._load_group_tape_file(path)
        items.append(cleaned)
        items = self._prune_episodic(items, quota=cap)
        self._save_episodic_file(path, items)

    def recent_group_tape(self, group_id: str, n: int = 12) -> list[dict]:
        path = self._group_tape_path(group_id)
        items = self._load_group_tape_file(path)
        return items[-n:] if n > 0 else []

    def _mark_dirty(self, user_id: str) -> None:
        portrait = self.load_portrait(user_id)
        if portrait.get("dirty"):
            return
        portrait["dirty"] = True
        portrait["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        self.save_portrait(user_id, portrait)

    def recent_episodic(self, user_id: str, channel: str, n: int = 2) -> list[dict]:
        path = self._episodic_path(user_id, channel)
        items = self._load_episodic_file(path)
        return items[-n:] if n > 0 else []

    def nearby_context(
        self,
        user_id: str,
        channel: str,
        *,
        before_n: int = 3,
        after_n: int = 3,
        current_text: str = "",
    ) -> dict[str, list[dict[str, str]]]:
        """
        紧邻上下文：上 before_n 条（触发前消息），下 after_n 条（她最近说过的话）。
        供本回合用户消息直接塞入，加强连贯。
        """
        before_n = max(0, int(before_n))
        after_n = max(0, int(after_n))
        before: list[dict[str, str]] = []
        after: list[dict[str, str]] = []
        cur = (current_text or "").strip()

        if channel.startswith("group:"):
            gid = channel.split(":", 1)[1]
            raw = self.recent_group_tape(gid, n=max(before_n + after_n + 8, 12))
            # 去掉刚写入、与本条完全相同的尾项（竞态）
            if raw and cur:
                last = raw[-1]
                last_txt = (last.get("text") or last.get("summary") or "").strip()
                if last_txt == cur and str(last.get("user_id") or "") == str(user_id):
                    raw = raw[:-1]
            for e in raw[-before_n:]:
                speaker = (e.get("speaker") or e.get("user_id") or "?")[:16]
                uid = str(e.get("user_id") or "")
                if uid and uid not in speaker:
                    speaker = f"{speaker}({uid})"
                user_part = (e.get("summary") or e.get("text") or "").strip()[:120]
                if not user_part or is_upstream_safety_refusal(user_part):
                    continue
                line = {
                    "speaker": speaker,
                    "text": user_part,
                    "user_id": str(e.get("user_id") or ""),
                }
                reply = str(e.get("reply") or "").strip()
                if reply and not is_upstream_safety_refusal(reply):
                    line["reply"] = reply[:100]
                before.append(line)
            # 群刷屏会把「同人刚交代的事」挤出 tape；用该用户 episodic 补回
            before = self._merge_same_user_episodic(
                before,
                user_id=user_id,
                channel=channel,
                current_text=cur,
                keep=max(3, min(before_n, 5)),
            )
            # 「下」：她侧最近说过（带 reply 的回合），不含已出现在 before 里的重复
            seen_replies: set[str] = set()
            for e in reversed(raw):
                rep = (e.get("reply") or "").strip()
                if not rep or rep in seen_replies or is_upstream_safety_refusal(rep):
                    continue
                seen_replies.add(rep)
                after.append({"speaker": "她", "text": rep[:120]})
                if len(after) >= after_n:
                    break
            # 同人 episodic 里她侧回复也补进 after（防 tape 挤掉）
            for e in reversed(self.recent_episodic(user_id, channel, n=after_n + 4)):
                if e.get("observed"):
                    continue
                txt = (e.get("text") or e.get("summary") or "").strip()
                if cur and txt == cur:
                    continue
                rep = (e.get("reply") or "").strip()
                if not rep or rep in seen_replies or is_upstream_safety_refusal(rep):
                    continue
                seen_replies.add(rep)
                after.insert(0, {"speaker": "她", "text": rep[:120]})
                if len(after) >= after_n:
                    break
            after = after[-after_n:]
        else:
            raw = self.recent_episodic(user_id, channel, n=max(before_n + after_n + 4, 8))
            if raw and cur:
                last_txt = (raw[-1].get("text") or raw[-1].get("summary") or "").strip()
                if last_txt == cur:
                    raw = raw[:-1]
            for e in raw[-before_n:]:
                user_part = (e.get("summary") or e.get("text") or "").strip()[:120]
                if not user_part or is_upstream_safety_refusal(user_part):
                    continue
                line = {
                    "speaker": "你",
                    "text": user_part,
                    "user_id": str(user_id),
                }
                reply = str(e.get("reply") or "").strip()
                if reply and not is_upstream_safety_refusal(reply):
                    line["reply"] = reply[:100]
                before.append(line)
            for e in reversed(raw):
                rep = (e.get("reply") or "").strip()
                if not rep or is_upstream_safety_refusal(rep):
                    continue
                after.append({"speaker": "她", "text": rep[:120]})
                if len(after) >= after_n:
                    break
            after.reverse()

        return {"before": before, "after": after}

    def episodic_digest(self, user_id: str, limit: int = 20) -> list[dict[str, Any]]:
        episodic_dir = os.path.join(self._user_dir(user_id), "episodic")
        merged: list[dict[str, Any]] = []
        if not os.path.isdir(episodic_dir):
            return []
        for name in os.listdir(episodic_dir):
            if not name.endswith(".json"):
                continue
            if name == "private.json":
                channel = "private"
            elif name.startswith("group_"):
                channel = f"group:{name[6:-5]}"
            else:
                channel = name[:-5].replace("_", ":", 1)
            path = os.path.join(episodic_dir, name)
            for item in self._load_episodic_file(path):
                if item.get("observed"):
                    continue
                merged.append(
                    {
                        "channel": channel,
                        "at": item.get("ts"),
                        "summary": item.get("summary") or item.get("text") or "",
                        "reply": item.get("reply") or "",
                    }
                )
        merged.sort(key=lambda x: float(x.get("at") or 0))
        return merged[-limit:]

    def count_episodic_since(self, user_id: str, since_ts: float | None) -> int:
        episodic_dir = os.path.join(self._user_dir(user_id), "episodic")
        if not os.path.isdir(episodic_dir):
            return 0
        count = 0
        for name in os.listdir(episodic_dir):
            if not name.endswith(".json"):
                continue
            path = os.path.join(episodic_dir, name)
            for item in self._load_episodic_file(path):
                if item.get("observed"):
                    continue
                ts = float(item.get("ts") or 0)
                if since_ts is None or ts >= since_ts:
                    count += 1
        return count

    def clear_user(self, user_id: str) -> None:
        import shutil

        path = os.path.join(self.root, "users", str(user_id))
        if os.path.isdir(path):
            shutil.rmtree(path, ignore_errors=True)
        logger.info("companion 记忆已清空 用户=%s", user_id)

    def upsert_anchor(self, user_id: str, key: str, value: Any) -> dict[str, Any]:
        portrait = self.load_portrait(user_id)
        anchors = portrait.get("anchors") or []
        now = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        for a in anchors:
            if a.get("key") == key:
                a["value"] = value
                a["updated_at"] = now
                break
        else:
            anchors.append({"key": key, "value": value, "updated_at": now})
        max_anchors = int(self.memory_cfg.get("portrait_max_anchors") or 30)
        portrait["anchors"] = anchors[:max_anchors]
        portrait["dirty"] = True
        portrait["updated_at"] = now
        self.save_portrait(user_id, portrait)
        return portrait

    def inject_block(
        self,
        user_id: str,
        channel: str,
        max_chars: int = 400,
        *,
        portrait_only: bool = False,
    ) -> str:
        portrait = self.load_portrait(user_id)
        max_epi = min(int(self.memory_cfg.get("max_inject") or 6), 3)
        epi = [] if portrait_only else self.recent_episodic(user_id, channel, n=max_epi)
        impression = (portrait.get("impression") or "").strip()
        anchors = portrait.get("anchors") or []
        anchor_line = "; ".join(
            f"{a.get('key')}={a.get('value')}"
            for a in anchors
            if a.get("value") is not None
        )
        fam = portrait.get("familiarity") or "stranger"
        parts = [f"【她眼中的你】熟悉度={fam}"]
        if impression:
            parts.append(impression[:max_chars])
        if anchor_line:
            parts.append(f"事实锚点（优先于印象文案）: {anchor_line}")
        if portrait_only:
            return "\n".join(parts)
        if channel.startswith("group:"):
            gid = channel.split(":", 1)[1]
            # 先注入同人 episodic，再塞群 tape——刷屏挤掉时仍能看见「刚交代的事」
            duo_n = min(int(self.memory_cfg.get("max_inject") or 6), 4)
            duo = self.recent_episodic(user_id, channel, n=duo_n)
            duo_lines: list[str] = []
            duo_texts: set[str] = set()
            for e in duo:
                if e.get("observed"):
                    continue
                user_part = (e.get("summary") or e.get("text") or "")[:100]
                reply_part = (e.get("reply") or "")[:80]
                if not user_part or is_upstream_safety_refusal(user_part):
                    continue
                if is_upstream_safety_refusal(reply_part):
                    reply_part = ""
                duo_texts.add(user_part.strip())
                if reply_part:
                    duo_lines.append(f"- 你: {user_part} → 她: {reply_part}")
                else:
                    duo_lines.append(f"- 你: {user_part}")
            if duo_lines:
                parts.append("【你俩近况】（同人刚对她说的；优先于群流水；被问「刚才交代什么」时以此为准）")
                parts.extend(duo_lines)

            tape_n = int(self.memory_cfg.get("group_tape_inject") or 12)
            if self.memory_cfg.get("group_tape_enabled", True):
                tape = self.recent_group_tape(gid, n=tape_n)
                if tape:
                    parts.append("【群里最近（含她未接话的消息）】")
                    for e in tape:
                        speaker = (e.get("speaker") or e.get("user_id") or "?")[:16]
                        uid = str(e.get("user_id") or "")
                        if uid and uid not in speaker:
                            speaker = f"{speaker}({uid})"
                        user_part = (e.get("summary") or e.get("text") or "")[:80]
                        reply_part = (e.get("reply") or "")[:60]
                        if not user_part or is_upstream_safety_refusal(user_part):
                            continue
                        if is_upstream_safety_refusal(reply_part):
                            reply_part = ""
                        # 与【你俩近况】重复的同人条目跳过，省字数
                        if (
                            str(e.get("user_id") or "") == str(user_id)
                            and (user_part or "").strip() in duo_texts
                        ):
                            continue
                        if reply_part:
                            parts.append(f"- {speaker}: {user_part} → 她: {reply_part}")
                        else:
                            parts.append(f"- {speaker}: {user_part}")
        elif epi:
            parts.append("【本频道近况】")
            for e in epi:
                user_part = (e.get("summary") or e.get("text") or "")[:80]
                reply_part = (e.get("reply") or "")[:60]
                if not user_part or is_upstream_safety_refusal(user_part):
                    continue
                if is_upstream_safety_refusal(reply_part):
                    reply_part = ""
                if reply_part:
                    parts.append(f"- 你: {user_part} → 她: {reply_part}")
                else:
                    parts.append(f"- {user_part}")
        parts.append("（事实以锚点为准；印象仅供语气；勿泄露私聊原文到群里）")
        return "\n".join(parts)[: max_chars + 900]

    def _merge_same_user_episodic(
        self,
        before: list[dict[str, str]],
        *,
        user_id: str,
        channel: str,
        current_text: str,
        keep: int = 3,
    ) -> list[dict[str, str]]:
        """把同人近期对话补进紧邻上文，避免被群流水挤掉。"""
        cur = (current_text or "").strip()
        seen = {(b.get("text") or "").strip() for b in before}
        extras: list[dict[str, str]] = []
        for e in self.recent_episodic(user_id, channel, n=keep + 2):
            if e.get("observed"):
                continue
            user_part = (e.get("summary") or e.get("text") or "").strip()[:120]
            if not user_part or user_part == cur or user_part in seen:
                continue
            if is_upstream_safety_refusal(user_part):
                continue
            seen.add(user_part)
            line = {
                "speaker": "你",
                "text": user_part,
                "user_id": str(user_id),
            }
            reply = str(e.get("reply") or "").strip()
            if reply and not is_upstream_safety_refusal(reply):
                line["reply"] = reply[:100]
            extras.append(line)
        if not extras:
            return before
        # 同人近况放前，再拼群流水；总长控制避免 prompt 膨胀
        merged = extras[-keep:] + before
        cap = max(len(before), keep) + keep
        return merged[-cap:]

    def _load_episodic_file(self, path: str) -> list[dict]:
        if not os.path.isfile(path):
            return []
        try:
            with open(path, "r", encoding="utf-8") as f:
                items = json.load(f) or []
        except Exception:
            return []
        quota = int(self.memory_cfg.get("quota_episodic") or 500)
        return self._prune_episodic(items, quota=quota)

    def _load_group_tape_file(self, path: str) -> list[dict]:
        if not os.path.isfile(path):
            return []
        try:
            with open(path, "r", encoding="utf-8") as f:
                items = json.load(f) or []
        except Exception:
            return []
        quota = int(self.memory_cfg.get("group_tape_quota") or 200)
        return self._prune_episodic(items, quota=quota)

    def _save_episodic_file(self, path: str, items: list[dict]) -> None:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(items, f, ensure_ascii=False, indent=2)

    def _prune_episodic(self, items: list[dict], quota: int) -> list[dict]:
        ttl_days = int(self.memory_cfg.get("episodic_ttl_days") or 90)
        cutoff = time.time() - ttl_days * 86400
        kept = [i for i in items if float(i.get("ts") or 0) >= cutoff]
        return kept[-quota:]


def empty_portrait() -> dict[str, Any]:
    return {
        "version": 1,
        "updated_at": None,
        "familiarity": "stranger",
        "form_bias": None,
        "impression": "",
        "anchors": [],
        "dirty": False,
        "consecutive_failures": 0,
        "last_consolidate_at": None,
        "consolidate_backoff_until": None,
    }
