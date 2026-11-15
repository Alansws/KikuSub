/**
 * 转写页「结果处理」的纯决策层（2026-11-15 从 TranscribeView 抽出来）。
 *
 * ## 为什么要重做这一块
 *
 * 旧界面只有 `自动 / 覆盖 / 追加` 三档：
 *
 * - 「自动」不是服务端的模式，而是前端按「有没有填区间」自己猜——有区间猜成
 *   追加、没区间猜成覆盖（`startTranscribe()` 里的三元）。用户在界面上既看不到
 *   这个规则，也无从判断这次点下去会发生什么；
 * - 更要命的是**三档里没有一档是「只替换区间」**。用户全篇转写完，发现
 *   40:20–44:24 是有 BGM 的歌词段需要换首歌的引擎重听，把选区同步到转写页后：
 *   选「覆盖」→ `apply=replace` 让整张表只剩这个选区的结果（前半部片子没了）；
 *   选「追加」/「自动」→ 旧字幕原封不动地与新字幕叠在一起（重复）。
 *   两条路都不是他要的「删掉选区旧字幕、写入新字幕、其余不动」。
 *
 * 而服务端 `apply=replace_range` 早就实现了这件事（`server/jobs.py` 的
 * `merge_replace_range`），核对台的「转写选区」一直走的就是它，只是转写页
 * 从来没把这个选项暴露出来。这里补上，并按「这次是不是整片」给出不同档位：
 * 整片没有「只替换一段」可言，硬塞进去只会让人再猜一次。
 *
 * ## 约束
 *
 * - 纯函数、不 import Svelte，`desktop/test/applyMode.test.mjs` 直接跑；
 * - 默认值只能是**不破坏已有字幕**的那一档（区间 = 替换选区，整片 = 覆盖）；
 * - 文案必须写清「会删掉什么」，不许再出现「自动」这种黑箱命名。
 */

/** 与服务端 `TranscribeJobRequest.apply` 的合法值一一对应。 */
export type ApplyMode = 'replace_range' | 'replace' | 'append';

export interface ApplyChoice {
  key: ApplyMode;
  label: string;
}

export interface ApplyContext {
  /** 这次是不是整片（起止都空，或区间正好覆盖整片）。 */
  fullCover: boolean;
  /** 起止输入框的原始文本，可能为空。 */
  start: string;
  end: string;
}

/** 「40:20 – 44:24」；空值退化成片头/片尾，让提示读起来仍是一句话。 */
export function rangeSpan(start: string, end: string): string {
  const left = start.trim() || '片头';
  const right = end.trim() || '片尾';
  return `${left} – ${right}`;
}

/**
 * 当前可选的档位。
 *
 * 区间任务把「替换选区」放第一（也是默认），「覆盖整片」放最后：它是唯一会
 * 丢数据的档位，不该挨着主操作。整片任务只在覆盖 / 追加之间选。
 */
export function applyChoices(ctx: ApplyContext): ApplyChoice[] {
  if (ctx.fullCover) {
    return [
      { key: 'replace', label: '覆盖整片' },
      { key: 'append', label: '追加' },
    ];
  }
  return [
    { key: 'replace_range', label: '替换选区' },
    { key: 'append', label: '追加' },
    { key: 'replace', label: '覆盖整片' },
  ];
}

/**
 * 用户上次选的档位在当前范围下是否仍然合法；不合法就退回默认档。
 *
 * 例：在整片状态下选过「覆盖整片」，再把区间填上时它依然合法（区间也有这一档），
 * 就按用户的选择保留——真正防止误删的是那一档的警示色、提示文案与二次确认，
 * 而不是替用户改选。只有「替换选区」在整片下不成立时，才退回覆盖。
 */
export function resolveApplyChoice(mode: ApplyMode, ctx: ApplyContext): ApplyMode {
  const allowed = applyChoices(ctx).map((choice) => choice.key);
  if (allowed.includes(mode)) return mode;
  return ctx.fullCover ? 'replace' : 'replace_range';
}

/**
 * 这一档会不会删掉区间之外的字幕。
 *
 * 唯一的是非题：区间任务里选「覆盖整片」。界面据此弹二次确认——用户报障的
 * 就是这一步没有任何预警。
 */
export function isDestructiveChoice(mode: ApplyMode, ctx: ApplyContext): boolean {
  return mode === 'replace' && !ctx.fullCover;
}

/** 按钮下面那一行提示：逐档写清后果，而不是概括三种模式。 */
export function applyHint(mode: ApplyMode, ctx: ApplyContext): string {
  const span = rangeSpan(ctx.start, ctx.end);
  if (mode === 'replace_range') {
    return `只重写 ${span}：删掉区间内现有字幕，写入本次结果；区间外一条不动`;
  }
  if (mode === 'append') {
    return '保留现有字幕，把本次结果按时间合并去重（同一时间点不会重复）';
  }
  return ctx.fullCover
    ? '用本次结果替换整张表'
    : `清空整张表，只留 ${span} 的结果；区间外字幕全部丢失`;
}

/** 「覆盖整片」在区间任务里的二次确认文案（⌘Z 可撤销，写清楚）。 */
export function confirmDestructiveText(ctx: ApplyContext): string {
  return `这会把整张表换成只含 ${rangeSpan(ctx.start, ctx.end)} 的结果，区间外的字幕会全部丢失（⌘Z 可撤销）。确定继续？`;
}

/**
 * 「替换选区」必须用原片绝对时间轴。
 *
 * 关掉它，新区间的字幕会从 0 秒开始编号，而 `replace_range` 又是按真实时间
 * 删旧句的——结果是选区旧字幕被删、新字幕插在片头，等于两头都坏。所以这一档
 * 下强制打开，并在界面上禁用那个勾选框。
 */
export function needsAbsoluteTimeline(mode: ApplyMode): boolean {
  return mode === 'replace_range';
}
