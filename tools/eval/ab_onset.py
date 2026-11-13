#!/usr/bin/env python3
"""句首补回的 A/B 矩阵驱动（路线文档 P0-1）。

    python tools/eval/ab_onset.py --engines qwen \
        --media Jap_test_2.mp4 --ref Jap_test_2_perfect.srt \
        --fixtures . --groups a0,a1,a2,a2b,a3

每组只是「起点提前多少」+「要不要过能量闸门」，跑片逻辑全部复用 `run_clip.run_one`，
所以表里的数字与 `run_clip.py` 单跑完全同源。

默认组（与文档的 A/B 矩阵一一对应）：

| 组 | 起点提前 | 闸门 |
| --- | ---: | --- |
| a0 | 0 | —（基线） |
| a1 | 400 ms | 无 |
| a2 | 400 ms | 纯信噪比 |
| a2b | 400 ms | 相对 + 上限 |
| a3 | 600 ms | 无 |
| a4 | 600 ms | 纯信噪比（可选） |

表里除 CER / 插入 / 句首缺字，还加了一列「重复句」的代理指标：吃进上一句尾音时，
重复句先涨、CER 未必涨（文档把这条列为 P0-1 的风险）。它只统计「相邻两条归一化后
文本完全相同」，不做语义判断。
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.eval.run_clip import run_one  # noqa: E402
from tools.eval.score_srt import (  # noqa: E402
    normalize_text,
    parse_srt,
    parse_time_token,
)
from tools.eval.scorecard import (  # noqa: E402
    DEFAULT_FIXTURES_DIR,
    interpreter_warning,
    resolve_fixture_path,
    resolve_fixtures,
)

GROUPS = {
    "a0": (0, "none"),
    "a1": (400, "none"),
    "a2": (400, "snr"),
    "a2b": (400, "snr_cap"),
    "a3": (600, "none"),
    "a4": (600, "snr"),
}
DEFAULT_GROUPS = "a0,a1,a2,a2b,a3"

HEADER = (
    "| 引擎 | 组 | 提前 | 闸门 | CER | ΔCER | 插入 (Δ) | 句首缺字 | 重复句 (Δ) | 耗时 |\n"
    "| --- | --- | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: |"
)


def _duplicate_cues(cues, min_chars: int = 4) -> int:
    """相邻两条文本完全相同的次数（「吃进上一句尾音」的代理指标）。"""
    count = 0
    previous = ""
    for cue in cues:
        text = normalize_text(cue.text)
        if len(text) >= min_chars and text == previous:
            count += 1
        previous = text
    return count


def _candidate_path(out_dir: Path, media: Path, engine: str) -> Path:
    suffix = "" if engine == "whisper" else f".{engine}"
    return out_dir / f"{media.stem}{suffix}.srt"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="句首补回 A/B 矩阵（评测台，不参与产品流程）")
    parser.add_argument("--engines", default="qwen", help="逗号分隔：qwen / whisper")
    parser.add_argument("--media", required=True, help="素材；相对路径按 --fixtures 解析")
    parser.add_argument("--ref", required=True, help="参考 SRT；相对路径按 --fixtures 解析")
    parser.add_argument("--fixtures", default=None, help=f"素材目录（默认 {DEFAULT_FIXTURES_DIR}）")
    parser.add_argument("--groups", default=DEFAULT_GROUPS, help=f"逗号分隔（默认 {DEFAULT_GROUPS}）")
    parser.add_argument("--out", type=Path, default=None, help="字幕落盘目录（默认 outputs/eval）")
    parser.add_argument("--from", dest="start", default=None, help="起始时间：HH:MM:SS 或秒")
    parser.add_argument("--to", dest="end", default=None, help="终止时间：HH:MM:SS 或秒")
    parser.add_argument("--json", dest="json_path", type=Path, default=None, help="把矩阵写入 JSON")
    parser.add_argument("--markdown", type=Path, default=None, help="把表格写入 .md")
    parser.add_argument("--quiet", action="store_true", help="不打印每组进度")
    return parser


def _fmt_row(entry: dict, base: dict | None) -> str:
    if base is None:
        delta = ins_delta = dup_delta = "—"
    else:
        delta = f"{(entry['cer'] - base['cer']) * 100:+.2f}pt"
        ins_delta = f"{entry['insertions'] - base['insertions']:+d}"
        dup_delta = f"{entry['duplicates'] - base['duplicates']:+d}"
    return (
        f"| {entry['engine']} | {entry['group']} | {entry['pad_ms']} ms | {entry['gate']} | "
        f"{entry['cer'] * 100:.2f}% | {delta} | {entry['insertions']} ({ins_delta}) | "
        f"{entry['onset_missing']} | {entry['duplicates']} ({dup_delta}) | "
        f"{entry['elapsed_s']:.0f}s |"
    )


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
            print(f"错误：{label}不存在：{path}（用 --fixtures 指定素材目录）", file=sys.stderr)
            return 2

    try:
        start = parse_time_token(args.start) if args.start else None
        end = parse_time_token(args.end) if args.end else None
    except ValueError as exc:
        print(f"错误：时间格式无法解析：{exc}", file=sys.stderr)
        return 2

    engines = [item.strip() for item in args.engines.split(",") if item.strip()]
    groups = [item.strip() for item in args.groups.split(",") if item.strip()]
    unknown = [group for group in groups if group not in GROUPS]
    if unknown:
        print(f"错误：未知组 {unknown}；可用：{' / '.join(GROUPS)}", file=sys.stderr)
        return 2

    out_dir = Path(args.out) if args.out else REPO_ROOT / "outputs" / "eval"
    rows: list[dict] = []
    for engine in engines:
        for group in groups:
            pad_ms, gate = GROUPS[group]
            print(f"\n▶ {engine} / {group}（提前 {pad_ms} ms，闸门 {gate}）", file=sys.stderr)
            try:
                card = run_one(
                    engine=engine,
                    media=media,
                    reference=reference,
                    out_dir=out_dir,
                    start=start,
                    end=end,
                    overrides={f"{engine}.vad_onset_pad_ms": pad_ms},
                    gate=gate,
                    progress=not args.quiet,
                )
            except Exception as exc:  # noqa: BLE001 - 一组成败不该中断整张表
                print(f"  ✗ {group} 失败：{exc}", file=sys.stderr)
                rows.append({"engine": engine, "group": group, "error": str(exc)})
                continue
            # 每组一份 SRT 留档：只看数字不够，插入涨了要能翻到具体是哪几条。
            srt = _candidate_path(out_dir, media, engine)
            archive = out_dir / "ab" / f"{media.stem}.{engine}.{group}.srt"
            archive.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(srt, archive)
            duplicates = _duplicate_cues(parse_srt(archive.read_text(encoding="utf-8-sig")))
            row = {
                "engine": engine,
                "group": group,
                "pad_ms": pad_ms,
                "gate": gate,
                "cer": card["score"]["cer"],
                "insertions": card["score"]["insertions"],
                "onset_missing": card["onset_missing"]["count"],
                "duplicates": duplicates,
                "cues": card["score"]["hypothesis_cues"],
                "elapsed_s": card["run"]["elapsed_s"],
                "srt": str(archive),
                "card": card,
            }
            rows.append(row)
            print(
                f"  CER {row['cer'] * 100:.2f}% ｜ 插入 {row['insertions']} ｜ "
                f"句首缺字 {row['onset_missing']} ｜ 重复句 {duplicates}",
                file=sys.stderr,
            )

    if not any("cer" in row for row in rows):
        return 1

    table: list[str] = [HEADER]
    for entry in rows:
        if "error" in entry:
            table.append(f"| {entry['engine']} | {entry['group']} | — | — | ✗ 失败 | | | | | |")
            continue
        base = next(
            (
                row
                for row in rows
                if row.get("engine") == entry["engine"]
                and row["group"] == groups[0]
                and "cer" in row
            ),
            None,
        )
        if base is entry:
            base = None
        table.append(_fmt_row(entry, base))

    body = "\n".join(table)
    print(f"\n素材 `{media.name}` ｜ 参考 `{reference.name}`\n")
    print(body)
    print(
        "\n升级门槛（路线文档 §5）：CER 改善 ≥0.5pt **且**插入不涨；"
        f"或句首缺字降 ≥50%。`{groups[0]}` 是基线，其余与它比。"
    )
    if args.markdown:
        args.markdown.parent.mkdir(parents=True, exist_ok=True)
        args.markdown.write_text(
            f"素材 `{media.name}` ｜ 参考 `{reference.name}`\n\n{body}\n", encoding="utf-8"
        )
    if args.json_path:
        args.json_path.parent.mkdir(parents=True, exist_ok=True)
        args.json_path.write_text(
            json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(f"矩阵：{args.json_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
