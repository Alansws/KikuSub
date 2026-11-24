#!/usr/bin/env python3
"""稀疏参考字幕的评测：只在参考**覆盖到的区间**上比较 CER 与块准确率。

`score_srt.py` 是把参考当成「全片真值」来比的。这在参考字幕本身就不完整时会
失真：ASMR 类素材的人工参考常常只标了台词、把喘息与留白留空（实测一支 320s
片子的参考只覆盖 92.7s 语音 / 355 字），此时整片拼接会把参考窗口之外的合法
字幕全算成插入，CER 能到 160% 量级，数字失去意义。

这里换成「只比参考覆盖到的地方」：

- **覆盖区间** = 参考每条 ±`--pad` 的并集（默认 0.6s）；
- **CER** = 覆盖区间内「参考文本」与「候选文本」的字符级编辑距离 / 参考字符数；
- **块准确率** = 1 - 每条参考 cue 与其重叠候选文本的 CER，再取平均；
- **漏块** = 块准确率 < 35% 且参考 >= 3 字（与 `score_srt.py` 同门槛）；
- **劈词** = 候选相邻两条的边界落在某条参考 cue 内部（两侧各留 0.15s）；
- **短段幻觉** = 候选 < 1.6s、中心落在覆盖区间内、且与参考 CER > 0.6；
- **段内静音占比**（给了 `--media` 才算）= 全片能量 < -60dBFS 的时长
  （前后 200ms 缓冲）占字幕显示总时长的比例。

归一化口径（写死，不要各自动手改）：NFKC + 去中日标点与空白、**保留 `ー`**。
它与 `score_srt.py` 的 `normalize_text` 不是同一套——两套口径的数字**不可混用**，
所以本脚本的 JSON 带 `method` 字段标明来源。

用法：

    ../.venv/bin/python tools/eval/score_partial.py \\
        --reference ../测试/01_…_SEなし.reference.srt \\
        --hypothesis outputs/eval/xxx/01_….srt \\
        --media /tmp/asmr16k.wav \\
        --json outputs/eval/partial.json

不给 `--media` 时跳过「段内静音」，其余指标照算（不需要加载音频库）。
"""

from __future__ import annotations

import argparse
import json
import sys
import unicodedata
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.eval.score_srt import Cue, parse_srt  # noqa: E402

METHOD = "partial-reference-v1"
#: 参考每条的扩张量（秒），用来容忍人工打轴的误差。
DEFAULT_PAD_S = 0.6
#: 判断「候选这条属于哪个参考窗口」时，用中心点还是整体重叠，这里是中心点。
PICK_PAD_S = 0.4
#: 与 `score_srt.py` 一致的漏块门槛。
MISS_ACC = 0.35
MISS_MIN_CHARS = 3
#: 劈词判定：边界离参考 cue 两侧至少这么远才算真的劈开。
SPLIT_MARGIN_S = 0.15
#: 短段幻觉：候选短于这个时长且与参考差得离谱。
HALL_MAX_DUR_S = 1.6
HALL_CER = 0.6
#: 段内静音：低于该 dBFS 视为静音，前后各留 200ms 缓冲。
SILENCE_DBFS = -60.0
SILENCE_BUFFER_S = 0.2
SAMPLE_RATE = 16000

PUNCT = set(
    "、。！？!?…‥，,．.：:；;・「」『』（）()［］[]【】〈〉《》～〜"
    "\"“”‘’'`· 　\t\r\n"
)


def normalize(text: str) -> str:
    """NFKC + 去标点空白；**保留 ``ー``**（它可能是词的一部分）。"""
    text = unicodedata.normalize("NFKC", text or "")
    return "".join(ch for ch in text if ch not in PUNCT)


def _levenshtein(a: str, b: str) -> int:
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def cer(reference: str, hypothesis: str) -> float:
    """字符错误率；参考为空时，候选也空算 0，否则算 1。"""
    if not reference:
        return 0.0 if not hypothesis else 1.0
    return _levenshtein(reference, hypothesis) / len(reference)


def coverage_spans(refs: list[Cue], *, pad_s: float = DEFAULT_PAD_S) -> list[tuple[float, float]]:
    """参考每条 ±pad 的并集（已合并重叠）。"""
    if not refs:
        return []
    raw = sorted((max(0.0, c.start - pad_s), c.end + pad_s) for c in refs)
    merged = [list(raw[0])]
    for start, end in raw[1:]:
        if start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return [(a, b) for a, b in merged]


def in_spans(t: float, spans: list[tuple[float, float]]) -> bool:
    return any(a <= t <= b for a, b in spans)


def pick(cues: list[Cue], start: float, end: float) -> list[Cue]:
    """中心点落在 [start, end] 内的候选（两边各放宽 `PICK_PAD_S`）。"""
    out = []
    for cue in cues:
        center = (cue.start + cue.end) / 2.0
        if start - PICK_PAD_S <= center <= end + PICK_PAD_S:
            out.append(cue)
    return out


def score_partial(
    reference: list[Cue],
    hypothesis: list[Cue],
    *,
    pad_s: float = DEFAULT_PAD_S,
    silence: "object | None" = None,
) -> dict:
    """在参考覆盖到的区间上打分。``silence`` 是 ``(db_array, hop_s)`` 或 ``None``。"""
    spans = coverage_spans(reference, pad_s=pad_s)
    if not spans:
        return {
            "method": METHOD,
            "cer": 0.0,
            "block_acc": 0.0,
            "missed": [],
            "splits": 0,
            "hall": [],
            "cues": len(hypothesis),
            "dead_pct": 0.0,
            "dead": 0.0,
            "max_cue": 0.0,
            "over42": 0,
            "covered_s": 0.0,
            "reference_cues": 0,
        }

    ref_text = normalize("".join(c.text for c in reference))
    hyp_text = normalize(
        "".join(c.text for c in hypothesis if in_spans((c.start + c.end) / 2.0, spans))
    )
    overall = cer(ref_text, hyp_text)

    blocks: list[float] = []
    missed: list[float] = []
    for cue in reference:
        got = normalize("".join(c.text for c in pick(hypothesis, cue.start, cue.end)))
        acc = 1.0 - cer(normalize(cue.text), got)
        blocks.append(acc)
        if acc < MISS_ACC and len(normalize(cue.text)) >= MISS_MIN_CHARS:
            missed.append(round(cue.start, 2))

    # 劈词：候选相邻两条的边界落在某条参考 cue 内部（两侧各留 SPLIT_MARGIN_S）。
    splits = 0
    for prev, nxt in zip(hypothesis, hypothesis[1:]):
        boundary = prev.end
        for cue in reference:
            if cue.start + SPLIT_MARGIN_S < boundary < cue.end - SPLIT_MARGIN_S:
                splits += 1
                break

    # 短段幻觉：落在覆盖区间内的短候选，与参考差得离谱。
    hall: list[float] = []
    for cue in hypothesis:
        if cue.end - cue.start >= HALL_MAX_DUR_S:
            continue
        if not in_spans((cue.start + cue.end) / 2.0, spans):
            continue
        got = normalize("".join(c.text for c in pick(reference, cue.start, cue.end)))
        if got and cer(got, normalize(cue.text)) > HALL_CER:
            hall.append(round(cue.start, 2))

    # 段内静音（可选）：只有当调用方给了 DB 包络才算。
    dead = 0.0
    total = 0.0
    dead_pct = 0.0
    if silence is not None:
        import numpy as np

        db, hop_s = silence
        near = (
            np.convolve(
                (db > SILENCE_DBFS).astype(np.float32),
                np.ones(max(1, int(round((2 * SILENCE_BUFFER_S) / hop_s))), np.float32),
                "same",
            )
            > 0
        )
        for cue in hypothesis:
            lo = max(0, int(cue.start / hop_s))
            hi = min(len(near), int(cue.end / hop_s))
            total += cue.end - cue.start
            dead += float((~near[lo:hi]).sum()) * hop_s
        dead_pct = (dead / total * 100.0) if total else 0.0

    durations = [cue.end - cue.start for cue in hypothesis]
    return {
        "method": METHOD,
        "cer": round(overall, 6),
        "block_acc": round(sum(blocks) / len(blocks), 6) if blocks else 0.0,
        "missed": missed,
        "splits": splits,
        "hall": hall,
        "cues": len(hypothesis),
        "dead": round(dead, 3),
        "dead_pct": round(dead_pct, 2),
        "max_cue": round(max(durations), 3) if durations else 0.0,
        "over42": sum(1 for d in durations if d > 4.2),
        "covered_s": round(sum(b - a for a, b in spans), 2),
        "reference_cues": len(reference),
    }


def load_silence(media: Path) -> tuple["object", float]:
    """把音频算成 10ms 跳距的 dB 包络，供段内静音占比使用。"""
    import numpy as np
    import soundfile as sf

    data, sr = sf.read(str(media), dtype="float32", always_2d=False)
    if data.ndim > 1:
        data = data.mean(axis=1)
    if int(sr) != SAMPLE_RATE:
        raise SystemExit(f"采样率必须是 {SAMPLE_RATE}Hz（收到 {sr}Hz），先转成 16k 单声道")
    frame = 400  # 25ms
    hop = 160  # 10ms
    db = 20 * np.log10(
        np.maximum(
            np.sqrt((np.lib.stride_tricks.sliding_window_view(data, frame)[::hop] ** 2).mean(axis=1)),
            1e-8,
        )
    )
    return db, hop / SAMPLE_RATE


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="稀疏参考字幕评测：只在参考覆盖到的区间上比较（与 score_srt 口径不同）"
    )
    parser.add_argument("--reference", required=True, help="参考 SRT（可以是不完整的）")
    parser.add_argument("--hypothesis", required=True, help="待评测的 SRT")
    parser.add_argument("--media", default=None, help="16k 单声道 wav；给了才算段内静音")
    parser.add_argument("--pad", type=float, default=DEFAULT_PAD_S, help="参考扩张量（秒），默认 0.6")
    parser.add_argument("--json", type=Path, default=None, help="把结果写入 JSON")
    args = parser.parse_args(argv)

    ref_path, hyp_path = Path(args.reference).expanduser(), Path(args.hypothesis).expanduser()
    for path, label in ((ref_path, "参考"), (hyp_path, "候选")):
        if not path.is_file():
            print(f"错误：{label}不存在：{path}", file=sys.stderr)
            return 2

    reference = parse_srt(ref_path.read_text(encoding="utf-8-sig"))
    hypothesis = parse_srt(hyp_path.read_text(encoding="utf-8-sig"))
    silence = None
    if args.media:
        media = Path(args.media).expanduser()
        if not media.is_file():
            print(f"错误：素材不存在：{media}", file=sys.stderr)
            return 2
        silence = load_silence(media)

    result = score_partial(reference, hypothesis, pad_s=args.pad, silence=silence)
    result.update({"reference": str(ref_path), "hypothesis": str(hyp_path)})

    print(f"参考：{ref_path.name}（{len(reference)} 条，覆盖 {result['covered_s']}s）")
    print(f"候选：{hyp_path.name}（{result['cues']} 条）")
    print(f"口径：{METHOD}（pad={args.pad:g}s；与 score_srt 的数字不可混用）")
    print()
    print(f"CER（覆盖区间内）   = {result['cer'] * 100:.2f}%")
    print(f"块均准确率          = {result['block_acc'] * 100:.1f}%")
    print(f"漏块(acc<35%, >=3字) = {len(result['missed'])}")
    print(f"劈词 / 短段幻觉      = {result['splits']} / {len(result['hall'])}")
    print(f"最长条 / >4.2s       = {result['max_cue']:.2f}s / {result['over42']}")
    if silence is not None:
        print(f"段内静音占比         = {result['dead_pct']:.1f}%（{result['dead']:.2f}s）")
    else:
        print("段内静音占比         = 未计算（没给 --media）")

    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n已写入 {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
