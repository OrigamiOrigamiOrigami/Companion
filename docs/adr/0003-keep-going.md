# ADR-0003：群续聊 keep_going（借鉴主动闸门思路，不做私聊主动）

## Status

Accepted（2026-09-06）— 已落地

## Context

`private_companion` 有完整主动消息引擎（仪式问候、关心、额度、免打扰）。本仓已有 `ReminderScheduler`（事务提醒）与沉默默认 Decide；`keep_going` 配置长期 no-op。产品选择：**不装**对方整包，也不做私聊主动/好感度门槛；首刀只做群内「刚聊完同人短窗续一句」。

## Decision

- **范围**：仅群 `keep_going`；提醒系统并列不动；不做 `fill_silence` / 私聊找人 / 自然语言勿扰。
- **开窗**：硬 @ 或 soft_mention 且 bot 实际发出后，为该 **user_id + group** 开窗。
- **接话**：窗内、同一发言者、未再硬 @/soft_mention、非整句确认词 → `FULL` + reason=`keep_going`。
- **上限**：`keep_going_max`（默认 1）；续聊发出后仅当已续次数 &lt; 上限时刷新短窗，否则须再唤醒。
- **窗长**：`keep_going_window_sec` 默认 60。
- **工具**：默认不挂；`keep_going_allow_tools` 可开。
- **确认词**：可配精确匹配表（默认见 CONTEXT）；命中 SILENCE 且不耗额度。
- **开关**：`speech_triggers.keep_going` 默认 **true**（便于实测）。
- **判据**：纯规则；不用 LLM 判「要不要回」。

## Consequences

- Decide / 出站成功路径需记录 `conversation_window`（截止时间、发言者、已续次数）。
- 群观察路径（`group_observe`）将真正开口，不只旁观写 tape。
- 面板/schema 去掉「keep_going 暂未生效」标注；状态行反映续聊开关。
