"""ASR 引擎空闲卸载的租约（2026-11-26 真机事故回归）。

**事故形态**：先用 Qwen3-ASR 跑完整片主稿（246 条进核对台），再在转写页把产出
切到「第二版（对照）」用 Anime Whisper 跑整片。Anime Whisper 跑完转录、即将落盘时
底部报 `! 转写失败 'NoneType' object is not callable`。

**真机 traceback**（`~/Library/Application Support/KikuSub-Next/outputs/logs/kikusub.log`
2026-11-26 00:36:08）::

    File "server/jobs.py", line 960, in _run_transcribe
    File "core/pipeline.py", line 433, in run_transcription
    File "core/transcribe.py", line 1839, in transcribe_file
    File "core/transcribe.py", line 1991, in _decode
    File "core/transcribe.py", line 1708, in _decode_chunk
    TypeError: 'NoneType' object is not callable

`core/transcribe.py:1708` 是 `res = self._pipe(...)`。`_pipe` 为 None 是因为
`kikusub-asr-idle` 线程在**任务运行中**把 Anime Whisper 卸了：上一次 whisper 的
`touch` 是复核任务结束时（00:33:07），整片任务 00:33:57 开始后从未 touch，
00:36:08 正好跨过 180s 空闲阈值，巡检照卸不误。

修复：`EngineIdleReleaser.hold()` 租约 —— 跑片期间 sweep / release_others /
release_now 一律跳过该引擎，租约退出时重新计时。本文件把「旧行为会崩」与
「修复后不崩」都钉成断言，并覆盖用户报障的完整路径（主稿存在 → Anime Whisper
转录第二版）。
"""

from __future__ import annotations

import time

import pytest

from core.engine_idle import EngineIdleReleaser


class _FakeClock:
    def __init__(self, start: float = 1000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class _FakeWhisper:
    """模仿 `AnimeWhisperEngine`：`release()` 把 `_pipe` 置 None，之后调用即崩。"""

    def __init__(self) -> None:
        self._pipe = self.decode
        self.released = 0
        self.decodes = 0

    def decode(self, *_a, **_k) -> str:
        self.decodes += 1
        return f"第{self.decodes}段"

    def release(self) -> None:
        self._pipe = None
        self.released += 1

    def transcribe(self) -> str:
        # 与 core/transcribe.py:1708 同一形态：None 被当函数调用。
        return self._pipe({"array": b"", "sampling_rate": 16000})

    def load(self) -> None:
        self._pipe = self.decode


def _releaser(clock: _FakeClock, engine: _FakeWhisper, *, idle_seconds: float = 180.0):
    released: list[str] = []

    def release(key: str) -> bool:
        # 真实现里 release_engine("qwen") 卸的是 Qwen 的权重，不是 Whisper 的。
        released.append(key)
        if key == "whisper":
            engine.release()
        return True

    idle = EngineIdleReleaser(
        idle_seconds=idle_seconds,
        clock=clock,
        release=release,
        autostart=False,
    )
    return idle, released


# ---------------------------------------------------------------------------
# 一、租约本身
# ---------------------------------------------------------------------------


def test_without_lease_idle_sweep_unloads_mid_run():
    """事故复现：没有租约时，跑片途中巡检会把正在用的引擎卸掉 → TypeError。

    这条断言钉住「为什么必须加租约」，不是断言某个 bug 还在。
    """
    clock = _FakeClock()
    engine = _FakeWhisper()
    idle, released = _releaser(clock, engine)

    idle.touch("whisper")
    engine.transcribe()  # 第一段正常
    clock.advance(181)  # 整片跑了 181s，期间没有 touch
    assert idle.sweep() == ["whisper"]  # 巡检照卸
    with pytest.raises(TypeError, match="NoneType"):
        engine.transcribe()


def test_hold_keeps_engine_alive_through_long_run():
    clock = _FakeClock()
    engine = _FakeWhisper()
    idle, released = _releaser(clock, engine)

    idle.touch("qwen")  # 主稿用的那个引擎也在 _last_used 里
    idle.touch("whisper")

    with idle.hold("whisper", reason="整片任务"):
        assert idle.busy("whisper")
        for _ in range(20):
            clock.advance(30)  # 合计 600s，远超 180s 阈值
            assert idle.sweep() == []  # 巡检不卸正在跑的
            assert idle.release_others("qwen") == []  # 「让路」也不许碰它
            # 主动卸载会卸掉空闲的别的引擎，但绝不许碰租约里的这个
            assert "whisper" not in idle.release_now()
            idle.touch("qwen")  # 补回来，下一轮继续验
            assert engine.transcribe().startswith("第")
    assert not idle.busy("whisper")
    assert "whisper" not in released  # 全程一次都没卸过正在跑的那个
    assert engine.released == 0


def test_hold_touches_on_entry_and_rearms_window_on_exit():
    clock = _FakeClock()
    engine = _FakeWhisper()
    idle, released = _releaser(clock, engine)

    with idle.hold("whisper"):
        clock.advance(181)  # 租约期内时间照走
        assert idle.sweep() == []
    # 退出即重新计时：再等 100s 仍不算空闲（从「这轮结束」算，不是从「开始」算）
    clock.advance(100)
    assert idle.sweep() == []
    clock.advance(81)  # 现在才满 180s
    assert idle.sweep() == ["whisper"]
    assert released == ["whisper"]


def test_hold_is_noop_without_engine_key():
    clock = _FakeClock()
    engine = _FakeWhisper()
    idle, released = _releaser(clock, engine)
    with idle.hold(""):
        pass
    assert idle.touched() == []  # 不凭空记一个空 key
    assert released == []


def test_release_others_skips_only_busy_engine():
    clock = _FakeClock()
    engine = _FakeWhisper()
    idle, released = _releaser(clock, engine)
    idle.touch("qwen")
    idle.touch("whisper")

    with idle.hold("whisper"):
        assert idle.release_others("sherpa") == ["qwen"]  # 空闲的照常让路
        assert released == ["qwen"]


def test_lease_is_threadsafe_under_real_threads():
    """真线程下也不许把租约漏掉：后台巡检与跑片并发 200 轮。"""
    import threading

    clock = _FakeClock()
    engine = _FakeWhisper()
    idle, released = _releaser(clock, engine)
    idle.touch("whisper")
    errors: list[BaseException] = []
    done = threading.Event()

    def worker() -> None:
        try:
            with idle.hold("whisper"):
                for _ in range(200):
                    clock.advance(5)
                    engine.transcribe()
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)
        finally:
            done.set()

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    while not done.is_set():
        idle.sweep()
        time.sleep(0.0005)
    thread.join(timeout=5)
    assert errors == []
    assert released == []
    assert engine.released == 0
