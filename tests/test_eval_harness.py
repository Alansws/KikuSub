"""评测台公共件测试（纯函数，不加载模型，CI 直接跑）。

看守三件事：句首缺字的判定口径、`--set` 不静默吞键、基线指纹能拦住「素材换了」。
"""

from __future__ import annotations

import json

import numpy as np
import pytest

from tools.eval import scorecard as sc
from tools.eval.score_srt import Cue

REPO_BASELINE = sc.REPO_ROOT / "tools" / "eval" / "baseline.json"


def _card(**overrides) -> dict:
    card = {
        "engine": "qwen",
        "score": {"cer": 0.10, "insertions": 40},
        "onset_missing": {"count": 3},
        "params": {"qwen.vad_threshold": 0.3},
    }
    card.update(overrides)
    return card


def _run(**overrides) -> dict:
    run = {
        "id": "test1.qwen",
        "engine": "qwen",
        "reference": {"name": "Jap_test_perfect.srt"},
        "score": {"cer": 0.10, "insertions": 40},
        "onset_missing": {"count": 3},
        "params": {"qwen.vad_threshold": 0.3},
    }
    run.update(overrides)
    return run


# --------------------------------------------------------------------------- 句首缺字


def test_onset_missing_flags_late_start_and_new_first_char():
    items = sc.onset_missing([Cue(0.0, 2.0, "すっごいおちんちん")], [Cue(1.2, 2.0, "ちんちん")])
    assert len(items) == 1
    assert items[0]["lag_s"] == 1.2
    assert items[0]["ref_text"] == "すっごいおちんちん"


def test_onset_missing_ignores_same_first_char():
    # 起点晚了，但句首还在：这是「整条后移」，不是缺字。
    assert sc.onset_missing([Cue(0.0, 2.0, "こういう服装")], [Cue(1.1, 2.0, "こういう服装")]) == []


def test_onset_missing_ignores_early_start_and_boundary():
    ref = [Cue(1.0, 3.0, "まだだーめ")]
    assert sc.onset_missing(ref, [Cue(0.5, 3.0, "だーめ")]) == []
    # 恰好等于门槛不算（判定是「晚于」）。
    assert sc.onset_missing([Cue(0.0, 3.0, "まだだーめ")], [Cue(0.4, 3.0, "だーめ")]) == []


def test_onset_missing_ignores_uncovered_reference():
    # 完全没被覆盖 = 漏块，交给 score_srt 数，不在句首缺字里重复计。
    assert sc.onset_missing([Cue(5.0, 6.0, "おはよう")], [Cue(0.0, 1.0, "こんばんは")]) == []


def test_onset_missing_ignores_text_split_across_cues():
    # 回归：人工版一句被拆成两条候选时，只看「重叠最多的那条」会把前半句误报成缺字
    #（2026-11-13 实测：Test 一 qwen 因此多报 2 条）。拼起来看首字才是对的。
    ref = [Cue(10.0, 13.0, "そんなに腰ビクつかせちゃって")]
    hyps = [Cue(10.2, 10.6, "そんなに"), Cue(11.4, 12.2, "腰ビクつかせちゃって")]
    assert sc.onset_missing(ref, hyps) == []


def test_onset_missing_flags_when_lead_in_is_really_gone():
    # 真的只有后半句：首字「す」不在，且第一条候选起点晚 >0.4s。
    ref = [Cue(10.0, 13.0, "すっごいおちんちん")]
    hyps = [Cue(11.0, 13.0, "おちんちん")]
    items = sc.onset_missing(ref, hyps)
    assert len(items) == 1
    assert items[0]["hyp_start"] == 11.0
    assert items[0]["hyp_text"] == "おちんちん"


# --------------------------------------------------------------------------- 参数覆写


def test_apply_overrides_rejects_unknown_key():
    with pytest.raises(sc.OverrideError):
        sc.apply_overrides("whisper", ["whisper.vad_onset_gate=snr"])


def test_apply_overrides_rejects_foreign_engine_key():
    with pytest.raises(sc.OverrideError):
        sc.apply_overrides("whisper", ["qwen.vad_threshold=0.3"])


def test_apply_overrides_coerces_types():
    values = sc.apply_overrides(
        "whisper", ["whisper.vad_speech_pad_ms=300", "whisper.strip_nonverbal_edges=false"]
    )
    assert values == {
        "whisper.vad_speech_pad_ms": 300,
        "whisper.strip_nonverbal_edges": False,
    }
    assert isinstance(values["whisper.vad_speech_pad_ms"], int)


def test_apply_overrides_requires_value():
    with pytest.raises(sc.OverrideError):
        sc.apply_overrides("whisper", ["whisper.vad_threshold="])


# --------------------------------------------------------------------------- 评测卡


def _write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_build_card_keeps_fingerprint_and_no_absolute_path(tmp_path):
    reference = _write(tmp_path / "ref.srt", "1\n00:00:01,000 --> 00:00:02,000\nおはよう\n")
    media = tmp_path / "clip.mp4"
    media.write_bytes(b"\x00" * 32)
    score = {"reference_cues": 1, "reference_chars": 4, "cer": 0.1, "insertions": 2}

    card = sc.build_card(
        engine="qwen",
        media=media,
        reference=reference,
        score_result=score,
        resolved_params={"qwen.vad_threshold": 0.3},
        pending_qa=5,
        elapsed_s=12.3456,
        peak_rss_mb=1024,
        onset=[{"ref_start": 1.0}],
        media_duration_s=830.2294,
        captured_at="2026-11-13T00:00:00",
    )
    assert card["schemaVersion"] == sc.SCHEMA_VERSION
    assert card["reference"]["sha1"] == sc.file_sha1(reference)
    assert card["reference"]["name"] == "ref.srt"
    assert card["media"] == {"name": "clip.mp4", "bytes": 32, "duration_s": 830.229}
    assert card["run"]["elapsed_s"] == 12.35
    assert card["onset_missing"]["count"] == 1
    assert set(card["score"]) <= set(sc.SCORE_KEYS)
    assert set(card["env"]) == set(sc.ENV_KEYS)
    assert card["env"]["python"]
    # 卡片要能跨机器比对：不能把工作区绝对路径写进去。
    assert str(tmp_path) not in json.dumps(card, ensure_ascii=False)


def test_format_card_survives_missing_timing():
    text = sc.format_card(
        {
            "engine": "whisper",
            "media": {"name": "a.mp4"},
            "reference": {"name": "r.srt", "sha1": None},
            "run": {"cues": 3},
            "score": {"cer": 0.2},
            "onset_missing": {"count": 0},
            "params": {},
        }
    )
    assert "CER 20.00%" in text
    assert "MPS —" in text


# --------------------------------------------------------------------------- 基线比对


def test_compare_flags_cer_regression_beyond_tolerance():
    result = sc.compare_to_baseline(_card(score={"cer": 0.106, "insertions": 40}), _run())
    assert result["cer_delta_pt"] == pytest.approx(0.6)
    assert result["regressed"] is True


def test_compare_tolerates_noise_band():
    result = sc.compare_to_baseline(_card(score={"cer": 0.104, "insertions": 40}), _run())
    assert result["regressed"] is False


def test_compare_flags_insertion_growth():
    result = sc.compare_to_baseline(_card(score={"cer": 0.10, "insertions": 41}), _run())
    assert result["insertions_delta"] == 1
    assert result["regressed"] is True


def test_compare_flags_env_drift():
    card = _card(env={"python": "3.12.2", "torch": "2.15.0"})
    run = _run(env={"python": "3.12.2", "torch": "2.14.1"})
    result = sc.compare_to_baseline(card, run)
    assert result["env_differ"] is True


def test_compare_ignores_unknown_baseline_env():
    # 早期基线没有 env 字段：不能因为「不知道」就判不可比。
    assert sc.compare_to_baseline(_card(), _run())["env_differ"] is False


def test_compare_reports_param_drift():
    card = _card(params={"qwen.vad_threshold": 0.25})
    result = sc.compare_to_baseline(card, _run())
    assert result["params_differ"] is True


def test_find_run_by_id_and_by_engine_reference():
    baseline = {"runs": [_run(), _run(id="test2.qwen", reference={"name": "Jap_test_2_perfect.srt"})]}
    assert sc.find_run(baseline, engine="qwen", run_id="test2.qwen")["id"] == "test2.qwen"
    found = sc.find_run(baseline, engine="qwen", reference="Jap_test_perfect.srt")
    assert found["id"] == "test1.qwen"
    with pytest.raises(KeyError):
        sc.find_run(baseline, engine="qwen")


# --------------------------------------------------------------------------- fixtures


def test_resolve_fixture_path_prefers_fixtures_dir(tmp_path, monkeypatch):
    monkeypatch.setenv(sc.FIXTURES_ENV, str(tmp_path))
    assert sc.resolve_fixtures().name == tmp_path.name
    local = tmp_path / "a.mp4"
    local.write_bytes(b"x")
    assert sc.resolve_fixture_path("a.mp4", tmp_path) == local.resolve()


def test_fixture_problems_detects_tampering(tmp_path):
    ref = _write(tmp_path / "ref.srt", "1\n00:00:01,000 --> 00:00:02,000\nおはよう\n")
    baseline = {
        "fixtures": {
            "references": {"ref.srt": {"sha1": sc.file_sha1(ref)}},
            "media": {"clip.mp4": {"bytes": 4}},
        }
    }
    assert sc.fixture_problems(baseline, tmp_path) == ["缺素材：" + str(tmp_path / "clip.mp4")]
    (tmp_path / "clip.mp4").write_bytes(b"0123")
    assert sc.fixture_problems(baseline, tmp_path) == []
    ref.write_text("changed", encoding="utf-8")
    assert "指纹不符" in sc.fixture_problems(baseline, tmp_path)[0]


def test_interpreter_warning_only_for_foreign_python(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.setattr(sc, "REPO_ROOT", repo)
    assert sc.venv_python() is None
    assert sc.interpreter_warning() is None

    # 工作区根放一个 .venv：当前解释器（pytest 用的那个）必然不是它。
    venv_python = tmp_path / ".venv" / "bin" / "python"
    venv_python.parent.mkdir(parents=True)
    venv_python.write_text("", encoding="utf-8")
    warning = sc.interpreter_warning()
    assert warning is not None and ".venv" in warning


def test_repo_baseline_is_wellformed():
    baseline = sc.load_baseline(REPO_BASELINE)
    ids = [run["id"] for run in baseline["runs"]]
    assert ids == ["test1.whisper", "test1.qwen", "test2.whisper", "test2.qwen"]
    for run in baseline["runs"]:
        assert len(run["reference"]["sha1"]) == 40
        assert run["score"]["cer"] > 0
        assert run["params"], "基线要存完整参数取值，否则默认值改了也发现不了"
        assert set(run["env"]) == set(sc.ENV_KEYS), "基线要记跑片环境，换解释器会改数字"
    for entry in baseline["fixtures"]["media"].values():
        assert entry["bytes"] > 0


# --------------------------------------------------------------------------- 入口脚本


def test_run_clip_check_fixtures_requires_baseline():
    from tools.eval import run_clip

    assert run_clip.main(
        ["--engine", "qwen", "--media", "a.mp4", "--ref", "a.srt", "--check-fixtures"]
    ) == 2


def test_run_clip_check_fixtures_reports_missing(tmp_path, capsys):
    from tools.eval import run_clip

    code = run_clip.main(
        [
            "--engine", "qwen",
            "--media", "Jap_test.mp4",
            "--ref", "Jap_test_perfect.srt",
            "--fixtures", str(tmp_path),
            "--baseline", str(REPO_BASELINE),
            "--check-fixtures",
        ]
    )
    assert code == 1
    assert "缺素材" in capsys.readouterr().err


def test_run_clip_rejects_unknown_engine(tmp_path):
    from tools.eval import run_clip

    assert run_clip.main(
        ["--engine", "no-such-engine", "--media", "a.mp4", "--ref", "a.srt",
         "--fixtures", str(tmp_path)]
    ) == 2


def test_ab_onset_groups_match_the_route_doc():
    from tools.eval import ab_onset

    assert ab_onset.GROUPS["a0"] == (0, "none")
    assert ab_onset.GROUPS["a1"] == (400, "none")
    assert ab_onset.GROUPS["a2"] == (400, "snr")
    assert ab_onset.GROUPS["a2b"] == (400, "snr_cap")
    assert ab_onset.GROUPS["a3"] == (600, "none")
    # 起点提前全部落在参数表允许的 0–600 区间。
    for pad_ms, _ in ab_onset.GROUPS.values():
        assert 0 <= pad_ms <= 600


def test_ab_onset_duplicate_proxy():
    from tools.eval import ab_onset
    from tools.eval.score_srt import Cue

    cues = [Cue(0, 1, "おはよう"), Cue(1, 2, "おはよう"), Cue(2, 3, "おはよう")]
    assert ab_onset._duplicate_cues(cues) == 2
    # 太短的重复（「うん」）不算：那是正常的对话来回，不是吃进尾音。
    assert ab_onset._duplicate_cues([Cue(0, 1, "うん"), Cue(1, 2, "うん")]) == 0


def test_ab_onset_candidate_path_uses_engine_suffix(tmp_path):
    from tools.eval import ab_onset

    media = tmp_path / "Jap_test_2.mp4"
    assert ab_onset._candidate_path(tmp_path, media, "whisper").name == "Jap_test_2.srt"
    assert ab_onset._candidate_path(tmp_path, media, "qwen").name == "Jap_test_2.qwen.srt"


def test_probe_window_rejects_missing_media(tmp_path):
    from tools.eval import probe_window

    assert probe_window.main(
        ["--media", "nope.mp4", "--ref", "nope.srt", "--fixtures", str(tmp_path)]
    ) == 2


# --------------------------------------------------------------------------- 置信度诊断的统计件


def test_auc_handles_separation_and_ties():
    # 完全分开：错的都更大 → 1.0。
    assert sc.auc([0.1, 0.2, 0.8, 0.9], [False, False, True, True]) == 1.0
    # 完全反向 → 0.0（调用方靠取负来归一方向）。
    assert sc.auc([0.9, 0.8, 0.2, 0.1], [False, False, True, True]) == 0.0
    # 全并列 → 0.5。
    assert sc.auc([0.5] * 4, [False, True, False, True]) == 0.5


def test_auc_ignores_missing_values_and_single_class():
    assert sc.auc([0.1, float("nan"), 0.9], [False, True, True]) is not None
    assert sc.auc([0.1, 0.2], [True, True]) is None


def test_threshold_at_fpr_reports_recall_and_precision():
    values = [0.1, 0.2, 0.3, 0.4, 0.9, 0.95]
    labels = [False, False, False, False, True, True]
    result = sc.threshold_at_fpr(values, labels, fpr=0.0)
    assert result is not None
    assert result["recall"] == 1.0
    assert result["threshold"] == 0.4


# --------------------------------------------------------------------------- 置信度诊断


def test_confidence_label_uses_reference_to_hyp_concatenation():
    from tools.eval import qwen_confidence_diag as diag
    from tools.eval.score_srt import Cue

    refs = [Cue(0.0, 4.0, "あいうえ")]
    # 参考一句被候选切成两条：拼起来与参考一致 → 两条都算对句。
    cues = [Cue(0.0, 2.0, "あい"), Cue(2.0, 4.0, "うえ")]
    labels = diag._label_by_reference(refs, cues)
    assert {item["label"] for item in labels} == {"correct"}
    assert len(labels) == 2


def test_confidence_label_marks_wrong_and_skips_grey_zone():
    from tools.eval import qwen_confidence_diag as diag
    from tools.eval.score_srt import Cue

    refs = [Cue(0.0, 4.0, "あいうえ"), Cue(10.0, 14.0, "かきくけ")]
    cues = [Cue(0.0, 4.0, "かき"), Cue(10.0, 14.0, "かきくけ")]
    labels = {item["cue_id"]: item["label"] for item in diag._label_by_reference(refs, cues)}
    assert labels[id(cues[0])] == "wrong"
    assert labels[id(cues[1])] == "correct"


def test_confidence_onset_stats():
    from tools.eval import qwen_confidence_diag as diag

    silence = np.zeros(16000, dtype=np.float32)
    assert diag._onset_stats(silence, 0.0)[0] == -100.0
    tone = np.full(16000, 0.5, dtype=np.float32)
    db, zcr = diag._onset_stats(tone, 0.0)
    assert -6.5 < db < -5.5
    assert zcr < 0.01


def test_confidence_analysis_respects_feature_direction():
    from tools.eval import qwen_confidence_diag as diag

    # logprob 越低越可疑：错句给更低的均值，方向取负后 AUC 应为 1。
    rows = [
        {"label": "correct", "mean_logprob": -0.05},
        {"label": "correct", "mean_logprob": -0.10},
        {"label": "wrong", "mean_logprob": -0.90},
        {"label": "wrong", "mean_logprob": -0.80},
    ]
    analysis = {item["feature"]: item for item in diag._analysis(rows)}
    assert analysis["mean_logprob"]["auc"] == 1.0
    assert analysis["mean_logprob"]["direction"] == "越小越可疑"
