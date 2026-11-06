# 评测台（SRT CER / 块准确率）

一个只依赖 Python 标准库的字幕评测脚本，用来在改动 VAD/ASR/断句参数前后做可比较的回归。

它**不加载模型**，所以可以在一台只装了 Python 的机器上复跑；它也不解析视频，只比较两份 SRT。

## 用法

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

参数：

| 参数 | 说明 |
| --- | --- |
| `--reference` | 参考 SRT；中日双语文件会自动只取含假名的日文行（`--ref-lang ja`） |
| `--hypothesis` | 待评测的 SRT |
| `--from` / `--to` | 评测区间，支持 `HH:MM:SS` 或纯秒数；按时间重叠筛选 |
| `--ref-lang` | `ja`（默认）/ `zh` / `all` |
| `--hyp-lang` | `all`（默认）/ `ja` / `zh` |
| `--json` | 额外写出机器可读结果 |

## 指标口径

- **CER**：归一化（NFKC、去空白、去标点）后的字符级编辑距离 / 参考字符数；
- **S/D/I**：近似替换/删除/插入拆分（用于观察错误类型，不保证与最小编辑距离完全一致）；
- **块均准确率**：每条参考字幕与其时间重叠的候选文本计算 `1 - CER`，再取平均；
- **漏块**：块准确率 < 35% 且参考文本 ≥ 3 字的条数；
- **可疑切分**：相邻候选字幕（间隙 ≤ 0.05s）中，下一条以助词开头 / 以活用尾开头的次数。

> 参考字幕若含制作组信息、主题歌歌词，建议用 `--from/--to` 避开，或先手工整理参考文件。
> 版权素材（参考字幕、音频）不要提交到仓库；本目录只提交脚本。

## 作为回归门槛

建议在改 `qwen_ctc._break_costs`、`partition_cues`、VAD 参数前后各跑一次同一区间，至少同时看：

1. CER 不上升（允许噪声带内浮动）；
2. `particle_start_cues` / `aux_start_cues` 下降；
3. `max_cue_dur` / `over_4_3s` 不恶化。

只看 CER 会漏掉“切在词中间”这类产品可读性问题；只看劈词指标又可能把字幕切得过碎。两个一起看。
