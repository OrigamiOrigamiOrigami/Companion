# Companion — agent notes

AstrBot social-character plugin. Product root for Matt Pocock engineering skills is this directory (`companion/`).

## Agent skills

### Issue tracker

Local markdown under `.scratch/<feature-slug>/` (spec + one file per ticket). See `docs/agents/issue-tracker.md`.

### Triage labels

Default vocabulary: `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: `CONTEXT.md` + `docs/adr/` at this root (created lazily by `/grill-with-docs`). See `docs/agents/domain.md`.

## Main flow

1. `/grill-with-docs` — align on the change; sharpen glossary/ADRs
2. If multi-session: `/to-spec` → `/to-tickets`
3. `/implement` per ticket (fresh context) → `/tdd` at agreed seams → `/code-review` → commit
4. Unsure? `/ask-matt`

Notes:
- Group wake: hard @ / soft_mention / private / **keep_going**（同人短窗续聊，见 ADR-0003）。
- Private parser-share silence: `decide.silence_parser_links` (default on) → SILENCE so astrbot_plugin_parser can own the turn.
- Prefer AstrBot built-in `web_search_*` over MCP search; hide redundant MCP search tools when builtin exists. Keep MCP for weather / fetch only when needed.
- Tool surface is ungated by default (`model_decides`): all enabled adapter tools are exposed; the model decides whether/which to call. Only voice-speak / tools-off / **keep_going 默认** strip tools.
- qqadmin passthrough: allow `llm_set_group_ban` / `whole_ban` / `card` / `special_title`; denylist other qqadmin `llm_*` (see ADR-0001). Bridge must drain async-generator tool yields.
- Busy channels: FIFO queue (not drop). Private: debounce + epoch cancel.
- Reserved (panel may show; no runtime effect): `silence_prior`, `familiarity_threshold`, `llm_assist`, `intent_boost`, `form_rate_multiplier`.
- Sticker empty buckets fall back via `INTENT_FALLBACKS`; check `/伴侣 状态` or `表情统计` for gaps.
