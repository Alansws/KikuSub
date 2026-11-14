#!/usr/bin/env python3
"""逐窗探针：拿参考 SRT 的每条时间窗直接送模型，把「识别」与「分段/断句」分开。

这就是路线文档 §2.1 用的那套做法（原型在工作区的 `tune/qwen_probe.py`）：
绕开 VAD 与断句，只问「给模型这段音频，它能不能听出来」，所以「识别对了但产品
字幕缺了句首」就能被判定成前端问题，而不是模型能力问题。

    python tools/eval/probe_window.py --media Jap_test.mp4 \
        --ref Jap_test_perfect.srt --pad 0.25 --fixtures /path/to/fixtures

只支持 qwen：它的模型级入口 `_transcribe(chunk)` 就是引擎解码本身，没有第二份
生成参数。Whisper 的模型级调用藏在 `transcribe.py::_decode` 闭包里，硬拷一份
`generate_kwargs` 等于再造第二份真相；Whisper 侧要看「句首缺字」，用
`run_clip.py` 的 scorecard 指标复核。

音频按 `--pad` 在人工时间窗左右各扩一点再送模（§2.1 用 0.25s）；默认开启动态
响度归一化，与产品链路一致，`--no-loudnorm` 用于诊断「归一化压扁轻声起音」。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.eval.score_srt import (  # noqa: E402
    levenshtein,
    normalize_text,
    parse_srt,
)
from tools.eval.scorecard import (  # noqa: E402
    DEFAULT_FIXTURES_DIR,
    interpreter_warning,
    resolve_fixture_path,
    resolve_fixtures,
)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="逐窗直送探针：绕开 VAD，把参考时间窗直接送 Qwen3-ASR"
    )
    parser.add_argument("--engine", default="qwen", choices=["qwen"], help="目前只支持 qwen")
    parser.add_argument("--media", required=True, help="素材路径；相对路径按 --fixtures 解析")
    parser.add_argument("--ref", required=True, help="参考 SRT；相对路径按 --fixtures 解析")
    parser.add_argument("--fixtures", default=None, help=f"素材目录（默认 {DEFAULT_FIXTURES_DIR}）")
    parser.add_argument("--pad", type=float, default=0.25, help="时间窗左右各扩多少秒（默认 0.25）")
    parser.add_argument(
        "--no-loudnorm", action="store_true", help="关闭动态响度归一化（诊断用，不是产品口径）"
    )
    parser.add_argument("--limit", type=int, default=0, help="只探前 N 条（0 = 全部）")
    parser.add_argument("--json", dest="json_path", type=Path, default=None, help="逐条结果写入 JSON")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    warning = interpreter_warning()
    if warning:
        print(f"⚠ {warning}", file=sys.stderr)
    fixtures = resolve_fixtures(args.fixtures)
    media = resolve_fixture_path(args.media, fixtures)
    reference = resolve_fixture_path(args.ref, fixtures)
    for path, label in ((media, "素材"), (reference, "参考 SRT")):
        if not path.is_file():
            print(f"错误：{label}不存在：{path}（用 --fixtures 指定素材目录）", file=sys.stderr)
            return 2
    if args.pad < 0:
        print("错误：--pad 不能为负", file=sys.stderr)
        return 2

    import numpy as np

    from core import params as param_specs
    from core.pipeline import resolve_engine
    from core.qwen_ctc import QwenCtcConfig
    from core.transcribe import SAMPLE_RATE, load_audio_for_transcription

    cues = parse_srt(reference.read_text(encoding="utf-8-sig"))
    if args.limit > 0:
        cues = cues[: args.limit]
    if not cues:
        print("错误：参考 SRT 没有可用的时间窗", file=sys.stderr)
        return 2

    print(f"解码音频：{media.name}（响度归一化 {'关' if args.no_loudnorm else '开'}）",
          file=sys.stderr, flush=True)
    audio = load_audio_for_transcription(media, enable_loudnorm=not args.no_loudnorm)

    engine = resolve_engine("qwen")
    engine.load()
    config = QwenCtcConfig(**param_specs.config_kwargs("qwen", {}))

    rows: list[dict] = []
    edits = chars = empties = 0
    for index, cue in enumerate(cues, start=1):
        lo = max(0, int(round((cue.start - args.pad) * SAMPLE_RATE)))
        hi = min(audio.size, int(round((cue.end + args.pad) * SAMPLE_RATE)))
        chunk = np.ascontiguousarray(audio[lo:hi], dtype=np.float32)
        hypothesis, _ = engine._transcribe(chunk, config)
        ref_text = normalize_text(cue.text)
        hyp_text = normalize_text(hypothesis)
        distance = levenshtein(ref_text, hyp_text)
        edits += distance
        chars += len(ref_text)
        if not hyp_text:
            empties += 1
        rows.append(
            {
                "index": index,
                "start": round(cue.start, 3),
                "end": round(cue.end, 3),
                "ref": cue.text.strip(),
                "hyp": (hypothesis or "").strip(),
                "edits": distance,
                "ref_chars": len(ref_text),
            }
        )
        flag = "  " if distance <= max(1, len(ref_text) // 5) else ("空!" if not hyp_text else "错 ")
        print(f"{index:3d} {cue.start:7.2f}-{cue.end:7.2f} {flag} "
              f"ref={cue.text.strip()}  |  hyp={hypothesis or '∅'}")

    cer = edits / chars if chars else 0.0
    print(
        f"\n逐窗 CER = {cer * 100:.2f}%（{edits}/{chars} 字，每窗各自编辑距离后按字数加权）｜ "
        f"空结果 {empties}/{len(rows)}"
    )
    if args.json_path:
        args.json_path.parent.mkdir(parents=True, exist_ok=True)
        args.json_path.write_text(
            json.dumps(
                {
                    "engine": args.engine,
                    "media": media.name,
                    "reference": reference.name,
                    "pad_s": args.pad,
                    "loudnorm": not args.no_loudnorm,
                    "cer": round(cer, 6),
                    "empties": empties,
                    "cues": len(rows),
                    "rows": rows,
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        print(f"JSON：{args.json_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
