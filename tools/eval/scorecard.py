"""评测台公共件：评测卡、基线比对、fixtures 解析。

`score_srt.py` 只回答「两份 SRT 差多少」，`run_clip.py` 要真的跑模型；把「卡片的形状、
句首缺字判定、基线回归断言」放在这一层，就能在不加载 torch 的 CI 里用纯函数测。

改这里之前先读三条不变量：

1. **卡片只记数字与指纹（sha1 / 字节数），不记绝对路径**——换工作区目录，基线照样能比；
2. **CER 一律走 `score_srt` 的口径**（不剔发声、标点计入），和标定文档那套口径不混用；
3. **基线比对只回答「有没有变差」**；「改善了多少」属于 A/B 表，不在这一层下结论。
   单次转写的 CER 本身有 0.5pt 级噪声（路线文档 §5），所以默认容差就是 0.5pt。
"""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
import platform
import sys
from datetime import datetime
from pathlib import Path

from tools.eval.score_srt import Cue, normalize_text

SCHEMA_VERSION = 1

# 仓库根（tools/eval/scorecard.py → tools/eval → tools → 仓库）
REPO_ROOT = Path(__file__).resolve().parents[2]
# 默认 fixtures：仓库的上一级。本工作区里素材就放在那里（repo/ 是仓库，媒体在外层）。
DEFAULT_FIXTURES_DIR = REPO_ROOT.parent
FIXTURES_ENV = "KIKUSUB_EVAL_FIXTURES"

# 句首被判「缺字」的门槛：字幕起点比人工版晚超过这个值，且首字不同。
ONSET_LAG_S = 0.4

SCORE_KEYS = (
    "reference_cues",
    "hypothesis_cues",
    "reference_chars",
    "hypothesis_chars",
    "cer",
    "substitutions",
    "deletions",
    "insertions",
    "block_accuracy",
    "missed_blocks",
    "max_cue_dur",
    "over_4_3s",
    "particle_start_cues",
    "aux_start_cues",
)

RUN_KEYS = ("cues", "chars", "pending_qa", "elapsed_s", "peak_rss_mb", "peak_mps_mb")

# 跑片环境的指纹。不是洁癖：本机 `python` 是 anaconda（torch 2.14 / silero-vad 5.1），
# 仓库 `.venv` 是 torch 2.15 / silero-vad 6.2；VAD 版本一变，分段就变，CER 能差 2pt 以上。
# 卡片不记这一项，跨解释器的两张卡片会被当成「同一配置的两次跑」。
ENV_KEYS = ("python", "torch", "transformers", "silero-vad", "numpy")


class OverrideError(ValueError):
    """`--set` 的键不认识、或属于别的引擎。宁可报错，也不静默忽略。"""


# --------------------------------------------------------------------------- fixtures


def resolve_fixtures(cli_value: str | Path | None = None) -> Path:
    """素材目录：命令行 > `KIKUSUB_EVAL_FIXTURES` > 仓库上一级。"""
    raw = str(cli_value).strip() if cli_value is not None else ""
    if not raw:
        raw = (os.environ.get(FIXTURES_ENV) or "").strip()
    base = Path(raw).expanduser() if raw else DEFAULT_FIXTURES_DIR
    return base.resolve()


def resolve_fixture_path(value: str | Path, fixtures: Path) -> Path:
    """素材名优先按 fixtures 目录解析；绝对路径与仓库内相对路径原样使用。"""
    path = Path(value).expanduser()
    if path.is_absolute():
        return path
    candidate = Path(fixtures) / path
    if candidate.exists():
        return candidate.resolve()
    return (REPO_ROOT / path).resolve()


# --------------------------------------------------------------------------- 参数覆写


def _param_specs():
    from core import params  # 纯标准库表；放在函数里，模块导入保持轻量

    return params


def apply_overrides(engine: str, pairs: list[str] | tuple[str, ...] | None) -> dict:
    """把 `--set key=value` 校验并转型成该引擎的参数键值。

    不认识的键、或 `qwen.*` 传给 whisper，一律抛 `OverrideError`：
    `core.params.normalize()` 会静默丢掉这类键，评测台上那就是「改了参数但没生效」。
    """
    params = _param_specs()
    out: dict = {}
    for pair in pairs or ():
        raw = str(pair or "").strip()
        if not raw:
            continue
        if "=" not in raw:
            raise OverrideError(f"--set 需要 key=value 形式：{raw!r}")
        key, value = (part.strip() for part in raw.split("=", 1))
        spec = params.BY_KEY.get(key)
        if spec is None:
            sample = ", ".join(s.key for s in params.specs_for(engine)[:3])
            raise OverrideError(f"不认识的参数键：{key!r}（{engine} 的键形如 {sample}）")
        if spec.engine != engine:
            raise OverrideError(f"参数键 {key!r} 属于 {spec.engine}，不能传给 {engine}")
        if not value:
            raise OverrideError(f"参数键 {key!r} 没有给值")
        try:
            out[key] = params.coerce(spec, value)
        except (TypeError, ValueError) as exc:
            raise OverrideError(f"参数键 {key!r} 的值无法解析：{value!r}") from exc
    return out


# --------------------------------------------------------------------------- 句首缺字


def _overlap_s(a: Cue, b: Cue) -> float:
    return max(0.0, min(a.end, b.end) - max(a.start, b.start))


def onset_missing(
    reference: list[Cue],
    hypothesis: list[Cue],
    *,
    min_lag_s: float = ONSET_LAG_S,
) -> list[dict]:
    """句首缺字：字幕起点晚于人工版 `min_lag_s` 以上，且首字不同。

    判定口径与路线文档 §2.1 的整片统计一致：每条参考条取**时间重叠最多**的那条候选，
    不做文本相似度匹配（否则「听成近似音」会被算成边界问题）。
    候选完全没盖住这条参考时不计入——那是「漏块」，`score_srt` 已经在数。
    """
    items: list[dict] = []
    for ref in reference:
        ref_chars = normalize_text(ref.text)
        if not ref_chars:
            continue
        best: Cue | None = None
        best_overlap = 0.0
        for hyp in hypothesis:
            overlap = _overlap_s(ref, hyp)
            if overlap > best_overlap:
                best, best_overlap = hyp, overlap
        if best is None:
            continue
        lag = best.start - ref.start
        if lag > min_lag_s and normalize_text(best.text)[:1] != ref_chars[:1]:
            items.append(
                {
                    "ref_start": round(ref.start, 3),
                    "ref_text": ref.text.strip()[:40],
                    "hyp_start": round(best.start, 3),
                    "hyp_text": best.text.strip()[:40],
                    "lag_s": round(lag, 3),
                }
            )
    return items


# --------------------------------------------------------------------------- 评测卡


def venv_python() -> Path | None:
    """仓库约定的解释器（工作区根的 `.venv`）；不存在时返回 None。"""
    candidate = REPO_ROOT.parent / ".venv" / "bin" / "python"
    return candidate if candidate.exists() else None


def interpreter_warning() -> str | None:
    """当前解释器不是仓库 `.venv` 时给一句提醒。

    不抛错：本机 `python` 是 anaconda，`.venv` 是另一套 torch / silero-vad；
    两者跑同一组参数，Test 一 qwen 的 CER 差 2pt 以上（12.97% vs 10.86%）。
    数字只在同一解释器内可比，所以这一句必须出现在跑片前，而不是事后解释。
    """
    candidate = venv_python()
    if candidate is None:
        return None
    # 不能用 resolve() 比：本机 .venv/bin/python 是指向 anaconda python3 的符号链接，
    # 解析后两者相同，恰好把「跑在 venv 里还是全局里」这个区别抹掉。用 sys.prefix 判断。
    if Path(sys.prefix).resolve() == candidate.parent.parent.resolve():
        return None
    return (
        f"当前解释器 {sys.executable} 不在仓库 .venv（{candidate.parent.parent}）里；"
        "torch / silero-vad 版本可能不同，评测数字与基线不可比。建议用 .venv/bin/python 跑。"
    )


def env_fingerprint() -> dict:
    """跑片环境指纹（只读包元数据，不 import torch）。"""
    out = {"python": platform.python_version()}
    for name in ENV_KEYS[1:]:
        try:
            out[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            out[name] = None
    return out


def file_sha1(path: Path) -> str:
    digest = hashlib.sha1()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_card(
    *,
    engine: str,
    media: Path,
    reference: Path,
    score_result: dict,
    resolved_params: dict | None = None,
    cues: int | None = None,
    chars: int | None = None,
    pending_qa: int | None = None,
    elapsed_s: float | None = None,
    peak_rss_mb: float | None = None,
    peak_mps_mb: float | None = None,
    onset: list[dict] | None = None,
    media_duration_s: float | None = None,
    timerange: tuple[float | None, float | None] = (None, None),
    captured_at: str | None = None,
) -> dict:
    """组装一张评测卡。`resolved_params` 传**该引擎的完整取值**（含默认值），
    这样「代码里的默认值改了」会在基线比对时以 `params_differ` 暴露出来。"""
    media = Path(media)
    reference = Path(reference)
    score = {key: score_result[key] for key in SCORE_KEYS if key in score_result}
    run = {
        "cues": cues if cues is not None else score.get("hypothesis_cues"),
        "chars": chars if chars is not None else score.get("hypothesis_chars"),
        "pending_qa": pending_qa,
        "elapsed_s": None if elapsed_s is None else round(float(elapsed_s), 2),
        "peak_rss_mb": None if peak_rss_mb is None else round(float(peak_rss_mb), 1),
        "peak_mps_mb": None if peak_mps_mb is None else round(float(peak_mps_mb), 1),
    }
    return {
        "schemaVersion": SCHEMA_VERSION,
        "capturedAt": captured_at or datetime.now().isoformat(timespec="seconds"),
        "engine": engine,
        "media": {
            "name": media.name,
            "bytes": media.stat().st_size if media.exists() else None,
            "duration_s": None if media_duration_s is None else round(media_duration_s, 3),
        },
        "reference": {
            "name": reference.name,
            "sha1": file_sha1(reference) if reference.exists() else None,
            "cues": score.get("reference_cues"),
            "chars": score.get("reference_chars"),
        },
        "env": env_fingerprint(),
        "params": dict(resolved_params or {}),
        "run": run,
        "score": score,
        "onset_missing": {"count": len(onset or []), "items": list(onset or [])},
        "range": [timerange[0], timerange[1]],
    }


def _mb(value: float | None) -> str:
    return "—" if value is None else f"{value:.0f} MB"


def _int(value) -> str:
    return "—" if value is None else str(value)


def _secs(value: float | None) -> str:
    return "—" if value is None else f"{value:.1f}s"


def _params_note(params: dict, defaults: dict) -> str:
    if not params:
        return "—（默认）"
    changed = {k: v for k, v in params.items() if defaults.get(k) != v}
    if not changed:
        return "—（默认）"
    return " ".join(f"{k.split('.', 1)[-1]}={v}" for k, v in sorted(changed.items()))


def format_card(card: dict, defaults: dict | None = None) -> str:
    """人读的一屏摘要（stdout 用）。字段与 JSON 一一对应，不另算指标。"""
    media = card.get("media") or {}
    ref = card.get("reference") or {}
    run = card.get("run") or {}
    score = card.get("score") or {}
    onset = card.get("onset_missing") or {}
    dur = media.get("duration_s")
    lines = [
        f"引擎 {card.get('engine')} ｜ 素材 {media.get('name')}"
        + (f"（{dur:.1f}s）" if dur else ""),
        f"参考 {ref.get('name')}（sha1 {(ref.get('sha1') or '—')[:8]}，"
        f"{_int(ref.get('cues'))} 条 / {_int(ref.get('chars'))} 字）",
        f"卡片 {card.get('capturedAt')} ｜ 参数："
        f"{_params_note(card.get('params') or {}, defaults or {})}",
        f"转写 {_int(run.get('cues'))} 条 / {_int(run.get('chars'))} 字 ｜ "
        f"质检 {_int(run.get('pending_qa'))} 项 ｜ 耗时 {_secs(run.get('elapsed_s'))} ｜ "
        f"峰值 RSS {_mb(run.get('peak_rss_mb'))} / MPS {_mb(run.get('peak_mps_mb'))}",
        f"CER {score.get('cer', 0.0) * 100:.2f}% "
        f"(S={score.get('substitutions')} D={score.get('deletions')} "
        f"I={score.get('insertions')}) ｜ 块均 {score.get('block_accuracy', 0.0) * 100:.1f}% ｜ "
        f"漏块 {_int(score.get('missed_blocks'))}",
        f"句首缺字 {_int(onset.get('count'))} 条（起点晚 >{ONSET_LAG_S}s 且首字不同）",
    ]
    return "\n".join(lines)


def format_onset(items: list[dict]) -> str:
    if not items:
        return "句首缺字：无"
    rows = ["句首缺字明细（参考起 → 候选起，lag）："]
    for item in items:
        rows.append(
            f"  {item['ref_start']:8.2f} → {item['hyp_start']:8.2f} "
            f"(+{item['lag_s']:.2f}s)  {item['ref_text']}  |  {item['hyp_text']}"
        )
    return "\n".join(rows)


# --------------------------------------------------------------------------- 基线


def load_baseline(path: Path) -> dict:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if payload.get("schemaVersion") != SCHEMA_VERSION:
        raise ValueError(
            f"基线版本不匹配：文件是 {payload.get('schemaVersion')}，"
            f"代码要 {SCHEMA_VERSION}（重新采集，不要就地改数）"
        )
    if not payload.get("runs"):
        raise ValueError("基线里没有 runs；采集方式见 tools/eval/README.md")
    return payload


def find_run(
    baseline: dict,
    *,
    engine: str,
    reference: str | None = None,
    run_id: str | None = None,
) -> dict:
    """按 id 或（引擎 + 参考文件名）找基线条目；找不到就抛，不做「取第一条」。"""
    runs = baseline.get("runs") or []
    if run_id:
        for run in runs:
            if run.get("id") == run_id:
                return run
        raise KeyError(f"基线里没有 id={run_id!r}；有：{', '.join(r.get('id', '?') for r in runs)}")
    matched = [
        run
        for run in runs
        if run.get("engine") == engine
        and (reference is None or (run.get("reference") or {}).get("name") == reference)
    ]
    if len(matched) == 1:
        return matched[0]
    if not matched:
        raise KeyError(f"基线里没有 {engine} / {reference or '任一参考'} 的条目")
    raise KeyError(
        f"{engine} 有多条基线（{', '.join(r.get('id', '?') for r in matched)}），请用 --against 指定"
    )


def compare_to_baseline(card: dict, run: dict, *, tolerance_pt: float = 0.5) -> dict:
    """与基线条目比：只回答「有没有变差」。

    - CER 涨超过 `tolerance_pt`（默认 0.5，见路线文档 §5 的噪声带）→ 回归；
    - 插入字数变多 → 回归（升级门槛要求「插入不涨」）；
    - 参数取值与基线不同 → `params_differ`，此时结论不可比，调用方应提示重采基线。
    """
    current = card.get("score") or {}
    base = run.get("score") or {}
    cer_delta = round((float(current.get("cer", 0.0)) - float(base.get("cer", 0.0))) * 100, 2)
    insertions_delta = int(current.get("insertions", 0)) - int(base.get("insertions", 0))
    onset_now = (card.get("onset_missing") or {}).get("count")
    onset_base = (run.get("onset_missing") or {}).get("count")
    onset_delta = None if onset_now is None or onset_base is None else int(onset_now - onset_base)
    params_differ = dict(card.get("params") or {}) != dict(run.get("params") or {})
    env_now = card.get("env") or {}
    env_base = run.get("env") or {}
    env_differ = bool(env_now and env_base and env_now != env_base)
    return {
        "baseline_id": run.get("id", ""),
        "cer_delta_pt": cer_delta,
        "insertions_delta": insertions_delta,
        "onset_missing_delta": onset_delta,
        "params_differ": params_differ,
        "env_differ": env_differ,
        "tolerance_pt": tolerance_pt,
        "regressed": bool(cer_delta > tolerance_pt or insertions_delta > 0),
    }


def format_comparison(result: dict) -> str:
    sign = "+" if result["cer_delta_pt"] >= 0 else ""
    onset = result.get("onset_missing_delta")
    onset_text = "—" if onset is None else f"{onset:+d}"
    lines = [
        f"对比基线 {result['baseline_id']}：CER {sign}{result['cer_delta_pt']:.2f}pt ｜ "
        f"插入 {result['insertions_delta']:+d} 字 ｜ 句首缺字 {onset_text} 条"
    ]
    if result.get("params_differ"):
        lines.append("⚠ 参数取值与基线不同，这组数字不可比（改动参数后请重采基线或另起一条）")
    if result.get("env_differ"):
        lines.append("⚠ 解释器/torch/VAD 版本与基线不同，这组数字不可比（换环境后请重采基线）")
    lines.append("❌ 回归：CER 涨超容差或插入变多" if result["regressed"] else "✅ 不劣于基线")
    return "\n".join(lines)


def fixture_problems(baseline: dict, fixtures: Path) -> list[str]:
    """按基线里的指纹核对素材；返回问题清单（空表示对得上）。"""
    problems: list[str] = []
    fixtures = Path(fixtures)
    for name, entry in ((baseline.get("fixtures") or {}).get("references") or {}).items():
        path = fixtures / name
        if not path.is_file():
            problems.append(f"缺参考字幕：{path}")
            continue
        expected = (entry or {}).get("sha1")
        if expected and file_sha1(path) != expected:
            problems.append(f"参考字幕指纹不符：{path}（基线 {expected[:8]}）")
    for name, entry in ((baseline.get("fixtures") or {}).get("media") or {}).items():
        path = fixtures / name
        if not path.is_file():
            problems.append(f"缺素材：{path}")
            continue
        expected = (entry or {}).get("bytes")
        if expected and path.stat().st_size != expected:
            problems.append(f"素材大小不符：{path}（基线 {expected} 字节）")
    return problems
