"""实现验证：报告渲染 / 峰值缓存落盘 / 原子写 / 劈词缝合闸门 / P4 截断标记 / E5 漏句降噪。"""
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = str(Path(__file__).resolve().parents[2])
sys.path.insert(0, ROOT)

import app
import audio_cache
from qwen_ctc import QwenCtcConfig
from transcribe import SubtitleCue, WhisperVadConfig

ok = 0


def check(cond, msg):
    global ok
    assert cond, msg
    ok += 1


# ---------------------------------------------------------------- A6 报告渲染
def test_report():
    cfg = QwenCtcConfig()
    stats = {
        "enabled": True, "segments": 120, "aligned": 118, "noop": 0, "degraded": 1,
        "empty": 1, "align_chars": 1842, "interp_chars": 7, "truncated": 1,
        "capped_repeat": 3,
        "spans": [
            {"start": 83.4, "end": 89.1, "dur": 5.7, "reason": "too-few-frames(312<340)", "chars": 48},
            {"start": 724.8, "end": 731.2, "dur": 6.4, "reason": "no-spans", "chars": 53},
        ],
    }
    txt = app.build_transcription_report(
        media_name="a.mkv", out_filename="a.srt", out_path="/tmp/a.srt",
        engine_name="Qwen3-ASR + 逐字对齐（jaykwok）", output_format="SRT",
        elapsed_time=12.0, cue_count=100, char_count=1800, is_qwen=True,
        config=cfg, align_stats=stats,
    )
    check("【逐字对齐】" in txt, "报告缺少【逐字对齐】小节")
    check("118 段完成（98.3%）" in txt, f"成功率不对：{[ln for ln in txt.splitlines() if '逐字对齐' in ln]}")
    check("降级 1 段" in txt, "降级段数缺失")
    check("空结果 1 段" in txt, "空结果桶缺失")
    check("复读吃满上限 3 段" in txt, "复读计数缺失")
    check(118 + 0 + 1 + 1 == 120, "四桶不守恒（测试数据自检）")
    check("字级插值 7/1842 字（0.4%）" in txt, "插值率缺失")
    check("生成截断 1 段" in txt, "截断计数缺失")
    check("too-few-frames(312<340)  48 字" in txt, "降级清单缺 reason/字数")
    check(txt.index("【切分点吸附】") < txt.index("【逐字对齐】"), "小节顺序不对")

    # Whisper：不能让人误以为也有 40ms 精度
    txt_w = app.build_transcription_report(
        media_name="a.mkv", out_filename="a.srt", out_path="/tmp/a.srt",
        engine_name="Anime Whisper（litagin）", output_format="SRT",
        elapsed_time=12.0, cue_count=100, char_count=1800, is_qwen=False,
        config=WhisperVadConfig(), align_stats={},
    )
    check("该引擎无逐字对齐，句内时间按字数比例分配" in txt_w, "Whisper 报告措辞不对")

    # 停用对齐：不能报成 0/120 降级（会被读成故障）
    txt_off = app.build_transcription_report(
        media_name="a.mkv", out_filename="a.srt", out_path="/tmp/a.srt",
        engine_name="Qwen3-ASR + 逐字对齐（jaykwok）", output_format="SRT",
        elapsed_time=12.0, cue_count=100, char_count=1800, is_qwen=True,
        config=cfg, use_alignment=False,
        align_stats={"enabled": False, "segments": 120, "aligned": 0, "noop": 0, "degraded": 0},
    )
    check("逐字对齐已停用" in txt_off, "停用态措辞不对")

    # 中断：统计口径要标清楚
    txt_int = app.build_transcription_report(
        media_name="a.mkv", out_filename="a.srt", out_path="/tmp/a.srt",
        engine_name="Qwen3-ASR + 逐字对齐（jaykwok）", output_format="SRT",
        elapsed_time=12.0, cue_count=40, char_count=600, is_qwen=True,
        config=cfg, is_interrupted=True, align_stats=stats,
    )
    check("（统计截至中断处）" in txt_int, "中断任务未标注统计范围")

    # 无降级时明确写"无降级段"
    txt_clean = app.build_transcription_report(
        media_name="a.mkv", out_filename="a.srt", out_path="/tmp/a.srt",
        engine_name="Qwen3-ASR + 逐字对齐（jaykwok）", output_format="SRT",
        elapsed_time=12.0, cue_count=100, char_count=1800, is_qwen=True,
        config=cfg,
        align_stats={"enabled": True, "segments": 10, "aligned": 10, "noop": 0,
                     "degraded": 0, "align_chars": 100, "interp_chars": 0, "spans": []},
    )
    check("• 无降级段" in txt_clean, "零降级时未给明确结论")
    print("  A6 报告：10 项通过")


# ---------------------------------------------------------------- 问题 13 原子写
def test_atomic_write():
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "sub" / "a.srt"
        app.write_text_atomic(p, "1\n00:00:01,000 --> 00:00:02,000\nテスト\n")
        check(p.read_text(encoding="utf-8").startswith("1\n"), "原子写内容不对")
        check(not any(f.name.endswith(".tmp") for f in p.parent.iterdir()), "残留临时文件")

        # 覆盖写：内容必须整体替换，不能出现新旧混杂
        app.write_text_atomic(p, "2\n")
        check(p.read_text(encoding="utf-8") == "2\n", "覆盖写不干净")
        check(len(list(p.parent.iterdir())) == 1, "目录里多出文件")

        # 写入失败时不能破坏原文件（传非字符串，让 fh.write 抛 TypeError）
        try:
            app.write_text_atomic(p, 12345)
        except Exception:
            pass
        check(p.read_text(encoding="utf-8") == "2\n", "失败写破坏了原文件")
    print("  Q13 原子写：4 项通过")


# ---------------------------------------------------------------- P6 峰值缓存
def test_peaks_cache(tmp_media: Path):
    # 冷启动
    app.MEDIA_PEAKS_CACHE.clear()
    for f in app.PEAKS_CACHE_DIR.glob("*.npz"):
        f.unlink()
    d1, p1 = app._media_duration_and_peaks(tmp_media)
    check(len(p1) > 0, "波形为空")
    key = app._peaks_cache_key(tmp_media)
    npz = app.PEAKS_CACHE_DIR / f"{key}.npz"
    check(npz.exists(), "npz 未落盘")
    check(d1 > 0, "时长探测失败")

    # 清内存 → 必须从磁盘命中（把计算函数打成炸弹，证明没走计算）
    app.MEDIA_PEAKS_CACHE.clear()
    real = audio_cache.peaks
    audio_cache.peaks = lambda *a, **k: (_ for _ in ()).throw(AssertionError("不应重算"))
    try:
        d2, p2 = app._media_duration_and_peaks(tmp_media)
    finally:
        audio_cache.peaks = real
    check(d1 == d2 and p1 == p2, "磁盘缓存与首次结果不一致")

    # 命中要刷新 LRU 序位（真 LRU，而不是 FIFO）
    app.MEDIA_PEAKS_CACHE.clear()
    for i in range(app.MEDIA_PEAKS_CACHE_LIMIT):
        app._remember_peaks(f"k{i}", (0.0, []))
    app._remember_peaks("k0", (0.0, []))      # k0 命中 → 移到末尾
    app._remember_peaks("new", (0.0, []))     # 挤掉最旧的 k1
    check("k0" in app.MEDIA_PEAKS_CACHE and "k1" not in app.MEDIA_PEAKS_CACHE, "LRU 未按命中刷新")

    # 损坏的 npz 必须被当作未命中并清理，不能抛错
    npz.write_bytes(b"not a npz")
    app.MEDIA_PEAKS_CACHE.clear()
    d3, p3 = app._media_duration_and_peaks(tmp_media)
    check(len(p3) > 0, "损坏缓存未降级重算")

    # bins 变化时不复用旧分辨率
    check(app._load_peaks_from_disk(key, 99999) is None, "bins 不匹配仍命中")
    print("  P6 峰值缓存：6 项通过")


# ---------------------------------------------------------------- 问题 6 缝合闸门
def test_heal_gap():
    from qwen_ctc import _heal_broken_cues

    # 首尾相接：判为同一个词被劈开 → 合并（汉字接汉字）
    tight = [SubtitleCue(0.0, 1.0, "今日"), SubtitleCue(1.0, 2.5, "東京に行く")]
    check(len(_heal_broken_cues(tight)) == 1, "无间隙时应合并")

    # 中间有真实停顿：两句独立台词 → 不合并（旧实现会错并）
    loose = [SubtitleCue(0.0, 1.0, "今日"), SubtitleCue(1.8, 3.3, "東京に行く")]
    merged = _heal_broken_cues(loose)
    check(len(merged) == 2, f"有停顿仍被合并：{[c.text for c in merged]}")
    check(merged[0].text == "今日" and merged[1].text == "東京に行く", "文本被改坏")

    # 重叠（间隙为负）仍要合并（ありま + せん → ありません）
    overlap = [SubtitleCue(0.0, 1.2, "ありま"), SubtitleCue(1.0, 2.0, "せん")]
    check(len(_heal_broken_cues(overlap)) == 1, "重叠时应合并")

    # 小假名开头（明确劈词）在有间隙时也不合并
    sm = [SubtitleCue(0.0, 1.0, "ありがと"), SubtitleCue(1.6, 2.4, "う")]
    check(len(_heal_broken_cues(sm)) == 2, "有停顿的小假名续接被误并")
    print("  Q6 缝合闸门：4 项通过")


# ---------------------------------------------------------------- P4 上限自适应
def test_p4_cap():
    import qwen_ctc as Q

    cfg = QwenCtcConfig()
    seen = {}

    class FakeProc:
        def apply_transcription_request(self, audio, sampling_rate, language):
            return {"input_ids": type("T", (), {"shape": (1, 5)})(), "x": 1}

    class FakeModel:
        def generate(self, **kw):
            seen["cap"] = kw["max_new_tokens"]
            import numpy as np
            n = min(kw["max_new_tokens"], 3)
            return np.zeros((1, 5 + n), dtype=int)

    class FakeIds(dict):
        def to(self, **kw):
            return self

    class Proc:
        def apply_transcription_request(self, audio, sampling_rate, language):
            return FakeIds(input_ids=type("T", (), {"shape": (1, 5)})())

        def decode(self, generated, return_format=None):
            return ["テスト"]

    eng = Q.QwenCtcEngine.__new__(Q.QwenCtcEngine)
    eng.config = cfg
    eng.device = "cpu"
    eng._dtype = None
    eng._processor = Proc()
    eng._model = FakeModel()
    eng._last_truncated = False
    eng._last_capped = False

    import numpy as np
    eng._transcribe(np.zeros(16000 * 16, dtype=np.float32))   # 16s
    check(seen["cap"] == 16 * Q.TOKENS_PER_SEC + Q.TOKENS_HEADROOM, f"16s cap 不对：{seen['cap']}")
    check(seen["cap"] < 440, "16s 段未收紧上限")

    eng._transcribe(np.zeros(int(16000 * 4.0), dtype=np.float32))   # 4s
    check(seen["cap"] == 4 * Q.TOKENS_PER_SEC + Q.TOKENS_HEADROOM, f"4s cap 不对：{seen['cap']}")

    eng._transcribe(np.zeros(int(16000 * 0.2), dtype=np.float32))   # 0.2s → 下限 64
    check(seen["cap"] == 64, f"极短段未触发 64 下限：{seen['cap']}")

    # 截断检测：撞上限 + 密度正常 = 真截断；撞上限 + 密度塌陷 = 复读，不算截断
    class LongModel(FakeModel):
        def generate(self, **kw):
            seen["cap"] = kw["max_new_tokens"]
            import numpy as np
            return np.zeros((1, 5 + kw["max_new_tokens"]), dtype=int)

    class ProcDense(Proc):
        """密度正常：token 数 ≈ 字数，模拟"字被砍在半句"。"""

        def decode(self, generated, return_format=None):
            return ["あ" * int(generated.shape[1])]

    eng._model = LongModel()
    eng._processor = ProcDense()
    eng._transcribe(np.zeros(16000 * 4, dtype=np.float32))
    check(eng._last_capped is True, "撞上限未标记 capped")
    check(eng._last_truncated is True, "撞上限且密度正常却未标记截断")

    eng._processor = Proc()          # decode 固定 3 字，而 cap 给 80 token
    eng._transcribe(np.zeros(16000 * 4, dtype=np.float32))
    check(eng._last_capped is True, "复读段未标记 capped")
    check(eng._last_truncated is False, "复读段被误判为截断")

    eng._model = FakeModel()         # n=3 < cap，EOS 提前结束
    eng._transcribe(np.zeros(16000 * 4, dtype=np.float32))
    check(eng._last_capped is False, "未撞上限却标记了 capped")
    check(eng._last_truncated is False, "未撞上限却标记了截断")
    print("  P4 上限自适应：9 项通过")


def test_missed_filter():
    """E5：近静音漏句记录不在报告里喊，但必须留在 JSON 里。"""
    cfg = WhisperVadConfig()
    loud = {"start": 100.0, "end": 102.0, "dur": 2.0, "reason": "empty-after-retry",
            "peak": 0.42, "rms": 0.031}
    quiet = {"start": 200.0, "end": 201.5, "dur": 1.5, "reason": "empty-after-retry",
             "peak": 0.004, "rms": 0.0008}
    legacy = {"start": 300.0, "end": 301.0, "dur": 1.0, "reason": "empty-after-retry"}

    def report(spans):
        return app.build_transcription_report(
            media_name="a.mkv", out_filename="a.srt", out_path="/tmp/a.srt",
            engine_name="Anime Whisper（litagin）", output_format="SRT",
            elapsed_time=12.0, cue_count=10, char_count=100, is_qwen=False,
            config=cfg, missed_spans=spans,
        )

    txt = report([loud, quiet])
    check("共 1 处 / 2.0 秒" in txt, f"headline 未按峰值过滤：{[ln for ln in txt.splitlines() if '漏句' in ln]}")
    check("00:01:40.000" in txt, "有声漏句应被展示")
    check("00:03:20.000" not in txt, "近静音漏句不该展示")
    check("另有 1 处峰值低于 0.02" in txt, "被隐藏的条数没有交代")
    check("峰值 0.420" in txt, "展示项缺峰值")

    # 老 JSON 没有 peak 字段：按「有声音」处理，不能把历史记录一并藏掉
    txt_legacy = report([legacy])
    check("共 1 处 / 1.0 秒" in txt_legacy, "无 peak 字段的旧记录被误隐藏")

    # 全部是近静音：headline 显示「未发现」，但仍交代隐藏了几条
    txt_all_quiet = report([quiet])
    check("【疑似漏句区间】未发现" in txt_all_quiet, "全静音时应报未发现")
    check("另有 1 处峰值低于 0.02" in txt_all_quiet, "全静音时缺隐藏说明")

    # 落盘不过滤：信息只降噪、不丢失
    media = Path(tempfile.gettempdir()) / "zz_kikusub_missed_filter.mkv"
    path = app.write_missed_report(media, "", "whisper", [loud, quiet])
    check(path is not None and path.exists(), "漏句 JSON 未落盘")
    data = json.loads(path.read_text(encoding="utf-8"))
    check(len(data["spans"]) == 2, "JSON 不应过滤记录")
    check(data["spans"][1]["peak"] == 0.004, "JSON 缺 peak 字段")
    try:
        path.unlink()
    except OSError:
        pass
    print("  E5 漏句降噪：11 项通过")


if __name__ == "__main__":
    test_report()
    test_atomic_write()
    test_heal_gap()
    test_p4_cap()
    test_missed_filter()

    media = Path("/tmp/kikusub_test_peak.wav")
    if not media.exists():
        os.system(
            f'ffmpeg -v error -y -f lavfi -i "sine=frequency=440:duration=3" '
            f'-ac 1 -ar 16000 "{media}"'
        )
    test_peaks_cache(media)
    print(f"\nALL PASS：{ok} 项断言")
