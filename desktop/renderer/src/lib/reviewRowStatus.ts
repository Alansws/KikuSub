/**
 * 字幕表「状态」列的判定（纯函数，无 Svelte 依赖）。
 *
 * 数据来源只有一处：质检队列（`/api/qa` 的 `items` + `statuses`）。**不新增引擎字段**，
 * 也不在前端自己算置信度——低置信 / 待核是转写期就产出的结论，这里只负责把它按
 * 时间窗落到「第几条字幕」上。
 *
 * 为什么按时间窗而不是按条号：质检项存的是 `{start, end}`（覆盖空白是间隙、
 * 误删是切片区间），与字幕条没有稳定的一一对应；转写后用户还可能删过 / 合并过字幕，
 * 条号会漂。时间重叠是唯一不会骗人的对应关系。
 *
 * 优先级（同一行命中多条时取最要紧的）：
 *   miss（未覆盖 / 切片为空 = 可能漏了一句）
 *     > low（低置信 / 短句 / 误删 / 纯发声）
 *       > stale（译文本条已过期，与当前原文对不上）
 */

export type RowStatusKind = 'miss' | 'low' | 'stale';

export interface QaLike {
  id?: string;
  kind?: string;
  group?: string;
  start?: number | string;
  end?: number | string;
}

export interface RowStatus {
  kind: RowStatusKind;
  /** 命中几条待核项（`stale` 恒为 0）。 */
  count: number;
}

const GROUP_MISS = 'miss';

/** 质检项的组：显式 `group` 优先，否则 coverage 归 miss，其余归 low（与 QaPanel 同口径）。 */
export function groupOf(item: QaLike): string {
  if (item.group) return item.group;
  return item.kind === 'coverage' ? GROUP_MISS : 'low';
}

function num(value: unknown): number {
  const n = Number(value);
  return Number.isFinite(n) ? n : 0;
}

/** 只保留仍然是 `pending` 的项：已核对 / 已跳过的不该再在表里报警。 */
export function pendingItems(
  items: QaLike[],
  statuses: Record<string, { status?: string }> | undefined,
): QaLike[] {
  const byId = statuses ?? {};
  return items.filter((item) => (byId[String(item.id ?? '')]?.status ?? 'pending') === 'pending');
}

/** 两段是否重叠（端点相接算重叠：质检项贴着一句的边界时用户就该看到它）。 */
export function overlaps(aStart: number, aEnd: number, bStart: number, bEnd: number): boolean {
  return aStart <= bEnd && bStart <= aEnd;
}

/**
 * 每条字幕的状态徽标。
 *
 * 返回与 `cues` 等长的数组，`null` = 这一行没有任何需要提醒的东西（绝大多数行）。
 * `staleRows` 是「译文本条已过期」的行号集合，由调用方给出（它的判定在 store 里，
 * 依赖译文版本号）。
 */
export function rowStatuses(
  cues: { start: number; end: number }[],
  items: QaLike[],
  staleRows?: Set<number>,
): (RowStatus | null)[] {
  const missHits = new Map<number, number>();
  const lowHits = new Map<number, number>();

  for (const item of items) {
    const s = num(item.start);
    const e = Math.max(s, num(item.end));
    const isMiss = groupOf(item) === GROUP_MISS;
    for (let i = 0; i < cues.length; i += 1) {
      const cue = cues[i];
      if (!overlaps(s, e, cue.start, cue.end)) continue;
      const bucket = isMiss ? missHits : lowHits;
      bucket.set(i, (bucket.get(i) ?? 0) + 1);
    }
  }

  return cues.map((_, i) => {
    const miss = missHits.get(i) ?? 0;
    if (miss) return { kind: 'miss', count: miss };
    const low = lowHits.get(i) ?? 0;
    if (low) return { kind: 'low', count: low };
    if (staleRows?.has(i)) return { kind: 'stale', count: 0 };
    return null;
  });
}

/** 徽标文字：不写「低置信 0.62」这种假精度——队列里没有这一位小数。 */
export const ROW_STATUS_LABEL: Record<RowStatusKind, string> = {
  miss: '漏句待核',
  low: '待核',
  stale: '译文过期',
};

/** 徽标的 title：说清「为什么」以及「去哪儿处理」。 */
export function rowStatusTitle(status: RowStatus): string {
  switch (status.kind) {
    case 'miss':
      return `${status.count} 条漏句 / 未覆盖待核 · 在「质检待核」里补录或确认`;
    case 'low':
      return `${status.count} 条低置信 / 待确认 · 在「质检待核」里逐条确认`;
    default:
      return '这一条的译文本条已过期（原文改过）· 在「当前条目」里重新对齐或更新译文';
  }
}
