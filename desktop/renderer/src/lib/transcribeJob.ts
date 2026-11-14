/**
 * 转写任务的纯数据构造与收尾文案（从 `store.svelte.ts` 抽出来）。
 *
 * 为什么抽：`store.svelte.ts` 有行数预算（只许变短），而这两段都是纯的——
 * 一个是「点开始后立刻显示的乐观任务快照」，一个是「区间任务完成后那句 toast」。
 * 后者还必须只有一处实现：「转写页发起」与「核对台原地修正」只差一个前缀词
 * （选区转写完成 / 局部转写完成），两处各写一份迟早会分叉。
 */

import type { JobSnapshot } from './api';

/** 点「开始转写」后的乐观任务态：请求可能因内核预热慢一拍，界面必须先有反馈。 */
export function optimisticTranscribeJob(stage: string): JobSnapshot {
  return {
    id: '',
    kind: 'transcribe',
    status: 'queued',
    ratio: 0,
    percent: 0,
    stage,
    error: '',
    created_at: Date.now() / 1000,
    started_at: 0,
    finished_at: 0,
    elapsed: 0,
    result: null,
  };
}

export interface RangeJobSummary {
  /** 谁发起的：转写页的区间任务叫「选区转写」，核对台的原地修正叫「局部转写」。 */
  origin: 'transcribe' | 'review';
  added: number;
  removed: number;
  total: number;
  /** 这次结果是否已自动保存到导出文件夹。 */
  saved: boolean;
}

export function rangeDoneText(input: RangeJobSummary): string {
  const done = input.origin === 'transcribe' ? '选区转写完成' : '局部转写完成';
  const saved = input.saved ? '，已自动保存到导出文件夹' : '';
  const tail = `，时间轴共 ${input.total} 条${saved}`;
  if (input.added && input.removed) {
    return `${done}：替换 ${input.removed} 条、新增 ${input.added} 条${tail}`;
  }
  if (input.removed) return `${done}：更新该区间 ${input.removed} 条${tail}`;
  if (input.added) return `${done}：新增 ${input.added} 条${tail}`;
  return `${done}：该区间已有相同字幕${tail}`;
}
