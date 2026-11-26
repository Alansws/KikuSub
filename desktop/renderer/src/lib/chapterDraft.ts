/**
 * 「章节草稿」的纯逻辑：把一个时刻点补成区间章节。
 *
 * 用户场景：先在**场景结束**处（比如 14:06）插时刻点，再回头找**场景开始**
 * （0:10 附近）。整段 14 分钟在放大态一屏装不下，框选根本够不着；所以两个端点
 * 必须**分别落位**——草稿就是「先占住一端，另一端跟着播放头找」。
 *
 * 约束（与 `ReviewView` 的 4px 框选、`addRangeChapter` 的 0.2 秒下限对齐）：
 * 两端相差至少 `MIN_CHAPTER_SPAN`，否则播放器里点不中；
 * 先落一端时如果另一端已经存在，新端点不得越过它。
 *
 * 零导入：`node --test` 直接加载 `.ts`（同 `lib/scrub.ts` 的约束）。
 */

export type DraftEdge = 'start' | 'end';

export interface ChapterDraft {
  /** 源标记 id：保存时按 id 原地把时刻点升级成区间，不动其它标记。 */
  from: string;
  /** 沿用源标记的标题（保存时用户仍可在列表里改）。 */
  title: string;
  /** 已经落位的端点（秒）；null = 待定，预览时用播放头。 */
  start: number | null;
  end: number | null;
}

/** 章节最短长度（秒）：更短的区间在播放器章节列表里点不中。 */
export const MIN_CHAPTER_SPAN = 0.2;

/**
 * 落到毫秒：草稿里的时间一律按毫秒记。
 *
 * 波形点击算出来的时间常是 9.99998 这种值，直接格式化会显示成
 * 「00:09.1000」（`tcShort` 先取整秒、再四舍五入小数位）；先落到毫秒，
 * 面板、预览色带、落库三处读到的就是同一个数。
 */
function round3(t: number): number {
  return Math.round(t * 1000) / 1000;
}

/** 从一条时刻点开草稿：`edge` 表示「这个时间已经被当成章节的哪一端」。 */
export function beginDraft(input: {
  id: string;
  title: string;
  time: number;
  edge: DraftEdge;
}): ChapterDraft {
  const time = round3(Math.max(0, input.time));
  return {
    from: input.id,
    title: input.title,
    start: input.edge === 'start' ? time : null,
    end: input.edge === 'end' ? time : null,
  };
}

/**
 * 用播放头时间落一端。
 *
 * 返回新的草稿与一句错误文案（`''` = 成功）；失败时草稿原样不动。
 */
export function setEdge(
  draft: ChapterDraft,
  edge: DraftEdge,
  time: number,
  duration: number,
): { draft: ChapterDraft; error: string } {
  const max = duration > 0 ? duration : Number.POSITIVE_INFINITY;
  const t = round3(Math.max(0, Math.min(max, time)));
  // 另一端还没落位时，这一端就是用户辛苦找到的锚点：不许被误按覆盖，
  // 否则「14:06 是章末」这条信息会静默丢掉。
  const pending = pendingEdge(draft);
  if (pending && pending !== edge) {
    return { draft, error: '这一端已经定好了，先补另一端（或取消草稿）' };
  }
  if (edge === 'start') {
    if (draft.end !== null && t > draft.end - MIN_CHAPTER_SPAN) {
      return { draft, error: '起点必须比章末至少早 0.2 秒' };
    }
    return { draft: { ...draft, start: t }, error: '' };
  }
  if (draft.start !== null && t < draft.start + MIN_CHAPTER_SPAN) {
    return { draft, error: '章末必须比起点至少晚 0.2 秒' };
  }
  return { draft: { ...draft, end: t }, error: '' };
}

/** 还缺哪一端；两端都有时返回 null。 */
export function pendingEdge(draft: ChapterDraft): DraftEdge | null {
  if (draft.start === null) return 'start';
  if (draft.end === null) return 'end';
  return null;
}

/**
 * 预览区间：待定的那一端用当前播放头。
 *
 * 时间轴色带与面板里的「时长」读同一个函数，避免两处各算一套。
 */
export function span(draft: ChapterDraft | null, playTime: number): { start: number; end: number } | null {
  if (!draft) return null;
  const a = draft.start ?? playTime;
  const b = draft.end ?? playTime;
  return { start: Math.min(a, b), end: Math.max(a, b) };
}

/** 保存前的校验；`''` 表示可以保存。 */
export function readyError(draft: ChapterDraft | null): string {
  if (!draft) return '还没有章节草稿';
  if (draft.start === null) return '还没有起点';
  if (draft.end === null) return '还没有终点';
  if (draft.end - draft.start < MIN_CHAPTER_SPAN) return '章节太短（至少 0.2 秒）';
  return '';
}

/** 落库用的起止时间（四舍五入到毫秒，和 `addRangeChapter` 同一口径）。 */
export function toMarkTimes(draft: ChapterDraft | null): { start: number; end: number } | null {
  if (!draft || readyError(draft)) return null;
  const start = Math.round((draft.start as number) * 1000) / 1000;
  const end = Math.round((draft.end as number) * 1000) / 1000;
  if (end - start < MIN_CHAPTER_SPAN) return null;
  return { start, end };
}
