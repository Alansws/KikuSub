# 评测台（SRT 打分 / 跑片 scorecard / 逐窗探针）

> ⚠ **用哪个解释器决定了你拿到哪组数字。** 本机 `python`（anaconda：torch 2.14.1 /
> silero-vad 5.1.2）与仓库 `.venv`（torch 2.15.0 / silero-vad 6.2.3）跑同一组参数，
> Test 一 qwen 的 CER 是 10.86% vs 12.97%，Test 二是 16.05% vs 13.42%。
> **一律用 `../.venv/bin/python`**；不在 `.venv` 里跑时 `run_clip.py` / `probe_window.py`
> 会先打一行警告，卡片里的 `env` 与基线比对里的 `env_differ` 也会暴露这件事。

三件东西，用途不同：

| 文件 | 干什么 | 会加载模型吗 |
| --- | --- | --- |
| `score_srt.py` | 两份 SRT 打分：CER、块均准确率、漏块、可疑切分 | 否（只依赖标准库） |
| `run_clip.py` | 跑「一个引擎 × 一支片 × 一组参数」，出一条 scorecard | 是（whisper / qwen） |
| `ab_onset.py` | 跑 P0-1 的 A0–A3 矩阵（起点提前 × 能量闸门），拼成一张对比表 | 是（whisper / qwen） |
| `qwen_confidence_diag.py` | P0-3a：置信度特征 × 对/错句标签，打印每个特征的 AUC | 是（qwen） |
| `probe_window.py` | 参考 SRT 的每条时间窗**绕开 VAD** 直送模型，分离「识别」与「分段」 | 是（qwen） |
| `scorecard.py` | 公共件：卡片形状、句首缺字判定、基线比对、fixtures 解析 | 否 |

## score_srt.py：两份 SRT 打分

```bash
# 全片
python tools/eval/score_srt.py \
    --reference path/to/reference.srt \
    --hypothesis outputs/result.srt

# 只看 00:00:30 – 00:05:30
python tools/eval/score_srt.py \
    --reference path/to/reference.srt \
    --hypothesis outputs/result.srt \
    --from 00:00:30 --to 00:05:30 \
    --json /tmp/score.json
```

| 参数 | 说明 |
| --- | --- |
| `--reference` | 参考 SRT；中日双语文件会自动只取含假名的日文行（`--ref-lang ja`） |
| `--hypothesis` | 待评测的 SRT |
| `--from` / `--to` | 评测区间，支持 `HH:MM:SS` 或纯秒数；按时间重叠筛选 |
| `--ref-lang` | `ja`（默认）/ `zh` / `all` |
| `--hyp-lang` | `all`（默认）/ `ja` / `zh` |
| `--json` | 额外写出机器可读结果 |

## run_clip.py：跑一次，出一条 scorecard

```bash
# 素材与参考字幕不在仓库里：--fixtures 指向它们所在的目录
python tools/eval/run_clip.py \
    --engine qwen --media Jap_test.mp4 --ref Jap_test_perfect.srt \
    --fixtures /path/to/fixtures --json /tmp/qwen.json

# 只跑 0–300s，并临时覆写一个参数（可重复 --set）
python tools/eval/run_clip.py --engine whisper \
    --media Jap_test.mp4 --ref Jap_test_perfect.srt --fixtures /path/to/fixtures \
    --from 0 --to 300 --set whisper.vad_threshold=0.25

# 与基线比；回归时退出码 1（手动闸门用）
python tools/eval/run_clip.py --engine qwen --media Jap_test.mp4 \
    --ref Jap_test_perfect.srt --fixtures /path/to/fixtures \
    --baseline tools/eval/baseline.json

# 只核对素材指纹，不跑模型
python tools/eval/run_clip.py --engine qwen --media Jap_test.mp4 \
    --ref Jap_test_perfect.srt --fixtures /path/to/fixtures \
    --baseline tools/eval/baseline.json --check-fixtures
```

几个约定：

- 只覆盖 **whisper / qwen**。sherpa 两个中文引擎的权重按需下载，评测走应用内，免得评测台
  顺手触发几 GB 下载。
- `--set` 的键必须属于该引擎（`core.params` 的键），**写错直接报错**，不会静默忽略。
- 字幕落在 `--out`（默认 `outputs/eval/`），音频缓存复用 `outputs/.cache/audio/`，
  同一支片的第二组参数不用重新解码。
- 卡片里的 `params` 存**该引擎的完整取值**（含默认值）：只存覆写的话，代码里的默认值改了
  也发现不了。比对时参数不同会报 `params_differ`，提示这组数字不可比。

## ab_onset.py：句首补回的 A/B 矩阵

```bash
# Test 二、两个引擎、默认五组（a0 基线 / a1 400ms / a2 400ms+信噪比 / a2b 400ms+上限 / a3 600ms）
python tools/eval/ab_onset.py --engines qwen,whisper \
    --media Jap_test_2.mp4 --ref Jap_test_2_perfect.srt --fixtures . \
    --json /tmp/ab.json --markdown /tmp/ab.md
```

组定义在 `ab_onset.GROUPS`，与路线文档 P0-1 的矩阵一一对应；每组只是「`vad_onset_pad_ms`」
加一个 A/B 专用的 `onset_gate`（`none` / `snr` / `snr_cap`，**不进参数面板**）。
跑片逻辑复用 `run_clip.run_one`，所以表里的数字与单跑完全同源。

除 CER / 插入 / 句首缺字，表里多一列「重复句」：相邻两条归一化后文本完全相同的次数。
它是「吃进上一句尾音」的代理指标——重复句会先于 CER 变化，用来兜住「CER 没涨但字幕不对」。

## qwen_confidence_diag.py：置信度特征诊断（P0-3a）

```bash
python tools/eval/qwen_confidence_diag.py --media Jap_test.mp4 --ref Jap_test_perfect.srt     --json /tmp/conf.json
```

跑一遍 qwen（产品默认参数），把每条字幕的特征与「对句 / 错句」标签配起来，打印每个特征的
ROC AUC 与「误报率 ≤5% 时的阈值 / 召回 / 精度」。标签口径：与参考条比块准确率 = 1.0 算对句、
≤0.66 算错句，中间带与没有参考覆盖的条目不参与（前者是编辑距离灰区，后者是多余句）。

特征：`mean_logprob` / `min_char_logprob` / `min_pair_logprob`（CTC 后验按字聚合）、
`interp_ratio`（插值字数占比）、`cps`、句首 40 ms 的 `onset_db` / `onset_zcr`。
**文档的准入门槛是 AUC ≥ 0.75**，所以这张表直接决定「要不要进 audit」。

## probe_window.py：绕开 VAD 的逐窗探针

```bash
python tools/eval/probe_window.py --media Jap_test.mp4 \
    --ref Jap_test_perfect.srt --pad 0.25 --fixtures /path/to/fixtures
```

它回答的是「给模型这段音频，它能不能听出来」，所以「模型听对了、产品字幕却缺了句首」
会被判成前端（VAD/分段）问题。`--pad` 是时间窗左右各扩多少秒（路线文档 §2.1 用 0.25）；
`--no-loudnorm` 只用于诊断「动态归一化压扁轻声起音」，不是产品口径。

只支持 qwen：它的模型级入口 `_transcribe(chunk)` 就是引擎解码本身，没有第二份生成参数。
Whisper 的模型级调用在 `transcribe.py::_decode` 闭包里，硬拷一份 `generate_kwargs` 等于
再造第二份真相；Whisper 侧看「句首缺字」，用 `run_clip.py` 的 scorecard 指标复核。

## 素材（fixtures）与基线

参考字幕与音视频**都不提交**（体积 + 版权）。仓库里只有 `baseline.json` 的数字和指纹：

```jsonc
"fixtures": {
  "references": { "Jap_test_perfect.srt": { "sha1": "…", "cues": 76, "chars": 663 } },
  "media":      { "Jap_test.mp4":       { "bytes": 2091458850, "duration_s": 830.229 } }
}
```

`--check-fixtures` 会按这份指纹核对；素材换了（或拿错文件）时提前报错，而不是跑完 2 分钟
才发现基线不可比。素材目录优先级：`--fixtures` > `KIKUSUB_EVAL_FIXTURES` > 仓库上一级。

`baseline.json` 是 2026-11-13 第一遍实测（内置默认参数）的四条记录，`id` 为
`test1.whisper` / `test1.qwen` / `test2.whisper` / `test2.qwen`，出处见
[docs/日语引擎优化路线-2026-11.md](../../docs/日语引擎优化路线-2026-11.md) §1。
四组都用 `.venv/bin/python` + `run_clip.py` 复采过，CER 与条数与 §1 逐项一致
（12.97 / 13.42 / 9.80 / 15.48），所以它既是对照，也是「工具没有偷偷改管线」的证据。
每条记录带 `env`（python / torch / transformers / silero-vad / numpy）：换了环境，
比对会报 `env_differ`，结论不可比，得重采。耗时与 RSS/MPS 都是实采值；
§1 表的「峰值内存」是 RSS+MPS，这里两个数分开存。

## 指标口径

- **CER**：归一化（NFKC、去空白、去标点）后的字符级编辑距离 / 参考字符数；
- **S/D/I**：近似替换/删除/插入拆分（用于观察错误类型，不保证与最小编辑距离完全一致）；
- **块均准确率**：每条参考字幕与其时间重叠的候选文本计算 `1 - CER`，再取平均；
- **漏块**：块准确率 < 35% 且参考文本 ≥ 3 字的条数；
- **可疑切分**：相邻候选字幕（间隙 ≤ 0.05s）中，下一条以助词开头 / 以活用尾开头的次数；
- **句首缺字**：第一条重叠候选的起点比参考晚 > 0.4s **且**把覆盖这条参考的所有候选
  拼起来之后首字不同（完全没盖住参考的不算，那是漏块）。**拼接**这一步是必须的：
  人工版一句被拆成两条候选时，「只看重叠最多的那条」会把上一屏明明有的字误报成缺字。

> 参考字幕若含制作组信息、主题歌歌词，建议用 `--from/--to` 避开，或先手工整理参考文件。
> 版权素材（参考字幕、音频）不要提交到仓库；本目录只提交脚本与数字基线。

## 作为回归门槛

建议在改 `qwen_ctc._break_costs`、`partition_cues`、VAD 参数前后各跑一次同一区间，至少同时看：

1. CER 不上升（允许噪声带内浮动；单次转写的噪声就有 0.5pt 级，所以 `--tolerance-pt` 默认 0.5）；
2. `particle_start_cues` / `aux_start_cues` 下降；
3. `max_cue_dur` / `over_4_3s` 不恶化；
4. 句首缺字条数不上升。

只看 CER 会漏掉“切在词中间”这类产品可读性问题；只看劈词指标又可能把字幕切得过碎。两个一起看。
