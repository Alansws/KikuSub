"""P4 截断判据 + 重跑闸门的单元测试（不加载模型）。"""
from pathlib import Path
import sys

ROOT = str(Path(__file__).resolve().parents[2])
sys.path.insert(0, ROOT)

from qwen_ctc import CHARS_PER_TOKEN_FLOOR, TOKENS_HEADROOM, TOKENS_PER_SEC, classify_capped

fails = []


def check(name, got, want):
    ok = got == want
    print(f"{'✓' if ok else '✗'} {name}: {got}" + ("" if ok else f"  期望 {want}"))
    if not ok:
        fails.append(name)


# —— 1. 未吃满上限：永远不算截断（正常段由 EOS 提前结束）——
check("正常段 43/224", classify_capped(48, 43, 224), (False, False))
check("空段 0/64", classify_capped(0, 0, 64), (False, False))
check("恰好吃满前一个 token", classify_capped(48, 223, 224), (False, False))

# —— 2. 真截断：吃满 + 密度正常（探针实测正常段密度 1.12）——
check("真截断 120 字 / 224 token", classify_capped(120, 224, 224), (True, True))
check("真截断 密度恰在阈值上", classify_capped(int(CHARS_PER_TOKEN_FLOOR * 100), 100, 100), (True, True))

# —— 3. 复读：吃满但密度极低（探针实测 3 字 / 212 token = 0.014）——
check("复读 3 字 / 212 token", classify_capped(3, 212, 212), (True, False))
check("空转 1 字 / 212 token", classify_capped(1, 212, 212), (True, False))
check("复读 密度恰低于阈值", classify_capped(int(CHARS_PER_TOKEN_FLOOR * 100) - 1, 100, 100), (True, False))

# —— 4. cap=0 之类退化输入不炸 ——
check("n_gen=0 cap=0", classify_capped(0, 0, 0), (True, False))

# —— 5. 上限公式：min(440, max(64, dur*12+32)) ——
def cap_of(dur, cfg_max=440):
    return min(cfg_max, max(64, int(dur * TOKENS_PER_SEC) + TOKENS_HEADROOM))


check("1s 段走 64 地板", cap_of(1.0), 64)
check("4s 段 4*12+32", cap_of(4.0), 80)
check("15s 段 15*12+32", cap_of(15.0), 212)
check("16s 段封顶 224", cap_of(16.0), 224)
check("30s 段 30*12+32", cap_of(30.0), 392)
check("60s 段被 cfg 440 封顶", cap_of(60.0), 440)

print()
if fails:
    print(f"FAILED {len(fails)}: {fails}")
    sys.exit(1)
print("ALL PASS")
