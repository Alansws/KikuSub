"""D6 单句超长切分的断言（不加载模型）。

覆盖三条红线：
1. 文本守恒：拆出来的文本拼回去必须等于原文，一个字都不能丢；
2. 不按时间对半：切点时间必须来自「文本切点 × 字级时间戳」或「字符比例 + 能量谷」；
3. 禁则不破：切点不得落在小假名 / 长音符 / 汉字连写 / 词内。

运行：python tools/eval/test_d6.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

ROOT = str(Path(__file__).resolve().parents[2])
sys.path.insert(0, ROOT)

from transcribe import (  # noqa: E402
    _split_overlong_single,
    forbidden_cut_positions,
    nearest_text_cut,
    split_text_into_cues,
)

fails: list[str] = []


def check(ok: bool, msg: str) -> None:
    print(f"{'✅' if ok else '❌'} {msg}")
    if not ok:
        fails.append(msg)


def cues(text, dur, start=0.0, **kw):
    return split_text_into_cues(text, start, start + dur, 4.2, 20, **kw)


# ---------------- 1. 有标点：切在标点后 ----------------
c = cues("…この人は、いかにも優しそうに話す", 5.11)
check(len(c) == 2, f"5.11s 长句被拆成 2 条（实际 {len(c)}）")
check("".join(x.text for x in c) == "…この人は、いかにも優しそうに話す", "文本守恒")
check(c[0].text.endswith("、"), f"第一条切在「、」后：{c[0].text!r}")
check(abs(c[0].start - 0.0) < 1e-6 and abs(c[-1].end - 5.11) < 1e-6, "首尾时间贴合原段")
check(all(x.end - x.start >= 0.45 for x in c), "每条时长 ≥0.45s")
check(c[0].end == c[1].start, "两条时间首尾相接，无重叠/空洞")

# ---------------- 2. 无标点：切在助词后 ----------------
c = cues("小さめの傘も差さずに歩いた", 5.0)
check(len(c) >= 2, "无标点长句也能拆（靠助词）")
check("".join(x.text for x in c) == "小さめの傘も差さずに歩いた", "文本守恒")
check(any(x.text.endswith(("の", "も", "に")) for x in c[:-1]),
      f"切点在助词后：{[x.text for x in c]}")

# ---------------- 3. 禁则不破 ----------------
text = "ちょっと待ってください"
blocked = forbidden_cut_positions(text)
cut = nearest_text_cut(text, 4)
check(cut > 0, f"能找到切点：{text[:cut]!r} | {text[cut:]!r}")
check(not blocked[cut], "切点不在禁切位置")

# 全汉字连写（无标点无助词）→ 找不到合法切点 → 不切
c = cues("新宿到着", 5.0)
check(len(c) == 1, "无合法切点时保持单条，不硬切")

# ---------------- 4. 短句不动 ----------------
c = cues("はい。", 1.2)
check(len(c) == 1, "1.2s 短句不拆")

# ---------------- 5. 字级时间戳优先 ----------------
# 8 个字，第 4 个字结束于 1.30s；按字符比例应是 4/8*5=2.5s，二者不同以便区分
ct = [(i * 0.3, i * 0.3 + 0.3) for i in range(8)]
c = cues("あいうえおかきく", 5.0, char_times=ct)
check(len(c) == 2, "字级时间戳路径也拆成 2 条")
check(abs(c[0].end - ct[c[0].text.__len__() - 1][1]) < 1e-6,
      f"切点时间取自字级时间戳（{c[0].end:.2f}s）")

# ---------------- 6. 能量谷吸附 ----------------
sr = 16000
dur = 5.0
audio = np.random.RandomState(0).normal(0, 0.05, int(sr * dur)).astype(np.float32)
# 在 2.9–3.1s 挖一个静音谷（字符比例算出的位置是 2.5s，能量谷在 3.0s）
audio[int(2.9 * sr):int(3.1 * sr)] *= 0.01
pieces = _split_overlong_single("あいうえおかきく", 0.0, dur, 4.2, audio=audio, sample_rate=sr)
check(len(pieces) == 2, "能量谷路径拆成 2 条")
cut_t = pieces[0][1]
check(abs(cut_t - 3.0) < 0.25, f"切点吸附到能量谷附近（{cut_t:.2f}s，比例位置 2.50s）")
check(cut_t != 2.5, "没有退化成按时间/字符对半")

# ---------------- 7. 递归：超长 3 倍上限 ----------------
c = cues("あいうえおかきくけこさしすせそたちつてと", 12.0)
check(all(x.end - x.start <= 4.2 for x in c), f"全部 ≤4.2s：{[round(x.end-x.start,2) for x in c]}")
check("".join(x.text for x in c) == "あいうえおかきくけこさしすせそたちつてと", "文本守恒（多刀）")

print()
print(f"{'全部通过' if not fails else f'{len(fails)} 项失败'}")
raise SystemExit(1 if fails else 0)
