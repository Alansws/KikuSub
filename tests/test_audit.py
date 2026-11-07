"""质检待核队列：三类问题合并、状态合并、以及一次点击的动作语义。"""

from __future__ import annotations

import json

import pytest

pytest.importorskip("gradio")

import app  # noqa: E402
from transcribe import SubtitleCue  # noqa: E402


def _fixture():
    cues = [
        SubtitleCue(1.0, 1.5, "ねぇ…"),
        SubtitleCue(3.0, 4.14, "ぐぬっ…!"),
        SubtitleCue(10.0, 12.0, "こんにちは"),
    ]
    missed = [
        {"start": 5.0, "end": 5.8, "dur": 0.8, "reason": "empty-after-retry", "peak": 0.08},
        # 峰值过低：报告里会折叠，队列里也不该出现
        {"start": 6.0, "end": 6.4, "dur": 0.4, "reason": "empty-after-retry", "peak": 0.001},
    ]
    stats = {
        "hallucination_drops": 1,
        "suspect_cues": 1,
        "hallucination_spans": [
            {"start": 1.0, "end": 1.5, "dur": 0.5, "text": "ねぇ…", "rule": "short", "verdict": "suspect", "peak": 0.06},
            {"start": 3.0, "end": 4.14, "dur": 1.14, "text": "ぐぬっ…!", "rule": "low-density", "verdict": "dropped", "peak": 0.4},
        ],
    }
    return app.build_audit_items(missed, stats, cues), cues


def test_build_audit_items_merges_three_kinds_by_time_and_skips_silence():
    items, _ = _fixture()
    assert [item["kind"] for item in items] == ["suspect", "dropped", "missed"]
    assert [item["id"] for item in items] == [
        "suspect:1000:1500",
        "dropped:3000:4140",
        "missed:5000:5800",
    ]
    # 低峰值漏句只留在 .missed.json，不进入队列
    assert all(not (item["start"] == 6.0 and item["kind"] == "missed") for item in items)
    assert items[1]["cues"] == [{"start": 3.0, "end": 4.14, "text": "ぐぬっ…!"}]
    assert items[0]["status"] == "pending"
    assert items[2]["plain"]


def test_hidden_missed_count_matches_report_contract():
    _, _ = _fixture()
    spans = [
        {"start": 1.0, "end": 2.0, "dur": 1.0, "peak": 0.5},
        {"start": 3.0, "end": 4.0, "dur": 1.0, "peak": 0.001},
    ]
    assert len(app._visible_missed_spans(spans)) == 1
    assert app._missed_hidden_count(spans) == 1


def test_payload_merges_status_including_legacy_string():
    items, _ = _fixture()
    payload = json.loads(app.make_audit_payload(
        "demo.mp4", items, {items[0]["id"]: "done"}, latest_cue_count=3
    ))
    assert payload["items"][0]["status"] == "done"
    assert payload["items"][1]["status"] == "pending"
    assert payload["counts"]["done"] == 1
    assert payload["counts"]["pending"] == 2
    assert payload["latest_cue_count"] == 3


def test_empty_payload_is_renderable():
    payload = json.loads(app.empty_audit_payload())
    assert payload["items"] == []
    assert payload["counts"]["total"] == 0


def test_qa_actions_mark_restore_delete_and_focus(tmp_path, monkeypatch):
    monkeypatch.setattr(app, "OUTPUT_DIR", tmp_path)
    items, cues = _fixture()
    media = tmp_path / "demo.mp4"
    media.write_bytes(b"x")
    payload = app.make_audit_payload("demo.mp4", items, {}, len(cues))

    # 1) 标记保留：只改状态，不动字幕
    mark = json.dumps({"action": "mark", "id": items[0]["id"], "status": "done", "resolution": "kept"})
    out = app.qa_apply_action(mark, cues, str(media), payload)
    new_payload = json.loads(out[6])
    assert new_payload["items"][0]["status"] == "done"
    assert new_payload["items"][0]["resolution"] == "kept"
    assert len(out[0]) == len(cues)
    assert new_payload["last_action"]["message"].startswith("✅")

    # 1b) 重新放回待核：statuses 清空后必须回到 pending，不能留着 item 里的 done
    reopen = json.dumps({"action": "mark", "id": items[0]["id"], "status": "pending"})
    out = app.qa_apply_action(reopen, out[0], str(media), out[6])
    reopened = json.loads(out[6])
    assert reopened["items"][0]["status"] == "pending"
    assert reopened["items"][0]["resolution"] == ""

    # 2) 恢复被误删的原文：插入一条与区间一致的 cue
    restore = json.dumps({"action": "restore", "id": items[1]["id"]})
    out = app.qa_apply_action(restore, cues, str(media), out[6])
    restored = [cue for cue in out[0] if cue["text"] == "ぐぬっ…!"]
    assert restored and restored[0]["start"] == 3.0
    assert json.loads(out[6])["items"][1]["resolution"] == "restored"

    # 3) 删除短句：从核对台移除，并可 Cmd+Z 撤回
    delete = json.dumps({"action": "delete_cue", "id": items[0]["id"]})
    out = app.qa_apply_action(delete, out[0], str(media), out[6])
    assert all(cue["text"] != "ねぇ…" for cue in out[0])
    assert out[4]  # undo stack 里压入了删除前的快照
    assert json.loads(out[6])["items"][0]["resolution"] == "deleted"

    # 4) 定位编辑：把该条的时间/原文回填给单行精修框
    focus = json.dumps({"action": "focus", "id": items[1]["id"]})
    out = app.qa_apply_action(focus, out[0], str(media), out[6])
    assert out[8] == "00:00:03,000"
    assert out[9] == "00:00:04,140"
    assert out[10] == "ぐぬっ…!"
    assert (tmp_path / "demo.qa.json").exists()


def test_qa_action_on_missing_item_keeps_state(tmp_path, monkeypatch):
    monkeypatch.setattr(app, "OUTPUT_DIR", tmp_path)
    items, cues = _fixture()
    media = tmp_path / "demo.mp4"
    media.write_bytes(b"x")
    payload = app.make_audit_payload("demo.mp4", items, {}, len(cues))
    out = app.qa_apply_action(
        json.dumps({"action": "mark", "id": "missing:000:000"}), cues, str(media), payload
    )
    assert out[0] == app._cues_to_dicts(cues)
    assert out[6] == payload
    assert "失效" in out[3]


def test_keep_suspect_reinserts_missing_cue_and_syncs_table(tmp_path, monkeypatch):
    """“保留”不能只是改个状态：核对台缺这句时必须补回并刷新表格。"""
    monkeypatch.setattr(app, "OUTPUT_DIR", tmp_path)
    items, cues = _fixture()
    media = tmp_path / "demo.mp4"
    media.write_bytes(b"x")
    payload = app.make_audit_payload("demo.mp4", items, {}, len(cues))
    suspect = items[0]
    assert suspect["kind"] == "suspect"
    # 模拟“先设基线、之后重转/删改”：baseline 里恰好没有这句
    baseline = [cue for cue in cues if cue.text != "ねぇ…"]

    out = app.qa_apply_action(
        json.dumps({"action": "mark", "id": suspect["id"], "status": "done", "resolution": "kept"}),
        baseline,
        str(media),
        payload,
    )
    texts = [cue["text"] for cue in out[0]]
    assert "ねぇ…" in texts
    # 表格必须显式刷新（而不是 gr.update），否则会出现“状态已保留、表格里没有”
    assert isinstance(out[1], list) and len(out[1]) == len(out[0])
    assert "补回" in out[3]
    assert out[4]  # 撤销栈记录了补回前的基线
    assert json.loads(out[6])["items"][0]["resolution"] == "kept"


def test_keep_suspect_is_idempotent_when_baseline_already_has_cue(tmp_path, monkeypatch):
    monkeypatch.setattr(app, "OUTPUT_DIR", tmp_path)
    items, cues = _fixture()
    media = tmp_path / "demo.mp4"
    media.write_bytes(b"x")
    payload = app.make_audit_payload("demo.mp4", items, {}, len(cues))
    out = app.qa_apply_action(
        json.dumps({"action": "mark", "id": items[0]["id"], "status": "done", "resolution": "kept"}),
        cues,
        str(media),
        payload,
    )
    assert len(out[0]) == len(cues)
    # 即使状态里已经有这句，也要显式刷新表格，修复“导出有、表格没有”的显示不同步
    assert isinstance(out[1], list) and len(out[1]) == len(out[0])
    assert out[3].startswith("✅ 已保留；核对台已包含")


def test_keep_suspect_does_not_duplicate_manually_edited_cue(tmp_path, monkeypatch):
    """用户改过文字但时间没变时，保留不能把旧文本再插一遍。"""
    monkeypatch.setattr(app, "OUTPUT_DIR", tmp_path)
    items, _ = _fixture()
    media = tmp_path / "demo.mp4"
    media.write_bytes(b"x")
    payload = app.make_audit_payload("demo.mp4", items, {}, 1)
    edited = [SubtitleCue(1.0, 1.5, "ねぇ、聞いて")]
    out = app.qa_apply_action(
        json.dumps({"action": "mark", "id": items[0]["id"], "status": "done", "resolution": "kept"}),
        edited,
        str(media),
        payload,
    )
    assert [cue["text"] for cue in out[0]] == ["ねぇ、聞いて"]


def test_qa_queue_is_empty_after_restart(tmp_path, monkeypatch):
    """质检队列允许同进程刷新恢复，但重启应用后必须默认清空。"""
    monkeypatch.setattr(app, "OUTPUT_DIR", tmp_path)
    items, _ = _fixture()
    media = tmp_path / "demo.mp4"
    media.write_bytes(b"x")
    payload = app.make_audit_payload(
        "demo.mp4", items, {items[0]["id"]: {"status": "done", "resolution": "kept"}}, 3
    )
    app.write_audit_payload(str(media), payload)

    same_run = json.loads(app.load_audit_payload(str(media)))
    assert same_run["items"][0]["status"] == "done"
    assert same_run["session"] == app.AUDIT_SESSION_ID

    # 模拟进程重启：会话 ID 变了，旧 .qa.json 不再带入
    monkeypatch.setattr(app, "AUDIT_SESSION_ID", "new-process-session")
    restarted = json.loads(app.load_audit_payload(str(media)))
    assert restarted["items"] == []
    assert restarted["counts"]["total"] == 0
    assert restarted["session"] == "new-process-session"
