/**
 * 波形画布的纯绘制 helper。
 *
 * 从 `ReviewView.svelte` 抽出：这些函数只依赖 canvas context 与几何参数，不读组件状态。
 * 这样大文件预算（红线 11）能留出空间，也让「刻度 / 圆角矩形 / 峰值柱」只有一份实现。
 */

/** 兼容 `ctx.roundRect` 不存在时的圆角矩形。 */
export function roundRect(
  ctx: CanvasRenderingContext2D,
  x: number,
  y: number,
  w: number,
  h: number,
  r: number,
) {
  const rad = Math.min(r, w / 2, h / 2);
  ctx.beginPath();
  if (typeof ctx.roundRect === 'function') {
    ctx.roundRect(x, y, w, h, rad);
    return;
  }
  ctx.moveTo(x + rad, y);
  ctx.arcTo(x + w, y, x + w, y + h, rad);
  ctx.arcTo(x + w, y + h, x, y + h, rad);
  ctx.arcTo(x, y + h, x, y, rad);
  ctx.arcTo(x, y, x + w, y, rad);
  ctx.closePath();
}

/** 当前视窗跨度下，刻度该每多少秒画一根。 */
export function pickRulerStep(span: number): number {
  const candidates = [0.1, 0.2, 0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300, 600];
  for (const c of candidates) {
    if (span / c <= 12) return c;
  }
  return 900;
}

/** 相邻刻度标签之间至少留出的空隙（px），防止右端被夹回来后叠成一团。 */
export const RULER_LABEL_GAP = 6;

/**
 * 一个刻度标签的 x 坐标（纯函数，方便单测）。
 *
 * 默认放在刻度右侧 `+3`；右侧放不下时，把整个标签向左夹到画布内，
 * 而不是移到刻度左边（旧实现 `x - lw - 4` 会让最后一个标签压到前一个上，
 * 2026-11-25 用户截图里「165:00」和「180:00」叠在一起就是这条）。
 */
export function rulerLabelX(tickX: number, labelWidth: number, width: number): number {
  const preferred = tickX + 3;
  const clamped = Math.min(preferred, width - 2 - labelWidth);
  return Math.max(0, clamped);
}

/** 刻度标签：小于 1 秒时显示十分之一秒，避免出现两位小数。 */
export function rulerLabel(t: number, step: number): string {
  if (step < 1) {
    const tenths = Math.round(Math.max(0, t) * 10);
    const m = Math.floor(tenths / 600);
    const s = Math.floor(tenths / 10) % 60;
    return `${m}:${String(s).padStart(2, '0')}.${tenths % 10}`;
  }
  const total = Math.round(t);
  const m = Math.floor(total / 60);
  const s = total % 60;
  if (step < 60) return `${m}:${String(s).padStart(2, '0')}`;
  return `${m}:00`;
}

import type { Cue } from './api';

export interface RulerInput {
  viewStart: number;
  viewSpan: number;
  width: number;
  rulerH: number;
  separator: string;
  separatorStrong: string;
  text: string;
  xOf: (time: number) => number;
  /**
   * 播放头浮标在画布上的覆盖范围 `[left, right]`（px，含浮标自身的留白）。
   * 浮标是叠在画布上的 HTML 芯片，会盖住刻度标签的一半，读起来像
   * 「00:04.72005」。落在它底下的标签直接不画——和「太挤就不画字」是同一条纪律：
   * 宁可少一个标签，也不要出现半截字。
   */
  avoid?: [number, number] | null;
}

/** 顶部时间刻度 + 刻度条底线。 */
export function paintRuler(ctx: CanvasRenderingContext2D, input: RulerInput) {
  const step = pickRulerStep(input.viewSpan);
  // 11px = DESIGN.md 的 Data 档：刻度标签与时间码、计数同一档，不抢字幕
  ctx.font = '11px "SF Mono", ui-monospace, Menlo, monospace';
  ctx.textBaseline = 'top';
  const first = Math.ceil(input.viewStart / step) * step;
  // 已画标签的右边界：夹回来的最后一个标签不许再压到前一个上。
  let lastLabelRight = -Infinity;
  for (let t = first; t <= input.viewStart + input.viewSpan; t += step) {
    const x = Math.round(input.xOf(t)) + 0.5;
    const major = Math.abs(t / (step * 5) - Math.round(t / (step * 5))) < 1e-6;
    ctx.fillStyle = major ? input.separatorStrong : input.separator;
    ctx.fillRect(x, 0, 1, major ? 7 : 4);
    if (major || step >= 5) {
      const label = rulerLabel(t, step);
      const lw = ctx.measureText(label).width;
      const lx = rulerLabelX(x, lw, input.width);
      const hidden = input.avoid ? lx < input.avoid[1] && lx + lw > input.avoid[0] : false;
      // 太挤 / 被播放头浮标压住就只画刻度不画字：宁可少一个标签，也不要出现叠字。
      if (!hidden && lx >= lastLabelRight + RULER_LABEL_GAP) {
        ctx.fillStyle = input.text;
        ctx.fillText(label, lx, 1);
        lastLabelRight = lx + lw;
      }
    }
  }
  ctx.fillStyle = input.separator;
  ctx.fillRect(0, input.rulerH - 0.5, input.width, 1);
}

/** 字幕覆盖区：在波形背后垫一层极淡的蓝，同区间只画一次。 */
export function paintCueWash(
  ctx: CanvasRenderingContext2D,
  cues: readonly Cue[],
  viewStart: number,
  viewSpan: number,
  width: number,
  rulerH: number,
  laneTop: number,
  color: string,
  xOf: (time: number) => number,
) {
  const drawn = new Set<string>();
  for (const cue of cues) {
    if (cue.end < viewStart || cue.start > viewStart + viewSpan) continue;
    const key = `${cue.start}:${cue.end}`;
    if (drawn.has(key)) continue;
    drawn.add(key);
    const x0 = Math.max(0, xOf(cue.start));
    const x1 = Math.min(width, xOf(cue.end));
    if (x1 <= x0) continue;
    ctx.fillStyle = color;
    ctx.fillRect(x0, rulerH, Math.max(1, x1 - x0), laneTop - rulerH);
  }
}

/** 当前选中行的区间高亮（不是选区）：中性墨，不叠蓝。 */
export function paintSelectedCueWash(
  ctx: CanvasRenderingContext2D,
  cue: Pick<Cue, 'start' | 'end'>,
  viewStart: number,
  width: number,
  rulerH: number,
  laneTop: number,
  color: string,
  xOf: (time: number) => number,
) {
  const x0 = Math.max(0, xOf(cue.start));
  const x1 = Math.min(width, xOf(cue.end));
  if (x1 <= x0) return;
  ctx.fillStyle = color;
  ctx.globalAlpha = 0.5;
  ctx.fillRect(x0, rulerH, Math.max(1, x1 - x0), laneTop - rulerH);
  ctx.globalAlpha = 1;
}

export interface CueBlocksInput {
  cues: readonly Cue[];
  viewStart: number;
  viewSpan: number;
  width: number;
  laneTop: number;
  laneHeight: number;
  selectedKey: string;
  activeKey: string;
  hoverKey: string;
  dragKey: string;
  laneSelection: readonly string[];
  cueBlock: string;
  cueBlockHover: string;
  cueBlockActive: string;
  cueEdge: string;
  accent: string;
  xOf: (time: number) => number;
}

/**
 * 底部字幕轨道块。
 *
 * 同区间的双语 / 三语行只画一次（按 `start:end` 去重）；选中、悬停、拖动、
 * ⌘ 多选共用同一套配色与两端抓手。纯绘制，不读组件状态。
 */
export function paintCueBlocks(ctx: CanvasRenderingContext2D, input: CueBlocksInput) {
  const blockY = input.laneTop + 3;
  const blockH = input.laneHeight - 6;
  const picked = new Set(input.laneSelection);
  const drawn = new Set<string>();
  for (const cue of input.cues) {
    if (cue.end < input.viewStart || cue.start > input.viewStart + input.viewSpan) continue;
    const key = `${cue.start}:${cue.end}`;
    if (drawn.has(key)) continue;
    drawn.add(key);
    const x0 = Math.max(0, input.xOf(cue.start));
    const x1 = Math.min(input.width, input.xOf(cue.end));
    if (x1 <= x0 + 0.5) continue;
    const bw = Math.max(2, x1 - x0 - 0.5);
    const active = key === input.activeKey;
    const touched = key === input.hoverKey || key === input.dragKey;
    const chosen = picked.has(key);
    ctx.fillStyle = active || chosen ? input.cueBlockActive : touched ? input.cueBlockHover : input.cueBlock;
    if (chosen && !active) ctx.globalAlpha = 0.66;
    roundRect(ctx, x0, blockY, bw, blockH, 2.5);
    ctx.fill();
    ctx.globalAlpha = 1;
    // 当前句 / 悬停 / 选中块描一圈边，哪怕底色很浅也能一眼分清边界
    if (active || touched || key === input.selectedKey || chosen) {
      ctx.strokeStyle = chosen ? input.accent : input.cueEdge;
      ctx.globalAlpha = active || chosen ? 0.95 : 0.45;
      ctx.lineWidth = chosen ? 1.6 : 1;
      roundRect(ctx, x0 + 0.5, blockY + 0.5, Math.max(1, bw - 1), blockH - 1, 2.5);
      ctx.stroke();
      ctx.globalAlpha = 1;
    }
    // 当前句 / 被拖动的块加两端抓手，告诉用户「这里可以左右拉」
    if (active || touched) {
      ctx.fillStyle = input.cueEdge;
      ctx.fillRect(x0 + 2, blockY + 4, 1.5, blockH - 8);
      ctx.fillRect(x0 + bw - 3.5, blockY + 4, 1.5, blockH - 8);
    }
  }
}

/** 磁吸参考线：从刻度条贯穿到轨道底部的虚线。 */
export function drawSnapGuide(
  ctx: CanvasRenderingContext2D,
  x: number,
  height: number,
  color: string,
) {
  ctx.save();
  ctx.strokeStyle = color;
  ctx.globalAlpha = 0.85;
  ctx.setLineDash([3, 3]);
  ctx.beginPath();
  ctx.moveTo(Math.round(x) + 0.5, 0);
  ctx.lineTo(Math.round(x) + 0.5, height);
  ctx.stroke();
  ctx.restore();
}

export interface PeakBarsInput {
  peaks: readonly number[];
  peaksFrom: number;
  peaksSpan: number;
  viewStart: number;
  viewSpan: number;
  width: number;
  mid: number;
  ampH: number;
  color: string;
  alpha: number;
  /** 只画到这条像素线（已播放段用）。 */
  right: number;
}

/**
 * 逐像素绘制峰值包络。
 *
 * 一个像素覆盖的所有采样点取最大值；放大到 1 秒视窗时仍然是一条连续包络，
 * 不会退化成一排可数的柱子（仍与旧实现一致）。
 */
export function paintPeakBars(ctx: CanvasRenderingContext2D, input: PeakBarsInput) {
  const n = input.peaks.length;
  if (!n) return;
  const w = input.width;
  const span = input.peaksSpan || 1;
  const perBin = span / n;
  const limit = Math.max(0, Math.min(w, input.right));
  ctx.fillStyle = input.color;
  ctx.globalAlpha = input.alpha;
  for (let x = 0; x < limit; x += 1) {
    const t0 = input.viewStart + (x / w) * input.viewSpan;
    const t1 = input.viewStart + ((x + 1) / w) * input.viewSpan;
    let i0 = Math.floor((t0 - input.peaksFrom) / perBin);
    let i1 = Math.ceil((t1 - input.peaksFrom) / perBin);
    if (i1 <= 0 || i0 >= n) continue;
    i0 = Math.max(0, i0);
    i1 = Math.min(n, Math.max(i0 + 1, i1));
    let amp = 0;
    for (let i = i0; i < i1; i += 1) {
      if (input.peaks[i] > amp) amp = input.peaks[i];
    }
    // 全局峰值归一化会让对白显得很小；轻微 gamma 把弱信号抬起来，满幅配乐仍封顶。
    const shaped = Math.min(1, Math.pow(Math.max(0, amp), 0.72) * 1.08);
    const bh = Math.max(1.2, shaped * input.ampH);
    ctx.fillRect(x, input.mid - bh / 2, 1, bh);
  }
  ctx.globalAlpha = 1;
}
