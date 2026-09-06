# ADR-0002：被戳反应权重化（借鉴 pokepro，不装插件）

## Status

Accepted（2026-09-06）

## Context

companion 原被戳路径只有「变体文案 + 表情 + 概率回戳一次」，体感单调。`astrbot_plugin_pokepro` 有权重动作池，但与 companion 同开会抢事件，故只借鉴思路。

## Decision

- **不安装** pokepro；增强 companion 自有 `handle_poke`。
- 被戳按权重抽模式：`speech_poke` / `speech` / `antipoke` / `llm`（默认 40/25/20/15）。
- `antipoke`：连戳 2～`antipoke_max_times`（默认上限 3），带极短文案。
- `llm`：短人设一句（失败回落变体），并回戳 1 次。
- 第一期不做：QQ face、跟戳、定时戳、戳禁言。
- 出站用 `ExpressResult.poke_times` 支持连戳。

## Consequences

- 配置增加 `poke.reaction_weights`、`poke.antipoke_max_times`。
- 短 LLM 走 `ProviderRouter.chat`，与提醒文案同级轻量调用。
