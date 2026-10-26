"""客观 scorecard：把一份产物 SRT 折算成一行可比指标（不跑模型）。

口径与 `docs/优化效果实测报告-第一批与第二批.md` 完全一致：

- 参考：`测试用_言叶之庭_中日双语.srt` → 482 块 / 5315 字，覆盖 00:38–45:36；
- 全片 CER = (S + D + I) / 参考字数；
- 去歌 CER：只统计 42:00（2514s）之前的参考块与产物——42:00 之后是主题歌歌词，
  会把全片 CER 整体带偏；
- 块均准确率：482 个参考块的逐块命中率均值；
- 漏块：acc < 35% 且 ≥3 字；
- 插入字数：全局对齐的 ins（幻觉量，**硬约束 ≤90**）；
- VAD 不达标块（`--vad`）：参考块时长内被 VAD 合并段覆盖 ≥0.3s **且** ≥块时长 25% 才算达标。

用法
----
    python tools/eval/scorecard.py tools/eval/baseline_474.srt
    python tools/eval/scorecard.py outputs/eval/sweep/th_0.30.srt --vad 0.30 --secs 208 --json out.json

stdout 末尾固定输出一行 TSV（字段顺序见 HEADER），便于脚本汇总。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = str(Path(__file__).resolve().parents[2])
sys.path.insert(0, ROOT)
sys.path.insert(0, str(Path(__file__).resolve().parent))

from eval_lib import evaluate, load_reference, normalize, parse_srt  # noqa: E402

SR = 16000
SONG_T0 = 2514.0  # 主题歌《Rain》起点
WAV = f"{ROOT}/outputs/eval/full16k.wav"
REF = f"{ROOT}/测试用_言叶之庭_中日双语.srt"
BASELINE = f"{ROOT}/tools/eval/baseline_474.srt"

# 参考字幕自检口径（与 docs/优化效果实测报告 一致）
REF_BLOCKS = 482
REF_CHARS = 5315
BASELINE_CER = 0.2508

HEADER = ["label", "cues", "cer", "cer_no_song", "acc", "miss", "ins", "del", "sub",
          "vad_bad", "vad_bad_chars", "forced", "max_cue_s", "over_4.3s", "cps_max", "secs"]


def _ov(a0: float, a1: float, b0: float, b1: float) -> float:
    return max(0.0, min(a1, b1) - max(a0, b0))


def cues_in(cues: list[dict], t0: float, t1: float) -> list[dict]:
    return [c for c in cues if _ov(c["start"], c["end"], t0, t1) > 0]


def vad_spans(audio, threshold: float, *, max_segment_s: float = 12.0,
              merge_gap_s: float = 0.3, min_speech_s: float = 0.08,
              min_speech_ms: int = 120, min_silence_ms: int = 150,
              speech_pad_ms: int = 200) -> tuple[list[tuple[float, float]], dict]:
    """按给定阈值重算 VAD 合并段（不跑 ASR），用于「不达标块」统计。"""
    import torch

    import transcribe as T

    vad = T.load_silero_vad()
    stamps = T.get_speech_timestamps(
        torch.from_numpy(audio), vad, sampling_rate=SR,
        threshold=float(threshold),
        min_speech_duration_ms=int(min_speech_ms),
        min_silence_duration_ms=int(min_silence_ms),
        speech_pad_ms=int(speech_pad_ms),
        neg_threshold=T.vad_neg_threshold(threshold),
    )
    stats: dict = {}
    segs = T.merge_vad_segments(
        stamps, max_segment_s=max_segment_s, merge_gap_s=merge_gap_s,
        min_speech_s=min_speech_s, audio=audio, snap_stats=stats,
    )
    stats["stamps"] = len(stamps)
    stats["speech_s"] = round(sum(s["end"] - s["start"] for s in stamps) / SR, 1)
    return [(s / SR, e / SR) for s, e in segs], stats


def vad_bad_blocks(ref_blocks: list[dict], spans: list[tuple[float, float]]) -> tuple[int, int]:
    """返回（不达标块数, 不达标字数）。"""
    bad = chars = 0
    for b in ref_blocks:
        dur = b["end"] - b["start"]
        cov = sum(_ov(b["start"], b["end"], s, e) for s, e in spans)
        cov = min(cov, dur)
        if not (cov >= 0.3 and cov >= 0.25 * dur):
            bad += 1
            chars += len(b["text"])
    return bad, chars


def score(hyp: list[dict], ref_blocks: list[dict], *, label: str = "",
          spans: list[tuple[float, float]] | None = None, secs: float | None = None,
          forced: int | None = None) -> dict:
    full = evaluate(ref_blocks, hyp)
    no_song_ref = [b for b in ref_blocks if b["start"] < SONG_T0]
    no_song = evaluate(no_song_ref, cues_in(hyp, 0.0, SONG_T0))

    cps = full["cps"]
    durs = [c["end"] - c["start"] for c in hyp]
    row = {
        "label": label,
        "cues": len(hyp),
        "cer": round(full["cer"], 4),
        "cer_no_song": round(no_song["cer"], 4),
        "acc": round(full["acc_mean"], 4),
        "miss": len(full["miss_blocks"]),
        "ins": full["ins"],
        "del": full["del"],
        "sub": full["sub"],
        "n_ref_chars": full["n_ref_chars"],
        "max_cue_s": round(max(durs), 2) if durs else 0.0,
        "over_4.3s": sum(1 for d in durs if d > 4.3),
        "cps_max": round(cps.get("cps_max", 0.0), 2),
        "cps_median": round(cps.get("cps_median", 0.0), 2),
        "boundary_start_median": full["boundary"].get("start_median"),
        "boundary_start_p90": full["boundary"].get("start_p90"),
        "secs": round(secs, 1) if secs is not None else None,
        "forced": forced,
    }
    if spans is not None:
        bad, bad_chars = vad_bad_blocks(ref_blocks, spans)
        row["vad_bad"] = bad
        row["vad_bad_chars"] = bad_chars
    return row


def tsv_row(row: dict) -> str:
    return "\t".join("" if row.get(k) is None else str(row.get(k)) for k in HEADER)


def selftest() -> int:
    """评测台自检：参考字幕口径 + 基线产物指标是否与文档一致。

    参考字幕与 16k 音频因版权不入库（见 `.gitignore` 的「本地测试素材」段），
    换机器时先确认这两份素材存在，再跑本自检确认口径没漂。
    """
    fails = []

    def check(ok: bool, msg: str) -> None:
        print(f"{'✅' if ok else '❌'} {msg}")
        if not ok:
            fails.append(msg)

    if not Path(REF).exists():
        print(f"❌ 缺少参考字幕：{REF}（版权素材，不入库）")
        return 1
    ref = load_reference(REF)
    n_chars = sum(len(normalize(b["text"])) for b in ref)
    check(len(ref) == REF_BLOCKS, f"参考块 {len(ref)} == {REF_BLOCKS}")
    check(n_chars == REF_CHARS, f"参考字数 {n_chars} == {REF_CHARS}")

    if Path(BASELINE).exists():
        row = score(parse_srt(BASELINE), ref, label="baseline_474")
        check(abs(row["cer"] - BASELINE_CER) < 5e-4,
              f"基线全片 CER {row['cer']*100:.2f}% == {BASELINE_CER*100:.2f}%")
        check(row["cues"] == 474, f"基线条数 {row['cues']} == 474")
        check(row["ins"] == 69, f"基线插入字数 {row['ins']} == 69")
        check(row["miss"] == 92, f"基线漏块 {row['miss']} == 92")
    else:
        print(f"⚠️ 跳过基线比对：{BASELINE} 不存在")

    print("自检通过" if not fails else f"自检失败 {len(fails)} 项")
    return 0 if not fails else 1


def main() -> None:
    ap = argparse.ArgumentParser(description="产物 SRT → scorecard 一行指标")
    ap.add_argument("hyp", nargs="?", help="待评测的 SRT 路径")
    ap.add_argument("--selftest", action="store_true",
                    help="校验参考字幕口径与基线产物指标（不跑模型）")
    ap.add_argument("--label", default=None, help="行标签（默认取文件名）")
    ap.add_argument("--json", default=None, help="把结果写入该 JSON 文件")
    ap.add_argument("--vad", type=float, default=None,
                    help="额外统计 VAD 不达标块，需给出阈值（如 0.45）")
    ap.add_argument("--secs", type=float, default=None, help="转写耗时（秒），仅记录")
    ap.add_argument("--forced", type=int, default=None, help="强制切分次数，仅记录")
    args = ap.parse_args()

    if args.selftest:
        raise SystemExit(selftest())
    if not args.hyp:
        ap.error("需要给出待评测的 SRT 路径（或用 --selftest）")

    hyp_path = Path(args.hyp)
    ref_blocks = load_reference(REF)
    hyp = parse_srt(str(hyp_path))
    label = args.label or hyp_path.stem

    spans = None
    if args.vad is not None:
        import soundfile as sf

        audio, sr = sf.read(WAV, dtype="float32")
        assert sr == SR
        spans, _ = vad_spans(audio, args.vad)

    row = score(hyp, ref_blocks, label=label, spans=spans,
                secs=args.secs, forced=args.forced)

    print(f"{label}: {row['cues']} 条  全片 CER {row['cer']*100:.2f}%  "
          f"去歌 {row['cer_no_song']*100:.2f}%  块均 {row['acc']*100:.1f}%  "
          f"漏块 {row['miss']}  插入 {row['ins']} 字  "
          f"S{row['sub']}/D{row['del']}/I{row['ins']}  "
          f"最长条 {row['max_cue_s']}s（>4.3s {row['over_4.3s']} 条）")
    if "vad_bad" in row:
        print(f"  VAD 不达标块 {row['vad_bad']} / {row['vad_bad_chars']} 字")
    print("\t".join(HEADER))
    print(tsv_row(row))

    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(
            json.dumps(row, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"→ {args.json}")


if __name__ == "__main__":
    main()
