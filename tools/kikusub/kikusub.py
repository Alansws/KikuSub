#!/usr/bin/env python3
"""`kikusub` — 连接正在运行的 KikuSub，读取工程证据、提交审阅提案。

它是**纯 stdlib 客户端**（urllib + json + pathlib），不 import `core/`、不加载
模型、不读写字幕。端口与 token 来自 sidecar 写的 `runtime.json`（0600）。

三条红线：

1. **只读证据**：`project / cues / cue / qa / listen` 都不改字幕；`listen` 只是
   用另一个引擎把这一句重听一遍，输出文本，不写回会话。
2. **提案只提交、不应用**：`propose` 走现有 `/api/ai/proposal`、
   `/api/ai/structure/from-json`、`/api/ai/reshape/proposal`，digest 校验由
   服务端完成；应用永远由用户在 KikuSub 里点。
3. **不给 Agent 猜路径**：找不到运行中的 App 时直接报清楚，不扫描磁盘、不新建会话。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import unicodedata
import urllib.error
import urllib.request
from pathlib import Path

DEFAULT_TIMEOUT = 30.0
JOB_TIMEOUT = 1800.0

EXIT_USAGE = 2
EXIT_NOT_RUNNING = 3
EXIT_JOB_FAILED = 4


class CliError(Exception):
    def __init__(self, message: str, code: int = EXIT_USAGE) -> None:
        super().__init__(message)
        self.code = code


# --------------------------------------------------------------------------- 运行期发现


def runtime_candidates(explicit: str | None = None) -> list[Path]:
    """按「显式 → 环境变量 → 打包态 → 源码仓库 → 当前目录」找 runtime.json。"""
    candidates: list[Path] = []
    if explicit:
        candidates.append(Path(explicit).expanduser())
    env = (os.environ.get("KIKUSUB_RUNTIME") or "").strip()
    if env:
        candidates.append(Path(env).expanduser())
    home = Path.home()
    # 打包态：主进程（desktop/main/main.cjs，非开发模式）把 KIKUSUB_OUTPUT_DIR 设成
    # `~/Library/Application Support/KikuSub/outputs`，sidecar 就把 runtime.json 写在这里。
    # 这个候选必须排在第一个，终端直接敲 `kikusub` 才不需要 --runtime。
    # 改动路径时同步 `desktop/main/main.cjs` 的 dataDir()/baseDir() 与
    # tests/test_kikusub_cli.py::test_default_runtime_path_matches_packaged_app。
    candidates.append(home / "Library" / "Application Support" / "KikuSub" / "outputs" / "runtime.json")
    candidates.append(home / "Library" / "Application Support" / "KikuSub" / "runtime.json")
    # 源码仓库里跑：tools/kikusub/kikusub.py → 仓库根 / outputs
    here = Path(__file__).resolve()
    for parent in list(here.parents)[:5]:
        candidates.append(parent / "outputs" / "runtime.json")
    candidates.append(Path.cwd() / "outputs" / "runtime.json")
    seen: set[Path] = set()
    unique: list[Path] = []
    for path in candidates:
        try:
            key = path.resolve()
        except OSError:
            key = path
        if key in seen:
            continue
        seen.add(key)
        unique.append(path)
    return unique


def read_runtime(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text("utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


class Client:
    def __init__(self, runtime: dict) -> None:
        self.port = int(runtime.get("port") or 0)
        self.token = str(runtime.get("token") or "")
        self.session_id = str(runtime.get("session_id") or "")
        self.pid = int(runtime.get("pid") or 0)
        self.version = str(runtime.get("api_version") or "")
        self.base = f"http://127.0.0.1:{self.port}"

    def request(
        self,
        method: str,
        path: str,
        *,
        body: dict | None = None,
        timeout: float = DEFAULT_TIMEOUT,
        raw: bool = False,
    ):
        data = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(self.base + path, data=data, method=method)
        request.add_header("Authorization", f"Bearer {self.token}")
        if self.session_id:
            request.add_header("X-Kikusub-Session", self.session_id)
        if data is not None:
            request.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                payload = response.read()
                if raw:
                    return payload
                return json.loads(payload.decode("utf-8"))
        except urllib.error.HTTPError as exc:
            payload = exc.read()
            detail = ""
            errors: list[str] = []
            try:
                parsed = json.loads(payload.decode("utf-8"))
                detail = str(parsed.get("detail") or "")
                errors = [str(item) for item in (parsed.get("errors") or [])]
            except (ValueError, UnicodeDecodeError):
                detail = payload.decode("utf-8", "replace")[:400]
            message = detail or f"HTTP {exc.code}"
            if errors:
                message += "\n  - " + "\n  - ".join(errors)
            raise CliError(message, EXIT_USAGE) from exc
        except urllib.error.URLError as exc:
            raise CliError(f"连接 KikuSub 失败：{exc.reason}（App 可能刚退出）", EXIT_NOT_RUNNING) from exc

    def get(self, path: str, **kwargs):
        return self.request("GET", path, **kwargs)

    def post(self, path: str, body: dict, **kwargs):
        return self.request("POST", path, body=body, **kwargs)


def connect(explicit: str | None) -> Client:
    tried: list[str] = []
    for path in runtime_candidates(explicit):
        if not path.exists():
            continue
        data = read_runtime(path)
        if not data:
            tried.append(f"{path}（内容不合法）")
            continue
        pid = int(data.get("pid") or 0)
        if not _pid_alive(pid):
            tried.append(f"{path}（pid {pid} 已退出，是旧文件）")
            continue
        client = Client(data)
        try:
            client.get("/api/health", timeout=3)
        except CliError as exc:
            tried.append(f"{path}（{exc}）")
            continue
        if not client.session_id:
            raise CliError(
                "KikuSub 正在运行，但界面还没建立会话。先把 KikuSub 窗口打开（或切到主界面）再试。",
                EXIT_NOT_RUNNING,
            )
        return client
    detail = "\n  ".join(tried) if tried else "没有找到 runtime.json"
    raise CliError(
        "没有找到正在运行的 KikuSub。先打开应用，再运行 `kikusub`。\n  已检查：\n  " + detail,
        EXIT_NOT_RUNNING,
    )


# --------------------------------------------------------------------------- 输出


def _width(text: str) -> int:
    return sum(2 if unicodedata.east_asian_width(ch) in "WF" else 1 for ch in text)


def _pad(text: str, width: int) -> str:
    return text + " " * max(0, width - _width(text))


def table(headers: list[str], rows: list[list[str]], *, max_widths: list[int] | None = None) -> str:
    widths = [_width(item) for item in headers]
    for row in rows:
        for index, cell in enumerate(row):
            width = _width(str(cell))
            if max_widths and index < len(max_widths):
                width = min(width, max_widths[index])
            widths[index] = max(widths[index], width)
    lines = ["  ".join(_pad(header, widths[i]) for i, header in enumerate(headers)).rstrip()]
    lines.append("  ".join("-" * width for width in widths))
    for row in rows:
        cells = []
        for index, cell in enumerate(row):
            text = str(cell)
            limit = max_widths[index] if max_widths and index < len(max_widths) else 0
            if limit and _width(text) > limit:
                text = _truncate(text, limit)
            cells.append(_pad(text, widths[index]))
        lines.append("  ".join(cells).rstrip())
    return "\n".join(lines)


def _truncate(text: str, limit: int) -> str:
    out = ""
    for char in text:
        if _width(out + char) > limit - 1:
            return out + "…"
        out += char
    return text


def _tc(seconds: float) -> str:
    total = max(0.0, float(seconds or 0.0))
    hours, rest = divmod(int(total), 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def _db(value) -> str:
    return "—" if value is None else f"{float(value):.1f}"


def _json_out(payload: dict) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


# --------------------------------------------------------------------------- 命令


def cmd_project(client: Client, args) -> dict:
    config = client.get("/api/config")
    session = client.get("/api/session")
    cues = client.get("/api/cues")
    proposals = client.get("/api/proposals/status")
    media = session.get("media") or {}
    source = session.get("review_source") or {}
    payload = {
        "app": {
            "version": config.get("version"),
            "url": client.base,
            "pid": client.pid,
        },
        "media": {
            "path": media.get("path"),
            "name": media.get("name") or (Path(media.get("path") or "").name),
            "duration": media.get("duration"),
            "id": media.get("id") or session.get("media_id"),
        },
        "cues": {
            "count": cues.get("count", 0),
            "digest": cues.get("digest"),
            "source": source,
        },
        "proposals": proposals.get("items") or [],
        "output_dir": config.get("output_dir"),
        "export_dir": config.get("export_dir"),
    }
    if args.json:
        _json_out(payload)
        return payload
    print(f"KikuSub {config.get('version') or '?'}  ·  {client.base}  ·  pid {client.pid}")
    if media:
        print(
            f"媒体    {media.get('path') or '—'}\n"
            f"        {_tc(float(media.get('duration') or 0))}  ·  id {media.get('id') or '—'}"
        )
    else:
        print("媒体    —（还没打开影片）")
    print(
        f"字幕    {cues.get('count', 0)} 条  ·  来源 {source.get('engine') or '—'}"
        f"  ·  {source.get('name') or '—'}"
    )
    print(f"指纹    {cues.get('digest') or '—'}")
    items = payload["proposals"]
    if items:
        print("提案    " + "、".join(f"{item['kind']}{('/' + item['lang']) if item.get('lang') else ''}" for item in items))
    else:
        print("提案    —")
    print(f"导出    {config.get('export_dir') or '—'}")
    return payload


def _decode_srt(path: str, lang: str) -> str:
    data = Path(path).expanduser().read_bytes()
    for encoding in ("utf-8-sig", "utf-8", "utf-16"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise CliError(f"读不出这个文件的文本（尝试过 UTF-8/UTF-16）：{path}")


def _cue_metrics(client: Client, start: int, end: int, enabled: bool) -> dict:
    if not enabled or end < start:
        return {"items": {}, "vocals_cached": None}
    payload = client.get(f"/api/evidence/cues?start={start}&end={end}", timeout=120)
    return {
        "items": {int(item["i"]): item for item in payload.get("items") or []},
        "vocals_cached": payload.get("vocals_cached"),
    }


def _alt_rows(client: Client) -> dict[int, dict]:
    try:
        payload = client.get("/api/alt-review?diff=1")
    except CliError:
        return {}
    rows = payload.get("rows") or []
    mapping: dict[int, dict] = {}
    for row in rows:
        for index in row.get("a_indices") or []:
            mapping[int(index) + 1] = row
    return mapping


def cmd_cues(client: Client, args) -> dict:
    snapshot = client.get("/api/cues")
    cues = snapshot.get("cues") or []
    total = len(cues)
    start = max(1, int(args.start))
    end = min(total, int(args.end)) if args.end else total
    if start > end:
        raise CliError(f"范围不合法：第 {start}–{end} 条（共 {total} 条）")
    window = cues[start - 1 : end]
    for offset, cue in enumerate(window, start=start):
        cue["i"] = offset

    metric_payload = _cue_metrics(client, start, end, not args.no_metrics)
    metrics = metric_payload["items"]
    alt = _alt_rows(client) if args.with_b else {}
    items = []
    for cue in window:
        index = cue["i"]
        item = {
            "i": index,
            "start": cue.get("start"),
            "end": cue.get("end"),
            "text": cue.get("text"),
            "raw_dbfs": (metrics.get(index) or {}).get("raw_dbfs"),
            "vocals_dbfs": (metrics.get(index) or {}).get("vocals_dbfs"),
        }
        if args.with_b:
            row = alt.get(index)
            item["b_text"] = (row or {}).get("b_text")
            item["b_kind"] = (row or {}).get("kind")
        items.append(item)
    payload = {
        "total": total,
        "from": start,
        "to": end,
        "vocals_cached": metric_payload["vocals_cached"],
        "items": items,
    }
    if args.json:
        _json_out(payload)
        return payload
    headers = ["#", "开始", "结束", "raw dBFS", "vocals dBFS", "文本"]
    if args.with_b:
        headers.insert(5, "B 版")
    rows = []
    for item in items:
        row = [
            str(item["i"]),
            _tc(item["start"]),
            _tc(item["end"]),
            _db(item["raw_dbfs"]),
            _db(item["vocals_dbfs"]),
        ]
        if args.with_b:
            row.append(item.get("b_text") or "—")
        row.append(item["text"] or "")
        rows.append(row)
    print(table(headers, rows, max_widths=[6, 8, 8, 9, 11] + ([40] if args.with_b else []) + [60]))
    print(f"\n{total} 条 · 显示第 {start}–{end} 条 · 人声缓存 {'有' if payload['vocals_cached'] else '无'}")
    return payload


def cmd_cue(client: Client, args) -> dict:
    index = int(args.index)
    payload = client.get(f"/api/evidence/cues/{index}?with_b={'1' if args.with_b else '0'}")
    evidence: dict = {}
    if args.evidence:
        folder = Path(args.evidence).expanduser() / f"cue-{index:04d}"
        folder.mkdir(parents=True, exist_ok=True)
        frame = client.get(f"/api/evidence/cues/{index}/frame", raw=True, timeout=90)
        (folder / "frame.jpg").write_bytes(frame)
        evidence["frame"] = str(folder / "frame.jpg")
        audio = client.get(f"/api/evidence/cues/{index}/audio?track=original", raw=True, timeout=90)
        (folder / "audio-original.wav").write_bytes(audio)
        evidence["audio"] = str(folder / "audio-original.wav")
        if payload.get("vocals_cached"):
            try:
                vocals = client.get(
                    f"/api/evidence/cues/{index}/audio?track=vocals", raw=True, timeout=90
                )
                (folder / "audio-vocals.wav").write_bytes(vocals)
                evidence["vocals"] = str(folder / "audio-vocals.wav")
            except CliError as exc:
                evidence["vocals_error"] = str(exc)
    payload["evidence"] = evidence
    if args.json:
        _json_out(payload)
        return payload
    print(f"第 {index} 句  {_tc(payload['start'])} → {_tc(payload['end'])}")
    print(f"原文    {payload.get('text') or '—'}")
    if args.with_b:
        b = payload.get("b")
        print(f"B 版    {b.get('text') if b else '—'}")
    print(
        f"电平    raw {_db(payload.get('raw_dbfs'))} dBFS  ·  "
        f"vocals {_db(payload.get('vocals_dbfs'))} dBFS"
        + ("" if payload.get("vocals_cached") else "（未缓存分离人声）")
    )
    if evidence:
        print("证据    " + "  ".join(f"{key}={value}" for key, value in evidence.items()))
    return payload


def cmd_qa(client: Client, args) -> dict:
    payload = client.get("/api/qa")
    items = payload.get("items") or []
    if args.kind:
        items = [item for item in items if (item.get("kind") or "") == args.kind]
    if args.limit:
        items = items[: int(args.limit)]
    if args.json:
        _json_out({**payload, "items": items})
        return payload
    counts: dict[str, int] = {}
    for item in payload.get("items") or []:
        kind = str(item.get("kind") or "其它")
        counts[kind] = counts.get(kind, 0) + 1
    if counts:
        print("队列    " + "  ".join(f"{kind} {count}" for kind, count in sorted(counts.items())))
    rows = [
        [
            str(item.get("index") or "—"),
            _tc(float(item.get("start") or 0)),
            str(item.get("kind") or "—"),
            (item.get("text") or "")[:40],
            (item.get("reason") or "")[:50],
        ]
        for item in items
    ]
    if rows:
        print(table(["#", "时间", "类型", "文本", "原因"], rows, max_widths=[6, 8, 12, 42, 52]))
    else:
        print("队列为空")
    return payload


def _default_engine(client: Client) -> str:
    config = client.get("/api/config")
    engines = [item for item in (config.get("engines") or []) if item.get("reviewable")]
    session = client.get("/api/session")
    used = str((session.get("review_source") or {}).get("engine") or "").lower()
    for key in ("qwen", "whisper"):
        for item in engines:
            if item.get("key") == key and key not in used:
                return key
    if engines:
        return str(engines[0]["key"])
    raise CliError("这个版本的 KikuSub 没有可复核引擎")


def cmd_listen(client: Client, args) -> dict:
    snapshot = client.get("/api/cues")
    cues = snapshot.get("cues") or []
    index = int(args.index)
    if index < 1 or index > len(cues):
        raise CliError(f"第 {index} 句不存在（共 {len(cues)} 条）")
    cue = cues[index - 1]
    engine = args.engine or _default_engine(client)
    body = {
        "media_id": (client.get("/api/session").get("media") or {}).get("id") or "",
        "kind": "compare",
        "engine": engine,
        "separate_vocals": bool(args.separate),
        "ranges": [
            {
                "index": index - 1,
                "start": float(cue["start"]),
                "end": float(cue["end"]),
                "prev_end": float(cues[index - 2]["end"]) if index > 1 else None,
                "next_start": float(cues[index]["start"]) if index < len(cues) else None,
            }
        ],
    }
    if not body["media_id"]:
        raise CliError("当前会话没有绑定媒体")
    job = client.post("/api/jobs", body)
    job_id = str(job.get("id") or "")
    if not job_id:
        raise CliError("服务端没有返回任务 id")
    started = time.time()
    last_stage = ""
    while True:
        if time.time() - started > float(args.timeout):
            raise CliError(f"重听超时（{args.timeout:.0f}s），任务仍在跑：{job_id}", EXIT_JOB_FAILED)
        state = client.get(f"/api/jobs/{job_id}", timeout=15)
        status = state.get("status")
        stage = str(state.get("stage") or "")
        if stage and stage != last_stage and not args.json:
            print(f"… {stage}", file=sys.stderr)
            last_stage = stage
        if status in {"done", "error", "cancelled"}:
            break
        time.sleep(0.4)
    if status != "done":
        raise CliError(f"重听失败：{state.get('error') or status}", EXIT_JOB_FAILED)
    result = state.get("result") or {}
    text = ""
    for item in result.get("texts") or []:
        if int(item.get("index", -1)) == index - 1:
            text = str(item.get("text") or "")
            break
    payload = {
        "cue": {
            "i": index,
            "start": cue["start"],
            "end": cue["end"],
            "text": cue.get("text"),
        },
        "listen": {
            "engine": result.get("engine") or engine,
            "engine_name": result.get("engine_name") or engine,
            "separate": bool(result.get("separate")),
            "text": text,
            "elapsed": result.get("elapsed"),
        },
    }
    if args.json:
        _json_out(payload)
        return payload
    print(f"第 {index} 句  {_tc(cue['start'])} → {_tc(cue['end'])}")
    print(f"当前    {cue.get('text') or '—'}")
    mode = "分离人声" if payload["listen"]["separate"] else "原声"
    print(f"重听    [{payload['listen']['engine_name']} · {mode}] {text or '—'}")
    return payload


def cmd_propose(client: Client, args) -> dict:
    path = Path(args.file).expanduser()
    if not path.exists():
        raise CliError(f"提案文件不存在：{path}")
    if args.kind == "structure":
        text = _decode_srt(path, "")
        payload = client.post("/api/ai/structure/from-json", {"text": text})
        summary = {
            "kind": "structure",
            "path": payload.get("path"),
            "ops": len(payload.get("ops") or []),
            "summary": payload.get("summary"),
            "warnings": payload.get("warnings") or [],
        }
    elif args.kind == "reshape":
        text = _decode_srt(path, "")
        body = {"text": text, "from_index": int(args.start), "to_index": args.end}
        payload = client.post("/api/ai/reshape/proposal", body)
        summary = {
            "kind": "reshape",
            "path": payload.get("path"),
            "count": payload.get("count"),
            "range": payload.get("range"),
        }
    else:
        try:
            data = json.loads(path.read_text("utf-8"))
        except ValueError as exc:
            raise CliError(f"不是合法的提案 JSON：{path}（{exc}）") from exc
        if not isinstance(data, dict):
            raise CliError("提案 JSON 顶层必须是对象（见 docs/contracts/ai-proposal.md）")
        body = {"kind": args.kind, "proposal": data}
        if args.kind == "translate":
            body["lang"] = args.lang
        payload = client.post("/api/ai/proposal", body)
        summary = {
            "kind": args.kind,
            "path": payload.get("path"),
            "count": payload.get("count"),
            "range": payload.get("range"),
            "warnings": payload.get("warnings") or [],
        }
    summary["next"] = "已提交到审阅队列；回 KikuSub 对照后手动应用，agent 不直接改字幕。"
    if args.json:
        _json_out(summary)
        return summary
    print(f"已提交  {summary['kind']} → {summary.get('path')}")
    if summary.get("count") is not None:
        print(f"条目    {summary['count']} 条" + (f"  ·  范围 {summary['range']}" if summary.get("range") else ""))
    if summary.get("ops") is not None:
        print(f"操作    {summary['ops']} 项  ·  {summary.get('summary') or ''}")
    for warning in summary.get("warnings") or []:
        print(f"提醒    {warning}")
    print(summary["next"])
    return summary


def cmd_status(client: Client, args) -> dict:
    payload = client.get("/api/proposals/status")
    if args.json:
        _json_out(payload)
        return payload
    print(f"提案版本  {payload.get('revision') or '—'}")
    for item in payload.get("items") or []:
        print(f"  {item['kind']:<10} {item.get('lang') or '':<8} {item['path']}")
    return payload


# --------------------------------------------------------------------------- argparse


def build_parser() -> argparse.ArgumentParser:
    # 选项写在子命令前后都要能用：子解析器继承同一组参数，但默认值必须 SUPPRESS，
    # 否则 `kikusub --runtime X project` 会被子解析器的 None 覆盖（踩过）。
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--json", action="store_true", help="输出机器可读 JSON（agent 默认用它）")
    common.add_argument("--runtime", default=None, help="runtime.json 路径（默认自动发现）")

    child = argparse.ArgumentParser(add_help=False)
    child.add_argument("--json", action="store_true", default=argparse.SUPPRESS)
    child.add_argument("--runtime", default=argparse.SUPPRESS)

    parser = argparse.ArgumentParser(
        prog="kikusub",
        description="连接正在运行的 KikuSub：读工程/证据、提交审阅提案（不改字幕）。",
        parents=[common],
    )
    sub = parser.add_subparsers(dest="command", required=True)

    project = sub.add_parser("project", parents=[child], help="工程概览")
    project.set_defaults(func=cmd_project)

    cues = sub.add_parser("cues", parents=[child], help="字幕表 + 电平证据")
    cues.add_argument("--from", dest="start", type=int, default=1, help="起始条号（1 起）")
    cues.add_argument("--to", dest="end", type=int, default=0, help="结束条号（含）")
    cues.add_argument("--with-b", action="store_true", help="附带第二版文本")
    cues.add_argument("--no-metrics", action="store_true", help="不查 raw/vocals dBFS")
    cues.set_defaults(func=cmd_cues)

    cue = sub.add_parser("cue", parents=[child], help="单句详情 + 图片/音频证据导出")
    cue.add_argument("index", type=int)
    cue.add_argument("--with-b", action="store_true", help="附带第二版文本")
    cue.add_argument("--evidence", default="", help="导出目录（生成 frame.jpg / audio-original.wav）")
    cue.set_defaults(func=cmd_cue)

    qa = sub.add_parser("qa", parents=[child], help="质检待核队列")
    qa.add_argument("--kind", default="", help="只显示某一类（missed / suspect / …）")
    qa.add_argument("--limit", type=int, default=0, help="最多显示多少条（0 = 全部）")
    qa.set_defaults(func=cmd_qa)

    listen = sub.add_parser("listen", parents=[child], help="用另一个引擎只读重听一句")
    listen.add_argument("index", type=int)
    listen.add_argument("--engine", default="", help="引擎 key（默认挑一个与主稿不同的可复核引擎）")
    listen.add_argument("--separate", action="store_true", help="先分离人声，只听分离轨")
    listen.add_argument("--timeout", type=float, default=JOB_TIMEOUT, help="等待秒数")
    listen.set_defaults(func=cmd_listen)

    propose = sub.add_parser("propose", parents=[child], help="提交审阅提案（不应用）")
    propose_sub = propose.add_subparsers(dest="kind", required=True)

    polish = propose_sub.add_parser("polish", parents=[child], help="润色提案 JSON")
    polish.add_argument("--file", required=True)
    polish.set_defaults(func=cmd_propose)

    translate = propose_sub.add_parser("translate", parents=[child], help="翻译提案 JSON")
    translate.add_argument("--file", required=True)
    translate.add_argument("--lang", required=True, help="目标语种（如 zh-Hans）")
    translate.set_defaults(func=cmd_propose)

    structure = propose_sub.add_parser("structure", parents=[child], help='结构建议 {"ops":[...]}')
    structure.add_argument("--file", required=True)
    structure.set_defaults(func=cmd_propose)

    reshape = propose_sub.add_parser("reshape", parents=[child], help="整份重排的新 SRT")
    reshape.add_argument("--file", required=True)
    reshape.add_argument("--from", dest="start", type=int, default=1)
    reshape.add_argument("--to", dest="end", type=int, default=None)
    reshape.set_defaults(func=cmd_propose)

    status = sub.add_parser("status", parents=[child], help="提案文件版本（轮询用）")
    status.set_defaults(func=cmd_status)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        client = connect(args.runtime)
        args.func(client, args)
        return 0
    except CliError as exc:
        print(f"kikusub: {exc}", file=sys.stderr)
        return exc.code
    except KeyboardInterrupt:
        print("kikusub: 已中断", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
