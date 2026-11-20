#!/usr/bin/env python3
"""P2 双引擎协同真机回归：主 Whisper + 副 Qwen、区间 replace_range、vad_only 分离。

三个场景各自走完整的 HTTP 栈（`server.app` + `TestClient`），不是替身 runner：

1. ``full``  ：整片（默认 Test 二）主 Whisper + 副 Qwen，验证两遍顺序、释放主引擎、
   第二列只读、报告【双引擎协同】；
2. ``range`` ：区间 `replace_range`，先导入一份跨区间的旧第二列，验证**范围外逐字
   不变、范围内被副稿替换**（区间第二列保护）；
3. ``separation``：区间 + 人声分离 `vad_only`，验证两次 pass 的 ASR 仍听原声
   （`vad_audio_path` 指向分离人声）、分离缓存只算一次、释放顺序正常。

用法：

    ../.venv/bin/python tools/eval/dual_regression.py \
        --full-media ../Jap_test_2.mp4 \
        --range-media ../测试用_言叶之庭.mkv \
        --range 2410 2470 \
        --out outputs/eval/p2
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

pytest_missing = None
try:
    from fastapi.testclient import TestClient
except Exception as exc:  # pragma: no cover - 环境缺 fastapi 时给出可读提示
    pytest_missing = exc

TOKEN = "dual-regression"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


def _wait(client, job_id: str, timeout: float) -> dict:
    deadline = time.time() + timeout
    last = {}
    while time.time() < deadline:
        last = client.get(f"/api/jobs/{job_id}", headers=AUTH).json()
        if last.get("status") in {"done", "error", "cancelled"}:
            return last
        time.sleep(0.5)
    raise TimeoutError(f"job {job_id} 超时；最后状态：{last.get('status')}")


def _write_srt(path: Path, cues: list[tuple[float, float, str]]) -> None:
    def stamp(sec: float) -> str:
        h = int(sec // 3600)
        m = int((sec % 3600) // 60)
        s = sec % 60
        return f"{h:02d}:{m:02d}:{int(s):02d},{int(round((s - int(s)) * 1000)):03d}"

    blocks = [f"{i}\n{stamp(a)} --> {stamp(b)}\n{text}" for i, (a, b, text) in enumerate(cues, 1)]
    path.write_text("\n\n".join(blocks) + "\n", encoding="utf-8")


def _alt_texts(client) -> list[dict]:
    body = client.get("/api/alt-review", headers=AUTH).json()
    return body.get("cues") or []


class _Probe:
    """包住引擎/释放/分离器，记录这次真机跑到底做了什么。"""

    def __init__(self) -> None:
        self.released: list[str] = []
        self.separations: list[tuple[float, float]] = []
        self.engine_calls: list[dict] = []
        self._orig: list[tuple[object, str, object]] = []

    def install(self) -> None:
        import core.pipeline as pipeline_mod
        import core.separate as separate_mod
        from core.qwen_ctc import QwenCtcEngine
        from core.transcribe import AnimeWhisperEngine

        orig_release = pipeline_mod.release_engine
        self._orig.append((pipeline_mod, "release_engine", orig_release))

        def release(key, *args, **kwargs):
            self.released.append(str(key))
            return orig_release(key, *args, **kwargs)

        pipeline_mod.release_engine = release

        orig_sep = separate_mod.separate_to_wav
        self._orig.append((separate_mod, "separate_to_wav", orig_sep))

        def separation(media, out, *, start=0.0, end=0.0, **kwargs):
            self.separations.append((float(start), float(end)))
            return orig_sep(media, out, start=start, end=end, **kwargs)

        separate_mod.separate_to_wav = separation

        probe = self
        for cls, key in ((AnimeWhisperEngine, "whisper"), (QwenCtcEngine, "qwen")):
            orig = cls.transcribe_file
            self._orig.append((cls, "transcribe_file", orig))

            def wrapped(engine_self, media_path, *args, _key=key, _orig=orig, **kwargs):
                probe.engine_calls.append(
                    {
                        "engine": _key,
                        "media": str(media_path),
                        "start": kwargs.get("start_time_s"),
                        "end": kwargs.get("end_time_s"),
                        "vad_audio": str(kwargs.get("vad_audio_path") or ""),
                    }
                )
                return _orig(engine_self, media_path, *args, **kwargs)

            cls.transcribe_file = wrapped

    def reset(self) -> None:
        self.released.clear()
        self.separations.clear()
        self.engine_calls.clear()

    def restore(self) -> None:
        for target, attr, orig in reversed(self._orig):
            setattr(target, attr, orig)
        self._orig.clear()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--full-media", default="", help="整片场景素材；留空跳过 full")
    parser.add_argument("--range-media", required=True)
    parser.add_argument("--range", nargs=2, type=float, required=True, metavar=("START", "END"))
    parser.add_argument("--out", type=Path, default=REPO_ROOT / "outputs" / "eval" / "p2")
    parser.add_argument("--full-timeout", type=float, default=900.0)
    parser.add_argument("--range-timeout", type=float, default=600.0)
    args = parser.parse_args(argv)

    if pytest_missing is not None:
        print(f"错误：缺少 fastapi TestClient：{pytest_missing}", file=sys.stderr)
        return 2

    from server.app import create_app
    from server.config import ServerConfig

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    report: dict = {"scenarios": {}}
    failures: list[str] = []
    probe = _Probe()
    probe.install()

    def make_client(root: Path):
        root.mkdir(parents=True, exist_ok=True)
        app = create_app(ServerConfig(token=TOKEN, output_dir=root))
        return TestClient(app)

    try:
        # ------------------------------------------------------------ 1) full
        if args.full_media:
            media = Path(args.full_media).expanduser().resolve()
            if not media.is_file():
                print(f"跳过 full：素材不存在 {media}", file=sys.stderr)
            else:
                print(f"[full] {media.name}：主 Whisper + 副 Qwen …", flush=True)
                client = make_client(out_dir / "full")
                media_id = client.post("/api/media", headers=AUTH, json={"path": str(media)}).json()["id"]
                probe.reset()
                started = time.perf_counter()
                created = client.post(
                    "/api/jobs",
                    headers=AUTH,
                    json={
                        "media_id": media_id,
                        "kind": "dual",
                        "engine": "whisper",
                        "secondary_engine": "qwen",
                        "apply": "replace",
                    },
                )
                if created.status_code != 201:
                    failures.append(f"full: 创建任务失败 {created.status_code} {created.text[:200]}")
                    print(f"[full] ❌ {created.status_code} {created.text[:200]}", flush=True)
                else:
                    snap = _wait(client, created.json()["id"], args.full_timeout)
                    elapsed = time.perf_counter() - started
                    result = snap.get("result") or {}
                    dual_section = None
                    rpt = client.get(f"/api/report?job_id={created.json()['id']}", headers=AUTH).json()
                    dual_section = next((s for s in rpt.get("sections", []) if s.get("id") == "dual"), None)
                    alt = _alt_texts(client)
                    scenario = {
                        "status": snap.get("status"),
                        "elapsed_s": round(elapsed, 1),
                        "summary": result.get("summary"),
                        "primary_cues": result.get("primary_cues"),
                        "secondary_cues": result.get("secondary_cues"),
                        "ensemble_count": result.get("ensemble_count"),
                        "alt_count": len(alt),
                        "report_headline": (dual_section or {}).get("headline"),
                        "released": list(probe.released),
                        "engine_calls": list(probe.engine_calls),
                        "separations": list(probe.separations),
                    }
                    report["scenarios"]["full"] = scenario
                    print(
                        f"[full] {snap.get('status')} · {elapsed:.1f}s · {result.get('summary')} · "
                        f"release={probe.released}",
                        flush=True,
                    )
                    checks = [
                        (snap.get("status") == "done", "任务未完成"),
                        (result.get("dual") is True, "结果缺 dual 标记"),
                        (result.get("primary_engine") == "whisper", "主引擎不是 whisper"),
                        (result.get("secondary_engine") == "qwen", "副引擎不是 qwen"),
                        (result.get("primary_cues", 0) > 0, "主稿为空"),
                        (len(alt) > 0, "第二列没有副稿"),
                        (probe.released[:1] == ["whisper"], f"未释放主引擎：{probe.released}"),
                        (bool(dual_section), "报告缺【双引擎协同】"),
                    ]
                    failures.extend(f"full: {msg}" for ok, msg in checks if not ok)

        # ----------------------------------------------------------- 2) range
        range_media = Path(args.range_media).expanduser().resolve()
        start, end = args.range
        client = make_client(out_dir / "range")
        media_id = client.post(
            "/api/media", headers=AUTH, json={"path": str(range_media)}
        ).json()["id"]
        # 会话绑定到媒体，第二列才能按影片身份落盘/导入。
        client.post("/api/session/bind", headers=AUTH, json={"media_id": media_id})
        old_cues = [
            (5.0, 6.0, "範囲外の前の台詞"),
            (start + 2.0, start + 3.0, "範囲内の古い台詞"),
            (start + 6.0, start + 7.0, "範囲内の古い台詞2"),
            (end + 10.0, end + 11.0, "範囲外の後の台詞"),
        ]
        alt_src = out_dir / "range" / "old-alt.srt"
        alt_src.parent.mkdir(parents=True, exist_ok=True)
        _write_srt(alt_src, old_cues)
        imported = client.post(
            "/api/alt-review/import", headers=AUTH, json={"path": str(alt_src)}
        )
        if imported.status_code != 200:
            failures.append(f"range: 预置第二列失败 {imported.status_code} {imported.text[:200]}")
            print(f"[range] ❌ 预置第二列失败 {imported.text[:200]}", flush=True)
        else:
            print(f"[range] {range_media.name} {start:.0f}–{end:.0f}s：主 Whisper + 副 Qwen …", flush=True)
            probe.reset()
            before = _alt_texts(client)
            started = time.perf_counter()
            created = client.post(
                "/api/jobs",
                headers=AUTH,
                json={
                    "media_id": media_id,
                    "kind": "dual",
                    "engine": "whisper",
                    "secondary_engine": "qwen",
                    "apply": "replace_range",
                    "start": start,
                    "end": end,
                },
            )
            if created.status_code != 201:
                failures.append(f"range: 创建任务失败 {created.status_code} {created.text[:200]}")
                print(f"[range] ❌ {created.text[:200]}", flush=True)
            else:
                snap = _wait(client, created.json()["id"], args.range_timeout)
                elapsed = time.perf_counter() - started
                after = _alt_texts(client)
                result = snap.get("result") or {}
                main = client.get("/api/cues", headers=AUTH).json().get("cues") or []
                outside_before = [c for c in before if c["end"] <= start or c["start"] >= end]
                outside_after = [c for c in after if c["end"] <= start or c["start"] >= end]
                inside_after = [c for c in after if c["start"] >= start - 0.001 and c["end"] <= end + 0.001]
                main_inside = [c for c in main if c["start"] >= start - 0.5 and c["end"] <= end + 0.5]
                scenario = {
                    "status": snap.get("status"),
                    "elapsed_s": round(elapsed, 1),
                    "summary": result.get("summary"),
                    "alt_before": len(before),
                    "alt_after": len(after),
                    "alt_outside_before": outside_before,
                    "alt_outside_after": outside_after,
                    "alt_inside_after": len(inside_after),
                    "main_cues": len(main),
                    "main_inside": len(main_inside),
                    "released": list(probe.released),
                    "engine_calls": list(probe.engine_calls),
                }
                report["scenarios"]["range"] = scenario
                print(
                    f"[range] {snap.get('status')} · {elapsed:.1f}s · 第二列 {len(before)}→{len(after)}"
                    f"（范围内 {len(inside_after)}）· 主稿 {len(main)} · release={probe.released}",
                    flush=True,
                )
                checks = [
                    (snap.get("status") == "done", "任务未完成"),
                    (outside_before == outside_after, "区间外第二列被改动"),
                    (len(inside_after) > 0, "区间内没有替换成副稿"),
                    (len(outside_after) > 0, "区间外旧条目丢失"),
                    (len(main_inside) == len(main), "主稿出现区间外字幕"),
                    (probe.released[:1] == ["whisper"], f"未释放主引擎：{probe.released}"),
                ]
                failures.extend(f"range: {msg}" for ok, msg in checks if not ok)

            # ------------------------------------------------- 3) separation
            print(
                f"[separation] {range_media.name} {start:.0f}–{end:.0f}s：vad_only + 双引擎 …",
                flush=True,
            )
            probe.reset()
            created = client.post(
                "/api/jobs",
                headers=AUTH,
                json={
                    "media_id": media_id,
                    "kind": "dual",
                    "engine": "whisper",
                    "secondary_engine": "qwen",
                    "apply": "replace_range",
                    "start": start,
                    "end": end,
                    "separate_vocals": True,
                    "separate_mode": "vad_only",
                },
            )
            if created.status_code != 201:
                failures.append(f"separation: 创建任务失败 {created.status_code} {created.text[:200]}")
                print(f"[separation] ❌ {created.text[:200]}", flush=True)
            else:
                snap = _wait(client, created.json()["id"], args.range_timeout)
                result = snap.get("result") or {}
                calls = list(probe.engine_calls)
                scenario = {
                    "status": snap.get("status"),
                    "summary": result.get("summary"),
                    "released": list(probe.released),
                    "engine_calls": calls,
                    "separations": list(probe.separations),
                }
                report["scenarios"]["separation"] = scenario
                print(
                    f"[separation] {snap.get('status')} · calls={[(c['engine'], c['start'], c['end'], bool(c['vad_audio'])) for c in calls]}"
                    f" · separations={len(probe.separations)} · release={probe.released}",
                    flush=True,
                )
                checks = [
                    (snap.get("status") == "done", "任务未完成"),
                    (len(calls) == 2, "应恰好跑两遍引擎"),
                    (all(bool(c["vad_audio"]) for c in calls), "ASR 没有走 vad_only 分离参考"),
                    (
                        all(abs(float(c["start"] or 0) - start) < 0.01 for c in calls)
                        and all(abs(float(c["end"] or 0) - end) < 0.01 for c in calls),
                        "两个 pass 的区间不一致",
                    ),
                    (len(probe.separations) == 0, "人声分离缓存未复用（又跑了一次 Demucs）"),
                    ("whisper" in probe.released, "Pass A 后未释放 Whisper"),
                ]
                failures.extend(f"separation: {msg}" for ok, msg in checks if not ok)
    finally:
        probe.restore()

    report["failures"] = failures
    json_path = out_dir / "p2_dual_regression.json"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print()
    if failures:
        print("❌ 失败：")
        for item in failures:
            print(f"  - {item}")
    else:
        print("✅ P2 全部场景通过")
    print(f"结果：{json_path}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
