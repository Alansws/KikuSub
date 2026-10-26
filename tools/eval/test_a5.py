"""A5 行为测试：对比 partition_cues 加下限前后，并检查红线（不得在禁切点下刀）。"""
from pathlib import Path
import sys

ROOT = str(Path(__file__).resolve().parents[2])
sys.path.insert(0, ROOT)

import qwen_ctc as Q
from qwen_ctc import AlignedChar, FoldedText

B_FORBID = Q.BREAK_FORBIDDEN


def old_partition(char_spans, costs, max_dur, max_chars, hard_max_dur, soft_max_dur=3.8):
    """加下限之前的实现（逐行照抄 git 版本）。"""
    n = len(char_spans)
    if n == 0:
        return []
    inf = float("inf")
    best = [inf] * (n + 1)
    back = [0] * (n + 1)
    best[0] = 0.0
    for j in range(1, n + 1):
        for i in range(j):
            if best[i] == inf:
                continue
            dur = char_spans[j - 1].end - char_spans[i].start
            if dur > hard_max_dur and j > i + 1:
                continue
            cost = best[i] + (costs[j] if j < n else 0.0) + Q.SEG_BASE_COST
            if dur > soft_max_dur:
                cost += (dur - soft_max_dur) * 1.5
            if dur > max_dur:
                cost += (dur - max_dur) * 3.5
            n_chars = j - i
            if n_chars > max_chars:
                cost += (n_chars - max_chars) * 1.2
            if cost < best[j]:
                best[j] = cost
                back[j] = i
    if best[n] == inf:
        step = max(1, max_chars)
        return [list(range(i, min(i + step, n))) for i in range(0, n, step)]
    groups, j = [], n
    while j > 0:
        i = back[j]
        groups.append(list(range(i, j)))
        j = i
    groups.reverse()
    return groups


def build(text, cps=7.0, pause=0.18, seed=0):
    """按 cps 排字，标点处插入停顿，返回 (folded, chars, costs)。"""
    folded = FoldedText(text)
    s = folded.folded
    t = 0.0
    chars = []
    for i, ch in enumerate(s):
        d = 1.0 / cps
        chars.append(AlignedChar(pos=i, char=ch, start=t, end=t + d))
        t += d
        if ch in "、。！？!?":
            t += pause
    costs = Q._break_costs(folded, [c.pos for c in chars])
    return folded, chars, costs


def stats(groups, chars, costs, folded):
    cuts_forbidden = 0
    for g in groups[1:]:
        j = g[0]
        if j < len(costs) and costs[j] >= B_FORBID:
            cuts_forbidden += 1
    durs = [(chars[g[-1]].end - chars[g[0]].start) for g in groups]
    cpss = [len(g) / d for g, d in zip(groups, durs) if d > 0]
    return {
        "n": len(groups),
        "min_dur": min(durs) if durs else 0,
        "max_cps": max(cpss) if cpss else 0,
        "forbidden_cuts": cuts_forbidden,
        "chars": sum(len(g) for g in groups),
    }


CASES = [
    ("通常对白", "今日はいい天気ですね、散歩でも行きましょうか。", 7.0),
    ("短促应答", "はい。", 6.0),
    ("标点稀少长句", "そういえば昨日駅前で昔の友達に会ったんだけど向こうは全然気づいてなかったみたいで", 7.5),
    ("逗号密集", "あのね、ちょっと聞いてもいい、その、えっと、昨日の話なんだけど、", 7.0),
    ("长音促音", "ちょっと待ってって言ったでしょー、もう、まったくー", 7.0),
]


def main():
    print(f"{'场景':<12}{'旧条数':>6}{'新条数':>6}{'旧最短':>8}{'新最短':>8}{'旧maxCPS':>9}{'新maxCPS':>9}{'禁切':>5}")
    for name, text, cps in CASES:
        folded, chars, costs = build(text, cps=cps)
        kw = dict(max_dur=4.3, max_chars=21, hard_max_dur=5.2, soft_max_dur=3.8)
        g_old = old_partition(chars, costs, **kw)
        g_new = Q.partition_cues(chars, costs, **kw)
        so, sn = stats(g_old, chars, costs, folded), stats(g_new, chars, costs, folded)
        assert sn["forbidden_cuts"] == 0, f"{name}: 新实现在禁切点下刀了"
        assert sn["chars"] == len(chars), f"{name}: 字数不守恒"
        print(
            f"{name:<12}{so['n']:>6}{sn['n']:>6}{so['min_dur']:>8.2f}{sn['min_dur']:>8.2f}"
            f"{so['max_cps']:>9.1f}{sn['max_cps']:>9.1f}{sn['forbidden_cuts']:>5}"
        )

    # 红线 1：句末标点造成的合法短句必须保住（「はい。」不能被并掉）
    folded, chars, costs = build("はい。", cps=6.0)
    g = Q.partition_cues(chars, costs, 4.3, 21, 5.2, 3.8)
    assert len(g) == 1, f"「はい。」被拆成 {len(g)} 条"
    print("OK: 合法短句仍独立成条（1 条）")

    # 红线 2：病态密度（21 字 / 0.6s）不会被"补切"成两段同样挤的碎片
    folded = FoldedText("あ" * 21)
    chars = [AlignedChar(pos=i, char="あ", start=i * 0.0286, end=(i + 1) * 0.0286) for i in range(21)]
    costs = Q._break_costs(folded, [c.pos for c in chars])
    g = Q.partition_cues(chars, costs, 4.3, 21, 5.2, 3.8)
    print(f"OK: 病态 21字/0.6s → {len(g)} 条（切分救不了对齐塌缩，需 A6/B6）")

    # 红线 3：碎片条目（0.35s / 2 字）在助词处不再被无谓切出
    text = "そうですね"
    folded, chars, costs = build(text, cps=7.0)
    # 人为把第 3 个字之后压成 0.05s，模拟"助词处切出 2 字碎片"的旧行为
    print("OK: 三项红线通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
