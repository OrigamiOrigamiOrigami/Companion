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
群里硬 @ / soft_mention 唤醒且 bot 说完后，为**同一发言者**打开短窗；窗内未再唤醒也可能接话。规则（可配）：默认窗 **60s**、每轮唤醒最多续 **1** 次、默认 **不挂工具**、极短确认词表静音（不耗额度）；开关默认 **开**。续聊发出的气泡仅在「已续次数 < 上限」时刷新短窗，否则必须再唤醒。续聊回合跳过同人 `user_cooldown`，否则短窗内接不上。
_Avoid_: 用 LLM 判「要不要回」；群里任何人都能续；无上限链式；与 `fill_silence` / 私聊主动找人混谈；用熟悉度挡续聊

**主动发消息（范围定案）**:
首刀只做群 `keep_going`。不复制 private_companion 的私聊仪式/关心链路；不培养好感度作门槛；`ReminderScheduler` 保持并列事务提醒、本刀不重写。群冷插话（`fill_silence`）与自然语言「别打扰」不在本刀。
_Avoid_: 把对方整包主动引擎搬进来；用熟悉度档位挡续聊

**keep_going 确认词（默认）**:
`嗯` `嗯嗯` `好` `好的` `好哦` `行` `ok` `OK` `收到` `懂了` `知道了` `1` `哈哈哈` `哈` `草` `dd` — 整句 trim 后精确匹配则 SILENCE。
_Avoid_: 用子串匹配（会误杀「好的呀那我们…」）；把名单写死进代码不可配

**parser_link 静音**:
私聊正文像 `astrbot_plugin_parser` 会解析的分享（B站/抖音/小红书等）时 Decide=`SILENCE`，避免与解析插件双响。由 `decide.silence_parser_links` 控制（默认开）。
_Avoid_: 把群聊硬 @ 带链接也静掉；不要 import parser 做匹配

**内置网页搜索**:
AstrBot 的搜索工具。无 key 时默认 denylist 掉 `web_search_tavily` / `web_search_bocha`，只用免费 `web_search`。
_Avoid_: 把未配置的付费搜索仍挂给模型（会空枪耗轮次）

**chat / 工具面（无闸门）**:
`ToolPlan.reason=model_decides`：本回合挂上已启用适配器的**全部**工具；是否调用、调哪个由模型理解对方意图决定。仅 `voice_speak_no_tools` / 总开关关闭时不挂工具。
_Avoid_: 用关键词闸门把 jm/setu 从闲聊回合摘掉（「换一个」等指代会无法触发）

**qqadmin 透传**:
群管 LLM 走 `astrbot_plugin_qqadmin` 的 `llm_*`；companion 只放行禁言/全员禁言/改名片/改头衔，其余进 denylist。鉴权与执行均在 qqadmin。
_Avoid_: 在 companion 再写一套禁言适配器；把踢人/群拉黑默认挂给人设

**被戳反应（权重）**:
被戳不经完整 Express；按权重抽 `speech_poke` / `speech` / `antipoke` / `llm`（详见 ADR-0002）。
_Avoid_: 再装 pokepro 与 companion 双开抢戳事件

**jm 工具提示**:
skill 仍给 search/download/随机/换一本的用法提示；不作为是否挂工具的闸门。
_Avoid_: 仅当抽出本子 ID 或含「本子」二字才开放 jm 工具
