---
created: 2026-11-14 20:05
updated: 2026-11-14 20:05
---
# 参数规格与预设（引擎绑定）

> 改 `core/params.py`、`core/presets.py`、`server/routes_presets.py`、`presets.json` 或
> 转写页的预设栏之前先读这份。它回答三件事：参数默认值从哪来、预设为什么必须绑定引擎、
> 载入预设时哪些行为是**不允许**的。

## 0. 一句话

**预设 = 某个引擎的一份完整参数快照**。保存时写死引擎，载入时校验引擎；
跨引擎载入直接报错，界面上也看不到别的引擎的预设。

## 1. 唯一数据源

| 东西 | 位置 | 作用 |
| --- | --- | --- |
| 参数规格 | `core/params.py` 的 `SPECS` | 每个可调项的键（`引擎.字段`）、范围、默认值、映射到引擎配置的字段 |
| 预设读写 | `core/presets.py` 的 `PresetStore` | 校验、向后兼容读取、原子写入 |
| HTTP | `server/routes_presets.py` | `/api/presets` CRUD；读取时校验引擎 |
| 种子文件 | `presets.json` | 开发期与打包版首次启动的预设来源 |
| 界面 | `desktop/renderer/src/views/TranscribeView.svelte` + `lib/store.svelte.ts` | 只列当前引擎的预设；载入前做客户端二次校验 |

参数默认值只写在 `core/params.py`。引擎 dataclass 里的默认值只是「没有界面参数时的兜底」，
不是产品默认值；两者不一致时以规格表为准（`config_kwargs()` 会覆盖）。

## 2. 预设里存什么

```json
{
  "版本": 1,
  "预设": {
    "日语 ASMR：耳语·低底噪（Whisper 默认）": {
      "引擎": "whisper",
      "参数": { "whisper.vad_threshold": 0.25, "...": "..." }
    }
  }
}
```

- `引擎` 必须是 `core/engines.py` 注册表里的 key（`whisper` / `qwen` / `sensevoice` / `firered`）；
- `参数` 的键必须是 `引擎.字段`，并且属于同一个引擎；
- 保存时会调用 `params.normalize(engine, values)`：补当前默认值、把越界值夹回区间、
  丢掉别的引擎的键。**落盘的是完整快照**，不是「只存改过的键」；
- 客户端调参状态（`localStorage` 的 `kikusub.tuning.v2`）才只存与默认值不同的键；
  两者别混用。

## 3. 绑定规则（硬约束）

1. **保存必须带引擎**。没有引擎的预设无法判断该套到哪个参数面板，直接 422。
2. **同名预设不能跨引擎覆盖**。已存在「X」（Whisper）时，用同一个名字保存 Qwen 预设会被拒绝，
   提示换名；避免把另一套引擎的方案静默覆盖。
3. **载入必须带引擎**。`GET /api/presets/{name}` 的 `engine` 是必填 query：
   - 缺 → 422；
   - 名字不存在 → 404；
   - 预设绑定的引擎与 `engine` 不一致 → **409**，前端 toast 后不修改任何参数。
4. **界面只列当前引擎的预设**。`TranscribeView` 用
   `tuning.presets.filter((p) => p.engine === engine)` 严格过滤；切引擎会清空已选项，
   并清掉属于上一个引擎的 `activePreset`。
5. **载入是替换，不是合并**。服务端返回的是该引擎的完整快照，前端直接替换该引擎的参数表，
   不把面板里手改过的残留值混进来。

`PresetStore.resolve(name, engine)` 是规则 3 的唯一实现；路由、测试与 `core/smoke.py`
都走它，别在别处再写一份引擎比较。

## 4. 当前种子预设（2026-11-14）

| 预设名 | 引擎 | 对应的素材条件 |
| --- | --- | --- |
| 日语 ASMR：耳语·低底噪（Whisper 默认） | `whisper` | `Jap_test.mp4`：830s 日语成人 ASMR，全片耳语，**无 BGM、母带极安静**；人工精修字幕作参照 |
| 日语 ASMR：耳语·低底噪（Qwen3 默认） | `qwen` | 同上（两支日语引擎用同一支素材、同一份参照） |
| 中文短视频：快节奏·带 BGM（SenseVoice 默认） | `sensevoice` | `中文_test_1.mp4`：345s 科技口播短视频，作者剪掉气口、语速快，**持续底噪/BGM**；画面烧字幕 OCR 后人工核对作参照 |
| 中文短视频：快节奏·带 BGM（FireRed 默认） | `firered` | 同上 |

四个预设的参数值都等于 `core/params.py` 的当前默认值，由
`tests/test_params.py::test_shipped_presets_cover_every_engine_with_its_defaults` 看守。
素材、数字与结论分别在
[转录标定-AnimeWhisper-2026-11.md](../转录标定-AnimeWhisper-2026-11.md)、
[转录标定-Qwen-2026-11.md](../转录标定-Qwen-2026-11.md)、
[转录标定-中文-2026-11.md](../转录标定-中文-2026-11.md)。

> 为什么正好是这两种条件：日语片无 BGM、VAD 是主要切分手段，参数是在「不被底噪干扰」
> 的前提下调的；中文片有持续 BGM、VAD 几乎判不出停顿，真正切段靠 `max_segment_s`，
> 所以两套参数不能互相套用，也不该指望把日语耳语片的 VAD 经验直接搬过来。

## 5. 旧预设的处理

2026-11-14 之前 `presets.json` 里的 6 套「耳语 / 电影推荐 / MLX 对标」预设已经过时：
它们对应的是调参前的默认值，载入后会把已经标定好的引擎又拉回旧行为。处理方式是
**整份替换为上面 4 套**，不做兼容保留：

- 开发期：仓库根 `presets.json` 已替换；
- 打包版：删掉 `~/Library/Application Support/KikuSub/presets.json`，下次启动会从
  `KikuSub.app/Contents/Resources/python/presets.json` 重新抄一份；不删就会继续用旧副本；
- 读取层仍兼容 v1 的「平铺参数」旧格式（`PresetStore._normalize`），但未绑定引擎的旧条目
  永远不会出现在当前引擎的预设下拉里，也无法通过 `resolve()` 载入。

没有做自动迁移：旧预设的语义已经变了，静默保留比删掉更危险。

## 6. 加/改预设的流程

**只是把当前默认值再存一份**（例如调完参数后固化）：

1. 在 `core/params.py` 改默认值；
2. 用下面的脚本重新生成种子文件（不要手抄，容易漏键）：

```bash
python - <<'PY'
import json
from core import params
names = {
    "whisper": "日语 ASMR：耳语·低底噪（Whisper 默认）",
    "qwen": "日语 ASMR：耳语·低底噪（Qwen3 默认）",
    "sensevoice": "中文短视频：快节奏·带 BGM（SenseVoice 默认）",
    "firered": "中文短视频：快节奏·带 BGM（FireRed 默认）",
}
payload = {"版本": 1, "预设": {}}
for engine, name in names.items():
    payload["预设"][name] = {"引擎": engine, "参数": params.defaults_for(engine)}
with open("presets.json", "w", encoding="utf-8") as fh:
    json.dump(payload, fh, ensure_ascii=False, indent=2)
    fh.write("\n")
PY
```

3. 跑 `pytest -q tests/test_params.py tests/test_presets.py`。

**用户自己存预设**：转写页右下角填名字 → 保存；客户端会把当前引擎的完整参数发给
`POST /api/presets`，服务端再规范化一次。改名/删除仍走原来的 PUT/DELETE，
名字冲突会拒绝而不是覆盖。

## 7. 测试守卫

| 测试 | 守什么 |
| --- | --- |
| `tests/test_params.py::test_every_preset_key_exists_in_specs` | 种子文件里的键都在规格表里 |
| `tests/test_params.py::test_shipped_presets_cover_every_engine_with_its_defaults` | 四个引擎各恰好一份、值等于当前默认值 |
| `tests/test_presets.py::test_save_requires_engine` | 无引擎/非法引擎不能保存 |
| `tests/test_presets.py::test_resolve_rejects_cross_engine_load` | 跨引擎载入被拒 |
| `tests/test_presets.py::test_cannot_overwrite_another_engines_preset` | 同名跨引擎覆盖被拒 |
| `tests/test_server_api.py::test_preset_roundtrip` | HTTP 层 404 / 409 / 422 与过滤 |
| `core/smoke.py` 第 4 段 | 内核在干净解释器里仍能完成 CRUD 与引擎校验 |
