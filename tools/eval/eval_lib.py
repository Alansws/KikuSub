"""客观评测库：把参考字幕与转录结果做字符级对齐，产出可量化指标。

设计要点
--------
1. 参考字幕是「双条目同时间轴」写法（日语行、中文行各一条，起止完全相同），
   按 (start, end) 归并后取含假名的那条为日语基准。
2. 参考字幕的单条时长 4-5s，比转录结果（2-3s）粗得多，因此**不做逐条一对一比较**，
   而是：
   - 全局字符级对齐（rapidfuzz 的 Levenshtein editops）算 CER；
   - 逐参考块取「时间重叠的转录条」拼接后算块级准确率（天然容忍 1→N 切分）；
   - 边界精度只统计「转录条 ↔ 参考块」的最近边界差，不与切分粒度耦合。
3. 删除/插入按时间聚类，输出「漏句候选」与「多余内容（幻觉）」。
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

KANA_RE = re.compile(r"[\u3040-\u30ff]")
# 归一化时保留的字符：假名、汉字、ASCII 字母数字
KEEP_RE = re.compile(r"[^\u3040-\u30ff\u4e00-\u9fffA-Za-z0-9]")
PUNCT_RE = re.compile(r"[\s\u3000。、，．.,!！?？…‥⋯・：:；;「」『』（）()\[\]【】~〜\-ー♪♬]")

CREDIT_MARKERS = ("字幕组", "kamigami", "翻译", "校对", "时间轴", "压制", "仅供交流")


def parse_srt(path_or_text: str, *, is_text: bool = False) -> list[dict]:
    raw = path_or_text if is_text else open(path_or_text, encoding="utf-8-sig").read()
    raw = raw.replace("\r\n", "\n").replace("\r", "\n")
    blocks = [b for b in re.split(r"\n\s*\n", raw.strip()) if b.strip()]
    out: list[dict] = []
    for b in blocks:
        lines = b.split("\n")
        tline = next((i for i, ln in enumerate(lines) if "-->" in ln), None)
        if tline is None:
            continue
        m = re.search(
            r"(\d+):(\d+):(\d+)[,.](\d+)\s*-->\s*(\d+):(\d+):(\d+)[,.](\d+)", lines[tline]
        )
        if not m:
            continue
        g = [int(x) for x in m.groups()]
        st = g[0] * 3600 + g[1] * 60 + g[2] + g[3] / 1000
        en = g[4] * 3600 + g[5] * 60 + g[6] + g[7] / 1000
        text = "\n".join(lines[tline + 1:]).strip()
        out.append({"start": st, "end": en, "text": text})
    return out


def load_reference(path: str) -> list[dict]:
    """参考双语 SRT → 日语单语块（按时间轴归并、去制作组信息）。"""
    cues = parse_srt(path)
    groups: dict[tuple[int, int], list[str]] = {}
    for c in cues:
        key = (round(c["start"] * 1000), round(c["end"] * 1000))
        groups.setdefault(key, []).append(c["text"])

    blocks: list[dict] = []
    for (st_ms, en_ms), texts in groups.items():
        if any(any(mk in t for mk in CREDIT_MARKERS) for t in texts):
            continue
        # 无假名的条目是画面文字/译者注/片尾卡（如「万葉集」「升学考试」「靴職人？」），
        # 不是台词，ASR 本来就不该出——留在基准里会把它算成"漏句"。
        jp = [t for t in texts if KANA_RE.search(t)]
        if not jp:
            continue
        pick = jp[0].replace("\n", " ")
        if not PUNCT_RE.sub("", pick):
            continue
        blocks.append({"start": st_ms / 1000, "end": en_ms / 1000, "text": pick})
    blocks.sort(key=lambda b: b["start"])
    return blocks


def normalize(text: str, *, fold_kana: bool = False, fold_numeral: bool = False) -> str:
    t = unicodedata.normalize("NFKC", text or "")
    if fold_kana:
        t = "".join(
            chr(ord(ch) - 0x60) if "\u30a1" <= ch <= "\u30f6" else ch for ch in t
        )
    if fold_numeral:
        t = re.sub(r"[0-9]+", "0", t)
    t = KEEP_RE.sub("", t)
    return t.lower() if t.isascii() else t


@dataclass
class CharRef:
    ch: str
    t: float  # 该字的时间（按条内字数均分）


def chars_with_time(cues: list[dict], fold_kana=False, fold_numeral=False) -> list[CharRef]:
    out: list[CharRef] = []
    for c in cues:
        txt = normalize(c["text"], fold_kana=fold_kana, fold_numeral=fold_numeral)
        if not txt:
            continue
        dur = max(0.0, c["end"] - c["start"])
        for i, ch in enumerate(txt):
            out.append(CharRef(ch, c["start"] + dur * (i + 0.5) / len(txt)))
    return out


@dataclass
class AlignResult:
    cer: float
    sub: int
    dele: int
    ins: int
    n_ref: int
    ops: list = field(default_factory=list)  # (tag, ref_idx, hyp_idx)


def align(ref: list[CharRef], hyp: list[CharRef]) -> AlignResult:
    from rapidfuzz.distance import Levenshtein

    a = "".join(c.ch for c in ref)
    b = "".join(c.ch for c in hyp)
    ops = Levenshtein.editops(a, b)
    sub = sum(1 for o in ops if o.tag == "replace")
    dele = sum(1 for o in ops if o.tag == "delete")
    ins = sum(1 for o in ops if o.tag == "insert")
    n = max(len(a), 1)
    return AlignResult((sub + dele + ins) / n, sub, dele, ins, len(a), ops)


def deletion_spans(ref: list[CharRef], res: AlignResult, *, gap_s=1.2, min_chars=2) -> list[dict]:
    """把连续删除聚类成「漏句候选」区间。"""
    idxs = [o.src_pos for o in res.ops if o.tag == "delete"]
    if not idxs:
        return []
    spans: list[dict] = []
    cur = [idxs[0]]
    for i in idxs[1:]:
        if ref[i].t - ref[cur[-1]].t <= gap_s and i - cur[-1] <= 12:
            cur.append(i)
        else:
            spans.append(cur)
            cur = [i]
    spans.append(cur)

    out = []
    for sp in spans:
        chars = "".join(ref[i].ch for i in sp)
        if len(sp) < min_chars:
            continue
        out.append({
            "start": ref[sp[0]].t,
            "end": ref[sp[-1]].t,
            "chars": len(sp),
            "text": chars,
        })
    return out


def insertion_spans(hyp: list[CharRef], res: AlignResult, *, gap_s=1.2, min_chars=2) -> list[dict]:
    idxs = [o.dest_pos for o in res.ops if o.tag == "insert"]
    if not idxs:
        return []
    spans: list[dict] = []
    cur = [idxs[0]]
    for i in idxs[1:]:
        if hyp[i].t - hyp[cur[-1]].t <= gap_s and i - cur[-1] <= 12:
            cur.append(i)
        else:
            spans.append(cur)
            cur = [i]
    spans.append(cur)
    out = []
    for sp in spans:
        chars = "".join(hyp[i].ch for i in sp)
        if len(sp) < min_chars:
            continue
        out.append({"start": hyp[sp[0]].t, "end": hyp[sp[-1]].t, "chars": len(sp), "text": chars})
    return out


def overlap(a0, a1, b0, b1) -> float:
    return max(0.0, min(a1, b1) - max(a0, b0))


def block_accuracy(ref_blocks: list[dict], hyp_cues: list[dict], ops) -> list[dict]:
    """块级准确率 = 该参考块内**逐字对齐后完全命中**的字数占比。

    用全局对齐的 ops 反推（而不是按时间窗取转录条再算编辑距离）：
    时间窗取法会把相邻条目的文字一并算进去，长度一超就把整块判成 0。
    """
    deleted = {o.src_pos for o in ops if o.tag == "delete"}
    replaced = {o.src_pos for o in ops if o.tag == "replace"}
    out: list[dict] = []
    pos = 0
    for b in ref_blocks:
        n = len(normalize(b["text"]))
        if n == 0:
            continue
        hit = sum(1 for i in range(pos, pos + n) if i not in deleted and i not in replaced)
        out.append({
            "start": b["start"], "end": b["end"], "ref": b["text"],
            "acc": hit / n, "matched": hit, "chars": n,
        })
        pos += n
    return out


def evaluate(ref_blocks: list[dict], hyp_cues: list[dict], *, fold_kana=False, fold_numeral=False) -> dict:
    R = chars_with_time(ref_blocks, fold_kana=fold_kana, fold_numeral=fold_numeral)
    H = chars_with_time(hyp_cues, fold_kana=fold_kana, fold_numeral=fold_numeral)
    res = align(R, H)
    ba = block_accuracy(ref_blocks, hyp_cues, res.ops)
    accs = sorted(b["acc"] for b in ba)
    n = len(accs)
    def frac(th):
        return sum(1 for a in accs if a >= th) / n if n else 0.0
    return {
        "res": res, "R": R, "H": H, "blocks": ba,
        "cer": res.cer, "sub": res.sub, "del": res.dele, "ins": res.ins,
        "n_ref_chars": res.n_ref,
        "acc_mean": sum(accs) / n if n else 0.0,
        "acc_median": accs[n // 2] if n else 0.0,
        "p95": frac(0.95), "p90": frac(0.90), "p80": frac(0.80), "p50": frac(0.50),
        "miss_blocks": [b for b in ba if b["acc"] < 0.35 and b["chars"] >= 3],
        "del_spans": deletion_spans(R, res),
        "ins_spans": insertion_spans(H, res),
        "boundary": boundary_stats(ref_blocks, hyp_cues),
        "cps": cps_stats(hyp_cues),
    }


def region_slice(blocks: list[dict], t0: float, t1: float) -> list[dict]:
    return [b for b in blocks if b["end"] > t0 and b["start"] < t1]


def summary_line(tag: str, ev: dict) -> str:
    return (
        f"{tag}: CER={ev['cer']*100:5.2f}% (sub {ev['sub']}/del {ev['del']}/ins {ev['ins']}) "
        f"块均准确率={ev['acc_mean']*100:5.1f}% 完全对={ev['p95']*100:4.1f}% "
        f"漏块={len(ev['miss_blocks'])}"
    )



def boundary_stats(ref_blocks: list[dict], hyp_cues: list[dict], tol=2.5) -> dict:
    """转录条边界 → 最近参考边界的偏差。"""
    edges = sorted({round(b["start"], 3) for b in ref_blocks} | {round(b["end"], 3) for b in ref_blocks})
    ds, de = [], []
    matched = 0
    for h in hyp_cues:
        for val, bucket in ((h["start"], ds), (h["end"], de)):
            near = min(edges, key=lambda e: abs(e - val)) if edges else None
            if near is None:
                continue
            d = val - near
            if abs(d) <= tol:
                bucket.append(abs(d))
                matched += 1
    def q(v, p):
        if not v:
            return None
        v = sorted(v)
        return v[min(len(v) - 1, int(p * (len(v) - 1) + 0.5))]
    return {
        "start_median": q(ds, 0.5), "start_p90": q(ds, 0.9),
        "end_median": q(de, 0.5), "end_p90": q(de, 0.9),
        "within_0.5s": sum(1 for x in ds + de if x <= 0.5),
        "n_edges": len(ds) + len(de),
    }


def cps_stats(hyp_cues: list[dict]) -> dict:
    vals = []
    for h in hyp_cues:
        txt = normalize(h["text"])
        dur = h["end"] - h["start"]
        if dur > 0 and txt:
            vals.append((len(txt) / dur, dur, len(txt), h["text"]))
    if not vals:
        return {}
    cps = sorted(v[0] for v in vals)
    durs = sorted(v[1] for v in vals)
    worst = sorted(vals, key=lambda v: -v[0])[:5]
    return {
        "cps_median": cps[len(cps) // 2],
        "cps_p95": cps[int(0.95 * (len(cps) - 1))],
        "cps_max": cps[-1],
        "dur_min": durs[0],
        "dur_median": durs[len(durs) // 2],
        "dur_max": durs[-1],
        "over_10cps": sum(1 for v in vals if v[0] > 10),
        "under_0.5s": sum(1 for v in vals if v[1] < 0.5),
        "worst": worst,
    }


def fmt_t(sec: float) -> str:
    sec = max(0.0, sec)
    return f"{int(sec // 60):02d}:{sec % 60:06.3f}"
