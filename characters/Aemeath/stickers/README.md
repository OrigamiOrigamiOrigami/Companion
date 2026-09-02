# Aemeath 表情包素材说明

按 Companion 命名；**LLM 永不看到文件名**，只出 `sticker_wanted` + `sticker_intent`。

## 目录

```text
stickers/                        # 角色卡内置（可选）
  manifest.yaml                  # 可选：weight / 副标签 / enabled
  Aemeath_tease_01.webp
  Aemeath_warm_01.png
```

运行时覆盖（推荐上传落盘处）：

`data/stickers/Aemeath/`

```text
data/stickers/Aemeath/
  Aemeath_tired_01.gif
  Aemeath_angry_02.gif
  _emotion_stats.json            # 情绪统计
  _catalog.png                   # 图鉴缓存
```

**不再使用** `default/` 子目录。

## 文件名

`{角色id}_{primary_tag}_{seq}.{ext}`

例：`Aemeath_tease_01.gif`

- `primary_tag` ∈ tease / playful / shy / warm / lonely / guarded / quiet / speechless / happy / sad / angry / thinking / question / like / tired / cute / approve
- `seq`：`01`–`99`
- `ext`：webp / png / gif / jpg / jpeg

衍生 id 与文件名去扩展名一致：`Aemeath_tease_01`（程序内用，不进 prompt）

## 维护

放入/改名后执行 `/伴侣 表情重载`；查看：`表情图鉴`。
