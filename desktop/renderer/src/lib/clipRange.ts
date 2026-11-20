/**
 * 片段范围（clip scope）的纯函数：章节选项、命中条数、平移口径、文件名标签。
 *
 * 与 `core/clip_range.py` 同一套口径（0.1s 蹭边阈值、章节区间不被时刻点拆碎、
 * 文件名安全标签），但**不重复实现裁剪**：真正的裁剪永远在服务端做，前端只用
 * 这些函数决定「界面显示哪一段、请求带哪一个 1 基区间」。
 *
 * 为什么前端也需要同一套阈值：润色 / 翻译页要显示「命中 291 / 899 条」，
 * 如果这里和 Python 各写一套边界规则，界面会先报 292 条、服务端再只处理 291 条。
 */

import type { ChapterMark, Cue } from './api';

/** 片段范围（秒，原片时间）。`end <= 0` = 全片。 */
export interface ClipScope {
  start: number;
  end: number;
  /** 人类可读标签（章节标题）；自定义范围时为空。 */
  label: string;
}

export interface ChapterScopeOption {
  id: string;
  title: string;
  start: number;
  end: number;
  label: string;
}

/** 全片：导出 / 润色 / 翻译都按整片处理。 */
export const FULL_CLIP: ClipScope = { start: 0, end: 0, label: '' };

/** 与 `core.clip_range.MIN_EDGE_OVERLAP_S` 一致：更短的首尾重叠来自相邻场景。 */
export const MIN_EDGE_OVERLAP_S = 0.1;
/** 与 `core.clip_range.MIN_CLIP_S` 一致：再短不是「一段」而是误触。 */
export const MIN_CLIP_S = 0.2;

export function isFullClip(scope: ClipScope | null | undefined): boolean {
  return !scope || !(scope.end > 0.01);
}

/** 片段长度（秒）；全片时回落到 `duration`。 */
export function clipLength(scope: ClipScope, duration = 0): number {
  if (isFullClip(scope)) return Math.max(0, duration);
  return Math.max(0, scope.end - scope.start);
}

/** 夹进 `[0, duration]`；`end<=start` 时退化成全片（调用方禁用按钮即可）。 */
export function normalizeClip(scope: ClipScope, duration = 0): ClipScope {
  const total = Math.max(0, duration);
  const start = Math.max(0, Math.min(scope.start, total || scope.start));
  const end = Math.max(start, Math.min(scope.end, total || scope.end));
  return { start, end, label: scope.label };
}

/** `mm:ss` / `h:mm:ss`；与核对台时间码同一读法。 */
export function formatClock(seconds: number): string {
  const total = Math.max(0, seconds);
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = Math.floor(total % 60);
  const ss = String(s).padStart(2, '0');
  return h > 0 ? `${h}:${String(m).padStart(2, '0')}:${ss}` : `${m}:${ss}`;
}

/** 范围摘要：`0:10 → 24:22`；全片返回空串。 */
export function formatRange(scope: ClipScope): string {
  if (isFullClip(scope)) return '';
  return `${formatClock(scope.start)} → ${formatClock(scope.end)}`;
}

/** 界面上的一句话（含章节标题）。 */
export function clipCaption(scope: ClipScope): string {
  if (isFullClip(scope)) return '全片';
  const title = scope.label ? `${scope.label} · ` : '';
  return `${title}${formatRange(scope)}`;
}

/** 历史步骤文案：`全片` ↔ `章节1 · 0:10 → 24:22`。 */
export function clipScopeLabel(scope: ClipScope): string {
  return clipCaption(scope);
}

/** 文件名安全标签：去掉路径分隔符与控制字符，折叠空白（与 core 同规则）。 */
export function safeClipLabel(text: string, maxLen = 48): string {
  const cleaned = String(text || '')
    .trim()
    .replace(/[\s\\/:*?"<>|;#$\u0000-\u001f]+/g, '-')
    .replace(/-{2,}/g, '-')
    .replace(/^[-._]+|[-._]+$/g, '');
  return cleaned.slice(0, maxLen).replace(/^[-._]+|[-._]+$/g, '');
}

/** `10` → `00m10s`，`1462` → `24m22s`（与 `core.clip_range.clock_label` 一致）。 */
export function clockLabel(seconds: number): string {
  const total = Math.max(0, Math.round(seconds));
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  const mm = String(m).padStart(2, '0');
  const ss = String(s).padStart(2, '0');
  return h > 0 ? `${h}h${mm}m${ss}s` : `${mm}m${ss}s`;
}

/** 与 `core.clip_range.clip_tag` 一致：`章节1-00m10s-24m22s`。 */
export function clipFileTag(scope: ClipScope): string {
  if (isFullClip(scope)) return '';
  const window = `${clockLabel(scope.start)}-${clockLabel(scope.end)}`;
  const title = safeClipLabel(scope.label);
  return title ? `${title}-${window}` : window;
}

/**
 * 与 `core.clip_range.select_cues_in_range` 相同的命中规则（1 基、含两端）。
 *
 * 只用于界面显示与请求参数；真正的剪切仍由服务端按同一规则执行。
 */
export function clipSpan(cues: Cue[], scope: ClipScope): { from: number; to: number; count: number } {
  const total = cues.length;
  if (isFullClip(scope)) return { from: 1, to: total, count: total };
  let first = 0;
  let last = 0;
  let count = 0;
  for (let index = 0; index < cues.length; index += 1) {
    const cue = cues[index];
    const overlap = Math.min(cue.end, scope.end) - Math.max(cue.start, scope.start);
    if (overlap <= 0) continue;
    const inside = cue.start >= scope.start && cue.end <= scope.end;
    if (!inside && overlap < MIN_EDGE_OVERLAP_S) continue;
    if (!count) first = index + 1;
    last = index + 1;
    count += 1;
  }
  return { from: count ? first : 0, to: count ? last : 0, count };
}

/** 该范围里有没有可处理的字幕（界面据此禁用按钮并给提示）。 */
export function hasCuesInScope(cues: Cue[], scope: ClipScope): boolean {
  return clipSpan(cues, scope).count > 0;
}

/**
 * 章节范围选项：**只取带 end 的区间标记**，按起点排序。
 *
 * 时刻点（`end === null`）不单独成项——它会被区间标记覆盖，列出来只会把
 * 「章节1」拆成一堆看起来像章节的时刻点。终点夹进片长，重叠的区间原样保留
 * （用户怎么画就怎么用）。
 */
export function chapterScopeOptions(marks: ChapterMark[], duration = 0): ChapterScopeOption[] {
  const total = Math.max(0, duration);
  return marks
    .filter((mark) => mark.end !== null && mark.end - mark.start >= MIN_CLIP_S)
    .map((mark) => {
      const start = Math.max(0, mark.start);
      const end = total > 0 ? Math.min(mark.end as number, total) : (mark.end as number);
      return {
        id: mark.id,
        title: mark.title || `章节 ${formatClock(start)}`,
        start,
        end: Math.max(start, end),
        label: mark.title || formatRange({ start, end, label: '' }),
      };
    })
    .filter((option) => option.end - option.start >= MIN_CLIP_S)
    .sort((a, b) => a.start - b.start);
}

/** 章节 → 处理范围。 */
export function scopeForChapter(option: ChapterScopeOption): ClipScope {
  return { start: option.start, end: option.end, label: option.title };
}

/** 当前范围命中哪个章节选项（用于下拉框回显）；没有命中返回空串。 */
export function matchedChapterId(scope: ClipScope, options: ChapterScopeOption[]): string {
  if (isFullClip(scope)) return '';
  const hit = options.find(
    (option) =>
      Math.abs(option.start - scope.start) < 0.05 && Math.abs(option.end - scope.end) < 0.05,
  );
  return hit?.id ?? '';
}

/** 把任意时间范围包成 scope（自定义输入用）。 */
export function customScope(start: number, end: number): ClipScope {
  return { start: Math.max(0, start), end: Math.max(start, end), label: '' };
}

/**
 * 导出 / 处理范围的下拉框取值：
 * - `'full'` 全片；`'chapter:<id>'` 章节区间；`'custom'` 自定义。
 */
export function scopeSelectValue(scope: ClipScope, options: ChapterScopeOption[]): string {
  if (isFullClip(scope)) return 'full';
  const id = matchedChapterId(scope, options);
  return id ? `chapter:${id}` : 'custom';
}
