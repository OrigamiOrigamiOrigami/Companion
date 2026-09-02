# Companion（社交角色 Harness）

AstrBot 社交角色插件。人设外置为角色卡；当前默认卡 **Aemeath（爱弥斯）**。
旧卡 `characters/daniya/` 暂留，定稿后可删。

**当前版本：0.3.1**

## 文档

- 角色卡：[`characters/Aemeath/`](characters/Aemeath/)（见 [`填写清单.md`](characters/Aemeath/填写清单.md)）
- 旧卡：[`characters/daniya/`](characters/daniya/)
- 需求文档：[`PRD.md`](PRD.md)

## 配置

1. **AstrBot 配置面板** — [`_conf_schema.json`](_conf_schema.json)
2. **示例** — [`config/default_config.example.json`](config/default_config.example.json)

| 块 | 说明 |
|----|------|
| `active_character` | 默认角色卡 ID（`Aemeath`） |
| `group` | 群沉默、冷却、同文去重、speech_triggers |
| `reminders` | 延时提醒（到点 @ + 可选戳一戳） |
| `memory` | 情景记忆 / 群 tape / 画像注入 |
| `stickers` | 表情包选图 |
| `voice` | MiniMax TTS |
| `poke` | 戳一戳（入站回复 / 出站回戳） |

### 群限流（`group`）

| 键 | 默认 | 说明 |
|----|------|------|
| `user_cooldown_sec` | 8 | 同一人短窗冷却，命中则旁观入库、不调 LLM |
| `dedupe_sec` | 45 | 同一人同文去重窗口 |
| `cooldown_sec` | 6 | 兼容旧配置；`user_cooldown_sec` 未设时回落用它 |

## 安装

1. 目录：`data/plugins/companion`
2. 面板启用 **companion**（旧 `daniya` 插件请禁用/删除）
3. `/companion status`

## 命令

入口可用：`/companion` · `/伴侣` · `/人设` · `/小伴`（中英子命令互通）

- `/伴侣 状态` · `开` · `关`（群）
- `/伴侣 供应商` · `供应商 claude` · `供应商 minimax`（管理员；多供应商切换）
- `/伴侣 语音 开|关`
- `/伴侣 表情重载` · `表情统计` · `表情图鉴`（分类缩略图 PNG；也可直接发 `表情图鉴`）
- `上传 疲惫` + 图 / 回复图 / 图片直链（支持 `上传疲惫https://…gif` 粘连写法）
- `/伴侣 画像` · `画像 刷新`（查看限私聊）
- `/伴侣 清除记忆`（也可直接发：清除记忆）
- `添加管理员 @某人` · `@某人 添加管理员`；删除同理（仅超管；也可带 `/伴侣`）
- `管理员名单`
- `/伴侣 帮助`

### 权限

| 角色 | 来源 | 能力 |
|------|------|------|
| 超管 | 面板「超级管理员QQ号」 | 全部管理权限 + 增删管理员 |
| 管理员 | 面板「管理员QQ号」或超管命令 | 上传表情等管理权限 |
| 平台群管 | AstrBot `is_admin()` | 同管理员（不能改名单） |

超管名单只能改面板；管理员名单命令改完会写回面板。

## 能力摘要（0.3.1）

### 提醒

- 自然语言「N 分钟后提醒我…」→ `schedule_reminder`（可取消）
- 到点主动 @，可选戳一戳；**文案走短人设 LLM**（失败回落变体池）
- 提醒类以 `ok=true` 为准，勿被 `delivered=false`（媒体送达语义）误导

### 群禁言

- 「禁言/闭嘴/口球 @某人」→ `mute_group_member`；「解禁」→ `unmute_group_member`
- 目标：@、回复消息、或 QQ 号；也可「禁言我」
- 默认约 1 分钟，最长 1 小时（可配）；超管/管理员默认受保护
- **机器人必须是群管**，且通常无法禁言职位更高的人

### 记忆与群聊

- 群 tape + 同人 episodic 近况，避免刷屏挤掉刚交代的事
- **群友卡**（`display_name` / 外号）：落盘并注入「对方 + 邻座」
- 待办提醒注入 `【待办提醒】`
- **上游安全拒答**（如「当前输入涉及敏感信息…」）不写入记忆、不进下一轮上下文；出站改人设兜底

### 表达与工具

- 每轮表情意图；缺 tag 资源时近义回退（如 `happy` → `warm`/`playful`）
- 工具环：闲聊 1 次 LLM；调工具时 2 次（选工具 + 收尾），提醒等会更慢属正常
- 前言已说过时，不再补发占位「……」

### 戳一戳 / 语音

- 入站戳一戳可短回；出站可按 `poke_wanted` 回戳
- 支持强制语音念白（与点歌意图区分）

## 更新记录

### 0.3.1

- 新增：群聊真@点名工具 `mention_group_member`（skill 主路径）；正文 `@外号` 仅降级
- 修复：重复工具调用不再复读成功 ACK；`mention` 成功时 `delivered=true`，次数与实际一致
- 新增：多供应商 `claude` / `minimax` 切换；失败自动回退就绪供应商
- 修复：Claude 网关 Cloudflare 1010（补浏览器 User-Agent）
- 优化：供应商面板与命令统一为 claude

### 0.3.0

- 新增：延时提醒调度 + 到点 LLM 文案
- 新增：同文去重 / 同人冷却限流
- 新增：群友卡落盘与注入
- 新增：上游安全拒答过滤（记忆读写 + 出站）
- 新增：超管 / 管理员分层；`/companion admin add|remove|list`
- 新增：群禁言 / 解禁工具（OneBot `set_group_ban`）
- 修复：工具收尾只出控制行时不再刷「……」
- 修复：降级兜底句不再硬塞表情包
- 优化：表情缺图近义回退；提醒工具提示与 ACK 语义

### 0.2.0

- 角色卡 Harness、群决策、记忆、表情、工具桥、语音等基线能力
