/**
 * 核对台波形画布的一次完整重绘（从 ReviewView 抽出，行为不变）。
 *
 * 为什么整段搬出来：核对台要新增「章节旗标 / 区间色条」，而这块 `draw()` 每次
 * 动它都得先读完整份 state。抽出后组件只负责把当前状态传进来，画法（主题令牌、
 * 刻度、波形、选中高亮、字幕轨道、吸附参考线）只有这一份实现。
 *
 * 纯绘制：不写任何响应式状态，也不持有 DOM 之外的引用；`getComputedStyle` 是
 * 读取主题令牌的唯一途径（红线 7：主题只走令牌）。
 */

import type { Cue } from './api';
import {
  drawSnapGuide,
  paintCueBlocks,
  paintCueWash,
  paintPeakBars,
  paintRuler,
  paintSelectedCueWash,
} from './waveformDraw';

export interface WaveformPaintInput {
  canvas: HTMLCanvasElement;
  waveWrap: HTMLDivElement;
  peaks: number[];
  peaksFrom: number;
  peaksSpan: number;
  viewStart: number;
  viewSpan: number;
  cues: Cue[];
  /** 当前选中行；-1 表示没有。 */
  selectedIndex: number;
  playTime: number;
  /** 底部字幕轨道三态高亮（块 key，双语同区间共用一个）。 */
  activeKey: string;
  hoverKey: string;
  dragKey: string;
  laneSelection: string[];
  snapGuide: number | null;
  /** 顶部刻度条高度；底部轨道高度。由组件持有（命中判定共用同一组常量）。 */
  rulerH: number;
  laneH: number;
  /** 最底部波形高度把手高度：轨道上沿 = h - resizeH - laneH。 */
  resizeH: number;
}

/**
 * 波形包络的采样点数：按像素的 3 倍取，放大到 1 秒视窗时仍有足够包络，
 * 不会退化成一排可数的柱子。服务端只读这一小段样本，成本可忽略。
 * 缓存键必须带上这个数（`peakCacheKey` 的第四个参数）。
 */
export function binsForWidth(width: number): number {
  return Math.max(512, Math.min(12000, Math.round(width * 3)));
}

export function paintReviewCanvas(input: WaveformPaintInput): void {
  const { canvas, waveWrap } = input;
  const w = waveWrap.clientWidth;
  const h = waveWrap.clientHeight;
  if (!w || !h) return;
  const dpr = window.devicePixelRatio || 1;
  const ctx = canvas.getContext('2d');
  if (!ctx) return;
  // 播放时每帧都会重绘：只在尺寸真变了的时候重设画布，避免每帧重新分配位图。
  const pw = Math.round(w * dpr);
  const ph = Math.round(h * dpr);
  if (canvas.width !== pw || canvas.height !== ph) {
    canvas.width = pw;
    canvas.height = ph;
  }
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, w, h);

  const { viewStart, viewSpan, rulerH, laneH, resizeH } = input;
  const xOf = (time: number) => ((time - viewStart) / (viewSpan || 1)) * w;

  const css = getComputedStyle(document.documentElement);
  const token = (name: string, fallback: string) => css.getPropertyValue(name).trim() || fallback;
  const sep = token('--separator-soft', 'rgba(0,0,0,.06)');
  const sepStrong = token('--separator', 'rgba(0,0,0,.1)');
  const waveColor = token('--wave', '#7b8a99');
  const accent = token('--accent', '#4f6bff');
  const text3 = token('--text-3', '#98989d');
  const cueLane = token('--cue-lane', 'rgba(0,0,0,.055)');
  const cueWash = token('--cue-wash', 'rgba(0,122,255,.035)');
  const cueBlock = token('--cue-block', 'rgba(0,122,255,.28)');
  const cueBlockHover = token('--cue-block-hover', 'rgba(0,122,255,.46)');
  const cueBlockActive = token('--cue-block-active', 'rgba(0,122,255,.82)');
  const cueEdge = token('--cue-edge', 'rgba(0,122,255,.9)');

  const laneTop = h - resizeH - laneH;
  const mid = rulerH + (laneTop - rulerH) / 2;
  const ampH = Math.max(8, (laneTop - rulerH) * 0.94);

  // 字幕覆盖区在波形背后垫一层极淡的蓝（同区间双语行只画一次）。
  paintCueWash(ctx, input.cues, viewStart, viewSpan, w, rulerH, laneTop, cueWash, xOf);

  // 时间刻度
  paintRuler(ctx, {
    viewStart,
    viewSpan,
    width: w,
    rulerH,
    separator: sep,
    separatorStrong: sepStrong,
    text: text3,
    xOf,
    // 播放头浮标约 62px 宽、以播放头为中（靠边时 HTML 侧会夹住，这里按 72px 覆盖算）
    avoid: [xOf(input.playTime) - 36, xOf(input.playTime) + 36],
  });

  // 波形：逐像素取该像素覆盖的所有采样点的最大值（纯绘制见 lib/waveformDraw）。
  if (!input.peaks.length) {
    ctx.fillStyle = sepStrong;
    ctx.fillRect(0, Math.round(mid), w, 1);
  } else {
    const base = {
      peaks: input.peaks,
      peaksFrom: input.peaksFrom,
      peaksSpan: input.peaksSpan,
      viewStart,
      viewSpan,
      width: w,
      mid,
      ampH,
    };
    paintPeakBars(ctx, { ...base, color: waveColor, alpha: 0.9, right: w });
    // 已播放段用 accent 再画一遍：当前进度在波形上一眼可见（比未播放段更深）
    const playedX = xOf(input.playTime);
    if (playedX > 0.5) {
      paintPeakBars(ctx, { ...base, color: accent, alpha: 0.9, right: playedX });
    }
  }

  // 选中行的区间高亮（不是选区，只是当前条目）：中性墨，别再加一层蓝。
  const selected = input.selectedIndex >= 0 ? input.cues[input.selectedIndex] : null;
  if (selected) {
    paintSelectedCueWash(ctx, selected, viewStart, w, rulerH, laneTop, sepStrong, xOf);
  }

  // 底槽：明确区分「轨道」与「波形」，哪怕整片都没有字幕也能看出这里有东西。
  ctx.fillStyle = cueLane;
  ctx.fillRect(0, laneTop, w, laneH - 1);

  paintCueBlocks(ctx, {
    cues: input.cues,
    viewStart,
    viewSpan,
    width: w,
    laneTop,
    laneHeight: laneH,
    selectedKey: selected ? `${selected.start}:${selected.end}` : '',
    activeKey: input.activeKey,
    hoverKey: input.hoverKey,
    dragKey: input.dragKey,
    laneSelection: input.laneSelection,
    cueBlock,
    cueBlockHover,
    cueBlockActive,
    cueEdge,
    accent,
    xOf,
  });
  if (input.snapGuide !== null) drawSnapGuide(ctx, xOf(input.snapGuide), h, accent);
}
