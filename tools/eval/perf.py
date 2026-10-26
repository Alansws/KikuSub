"""性能类优化实测：P1 解码缓存 / P6 波形落盘 / P7 禁切点预计算。

产物：outputs/eval/perf.json
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import soundfile as sf

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import audio_cache as AC  # noqa: E402
import transcribe as T  # noqa: E402

MKV = ROOT / "测试用_言叶之庭.mkv"
out: dict = {}


def timeit(fn, n=1):
    ts = []
    for _ in range(n):
        t = time.perf_counter()
        r = fn()
        ts.append(time.perf_counter() - t)
    return (min(ts), r)


# ---------------- P1 解码缓存 ----------------
wav = AC.wav_path(MKV, loudnorm=False)
print("缓存文件:", wav.name, wav.exists(), f"{wav.stat().st_size/1e6:.0f}MB" if wav.exists() else "")
backup = wav.with_suffix(".wav.bak")
if wav.exists():
    os.replace(wav, backup)
try:
    cold, p = timeit(lambda: AC.ensure_wav(MKV, loudnorm=False, extractor=T.decode_wav_16k))
    print(f"P1 冷启动解码 {cold*1000:.0f}ms → {p.name}")
finally:
    if backup.exists():
        os.replace(backup, wav)   # 还原，避免污染
warm, p2 = timeit(lambda: AC.ensure_wav(MKV, loudnorm=False, extractor=T.decode_wav_16k), n=20)
print(f"P1 缓存命中 {warm*1000:.2f}ms")

# 缓存 wav 与现场解码是否逐样本一致
tmp = Path("/tmp/_p1_check.wav")
T.decode_wav_16k(MKV, tmp, enable_loudnorm=False)
a, _ = sf.read(str(wav), dtype="int16")
b, _ = sf.read(str(tmp), dtype="int16")
same = a.shape == b.shape and bool(np.array_equal(a, b))
print(f"P1 缓存 wav 与现场解码逐样本一致: {same} ({a.shape[0]} samples)")
tmp.unlink(missing_ok=True)

# 核对台波形：旧路径（ffmpeg 直读 1kHz） vs 新路径（缓存 16k）
def old_peaks():
    proc = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(MKV), "-map", "0:a:0?", "-ac", "1", "-ar", "1000", "-f", "f32le", "pipe:1"],
        capture_output=True, timeout=300)
    s = np.frombuffer(proc.stdout, dtype=np.float32)
    bins = max(2400, min(8000, int((len(s) / 1000) * 4)))
    edges = np.linspace(0, len(s), bins + 1, dtype=int)
    peaks = [float(np.max(np.abs(s[edges[i]:edges[i + 1]]))) if edges[i] < edges[i + 1] else 0.0 for i in range(bins)]
    m = max(peaks, default=0.0)
    return [round(min(1.0, v / m), 2) if m else 0.0 for v in peaks]


def new_peaks():
    w = AC.ensure_wav(MKV, loudnorm=False)
    return AC.peaks(w, max(2400, min(8000, int(2751.8 * 4))))[1]


t_old, pk_old = timeit(old_peaks)
t_new, pk_new = timeit(new_peaks)
n = min(len(pk_old), len(pk_new))
corr = float(np.corrcoef(pk_old[:n], pk_new[:n])[0, 1]) if n else 0.0
print(f"P1 波形：旧 ffmpeg 直读 {t_old*1000:.0f}ms / 新缓存 {t_new*1000:.0f}ms  相关系数 {corr:.4f}")

# KIKUSUB_AUDIO_CACHE=0 行为
os.environ["KIKUSUB_AUDIO_CACHE"] = "0"
t_off, path_off = timeit(lambda: T.extract_audio_16k(MKV, "/tmp/_p1_off.wav", enable_loudnorm=False))
os.environ.pop("KIKUSUB_AUDIO_CACHE")
print(f"P1 关闭缓存时现场解码 {t_off*1000:.0f}ms（每次转写都要付）")
Path("/tmp/_p1_off.wav").unlink(missing_ok=True)

out["P1"] = {
    "cold_ms": round(cold * 1000, 1), "warm_ms": round(warm * 1000, 2),
    "cold_over_warm": round(cold / max(warm, 1e-6), 1),
    "wav_identical": same, "samples": int(a.shape[0]),
    "peaks_old_ms": round(t_old * 1000), "peaks_new_ms": round(t_new * 1000),
    "peaks_corr": round(corr, 4),
    "cache_off_ms": round(t_off * 1000, 1),
}

# ---------------- P6 波形落盘缓存 ----------------
import app  # noqa: E402  重量级，但只需函数

app.MEDIA_PEAKS_CACHE.clear()
t_disk0, _ = timeit(lambda: app._media_duration_and_peaks(MKV))
app.MEDIA_PEAKS_CACHE.clear()
t_disk1, _ = timeit(lambda: app._media_duration_and_peaks(MKV))
t_mem, _ = timeit(lambda: app._media_duration_and_peaks(MKV))
print(f"P6 波形：进程内无缓存 {t_disk0*1000:.0f}ms / 清内存后走磁盘缓存 {t_disk1*1000:.0f}ms / 内存命中 {t_mem*1000:.3f}ms")
out["P6"] = {"no_cache_ms": round(t_disk0 * 1000), "disk_ms": round(t_disk1 * 1000),
             "mem_ms": round(t_mem * 1000, 3)}

# ---------------- P7 禁切点预计算 ----------------
texts = [
    "そうやって俺はいつも逃げてばかりいるんだろうなって思ってたけど実際そうだったし",
    "ありがとうございますそれではまた明日お会いしましょうということでよろしくお願いします",
    "ちょっと待ってよお兄ちゃんそんなこと言われても困るんだけどどうしたらいいのかな",
] * 20


def precomputed():
    for t in texts:
        T.forbidden_cut_positions(t)


def naive():
    """旧写法：每个候选切点都重扫一遍全文本。"""
    for t in texts:
        n = len(t)
        for p in range(1, n):
            T.forbidden_cut_positions(t)[p]


t_pre, _ = timeit(precomputed, n=20)
t_nai, _ = timeit(naive, n=3)
print(f"P7 禁切表：预计算 {t_pre*1000:.1f}ms / 逐点重扫 {t_nai*1000:.0f}ms  ({(t_nai/t_pre):.0f}×)")
out["P7"] = {"precompute_ms": round(t_pre * 1000, 2), "naive_ms": round(t_nai * 1000),
             "speedup": round(t_nai / t_pre, 1), "texts": len(texts)}

json.dump(out, open(ROOT / "outputs/eval/perf.json", "w"), ensure_ascii=False, indent=1)
print("\n→ outputs/eval/perf.json")
