"""`whisper.use_prev_text_prompt` 的两道守卫（2026-11-22）。

1. 上下文只走**显式参数**：`ENGINE` 是模块级单例，整片转写、核对台单句重转
   （`core.short_clip`）与「另一引擎听一遍」（`transcribe_window`）共用同一个实例。
   把「上一句是什么」留在实例上，上一次整片任务的尾巴会污染下一次单句重转，
   取消/异常退出时还会把旧上下文留在里面——所以 `_decode_chunk` 不读实例状态。
2. `prompt_text_for` 是「上一句能不能当上下文」的唯一判断处：长停顿换场、
   可疑幻觉、纯装饰、病理性复读都不传。

这里用假 pipeline/假 tokenizer，不需要 torch，也不加载任何权重。
"""

from __future__ import annotations

import numpy as np
import pytest

from core.transcribe import (
    PROMPT_MAX_CHARS,
    PROMPT_MAX_GAP_S,
    AnimeWhisperEngine,
    prompt_text_for,
)

# ---------------------------------------------------------------- 上下文闸门


def test_decorative_symbols_are_stripped():
    assert prompt_text_for("ママ、気持ちいい♡") == "ママ、気持ちいい"
    assert prompt_text_for("♪ はい ♪") == "はい"


@pytest.mark.parametrize("text", ["", "……", "♪♡…", "　　"])
def test_context_without_content_is_dropped(text):
    assert prompt_text_for(text) == ""


def test_long_gap_drops_context():
    # 换场/长停顿：上一句和本句通常不是同一段对话，不把语义带过来。
    assert prompt_text_for("はい", gap_s=PROMPT_MAX_GAP_S + 0.1) == ""
    assert prompt_text_for("はい", gap_s=PROMPT_MAX_GAP_S) == "はい"
    assert prompt_text_for("はい", gap_s=None) == "はい"


def test_suspicious_or_repetitive_context_is_dropped():
    assert prompt_text_for("はい", suspicious=True) == ""
    assert prompt_text_for("らめ" * 6) == ""


def test_context_is_capped():
    text = "".join(chr(0x3042 + i % 40) for i in range(400))
    assert len(prompt_text_for(text)) == PROMPT_MAX_CHARS


# ------------------------------------------------------------ 显式传参（假管线）


class _FakeTensor:
    def __init__(self, text: str) -> None:
        self.text = text
        self.device = None

    def to(self, device):
        self.device = device
        return self


class _FakeTokenizer:
    def __init__(self) -> None:
        self.seen: list[str] = []
        self.fail = False

    def get_prompt_ids(self, text: str, return_tensors=None) -> _FakeTensor:
        if self.fail:
            raise RuntimeError("tokenizer 拒绝")
        self.seen.append(text)
        return _FakeTensor(text)


class _FakePipe:
    device = "fake-device"

    def __init__(self) -> None:
        self.tokenizer = _FakeTokenizer()
        self.calls: list[dict] = []

    def __call__(self, inputs, generate_kwargs=None, return_timestamps=False):
        self.calls.append(dict(generate_kwargs or {}))
        return {"text": "はい"}


def _engine(*, enabled: bool = True) -> AnimeWhisperEngine:
    engine = AnimeWhisperEngine.__new__(AnimeWhisperEngine)
    engine._pipe = _FakePipe()
    engine.last_prompt_ids_stats = {"enabled": enabled, "applied": 0, "failed": 0}
    return engine


BUF = np.zeros(16000, dtype=np.float32)


def test_prompt_is_sent_when_explicitly_passed():
    engine = _engine()
    engine._decode_chunk(BUF, {"language": "Japanese"}, prompt_text="ママ、気持ちいい")
    assert engine._pipe.tokenizer.seen == ["ママ、気持ちいい"]
    assert engine._pipe.calls[0]["prompt_ids"].text == "ママ、気持ちいい"
    assert engine.last_prompt_ids_stats["applied"] == 1


def test_no_prompt_text_means_no_prompt():
    """核对台单句重转 / 「另一引擎听一遍」不传上下文 → 永远不带旧的上一句。"""
    engine = _engine(enabled=True)
    engine._decode_chunk(BUF, {"language": "Japanese"})
    assert engine._pipe.tokenizer.seen == []
    assert "prompt_ids" not in engine._pipe.calls[0]


def test_timestamps_decode_never_carries_prompt():
    engine = _engine()
    engine._decode_chunk(BUF, {"language": "Japanese"}, timestamps=True, prompt_text="ママ")
    assert engine._pipe.tokenizer.seen == []


def test_failure_latches_off_for_the_rest_of_the_run():
    engine = _engine()
    engine._pipe.tokenizer.fail = True
    assert engine._decode_chunk(BUF, {}, prompt_text="ママ") == "はい"
    assert engine.last_prompt_ids_stats["enabled"] is False
    assert engine.last_prompt_ids_stats["failed"] == 1
    # 熔断后不再反复踩同一个坑，也不影响出字幕。
    engine._pipe.tokenizer.fail = False
    engine._decode_chunk(BUF, {}, prompt_text="ママ")
    assert engine._pipe.tokenizer.seen == []


def test_prompt_is_silero_only():
    """按实际使用的切分器门控：WhisperSeg 打开提示会明显变差（12.11% → 26.76%）。"""
    from core.transcribe import prev_text_prompt_enabled

    assert prev_text_prompt_enabled(True, "silero") is True
    assert prev_text_prompt_enabled(True, "whisperseg") is False
    assert prev_text_prompt_enabled(True, "") is False
    assert prev_text_prompt_enabled(False, "silero") is False
