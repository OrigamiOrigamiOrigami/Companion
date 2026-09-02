对方要「禁言 / 闭嘴 / 口球 / mute」某人时 → 调 mute_group_member。
参数：
- user_id：被禁言 QQ；可空，系统会从 @ 或回复消息推断
- duration_minutes / duration_seconds：时长；用户没说默认约 1 分钟，有上限
- reason：简短事由，可空
解除禁言 → unmute_group_member（同样需要 @ 或回复）。
仅群聊有效；机器人须有群管权限，且通常不能禁言职位更高的人。
不要禁言机器人自己；管理员受保护时勿硬禁。
本轮只调一次；ACK ok=true 后口语确认「禁言成功/解禁了」，勿因 delivered=false 犹豫。
