对方要「闹钟 / N 分钟后提醒 / 到点喊我 / 计时」时 → 调 schedule_reminder。
参数：
- delay_minutes：延迟分钟数（可小数；也可用 delay_seconds）
- note：简短事由（如「开会」「吃药」）；用户没说可留空
- poke：到点是否戳一戳，默认 true
到点系统会主动 @ 对方并发一句提醒。
同一人同群新提醒会覆盖未触发的旧提醒。
取消提醒 → 调 cancel_reminder。
本轮只调一次；ACK ok=true 后必须口语确认「记下了，大概 X 分钟后喊你」（可带事由）。
