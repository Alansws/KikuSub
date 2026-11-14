#!/usr/bin/env python3
"""Qwen 置信度特征诊断（路线文档 P0-3a：只诊断，不写 audit）。

    python tools/eval/qwen_confidence_diag.py --media Jap_test.mp4 \
        --ref Jap_test_perfect.srt --fixtures . --json /tmp/conf_t1.json

做法：跑一遍 qwen（产品默认参数），把每条字幕的特征与「对句 / 错句」标签配起来，
打印每个特征的 ROC AUC 与「误报率 ≤5% 时的阈值 / 召回 / 精度」。

标签口径（可复核，不靠猜）：

- **错句**：与时间重叠的参考文本比，块准确率 ≤ 0.66（即至少 1/3 的字不对）；
- **对句**：块准确率 = 1.0；
- 中间带（0.66–1.0）与「没有参考覆盖」的条目不参与统计——前者是编辑距离的灰区，
  后者是多余句/幻觉，不属于「这条文本准不准」的问题。

特征（数字越大越可疑；logprob 类的方向在表里会标出来）：

| 特征 | 来源 | 抓什么 |
| --- | --- | --- |
| `mean_logprob` | CTC 逐帧后验按字聚合 | 整句声学置信（会被段均值稀释） |
| `min_char_logprob` | 同上，取最差字 | 局部 1–2 字错 |
| `min_pair_logprob` | 连续两字均值下限 | 局部错字（比单字稳） |
| `interp_ratio` | 插值字数 / 总字数 | 对齐没对上（时间靠猜） |
| `cps` | 字数 / 秒 | 合并两句、语速异常 |
| `onset_db` | 句首 40 ms 的 RMS（dBFS） | 句首截断 |
| `onset_zcr` | 句首 40 ms 过零率 | 清辅音起音 |

**文档要求 AUC < 0.75 的特征不上线**，所以这张表同时是 P0-3b 的准入证据。
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import numpy as np  # noqa: E402

from tools.eval.run_clip import _transcribe  # noqa: E402
from tools.eval.score_srt import (  # noqa: E402
    filter_language,
    levenshtein,
    normalize_text,
    parse_srt,
    parse_time_token,
)
from tools.eval.scorecard import (  # noqa: E402
    DEFAULT_FIXTURES_DIR,
    auc,
    interpreter_warning,
    resolve_fixture_path,
    resolve_fixtures,
    threshold_at_fpr,
)

# 方向：True = 特征越小越可疑（logprob 类），统计前取负归一。
FEATURES = {
    "mean_logprob": True,
    "min_char_logprob": True,
    "min_pair_logprob": True,
    "interp_ratio": False,
    "cps": False,
    "onset_db": False,
    "onset_zcr": False,
}
ONSET_WINDOW_S = 0.04
SILENCE_DB = -100.0


def _onset_stats(audio: np.ndarray, start: float, sr: int = 16000) -> tuple[float, float]:
    lo = max(0, int(round(start * sr)))
    hi = min(audio.size, lo + int(ONSET_WINDOW_S * sr))
    if hi - lo < 16:
        return SILENCE_DB, 0.0
    window = audio[lo:hi]
    rms = float(np.sqrt(np.mean(np.square(window))))
    db = 20 * math.log10(rms) if rms > 1e-10 else SILENCE_DB
    zero_cross = float(np.mean(np.abs(np.diff(np.signbit(window).astype(np.int8)))))
    return db, zero_cross


def _label_by_reference(references, cues) -> list[dict]:
    """按「参考条 → 覆盖它的候选文本」算块准确率，再回填到候选条上。

    口径与 `score_srt` 的块准确率一致：一条参考 = 它时间重叠的所有候选拼起来。
    反过来拿「候选条 ↔ 重叠参考」比会把「参考一句被切成两条」的正确候选判成错句，
    那是把一个切分口径混进了置信度诊断。
    """
    labels: list[dict] = []
    for ref in references:
        ref_text = normalize_text(ref.text)
        if len(ref_text) < 3:
            continue
        hits = [cue for cue in cues if cue.end > ref.start and cue.start < ref.end]
        if not hits:
            continue
        hyp_text = "".join(normalize_text(cue.text) for cue in hits)
        accuracy = 1.0 - levenshtein(ref_text, hyp_text) / len(ref_text)
        label = "correct" if accuracy >= 0.999 else ("wrong" if accuracy <= 0.66 else None)
        if label is None:
            continue
        for cue in hits:
            labels.append({"cue_id": id(cue), "label": label, "accuracy": accuracy})
    merged: dict[int, dict] = {}
    for item in labels:
        previous = merged.get(item["cue_id"])
        if previous is None:
            merged[item["cue_id"]] = item
        elif previous["label"] != item["label"]:
            merged[item["cue_id"]] = {"cue_id": item["cue_id"], "label": None, "accuracy": None}
    return list(merged.values())


def _rows(candidate: Path, reference: Path, audio: np.ndarray, confidences):
    cues = parse_srt(candidate.read_text(encoding="utf-8-sig"))
    refs = filter_language(parse_srt(reference.read_text(encoding="utf-8-sig")), "ja")
    labelled = {item["cue_id"]: item for item in _label_by_reference(refs, cues)}
    rows: list[dict] = []
    for index, cue in enumerate(cues):
        conf = confidences[index] if index < len(confidences) else None
        tag = labelled.get(id(cue)) or {}
        label, accuracy = tag.get("label"), tag.get("accuracy")
        duration = max(1e-3, cue.end - cue.start)
        onset_db, onset_zcr = _onset_stats(audio, cue.start)
        row = {
            "index": index,
            "start": round(cue.start, 3),
            "end": round(cue.end, 3),
            "text": cue.text,
            "label": label,
            "accuracy": None if accuracy is None else round(accuracy, 3),
            "chars": len(normalize_text(cue.text)),
            "cps": round(len(normalize_text(cue.text)) / duration, 3),
            "onset_db": round(onset_db, 1),
            "onset_zcr": round(onset_zcr, 4),
        }
        if conf is None:
            row.update(
                mean_logprob=None,
                min_char_logprob=None,
                min_pair_logprob=None,
                interp_ratio=None,
            )
        else:
            def _num(key):
                value = conf.get(key)
                return round(value, 5) if value is not None and math.isfinite(value) else None

            row.update(
                mean_logprob=_num("mean_logprob"),
                min_char_logprob=_num("min_char_logprob"),
                min_pair_logprob=_num("min_pair_logprob"),
                interp_ratio=round(
                    conf.get("interp_chars", 0) / max(1, conf.get("chars", 1)), 3
                ),
            )
        rows.append(row)
    return rows


def _analysis(rows: list[dict]) -> list[dict]:
    labelled = [row for row in rows if row["label"] in {"correct", "wrong"}]
    labels = [row["label"] == "wrong" for row in labelled]
    out: list[dict] = []
    for name, invert in FEATURES.items():
        values = []
        kept_labels = []
        for row, label in zip(labelled, labels):
            value = row.get(name)
            if value is None:
                continue
            values.append(-value if invert else value)
            kept_labels.append(label)
        score = auc(values, kept_labels)
        gate = threshold_at_fpr(values, kept_labels, fpr=0.05) if score is not None else None
        out.append(
            {
                "feature": name,
                "direction": "越小越可疑" if invert else "越大越可疑",
                "auc": None if score is None else round(score, 3),
                "threshold": None if gate is None else gate["threshold"],
                "recall_at_5pct": None if gate is None else round(gate["recall"], 3),
                "precision_at_5pct": None if gate is None else round(gate["precision"], 3),
                "samples": len(values),
            }
        )
    return out


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Qwen 置信度特征诊断（P0-3a，只诊断不接线）")
    parser.add_argument("--media", required=True)
    parser.add_argument("--ref", required=True)
    parser.add_argument("--fixtures", default=None, help=f"素材目录（默认 {DEFAULT_FIXTURES_DIR}）")
    parser.add_argument("--out", type=Path, default=None, help="字幕落盘目录（默认 outputs/eval）")
    parser.add_argument("--from", dest="start", default=None)
    parser.add_argument("--to", dest="end", default=None)
    parser.add_argument("--json", dest="json_path", type=Path, default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    warning = interpreter_warning()
    if warning:
        print(f"⚠ {warning}", file=sys.stderr)
    fixtures = resolve_fixtures(args.fixtures)
    media = resolve_fixture_path(args.media, fixtures)
    reference = resolve_fixture_path(args.ref, fixtures)
    for path, label in ((media, "素材"), (reference, "参考 SRT")):
        if not path.is_file():
            print(f"错误：{label}不存在：{path}", file=sys.stderr)
            return 2
    start = parse_time_token(args.start) if args.start else None
    end = parse_time_token(args.end) if args.end else None

    from core.pipeline import resolve_engine
    from core.transcribe import load_audio_for_transcription

    out_dir = Path(args.out) if args.out else REPO_ROOT / "outputs" / "eval"
    result, _resolved = _transcribe(
        media,
        "qwen",
        {},
        out_dir,
        start=start,
        end=end,
        progress=True,
    )
    engine = resolve_engine("qwen")
    confidences = list(getattr(engine, "last_cue_confidence", []) or [])
    if len(confidences) != len(result.cues):
        print(
            f"错误：置信度条数 {len(confidences)} 与字幕条数 {len(result.cues)} 不一致，"
            " 说明 last_cue_confidence 没有跟 cues 同步（先修这里再谈诊断）",
            file=sys.stderr,
        )
        return 1

    audio = load_audio_for_transcription(media, enable_loudnorm=True)
    rows = _rows(Path(result.out_path), reference, audio, confidences)
    analysis = _analysis(rows)

    wrong = sum(1 for row in rows if row["label"] == "wrong")
    correct = sum(1 for row in rows if row["label"] == "correct")
    grey = len(rows) - wrong - correct
    print(f"\n素材 {media.name} ｜ 字幕 {len(rows)} 条 ｜ 错句 {wrong} / 对句 {correct} / 不计 {grey}")
    print("\n| 特征 | 方向 | AUC | 5%FPR 阈值 | 召回 | 精度 |")
    print("| --- | --- | ---: | ---: | ---: | ---: |")
    for item in analysis:
        if item["auc"] is None:
            print(f"| {item['feature']} | {item['direction']} | — | — | — | — |")
            continue
        print(
            f"| {item['feature']} | {item['direction']} | {item['auc']:.3f} | "
            f"{item['threshold']:.4f} | {item['recall_at_5pct']:.2f} | "
            f"{item['precision_at_5pct']:.2f} |"
        )
    best = max((item for item in analysis if item["auc"] is not None), key=lambda i: i["auc"], default=None)
    if best:
        verdict = "可进 audit" if best["auc"] >= 0.75 else "AUC <0.75，按文档不上线"
        print(f"\n最佳特征：{best['feature']}（AUC {best['auc']:.3f}）→ {verdict}")
    print("\n错句样本（最多 10 条）：")
    for row in [item for item in rows if item["label"] == "wrong"][:10]:
        print(
            f"  {row['start']:8.2f} acc={row['accuracy']} lp={row['mean_logprob']} "
            f"pair={row['min_pair_logprob']} cps={row['cps']} {row['text'][:28]}"
        )

    if args.json_path:
        args.json_path.parent.mkdir(parents=True, exist_ok=True)
        args.json_path.write_text(
            json.dumps(
                {
                    "media": media.name,
                    "reference": reference.name,
                    "counts": {"wrong": wrong, "correct": correct, "skipped": grey},
                    "features": analysis,
                    "rows": rows,
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        print(f"\nJSON：{args.json_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
