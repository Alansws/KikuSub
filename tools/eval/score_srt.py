#!/usr/bin/env python3
"""字幕评测台：对参考 SRT 与候选 SRT 计算 CER、块准确率、漏块与切分统计。

只依赖标准库，不加载 torch/模型，因此可以在任何机器上复跑：

    python tools/eval/score_srt.py \
        --reference 测试用_言叶之庭_中日双语.srt \
        --hypothesis outputs/xxx.srt \
        --from 00:00:30 --to 00:05:30

设计口径（与 docs/ 里的历史评测一致）：

* 参考字幕若是中日双语，默认只取含假名的日文行（`--ref-lang ja`）；
* CER = 字符级编辑距离 / 参考字符数，标点与空白不计；
* 块准确率 = 每条参考字幕与其时间重叠候选文本的 1 - CER，再取平均；
* 漏块 = 块准确率 < 35% 且参考文本 >= 3 字的条数；
* 额外输出「下一条以助词/活用尾开头」的次数，用于观察劈词（越低越好）。

它不做“谁对谁错”的语义判断，也不替代人工校对；它的价值是让同一段素材
在改动前后有可比较的数字。
"""

from __future__ import annotations

import argparse
import difflib
import json
import re
import statistics
import sys
import unicodedata
from dataclasses import dataclass
from pathlib import Path

TIME_LINE_RE = re.compile(
    r"^\s*(?P<start>\d{1,}:\d{2}:\d{2}[,.]\d{1,3})\s*-->\s*"
    r"(?P<end>\d{1,}:\d{2}:\d{2}[,.]\d{1,3})(?:\s+.*)?\s*$"
)
TIME_TOKEN_RE = re.compile(r"^\s*(\d{1,}:\d{2}(?::\d{2})?)([,.]\d{1,3})?\s*$")

# 只用于 CER 的标点/空白归一化；长音符「ー」保留，因为它可能是词的一部分。
_PUNCT = set(
    "、。！？!?…‥，,．.：:；;・「」『』（）()［］[]【】〈〉《》～〜"
    "\"“”‘’'`· 　\t\r\n"
)
PARTICLE_STARTS = set("はがをにでへとものかねよわや")
AUX_STARTS = set("るたてだなばれらずぬ")


@dataclass
class Cue:
    start: float
    end: float
    text: str


def parse_time_token(value: str) -> float:
    """支持 HH:MM:SS,mmm / MM:SS / 纯秒数。"""
    value = (value or "").strip().replace(",", ".")
    if not value:
        raise ValueError("空时间")
    match = TIME_TOKEN_RE.match(value)
    if not match:
        return float(value)
    parts = [int(p) for p in match.group(1).split(":")]
    if len(parts) == 3:
        seconds = parts[0] * 3600 + parts[1] * 60 + parts[2]
    else:
        seconds = parts[0] * 60 + parts[1]
    if match.group(2):
        seconds += float("0" + match.group(2))
    return float(seconds)


def parse_srt(text: str) -> list[Cue]:
    """解析 SRT；对空行/CRLF/BOM/缺序号都宽容。"""
    normalized = text.lstrip("\ufeff").replace("\r\n", "\n").replace("\r", "\n")
    blocks = re.split(r"\n\s*\n", normalized)
    cues: list[Cue] = []
    for block in blocks:
        lines = [line.strip() for line in block.split("\n") if line.strip()]
        if not lines:
            continue
        time_index = None
        match = None
        for i, line in enumerate(lines):
            match = TIME_LINE_RE.match(line)
            if match:
                time_index = i
                break
        if match is None or time_index is None:
            continue
        body = "\n".join(lines[time_index + 1 :]).strip()
        if not body:
            continue
        try:
            start = parse_time_token(match.group("start"))
            end = parse_time_token(match.group("end"))
        except ValueError:
            continue
        cues.append(Cue(start=start, end=end, text=body))
    return cues


def normalize_text(text: str) -> str:
    value = unicodedata.normalize("NFKC", text or "")
    return "".join(ch for ch in value if not ch.isspace() and ch not in _PUNCT)


def has_kana(text: str) -> bool:
    return any("\u3040" <= ch <= "\u30ff" or "\u31f0" <= ch <= "\u31ff" for ch in text or "")


def filter_language(cues: list[Cue], lang: str) -> list[Cue]:
    lang = (lang or "ja").lower()
    if lang in {"ja", "jp", "japanese"}:
        return [c for c in cues if has_kana(c.text)]
    if lang in {"zh", "cn", "chinese"}:
        return [
            c
            for c in cues
            if any("\u4e00" <= ch <= "\u9fff" for ch in c.text) and not has_kana(c.text)
        ]
    return list(cues)


def filter_time(cues: list[Cue], start: float | None, end: float | None) -> list[Cue]:
    out = []
    for cue in cues:
        if start is not None and cue.end <= start:
            continue
        if end is not None and cue.start >= end:
            continue
        out.append(cue)
    return out


def levenshtein(a: str, b: str) -> int:
    """字符级编辑距离（两行滚动数组）。"""
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    previous = list(range(len(b) + 1))
    for i, ch_a in enumerate(a, start=1):
        current = [i]
        for j, ch_b in enumerate(b, start=1):
            insert = current[j - 1] + 1
            delete = previous[j] + 1
            replace = previous[j - 1] + (ch_a != ch_b)
            current.append(min(insert, delete, replace))
        previous = current
    return previous[-1]


def edit_ops(a: str, b: str) -> tuple[int, int, int]:
    """近似 S/D/I 拆分；总数与 SequenceMatcher 的匹配块一致，CER 仍用 levenshtein。"""
    substitutions = deletions = insertions = 0
    matcher = difflib.SequenceMatcher(None, a, b, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        left, right = i2 - i1, j2 - j1
        if tag == "replace":
            substitutions += min(left, right)
            deletions += max(0, left - right)
            insertions += max(0, right - left)
        elif tag == "delete":
            deletions += left
        elif tag == "insert":
            insertions += right
    return substitutions, deletions, insertions


def _overlaps(a: Cue, b: Cue) -> bool:
    return a.end > b.start and b.end > a.start


def score(
    reference: list[Cue],
    hypothesis: list[Cue],
    *,
    start: float | None = None,
    end: float | None = None,
    ref_lang: str = "ja",
    hyp_lang: str = "all",
) -> dict:
    refs = filter_time(filter_language(reference, ref_lang), start, end)
    hyps = filter_time(filter_language(hypothesis, hyp_lang), start, end)

    ref_text = normalize_text("".join(c.text for c in refs))
    hyp_text = normalize_text("".join(c.text for c in hyps))
    distance = levenshtein(ref_text, hyp_text)
    substitutions, deletions, insertions = edit_ops(ref_text, hyp_text)
    cer = distance / len(ref_text) if ref_text else 0.0

    block_scores: list[float] = []
    missed = 0
    for ref in refs:
        pieces = [normalize_text(h.text) for h in hyps if _overlaps(ref, h)]
        hyp_text_block = "".join(pieces)
        ref_text_block = normalize_text(ref.text)
        if not ref_text_block:
            continue
        block_distance = levenshtein(ref_text_block, hyp_text_block)
        accuracy = max(0.0, 1.0 - block_distance / len(ref_text_block))
        block_scores.append(accuracy)
        if accuracy < 0.35 and len(ref_text_block) >= 3:
            missed += 1

    durations = [max(0.0, c.end - c.start) for c in hyps]
    cps = [
        len(normalize_text(c.text)) / (c.end - c.start)
        for c in hyps
        if c.end > c.start
    ]

    particle_starts = 0
    aux_starts = 0
    for previous, current in zip(hyps, hyps[1:]):
        if current.start - previous.end > 0.05:
            continue
        first = normalize_text(current.text)[:1]
        if first in PARTICLE_STARTS:
            particle_starts += 1
        elif first in AUX_STARTS:
            aux_starts += 1

    return {
        "reference_cues": len(refs),
        "hypothesis_cues": len(hyps),
        "reference_chars": len(ref_text),
        "hypothesis_chars": len(hyp_text),
        "cer": round(cer, 6),
        "substitutions": substitutions,
        "deletions": deletions,
        "insertions": insertions,
        "block_accuracy": round(statistics.mean(block_scores), 6) if block_scores else 0.0,
        "missed_blocks": missed,
        "max_cue_dur": round(max(durations), 3) if durations else 0.0,
        "over_4_3s": sum(1 for d in durations if d > 4.3),
        "cps_median": round(statistics.median(cps), 3) if cps else 0.0,
        "cps_max": round(max(cps), 3) if cps else 0.0,
        "particle_start_cues": particle_starts,
        "aux_start_cues": aux_starts,
        "range": [start, end],
        "ref_lang": ref_lang,
    }


def _print_summary(result: dict, ref_path: Path, hyp_path: Path) -> None:
    rng = result["range"]
    rng_text = "全片" if rng == [None, None] else f"{rng[0]}s – {rng[1]}s"
    print(f"参考：{ref_path}")
    print(f"候选：{hyp_path}")
    print(f"区间：{rng_text} ｜ 参考语言：{result['ref_lang']}")
    print(
        f"条数：参考 {result['reference_cues']} / 候选 {result['hypothesis_cues']} ｜ "
        f"字符：参考 {result['reference_chars']} / 候选 {result['hypothesis_chars']}"
    )
    print(
        f"CER = {result['cer'] * 100:.2f}%  "
        f"(S={result['substitutions']} D={result['deletions']} I={result['insertions']})"
    )
    print(
        f"块均准确率 = {result['block_accuracy'] * 100:.1f}% ｜ "
        f"漏块(acc<35%, >=3字) = {result['missed_blocks']}"
    )
    print(
        f"候选切分：最长 {result['max_cue_dur']:.2f}s ｜ >4.3s {result['over_4_3s']} 条 ｜ "
        f"cps 中位 {result['cps_median']} / 最大 {result['cps_max']}"
    )
    print(
        f"可疑切分：下一条以助词开头 {result['particle_start_cues']} 次 ｜ "
        f"以活用尾开头 {result['aux_start_cues']} 次"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="KikuSub 字幕评测台（SRT CER / 块准确率）")
    parser.add_argument("--reference", required=True, type=Path, help="参考 SRT（可为中日双语）")
    parser.add_argument("--hypothesis", required=True, type=Path, help="待评测的 SRT")
    parser.add_argument("--from", dest="start", default=None, help="起始时间：HH:MM:SS 或秒")
    parser.add_argument("--to", dest="end", default=None, help="终止时间：HH:MM:SS 或秒")
    parser.add_argument("--ref-lang", default="ja", choices=["ja", "zh", "all"])
    parser.add_argument("--hyp-lang", default="all", choices=["ja", "zh", "all"])
    parser.add_argument("--json", dest="json_path", type=Path, default=None, help="把结果写入 JSON")
    args = parser.parse_args(argv)

    for path in (args.reference, args.hypothesis):
        if not path.is_file():
            print(f"错误：文件不存在：{path}", file=sys.stderr)
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

    reference = parse_srt(args.reference.read_text(encoding="utf-8-sig"))
    hypothesis = parse_srt(args.hypothesis.read_text(encoding="utf-8-sig"))
    result = score(
        reference,
        hypothesis,
        start=start,
        end=end,
        ref_lang=args.ref_lang,
        hyp_lang=args.hyp_lang,
    )
    result["reference_file"] = str(args.reference)
    result["hypothesis_file"] = str(args.hypothesis)
    _print_summary(result, args.reference, args.hypothesis)

    if args.json_path:
        args.json_path.parent.mkdir(parents=True, exist_ok=True)
        args.json_path.write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"JSON：{args.json_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
