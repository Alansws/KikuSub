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


export interface AlignStats {
  enabled?: boolean;
  segments?: number;
  aligned?: number;
  noop?: number;
  degraded?: number;
  empty?: number;
}

/**
 * 转写完成后进度卡里的「对齐说明」。
 *
 * 只在 Qwen（走 CTC）且确实有语音段时出现：Whisper 关闭 CTC、中文引擎走
 * token 时间戳，它们不应该冒出一行 `0/0` 的逐字对齐汇总（用户明确要求）。
 * 文案必须说清分母是「语音段」而不是字幕条数，否则 230/257 很容易被读成漏字。
 */
export function alignDoneText(
  stats: AlignStats | null | undefined,
  family: string,
): string {
  if (family !== 'qwen') return '';
  if (!stats || stats.enabled === false) return '';
  const total = Number(stats.segments ?? 0);
  if (!Number.isFinite(total) || total <= 0) return '';
  const aligned = Number(stats.aligned ?? 0);
  const rest = Math.max(0, total - aligned);
  if (rest === 0) {
    return `本次 ${total} 个语音段全部完成逐字对齐（语音段不是字幕条数）。`;
  }
  const parts: string[] = [];
  const degraded = Number(stats.degraded ?? 0);
  const noop = Number(stats.noop ?? 0);
  const empty = Number(stats.empty ?? 0);
  if (degraded > 0) parts.push(`对齐降级 ${degraded}`);
  if (noop > 0) parts.push(`纯符号 ${noop}`);
  if (empty > 0) parts.push(`无台词 ${empty}`);
  const detail = parts.length ? parts.join('、') : '其他';
  return `本次 ${total} 个语音段（不是字幕条数）：${aligned} 段完成逐字对齐；其余 ${rest} 段为${detail}。`;
}
