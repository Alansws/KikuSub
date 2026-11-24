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
| 歌曲 | `whisper` | 40:20–44:24 的强 BGM 歌曲段；`max_segment_s=15 / merge_gap_s=0.5 / min_silence_ms=300`，配合「人声分离」勾选使用 |
| 日语 ASMR：轻声耳语·Silero 切分 | `whisper` | 同一支耳语素材的「Silero 切分 + 上一句提示」专项：`vad_backend=silero / vad_threshold=0.25 / use_prev_text_prompt=true`（见 §8.1），配合**关闭人声分离**使用。同进程对照：**11.55%**（同配置关提示 15.49%；WhisperSeg 0.45 是 12.11%）。**定位：不宣称 CER 最低**，选它的理由是**时间轴更贴发声**——但要说清来源：紧的是 Silero 的 20s 分窗机制，**不是** `use_prev_text_prompt`（后者只改文本、不动边界，段内静音 4.5% → 4.5% 不变）。实测段内静音 4.5%（WhisperSeg 12.4%）、劈词 11（19）、最长条 4.22s（WhisperSeg 4.48s）；追求字面 CER 最低请直接用默认的 WhisperSeg 0.45（12.11%） |

前四个预设的参数值都等于 `core/params.py` 的当前默认值；「歌曲」与
「日语 ASMR：轻声耳语·Silero 切分」是 Whisper 的同引擎命名方案（不是默认快照）。
由 `tests/test_params.py::test_shipped_presets_cover_every_engine_with_its_defaults` 看守：
每个引擎恰好一份默认快照，另允许 Whisper 这两个变体，且 ASMR 变体的三个关键值
（`vad_backend=silero` / `vad_threshold=0.25` / `use_prev_text_prompt=true`）不许被调回默认。
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
# Whisper 的「歌曲」变体：默认值 + 3 个强 BGM 参数。
song = params.defaults_for("whisper")
song.update({
    "whisper.vad_max_segment_s": 15.0,
    "whisper.vad_merge_gap_s": 0.5,
    "whisper.vad_min_silence_ms": 300,
})
payload["预设"]["歌曲"] = {"引擎": "whisper", "参数": song}
# Whisper 的「轻声耳语」变体：默认值 + Silero 切分 + 上一句文本提示。
whisper_asmr = params.defaults_for("whisper")
whisper_asmr.update({
    "whisper.vad_backend": "silero",
    "whisper.vad_threshold": 0.25,
    "whisper.use_prev_text_prompt": True,
})
payload["预设"]["日语 ASMR：轻声耳语·Silero 切分"] = {
    "引擎": "whisper",
    "参数": params.normalize("whisper", whisper_asmr),
}
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
| `tests/test_params.py::test_shipped_presets_cover_every_engine_with_its_defaults` | 四个引擎各恰好一份默认快照；额外只允许 Whisper「歌曲」与「轻声耳语·Silero 切分」两个变体 |
| `tests/test_presets.py::test_save_requires_engine` | 无引擎/非法引擎不能保存 |
| `tests/test_presets.py::test_resolve_rejects_cross_engine_load` | 跨引擎载入被拒 |
| `tests/test_presets.py::test_cannot_overwrite_another_engines_preset` | 同名跨引擎覆盖被拒 |
| `tests/test_server_api.py::test_preset_roundtrip` | HTTP 层 404 / 409 / 422 与过滤 |
| `core/smoke.py` 第 4 段 | 内核在干净解释器里仍能完成 CRUD 与引擎校验 |

## 8. P0 新增参数（2026-11-20）

| 键 | 默认 | 作用 |
| --- | --- | --- |
| `whisper.vad_backend` | whisperseg | 切分器：`whisperseg`（推荐，首次使用下载约 114MB）/ `silero`（Silero 20s，无需权重）。旧值 `auto`/`silero20`/`silero10` 会回落到默认；已否决的 TEN 不再可选 |
| `whisper.enable_start_repair` | true | 保留 end，只把 Anime Whisper 段首的底噪/长静音按音频证据向右收；关闭 = 旧时间轴逐字节一致 |
| `whisper.nonverbal_qa` | true | 纯喘息/笑声/拟声被字幕剔除后进质检队列（最多 20 条），不静默消失 |
| `qwen.nonverbal_qa` | false | 同上；Qwen 对呼吸声敏感，默认关闭避免长片一次多出二十条待核，需要时手动打开；CTC 时间轴不变 |

老预设没有这三个键时，`params.normalize()` 补当前默认值；保存时写完整快照。
它们都不改变引擎绑定、不新增引擎 key，因此不触发跨引擎 409 规则。

## 8.1 反幻觉开关：`whisper.use_prev_text_prompt`（2026-11-22）

| 键 | 默认 | 作用 |
| --- | --- | --- |
| `whisper.use_prev_text_prompt` | false | 把**上一条已定稿字幕**的文本作为 Whisper 的 `prompt_ids` 送给下一条：只补语义上下文，**不改字幕边界** |

存在的理由与边界：

- 「Silero 切得紧但短段会幻觉」是这条素材上的主要病（1.2s 的 `当店、` 被解成 `だーてん`）。
  曾考虑「多截 0.3–0.5s 音频再按原边界裁回」，但 Anime Whisper 没有 CTC 对齐头，
  裁不回去，会串句——所以改成只喂文本。
- 实测（日语 ASMR 单人女声耳语，320s，36 条人工参考 / 355 字）：
  Silero 0.25 **CER 15.49% → 11.55%**（劈词 11 → 11，段内静音 4.5% 不变，
  最长条 4.22s 不变）；WhisperSeg 0.45 **12.11% → 26.76%**（反而差 14.6pt，见下一条）。
  **这组 15.49/11.55 是修完 `_refine_bounds_by_pauses` 的 `vad.reset_states()` 之后
  重跑的数字**（2026-11-22 当天两跑逐条一致，仅 1 处句尾差 32ms）。历史值 17.46/13.80
  来自修复前的 `runs3/`，是带状态 Silero 探针造成的漂移产物，**不再引用**。
  WhisperSeg 两轮数字逐位可复现，说明漂移只在 Silero 的 VAD 边界上。
- **只对 Silero 有效**：同一支素材上 WhisperSeg 0.45 打开它是 **12.11% → 26.76%**
  （WhisperSeg 的段更短，上一句容易被整段复述进下一段）。因此
  `backend_only="silero"`：面板按后端置灰，代码里
  `prev_text_prompt_enabled(开关, 实际使用的后端)` 是唯一的门——只置灰不改行为属于欺骗（§9）。
  用户勾了但后端不生效时，`segment_stats["prev_text_prompt_ignored_backend"]` 留痕。
- 代价：个别短句会**换一种错法**（`だーてん` → `0点`），并偶发 `♡`、片假名等杂讯。
  因此默认关；对白/动画片应 A/B 后再决定。产品里以预设
  「日语 ASMR：轻声耳语·Silero 切分」提供（见 §4）。

实现约束（改之前先看这几条，它们都是实测踩出来的）：

1. **上下文只走显式参数**。`_decode_chunk(..., prompt_text=...)` 不读实例状态：
   `ENGINE` 是模块级单例，整片转写、核对台单句重转（`core.short_clip`）、
   「另一引擎听一遍」（`transcribe_window`）共用同一个实例；把「上一句是什么」存在
   实例上，上一次整片任务的尾巴会污染下一次单句重转，取消/异常退出还会留下旧上下文。
   守卫是 `tests/test_prompt_ids.py::test_no_prompt_text_means_no_prompt`。
2. **四道闸门在 `prompt_text_for()`**（唯一判断处，纯函数、有单测）：
   ① 上一句被幻觉门控判为可疑 `suspicious` → 不传；② 与上一句间隔
   `> PROMPT_MAX_GAP_S`（3.0s，换场/长停顿）→ 不传；③ 去掉装饰符号后没有实义字符
   （`♪♡…`）→ 不传；④ 病理性复读（与幻觉门控同一条 `REPEATED_CHUNK_RE`）→ 不传。
   装饰符号（`♡♪☆` 等）一律先剥掉：它们不发音，留着会被模型照抄。
3. **设备**：`get_prompt_ids()` 返回 CPU 张量，必须 `.to(pipe.device)`——MPS 上漏掉
   直接 `Passed CPU tensor to MPS op`。
4. **失败熔断**：`tokenizer.get_prompt_ids()` 抛错时只把本轮
   `last_prompt_ids_stats["enabled"]` 置 False（`failed` 计数 +1），字幕照出、
   后续段落不再重试；下一次整片转写重新武装。熔断只影响本次任务，不影响别的调用方
   （它们本来就不传 `prompt_text`）。

## 9. 后端限定参数与标定推荐（2026-11-20）

VAD 切分器有两个后端，参数面板里有一部分微调只对其中一个有意义。这类关系写在
`ParamSpec` 上，**前端不另写一份白名单**：

| 字段 | 含义 | 现在的用法 |
| --- | --- | --- |
| `backend_only` | 只对某个兄弟枚举值生效（值是那个枚举的 value） | `whisper.vad_onset_pad_ms` → `silero`：它补偿的是 Silero 的起点系统性偏晚；WhisperSeg 的帧级概率已贴合句首，`core/transcribe.py` 按**实际使用的后端**把它置 0，并在 `segment_stats["onset_pad_ignored_backend"]` 留痕（报告显示「仅 Silero 生效」）。`whisper.use_prev_text_prompt` → `silero`：WhisperSeg 上会明显退化（§8.1），门在 `prev_text_prompt_enabled()` |
| `backend_notes` | 按兄弟枚举值给出的校准文案 | `whisper.vad_threshold`：WhisperSeg 0.45 / Silero 0.25（2026-11-22 由 0.35 上调，见 §8.1） |
| `backend_recommended` | 按兄弟枚举值给出的推荐数值，前端提供「用 0.45」一击校准 | 同上；WhisperSeg 也已随默认值上调到 0.45 |

约束：

- 这些字段只影响展示与「是否生效」，**不改变 `normalize()` 的默认值**；
  `presets.json` 的默认快照仍是全后端通用的一套值。
- 后端判定取同一个引擎里 `*.vad_backend` 的当前值；缺这个键的引擎（中文两个）不显示限定。
- 新增「只对某后端生效」的参数时，必须同时在代码路径上真的门控它，并加一条测试；
  只改 UI 置灰、后端仍生效属于欺骗。
