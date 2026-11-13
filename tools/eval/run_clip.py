#!/usr/bin/env python3
"""一条命令跑「一个引擎 × 一支片 × 一组参数」，打印一张 scorecard。

    python tools/eval/run_clip.py --engine qwen --media Jap_test.mp4 \
        --ref Jap_test_perfect.srt --fixtures /path/to/fixtures

三条使用约定：

- 只覆盖 **whisper / qwen** 两个日语引擎；sherpa 两个中文引擎的权重按需下载，
  评测请走应用内，免得评测台顺手触发几 GB 的下载；
- 参数默认取 `core.params` 的内置默认值，`--set whisper.vad_threshold=0.25` 临时覆写；
  **不认识的键会直接报错**，不会静默忽略；
- `--baseline tools/eval/baseline.json` 与基线比，回归时以退出码 1 报告（手动闸门用）。
  基线比对只回答「有没有变差」，改善多少请用 `--set` 跑多组再并排看。

字幕落在 `--out`（默认 `outputs/eval/`），音频缓存复用 `outputs/.cache/audio/`，
所以同一支片的第二组参数不用重新解码。
"""

from __future__ import annotations

import argparse
import json
import resource
import sys
import threading
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.eval.score_srt import (  # noqa: E402
    filter_language,
    filter_time,
    parse_srt,
    parse_time_token,
    score,
)
from tools.eval.scorecard import (  # noqa: E402
    DEFAULT_FIXTURES_DIR,
    OverrideError,
    apply_overrides,
    build_card,
    compare_to_baseline,
    find_run,
    fixture_problems,
    format_card,
    format_comparison,
    format_onset,
    interpreter_warning,
    load_baseline,
    onset_missing,
    resolve_fixture_path,
    resolve_fixtures,
)

SUPPORTED_FAMILIES = {"whisper", "qwen"}


# --------------------------------------------------------------------------- 峰值内存


class _MpsPeak:
    """后台线程采样 MPS 已分配显存；torch 不可用就整类失效（不影响跑片）。"""

    def __init__(self) -> None:
        self.peak_bytes = 0
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._available = False
        try:
            import torch

            self._available = bool(torch.backends.mps.is_available())
        except Exception:  # noqa: BLE001 - 没有 torch 也要能报错退出
            self._available = False

    def start(self) -> None:
        if not self._available:
            return
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def _loop(self) -> None:
        import torch

        while not self._stop.is_set():
            try:
                self.peak_bytes = max(self.peak_bytes, int(torch.mps.driver_allocated_memory()))
            except Exception:  # noqa: BLE001 - 采样失败不该让跑片失败
                pass
            self._stop.wait(0.1)

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=1.0)

    @property
    def peak_mb(self) -> float | None:
        return round(self.peak_bytes / (1024 * 1024), 1) if self.peak_bytes else None


def _peak_rss_mb() -> float:
    raw = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    # macOS 的 ru_maxrss 是字节，Linux 是 KB。
    return raw / (1024 * 1024) if sys.platform == "darwin" else raw / 1024


def _media_duration_s(path: Path) -> float | None:
    try:
        from core.video_export import probe_source

        duration = float(probe_source(path).duration or 0.0)
    except Exception:  # noqa: BLE001 - 时长只是素材元信息，探不到就算了
        return None
    return duration or None


# --------------------------------------------------------------------------- 引擎配置


def _engine_configs(engine_key: str, overrides: dict):
    """返回 (whisper_config, qwen_config, passthrough, resolved)。"""
    from core import engines as registry
    from core import params as param_specs

    known = [spec.key for spec in registry.ENGINES]
    if engine_key not in known:
        raise SystemExit(f"未知引擎 {engine_key!r}；可用：{' / '.join(known)}")
    family = registry.family_of(engine_key)
    if family not in SUPPORTED_FAMILIES:
        raise SystemExit(
            f"评测台只覆盖 whisper / qwen；{engine_key!r} 的 family={family!r}。"
            "  sherpa 引擎请走应用内评测（权重按需下载）。"
        )
    kwargs = param_specs.config_kwargs(engine_key, overrides)
    resolved = param_specs.normalize(engine_key, overrides)
    passthrough = param_specs.passthrough_kwargs(engine_key, overrides)
    if family == "qwen":
        from core.qwen_ctc import QwenCtcConfig

        return None, QwenCtcConfig(**kwargs), passthrough, resolved
    from core.transcribe import build_whisper_config

    return build_whisper_config(**kwargs), None, passthrough, resolved


def _known_engines() -> list[str]:
    from core import engines as registry

    return [spec.key for spec in registry.ENGINES]


def _default_params(engine_key: str) -> dict:
    """内置默认值，只用于把「这次改过哪几个键」显示出来。"""
    from core import params as param_specs

    return param_specs.defaults_for(engine_key)


def _transcribe(media: Path, engine_key: str, overrides: dict, out_dir: Path, args):
    from core.pipeline import TranscribeRequest, run_transcription

    whisper_config, qwen_config, passthrough, resolved = _engine_configs(engine_key, overrides)
    req = TranscribeRequest(
        media_path=media,
        engine_key=engine_key,
        output_format="SRT",
        whisper_config=whisper_config,
        qwen_config=qwen_config,
        start_s=args.start,
        end_s=args.end,
        write_audit=False,  # 评测不该覆盖应用里的待核进度
        no_repeat_ngram_size=int(passthrough.get("no_repeat_ngram_size", 5)),
        repetition_penalty=float(passthrough.get("repetition_penalty", 1.15)),
        use_alignment=bool(passthrough.get("use_alignment", True)),
    )
    state = {"last": -5}

    def on_progress(ratio: float, message: str) -> None:
        pct = int(round(ratio * 100))
        if pct >= state["last"] + 5 or ratio >= 1.0:
            state["last"] = pct
            print(f"  [{pct:3d}%] {message}", file=sys.stderr, flush=True)

    print(f"跑片：{engine_key} × {media.name}", file=sys.stderr, flush=True)
    result = run_transcription(req, on_progress=on_progress, output_dir=out_dir)
    return result, resolved


# --------------------------------------------------------------------------- 主流程


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="跑一次「引擎 × 片 × 参数」并打印 scorecard（评测台，不参与产品流程）"
    )
    parser.add_argument("--engine", required=True, help="引擎 key（whisper / qwen）")
    parser.add_argument("--media", required=True, help="素材路径；相对路径按 --fixtures 解析")
    parser.add_argument("--ref", required=True, help="参考 SRT；相对路径按 --fixtures 解析")
    parser.add_argument("--fixtures", default=None, help=f"素材目录（默认 {DEFAULT_FIXTURES_DIR}）")
    parser.add_argument("--out", type=Path, default=None, help="字幕落盘目录（默认 outputs/eval）")
    parser.add_argument("--from", dest="start", default=None, help="起始时间：HH:MM:SS 或秒")
    parser.add_argument("--to", dest="end", default=None, help="终止时间：HH:MM:SS 或秒")
    parser.add_argument(
        "--set", dest="overrides", action="append", default=[], metavar="KEY=VALUE",
        help="临时覆写参数，可重复，例如 --set whisper.vad_threshold=0.25",
    )
    parser.add_argument("--json", dest="json_path", type=Path, default=None, help="把卡片写入 JSON")
    parser.add_argument("--baseline", type=Path, default=None, help="基线 JSON（tools/eval/baseline.json）")
    parser.add_argument("--against", default=None, help="基线条目 id（默认按引擎 + 参考文件匹配）")
    parser.add_argument(
        "--tolerance-pt", type=float, default=0.5, help="CER 回归容差，默认 0.5pt（噪声带）"
    )
    parser.add_argument(
        "--check-fixtures", action="store_true",
        help="只按基线指纹核对素材，不跑模型",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    warning = interpreter_warning()
    if warning:
        print(f"⚠ {warning}", file=sys.stderr)
    known = _known_engines()
    if args.engine not in known:
        print(f"错误：未知引擎 {args.engine!r}；可用：{' / '.join(known)}", file=sys.stderr)
        return 2
    fixtures = resolve_fixtures(args.fixtures)

    if args.check_fixtures:
        if args.baseline is None:
            print("错误：--check-fixtures 需要 --baseline", file=sys.stderr)
            return 2
        problems = fixture_problems(load_baseline(args.baseline), fixtures)
        if problems:
            print("素材核对失败：", file=sys.stderr)
            for item in problems:
                print(f"  - {item}", file=sys.stderr)
            return 1
        print(f"素材核对通过：{fixtures}")
        return 0

    media = resolve_fixture_path(args.media, fixtures)
    reference = resolve_fixture_path(args.ref, fixtures)
    for path, label in ((media, "素材"), (reference, "参考 SRT")):
        if not path.is_file():
            print(f"错误：{label}不存在：{path}（用 --fixtures 指定素材目录）", file=sys.stderr)
            return 2
    try:
        start = parse_time_token(args.start) if args.start else None
        end = parse_time_token(args.end) if args.end else None
    except ValueError as exc:
        print(f"错误：时间格式无法解析：{exc}", file=sys.stderr)
        return 2
    if start is not None and end is not None and end <= start:
        print("错误：--to 必须大于 --from", file=sys.stderr)
        return 2

    try:
        overrides = apply_overrides(args.engine, args.overrides)
    except OverrideError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 2

    out_dir = Path(args.out) if args.out else REPO_ROOT / "outputs" / "eval"
    out_dir.mkdir(parents=True, exist_ok=True)

    sampler = _MpsPeak()
    started = time.perf_counter()
    sampler.start()
    try:
        result, resolved = _transcribe(media, args.engine, overrides, out_dir, args)
    finally:
        sampler.stop()
    wall_s = time.perf_counter() - started

    hypothesis = parse_srt(Path(result.out_path).read_text(encoding="utf-8-sig"))
    reference_cues = parse_srt(reference.read_text(encoding="utf-8-sig"))
    score_result = score(reference_cues, hypothesis, start=start, end=end)
    ref_ja = filter_time(filter_language(reference_cues, "ja"), start, end)
    onset = onset_missing(ref_ja, filter_language(hypothesis, "all"))

    card = build_card(
        engine=args.engine,
        media=media,
        reference=reference,
        score_result=score_result,
        resolved_params=resolved,
        cues=len(result.cues),
        chars=result.char_count,
        pending_qa=result.pending_qa,
        elapsed_s=wall_s,
        peak_rss_mb=_peak_rss_mb(),
        peak_mps_mb=sampler.peak_mb,
        onset=onset,
        media_duration_s=_media_duration_s(media),
        timerange=(start, end),
    )

    print()
    print(format_card(card, defaults=_default_params(args.engine)))
    print(format_onset(card["onset_missing"]["items"]))
    if args.json_path:
        args.json_path.parent.mkdir(parents=True, exist_ok=True)
        args.json_path.write_text(
            json.dumps(card, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(f"卡片：{args.json_path}")

    if args.baseline is None:
        return 0
    baseline = load_baseline(args.baseline)
    try:
        run = find_run(
            baseline, engine=args.engine, reference=reference.name, run_id=args.against
        )
    except KeyError as exc:
        print(f"错误：{exc.args[0]}", file=sys.stderr)
        return 2
    comparison = compare_to_baseline(card, run, tolerance_pt=args.tolerance_pt)
    print()
    print(format_comparison(comparison))
    return 1 if comparison["regressed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
