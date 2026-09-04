# Companion

AstrBot 社交角色 Harness：人设外置为角色卡，群聊/私聊里用 Express 说话，并可发表情与调用工具。

## Language

### Stickers

**Sticker tag**:
规范情绪桶的英文 key（如 `sleep`、`reject`）。文件名、`sticker_intent`、图鉴分组都用它。
_Avoid_: emotion（易与 TTS voice_emotion 混淆）、category（口语可说「分类」，词表里用 tag）

**表情图鉴**:
按 sticker tag 分组生成的分类缩略图长图（PNG），供人浏览库存。
_Avoid_: 图库、相册

**sleep**:
已经睡着 / 在睡觉的贴纸桶（含晚安入睡、睡着了）。上传别名含「困」「睡觉」等。
_Avoid_: sleepy、sleeping（规范 key 为 `sleep`）

**tired**:
疲惫、想睡但还没睡着（累、耗尽）。
_Avoid_: 把「已经睡着」算进 tired；别名不再含「困」

**reject**:
明确拒绝、不要、嫌弃、推开的贴纸桶。
_Avoid_: 与 `angry`（恼火）或 `speechless`（无语）混用

**mock**:
嘲笑、嘲讽、讥笑的贴纸桶。
_Avoid_: 与 `tease`（调戏/调侃）混用；戏弄亲近感用 tease，踩人感用 mock

**surprise**:
惊讶、吃惊、震惊的贴纸桶。
_Avoid_: 与 `speechless`（无语）混用；愣住但偏「哇」用 surprise，偏「…」用 speechless

**空桶**:
角色 allow 中有、磁盘无素材的 sticker tag。运行时靠近义回退；应在「表情统计 / 状态」中可见。

**lonely / guarded**:
已退役的 sticker tag（原「寂寞」「防备」）。不再进入词表与角色卡 allow-list。

### Turns & Decide

**TurnGate**:
同频道（群或私聊）的回合占用闸门：同时只跑一轮 Express。
_Avoid_: 把限流冷却（user_cooldown）叫成 TurnGate

**FIFO 排队**:
频道忙时后来的回合入队，前一轮结束后再跑；超长或超限则丢弃并打日志。
_Avoid_: 忙时直接丢弃还当正式策略（旧行为）

**Turn Aggregation**:
私聊短窗内连发合并成一轮再 Perceive。
_Avoid_: 每条私聊消息立刻各开一轮 Express

**Epoch 作废**:
某轮 Express 尚未发出时，若同频道已开启更新的回合，则丢弃过期 LLM 结果，不发送。
_Avoid_: 用「取消工具副作用」混称（工具已执行的 ACK 另论）

**keep_going（续聊）**:
群里机器人刚说过话后、用户未再 @/唤醒词仍可能接话的触发。**本阶段搁置（no-op）**；唤醒靠硬 @ / soft_mention / 私聊。
_Avoid_: 用 LLM 判「这句话算不算还要回」（易把「懂了」接成续聊）
