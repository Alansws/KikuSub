/**
 * 转写页的页面级状态（2026-11-25）。
 *
 * 为什么不放 `store.svelte.ts`：那个文件有 3255 行的预算（红线 11，只许变短），
 * 而这里的状态只服务一个页面；放独立模块还能让「切页不丢范围」这件事有唯一
 * 的写入点。
 *
 * ## 范围为什么可以跨切页保留
 *
 * 旧实现把区间存在组件局部 state 里：`App.svelte` 用 `{#key app.view}` 重建
 * 视图，一回核对台再回来，区间就没了（用户报障）。`app.slice` 仍然保持
 * 「读走即清空」的一次性消息语义——防的是「旧区间复活、输入框与提交不一致」；
 * 本模块只记住**用户明确填入过的那一段**，并在切媒体 / 点「整片」时清掉。
 * 误转整片的防线不在「偷偷清空」，而在三处显式提示：范围 chip、底栏复述、
 * 按钮文案；且区间的默认档位是「替换选区」，最坏也只重写这一段。
 */

import type { OutputTarget } from './transcribePlan';

export type ScopeFrom = 'full' | 'chapter' | 'review' | 'manual';

/** 右栏「最近一次」的展示数据（由转写页组装，组件只负责排版）。 */
export interface LastRunView {
  engineLabel: string;
  targetText: string;
  rangeText: string;
  countText: string;
  canReplay: boolean;
  at: number;
}

export interface TranscribeScope {
  startText: string;
  endText: string;
  from: ScopeFrom;
  /** 来源名：章节标题 / 「核对台选区」；手动填写为空。 */
  label: string;
}

export const transcribeTask = $state({
  /** 这一趟的产出。默认由 `defaultTarget()` 按引擎推出，用户点过后不再自动改。 */
  target: 'primary' as OutputTarget,
  /** 用户是否亲手点过产出：点过之后自动默认值不再覆盖它。 */
  targetTouched: false,
  scope: { startText: '', endText: '', from: 'full', label: '' } as TranscribeScope,
  mediaId: '',
  /** 本页最近一次提交（引擎 + 目标 + 范围），右栏「最近一次」用；不做持久化。 */
  lastSubmit: null as null | {
    engine: string;
    target: OutputTarget;
    startText: string;
    endText: string;
    label: string;
    apply: 'replace' | 'append' | 'replace_range';
    at: number;
  },
});

/** 核对台 / 章节「加入转写选区」带过来的一段：写进页面记忆。 */
export function applySliceScope(req: {
  start: string;
  end: string;
  origin?: 'chapter' | 'review';
  label?: string;
}): void {
  transcribeTask.scope = {
    startText: req.start,
    endText: req.end,
    from: req.origin === 'chapter' ? 'chapter' : 'review',
    label: req.origin === 'chapter' ? String(req.label || '') : '核对台选区',
  };
}

/** 「整片」：清掉起止与来源。 */
export function setScopeFull(): void {
  transcribeTask.scope = { startText: '', endText: '', from: 'full', label: '' };
}

/** 把某一段填回范围（右栏「作为第二版重跑这段」用）。 */
export function restoreScope(startText: string, endText: string): void {
  transcribeTask.scope = { startText, endText, from: 'manual', label: '' };
}

/** 用户手填 / 改了起止：来源降级为「手动」，章节名不再可信。 */
export function touchScope(startText: string, endText: string): void {
  transcribeTask.scope = { startText, endText, from: 'manual', label: '' };
}

/** 用户点了产出：从此不再被自动默认值覆盖。 */
export function chooseTarget(target: OutputTarget): void {
  transcribeTask.target = target;
  transcribeTask.targetTouched = true;
}

/** 换片：范围与「最近一次」都属于上一部片，必须归零。 */
export function resetForMedia(mediaId: string): boolean {
  if (transcribeTask.mediaId === mediaId) return false;
  transcribeTask.mediaId = mediaId;
  transcribeTask.target = 'primary';
  transcribeTask.targetTouched = false;
  transcribeTask.lastSubmit = null;
  setScopeFull();
  return true;
}

/** 记下这一趟；右栏据此提供「作为第二版重跑这段」。 */
export function noteSubmit(entry: {
  engine: string;
  target: OutputTarget;
  startText: string;
  endText: string;
  label: string;
  apply: 'replace' | 'append' | 'replace_range';
}): void {
  transcribeTask.lastSubmit = { ...entry, at: Date.now() };
}
