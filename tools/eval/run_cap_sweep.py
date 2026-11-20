#!/usr/bin/env python3
"""VAD 单次送模上限（max_segment_s）扫描：只给评测用，绕开参数面板的 5s 下限。

    ../.venv/bin/python tools/eval/run_cap_sweep.py --values 4.0,4.2,4.3,5.0

参数面板把 `whisper.vad_max_segment_s` 限制在 >= 5.0（产品口径：块太短会丢上下文）。
这个脚本直接改 `WhisperVadConfig.max_segment_s`，用同一套 run_clip/score_srt 口径
回答「压到 4.x 能不能把超长条打下来、CER 会不会变差」。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.eval.run_clip import run_one  # noqa: E402
from tools.eval.scorecard import resolve_fixture_path, resolve_fixtures  # noqa: E402

import tools.eval.run_clip as run_clip  # noqa: E402

_original = run_clip._engine_configs
_CAP = {"value": None}


def _patched(engine_key, overrides, gate=None):
    whisper_config, qwen_config, passthrough, resolved = _original(
        engine_key, overrides, gate
    )
    if whisper_config is not None and _CAP["value"] is not None:
        whisper_config.max_segment_s = float(_CAP["value"])
        resolved["whisper.vad_max_segment_s"] = float(_CAP["value"])
    return whisper_config, qwen_config, passthrough, resolved


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="VAD max_segment_s 扫描（评测专用）")
    parser.add_argument("--media", default="../Jap_test_2.mp4")
    parser.add_argument("--ref", default="../Jap_test_2_perfect.srt")
    parser.add_argument("--fixtures", default="..")
    parser.add_argument("--values", default="4.0,4.2,4.3,5.0")
    parser.add_argument("--backend", default="whisperseg")
    parser.add_argument("--threshold", default="0.35")
    parser.add_argument("--out", type=Path, default=Path("outputs/eval/p1/cap_sweep"))
    parser.add_argument("--json", type=Path, default=Path("outputs/eval/p1/cap_sweep.json"))
    args = parser.parse_args(argv)

    fixtures = resolve_fixtures(args.fixtures)
    media = resolve_fixture_path(args.media, fixtures)
    reference = resolve_fixture_path(args.ref, fixtures)
    args.out.mkdir(parents=True, exist_ok=True)

    overrides = {
        "whisper.vad_backend": args.backend,
        "whisper.vad_threshold": float(args.threshold),
    }
    run_clip._engine_configs = _patched
    rows = []
    for raw in args.values.split(","):
        cap = float(raw)
        _CAP["value"] = cap
        out_dir = args.out / f"cap_{raw.replace('.', '_')}"
        out_dir.mkdir(parents=True, exist_ok=True)
        print(f"\n=== max_segment_s={cap} ===", file=sys.stderr, flush=True)
        card = run_one(
            engine="whisper",
            media=media,
            reference=reference,
            out_dir=out_dir,
            overrides=overrides,
            progress=True,
        )
        row = {
            "max_segment_s": cap,
            "cer": card["score"]["cer"],
            "missed_blocks": card["score"]["missed_blocks"],
            "insertions": card["score"]["insertions"],
            "max_cue_dur": card["score"]["max_cue_dur"],
            "over_4_3s": card["score"]["over_4_3s"],
            "cues": card["run"]["cues"],
            "pending_qa": card["run"]["pending_qa"],
            "elapsed_s": card["run"]["elapsed_s"],
            "peak_rss_mb": card["run"]["peak_rss_mb"],
        }
        rows.append(row)
        print(json.dumps(row, ensure_ascii=False))

    payload = {"backend": args.backend, "threshold": args.threshold, "rows": rows}
    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                         encoding="utf-8")
    print("\n| 上限 | CER | 漏块 | 插入 | 最长条 | >4.3s | 条数 | 质检 | 耗时 | RSS |")
    print("| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |")
    for r in rows:
        print(f"| {r['max_segment_s']}s | {r['cer'] * 100:.2f}% | {r['missed_blocks']} | "
              f"{r['insertions']} | {r['max_cue_dur']:.2f}s | {r['over_4_3s']} | "
              f"{r['cues']} | {r['pending_qa']} | {r['elapsed_s']:.1f}s | "
              f"{r['peak_rss_mb']:.0f} MB |")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
