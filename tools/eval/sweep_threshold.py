"""E1 全局阈值扫描：只改 `threshold`，其余参数全部锁定基线。

纪律
----
一次只改一个变量。本脚本**不动** min_speech / min_silence / speech_pad / merge_gap /
max_segment / 分句参数，也不动任何代码路径——只在 `build_whisper_config` 里换阈值。
（方案文档 §3.2 那张表是「阈值 + 最小语音 + 停顿 + pad」同时变的混合扫描，只能用于
估算召回上限，不能当作单变量 A/B 的结论。）

用法
----
    python tools/eval/sweep_threshold.py                    # 默认 0.45 / 0.35 / 0.30 / 0.25
    python tools/eval/sweep_threshold.py --thresholds 0.30  # 只跑一档
    # 非阈值参数的单变量实验（如 D3 合并间隔）：用 --override 覆盖一项，其余锁定
    python tools/eval/sweep_threshold.py --thresholds 0.30 --override merge_gap_s=0.15

产物
----
    outputs/eval/sweep/th_<阈值>.srt    每次全片产物
    outputs/eval/sweep/results.json     逐档 scorecard（每档跑完立刻落盘）
    outputs/eval/sweep/summary.md       汇总表（含与基线的差值）

硬约束（方案 §7）：插入字数 ≤90、禁切接缝 0、耗时 ≤280s。
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = str(Path(__file__).resolve().parents[2])
sys.path.insert(0, ROOT)
sys.path.insert(0, str(Path(__file__).resolve().parent))

import soundfile as sf  # noqa: E402

import transcribe as T  # noqa: E402
import scorecard as SC  # noqa: E402

SR = 16000
WAV = f"{ROOT}/outputs/eval/full16k.wav"
REF = f"{ROOT}/测试用_言叶之庭_中日双语.srt"
BASELINE_SRT = f"{ROOT}/tools/eval/baseline_474.srt"

# 基线参数（与 exp_full.py / 交付版一致），扫描时只覆盖 threshold
BASE_PARAMS = dict(
    min_speech_ms=120,
    min_silence_ms=150,
    speech_pad_ms=200,
    merge_gap_s=0.3,
    max_segment_s=12.0,
    min_speech_s=0.08,
    cue_pad_s=0.02,
    enable_sentence_split=True,
    enable_loudnorm=False,
)


def main() -> None:
    ap = argparse.ArgumentParser(description="E1 全局 VAD 阈值扫描（单变量）")
    ap.add_argument("--thresholds", default="0.45,0.35,0.30,0.25")
    ap.add_argument("--out", default=f"{ROOT}/outputs/eval/sweep")
    ap.add_argument("--wav", default=WAV, help="16k 单声道 wav（默认全片）")
    ap.add_argument("--override", action="append", default=[], metavar="KEY=VALUE",
                    help="在锁定参数上覆盖一项（用于 D3 这类非阈值单变量实验），可重复")
    args = ap.parse_args()

    thresholds = [float(x) for x in args.thresholds.split(",") if x.strip()]
    params = dict(BASE_PARAMS)
    overrides: dict = {}
    for item in args.override:
        key, _, raw = item.partition("=")
        key = key.strip()
        if key not in params:
            ap.error(f"未知参数 {key}；可选：{', '.join(sorted(params))}")
        cur = params[key]
        if isinstance(cur, bool):
            val = raw.strip().lower() in ("1", "true", "yes", "on")
        elif isinstance(cur, int):
            val = int(raw)
        else:
            val = float(raw)
        params[key] = val
        overrides[key] = val
    tag = "".join(f"_{k}{v}" for k, v in overrides.items())

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"读取 16k 音频 {args.wav} …", flush=True)
    audio, sr = sf.read(args.wav, dtype="float32")
    assert sr == SR, sr
    print(f"音频 {len(audio)/SR:.1f}s，参考块 {len(SC.load_reference(REF))} 个"
          + (f"；覆盖参数 {overrides}" if overrides else ""), flush=True)

    cfg0 = T.build_whisper_config(threshold=thresholds[0], **params)
    print("加载 Anime Whisper …", flush=True)
    t_load = time.time()
    eng = T.AnimeWhisperEngine(cfg0)
    eng.load()
    print(f"模型就绪 {time.time()-t_load:.1f}s，开始 {len(thresholds)} 档全片转写", flush=True)

    ref_blocks = SC.load_reference(REF)
    results: list[dict] = []
    for th in thresholds:
        cfg = T.build_whisper_config(threshold=th, **params)
        print(f"\n=== threshold={th:.2f}{tag} 开始 ===", flush=True)
        t0 = time.time()
        cues = eng._transcribe_array(
            audio, config=cfg, no_repeat_ngram_size=5, repetition_penalty=1.15,
        )
        secs = time.time() - t0

        srt_path = out_dir / f"th_{th:.2f}{tag}.srt"
        srt_path.write_text(T.cues_to_srt(cues), encoding="utf-8")

        stats = dict(eng.last_segment_stats or {})
        spans, vad_stats = SC.vad_spans(
            audio, th,
            max_segment_s=params["max_segment_s"],
            merge_gap_s=params["merge_gap_s"],
            min_speech_s=params["min_speech_s"],
        )
        row = SC.score(
            [{"start": c.start, "end": c.end, "text": c.text} for c in cues],
            ref_blocks,
            label=f"th={th:.2f}{tag}",
            spans=spans,
            secs=secs,
            forced=stats.get("forced_cuts"),
        )
        row.update({
            "threshold": th,
            "srt": str(srt_path),
            "missed_spans": len(eng.last_missed_spans),
            "vad_stamps": vad_stats.get("stamps"),
            "vad_speech_s": vad_stats.get("speech_s"),
            "vad_blocks": stats.get("blocks"),
            "vad_snapped": stats.get("snapped_cuts"),
        })

        results.append(row)
        (out_dir / "results.json").write_text(
            json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")

        print(f"--- th={th:.2f} 完成 {secs:.1f}s：{row['cues']} 条  "
              f"CER {row['cer']*100:.2f}%（去歌 {row['cer_no_song']*100:.2f}%）"
              f"块均 {row['acc']*100:.1f}%  漏块 {row['miss']}  插入 {row['ins']} 字  "
              f"VAD 不达标 {row['vad_bad']}/{row['vad_bad_chars']}字  "
              f"强制切分 {row['forced']}", flush=True)

    # ---- 汇总 ----
    base = next((r for r in results if abs(r["threshold"] - 0.45) < 1e-9), results[0])
    lines = [
        "# 单变量扫描（只改 threshold" + ("，外加 " + str(overrides) if overrides else "") + "）",
        "",
        f"- 音频：`{args.wav}`（{len(audio)/SR:.1f}s）",
        "- 锁定参数：" + "，".join(f"{k}={v}" for k, v in params.items()),
        "- 基线参照：`tools/eval/baseline_474.srt`（CER 25.08%，插入 69）",
        "",
        "| 阈值 | 条数 | 全片 CER | 去歌 CER | 块均 | 漏块 | 插入字数 | VAD 不达标块/字 | 强制切分 | 最长条 | >4.3s | 耗时 |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in results:
        lines.append(
            f"| {r['threshold']:.2f} | {r['cues']} | {r['cer']*100:.2f}% | "
            f"{r['cer_no_song']*100:.2f}% | {r['acc']*100:.1f}% | {r['miss']} | "
            f"{r['ins']} | {r['vad_bad']} / {r['vad_bad_chars']} | {r['forced']} | "
            f"{r['max_cue_s']}s | {r['over_4.3s']} | {r['secs']:.0f}s |"
        )
    lines += [
        "",
        "## 相对 0.45 的变化",
        "",
        "| 阈值 | ΔCER | Δ去歌 CER | Δ插入 | Δ漏块 | ΔVAD 不达标 | 门禁（CER≥1.5pt 且 插入≤85 且 强切≤3） |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in results:
        d_cer = (base["cer"] - r["cer"]) * 100
        d_no_song = (base["cer_no_song"] - r["cer_no_song"]) * 100
        ok = (d_cer >= 1.5) and (r["ins"] <= 85) and ((r["forced"] or 0) <= 3)
        lines.append(
            f"| {r['threshold']:.2f} | {d_cer:+.2f}pt | {d_no_song:+.2f}pt | "
            f"{r['ins']-base['ins']:+d} | {r['miss']-base['miss']:+d} | "
            f"{r['vad_bad']-base['vad_bad']:+d} | {'✅ 通过' if ok else '—'} |"
        )
    (out_dir / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n" + "\n".join(lines), flush=True)
    print(f"\n→ {out_dir}/summary.md  {out_dir}/results.json", flush=True)


if __name__ == "__main__":
    main()
