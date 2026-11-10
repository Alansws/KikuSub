"""任务详报路由。

改造规划 §4 的明确要求：**返回数据，不返回 HTML**。旧实现是
`build_transcription_report()` 生成一大段文本、再由 `render_report_panel()` 用正则
把它解析回 HTML 胶囊——那种「文本 → 正则 → HTML」的往返正是要消灭的东西。

现在 `core.report.build_report_data()` 一次产出结构化数据：

- `overview` / `params`：`[{label, value}]`，前端渲染指标胶囊
- `quality`：漏句 / 误删 / 短句的数量与一句话速览
- `sections`：分段明细（疑似漏句、切分点吸附、幻觉门控、幻觉复核、逐字对齐）
- `raw_text`：纯文本原稿，供「一键复制」与归档，与旧界面逐字一致
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from .jobs import JobNotFound
from .security import require_token

router = APIRouter(tags=["report"], dependencies=[Depends(require_token)])


@router.get("/api/report")
def get_report(request: Request, job_id: str | None = None) -> dict:
    """取任务详报。不传 `job_id` 时返回最近一次成功转写的报告。"""
    manager = request.app.state.jobs
    if job_id:
        try:
            job = manager.get(job_id)
        except JobNotFound as exc:
            raise HTTPException(status_code=404, detail="任务不存在") from exc
    else:
        job = manager.latest_completed("transcribe")
        if job is None:
            raise HTTPException(status_code=404, detail="还没有完成过转写任务")

    result = job.result or {}
    report = result.get("report")
    if not report:
        raise HTTPException(
            status_code=409,
            detail=f"该任务没有报告（状态：{job.status}）",
        )
    return {
        "job_id": job.id,
        "media_id": result.get("media_id"),
        "out_filename": result.get("out_filename"),
        "out_path": result.get("out_path"),
        **report,
    }
