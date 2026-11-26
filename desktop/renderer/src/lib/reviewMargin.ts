/**
 * 核对表**页边记号**（44px cue margin）的数据来源。
 *
 * 页边只承载三件事，而且每一件都来自本会话已有的真实状态，不另造「已读 / 已看」
 * 这类产品里不存在的标记：
 *
 * - `warn` 待核：这一句落在质检队列里、还没被处理（朱点）；
 * - `ok` 已核：这一句对应的质检项已经处理过（打勾）；
 * - `ai` 蓝铅笔：这一行已经有译文——机器写下的第二行。**即使当前看的是「原文」，
 *   页边也能看见哪些句子已经被译过**，这是原文模式里唯一能看出译文进度的地方。
 *
 * 优先级 `warn > ok > ai`：一条字幕只留一个记号，先说「需要人动手」，再说
 * 「已经处理完」，最后才是「机器写过」。同一条字幕上叠两个质检项时以待核为准。
 *
 * 质检项按**时间**与字幕相交（与 QaPanel 的 `cueIndexForRange` 同口径，但这里
 * 要的是「任意重叠」而不是「最匹配的那一条」）：`coverage` / `missed` / `nonverbal`
 * 这类「那里本来就没有字幕」的项匹配不到任何行，页边自然不画——页边画的是**这张纸上
 * 看得见的行**，队列总数仍由「质检待核」页签的计数表达。
 *
 * 零运行时相对导入：`node --test` 直接加载 `.ts` 时 ESM 不给无扩展名路径补 `.ts`。
 */
import type { Cue } from './api';

export type CueMark = 'warn' | 'ok' | 'ai';

interface QaItem {
  id?: string;
  start?: number;
  end?: number;
}

interface QaPayload {
  items?: QaItem[];
  statuses?: Record<string, { status?: string } | undefined>;
}

/** 找到与 `[start, end]` 有任意正重叠的第一条字幕；没有就 -1。 */
function cueIndexOverlapping(cues: Cue[], start: number, end: number): number {
  for (let i = 0; i < cues.length; i += 1) {
    const cue = cues[i];
    if (cue.end <= start) continue;
    if (cue.start >= end) break;
    const overlap = Math.min(cue.end, end) - Math.max(cue.start, start);
    if (overlap > 0) return i;
  }
  return -1;
}

/**
 * 一次算出整张表的页边记号。
 *
 * `texts` 是当前语种译文轨（`app.translations[lang].texts`）；没有译文轨时传 null，
 * 页边就只剩质检状态——「没有译文」和「译文是空串」都不画铅笔。
 */
export function cueMarks(
  cues: Cue[],
  payload: QaPayload | null | undefined,
  texts: string[] | null | undefined,
): Map<number, CueMark> {
  const marks = new Map<number, CueMark>();
  if (!cues.length) return marks;

  const statuses = payload?.statuses ?? {};
  for (const item of payload?.items ?? []) {
    const start = Number(item.start);
    const end = Number(item.end);
    if (!Number.isFinite(start) || !Number.isFinite(end)) continue;
    const index = cueIndexOverlapping(cues, start, end);
    if (index < 0) continue;
    const status = statuses[item.id ?? '']?.status ?? 'pending';
    if (status === 'pending') marks.set(index, 'warn');
    else if (marks.get(index) !== 'warn') marks.set(index, 'ok');
  }

  if (Array.isArray(texts)) {
    const limit = Math.min(cues.length, texts.length);
    for (let i = 0; i < limit; i += 1) {
      if (marks.has(i)) continue;
      if (String(texts[i] ?? '').trim()) marks.set(i, 'ai');
    }
  }

  return marks;
}

/** 页边记号的悬停说明。文案在组件里只查表，不各写一份。 */
export function cueMarkTitle(mark: CueMark | undefined): string {
  if (mark === 'warn') return '质检队列里还没处理这一句（点右侧「质检待核」）';
  if (mark === 'ok') return '这一句的质检项已经处理过';
  if (mark === 'ai') return '这一行已经有译文（机器写下的第二行）';
  return '还没有质检记录';
}
