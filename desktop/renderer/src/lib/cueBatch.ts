/**
 * 条号子范围（批次）纯函数：润色 / 翻译 / 断句重排共用的「本次处理批次」。
 *
 * 为什么单独一个模块：批次是**实时列表索引区间**，用户在前面改一句文字、表格
 * 条数不变时批次必须原地不动；而处理范围只决定 `span`。把夹紧 / 步进 / 指纹
 * 写成纯函数，页面只负责把当前值接进请求，`node --test` 能直接钉死边界。
 *
 * 约定：`from` / `to` 都是 1 基、含两端；`span` 是当前处理范围命中的全片区间。
 * 批次永远被夹在 `span` 内，因此「范围变小」只会让批次跟着缩，不会抛错。
 */

export interface CueRange {
  from: number;
  to: number;
}

export interface CueSpan extends CueRange {
  count: number;
}

/** 默认每批条数。润色与翻译的长片智能分段也是 150，保持一致。 */
export const DEFAULT_BATCH_SIZE = 150;

/** 空批次（没有字幕 / 范围里没有条目）。 */
export const EMPTY_RANGE: CueRange = { from: 0, to: 0 };

export function rangeCount(range: CueRange): number {
  return Math.max(0, range.to - range.from + 1);
}

/**
 * 把任意输入夹进 span。`from > to` 时把 `to` 拉回 `from`（不抛错），
 * 这样用户输错一个数字不会让整页分批状态失效。
 */
export function clampRange(range: CueRange, span: CueSpan): CueRange {
  if (span.count <= 0) return { ...EMPTY_RANGE };
  const min = Math.max(1, span.from);
  const max = Math.max(min, span.to);
  const from = Math.min(Math.max(min, Math.floor(range.from || min)), max);
  const rawTo = Math.floor(range.to || from);
  const to = Math.min(Math.max(from, rawTo), max);
  return { from, to };
}

export function isWholeRange(range: CueRange, span: CueSpan): boolean {
  return span.count > 0 && range.from === span.from && range.to === span.to;
}

/** 批次摘要：`1–151`；空批次给 `—`。 */
export function batchLabel(range: CueRange): string {
  if (range.to < range.from || range.to <= 0) return '—';
  return `${range.from}–${range.to}`;
}

/**
 * 按固定条数从起点重切一批：`from` 不动，`to = from + size - 1`（夹进 span）。
 * 「每批 N 条」预设与手动改 N 都走这里。
 */
export function resizeBatch(range: CueRange, span: CueSpan, size: number): CueRange {
  const step = Math.max(1, Math.floor(size || DEFAULT_BATCH_SIZE));
  const start = clampRange({ from: range.from, to: range.from }, span).from;
  if (!start) return { ...EMPTY_RANGE };
  return clampRange({ from: start, to: start + step - 1 }, span);
}

/** 下一批：接在当前 `to` 之后；已经在末尾时原样返回。 */
export function nextBatch(range: CueRange, span: CueSpan, size: number): CueRange {
  const step = Math.max(1, Math.floor(size || DEFAULT_BATCH_SIZE));
  if (span.count <= 0) return { ...EMPTY_RANGE };
  const current = clampRange(range, span);
  if (current.to >= span.to) return current;
  const from = current.to + 1;
  return clampRange({ from, to: from + step - 1 }, span);
}

/** 上一批：结束在当前 `from` 之前；已经在开头时原样返回。 */
export function previousBatch(range: CueRange, span: CueSpan, size: number): CueRange {
  const step = Math.max(1, Math.floor(size || DEFAULT_BATCH_SIZE));
  if (span.count <= 0) return { ...EMPTY_RANGE };
  const current = clampRange(range, span);
  if (current.from <= span.from) return current;
  const to = current.from - 1;
  return clampRange({ from: to - step + 1, to }, span);
}

/**
 * 当前批次指纹：媒体 + 处理范围 + 批次区间 + 当前表条数。
 *
 * 用在滚动位置记忆与「这批是不是同一批」的判断上；**不含任何文本内容**，
 * 所以用户中途改前面某句的文字不会让指纹变化、也不会把批次打回默认。
 */
export function batchKey(
  mediaId: string,
  span: CueSpan,
  range: CueRange,
  total: number,
  extra = '',
): string {
  return [
    mediaId,
    `${span.from}-${span.to}`,
    `${range.from}-${range.to}`,
    String(total),
    extra,
  ].join(':');
}
