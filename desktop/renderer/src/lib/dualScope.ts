/**
 * 双引擎复核「对照范围」的纯展示逻辑（2026-11-26）。
 *
 * 服务端负责真正的切片与统计（`core/dual_scope.py`），这里只做三件渲染层的事：
 *
 * 1. 把 `seconds` 变成页头那句「35:53–55:41」；
 * 2. 把范围状态翻译成页头横幅文案（聚焦章节 / 隐去多少条 / 能不能安全覆盖）；
 * 3. 决定「用 B 写回」那颗按钮的**文案**与**二次确认文本**——
 *    「替换当前范围」与「整列覆盖」是两个危险度完全不同的动作，文案必须一眼分得开。
 *
 * 全都是纯函数，`node --test` 直接加载（同 `applyMode.ts` / `transcribePlan.ts` 的套路）。
 */

/** 只有跨度与名字的那部分（范围清单里的每一项都能当它用）。 */
export interface SpanLike {
  kind: 'all' | 'range' | 'chapter';
  start: number;
  end: number;
  label: string;
}

export interface ScopeLike extends SpanLike {
  kind: 'all' | 'range' | 'chapter';
  key: string;
  start: number;
  end: number;
  label: string;
  range_label: string;
  auto: boolean;
  partial_b: boolean;
  hidden_a: number;
  hidden_b: number;
  would_trim: number;
  replace_mode: 'range' | 'all';
  replace_count: number;
}

/** `2133.4` → `35:33`；超过一小时 `1:02:03`。与 `core/dual_scope.format_clock` 同口径。 */
export function clockOf(seconds: number): string {
  const total = Math.max(0, Math.floor(Number(seconds) || 0));
  const hours = Math.floor(total / 3600);
  const rest = total % 3600;
  const minutes = Math.floor(rest / 60);
  const secs = rest % 60;
  const mm = String(minutes).padStart(2, '0');
  const ss = String(secs).padStart(2, '0');
  return hours ? `${hours}:${mm}:${ss}` : `${mm}:${ss}`;
}

/** 范围在页头那一小段里的名字：`章节三` / `B 所在区间` / `全片`。 */
export function scopeName(scope: SpanLike | null | undefined): string {
  if (!scope) return '全片';
  return scope.label || (scope.kind === 'all' ? '全片' : '当前范围');
}

/** 范围的一行说明：`章节三 · 35:53–55:41`。 */
export function scopeRangeLabel(scope: SpanLike | null | undefined): string {
  if (!scope) return '';
  if (scope.kind === 'all') return '全片';
  const span = `${clockOf(scope.start)}–${clockOf(scope.end)}`;
  return scope.label ? `${scope.label} · ${span}` : span;
}

/**
 * 页头横幅：**必须先说清「现在在看哪一段、外面还藏着多少条」**。
 *
 * 用户原话是「真正要核对的章节三被埋在最下面」——所以这句话里必须同时出现
 * 聚焦对象与隐去条数，而不是只写「已筛选」。
 */
export function scopeBanner(scope: ScopeLike | null | undefined): string {
  if (!scope) return '';
  const frozen = scope.kind === 'all' ? '' : `${scopeRangeLabel(scope)}`;
  const hidden: string[] = [];
  if (scope.hidden_a > 0) hidden.push(`A ${scope.hidden_a} 条`);
  if (scope.hidden_b > 0) hidden.push(`B ${scope.hidden_b} 条`);
  const tail = hidden.length ? `已隐去范围外 ${hidden.join(' / ')}` : '没有范围外条目';
  if (scope.kind === 'all') {
    return scope.partial_b
      ? '当前聚焦：全片（第二版只覆盖了一部分区间，整片对齐会把范围外的 A 全标成「仅 A」）'
      : '当前聚焦：全片';
  }
  return `当前聚焦：${frozen}（${tail}），可切换到全片或别的章节`;
}

/** 范围切换器的标签：`章节三（220）`。条数让人一眼看出这一段有多长。 */
export function scopeTabLabel(option: {
  key: string;
  label: string;
  a_count: number;
  b_count: number;
  kind: string;
}): string {
  if (option.kind === 'all') return '全片';
  const count = Math.max(option.a_count, option.b_count);
  const name = option.label || (option.kind === 'chapter' ? '章节' : 'B 区间');
  return count ? `${name}（${count}）` : name;
}

/**
 * 写回按钮的文案。
 *
 * - 范围对照 → 「用 B 替换当前范围」（安全，默认）；
 * - 全片且 B 盖住整片 → 「用 B 覆盖核对台」（唯一的整列动作）；
 * - 全片但 B 只覆盖局部 → 仍然只给范围替换，绝不给一颗能清空别的章节的按钮。
 */
export function replaceLabel(scope: ScopeLike | null | undefined, busy = false): string {
  if (busy) return '写入中…';
  if (!scope) return '用 B 覆盖核对台';
  if (scope.replace_mode === 'all') return '用 B 覆盖核对台';
  return '用 B 替换当前范围';
}

/** 写回按钮会不会丢字（用来决定 danger 配色与 title）。 */
export function replaceIsDestructive(scope: ScopeLike | null | undefined): boolean {
  if (!scope) return false;
  return scope.replace_mode === 'all' && scope.would_trim > 0;
}

/**
 * 二次确认文本。范围替换与整列覆盖**必须长得不一样**：
 * 前者要让人确认「只动这一段」，后者要明确写出会丢多少条。
 */
export function replaceConfirmText(
  scope: ScopeLike | null | undefined,
  aTotal: number,
  bTotal: number,
): string {
  if (!scope) {
    return `用第二版整列覆盖核对台？\n\n核对台当前 ${aTotal} 条会被 ${bTotal} 条替换；\n这一步只压一次历史，⌘Z 可以整批退回。`;
  }
  if (scope.replace_mode === 'range') {
    // 窗口外 = 被范围隐去的那些条（`hidden_a`），不是「总数 − 隐去数」。
    const outside = Math.max(0, scope.hidden_a);
    const outsideText = outside
      ? `窗口外的 ${outside} 条（其它章节）一条不动。`
      : '这一次没有窗口外的条目会被改动。';
    return (
      `用 B 替换「${scopeRangeLabel(scope)}」这一段的字幕？\n\n` +
      `只换窗口内的 ${scope.replace_count} 条；\n` +
      `${outsideText}\n` +
      '这一步只压一次历史，⌘Z 可以整批退回。'
    );
  }
  const loss = scope.would_trim > 0 ? `\n注意：范围外还有 ${scope.would_trim} 条会被丢掉，` : '';
  return (
    `用第二版整列覆盖核对台？\n\n` +
    `核对台当前 ${aTotal} 条会被 ${bTotal} 条替换。${loss}` +
    `\n这一步只压一次历史，⌘Z 可以整批退回；覆盖成功后第二版会被清空。`
  );
}

/** 范围为空时的提示（章节里没有字幕 / B 不含这段）。 */
export function scopeEmptyHint(scope: ScopeLike | null | undefined): string {
  if (!scope) return '';
  if (scope.kind === 'all') return '两份字幕在整片范围内都没有可对照的行。';
  return `「${scopeName(scope)}」里没有可对照的句子：换一个范围，或切回全片。`;
}

/** 统计片要带的口径后缀：范围对照时补一句「仅本段」，避免与整片条数混读。 */
export function scopeStatSuffix(scope: ScopeLike | null | undefined): string {
  if (!scope || scope.kind === 'all') return '';
  return '仅本段';
}
