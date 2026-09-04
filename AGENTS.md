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
- Group wake: hard @ / soft_mention / private. `keep_going` is intentionally **no-op** for now.
- Busy channels: FIFO queue (not drop). Private: debounce + epoch cancel.
- Reserved (panel may show; no runtime effect): `silence_prior`, `familiarity_threshold`, `llm_assist`, `intent_boost`, `form_rate_multiplier`.
- Sticker empty buckets fall back via `INTENT_FALLBACKS`; check `/伴侣 状态` or `表情统计` for gaps.
