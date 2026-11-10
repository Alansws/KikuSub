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
  import { untrack } from 'svelte';
  import Icon from '../components/Icon.svelte';
  import { api, mediaUrl } from '../lib/api';
  import { logEvent } from '../lib/api';
  import {
    app,
    applyCueTimes,
    focusRange,
    openSubtitle,
    play,
    previewRange,
    seekTo,
    toast,
    transcribeRange,
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
  // 波形高度：默认比旧版高一半，可拖动底部把手调整；记住用户选择。
  const savedHeight = Number(localStorage.getItem('kikusub.waveHeight') || 0);
  let waveHeight = $state(Math.max(110, Math.min(300, savedHeight || 148)));

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

  // 视频进度条拖动
  let trackDrag = $state(false);
  // 最近一次自动滚到/选中过的字幕行，避免同一句反复滚动
  let lastRevealed = -1;

  // 虚拟列表：行高固定 26px，只渲染可视区 ± OVERSCAN 行。
  const ROW_H = 26;
  const OVERSCAN = 6;

  // 有代理就走代理：Chromium 解不开 MKV / HEVC，原片喂进去只会黑屏。
  const src = $derived(
    app.media ? mediaUrl(app.media.id, Boolean(app.media.proxy_ready)) : '',
  );

  // 当前播放到的字幕。双语 SRT 的两行区间完全相同，必须一起显示。
  const captionLines = $derived.by(() => {
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
    for (let k = i + 1; k < cues.length; k += 1) {
      if (`${cues[k].start}:${cues[k].end}` !== key) break;
      if (cues[k].text.trim()) lines.push(cues[k].text);
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

  const rowStart = $derived(Math.max(0, Math.floor(scrollTop / ROW_H) - OVERSCAN));
  const rowEnd = $derived(
    Math.min(
      app.cues.length,
      rowStart + Math.ceil((viewH || 400) / ROW_H) + OVERSCAN * 2,
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
    canvas.width = Math.round(w * dpr);
    canvas.height = Math.round(h * dpr);
    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);

    const css = getComputedStyle(document.documentElement);
    const token = (name: string, fallback: string) =>
      css.getPropertyValue(name).trim() || fallback;
    const sep = token('--separator-soft', 'rgba(0,0,0,.06)');
    const sepStrong = token('--separator', 'rgba(0,0,0,.1)');
    const waveColor = token('--wave', '#7b8a99');
    const accent = token('--accent', '#007aff');
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
    ctx.font = '9.5px -apple-system, ui-monospace, Menlo, monospace';
    ctx.textBaseline = 'top';
    const first = Math.ceil(viewStart / step) * step;
    for (let t = first; t <= viewStart + viewSpan; t += step) {
      const x = Math.round(xOf(t)) + 0.5;
      const major = Math.abs(t / (step * 5) - Math.round(t / (step * 5))) < 1e-6;
      ctx.fillStyle = major ? sepStrong : sep;
      ctx.fillRect(x, 0, 1, major ? 7 : 4);
      if (major || step >= 5) {
        ctx.fillStyle = text3;
        ctx.fillText(rulerLabel(t, step), x + 3, 1);
      }
    }
    ctx.fillStyle = sep;
    ctx.fillRect(0, RULER_H - 0.5, w, 1);

    // 波形：逐像素取该像素覆盖的所有采样点的最大值。
    // 之前是「一个采样点画一根柱子」，放大后柱子间距会被拉开；逐像素合并后
    // 无论缩放到多深都是一条连续的包络，不会出现可数的柱形。
    const n = peaks.length;
    if (!n) {
      ctx.fillStyle = sepStrong;
      ctx.fillRect(0, Math.round(mid), w, 1);
    } else {
      ctx.fillStyle = waveColor;
      ctx.globalAlpha = 0.88;
      const span = peaksSpan || 1;
      const perBin = span / n;
      for (let x = 0; x < w; x += 1) {
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
    }

    // 选中行的区间高亮（不是选区，只是当前条目）
    if (play.selected >= 0 && app.cues[play.selected]) {
      const sel = app.cues[play.selected];
      const x0 = Math.max(0, xOf(sel.start));
      const x1 = Math.min(w, xOf(sel.end));
      if (x1 > x0) {
        ctx.fillStyle = accent;
        ctx.globalAlpha = 0.07;
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
    const pad = Math.min(2.5, Math.max(0.5, (req.end - req.start) * 0.6));
    const span = Math.max(2, req.end - req.start + pad * 2);
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

  function t0() {
    return viewStart + viewSpan;
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

  /** 一键聚焦：把播放头附近放大到便于核对的尺度。 */
  function focusPlayhead() {
    const span = Math.max(2, Math.min(12, viewSpan / 6 || 6));
    setView(play.time - span / 2, span);
    follow = true;
  }

  function focusSelection() {
    if (!selection) return;
    const span = Math.max(1.5, (selection.end - selection.start) * 1.6);
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

  function revealRow(i: number) {
    if (!rowsEl) return;
    const top = i * ROW_H;
    const viewTop = rowsEl.scrollTop;
    const viewBottom = viewTop + rowsEl.clientHeight;
    // 已经在可视区中间就不动，避免播放时每句都抖一下
    if (top >= viewTop + ROW_H * 2 && top + ROW_H <= viewBottom - ROW_H * 2) return;
    // 用即时滚动而不是 smooth：跳转要「同步」，动画在后台窗口会被节流，
    // 让人以为表格没跟上。落点按整行对齐，避免顶部永远卡着半行。
    const above = Math.max(1, Math.floor((rowsEl.clientHeight * 0.4) / ROW_H));
    rowsEl.scrollTop = Math.max(0, (i - above) * ROW_H);
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

  /** 从设置里的导出文件夹挑一个字幕导入核对台（换基线，不动当前媒体）。 */
  async function importSubtitleFromExport() {
    const dir = app.config?.export_dir || app.config?.output_dir || '';
    if (!dir) {
      toast('还没有可用的导出文件夹，请先到设置里选择', 'warn');
      return;
    }
    const file = await window.kikusub.pickSubtitle(dir);
    if (file) await openSubtitle(file);
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
          {#if app.media?.proxy_ready}
            Chromium 无法解码这个容器，代理已就绪但播放失败——请查看日志
          {:else}
            正在后台压制 480p 监看代理，完成后会自动切换
          {/if}
        </div>
      {/if}
    </div>

    <div class="transport">
      <button class="btn icon" onclick={togglePlay} title="播放 / 暂停（空格）">
        <Icon name={play.playing ? 'pause' : 'play'} size={13} />
      </button>
      <div class="tp-time">
        <b>{tc(play.time)}</b>
      </div>
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
      <div class="tp-dur">{formatDuration(duration)}</div>
    </div>
  </div>

  <div class="timeline">
    <div class="tl-head">
      <div class="tl-bar">
      <div class="zoom-group">
        <button
          class="btn icon ghost"
          onclick={() => zoomAt(play.time, 1.5)}
          title="缩小波形"
        >
          <Icon name="minus" size={12} />
        </button>
        <input
          class="zoom-slider"
          type="range"
          min="0"
          max="100"
          step="1"
          value={sliderValue}
          oninput={zoomSliderInput}
          title="波形缩放"
        />
        <button
          class="btn icon ghost"
          onclick={() => zoomAt(play.time, 1 / 1.5)}
          title="放大波形（滚轮 / 捏合同效）"
        >
          <Icon name="plus" size={12} />
        </button>
        <span class="zoom-x">{zoomX >= 10 ? Math.round(zoomX) : zoomX.toFixed(1)}×</span>
        <button class="btn ghost" onclick={fit} title="显示全片">全景</button>
        <button class="btn ghost" onclick={focusPlayhead} title="聚焦到播放头并放大">
          <Icon name="search" size={11} />聚焦
        </button>
        <button
          class="btn ghost"
          onclick={importSubtitleFromExport}
          disabled={busy}
          title="从导出文件夹选择上次转写的字幕，导入核对台作为基线"
        >
          <Icon name="export" size={11} />导入字幕
        </button>
        <button
          class="btn ghost"
          class:on={follow}
          aria-pressed={follow}
          onclick={toggleFollow}
          title={follow ? '跟随中：播放与跳转时保持播放头在视窗内；缩放/平移不会关闭它' : '开启后，播放或跳转字幕时波形会跟随播放头'}
        >
          {follow ? '跟随中' : '跟随'}
        </button>
      </div>

      <div class="tl-spacer"></div>

      {#if !selection}
        <span class="tl-hint">
          单击跳转 · 拖动框选 · 顶部刻度 / 播放头拖动逐帧擦洗 · 底部字幕块可拖动改时间
        </span>
      {/if}
    </div>

    {#if selection}
      <div class="sel-bar">
        <span class="sel-info">
          {tcShort(selection.start)} → {tcShort(selection.end)}
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

    <div
      class="wave-wrap"
      bind:this={waveWrap}
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
          还没有字幕。到「转写」跑一次，或导入 SRT；质检定位也会在这里高亮。
        </div>
      {:else}
        <div style="height:{rowStart * ROW_H}px"></div>
        {#each visibleCues as cue, k (rowStart + k)}
          {@const i = rowStart + k}
          <div
            class="row"
            class:row-sel={play.selected === i}
            class:playing={Boolean(activeKey) && `${cue.start}:${cue.end}` === activeKey}
            data-i={i}
            onclick={() => selectCue(i)}
            ondblclick={() => previewRange(cue.start, cue.end)}
            role="button"
            tabindex="-1"
            title="单击跳转 · 双击试听"
          >
            <div class="c-idx">{i + 1}</div>
            <div class="c-t">{tcShort(cue.start)}</div>
            <div class="c-t">{tcShort(cue.end)}</div>
            <div class="c-dur">{(cue.end - cue.start).toFixed(2)}s</div>
            <div class="c-text">{cue.text}</div>
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
        <div style="height:{Math.max(0, (app.cues.length - rowEnd) * ROW_H)}px"></div>
      {/if}
    </div>
  </div>
</div>

<style>
  .review {
    flex: 1;
    min-height: 0;
    display: flex;
    flex-direction: column;
  }

  .stage {
    padding: 12px 14px 0;
    display: flex;
    flex-direction: column;
    gap: 8px;
    flex: 0 0 auto;
  }

  .player {
    position: relative;
    width: 100%;
    height: min(42vh, 380px);
    background: #000;
    border-radius: 10px;
    overflow: hidden;
    box-shadow: 0 1px 3px rgba(0, 0, 0, 0.18), 0 0 0 0.5px rgba(0, 0, 0, 0.1);
    display: flex;
    align-items: center;
    justify-content: center;
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
    font-size: 14px;
    line-height: 1.5;
    padding: 5px 13px;
    border-radius: 6px;
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
    font-size: 11.5px;
    padding: 5px 10px;
    border-radius: 8px;
    pointer-events: none;
  }

  .transport {
    display: flex;
    align-items: center;
    gap: 9px;
    padding: 0 2px;
  }
  .tp-time {
    font-size: 11.5px;
    font-variant-numeric: tabular-nums;
    color: var(--text-3);
    font-family: ui-monospace, 'SF Mono', Menlo, monospace;
    letter-spacing: -0.01em;
    white-space: nowrap;
  }
  .tp-time b {
    color: var(--text);
    font-weight: 500;
  }
  .tp-dur {
    font-size: 11px;
    color: var(--text-3);
    font-variant-numeric: tabular-nums;
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
    border-radius: 6px;
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
    height: 4px;
    border-radius: 2px;
    background: var(--fill-strong);
  }
  .tp-track:hover .tp-rail,
  .tp-track.dragging .tp-rail {
    height: 6px;
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
    width: 11px;
    height: 11px;
    margin-left: -5.5px;
    border-radius: 50%;
    background: #fff;
    box-shadow: 0 1px 3px rgba(0, 0, 0, 0.35), 0 0 0 0.5px rgba(0, 0, 0, 0.12);
    transform: translateY(-50%);
    transition: transform 100ms var(--ease);
  }
  .tp-track:hover .tp-knob,
  .tp-track.dragging .tp-knob {
    transform: translateY(-50%) scale(1.18);
  }

  /* ---------------- 波形区 ---------------- */
  .timeline {
    padding: 6px 14px 0;
    display: flex;
    flex-direction: column;
    gap: 5px;
    flex: 0 0 auto;
  }
  .tl-head {
    position: relative;
    min-height: 26px;
  }
  .tl-bar {
    display: flex;
    align-items: center;
    gap: 8px;
    min-height: 26px;
  }
  .zoom-group {
    display: flex;
    align-items: center;
    gap: 3px;
  }
  .zoom-slider {
    width: 118px;
    accent-color: var(--accent);
    height: 14px;
  }
  .zoom-x {
    font-size: 10.5px;
    color: var(--text-3);
    font-variant-numeric: tabular-nums;
    min-width: 34px;
    text-align: right;
    font-family: ui-monospace, 'SF Mono', Menlo, monospace;
  }
  .tl-spacer {
    flex: 1;
  }
  .tl-hint {
    font-size: 10.5px;
    color: var(--text-3);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    min-width: 0;
  }

  .sel-bar {
    display: flex;
    align-items: center;
    gap: 5px;
    /* 悬浮在工具栏上层：出现/消失不能让波形上下跳，
       否则刚拖完选区的下一次点击会落到别的位置。 */
    position: absolute;
    inset: 0;
    z-index: 2;
    background: color-mix(in srgb, var(--accent) 9%, var(--bg-content));
    box-shadow: inset 0 0 0 1px var(--accent-ring);
    border-radius: 7px;
    padding: 2px 5px 2px 9px;
    height: 26px;
  }
  .sel-info {
    font-size: 10.5px;
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
    height: 20px;
    font-size: 10.5px;
    padding: 0 6px;
    background: var(--bg-content);
  }
  .btn.primary.tiny {
    background: var(--accent);
    color: #fff;
  }
  .btn.on {
    background: var(--accent-soft);
    color: var(--accent);
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
    background: var(--bg-inspector);
    border: 1px solid var(--separator-soft);
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
    color: #fff;
    font-size: 10px;
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
    background: rgba(0, 122, 255, 0.13);
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
    color: #fff;
  }
  .ph-flag {
    position: absolute;
    top: 2px;
    left: 50%;
    transform: translateX(-50%);
    background: var(--accent);
    color: #fff;
    font-size: 9.5px;
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
    font-size: 11px;
    color: var(--text-3);
    background: color-mix(in srgb, var(--bg-inspector) 74%, transparent);
  }

  /* ---------------- 表格 ---------------- */
  .table-area {
    flex: 1;
    min-height: 0;
    display: flex;
    flex-direction: column;
    margin-top: 4px;
    border-top: 1px solid var(--separator);
  }
  .thead {
    display: flex;
    align-items: center;
    height: 26px;
    padding: 0 14px;
    font-size: 11px;
    font-weight: 600;
    color: var(--text-3);
    border-bottom: 1px solid var(--separator-soft);
    flex: 0 0 26px;
  }
  .rows {
    flex: 1;
    min-height: 0;
    overflow-y: auto;
    overflow-x: hidden;
    padding-bottom: 6px;
    mask-image: linear-gradient(to bottom, #000 calc(100% - 22px), transparent 100%);
    -webkit-mask-image: linear-gradient(to bottom, #000 calc(100% - 22px), transparent 100%);
  }

  .row {
    display: flex;
    align-items: center;
    height: 26px;
    padding: 0 14px;
    font-size: 13px;
    border-bottom: 1px solid var(--separator-soft);
    position: relative;
    transition: background 120ms var(--ease);
  }
  .row:hover {
    background: var(--row-hover);
  }
  .row.row-sel {
    background: var(--accent-soft);
  }
  .row.playing::before {
    content: '';
    position: absolute;
    left: 0;
    top: 0;
    bottom: 0;
    width: 2.5px;
    background: var(--accent);
  }
  .row.playing .c-idx {
    color: var(--accent);
    font-weight: 600;
  }
  .row.playing .c-text {
    font-weight: 500;
  }

  .c-idx {
    width: 30px;
    flex: 0 0 30px;
    font-size: 11.5px;
    color: var(--text-3);
    font-variant-numeric: tabular-nums;
  }
  .c-t {
    width: 92px;
    flex: 0 0 92px;
    font-family: ui-monospace, 'SF Mono', Menlo, monospace;
    font-size: 11.5px;
    color: var(--text-2);
    font-variant-numeric: tabular-nums;
    letter-spacing: -0.02em;
  }
  .c-dur {
    width: 54px;
    flex: 0 0 54px;
    font-family: ui-monospace, 'SF Mono', Menlo, monospace;
    font-size: 11.5px;
    color: var(--text-3);
    font-variant-numeric: tabular-nums;
  }
  .c-text {
    flex: 1;
    min-width: 0;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .c-acts {
    width: 46px;
    flex: 0 0 46px;
    display: flex;
    justify-content: flex-end;
    gap: 2px;
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
</style>
