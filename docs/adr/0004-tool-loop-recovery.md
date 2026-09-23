# ADR-0004：Tool Loop 恢复（借鉴 Claude Code 分层，工具无关）

## Status

Accepted（2026-09-12）

## Context

后期将扩展桌面截图、挪文件等电脑工具。原 `ToolLoopRunner` 在「无 tool_calls」时直接收尾，易出现开了工没收尾。借鉴 Claude Code 四层防护，但 companion 首刀不做回合内 413 压缩。

## Decision

- **层 1**：空 / 无 summary 的 tool 回执经 `tool_result_content_or_placeholder` 占位，并尽量保持 ACK JSON。
- **层 2**：无 tool_calls 且本回合已有工具且 ACK `needs_followup`/`done=false` → 最多 `tools.recovery_max`（默认 1）次系统 nudge，再停。
- **层 3**：Express 工具开启时注入「不调工具≠完成」提示；`allow_tools=false`（如 keep_going）不跑工具环、不 nudge。
- **层 4**：沿用 `max_rounds`、单工具失败不崩环；**不做**回合内压缩。
- **ACK 契约**：`done` / `needs_followup` / `next_hint`；jm search「有结果待 download」映射进该契约。
- **预留**：`ToolSpec.risk` / `requires_confirm` / `multi_step` + `TOOL_META`；高危确认流以后再接。

## Consequences

- 新适配器只要填 ACK 扩展字段即可吃到恢复逻辑。
- 多一轮 LLM 成本默认最多 +1。
