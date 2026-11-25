/**
 * 补译批次（gap fill）的纯函数：从当前译文轨 + 处理范围里挑出「待译」条目。
 *
 * 为什么单独一个文件：检查器与翻译页是同一个流程的两个入口，必须有同一份口径；
 * 而且这里必须能 `node --test` 直接断言（只 import type，零运行时依赖）。
 *
 * 三种状态（与 lib/translationStatus.ts 同一口径）：
 * - **待译**：译文为空。局部转写新加的行、或者用户手动删掉的坏译文；
 * - **原文已改**：有译文，但它是对着旧原文翻的；
 * - 其余：已同步。
 *
 * 补译默认只收「待译」；「原文已改」要用户在面板里勾选才纳入——那意味着重翻，
 * 会覆盖现有译文，必须是显式动作。
 */

import type { Cue, TranslationTrack } from './api';

/** 处理范围（全片 1 基闭区间）。来自 `clipSpan(app.cues, exporter.clip)`。 */
export interface GapSpan {
  from: number;
  to: number;
  count: number;
}

export interface GapCounts {
  /** 这个范围里一共多少条字幕。 */
  total: number;
  /** 一条译文都没有。 */
  pending: number;
  /** 有译文但原文已经改过。 */
  stale: number;
  /** 有译文（含 stale）。 */
  translated: number;
}

/**
 * 「有译文、但原文已经改过」——与 `lib/translationStatus.ts` 的 `cueIsStale` 同口径。
 *
 * 这里不直接 import 它：`node --test` 直接加载 `.ts` 时，ESM 要求相对导入带扩展名，
 * 而仓库的 TS 配置不允许源码写 `.ts` 后缀。所以本文件保持**零运行时 import**，
 * 并在 `desktop/test/gapBatch.test.mjs` 里用 parity 用例锁住两份实现不许分叉。
 */
function isStale(
  track: TranslationTrack | undefined,
  index: number,
  cues: ReadonlyArray<Cue>,
): boolean {
  if (!track) return false;
  if (!track.texts[index]) return false;
  const base = track.base ?? [];
  if (index >= base.length) return true;
  return base[index] !== (cues[index]?.text ?? '');
}

function bounds(cues: ReadonlyArray<Cue>, span: GapSpan): [number, number] {
  const total = cues.length;
  if (!total || !span || span.count <= 0) return [0, 0];
  const start = Math.max(0, Math.min(span.from, total) - 1);
  const end = Math.max(start, Math.min(span.to, total));
  return [start, end];
}

/** 范围里的待译 / 原文已改计数。没有译文轨时整段都算待译（total = pending）。 */
export function gapCounts(
  cues: ReadonlyArray<Cue>,
  track: TranslationTrack | undefined,
  span: GapSpan,
): GapCounts {
  const [start, end] = bounds(cues, span);
  let total = 0;
  let pending = 0;
  let stale = 0;
  for (let index = start; index < end; index += 1) {
    total += 1;
    const text = track?.texts?.[index] ?? '';
    if (!text.trim()) {
      pending += 1;
      continue;
    }
    if (isStale(track, index, cues)) stale += 1;
  }
  return { total, pending, stale, translated: total - pending };
}

/**
 * 本次补译要复制的全片 1 基条号（升序）。
 *
 * `includeStale=false`（默认）只收空译文；`true` 时把「原文已改」也收进来——
 * 这个选择在界面上是显式勾选，不能在代码里悄悄打开。
 */
export function gapIndices(
  cues: ReadonlyArray<Cue>,
  track: TranslationTrack | undefined,
  span: GapSpan,
  includeStale = false,
): number[] {
  const [start, end] = bounds(cues, span);
  const out: number[] = [];
  for (let index = start; index < end; index += 1) {
    const text = track?.texts?.[index] ?? '';
    if (!text.trim() || (includeStale && isStale(track, index, cues))) {
      out.push(index + 1);
    }
  }
  return out;
}

/** 面板 / 提示条上的一句话；两组计数分开说，不混成「不可信」。 */
export function gapSummary(counts: GapCounts): string {
  const parts: string[] = [];
  if (counts.pending) parts.push(`${counts.pending} 条待译`);
  if (counts.stale) parts.push(`${counts.stale} 条原文已改`);
  if (!parts.length) return '全部同步';
  return parts.join(' · ');
}
