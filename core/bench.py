"""标准库层面的性能基线：`python -m core.bench`。

为什么要有：改断句、改 SRT 解析、改字幕表聚合之后，"感觉没变慢"不算证据。这里跑一组
**不依赖模型、不依赖 UI** 的纯函数工作负载，输出一份可跨版本对比的 JSON。

它刻意不测转写本身（那需要权重与真实音频，属于 `tools/eval/score_srt.py` 的领域）。
用法：

    python -m core.bench                 # 打印表格
    python -m core.bench --json out.json # 另外写一份 JSON
    python -m core.bench --quick         # 规模缩小 10 倍，给 CI/单测用
"""

from __future__ import annotations

import argparse
import json
import statistics
import tempfile
import time
from pathlib import Path

from .subtitles import (
    SubtitleCue,
    align_translation_texts,
    cues_from_subtitle_file,
    cues_to_srt,
    srt_to_cues,
)

#: 默认规模：5000 条 ≈ 一集 24 分钟番剧的 8 倍，足够暴露 O(n²)。
DEFAULT_CUES = 5000
#: 每个工作负载重复次数（取中位数，避开偶发的调度抖动）。
REPEATS = 3


def _make_cues(count: int) -> list[SubtitleCue]:
    cues = []
    for i in range(count):
        start = i * 2.0
        cues.append(SubtitleCue(start, start + 1.8, f"これはテスト用の字幕です。{i}"))
    return cues


def _time(fn, repeats: int = REPEATS) -> float:
    samples = []
    for _ in range(repeats):
        t0 = time.perf_counter()
        fn()
        samples.append((time.perf_counter() - t0) * 1000.0)
    return round(statistics.median(samples), 2)


def run(count: int = DEFAULT_CUES) -> dict:
    cues = _make_cues(count)
    srt = cues_to_srt(cues)
    texts = [c.text for c in cues]
    results: dict[str, float] = {}

    results["srt_to_cues"] = _time(lambda: srt_to_cues(srt))
    results["cues_to_srt"] = _time(lambda: cues_to_srt(cues))
    results["align_translation_texts"] = _time(lambda: align_translation_texts(cues, cues))

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "bench.srt"
        path.write_text(srt, encoding="utf-8")
        results["cues_from_subtitle_file"] = _time(lambda: cues_from_subtitle_file(path))

    return {"cues": count, "ms": results}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m core.bench", description="字幕内核性能基线")
    parser.add_argument("--cues", type=int, default=None, help=f"字幕条数（默认 {DEFAULT_CUES}）")
    parser.add_argument("--quick", action="store_true", help="1/10 规模，适合 CI")
    parser.add_argument("--json", type=Path, default=None, help="把结果写到这个 JSON 文件")
    args = parser.parse_args(argv)

    count = args.cues or (DEFAULT_CUES // 10 if args.quick else DEFAULT_CUES)
    payload = run(count)

    print(f"KikuSub 内核基线 · {payload['cues']} 条字幕 · 毫秒（中位数 / {REPEATS} 次）")
    width = max(len(k) for k in payload["ms"])
    for name, ms in payload["ms"].items():
        print(f"  {name:<{width}}  {ms:8.2f} ms")

    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"已写入 {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
