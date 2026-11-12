"""core.tts：音色仓库、切片去静音、缓存与资源回收。

这些用例刻意不加载 OmniVoice 模型（3GB / 十秒级），克隆推理的验收在
`tests/test_server_tts.py` 的 `KIKUSUB_TEST_TTS_MODEL=1` 开关用例里单独跑。
"""

from __future__ import annotations

import shutil
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from core.tts import (
    TTSManager,
    TTSVoice,
    VoiceConflict,
    VoiceInvalid,
    VoiceNotFound,
    VoiceStore,
)
from core.tts.base import EngineUnavailable, TTSError
from core.tts.clone_engine import REQUIRED_FILES
from core.tts.model_store import ModelDownloader


def write_wav(path: Path, seconds: float = 2.0, *, sr: int = 24000, lead: float = 0.0) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    silence = np.zeros(int(sr * lead), dtype=np.float32)
    t = np.linspace(0, seconds, int(sr * seconds), endpoint=False)
    tone = (0.3 * np.sin(2 * np.pi * 220 * t)).astype(np.float32)
    sf.write(str(path), np.concatenate([silence, tone]), sr, subtype="PCM_16")
    return path


@pytest.fixture()
def store(tmp_path: Path) -> VoiceStore:
    return VoiceStore(tmp_path / "voices")


def test_create_rename_delete_and_unique_names(store: VoiceStore, tmp_path: Path) -> None:
    ref = write_wav(tmp_path / "ref.wav", 2.0)
    voice = store.create_from_file(ref, name="女主角", ref_text="こんにちは")
    assert voice.id.startswith("clone:")
    assert voice.name == "女主角"
    assert voice.duration > 1.8
    assert store.ref_path(voice.id).is_file()

    # 同名会自动加序号，不覆盖已有音色
    second = store.create_from_file(ref, name="女主角")
    assert second.name == "女主角 2"
    assert {v.name for v in store.list()} == {"女主角", "女主角 2"}

    renamed = store.rename(voice.id, " 幼なじみ ")
    assert renamed.name == "幼なじみ"
    with pytest.raises(VoiceConflict):
        store.rename(second.id, "幼なじみ")

    store.delete(second.id)
    assert [v.name for v in store.list()] == ["幼なじみ"]
    with pytest.raises(Exception):
        store.get(second.id)


def test_voice_id_path_traversal_is_rejected(store: VoiceStore) -> None:
    for bad in ("clone:.", "clone:..", "clone:a/../b", "clone:"):
        with pytest.raises(VoiceNotFound):
            store.delete(bad)


def test_create_from_media_trims_silence(store: VoiceStore, tmp_path: Path) -> None:
    if not shutil.which("ffmpeg"):
        pytest.skip("需要 ffmpeg")
    media = write_wav(tmp_path / "media.wav", 1.0, lead=0.5)
    voice = store.create_from_media(
        media, start=0.5, end=1.5, name="切句", ref_text="テスト"
    )
    # 0.5s 静音被裁掉；前后各留 0.08s 的呼吸，所以落在 1.0–1.3s
    assert 1.0 <= voice.duration <= 1.3
    data, sr = sf.read(str(store.ref_path(voice.id)))
    assert sr == 24000
    assert abs(len(data) / sr - voice.duration) < 0.02


def test_invalid_reference_is_rejected(store: VoiceStore, tmp_path: Path) -> None:
    empty = tmp_path / "empty.wav"
    sf.write(str(empty), np.zeros(24000, dtype=np.float32), 24000, subtype="PCM_16")
    with pytest.raises(VoiceInvalid):
        store.create_from_file(empty, name="空的")
    with pytest.raises(VoiceInvalid):
        store.create_from_file(tmp_path / "nope.wav", name="不存在")


class FakeSay:
    key = "mac_say"
    label = "fake"
    platform_ok = True

    def __init__(self) -> None:
        self.calls = 0

    def list_voices(self) -> list[TTSVoice]:
        return [TTSVoice(id="system:Kyoko", name="Kyoko", engine="mac_say", kind="system")]

    def default_voice_name(self) -> str:
        return "Kyoko"

    def available(self) -> bool:
        return True

    def synthesize(self, text: str, voice: TTSVoice, speed: float, out_path: Path) -> None:
        self.calls += 1
        write_wav(out_path, max(0.3, len(text) / 12.0))

    def unload(self) -> None:
        return None


def test_synthesize_caches_and_reuses(tmp_path: Path) -> None:
    manager = TTSManager(tmp_path / "out", model_dir=tmp_path / "missing-model")
    fake = FakeSay()
    manager.say = fake  # type: ignore[assignment]

    first = manager.synthesize("こんにちは", voice_id="system:Kyoko")
    assert first["cached"] is False
    assert first["engine"] == "mac_say"
    second = manager.synthesize("こんにちは", voice_id="system:Kyoko")
    assert second["cached"] is True
    assert second["filename"] == first["filename"]
    assert fake.calls == 1
    assert (manager.cache_dir / first["filename"]).is_file()


def test_text_and_voice_validation(tmp_path: Path) -> None:
    manager = TTSManager(tmp_path / "out", model_dir=tmp_path / "missing-model")
    manager.say = FakeSay()  # type: ignore[assignment]
    with pytest.raises(TTSError):
        manager.synthesize("   ", voice_id="system:Kyoko")
    with pytest.raises(TTSError):
        manager.synthesize("あ" * 601, voice_id="system:Kyoko")
    with pytest.raises(TTSError):
        manager.synthesize("こんにちは", voice_id="system:NoSuchVoice")


def test_clone_engine_unavailable_message(tmp_path: Path) -> None:
    manager = TTSManager(tmp_path / "out", model_dir=tmp_path / "missing-model")
    manager.say = FakeSay()  # type: ignore[assignment]
    clone = TTSVoice(id="clone:deadbeef", name="某角色", engine="omnivoice", kind="clone")
    manager.resolve_voice = lambda voice_id="": clone  # type: ignore[assignment]
    with pytest.raises(EngineUnavailable) as excinfo:
        manager.synthesize("こんにちは", voice_id=clone.id)
    assert "克隆模型" in str(excinfo.value)


def test_default_voice_is_always_say_even_with_clones(tmp_path: Path) -> None:
    manager = TTSManager(tmp_path / "out", model_dir=tmp_path / "missing-model")
    manager.say = FakeSay()  # type: ignore[assignment]
    clone = TTSVoice(id="clone:deadbeef", name="某角色", engine="omnivoice", kind="clone")
    manager._custom_voices = lambda: [clone]  # type: ignore[assignment]
    # 克隆音色存在也必须默认 say，否则用户第一次点朗读会意外加载 3GB 模型。
    assert manager.default_voice_id() == "system:Kyoko"


def test_voices_payload_shape(tmp_path: Path) -> None:
    manager = TTSManager(tmp_path / "out", model_dir=tmp_path / "missing-model")
    manager.say = FakeSay()  # type: ignore[assignment]
    payload = manager.list_voices()
    assert payload["default"] == "system:Kyoko"
    assert payload["engine"]["installed"] is False
    assert payload["system"][0]["id"] == "system:Kyoko"
    assert "download" in payload["engine"]


def test_model_downloader_reports_progress(tmp_path: Path, monkeypatch) -> None:
    target = tmp_path / "model"
    downloader = ModelDownloader(target)
    assert downloader.status()["installed"] is False
    assert downloader.status()["status"] == "idle"

    def fake_total() -> int:
        return 100

    def fake_snapshot(**kwargs) -> None:
        for name in REQUIRED_FILES:
            path = target / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"x" * 10)

    monkeypatch.setattr(downloader, "_remote_total", fake_total)
    monkeypatch.setattr(
        "core.tts.model_store.snapshot_download",
        fake_snapshot,
        raising=False,
    )
    # `_run` 在函数内 import，patch huggingface_hub 上的符号更贴近真实调用
    import huggingface_hub

    monkeypatch.setattr(huggingface_hub, "snapshot_download", fake_snapshot)
    downloader.start()
    downloader._thread.join(timeout=5)  # type: ignore[union-attr]
    status = downloader.status()
    assert status["installed"] is True
    assert status["status"] == "done"
    assert status["percent"] == 100
    # 已安装时再点一次「下载」必须立刻返回 done（回归：Lock 重入会死锁）
    again = downloader.start()
    assert again["status"] == "done"


def test_heavy_jobs_release_tts_model(tmp_path: Path) -> None:
    """转写/导出开跑前必须先让 TTS 卸载克隆模型（统一内存只有一份）。"""
    from server.jobs import JobManager

    calls: list[str] = []
    manager = JobManager(tmp_path, on_heavy_job=calls.append)
    job = manager._launch("transcribe", "样本", "", None)
    manager._registry.finish(job.token)
    assert calls == ["transcribe 启动"]

    calls.clear()
    job = manager._launch("ai-polish", "润色", "", None)
    manager._registry.finish(job.token)
    assert calls == []


@pytest.mark.needs_model
@pytest.mark.needs_macos
@pytest.mark.skipif(
    __import__("os").environ.get("KIKUSUB_TEST_TTS_MODEL") != "1",
    reason="需要 OmniVoice 权重，显式设 KIKUSUB_TEST_TTS_MODEL=1 才跑（约 3GB / 10 秒级）",
)
def test_omnivoice_clone_roundtrip(tmp_path: Path) -> None:
    """真实模型集成用例：从 say 生成一段日语人声当参考，再克隆朗读一句。

    默认跳过，避免在普通 `pytest` / 轻量 CI 里拉 3GB 权重或占用 MPS。
    """
    import shutil
    import subprocess

    from core.tts.clone_engine import default_model_dir, model_installed

    if not model_installed():
        pytest.skip(f"没有 OmniVoice 权重：{default_model_dir()}")
    if not shutil.which("say"):
        pytest.skip("需要 macOS say 生成参考人声")

    ref = tmp_path / "ref.wav"
    subprocess.run(
        [
            "say",
            "-v",
            "Kyoko",
            "--file-format=WAVE",
            "--data-format=LEI16@24000",
            "-o",
            str(ref),
            "制服の裾を濡らす他人の傘",
        ],
        check=True,
        timeout=30,
    )
    manager = TTSManager(tmp_path / "out")
    try:
        voice = manager.create_voice_from_file(ref, name="集成测试", ref_text="制服の裾を濡らす他人の傘")
        first = manager.synthesize("雨の音が聞こえる。", voice_id=voice["id"])
        assert first["engine"] == "omnivoice"
        assert first["duration"] > 0.2
        assert first["cached"] is False
        second = manager.synthesize("雨の音が聞こえる。", voice_id=voice["id"])
        assert second["cached"] is True
        assert manager.clone.loaded is True
    finally:
        manager.close()
    assert manager.clone.loaded is False


def test_model_verify_detects_empty_weights(tmp_path: Path) -> None:
    """「校验 / 补齐」不能把 0 字节文件当作已就绪。"""
    target = tmp_path / "model"
    for name in REQUIRED_FILES:
        path = target / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x" * 10)
    downloader = ModelDownloader(target)
    assert downloader.verify()["installed"] is True

    (target / REQUIRED_FILES[0]).write_bytes(b"")
    result = downloader.verify()
    assert result["installed"] is False
    assert REQUIRED_FILES[0] in result["missing"]
