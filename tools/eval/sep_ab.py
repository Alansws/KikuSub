#!/usr/bin/env python3
"""P3 对照：人声分离「仅用于 VAD」vs 不分离 vs 「分离人声送识别」。

同一支片、同一区间、同一 ASR 参数，跑三组：

1. ``plain``    ：不勾人声分离（基线）；
2. ``vad_only`` ：默认档，Demucs 人声只给 VAD，识别仍读原声；
3. ``to_asr``   ：高级档，分离人声直接送识别（旧行为）。

先证明「ASR 解码音频」在 plain / vad_only 之间逐字节一致（sha256 相同），
再用 `tools/eval/score_srt.py` 打分，回答收益是不是只来自更干净的 VAD 边界。

    python tools/eval/sep_ab.py \
        --media ../测试用_言叶之庭.mkv \
        --ref ../测试用_言叶之庭_中日双语.srt \
        --from 2410 --to 2470 --out outputs/eval/p3

素材与参考字幕不随仓库，路径自行传。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core import audio_cache, pipeline, transcribe  # noqa: E402
from tools.eval.score_srt import parse_srt, score  # noqa: E402

MODES = ("plain", "vad_only", "to_asr")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _fmt_stamp(stamp: dict) -> str:
    return f"{stamp['start'] / 16000:.2f}-{stamp['end'] / 16000:.2f}"


def _vad_view(audio, cfg, *, gate_audio=None) -> dict:
    stats: dict = {}
    stamps = transcribe.detect_speech_stamps(
        audio,
        None,
        threshold=float(cfg.threshold),
        min_speech_ms=int(cfg.min_speech_ms),
        min_silence_ms=int(cfg.min_silence_ms),
        speech_pad_ms=int(cfg.speech_pad_ms),
        backend=str(cfg.vad_backend),
        fallback_backend="silero",
    )
    if gate_audio is not None:
        stamps = transcribe.gate_stamps_by_energy(
            stamps,
            gate_audio,
            floor_dbfs=transcribe.VOCAL_GATE_DBFS,
            stats=stats,
        )
    return {
        "audio_s": round(len(audio) / 16000, 2),
        "stamps": len(stamps),
        "speech_s": round(sum(s["end"] - s["start"] for s in stamps) / 16000, 2),
        "gate": stats or None,
        "items": stamps,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--media", required=True)
    parser.add_argument("--ref", required=True)
    parser.add_argument("--from", dest="start", type=float, required=True)
    parser.add_argument("--to", dest="end", type=float, required=True)
    parser.add_argument("--out", type=Path, default=REPO_ROOT / "outputs" / "eval" / "p3")
    parser.add_argument("--json", type=Path, default=None)
    args = parser.parse_args(argv)

    media = Path(args.media).expanduser().resolve()
    reference = Path(args.ref).expanduser().resolve()
    for path, label in ((media, "素材"), (reference, "参考 SRT")):
        if not path.is_file():
            print(f"错误：{label}不存在：{path}", file=sys.stderr)
            return 2
    if not audio_cache.enabled():
        print("错误：本脚本依赖 audio_cache 复用 16k wav；请勿设 KIKUSUB_AUDIO_CACHE=0", file=sys.stderr)
        return 2

    from core import separate

    if not separate.available():
        print("错误：缺少 demucs（人声分离依赖）", file=sys.stderr)
        return 2

    cfg = transcribe.WhisperVadConfig()
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"素材：{media.name} ｜ 区间 {args.start:.1f}–{args.end:.1f}s ｜ 切分器 {cfg.vad_backend}")
    print(f"参考：{reference.name} ｜ 输出：{out_dir}")
    print()

    ref_cues = parse_srt(reference.read_text(encoding="utf-8-sig"))
    results: dict[str, dict] = {}

    for mode in MODES:
        started = time.perf_counter()
        request = pipeline.TranscribeRequest(
            media_path=media,
            engine_key="whisper",
            output_format="SRT",
            start_s=args.start,
            end_s=args.end,
            keep_absolute_timeline=True,
            separate_vocals=mode != "plain",
            separate_mode=mode if mode != "plain" else "vad_only",
            write_audit=False,
        )
        print(f"[{mode}] 开始…", flush=True)
        result = pipeline.run_transcription(request, output_dir=out_dir)
        elapsed = time.perf_counter() - started

        # ASR 实际解码的那份 16k wav：plain/vad_only 都应该是「原片 + 同区间」，
        # 也就是同一个缓存键 → 同一个文件 → 同一个 sha256。
        if mode == "to_asr":
            vocals = audio_cache.vocals_wav_path(media, start=args.start, end=args.end)
            asr_wav = audio_cache.wav_path(vocals, loudnorm=True)
        else:
            asr_wav = audio_cache.wav_path(
                media, loudnorm=True, start=args.start, end=args.end
            )
        if not asr_wav.exists():
            print(f"错误：找不到 ASR 缓存 wav：{asr_wav}", file=sys.stderr)
            return 2

        # 三组输出文件名只按「引擎 + 区间」生成，会互相覆盖；审计要留档，
        # 所以先复制成 <mode>.srt，再对这份副本打分（结果与运行时逐字一致）。
        mode_out = out_dir / f"p3_{mode}.srt"
        shutil.copyfile(result.out_path, mode_out)
        scored = score(ref_cues, parse_srt(mode_out.read_text("utf-8")),
                       start=args.start, end=args.end)
        results[mode] = {
            "elapsed_s": round(elapsed, 1),
            "cues": len(result.cues),
            "asr_wav": str(asr_wav),
            "asr_sha256": _sha256(asr_wav),
            "cer": round(float(scored["cer"]) * 100, 2),
            "missed_blocks": int(scored["missed_blocks"]),
            "insertions": int(scored["insertions"]),
            "max_cue_dur": round(float(scored["max_cue_dur"]), 3),
            "out": str(mode_out),
            "vad_audio": (result.segment_stats.get("separation") or {}).get("asr_audio", "original"),
        }
        print(
            f"[{mode}] {elapsed:.1f}s · {len(result.cues)} 条 · CER {results[mode]['cer']:.2f}% · "
            f"漏块 {results[mode]['missed_blocks']} · 插入 {results[mode]['insertions']} · "
            f"asr_sha={results[mode]['asr_sha256'][:12]}",
            flush=True,
        )

    # VAD 边界证据：同一时间窗，原声 vs 分离人声各跑一次切分。
    print("\n[VAD] 逐段比较原声 / 分离人声的切分边界…", flush=True)
    plain_audio = transcribe.load_audio_for_transcription(
        media, enable_loudnorm=True, start_time_s=args.start, end_time_s=args.end
    )
    vocals_path = audio_cache.vocals_wav_path(media, start=args.start, end=args.end)
    # 产品路径（2026-11-21 起）：VAD 检测仍用 dynaudnorm 档位；绝对能量门控
    # 另读一份未归一化的真实电平，避免把放大后的近静音串音送进 ASR。
    vocals_audio = transcribe.load_audio_for_transcription(
        vocals_path, enable_loudnorm=True
    )
    gains: list[float] = []
    vocals_level = transcribe.load_audio_for_transcription(
        vocals_path, enable_loudnorm=False, peak_gain_out=gains
    )
    gain = float(gains[0]) if gains else 1.0
    if gain not in (0.0, 1.0):
        vocals_level = vocals_level / gain
    vad_plain = _vad_view(plain_audio, cfg)
    vad_vocals = _vad_view(vocals_audio, cfg, gate_audio=vocals_level)
    # 100ms 容差下「同一个边界」的个数：回答差异是整体重切还是只挪了几段。
    tol = 1600
    matched = 0
    used = set()
    for a in vad_plain["items"]:
        for index, b in enumerate(vad_vocals["items"]):
            if index in used:
                continue
            if abs(a["start"] - b["start"]) <= tol and abs(a["end"] - b["end"]) <= tol:
                used.add(index)
                matched += 1
                break
    vad = {
        "plain": {
            **{k: vad_plain[k] for k in ("audio_s", "stamps", "speech_s")},
            "items_s": [_fmt_stamp(item) for item in vad_plain["items"]],
        },
        "vocals": {
            **{
                k: vad_vocals[k]
                for k in ("audio_s", "stamps", "speech_s", "gate")
            },
            "items_s": [_fmt_stamp(item) for item in vad_vocals["items"]],
        },
        "matched_within_100ms": matched,
    }
    print(
        f"[VAD] 原声 {vad_plain['stamps']} 段 / {vad_plain['speech_s']:.1f}s ｜ "
        f"分离人声 {vad_vocals['stamps']} 段 / {vad_vocals['speech_s']:.1f}s ｜ "
        f"±100ms 内同边界 {matched} 段",
        flush=True,
    )
    gate = vad_vocals.get("gate")
    if gate:
        print(
            f"[VAD] 人声能量门控 {gate['floor_dbfs']} dBFS："
            f"{gate['input']} → {gate['kept']} 段，丢弃 {gate['dropped']} 段 / "
            f"{gate['dropped_s']:.1f}s",
            flush=True,
        )

    identical = results["plain"]["asr_sha256"] == results["vad_only"]["asr_sha256"]
    print()
    print("=" * 78)
    print(f"{'档位':<10}{'耗时':>8}{'条数':>6}{'CER':>8}{'漏块':>6}{'插入':>6}{'最长条':>8}")
    for mode in MODES:
        item = results[mode]
        print(
            f"{mode:<10}{item['elapsed_s']:>7.1f}s{item['cues']:>6}"
            f"{item['cer']:>7.2f}%{item['missed_blocks']:>6}{item['insertions']:>6}"
            f"{item['max_cue_dur']:>7.3f}s"
        )
    print("=" * 78)
    print(
        "ASR 音频逐字节一致（plain == vad_only）："
        + ("✅ 是" if identical else "❌ 否")
        + f"（sha256 {results['plain']['asr_sha256'][:16]}…）"
    )
    print(
        "vad_only 的 ASR 音频来源："
        + f"{results['vad_only']['vad_audio']}（expected: original）"
    )

    payload = {
        "media": str(media),
        "range": [args.start, args.end],
        "config": {
            "vad_backend": cfg.vad_backend,
            "threshold": cfg.threshold,
            "min_speech_ms": cfg.min_speech_ms,
            "min_silence_ms": cfg.min_silence_ms,
            "speech_pad_ms": cfg.speech_pad_ms,
        },
        "runs": results,
        "asr_audio_identical_plain_vs_vad_only": identical,
        "vad": vad,
    }
    json_path = args.json or (out_dir / "p3_sep_ab.json")
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"结果：{json_path}")
    return 0 if identical else 1


if __name__ == "__main__":
    raise SystemExit(main())
