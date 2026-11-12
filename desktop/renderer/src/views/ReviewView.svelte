<script lang="ts">
  /**
   * 核对工作台。
   *
   * 这一屏是整个应用最像「专业工具」的地方，交互必须对得上肌肉记忆：
   *
   * - 波形可缩放（滚轮 / 捏合 / 滑块）与平移（双指横移 / ⌥ 拖动选区外部），
   * - 单击波形 = 跳转；按住并移动超过 4px 才算框选——全局视图下 1px 就是好几秒，
   *   手抖绝不能把「单击」判成「框选」；
   * - 顶部刻度条与播放头两侧 8px 是专属擦洗区：按住拖动即可逐帧预览，
   *   视频进度条同样支持拖动，三者共用一个「暂停 → 跟手 seek → 松手恢复」的擦洗器；
   * - 底部字幕轨道用品牌蓝块表示「这段有字幕」：拖块体整体平移、拖两端改起止；
   *   双语同区间的多行作为一块成组编辑，提交走一次撤回；
   * - 播放头进入某句字幕时，底部表格滚到该句、右侧检查器同步选中（播放中也一样）；
   * - 跟随是持久化偏好：只有点按钮才会改变；跳转（哪怕暂停）会把播放头带回视窗，
   *   播放时则整页平移跟随。缩放/平移波形不会偷偷关掉它；
   * - 每一行都能单独重转，不会冲掉整张表；
   * - 质检面板通过 store 的 focusRange 定位到这里，跳转是真的跳。
   */
  import { tick as nextTick, untrack } from 'svelte';
  import Icon from '../components/Icon.svelte';
  import { api, mediaUrl } from '../lib/api';
  import { logEvent } from '../lib/api';
  import {
    app,
    applyCueTimes,
    closeFind,
    extractTtsVoiceFromCue,
    findState,
    focusRange,
    insertCueAt,
    isTranslationStale,
    jumpToCue,
    play,
    previewRange,
    rememberPlayhead,
    replaceAllInCues,
    replaceInCue,
    seekTo,
    startProxyJob,
    toast,
    translationAt,
    transcribeRange,
    tts,
  } from '../lib/store.svelte';
  import { formatDuration, tc, tcShort } from '../lib/time';

  let { engine = 'whisper' }: { engine?: string } = $props();

  let video = $state<HTMLVideoElement | null>(null);
  let waveWrap = $state<HTMLDivElement | null>(null);
  let canvas = $state<HTMLCanvasElement | null>(null);
  let rowsEl = $state<HTMLDivElement | null>(null);

  let peaks = $state<number[]>([]);
  let peaksFrom = $state(0);
  let peaksSpan = $state(0);
  let loadingPeaks = $state(false);
  let videoFailed = $state(false);
  let scrollTop = $state(0);
  let viewH = $state(0);
  let waveW = $state(0);
  // 波形高度：默认 80（D 稿），可拖动底部把手调整；记住用户选择。
  const savedHeight = Number(localStorage.getItem('kikusub.waveHeight') || 0);
  let waveHeight = $state(Math.max(72, Math.min(300, savedHeight || 80)));

  // 波形视窗（秒）。duration 来自媒体元数据。
  const duration = $derived(app.media?.duration ?? 0);
  let viewStart = $state(0);
  let viewSpan = $state(60);
  /**
   * 跟随是「用户偏好」，不是临时状态：
   * 只由用户点按钮改变，并持久化。缩放/平移波形、单击跳转、点字幕行、
   * 点底部字幕块都不许把它悄悄关掉（这些都被用户报成 bug）。
   */
  let follow = $state(localStorage.getItem('kikusub.follow') !== '0');
  let selection = $state<{ start: number; end: number } | null>(null);

  const MIN_SPAN = 0.5;
  /**
   * 所有「聚焦」按钮的统一倍率：相对全片时长固定 69×，不会因为当前已经放大
   * 到 145× 再点一次就叠成 415×。用户明确要求「聚焦定死 69 倍」。
   */
  const FOCUS_ZOOM = 69;

  // 时间轴三条竖带。绘制与命中判定共用同一组常量，避免“看到的”和“点到的”错位。
  const RULER_H = 17; // 顶部刻度条：按住拖动 = 擦洗播放头
  const LANE_H = 17; // 底部字幕轨道：拖块体移动整句，拖两端改时间戳
  const RESIZE_H = 6; // 最底部的波形高度把手
  const EDGE = 6; // 字幕块左右端的抓取宽度（px）
  const PLAYHEAD_GRAB = 8; // 播放头两侧的抓取宽度（px）
  const CLICK_SLOP = 4; // 按下后移动超过它才算框选，否则算单击跳转

  const laneTopOf = (h: number) => h - RESIZE_H - LANE_H;

  // 光标与高亮（悬停/拖动的字幕块用 key 标识，双语同区间的两行算同一块）
  let waveCursor = $state('crosshair');
  let hoverKey = $state('');
  let dragKey = $state('');
  let cueTip = $state<{ x: number; label: string } | null>(null);
  /** 音轨/字幕表右键菜单：在光标处插入空字幕，或把这一句切成克隆音色。 */
  let contextMenu = $state<{ x: number; y: number; t: number; index: number } | null>(null);
  /** 「以此句音频新建音色」浮层：命名 + 可选参考文本。 */
  let voiceDialog = $state<{ index: number; name: string; refText: string } | null>(null);
  let voiceBusy = $state(false);
  let voiceNameEl = $state<HTMLInputElement | null>(null);

  // 视频进度条拖动
  let trackDrag = $state(false);
  // 最近一次自动滚到/选中过的字幕行，避免同一句反复滚动
  let lastRevealed = -1;

  // 虚拟列表：行高固定 30px（双语 60px），只渲染可视区 ± OVERSCAN 行。
  const ROW_H = 30;
  const OVERSCAN = 7;

  // 有代理就走代理：Chromium 解不开 MKV / HEVC，原片喂进去只会黑屏。
  const src = $derived(
    app.media ? mediaUrl(app.media.id, Boolean(app.media.proxy_ready)) : '',
  );
  const proxyBusy = $derived(
    app.jobKind === 'proxy' &&
      (app.job?.status === 'running' || app.job?.status === 'queued'),
  );

  // 当前播放到的字幕。双语 SRT 的两行区间完全相同，必须一起显示。
  const captionLines = $derived.by(() => {
    // 显式依赖：切换显示模式或译文更新时，画面字幕要立刻跟着变
    void app.track;
    void app.translations[app.trackLang]?.texts.length;
    const cues = app.cues;
    if (!cues.length) return [] as string[];
    const t = play.time;
    let lo = 0;
    let hi = cues.length - 1;
    let hit = -1;
    while (lo <= hi) {
      const mid = (lo + hi) >> 1;
      const c = cues[mid];
      if (t < c.start) hi = mid - 1;
      else if (t >= c.end) lo = mid + 1;
      else {
        hit = mid;
        break;
      }
    }
    if (hit < 0) return [];
    const key = `${cues[hit].start}:${cues[hit].end}`;
    const lines: string[] = [];
    let i = hit;
    while (i >= 0 && `${cues[i].start}:${cues[i].end}` === key) i -= 1;
    const idxs: number[] = [];
    for (let k = i + 1; k < cues.length; k += 1) {
      if (`${cues[k].start}:${cues[k].end}` !== key) break;
      if (cues[k].text.trim()) idxs.push(k);
    }

    // 画面字幕跟着「原文 / 译文 / 双语」切换：双语是原文在上、译文在下。
    // 译文缺失时退回原文，绝不在画面上留空行。
    //
    // 一条 cue 里可能带 `\n`（外部 SRT 的硬换行、旧版双语文件）：必须拆成多行
    // 交给叠加层，否则 `white-space` 会把它压成「日文 中文」一行（用户报过）。
    for (const k of idxs) {
      const sourceLines = captionTextLines(cues[k].text);
      const targetLines = captionTextLines(translationAt(k));
      if (app.track === 'target') {
        lines.push(...(targetLines.length ? targetLines : sourceLines));
      } else if (app.track === 'both') {
        lines.push(...sourceLines);
        if (targetLines.length) lines.push(...targetLines);
      } else {
        lines.push(...sourceLines);
      }
    }
    return lines;
  });

  const cueIndex = $derived.by(() => {
    const t = play.time;
    const cues = app.cues;
    let lo = 0;
    let hi = cues.length - 1;
    while (lo <= hi) {
      const mid = (lo + hi) >> 1;
      const c = cues[mid];
      if (t < c.start) hi = mid - 1;
      else if (t >= c.end) lo = mid + 1;
      else return mid;
    }
    return -1;
  });

  /**
   * 当前画面对应的「字幕块」区间。双语 SRT 的日/中两行完全同区间，
   * 表格高亮与检查器都必须认这一整块，而不是只认第一条。
   */
  const activeKey = $derived.by(() => {
    const c = cueIndex >= 0 ? app.cues[cueIndex] : null;
    return c ? `${c.start}:${c.end}` : '';
  });

  // 双语是**固定双行高**：自动测量会和虚拟滚动的绝对定位打架（开发文档 §6.3.2）
  const rowHeight = $derived(app.track === 'both' ? ROW_H * 2 : ROW_H);
  const rowStart = $derived(Math.max(0, Math.floor(scrollTop / rowHeight) - OVERSCAN));
  const rowEnd = $derived(
    Math.min(
      app.cues.length,
      rowStart + Math.ceil((viewH || 400) / rowHeight) + OVERSCAN * 2,
    ),
  );
  const visibleCues = $derived(app.cues.slice(rowStart, rowEnd));

  const zoomX = $derived(duration > 0 ? Math.max(1, duration / Math.max(viewSpan, 0.001)) : 1);
  const progressPct = $derived(
    Math.max(0, Math.min(100, duration > 0 ? (play.time / duration) * 100 : 0)),
  );
  const busy = $derived(
    app.job?.status === 'queued' ||
      app.job?.status === 'running' ||
      app.job?.status === 'cancelling',
  );
  const rangeBusy = $derived(busy && app.jobMeta?.scope === 'range');

  // ---------------- 视窗与坐标 ----------------
  function clampView(start: number, span: number) {
    const d = duration || span;
    const s = Math.max(MIN_SPAN, Math.min(span, d || MIN_SPAN));
    const a = Math.max(0, Math.min(start, Math.max(0, d - s)));
    return { start: a, span: s };
  }

  /**
   * 改视窗只负责缩放/平移；跟随是独立偏好，绝不在这里被顺手关掉。
   * 专业剪辑软件也不会因为缩放时间线就取消「跟随播放头」。
   */
  function setView(start: number, span: number) {
    const next = clampView(start, span);
    viewStart = next.start;
    viewSpan = next.span;
  }

  /**
   * 跳转（包括暂停状态下点字幕）后把播放头带回视窗。
   *
   * 以前只有「播放中 + 跟随」才会平移视窗，于是暂停时点一句远处的字幕，
   * 视频跳到了对应帧，波形上的播放头却跑出画面外；用户只能先开跟随再敲空格。
   * 现在跟随开启时，任何 seek 都会补一次平移，不要求先播放。
   */
  function revealPlayhead(t = play.time) {
    if (!follow) return;
    const span = viewSpan;
    if (!(span > 0) || !(duration > 0)) return;
    // 已经在视窗里就不动，避免每次点当前句都把波形甩一下
    if (t >= viewStart && t <= viewStart + span) return;
    // 从右侧出去就从左侧 15% 处回来，反之亦然；缩放比例保持不变
    const anchor = t > viewStart + span ? 0.85 : 0.15;
    const next = clampView(t - span * anchor, span);
    viewStart = next.start;
  }

  function xOf(time: number) {
    return ((time - viewStart) / (viewSpan || 1)) * waveW;
  }

  function timeAt(clientX: number) {
    if (!waveWrap) return 0;
    const r = waveWrap.getBoundingClientRect();
    const ratio = Math.max(0, Math.min(1, (clientX - r.left) / Math.max(1, r.width)));
    return viewStart + ratio * viewSpan;
  }

  // 媒体变化：视窗归零、清空选区与波形
  $effect(() => {
    void app.media?.id;
    void app.media?.duration;
    const d = app.media?.duration ?? 0;
    play.duration = d;
    viewStart = 0;
    viewSpan = d || 60;
    selection = null;
    peaks = [];
    peaksFrom = 0;
    peaksSpan = 0;
    hoverKey = '';
    dragKey = '';
    cueTip = null;
    lastRevealed = -1;
  });

  // ---------------- 波形包络 ----------------
  let peakSeq = 0;
  let peakTimer = 0;

  async function fetchPeaks(id: string, from: number, span: number, width: number) {
    const seq = ++peakSeq;
    loadingPeaks = true;
    try {
      // 采样点数按像素的 3 倍取：放大到 1 秒视窗时仍有足够包络，
      // 不会退化成一排可数的柱子。服务端只读这一小段样本，成本可忽略。
      const bins = Math.max(512, Math.min(12000, Math.round(width * 3)));
      const data = await api.peaks(id, { from, to: from + span, bins });
      if (seq !== peakSeq) return;
      peaks = data.peaks;
      peaksFrom = from;
      peaksSpan = span;
    } catch {
      if (seq === peakSeq) peaks = [];
    } finally {
      if (seq === peakSeq) loadingPeaks = false;
    }
  }

  $effect(() => {
    const id = app.media?.id;
    const width = waveW;
    const from = viewStart;
    const span = viewSpan;
    if (!id || width <= 0 || span <= 0) return;
    clearTimeout(peakTimer);
    peakTimer = window.setTimeout(() => void fetchPeaks(id, from, span, width), 70);
    return () => clearTimeout(peakTimer);
  });

  // ---------------- 画布 ----------------
  function roundRect(
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

  function draw() {
    if (!canvas || !waveWrap) return;
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

    const css = getComputedStyle(document.documentElement);
    const token = (name: string, fallback: string) =>
      css.getPropertyValue(name).trim() || fallback;
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

    const laneTop = laneTopOf(h);
    const mid = RULER_H + (laneTop - RULER_H) / 2;
    const ampH = Math.max(8, (laneTop - RULER_H) * 0.94);

    // 字幕覆盖区在波形背后垫一层极淡的蓝：不抢波形，但一眼能看出「这段有字幕」。
    // 同区间的双语行只画一次，否则重叠区间会越叠越深。
    const drawn = new Set<string>();
    for (const cue of app.cues) {
      if (cue.end < viewStart || cue.start > viewStart + viewSpan) continue;
      const key = `${cue.start}:${cue.end}`;
      if (drawn.has(key)) continue;
      drawn.add(key);
      const x0 = Math.max(0, xOf(cue.start));
      const x1 = Math.min(w, xOf(cue.end));
      if (x1 <= x0) continue;
      ctx.fillStyle = cueWash;
      ctx.fillRect(x0, RULER_H, Math.max(1, x1 - x0), laneTop - RULER_H);
    }

    // 时间刻度
    const step = pickStep(viewSpan);
    ctx.font = '12px "SF Mono", ui-monospace, Menlo, monospace';
    ctx.textBaseline = 'top';
    const first = Math.ceil(viewStart / step) * step;
    for (let t = first; t <= viewStart + viewSpan; t += step) {
      const x = Math.round(xOf(t)) + 0.5;
      const major = Math.abs(t / (step * 5) - Math.round(t / (step * 5))) < 1e-6;
      ctx.fillStyle = major ? sepStrong : sep;
      ctx.fillRect(x, 0, 1, major ? 7 : 4);
      if (major || step >= 5) {
        ctx.fillStyle = text3;
        const label = rulerLabel(t, step);
        const lw = ctx.measureText(label).width;
        // 最右一格的标签别被画布裁掉：贴着右边界时向左放
        ctx.fillText(label, x + 4 + lw > w ? Math.max(0, x - lw - 4) : x + 3, 1);
      }
    }
    ctx.fillStyle = sep;
    ctx.fillRect(0, RULER_H - 0.5, w, 1);

    // 波形：逐像素取该像素覆盖的所有采样点的最大值。
    // 之前是「一个采样点画一根柱子」，放大后柱子间距会被拉开；逐像素合并后
    // 无论缩放到多深都是一条连续的包络，不会出现可数的柱形。
    const n = peaks.length;
    const paintBars = (color: string, alpha: number, right: number) => {
      if (!n) return;
      ctx.fillStyle = color;
      ctx.globalAlpha = alpha;
      const span = peaksSpan || 1;
      const perBin = span / n;
      const limit = Math.max(0, Math.min(w, right));
      for (let x = 0; x < limit; x += 1) {
        const t0 = viewStart + (x / w) * viewSpan;
        const t1 = viewStart + ((x + 1) / w) * viewSpan;
        let i0 = Math.floor((t0 - peaksFrom) / perBin);
        let i1 = Math.ceil((t1 - peaksFrom) / perBin);
        if (i1 <= 0 || i0 >= n) continue;
        i0 = Math.max(0, i0);
        i1 = Math.min(n, Math.max(i0 + 1, i1));
        let amp = 0;
        for (let i = i0; i < i1; i += 1) {
          if (peaks[i] > amp) amp = peaks[i];
        }
        // 全局峰值归一化会让对白显得很小；用轻微 gamma 把弱信号抬起来，
        // 满幅配乐仍然封顶，不会糊成一片。
        const shaped = Math.min(1, Math.pow(Math.max(0, amp), 0.72) * 1.08);
        const bh = Math.max(1.2, shaped * ampH);
        ctx.fillRect(x, mid - bh / 2, 1, bh);
      }
      ctx.globalAlpha = 1;
    };
    if (!n) {
      ctx.fillStyle = sepStrong;
      ctx.fillRect(0, Math.round(mid), w, 1);
    } else {
      paintBars(waveColor, 0.9, w);
      // 已播放段用 accent 再画一遍：当前进度在波形上一眼可见（比未播放段更深）
      const playedX = xOf(play.time);
      if (playedX > 0.5) paintBars(accent, 0.9, playedX);
    }

    // 选中行的区间高亮（不是选区，只是当前条目）：中性墨，别再加一层蓝
    if (play.selected >= 0 && app.cues[play.selected]) {
      const sel = app.cues[play.selected];
      const x0 = Math.max(0, xOf(sel.start));
      const x1 = Math.min(w, xOf(sel.end));
      if (x1 > x0) {
        ctx.fillStyle = sepStrong;
        ctx.globalAlpha = 0.5;
        ctx.fillRect(x0, RULER_H, Math.max(1, x1 - x0), laneTop - RULER_H);
        ctx.globalAlpha = 1;
      }
    }

    // ---------------- 底部字幕轨道 ----------------
    // 底槽：明确区分「轨道」与「波形」，哪怕整片都没有字幕也能看出这里有东西。
    ctx.fillStyle = cueLane;
    ctx.fillRect(0, laneTop, w, LANE_H - 1);

    const blockY = laneTop + 3;
    const blockH = LANE_H - 6;
    const selectedCue = play.selected >= 0 ? app.cues[play.selected] : null;
    const selectedKey = selectedCue ? `${selectedCue.start}:${selectedCue.end}` : '';
    drawn.clear();
    for (const cue of app.cues) {
      if (cue.end < viewStart || cue.start > viewStart + viewSpan) continue;
      const key = `${cue.start}:${cue.end}`;
      if (drawn.has(key)) continue;
      drawn.add(key);
      const x0 = Math.max(0, xOf(cue.start));
      const x1 = Math.min(w, xOf(cue.end));
      if (x1 <= x0 + 0.5) continue;
      const bw = Math.max(2, x1 - x0 - 0.5);
      const active = key === activeKey;
      const touched = key === hoverKey || key === dragKey;
      ctx.fillStyle = active ? cueBlockActive : touched ? cueBlockHover : cueBlock;
      roundRect(ctx, x0, blockY, bw, blockH, 2.5);
      ctx.fill();
      // 当前句/悬停/选中块描一圈边，哪怕底色很浅也能一眼分清边界
      if (active || touched || key === selectedKey) {
        ctx.strokeStyle = cueEdge;
        ctx.globalAlpha = active ? 0.95 : 0.45;
        ctx.lineWidth = 1;
        roundRect(ctx, x0 + 0.5, blockY + 0.5, Math.max(1, bw - 1), blockH - 1, 2.5);
        ctx.stroke();
        ctx.globalAlpha = 1;
      }
      // 当前句/被拖动的块加两端抓手，告诉用户「这里可以左右拉」
      if (active || touched) {
        ctx.fillStyle = cueEdge;
        ctx.fillRect(x0 + 2, blockY + 4, 1.5, blockH - 8);
        ctx.fillRect(x0 + bw - 3.5, blockY + 4, 1.5, blockH - 8);
      }
    }
  }

  function pickStep(span: number) {
    const candidates = [0.1, 0.2, 0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300, 600];
    for (const c of candidates) {
      if (span / c <= 12) return c;
    }
    return 900;
  }

  function rulerLabel(t: number, step: number) {
    if (step < 1) {
      // 按 0.1 秒取整再拆分，避免 99.999 → "1:39.10" 这种两位小数
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

  $effect(() => {
    void peaks;
    void viewStart;
    void viewSpan;
    void app.cues;
    void play.selected;
    void activeKey;
    void hoverKey;
    void dragKey;
    void app.theme;
    void waveW;
    void play.time;
    requestAnimationFrame(draw);
  });

  $effect(() => {
    if (!waveWrap) return;
    const ro = new ResizeObserver(() => {
      waveW = waveWrap?.clientWidth ?? 0;
      requestAnimationFrame(draw);
    });
    ro.observe(waveWrap);
    waveW = waveWrap.clientWidth;
    return () => ro.disconnect();
  });

  // ---------------- 播放头 / 擦洗 ----------------
  let rafId = 0;

  // 擦洗：拖动播放头或进度条时，play.time 立刻跟手，video.currentTime 每帧最多写一次，
  // 避免一次拖动触发上百个 seek 请求把解码器拖死。
  let scrubbing = false;
  let scrubTarget = 0;
  let scrubRaf = 0;
  let scrubResume = false;
  let lastSeekAt = 0;

  function setScrub(t: number) {
    const max = duration || video?.duration || Number.POSITIVE_INFINITY;
    const value = Math.max(0, Math.min(max, t));
    play.time = value;
    play.stopAt = 0;
    scrubTarget = value;
    // 每帧最多写一次 currentTime；窗口被遮挡时 rAF 会被节流，
    // 所以再加一条 16ms 的“立即写”分支，保证拖动时画面真的跟手。
    const now = performance.now();
    if (now - lastSeekAt >= 16) {
      lastSeekAt = now;
      flushScrub();
    } else if (!scrubRaf) {
      scrubRaf = requestAnimationFrame(flushScrub);
    }
  }

  function flushScrub() {
    scrubRaf = 0;
    if (!video) return;
    if (Math.abs(video.currentTime - scrubTarget) < 0.004) return;
    try {
      video.currentTime = scrubTarget;
    } catch {
      /* 媒体还没就绪：播放头数字照样跟手 */
    }
  }

  function beginScrub(t: number) {
    if (!scrubbing) {
      scrubResume = !video?.paused && !video?.ended && play.playing;
      if (scrubResume) video?.pause();
    }
    scrubbing = true;
    setScrub(t);
  }

  function endScrub() {
    if (!scrubbing) return;
    scrubbing = false;
    if (scrubRaf) {
      cancelAnimationFrame(scrubRaf);
      scrubRaf = 0;
    }
    if (video) {
      try {
        video.currentTime = scrubTarget;
      } catch {
        /* ignore */
      }
    }
    if (scrubResume) {
      scrubResume = false;
      void video?.play().catch(() => {});
    }
    // 擦洗期间不自动平移（手还在拖）；松手后把最终位置带回视窗
    revealPlayhead(scrubTarget);
  }

  function tick() {
    rafId = requestAnimationFrame(tick);
    if (!video) return;
    // 只在「真的能解码并且在播」时用 video.currentTime 驱动播放头。
    // MKV / HEVC 还没压好代理时 readyState 一直是 0，如果无条件同步，
    // 用户点哪里播放头都会被 video 的 0 覆盖回去——看起来就是「播放头坏了」。
    const ready = video.readyState >= 2 && !video.error;
    const t = ready ? video.currentTime : play.time;
    if (ready) {
      // 擦洗期间由手指说了算：seek 还没落盘时 currentTime 是滞后的，
      // 不能拿它把 play.time 拽回去，否则播放头会来回抖。
      if (!scrubbing && !video.paused && !video.ended) play.time = t;
      play.playing = !video.paused && !video.ended;
    } else if (!scrubbing) {
      play.playing = false;
    }
    if (play.stopAt > 0 && play.playing && t >= play.stopAt - 0.01) {
      video.pause();
      video.currentTime = play.stopAt;
      play.time = play.stopAt;
      play.stopAt = 0;
      return;
    }
    // 放大后播放：按「整页平移」跟随播放头，落点约在窗口左侧 15%
    if (
      follow &&
      play.playing &&
      !scrubbing &&
      viewSpan < duration * 0.96 &&
      (t > viewStart + viewSpan * 0.92 || t < viewStart + viewSpan * 0.02)
    ) {
      const next = clampView(t - viewSpan * 0.15, viewSpan);
      viewStart = next.start;
    }
  }

  function bindVideo(node: HTMLVideoElement) {
    video = node;
    rafId = requestAnimationFrame(tick);
    return {
      destroy() {
        cancelAnimationFrame(rafId);
        video = null;
      },
    };
  }

  // 波形高度拖拽
  let resizeStart: { y: number; h: number } | null = null;

  function onResizeDown(e: PointerEvent) {
    e.stopPropagation();
    e.preventDefault();
    resizeStart = { y: e.clientY, h: waveHeight };
    try {
      (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
    } catch {
      /* ignore */
    }
  }

  function onResizeMove(e: PointerEvent) {
    if (!resizeStart) return;
    const next = Math.max(110, Math.min(300, resizeStart.h + (e.clientY - resizeStart.y)));
    waveHeight = next;
  }

  function onResizeUp() {
    if (!resizeStart) return;
    resizeStart = null;
    localStorage.setItem('kikusub.waveHeight', String(Math.round(waveHeight)));
    requestAnimationFrame(draw);
  }

  // 所有「定位」入口都通过 seekNonce 进来，视频与播放头不会各走各的
  let seenSeek = 0;
  $effect(() => {
    const nonce = play.seekNonce;
    if (nonce === seenSeek) return;
    seenSeek = nonce;
    // 只依赖 nonce：play.time / playAfterSeek 用 untrack 读，否则「读一下再写回」
    // 会让这个 effect 自己触发自己（effect_update_depth_exceeded）。
    const request = untrack(() => ({ time: play.time, play: play.playAfterSeek }));
    const t = Math.max(0, Math.min(request.time, video?.duration || duration || request.time));
    // 暂停时的跳转也要让播放头可见（跟随开启时）；视频尚未绑定也要平移波形
    untrack(() => revealPlayhead(t));
    if (!video) return;
    scrubbing = false;
    if (scrubRaf) {
      cancelAnimationFrame(scrubRaf);
      scrubRaf = 0;
    }
    scrubTarget = t;
    try {
      video.currentTime = t;
    } catch {
      /* 媒体还没就绪 */
    }
    if (request.play) {
      play.playAfterSeek = false;
      void video.play().catch(() => {});
    }
  });

  // 质检 / 选区聚焦请求
  let seenFocus = 0;
  $effect(() => {
    const req = play.focus;
    if (!req || req.nonce === seenFocus) return;
    seenFocus = req.nonce;
    // 右栏「聚焦」/ 质检定位也统一 69×：区间本身仍然框出来，但倍率不叠加。
    const span = focusSpan();
    const center = (req.start + req.end) / 2;
    // 这是程序化定位，不是用户手势：不要顺手关掉跟随
    setView(center - span / 2, span);
    selection = { start: req.start, end: req.end };
  });

  // ---------------- 交互 ----------------
  type DragMode =
    | 'none'
    | 'pending' // 已按下但还没超过阈值：仍可能只是单击
    | 'select'
    | 'playhead'
    | 'pan'
    | 'cue-move'
    | 'cue-l'
    | 'cue-r'
    | 'resize-l'
    | 'resize-r';

  let dragMode: DragMode = $state('none');
  let dragAnchor = 0;
  let dragMoved = false;
  let downX = 0;
  let downY = 0;
  let panStartX = 0;
  let panStartView = 0;

  type CueBlock = { key: string; start: number; end: number; indices: number[] };

  let cueDrag: {
    indices: number[];
    start: number;
    end: number;
    edge: 'move' | 'start' | 'end';
    anchorT: number;
    curStart: number | null;
    curEnd: number | null;
  } | null = null;

  function xPlayhead() {
    return xOf(play.time);
  }

  function togglePlay() {
    if (!video) return;
    if (video.paused) void video.play().catch(() => {});
    else video.pause();
  }

  function seek(time: number) {
    scrubbing = false;
    if (scrubRaf) {
      cancelAnimationFrame(scrubRaf);
      scrubRaf = 0;
    }
    scrubTarget = time;
    seekTo(time);
  }

  // ---------------- 视频进度条（逐帧拖动预览） ----------------
  function timeFromTrack(clientX: number, el: HTMLElement) {
    const r = el.getBoundingClientRect();
    const ratio = Math.max(0, Math.min(1, (clientX - r.left) / Math.max(1, r.width)));
    return ratio * (duration || 0);
  }

  function onTrackPointerDown(e: PointerEvent) {
    if (e.button !== 0 || duration <= 0) return;
    e.preventDefault();
    trackDrag = true;
    try {
      (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
    } catch {
      /* ignore */
    }
    beginScrub(timeFromTrack(e.clientX, e.currentTarget as HTMLElement));
  }

  function onTrackPointerMove(e: PointerEvent) {
    if (!trackDrag) return;
    setScrub(timeFromTrack(e.clientX, e.currentTarget as HTMLElement));
  }

  function onTrackPointerUp(e: PointerEvent) {
    if (!trackDrag) return;
    trackDrag = false;
    try {
      (e.currentTarget as HTMLElement).releasePointerCapture(e.pointerId);
    } catch {
      /* ignore */
    }
    endScrub();
  }

  function wavePoint(e: PointerEvent) {
    const r = (waveWrap as HTMLDivElement).getBoundingClientRect();
    return { x: e.clientX - r.left, y: e.clientY - r.top, w: r.width, h: r.height };
  }

  /**
   * 底部轨道上 x 处的字幕块。
   * 双语 SRT 的日/中两行共享同一区间，必须作为一块整体移动；这里返回整块的下标。
   */
  function cueBlockAt(x: number): CueBlock | null {
    const seen = new Set<string>();
    let bestKey = '';
    let bestSpan = Infinity;
    for (const cue of app.cues) {
      const key = `${cue.start}:${cue.end}`;
      if (seen.has(key)) continue;
      seen.add(key);
      const x0 = xOf(cue.start);
      const x1 = xOf(cue.end);
      if (x < x0 - 1 || x > x1 + 1) continue;
      const span = x1 - x0;
      if (span < bestSpan) {
        bestSpan = span;
        bestKey = key;
      }
    }
    if (!bestKey) return null;
    const indices: number[] = [];
    app.cues.forEach((cue, i) => {
      if (`${cue.start}:${cue.end}` === bestKey) indices.push(i);
    });
    if (!indices.length) return null;
    const first = app.cues[indices[0]];
    return { key: bestKey, start: first.start, end: first.end, indices };
  }

  function beginPlayhead(t: number) {
    dragMode = 'playhead';
    dragMoved = true;
    waveCursor = 'ew-resize';
    beginScrub(t);
  }

  function beginSelect(a: number, b: number) {
    dragMode = 'select';
    dragMoved = true;
    dragAnchor = a;
    selection = { start: Math.min(a, b), end: Math.max(a, b) };
  }

  function beginCueDrag(e: PointerEvent, block: CueBlock, x: number) {
    const pixelWidth = Math.abs(xOf(block.end) - xOf(block.start));
    // 全景视图里很短的一句可能只有几像素宽：这时两端抓手会重叠，
    // 整个块都当“移动”处理，否则根本拖不动。
    const edge: 'move' | 'start' | 'end' =
      pixelWidth < EDGE * 3
        ? 'move'
        : Math.abs(x - xOf(block.start)) <= EDGE
          ? 'start'
          : Math.abs(x - xOf(block.end)) <= EDGE
            ? 'end'
            : 'move';
    cueDrag = {
      indices: block.indices,
      start: block.start,
      end: block.end,
      edge,
      anchorT: timeAt(e.clientX),
      curStart: null,
      curEnd: null,
    };
    dragMode = edge === 'move' ? 'cue-move' : edge === 'start' ? 'cue-l' : 'cue-r';
    dragKey = block.key;
    hoverKey = block.key;
    waveCursor = edge === 'move' ? 'grabbing' : 'ew-resize';
    selection = null;
    // 检查器与表格跟着正在调整的这句走
    if (block.indices.length) play.selected = block.indices[0];
  }

  const roundMs = (v: number) => Math.round(v * 1000) / 1000;

  function updateCueDrag(t: number) {
    const drag = cueDrag;
    if (!drag) return;
    const max = duration > 0 ? duration : Math.max(drag.end, t0());
    let start = drag.start;
    let end = drag.end;
    const minDur = 0.05;
    if (drag.edge === 'move') {
      const dur = drag.end - drag.start;
      start = Math.max(0, Math.min(Math.max(0, max - dur), drag.start + (t - drag.anchorT)));
      end = start + dur;
    } else if (drag.edge === 'start') {
      start = Math.max(0, Math.min(drag.end - minDur, t));
    } else {
      end = Math.min(max, Math.max(drag.start + minDur, t));
    }
    start = roundMs(start);
    end = roundMs(end);
    if (drag.curStart === start && drag.curEnd === end) return;
    drag.curStart = start;
    drag.curEnd = end;
    for (const i of drag.indices) {
      const cue = app.cues[i];
      if (cue) {
        cue.start = start;
        cue.end = end;
      }
    }
    const mid = (start + end) / 2;
    cueTip = {
      x: Math.max(44, Math.min(Math.max(44, waveW - 44), xOf(mid))),
      label: `${tcShort(start)} → ${tcShort(end)}`,
    };
    requestAnimationFrame(draw);
  }

  function finishCueDrag() {
    const drag = cueDrag;
    cueDrag = null;
    dragMode = 'none';
    dragKey = '';
    cueTip = null;
    waveCursor = 'crosshair';
    if (!drag) return;
    const moved =
      drag.curStart !== null &&
      drag.curEnd !== null &&
      (Math.abs(drag.curStart - drag.start) > 1e-6 ||
        Math.abs(drag.curEnd - drag.end) > 1e-6);
    if (!moved) {
      // 点了一下字幕块：和点表格行一样，直接把播放头放到这句开头
      seek(drag.start + 0.02);
      return;
    }
    const changes = drag.indices.map((index) => ({
      index,
      start: drag.curStart as number,
      end: drag.curEnd as number,
    }));
    void applyCueTimes(changes);
  }

  function updateHover(e: PointerEvent) {
    if (!waveWrap) return;
    const pt = wavePoint(e);
    if (pt.y <= RULER_H + 1 || Math.abs(pt.x - xPlayhead()) <= PLAYHEAD_GRAB) {
      if (hoverKey) hoverKey = '';
      waveCursor = 'ew-resize';
      return;
    }
    if (pt.y >= pt.h - RESIZE_H - LANE_H) {
      const block = cueBlockAt(pt.x);
      if (!block) {
        if (hoverKey) hoverKey = '';
        waveCursor = 'crosshair';
        return;
      }
      if (hoverKey !== block.key) hoverKey = block.key;
      const pixelWidth = Math.abs(xOf(block.end) - xOf(block.start));
      const onEdge =
        pixelWidth >= EDGE * 3 &&
        (Math.abs(pt.x - xOf(block.start)) <= EDGE ||
          Math.abs(pt.x - xOf(block.end)) <= EDGE);
      waveCursor = onEdge ? 'ew-resize' : 'grab';
      return;
    }
    if (hoverKey) hoverKey = '';
    waveCursor = 'crosshair';
  }

  function onWavePointerDown(e: PointerEvent) {
    if (!waveWrap || e.button !== 0) return;
    contextMenu = null;
    try {
      (e.currentTarget as HTMLElement).setPointerCapture?.(e.pointerId);
    } catch {
      /* 合成事件 / 已释放的 pointerId：忽略即可，拖动逻辑不依赖捕获 */
    }
    const pt = wavePoint(e);
    const t = timeAt(e.clientX);
    dragMoved = false;
    downX = e.clientX;
    downY = e.clientY;
    cueTip = null;

    if (e.altKey) {
      dragMode = 'pan';
      panStartX = e.clientX;
      panStartView = viewStart;
      waveCursor = 'grabbing';
      // ⌥ 拖动只是临时平移视窗；跟随偏好保持不变（下次跳转/播放仍会带回播放头）
      return;
    }

    // 1) 顶部刻度条：专属擦洗带，拖它就只移动播放头，永远不会变成框选
    if (pt.y <= RULER_H + 1) {
      beginPlayhead(t);
      return;
    }

    // 2) 播放头两侧 8px：随时抓得住（不用精确点到 1px 的线）
    if (Math.abs(pt.x - xPlayhead()) <= PLAYHEAD_GRAB) {
      beginPlayhead(t);
      return;
    }

    // 3) 底部字幕轨道：拖块体移动整句，拖两端改时间戳
    if (pt.y >= pt.h - RESIZE_H - LANE_H) {
      const block = cueBlockAt(pt.x);
      if (block) {
        beginCueDrag(e, block, pt.x);
        return;
      }
      dragMode = 'pending';
      dragAnchor = t;
      return;
    }

    // 4) 波形主体：Shift 直接框选；否则先当作「可能是单击」
    if (e.shiftKey) {
      beginSelect(play.time, t);
      return;
    }
    dragMode = 'pending';
    dragAnchor = t;
  }

  function onWavePointerMove(e: PointerEvent) {
    if (!waveWrap) return;
    if (dragMode === 'none') {
      updateHover(e);
      return;
    }
    const t = Math.max(0, Math.min(duration || t0(), timeAt(e.clientX)));
    if (dragMode === 'pan') {
      const dx = e.clientX - panStartX;
      const shift = -(dx / Math.max(1, waveW)) * viewSpan;
      setView(panStartView + shift, viewSpan);
      dragMoved = true;
      return;
    }
    if (dragMode === 'pending') {
      // 超过阈值才升级成框选：全局视图下 1px 可能是好几秒，
      // 但手抖不该把「单击跳转」判成「框选了几秒」。
      if (Math.hypot(e.clientX - downX, e.clientY - downY) < CLICK_SLOP) return;
      beginSelect(dragAnchor, t);
      return;
    }
    if (dragMode === 'playhead') {
      setScrub(t);
      return;
    }
    if (dragMode === 'cue-move' || dragMode === 'cue-l' || dragMode === 'cue-r') {
      updateCueDrag(t);
      return;
    }
    if (!selection) return;
    if (dragMode === 'resize-l') {
      selection = { start: Math.min(t, selection.end - 0.05), end: selection.end };
      dragMoved = true;
      return;
    }
    if (dragMode === 'resize-r') {
      selection = { start: selection.start, end: Math.max(t, selection.start + 0.05) };
      dragMoved = true;
      return;
    }
    dragMoved = true;
    selection = { start: Math.min(dragAnchor, t), end: Math.max(dragAnchor, t) };
  }

  // 记住播放头：定时写 localStorage，重启后自动回到上次的位置。
  // 不在 $effect 里直接写：播放时 play.time 每帧变化，会变成每帧一次 localStorage。
  $effect(() => {
    const media = app.media;
    if (!media) return;
    const timer = setInterval(() => {
      if (play.time > 0.2) rememberPlayhead(play.time);
    }, 2500);
    return () => clearInterval(timer);
  });

  function t0() {
    return viewStart + viewSpan;
  }

  /**
   * 把浮层挂到 body 下。
   *
   * `.view-enter.animated` 的切页动画带 `animation-fill-mode: both`，结束后
   * 计算出的 transform 仍是 identity matrix——它会让 `position: fixed` 相对
   * 这个容器定位，于是右键菜单被整体推开了「侧栏 + 工具栏」那么多（用户报过
   * 「菜单离鼠标太远」）。挂到 body 后 clientX/clientY 才是真正的视口坐标。
   */
  function portal(node: HTMLElement) {
    document.body.appendChild(node);
    return {
      destroy() {
        node.remove();
      },
    };
  }

  /** 光标下是否有字幕；返回下标，没有就 -1。 */
  function cueUnder(t: number): number {
    for (let i = 0; i < app.cues.length; i += 1) {
      if (app.cues[i].start <= t && t <= app.cues[i].end) return i;
    }
    return -1;
  }

  /** 右键：菜单出现在光标处；越靠近窗口边缘越往回收，避免被裁掉。 */
  function onWaveContextMenu(e: MouseEvent) {
    e.preventDefault();
    const t = Math.max(0, Math.min(duration || Number.POSITIVE_INFINITY, timeAt(e.clientX)));
    const hit = cueUnder(t);
    if (hit >= 0) play.selected = hit;
    const x = Math.min(e.clientX, window.innerWidth - 232);
    const y = Math.min(e.clientY, window.innerHeight - 132);
    contextMenu = { x, y, t, index: hit };
  }

  /** 字幕表整行右键：选中这一行，并提供「以此句音频新建音色」。 */
  function onCueContextMenu(e: MouseEvent, index: number) {
    e.preventDefault();
    e.stopPropagation();
    play.selected = index;
    const cue = app.cues[index];
    const x = Math.min(e.clientX, window.innerWidth - 232);
    const y = Math.min(e.clientY, window.innerHeight - 132);
    contextMenu = { x, y, t: cue?.start ?? timeAt(e.clientX), index };
  }

  async function addCueHere() {
    const t = contextMenu?.t ?? play.time;
    contextMenu = null;
    await insertCueAt(t);
  }

  /** 右键「以此句音频新建音色…」：先给角色起名，再让后端精确切片。 */
  function openVoiceDialog(index: number) {
    contextMenu = null;
    const cue = app.cues[index];
    if (!cue) return;
    voiceDialog = {
      index,
      name: `角色 ${tts.custom.length + 1}`,
      refText: cue.text,
    };
  }

  // 浮层打开后把焦点放进名字输入框（比 autofocus 更可控，也不会触发 Svelte 的无障碍告警）
  $effect(() => {
    if (!voiceDialog) return;
    void nextTick().then(() => {
      voiceNameEl?.focus();
      voiceNameEl?.select();
    });
  });

  async function createVoiceFromCue() {
    if (!voiceDialog) return;
    const name = voiceDialog.name.trim();
    if (!name) {
      toast('先给这个音色起个名字', 'warn');
      return;
    }
    voiceBusy = true;
    try {
      await extractTtsVoiceFromCue(voiceDialog.index, name, voiceDialog.refText);
      voiceDialog = null;
    } catch (err) {
      toast(`提取音色失败：${(err as Error).message}`, 'error');
    } finally {
      voiceBusy = false;
    }
  }

  function onWavePointerUp(e: PointerEvent) {
    try {
      (e.currentTarget as HTMLElement).releasePointerCapture?.(e.pointerId);
    } catch {
      /* ignore */
    }
    const mode = dragMode;
    if (mode === 'playhead') {
      dragMode = 'none';
      endScrub();
      return;
    }
    if (mode === 'pan') {
      dragMode = 'none';
      waveCursor = 'crosshair';
      return;
    }
    if (mode === 'cue-move' || mode === 'cue-l' || mode === 'cue-r') {
      finishCueDrag();
      return;
    }
    if (mode === 'pending') {
      // 没超过阈值 = 单击跳转；绝不因为手抖变成框选
      dragMode = 'none';
      selection = null;
      seek(dragAnchor);
      return;
    }
    dragMode = 'none';
    if (mode === 'select') {
      if (!selection || !dragMoved || selection.end - selection.start < 0.08) {
        // 单击：跳转并清掉选区
        const t = selection ? selection.start : dragAnchor;
        selection = null;
        seek(t);
      } else {
        play.selected = cueIndexAt(selection.start);
      }
    }
  }

  function cueIndexAt(t: number) {
    for (let i = 0; i < app.cues.length; i += 1) {
      if (app.cues[i].start <= t && t <= app.cues[i].end) return i;
    }
    return play.selected;
  }

  function onWaveWheel(e: WheelEvent) {
    e.preventDefault();
    if (duration <= 0) return;
    const panning = e.shiftKey || (Math.abs(e.deltaX) > Math.abs(e.deltaY) && !e.ctrlKey);
    if (panning) {
      const delta = e.shiftKey ? e.deltaY : e.deltaX;
      setView(viewStart + (delta / Math.max(1, waveW)) * viewSpan, viewSpan);
      return;
    }
    // 触控板捏合在 macOS 上是 ctrlKey=true 的 wheel
    const factor = Math.exp(e.deltaY * (e.ctrlKey ? 0.012 : 0.0022));
    zoomAt(timeAt(e.clientX), factor);
  }

  function zoomAt(time: number, factor: number) {
    const nextSpan = Math.max(MIN_SPAN, Math.min(duration || viewSpan, viewSpan * factor));
    const ratio = (time - viewStart) / (viewSpan || 1);
    setView(time - ratio * nextSpan, nextSpan);
  }

  function zoomSliderInput(e: Event) {
    const v = Number((e.currentTarget as HTMLInputElement).value);
    // 0=全景，100=最深
    const minSpan = Math.max(MIN_SPAN, Math.min(1.2, (duration || 60) / 400));
    const span = (duration || 60) * Math.pow(minSpan / (duration || 60), v / 100);
    const center = play.time;
    setView(center - span / 2, span);
  }

  const sliderValue = $derived.by(() => {
    const d = duration || 60;
    const minSpan = Math.max(MIN_SPAN, Math.min(1.2, d / 400));
    const v = (Math.log(viewSpan / d) / Math.log(minSpan / d)) * 100;
    return Math.max(0, Math.min(100, v));
  });

  function fit() {
    setView(0, duration || viewSpan);
  }

  /** 聚焦统一用同一个 span：duration / 69。媒体还没就绪时才退回 2–12 秒。 */
  function focusSpan() {
    if (duration > 0) return Math.max(MIN_SPAN, duration / FOCUS_ZOOM);
    return Math.max(2, Math.min(12, viewSpan / 6 || 6));
  }

  /** 一键聚焦：把播放头附近放大到固定 69×（不随当前缩放叠加）。 */
  function focusPlayhead() {
    const span = focusSpan();
    setView(play.time - span / 2, span);
    follow = true;
  }

  function focusSelection() {
    if (!selection) return;
    const span = focusSpan();
    const center = (selection.start + selection.end) / 2;
    setView(center - span / 2, span);
  }

  function clearSelection() {
    selection = null;
  }

  function toggleFollow() {
    follow = !follow;
    // 开启的瞬间就把当前播放头带回画面，不必先播放一下
    if (follow) revealPlayhead(play.time);
  }

  function selectCue(i: number, doSeek = true) {
    play.selected = i;
    if (doSeek) seek(app.cues[i].start + 0.02);
  }

  // ---------------- 查找与替换（⌘F，只作用于原文） ----------------
  let findInput = $state<HTMLInputElement | null>(null);

  function escapeRe(text: string) {
    return text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  }

  /** 所有匹配：记录属于第几条、在文本里的起止，用于计数、跳转与高亮。 */
  const findMatches = $derived.by(() => {
    const query = findState.query;
    const hits: { cue: number; start: number; end: number }[] = [];
    if (!query) return hits;
    const flags = findState.caseSensitive ? 'g' : 'gi';
    const source = escapeRe(query);
    app.cues.forEach((cue, index) => {
      const re = new RegExp(source, flags);
      let found: RegExpExecArray | null;
      while ((found = re.exec(cue.text)) !== null) {
        hits.push({ cue: index, start: found.index, end: found.index + found[0].length });
        if (found[0].length === 0) re.lastIndex += 1;
      }
    });
    return hits;
  });

  const matchedCueSet = $derived(new Set(findMatches.map((hit) => hit.cue)));

  $effect(() => {
    const nonce = findState.focusNonce;
    void nonce;
    if (!findState.open) return;
    void nextTick().then(() => {
      findInput?.focus();
      findInput?.select();
    });
  });

  // 替换后匹配数会变少：把当前位置拉回合法范围
  $effect(() => {
    const total = findMatches.length;
    if (total === 0) {
      if (findState.pos !== 0) findState.pos = 0;
      return;
    }
    if (findState.pos >= total) findState.pos = 0;
  });

  function findGo(delta: number) {
    const total = findMatches.length;
    if (!total) {
      toast('没有找到匹配的文本', 'warn');
      return;
    }
    findState.pos = (findState.pos + delta + total) % total;
    jumpToCue(findMatches[findState.pos].cue);
  }

  async function findReplaceCurrent() {
    if (!findState.query) return;
    const total = findMatches.length;
    if (!total) {
      toast('没有可替换的匹配', 'warn');
      return;
    }
    const hit = findMatches[Math.min(findState.pos, total - 1)];
    const ok = await replaceInCue(
      hit.cue,
      findState.query,
      findState.replacement,
      findState.caseSensitive,
      hit.start,
    );
    if (ok) toast('已替换 1 处');
  }

  async function findReplaceAll() {
    if (!findState.query) return;
    const count = await replaceAllInCues(
      findState.query,
      findState.replacement,
      findState.caseSensitive,
    );
    if (count) {
      findState.pos = 0;
      toast(`已替换 ${count} 处（⌘Z 可一次撤回）`);
    } else {
      toast('没有找到匹配的文本', 'warn');
    }
  }

  /** 画面叠加层：一条 cue 里的硬换行拆成多行，空行丢掉。 */
  function captionTextLines(text: string): string[] {
    return String(text || '')
      .split('\n')
      .map((line) => line.trim())
      .filter(Boolean);
  }

  /**
   * 表格里一行只能放一行文字（虚拟列表固定行高），多行 cue 用「 / 」分隔显示，
   * 不再让 newline 被 nowrap 压成一个空格——两种语言粘在一起看起来像识别错误。
   * 完整原文仍在检查器文本框里按原样编辑。
   */
  function cueDisplayText(text: string): string {
    return captionTextLines(text).join(' / ');
  }

  /** 把一条字幕文本切成「命中 / 未命中」片段，交给表格渲染 <span>。 */
  function highlightSegments(text: string) {
    const query = findState.query;
    if (!findState.open || !query) return [{ text, hit: false }];
    const re = new RegExp(escapeRe(query), findState.caseSensitive ? 'g' : 'gi');
    const parts: { text: string; hit: boolean }[] = [];
    let last = 0;
    let found: RegExpExecArray | null;
    while ((found = re.exec(text)) !== null) {
      if (found.index > last) parts.push({ text: text.slice(last, found.index), hit: false });
      parts.push({ text: found[0], hit: true });
      last = found.index + found[0].length;
      if (found[0].length === 0) re.lastIndex += 1;
    }
    if (last < text.length) parts.push({ text: text.slice(last), hit: false });
    return parts.length ? parts : [{ text, hit: false }];
  }

  async function retranscribeRow(i: number) {
    if (busy) {
      toast('已有任务在跑，请先等它完成或中途打断', 'warn');
      return;
    }
    const cue = app.cues[i];
    if (!cue) return;
    play.selected = i;
    await transcribeRange({
      start: cue.start,
      end: cue.end,
      engine,
      label: `第 ${i + 1} 条`,
    });
  }

  async function transcribeSelection() {
    if (!selection) return;
    if (busy) {
      toast('已有任务在跑，请先等它完成或中途打断', 'warn');
      return;
    }
    await transcribeRange({
      start: selection.start,
      end: selection.end,
      engine,
      label: '选区',
      padStart: 0.1,
      padEnd: 0.2,
    });
  }

  function sendSelectionToTranscribe() {
    if (!selection) return;
    app.slice = {
      start: tcShort(selection.start),
      end: tcShort(selection.end),
      nonce: (app.slice?.nonce ?? 0) + 1,
    };
    app.view = 'transcribe';
    app.inspectorOpen = false;
    toast('已把选区时间填入转写页，可直接开始局部转写');
  }

  /** 用户正在输入框里打字时，不要自动改选中行，否则会把草稿换掉。 */
  function isTyping() {
    const el = document.activeElement as HTMLElement | null;
    if (!el) return false;
    if (el.tagName === 'TEXTAREA' || el.isContentEditable) return true;
    if (el.tagName === 'INPUT') {
      const type = (el as HTMLInputElement).type;
      // 缩放滑块也是 input：它失焦后不该继续拦住自动同步
      return !['range', 'checkbox', 'radio', 'button', 'submit', 'file'].includes(type);
    }
    return false;
  }

  let revealRaf = 0;

  function revealRow(i: number) {
    if (!rowsEl) return;
    const top = i * rowHeight;
    const viewTop = rowsEl.scrollTop;
    const viewBottom = viewTop + rowsEl.clientHeight;
    // 已经在可视区中间就不动，避免播放时每句都抖一下
    if (top >= viewTop + rowHeight * 2 && top + rowHeight <= viewBottom - rowHeight * 2) return;
    const above = Math.max(1, Math.floor((rowsEl.clientHeight * 0.4) / rowHeight));
    const target = Math.max(0, (i - above) * rowHeight);
    cancelAnimationFrame(revealRaf);
    // 播放中必须瞬时：平滑滚动会被后台窗口节流，让人以为表格没跟上。
    // 暂停时的跳转用 120ms 自己滚，手感比浏览器自带 smooth（约 300ms）干脆。
    if (play.playing || matchMedia('(prefers-reduced-motion: reduce)').matches) {
      rowsEl.scrollTop = target;
      return;
    }
    const from = rowsEl.scrollTop;
    const dist = target - from;
    if (Math.abs(dist) < 2) {
      rowsEl.scrollTop = target;
      return;
    }
    const t0 = performance.now();
    const step = (now: number) => {
      const k = Math.min(1, (now - t0) / 120);
      rowsEl!.scrollTop = from + dist * (1 - Math.pow(1 - k, 3));
      if (k < 1) revealRaf = requestAnimationFrame(step);
    };
    revealRaf = requestAnimationFrame(step);
  }

  /**
   * 播放头（点波形 / 拖播放头 / 播放中）进入某句字幕时：
   * 底部表格滚到那一行，右侧检查器切到那一条。
   * 双语同区间的两行以块内第一条为准，表格里整块都会高亮。
   */
  $effect(() => {
    const hit = cueIndex;
    if (hit < 0) return;
    const hitCue = app.cues[hit];
    if (!hitCue) return;
    const key = `${hitCue.start}:${hitCue.end}`;
    const selected = app.cues[play.selected];
    // 用户点的是同一块里的第 2/3 行（双语/三语）时保留他的选择，
    // 不要因为我们“块内第一条”的规则把选中行抢回去。
    const selectedInBlock = Boolean(
      selected && `${selected.start}:${selected.end}` === key,
    );
    let first = hit;
    while (first > 0 && `${app.cues[first - 1].start}:${app.cues[first - 1].end}` === key) {
      first -= 1;
    }
    if (first === lastRevealed) return;
    lastRevealed = first;
    if (isTyping()) return;
    if (!selectedInBlock && play.selected !== first) play.selected = first;
    revealRow(selectedInBlock ? play.selected : first);
  });

  /**
   * 程序化选中（转写选区完成 / 右键添加字幕 / 查找定位）必须强制滚到目标行。
   * cueIndex 的 effect 有 lastRevealed 去重：局部转写的新句经常落在同一下标，
   * 只改 play.selected 会被当成「已经在看这句」而不滚动——用户必须手动点一下
   * 新字幕才能让底部和右侧同步。selectNonce 每次自增，绕过去重。
   */
  let seenSelect = 0;
  $effect(() => {
    const nonce = play.selectNonce;
    if (nonce === seenSelect) return;
    seenSelect = nonce;
    const index = untrack(() => play.selected);
    if (index < 0 || index >= app.cues.length) return;
    lastRevealed = index;
    revealRow(index);
  });

  // 跟随是持久偏好：重开应用也记住用户的选择
  $effect(() => {
    localStorage.setItem('kikusub.follow', follow ? '1' : '0');
  });

  $effect(() => {
    if (!rowsEl) return;
    const ro = new ResizeObserver(() => {
      viewH = rowsEl?.clientHeight ?? 0;
    });
    ro.observe(rowsEl);
    viewH = rowsEl.clientHeight;
    return () => ro.disconnect();
  });

  // 菜单 / 快捷键
  export function api_play() {
    togglePlay();
  }
  export function api_step(delta: number) {
    const next = Math.max(0, Math.min(app.cues.length - 1, play.selected + delta));
    if (app.cues[next]) selectCue(next);
  }
  export function api_focus() {
    focusPlayhead();
  }
</script>

<div class="review">
  <div class="stage">
    <div class="player">
      {#if src}
        <video
          {@attach bindVideo}
          {src}
          preload="auto"
          playsinline
          onerror={(e) => {
            videoFailed = true;
            const el = e.currentTarget as HTMLVideoElement;
            logEvent('warn', 'video-error', `code=${el.error?.code ?? '?'} src=${el.currentSrc.slice(0, 160)}`);
          }}
          onloadedmetadata={(e) => {
            videoFailed = false;
            play.duration = e.currentTarget.duration || duration;
            const t = play.time;
            if (t > 0.2) e.currentTarget.currentTime = t;
          }}
        ></video>
      {:else}
        <div class="empty">还没有导入媒体</div>
      {/if}

      {#if captionLines.length}
        <div class="caption">
          {#each captionLines as line, i (i)}
            <span>{line}</span>
          {/each}
        </div>
      {/if}

      {#if videoFailed || (app.media?.needs_proxy && !app.media?.proxy_ready)}
        <div class="notice">
          <Icon name="warn" size={13} />
          <div class="notice-main">
            {#if app.media?.proxy_ready}
              Chromium 无法解码这个容器，代理已就绪但播放失败——请查看日志
            {:else if proxyBusy}
              正在后台压制 480p 监看代理，完成后会自动切换；可以先让它在后台跑
            {:else if app.media?.needs_proxy}
              {app.media.proxy_reason === 'bitrate'
                ? `源视频码率约 ${((app.media.video_bitrate ?? 0) / 1_000_000).toFixed(1)} Mbps，直接拖进度条可能很卡`
                : 'Chromium 可能无法解码这个视频的容器/编码'}
              <span class="notice-sub">压一份 480p 代理后，核对台拖动会稳定很多。</span>
            {:else}
              画面加载失败，可以尝试压制一份 480p 代理
            {/if}
          </div>
          {#if !app.media?.proxy_ready}
            <button
              class="btn tiny"
              onclick={() => startProxyJob()}
              disabled={proxyBusy}
            >
              {proxyBusy ? '压制中…' : '压制代理'}
            </button>
          {/if}
        </div>
      {/if}
    </div>

    <div class="transport">
      <button
        class="playbtn"
        onclick={togglePlay}
        title="播放 / 暂停（空格）"
        aria-label={play.playing ? '暂停' : '播放'}
      >
        <Icon name={play.playing ? 'pause' : 'play'} size={11} />
      </button>
      <span class="tp-time">{tc(play.time)}</span>
      <div
        class="tp-track"
        class:dragging={trackDrag}
        role="slider"
        tabindex="-1"
        aria-label="播放进度"
        aria-valuemin="0"
        aria-valuemax={duration}
        aria-valuenow={play.time}
        onpointerdown={onTrackPointerDown}
        onpointermove={onTrackPointerMove}
        onpointerup={onTrackPointerUp}
        onpointercancel={onTrackPointerUp}
        title="拖动逐帧预览画面"
      >
        <div class="tp-rail">
          <div class="tp-fill" style="width:{progressPct}%"></div>
        </div>
        <div class="tp-knob" style="left:{progressPct}%"></div>
      </div>
      <span class="tp-dur">{formatDuration(duration)}</span>
    </div>

    <!-- 第二行只放「看时间轴」的工具：缩放、全景、聚焦、跟随。
         AI 优化 / 导出在顶栏，压制代理 / 导入字幕在「⋯」里。 -->
    <div class="tl-tools">
      <div class="zoom-group">
        <button class="zbtn" onclick={() => zoomAt(play.time, 1.5)} title="缩小波形" aria-label="缩小波形">
          <Icon name="minus" size={12} />
        </button>
        <input
          class="zoom-slider"
          type="range"
          min="0"
          max="100"
          step="1"
          value={sliderValue}
          style="--zoom-pct:{sliderValue}%"
          oninput={zoomSliderInput}
          title="波形缩放"
          aria-label="波形缩放"
        />
        <button
          class="zbtn"
          onclick={() => zoomAt(play.time, 1 / 1.5)}
          title="放大波形（滚轮 / 捏合同效）"
          aria-label="放大波形"
        >
          <Icon name="plus" size={12} />
        </button>
        <span class="zoom-x">{zoomX >= 10 ? Math.round(zoomX) : zoomX.toFixed(1)}×</span>
      </div>
      <button class="mini-text" onclick={fit} title="显示全片">全景</button>
      <button class="mini-text" onclick={focusPlayhead} title="聚焦到播放头并放大">聚焦</button>
      <div class="grow"></div>
      <button
        class="follow-pill"
        class:on={follow}
        aria-pressed={follow}
        onclick={toggleFollow}
        title={follow
          ? '跟随中：播放与跳转时保持播放头在视窗内；缩放/平移不会关闭它'
          : '开启后，播放或跳转字幕时波形会跟随播放头'}
      >
        <i></i>{follow ? '跟随中' : '跟随'}
      </button>

      {#if selection}
        <div class="sel-bar">
          <span class="sel-info">
            <span class="sel-range">{tcShort(selection.start)} → {tcShort(selection.end)}</span>
            <b>{(selection.end - selection.start).toFixed(2)}s</b>
          </span>
          <button
            class="btn tiny"
            onclick={() => seekTo(selection!.start, { stopAt: selection!.end, play: true })}
            title="只播放选区"
          >
            <Icon name="play" size={10} />试听
          </button>
          <button class="btn tiny primary" onclick={transcribeSelection} disabled={rangeBusy}>
            {#if rangeBusy}
              <span class="spin"></span>转写中
            {:else}
              <Icon name="wave" size={10} />转写选区
            {/if}
          </button>
          <button class="btn tiny" onclick={sendSelectionToTranscribe} title="填到转写页的区间">
            填入转写
          </button>
          <button class="btn tiny" onclick={focusSelection} title="放大到选区">聚焦</button>
          <div class="tl-spacer"></div>
          <button class="btn tiny ghost" onclick={clearSelection} title="清除选区">
            <Icon name="close" size={10} />
          </button>
        </div>
      {/if}
    </div>
  </div>

  <div class="timeline">
    <div
      class="wave-wrap"
      bind:this={waveWrap}
      role="group"
      aria-label="波形时间轴与字幕轨道"
      style="height:{waveHeight}px;cursor:{waveCursor}"
      onpointerdown={onWavePointerDown}
      onpointermove={onWavePointerMove}
      onpointerup={onWavePointerUp}
      onpointercancel={onWavePointerUp}
      onpointerleave={(e) => {
        if (dragMode === 'none') {
          hoverKey = '';
          waveCursor = 'crosshair';
        }
      }}
      onwheel={onWaveWheel}
      oncontextmenu={onWaveContextMenu}
      ondblclick={(e) => {
        const t = timeAt(e.clientX);
        const span = Math.max(1.5, Math.min(10, viewSpan / 5 || 5));
        setView(t - span / 2, span);
      }}
      class:dragging={dragMode !== 'none'}
    >
      <canvas bind:this={canvas}></canvas>

      {#if cueTip}
        <div class="cue-tip" style="left:{cueTip.x}px">{cueTip.label}</div>
      {/if}

      {#if selection}
        <div
          class="sel"
          style="left:{xOf(selection.start)}px;width:{Math.max(1, xOf(selection.end) - xOf(selection.start))}px"
        >
          <div
            class="sel-handle l"
            onpointerdown={(e) => {
              e.stopPropagation();
              dragMode = 'resize-l';
            }}
          ></div>
          <div
            class="sel-handle r"
            onpointerdown={(e) => {
              e.stopPropagation();
              dragMode = 'resize-r';
            }}
          ></div>
        </div>
      {/if}

      {#if play.time < viewStart - 0.02 || play.time > viewStart + viewSpan + 0.02}
        <button
          class="ph-off"
          class:right={play.time > viewStart}
          onclick={() => focusPlayhead()}
          onpointerdown={(e) => e.stopPropagation()}
          title="播放头在视窗外"
        >
          <Icon name={play.time > viewStart ? 'chevron-right' : 'chevron-left'} size={11} />
        </button>
      {:else}
        <div class="ph" style="left:{Math.max(0, Math.min(waveW, xPlayhead()))}px">
          <div
            class="ph-flag"
            style="transform:translateX({Math.max(0, Math.min(waveW, xPlayhead())) < 26
              ? '0'
              : Math.max(0, Math.min(waveW, xPlayhead())) > waveW - 26
                ? '-100%'
                : '-50%'})"
          >
            {tcShort(play.time)}
          </div>
        </div>
      {/if}

      {#if loadingPeaks && !peaks.length}
        <div class="wave-loading">正在解码波形…</div>
      {/if}

      <div
        class="wave-resize"
        onpointerdown={onResizeDown}
        onpointermove={onResizeMove}
        onpointerup={onResizeUp}
        onpointercancel={onResizeUp}
        title="拖动调整波形高度"
      ></div>
    </div>
  </div>

  <div class="table-area">
    {#if findState.open}
      <div class="find-bar">
        <Icon name="search" size={12} />
        <input
          bind:this={findInput}
          class="find-input"
          bind:value={findState.query}
          oninput={() => (findState.pos = 0)}
          onkeydown={(e) => {
            if (e.key === 'Enter') {
              e.preventDefault();
              findGo(e.shiftKey ? -1 : 1);
            } else if (e.key === 'Escape') {
              e.preventDefault();
              closeFind();
            }
          }}
          placeholder="查找原文…"
          spellcheck="false"
        />
        <span class="find-count">
          {#if findState.query}
            {findMatches.length ? `${findState.pos + 1} / ${findMatches.length}` : '无结果'}
          {:else}
            0
          {/if}
        </span>
        <button class="btn icon ghost" onclick={() => findGo(-1)} title="上一个（⇧Enter）">
          <Icon name="chevron-left" size={11} />
        </button>
        <button class="btn icon ghost" onclick={() => findGo(1)} title="下一个（Enter）">
          <Icon name="chevron-right" size={11} />
        </button>
        <button
          class="find-case"
          class:on={findState.caseSensitive}
          onclick={() => (findState.caseSensitive = !findState.caseSensitive)}
          title="区分大小写"
        >
          Aa
        </button>
        <div class="find-sep"></div>
        <input
          class="find-input replace"
          bind:value={findState.replacement}
          onkeydown={(e) => {
            if (e.key === 'Enter') {
              e.preventDefault();
              void findReplaceCurrent();
            } else if (e.key === 'Escape') {
              e.preventDefault();
              closeFind();
            }
          }}
          placeholder="替换为（可留空）"
          spellcheck="false"
        />
        <button class="btn tiny" onclick={findReplaceCurrent}>替换</button>
        <button class="btn tiny primary" onclick={findReplaceAll}>全部替换</button>
        <div class="tl-spacer"></div>
        <button class="btn icon ghost" onclick={closeFind} title="关闭（Esc）">
          <Icon name="close" size={11} />
        </button>
      </div>
    {/if}
    <div class="thead">
      <div class="c-idx">#</div>
      <div class="c-t">开始</div>
      <div class="c-t">结束</div>
      <div class="c-dur">时长</div>
      <div class="c-text">字幕文本</div>
      <div class="c-acts"></div>
    </div>
    <div class="rows" bind:this={rowsEl} onscroll={(e) => (scrollTop = e.currentTarget.scrollTop)}>
      {#if !app.cues.length}
        <div class="empty-rows">
          还没有字幕。到「转写」跑一次，或导入 SRT。
        </div>
      {:else}
        <div style="height:{rowStart * rowHeight}px"></div>
        {#each visibleCues as cue, k (rowStart + k)}
          {@const i = rowStart + k}
          <div
            class="row"
            class:dual={app.track === 'both'}
            class:row-sel={play.selected === i}
            class:row-match={matchedCueSet.has(i)}
            class:playing={Boolean(activeKey) && `${cue.start}:${cue.end}` === activeKey}
            data-i={i}
            onclick={() => selectCue(i)}
            oncontextmenu={(e) => onCueContextMenu(e, i)}
            ondblclick={() => previewRange(cue.start, cue.end)}
            role="button"
            tabindex="-1"
            title="单击跳转 · 双击试听"
          >
            <div class="c-idx">{i + 1}</div>
            <div class="c-t">{tcShort(cue.start)}</div>
            <div class="c-t">{tcShort(cue.end)}</div>
            <div class="c-dur">{(cue.end - cue.start).toFixed(2)}s</div>
            <div class="c-text" class:dual={app.track === 'both'}>
              {#if app.track === 'target'}
                <span class="line" class:stale={isTranslationStale(i)}>
                  {translationAt(i) || '（这条还没有译文）'}
                </span>
              {:else if app.track === 'both'}
                <span class="line">
                  {#each highlightSegments(cueDisplayText(cue.text)) as part}
                    <span class:text-hit={part.hit}>{part.text}</span>
                  {/each}
                </span>
                <span class="line sub" class:stale={isTranslationStale(i)}>
                  {cueDisplayText(translationAt(i))}
                </span>
              {:else}
                <span class="line">
                  {#each highlightSegments(cueDisplayText(cue.text)) as part}
                    <span class:text-hit={part.hit}>{part.text}</span>
                  {/each}
                </span>
              {/if}
            </div>
            <div class="c-acts">
              <button
                class="row-btn"
                onclick={(e) => {
                  e.stopPropagation();
                  previewRange(cue.start, cue.end);
                }}
                title="试听此句"
              >
                <Icon name="play" size={10} />
              </button>
              <button
                class="row-btn"
                onclick={(e) => {
                  e.stopPropagation();
                  retranscribeRow(i);
                }}
                disabled={busy}
                title="单独重转此句（只替换这一条）"
              >
                <Icon name="wave" size={10} />
              </button>
            </div>
          </div>
        {/each}
        <div style="height:{Math.max(0, (app.cues.length - rowEnd) * rowHeight)}px"></div>
      {/if}
    </div>
  </div>

  {#if contextMenu}
    <button
      class="ctx-backdrop"
      use:portal
      aria-label="关闭菜单"
      onclick={() => (contextMenu = null)}
    ></button>
    <div
      class="ctx-menu"
      use:portal
      style="left:{contextMenu.x}px;top:{contextMenu.y}px"
      role="menu"
      aria-label="音轨菜单"
    >
      <div class="ctx-head">
        <span>{tcShort(contextMenu.t)}</span>
        <span class="ctx-hint">
          {contextMenu.index >= 0 ? `第 ${contextMenu.index + 1} 句` : '0.8 秒'}
        </span>
      </div>
      {#if contextMenu.index >= 0}
        <button
          class="ctx-item"
          onclick={() => openVoiceDialog(contextMenu.index)}
          role="menuitem"
        >
          <Icon name="speaker" size={12} />
          <span class="ctx-label">以此句音频新建音色…</span>
        </button>
        <button
          class="ctx-item"
          onclick={() => {
            const index = contextMenu.index;
            const c = app.cues[index];
            contextMenu = null;
            if (c) previewRange(c.start, c.end);
          }}
          role="menuitem"
        >
          <Icon name="play" size={12} />
          <span class="ctx-label">试听这句原声</span>
        </button>
        <div class="ctx-sep"></div>
      {/if}
      <button class="ctx-item" onclick={addCueHere} role="menuitem">
        <Icon name="plus" size={12} />
        <span class="ctx-label">添加字幕</span>
        <span class="ctx-hint">在光标处居中插入空字幕</span>
      </button>
    </div>
  {/if}

  {#if voiceDialog}
    {@const vc = app.cues[voiceDialog.index]}
    <button
      class="vd-backdrop"
      use:portal
      aria-label="关闭新建音色"
      onclick={() => {
        if (!voiceBusy) voiceDialog = null;
      }}
    ></button>
    <div class="vd" use:portal role="dialog" aria-modal="true" aria-label="新建克隆音色">
      <div class="vd-head">以此句音频新建音色</div>
      <div class="vd-sub">
        {#if vc}
          第 {voiceDialog.index + 1} 句 · {tcShort(vc.start)}–{tcShort(vc.end)}
          <span class="vd-dur">{(vc.end - vc.start).toFixed(1)}s</span>
        {/if}
      </div>
      <label class="vd-field">
        <span>音色名</span>
        <input
          bind:this={voiceNameEl}
          bind:value={voiceDialog.name}
          maxlength="40"
          placeholder="角色名，例如「女主角」"
          onkeydown={(e) => {
            if (e.key === 'Enter' && !voiceBusy) {
              e.preventDefault();
              void createVoiceFromCue();
            } else if (e.key === 'Escape') {
              e.preventDefault();
              voiceDialog = null;
            }
          }}
        />
      </label>
      <label class="vd-field">
        <span>参考文本（这句的日文，用于对齐声线）</span>
        <textarea bind:value={voiceDialog.refText} rows="2"></textarea>
      </label>
      <p class="vd-note">
        后端会用 ffmpeg 从当前视频精确切出这句的人声（前后各留 0.2 秒），
        3–10 秒最稳。{tts.engine && !tts.engine.installed
          ? '提取不需要模型；朗读前再到右侧点「下载克隆模型」。'
          : ''}
      </p>
      <div class="vd-actions">
        <button class="btn mini" onclick={() => (voiceDialog = null)} disabled={voiceBusy}>
          取消
        </button>
        <span class="vd-spacer"></span>
        <button class="btn mini primary" onclick={createVoiceFromCue} disabled={voiceBusy}>
          {voiceBusy ? '提取中…' : '提取并保存'}
        </button>
      </div>
    </div>
  {/if}
</div>

<style>
  .review {
    flex: 1;
    min-height: 0;
    display: flex;
    flex-direction: column;
  }

  .stage {
    padding: 18px 26px 0;
    display: flex;
    flex-direction: column;
    flex: 0 0 auto;
  }

  /* 画面固定在 640×360 的 16:9 框里（窗口更窄时等比缩），只留阴影，不要光晕 */
  .player {
    position: relative;
    width: min(640px, 100%);
    aspect-ratio: 16 / 9;
    margin: 0 auto;
    background: #000;
    border-radius: 10px;
    overflow: hidden;
    box-shadow: var(--shadow-video);
    display: flex;
    align-items: center;
    justify-content: center;
  }
  :global(html[data-theme='dark']) .player {
    box-shadow: var(--shadow-video), 0 0 0 1px rgba(236, 241, 250, 0.06);
  }
  video {
    width: 100%;
    height: 100%;
    object-fit: contain;
    background: #000;
    display: block;
  }
  .empty {
    color: rgba(255, 255, 255, 0.5);
    font-size: 12.5px;
  }

  .caption {
    position: absolute;
    left: 50%;
    bottom: 14px;
    transform: translateX(-50%);
    max-width: 84%;
    background: var(--caption-bg);
    backdrop-filter: blur(6px);
    color: #fff;
    /* 与表格、检查器同一条字幕字体角色：主题换的是「字幕」，不是「界面」 */
    font-family: var(--font-cue);
    font-size: 14px;
    line-height: 1.5;
    padding: 5px 13px;
    border-radius: 4px;
    text-align: center;
    text-shadow: 0 1px 2px rgba(0, 0, 0, 0.5);
    pointer-events: none;
    display: flex;
    flex-direction: column;
    gap: 1px;
  }
  .caption span {
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  .notice {
    position: absolute;
    top: 10px;
    left: 50%;
    transform: translateX(-50%);
    display: flex;
    align-items: center;
    gap: 6px;
    background: rgba(0, 0, 0, 0.55);
    backdrop-filter: blur(6px);
    color: #fff;
    font-size: 12px;
    padding: 5px 10px;
    border-radius: 8px;
    pointer-events: auto;
    max-width: min(620px, 92%);
  }

  .notice-main {
    display: flex;
    flex-direction: column;
    gap: 1px;
    min-width: 0;
  }

  .notice-sub {
    color: rgba(255, 255, 255, 0.68);
    font-size: 12px;
  }

  .notice .btn {
    margin-left: 4px;
    flex: 0 0 auto;
  }

  .transport {
    display: flex;
    align-items: center;
    gap: 9px;
    height: 32px;
    flex: 0 0 32px;
    margin-top: 10px;
  }
  .playbtn {
    width: 24px;
    height: 24px;
    flex: 0 0 24px;
    padding: 0;
    border-radius: 50%;
    border: 1px solid var(--line);
    background: var(--raise);
    color: var(--ink);
    display: grid;
    place-items: center;
    cursor: default;
    transition: border-color var(--dur) var(--ease), color var(--dur) var(--ease);
  }
  .playbtn:hover {
    border-color: var(--accent-line);
    color: var(--accent);
  }
  .tp-time {
    font-size: 12px;
    line-height: 16px;
    font-variant-numeric: tabular-nums;
    color: var(--text);
    font-family: var(--font-mono);
    letter-spacing: -0.01em;
    white-space: nowrap;
    min-width: 84px;
  }
  .tp-dur {
    font-size: 12px;
    line-height: 16px;
    color: var(--text-3);
    font-variant-numeric: tabular-nums;
    font-family: var(--font-mono);
    min-width: 38px;
    text-align: right;
  }
  .tp-track {
    flex: 1;
    height: 16px; /* 比视觉轨道高：4px 的细线根本捏不住 */
    position: relative;
    cursor: pointer;
    touch-action: none;
    display: flex;
    align-items: center;
  }
  .tp-track::before {
    /* 悬停时给一条淡淡的底，提示这里可拖动 */
    content: '';
    position: absolute;
    inset: -2px -4px;
    border-radius: 4px;
    background: transparent;
    transition: background 120ms var(--ease);
  }
  .tp-track:hover::before,
  .tp-track.dragging::before {
    background: var(--accent-soft);
  }
  .tp-rail {
    position: relative;
    width: 100%;
    height: 3px;
    border-radius: 2px;
    background: var(--line);
    transition: height var(--dur-fast) var(--ease);
  }
  .tp-track:hover .tp-rail,
  .tp-track.dragging .tp-rail {
    height: 5px;
  }
  .tp-fill {
    position: absolute;
    inset: 0 auto 0 0;
    border-radius: 2px;
    background: var(--accent);
  }
  .tp-knob {
    position: absolute;
    top: 50%;
    width: 9px;
    height: 9px;
    margin-left: -4.5px;
    border-radius: 50%;
    background: var(--raise);
    border: 1px solid var(--accent);
    box-shadow: 0 1px 2px rgba(27, 39, 64, 0.18);
    transform: translateY(-50%);
    transition: transform var(--dur-fast) var(--ease);
  }
  .tp-track:hover .tp-knob,
  .tp-track.dragging .tp-knob {
    transform: translateY(-50%) scale(1.18);
  }

  /* ---------------- 波形区 ---------------- */
  .timeline {
    padding: 6px 26px 0;
    flex: 0 0 auto;
  }

  /* 时间线第二行：只放时间轴工具 */
  .tl-tools {
    position: relative;
    display: flex;
    align-items: center;
    gap: 8px;
    height: 30px;
    flex: 0 0 30px;
    margin-top: 3px;
  }
  .zoom-group {
    display: flex;
    align-items: center;
    gap: 4px;
  }
  .zbtn {
    width: 20px;
    height: 20px;
    padding: 0;
    border: 0;
    border-radius: 4px;
    background: transparent;
    color: var(--ink-2);
    font-size: 14px;
    line-height: 1;
    display: grid;
    place-items: center;
    cursor: default;
    transition: background var(--dur-fast) var(--ease), color var(--dur-fast) var(--ease);
  }
  .zbtn:hover {
    background: var(--line-2);
    color: var(--ink);
  }
  .zoom-slider {
    appearance: none;
    width: 64px;
    height: 14px;
    background: transparent;
    cursor: default;
  }
  /* 和播放进度同一种滑块语言：已选段实心 accent + 实心拇指 */
  .zoom-slider::-webkit-slider-runnable-track {
    height: 4px;
    border-radius: 2px;
    background: linear-gradient(
      to right,
      var(--accent) var(--zoom-pct, 0%),
      var(--line) var(--zoom-pct, 0%)
    );
  }
  .zoom-slider::-webkit-slider-thumb {
    appearance: none;
    width: 10px;
    height: 10px;
    margin-top: -3px;
    border-radius: 50%;
    background: var(--accent);
    border: 0;
    box-shadow: 0 1px 2px rgba(27, 39, 64, 0.28);
  }
  .zoom-slider:hover::-webkit-slider-thumb {
    box-shadow: 0 0 0 3px var(--accent-soft);
  }
  .zoom-x {
    font-size: 12px;
    line-height: 16px;
    color: var(--text-3);
    font-variant-numeric: tabular-nums;
    min-width: 32px;
    text-align: right;
    font-family: var(--font-mono);
  }
  .mini-text {
    height: 24px;
    padding: 0 7px;
    border: 0;
    border-radius: 4px;
    background: transparent;
    color: var(--ink-2);
    font: inherit;
    font-size: 12px;
    cursor: default;
    transition: background var(--dur-fast) var(--ease), color var(--dur-fast) var(--ease);
  }
  .mini-text:hover {
    background: var(--line-2);
    color: var(--ink);
  }
  .grow {
    flex: 1;
  }
  .follow-pill {
    height: 24px;
    display: inline-flex;
    align-items: center;
    gap: 5px;
    padding: 0 8px;
    border: 0;
    border-radius: 4px;
    background: transparent;
    color: var(--ink-2);
    font: inherit;
    font-size: 12px;
    font-weight: 500;
    cursor: default;
  }
  .follow-pill i {
    width: 5px;
    height: 5px;
    border-radius: 50%;
    background: var(--ink-3);
  }
  .follow-pill.on {
    background: var(--accent-soft);
    color: var(--accent);
  }
  .follow-pill.on i {
    background: var(--accent);
  }
  .follow-pill:hover {
    background: var(--accent-soft);
    color: var(--accent);
  }
  .tl-spacer {
    flex: 1;
  }

  .sel-bar {
    animation: selIn 140ms var(--ease);
    display: flex;
    align-items: center;
    gap: 5px;
    /* 悬浮在工具行上层：出现/消失不能让波形上下跳，
       否则刚拖完选区的下一次点击会落到别的位置。 */
    position: absolute;
    inset: 0;
    z-index: 2;
    background: color-mix(in srgb, var(--accent) 8%, var(--paper));
    box-shadow: inset 0 0 0 1px var(--accent-ring);
    border-radius: 4px;
    padding: 0 6px 0 9px;
    height: 30px;
  }
  @keyframes selIn {
    from {
      opacity: 0;
    }
  }
  .sel-info {
    font-size: 12px;
    line-height: 16px;
    color: var(--text-2);
    font-variant-numeric: tabular-nums;
    font-family: ui-monospace, 'SF Mono', Menlo, monospace;
    white-space: nowrap;
  }
  .sel-info b {
    color: var(--accent);
    font-weight: 600;
    margin-left: 3px;
  }
  .tiny {
    height: 22px;
    font-size: 12px;
    padding: 0 7px;
    background: var(--raise);
  }
  .btn.primary.tiny {
    background: var(--btn-primary-bg);
    color: var(--on-accent);
  }
  .spin {
    width: 9px;
    height: 9px;
    border-radius: 50%;
    border: 1.5px solid currentColor;
    border-top-color: transparent;
    animation: spin 650ms linear infinite;
  }
  @keyframes spin {
    to {
      transform: rotate(360deg);
    }
  }

  .wave-wrap {
    position: relative;
    border-radius: 8px;
    background: transparent;
    overflow: hidden;
    touch-action: none;
    /* 具体光标由脚本按命中区域切换（刻度/播放头/字幕块/波形） */
    cursor: crosshair;
  }
  canvas {
    display: block;
    width: 100%;
    height: 100%;
  }

  .cue-tip {
    position: absolute;
    bottom: 26px;
    transform: translateX(-50%);
    background: var(--accent);
    color: var(--on-accent);
    font-size: 12px;
    line-height: 16px;
    height: 16px;
    padding: 0 6px;
    border-radius: 4px;
    white-space: nowrap;
    font-variant-numeric: tabular-nums;
    font-family: ui-monospace, 'SF Mono', Menlo, monospace;
    pointer-events: none;
    box-shadow: 0 2px 8px rgba(0, 0, 0, 0.22);
    z-index: 3;
  }

  .wave-resize {
    position: absolute;
    left: 0;
    right: 0;
    bottom: 0;
    height: 6px;
    cursor: ns-resize;
    touch-action: none;
  }
  .wave-resize::after {
    content: '';
    position: absolute;
    left: 50%;
    bottom: 2px;
    width: 34px;
    height: 2px;
    margin-left: -17px;
    border-radius: 1px;
    background: var(--separator);
  }
  .wave-resize:hover {
    background: var(--accent-soft);
  }
  .wave-resize:hover::after {
    background: var(--accent);
  }

  .sel {
    position: absolute;
    top: 17px;
    bottom: 0;
    background: color-mix(in srgb, var(--accent) 8%, transparent);
    border-left: 1px solid var(--accent);
    border-right: 1px solid var(--accent);
    pointer-events: none;
  }
  .sel-handle {
    position: absolute;
    top: 0;
    /* 留出底部字幕轨道：选区的把手不能挡住字幕块的左右端拖动 */
    bottom: 23px;
    width: 8px;
    pointer-events: auto;
    cursor: ew-resize;
  }
  .sel-handle.l {
    left: -4px;
  }
  .sel-handle.r {
    right: -4px;
  }

  .ph {
    position: absolute;
    top: 0;
    bottom: 0;
    width: 1.5px;
    background: var(--accent);
    box-shadow: 0 0 0 0.5px rgba(255, 255, 255, 0.55);
    pointer-events: none;
    will-change: left;
  }
  .ph-off {
    position: absolute;
    top: 21px;
    width: 15px;
    height: 15px;
    padding: 0;
    border: 0;
    border-radius: 4px;
    background: var(--accent-soft);
    color: var(--accent);
    display: grid;
    place-items: center;
    left: 3px;
    z-index: 2;
  }
  .ph-off.right {
    left: auto;
    right: 3px;
  }
  .ph-off:hover {
    background: var(--accent);
    color: var(--on-accent);
  }
  .ph-flag {
    position: absolute;
    top: 2px;
    left: 50%;
    transform: translateX(-50%);
    background: var(--accent);
    color: var(--on-accent);
    font-size: 12px;
    line-height: 13px;
    padding: 0 4px;
    height: 13px;
    border-radius: 3px;
    font-variant-numeric: tabular-nums;
    font-family: ui-monospace, 'SF Mono', Menlo, monospace;
    white-space: nowrap;
  }

  .wave-loading {
    position: absolute;
    inset: 0;
    display: grid;
    place-items: center;
    font-size: 12px;
    color: var(--text-3);
    background: color-mix(in srgb, var(--bg-inspector) 74%, transparent);
  }

  /* ---------------- 表格 ---------------- */
  .table-area {
    flex: 1;
    min-height: 0;
    display: flex;
    flex-direction: column;
    margin: 6px 26px 0;
    border-top: 1px solid var(--line);
  }
  .thead {
    display: grid;
    grid-template-columns: 34px 100px 100px 54px minmax(0, 1fr) 44px;
    column-gap: 6px;
    align-items: center;
    height: 30px;
    padding: 0 10px;
    font-size: 12px;
    line-height: 16px;
    font-weight: 500;
    color: var(--text-2);
    box-shadow: inset 0 -1px 0 var(--line-2);
    flex: 0 0 30px;
  }
  .rows {
    flex: 1;
    min-height: 0;
    overflow-y: auto;
    overflow-x: hidden;
    padding-bottom: 0;
    mask-image: linear-gradient(to bottom, #000 calc(100% - 18px), transparent 100%);
    -webkit-mask-image: linear-gradient(to bottom, #000 calc(100% - 18px), transparent 100%);
  }

  .row {
    display: grid;
    grid-template-columns: 34px 100px 100px 54px minmax(0, 1fr) 44px;
    column-gap: 6px;
    align-items: center;
    height: 30px;
    padding: 0 10px;
    font-size: 15px;
    line-height: 20px; /* 15/20：行内上下各 5px，基线稳定，不出现 20.25 的分数行高 */
    /* 发丝线用 inset shadow：border 会吃掉 1px，行内 20px 文字就变成上下 4.5/5.5 */
    box-shadow: inset 0 -1px 0 var(--line-2);
    position: relative;
    transition: background 120ms var(--ease);
  }
  .row:hover {
    background: var(--line-2);
  }
  .row.row-match {
    background: var(--hit-row);
  }
  .row.row-sel {
    background: var(--accent-soft);
  }
  .row.playing::before,
  .row.row-sel::before {
    content: '';
    position: absolute;
    left: 0;
    top: 0;
    bottom: 0;
    width: 2px;
    background: var(--accent);
  }
  .row.playing .c-idx {
    color: var(--accent);
    font-weight: 600;
  }
  .row.playing .c-text {
    font-weight: 500;
  }

  @media (max-width: 1400px) {
    /* 1360 默认窗口：给字幕文本多 16px，当前句不要被时间码/图标挤掉尾巴 */
    .thead,
    .row {
      grid-template-columns: 34px 94px 94px 54px minmax(0, 1fr) 42px;
    }
  }

  @media (max-width: 1220px) {
    /* 窄窗口里选区工具条会挤出右边界：只留时长，把时间范围让给按钮 */
    .sel-range {
      display: none;
    }
    .thead,
    .row {
      grid-template-columns: 30px 88px 88px 48px minmax(0, 1fr) 38px;
      column-gap: 4px;
    }
    .thead {
      padding: 0 8px;
    }
    .row {
      padding: 0 8px;
    }
  }

  .c-idx {
    font-size: 12px;
    line-height: 16px;
    color: var(--text-3);
    font-variant-numeric: tabular-nums;
    font-family: var(--font-mono);
  }
  .c-t {
    font-family: var(--font-mono);
    font-size: 12px;
    line-height: 16px;
    color: var(--ink-2);
    font-variant-numeric: tabular-nums;
    letter-spacing: -0.02em;
  }
  .c-dur {
    font-family: var(--font-mono);
    font-size: 12px;
    line-height: 16px;
    color: var(--text-3);
    font-variant-numeric: tabular-nums;
  }
  .c-text {
    min-width: 0;
    font-family: var(--font-cue);
    font-size: 15px;
    line-height: 20px;
    color: var(--ink);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    padding-right: 6px;
  }
  /* 双语：固定两行，行高与虚拟列表的 60px 对齐 */
  .row.dual {
    height: 60px;
  }
  .c-text.dual {
    display: flex;
    flex-direction: column;
    justify-content: center;
    /* 20 + 16 + 2 = 38：(60 - 38) / 2 = 11，双语的上下留白落在整数像素上 */
    gap: 2px;
    line-height: 20px;
  }
  .c-text .line {
    display: block;
    min-width: 0;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .c-text .line.sub {
    /* 译文轨始终跟界面字体：12px 的明朝在浅底上太细，读起来像印刷品缩印 */
    font-family: var(--font-sans);
    font-size: 12px;
    line-height: 16px;
    color: var(--text-2);
  }
  .c-text .line.stale {
    color: var(--warn);
  }
  .c-text .text-hit {
    background: var(--hit);
    border-radius: 2px;
    color: inherit;
  }
  .c-acts {
    display: flex;
    justify-content: flex-end;
    gap: 4px;
    opacity: 0;
    transition: opacity 120ms var(--ease);
  }
  .row:hover .c-acts,
  .row.row-sel .c-acts {
    opacity: 1;
  }
  .row-btn {
    appearance: none;
    border: 0;
    background: transparent;
    color: var(--text-3);
    width: 19px;
    height: 19px;
    border-radius: 4px;
    display: grid;
    place-items: center;
    position: relative;
  }
  /* 视觉 19px，热区 24px：伪元素只扩大命中范围，不改变行高与列宽 */
  .row-btn::after {
    content: '';
    position: absolute;
    inset: -2.5px -2px;
  }
  .row-btn:hover {
    background: var(--fill-strong);
    color: var(--accent);
  }
  .row-btn:disabled {
    opacity: 0.35;
  }

  .empty-rows {
    padding: 22px 14px;
    color: var(--text-3);
    font-size: 12.5px;
  }

  /* ---------------- 查找与替换 ---------------- */
  .find-bar {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 4px;
    padding: 5px 14px;
    flex: 0 0 auto;
    border-bottom: 1px solid var(--separator-soft);
    background: color-mix(in srgb, var(--accent) 5%, var(--bg-content));
  }
  .find-input {
    height: 24px;
    width: 190px;
    min-width: 96px;
    flex: 0 1 190px;
    border-radius: 4px;
    border: 1px solid var(--separator);
    background: var(--bg-content);
    color: var(--text);
    font: inherit;
    font-size: 12px;
    padding: 0 7px;
  }
  .find-input:focus {
    outline: none;
    border-color: var(--accent);
    box-shadow: 0 0 0 2px var(--accent-soft);
  }
  .find-input.replace {
    width: 160px;
    flex-basis: 160px;
  }
  .find-count {
    min-width: 58px;
    text-align: right;
    font-size: 12px;
    color: var(--text-3);
    font-variant-numeric: tabular-nums;
    font-family: ui-monospace, 'SF Mono', Menlo, monospace;
    white-space: nowrap;
  }
  .find-case {
    appearance: none;
    border: 1px solid transparent;
    background: transparent;
    color: var(--text-3);
    font: inherit;
    font-size: 12px;
    font-weight: 600;
    height: 22px;
    padding: 0 5px;
    border-radius: 4px;
    cursor: pointer;
  }
  .find-case:hover {
    background: var(--fill-strong);
  }
  .find-case.on {
    background: var(--accent-soft);
    border-color: var(--accent-ring);
    color: var(--accent);
  }
  .find-sep {
    width: 1px;
    height: 16px;
    background: var(--separator);
    margin: 0 3px;
    flex: 0 0 1px;
  }

  /* ---------------- 音轨右键菜单 ---------------- */
  .ctx-backdrop {
    position: fixed;
    inset: 0;
    z-index: 70;
    border: 0;
    padding: 0;
    background: transparent;
    cursor: default;
  }
  .ctx-sep {
    height: 1px;
    margin: 3px 4px;
    background: var(--separator-soft);
  }
  .ctx-menu {
    position: fixed;
    z-index: 71;
    width: 216px;
    padding: 4px;
    border-radius: 4px;
    background: var(--bg-content);
    border: 1px solid var(--separator);
    box-shadow: var(--shadow-pop);
  }
  .ctx-head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 8px;
    padding: 4px 7px 5px;
    margin-bottom: 3px;
    border-bottom: 1px solid var(--separator-soft);
    font-size: 12px;
    color: var(--text-3);
    font-variant-numeric: tabular-nums;
    font-family: ui-monospace, 'SF Mono', Menlo, monospace;
  }
  .ctx-item {
    appearance: none;
    border: 0;
    background: transparent;
    color: var(--text);
    font: inherit;
    width: 100%;
    display: flex;
    align-items: center;
    gap: 7px;
    padding: 6px 7px;
    border-radius: 4px;
    cursor: pointer;
    text-align: left;
  }
  .ctx-item:hover {
    background: var(--accent-soft);
    color: var(--accent);
  }
  .ctx-label {
    flex: 1;
    font-size: 12px;
  }
  .ctx-hint {
    font-size: 12px;
    color: var(--text-3);
    white-space: nowrap;
  }

  /* ---------------- 以此句音频新建音色 ---------------- */
  .vd-backdrop {
    position: fixed;
    inset: 0;
    z-index: 80;
    border: 0;
    padding: 0;
    margin: 0;
    background: rgba(0, 0, 0, 0.28);
    backdrop-filter: blur(1px);
    cursor: default;
  }
  .vd {
    position: fixed;
    z-index: 81;
    left: 50%;
    top: 50%;
    transform: translate(-50%, -50%);
    width: min(340px, calc(100vw - 48px));
    padding: 14px 16px 12px;
    border-radius: 8px;
    background: var(--bg-content);
    border: 1px solid var(--separator);
    box-shadow: var(--shadow-pop);
    display: flex;
    flex-direction: column;
    gap: 10px;
  }
  .vd-head {
    font-size: 13px;
    font-weight: 600;
    color: var(--text);
  }
  .vd-sub {
    display: flex;
    align-items: center;
    gap: 6px;
    margin-top: -5px;
    font-size: 11px;
    color: var(--text-3);
    font-variant-numeric: tabular-nums;
  }
  .vd-dur {
    padding: 0 5px;
    border-radius: 3px;
    background: var(--separator-soft);
  }
  .vd-field {
    display: flex;
    flex-direction: column;
    gap: 4px;
    font-size: 11px;
    color: var(--text-3);
  }
  .vd-field input,
  .vd-field textarea {
    width: 100%;
    box-sizing: border-box;
    border: 1px solid var(--line);
    border-radius: 4px;
    background: var(--bg-inset, var(--raise));
    color: var(--text);
    font: inherit;
    font-size: 12px;
    padding: 5px 7px;
    resize: vertical;
  }
  .vd-field input:focus,
  .vd-field textarea:focus {
    outline: none;
    border-color: var(--accent-line);
    box-shadow: 0 0 0 2px var(--accent-soft);
  }
  .vd-note {
    margin: 0;
    font-size: 11px;
    line-height: 16px;
    color: var(--text-3);
  }
  .vd-actions {
    display: flex;
    align-items: center;
    gap: 8px;
    padding-top: 2px;
  }
  .vd-spacer {
    flex: 1;
  }

  /* ============================================================
     紧凑模式（≤900px；200% 页面缩放后是 680×419 / 540×340）。
     三块保持原顺序、整屏纵向滚动：播放器按可用宽度等比缩，
     时间线跟其后，表格保底 200px（虚拟列表自己滚），
     不再出现「内容区 96px、视频 44×25」的塌陷。
     ============================================================ */
  @media (max-width: 900px) {
    .review {
      overflow-x: hidden;
      overflow-y: auto;
    }
    .stage {
      padding: 12px 16px 0;
    }
    /* 200% 下保持 592×333 会把播放条推出首屏：按「视频 + 播放行 + 工具行」
       正好占满一屏可用高度来定宽，波形与表格往下滚一屏即可。 */
    .player {
      width: min(640px, 100%, calc((100vh - 170px) * 16 / 9));
    }
    .timeline {
      padding: 6px 16px 0;
    }
    .table-area {
      flex: 0 0 auto;
      height: clamp(200px, 52vh, 300px);
      margin: 6px 16px 16px;
    }
    .transport,
    .tl-tools {
      gap: 7px;
    }
    /* 查找栏在 680/540 宽下要留在一行：隐藏「Aa」与分隔线，输入框可收缩。
       折行会把表格再吃掉一行高度，关闭按钮也会单独掉到第二行。 */
    .find-bar {
      padding: 5px 6px;
      gap: 3px;
    }
    .find-input {
      width: auto;
      flex: 1 1 110px;
      min-width: 80px;
    }
    .find-input.replace {
      width: auto;
      flex: 1 1 96px;
      min-width: 72px;
    }
    .find-count {
      min-width: 42px;
    }
    .find-case,
    .find-sep {
      display: none;
    }
  }

  @media (max-width: 700px) {
    /* 540 / 680 宽：只留「# / 开始 / 字幕文本 / 行内动作」四列 */
    .thead,
    .row {
      grid-template-columns: 30px 78px minmax(0, 1fr) 36px;
      column-gap: 4px;
      padding: 0 8px;
    }
    .thead > :nth-child(3),
    .thead > :nth-child(4),
    .row > :nth-child(3),
    .row > :nth-child(4) {
      display: none;
    }
    .find-input,
    .find-input.replace {
      width: 120px;
      flex-basis: 120px;
    }
  }
</style>
