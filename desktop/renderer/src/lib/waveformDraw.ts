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
