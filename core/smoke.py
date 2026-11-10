"""内核自检：`python -m core.smoke`

用途有两个：

1. **证伪「内核与 UI 解耦」**。先断言 `gradio` / `fastapi` 没有被导入，再导入
   `core.*`，最后再次断言。如果哪天有人在 core 里顺手 `import gradio`，这里立刻红。
2. **确认搬迁没有搬坏路径**。模型目录、输出目录、预设文件、音频缓存目录都打印出来，
   并真的写一次临时预设、跑一次子进程、走一遍 SRT 往返。

退出码 0 表示全绿；任何一步失败都会抛出异常并返回非 0。
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

FORBIDDEN = ("gradio", "fastapi", "uvicorn", "starlette", "electron")


def _check_no_ui_modules(stage: str) -> None:
    leaked = [name for name in FORBIDDEN if name in sys.modules]
    if leaked:
        raise SystemExit(f"[FAIL] {stage}: 检测到 UI 依赖被引入 -> {leaked}")


def _section(title: str) -> None:
    print(f"\n\033[1m{title}\033[0m")


def main() -> int:
    _check_no_ui_modules("启动时（应为空）")

    _section("1. 导入 core 包")
    from core import audio_cache, jobs, paths, presets, procutil  # noqa: F401
    from core import transcribe
    from core.qwen_ctc import QwenCtcConfig, QwenCtcEngine  # noqa: F401
    from core.transcribe import (
        SubtitleCue,
        cues_to_srt,
        cues_to_vtt,
        detect_device,
        format_duration,
        parse_time_str,
        remove_ellipsis_only_cues,
        srt_to_cues,
    )

    print(f"  core 版本入口 OK；python={sys.version.split()[0]}")
    _check_no_ui_modules("导入 core 之后")

    _section("2. 路径解析")
    for label, value in (
        ("APP_ROOT", paths.ROOT),
        ("MODELS_DIR", paths.MODELS_DIR),
        ("OUTPUT_DIR", paths.OUTPUT_DIR),
        ("PRESETS_PATH", paths.PRESETS_PATH),
        ("CACHE_DIR", audio_cache.CACHE_DIR),
        ("whisper MODEL_DIR", transcribe.MODEL_DIR),
    ):
        print(f"  {label:<20} {value}")
    if paths.ROOT.name == "core":
        raise SystemExit("[FAIL] APP_ROOT 仍指向 core/，路径中枢没生效")

    _section("3. 字幕数据结构往返")
    cues = [
        SubtitleCue(start=0.0, end=1.25, text="おはよう"),
        SubtitleCue(start=1.25, end=2.5, text="…"),
        SubtitleCue(start=2.5, end=4.0, text="今日はいい天気ですね"),
    ]
    srt = cues_to_srt(cues)
    back = srt_to_cues(srt)
    assert len(back) == 3, f"SRT 往返条数不一致：{len(back)}"
    assert abs(back[0].start) < 1e-6 and abs(back[2].end - 4.0) < 1e-6, "时间轴往返失真"
    assert "WEBVTT" in cues_to_vtt(cues)
    assert parse_time_str("00:00:01,250") == 1.25
    assert format_duration(3725) == "62 分 5.00 秒 (3725.00 秒)", format_duration(3725)
    cleaned = remove_ellipsis_only_cues(cues)
    assert len(cleaned) == 2, f"省略号过滤失效：{len(cleaned)}"
    print("  SRT / VTT / 时间解析 / 省略号过滤 全部一致")

    _section("4. 预设存储（临时文件）")
    with tempfile.TemporaryDirectory() as tmp:
        store = presets.PresetStore(Path(tmp) / "presets.json")
        store.save("冒烟预设", {"whisper.beam_size": 5}, engine="whisper")
        assert store.get("冒烟预设")["参数"]["whisper.beam_size"] == 5
        assert store.list() == [("冒烟预设", "whisper")]
        store.rename("冒烟预设", "改名后")
        store.delete("改名后")
        assert store.names() == []
    print("  增 / 查 / 改 / 删 全部通过")

    _section("5. 任务注册表")
    registry = jobs.JobRegistry()
    token = registry.start("smoke-session", label="smoke")
    assert registry.active() is token
    try:
        registry.start("other-session")
    except jobs.JobBusy:
        print("  并发占槽正确抛出 JobBusy")
    else:
        raise SystemExit("[FAIL] 第二次 start 没有抛出 JobBusy")
    token.cancel()
    registry.finish(token)
    assert registry.active() is None
    print("  取消 / 释放 正确")

    _section("6. 子进程工具")
    result = procutil.run_command(
        [sys.executable, "-c", "print('kikusub-smoke')"], timeout=30
    )
    assert "kikusub-smoke" in result.stdout, result
    assert procutil.tail("short", 100) == "short"
    assert procutil.tail("x" * 10, 4) == "…xxxx"
    print("  run_command / tail 正常")

    _section("7. 推理设备探测")
    print(f"  detect_device() -> {detect_device()}")

    _section("8. 音频缓存键")
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as fh:
        fh.write(b"smoke")
        media = Path(fh.name)
    try:
        key = audio_cache.cache_key(media, loudnorm=False)
        assert len(key) >= 8 and (audio_cache.CACHE_DIR / f"{key}.wav").name.endswith(".wav")
        print(f"  cache_key -> {key}")
    finally:
        os.unlink(media)

    _section("9. 确认 core 可独立冷启动")
    # 全新解释器里只 import core，不碰 app.py；这是打包后 sidecar 的真实启动路径。
    code = (
        "import sys;"
        "import core.transcribe, core.qwen_ctc, core.jobs, core.presets, core.audio_cache;"
        f"leak=[m for m in {FORBIDDEN!r} if m in sys.modules];"
        "sys.exit(1 if leak else 0)"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(Path(__file__).resolve().parent.parent),
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise SystemExit(f"[FAIL] 冷启动泄漏 UI 依赖：{proc.stdout}{proc.stderr}")
    print("  干净解释器中 core 可独立导入，无 UI 依赖")

    print("\n\033[32m✅ core 自检全部通过\033[0m")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
