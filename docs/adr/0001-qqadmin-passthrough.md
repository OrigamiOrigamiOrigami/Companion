# ADR-0001：qqadmin 群管透传

## Status

Accepted（2026-09-06）

## Context

群管能力由 `astrbot_plugin_qqadmin` 提供。companion 不再自建禁言适配器；需决定 LLM 可见范围与收尾策略。

## Decision

- **透传**：依赖 qqadmin 已注册的 `llm_*`，不做 companion handlers 包装（痛了再包）。
- **白名单可见**：`llm_set_group_ban`、`llm_set_group_whole_ban`、`llm_set_group_card`、`llm_set_group_special_title`。
- **其余 qqadmin LLM 工具默认 denylist**（踢人/群拉黑/精华/公告/文件等）；群内指令仍可用。
- **鉴权**：交给 qqadmin（`need_auth`）；companion 不叠权限层。
- **收尾**：上述四工具进 single-shot / terminal intent。
- **skill**：轻量 `astrbot/qqadmin.md`。
- **group_manager**：暂留（验证码入群 + 零点打卡）；qqadmin 无对等能力，移植完成前不删。

## Consequences

- companion 工具桥需能消费 async generator（`yield`）型 llm_tool 回执。
- 现场配置 `工具黑名单` 需含 qqadmin 隐藏项；新装默认配置已带上。
