<script lang="ts">
  /**
   * 核对工作台。
   *
   * 这一屏是整个应用最像「专业工具」的地方，交互必须对得上肌肉记忆：
   *
   * - 波形可缩放（滚轮 / 捏合 / 滑块）与平移（双指横移 / 拖动选区外部），
   *   放大到数秒区间仍然清晰——服务端按可视窗口返回包络；
   * - 播放头始终可见，点哪里跳哪里，拖动播放头可搓碟；
   * - 在波形上拖出选区，可直接试听、局部转写、或同步到转写页；
   * - 每一行都能单独重转，不会冲掉整张表；
   * - 质检面板通过 store 的 focusRange 定位到这里，跳转是真的跳。
   */
  import { untrack } from 'svelte';
  import Icon from '../components/Icon.svelte';
  import { api, mediaUrl } from '../lib/api';
  import {
    app,
    focusRange,
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

  // 波形视窗（秒）。duration 来自媒体元数据。
  const duration = $derived(app.media?.duration ?? 0);
  let viewStart = $state(0);
  let viewSpan = $state(60);
  let follow = $state(true);
  let selection = $state<{ start: number; end: number } | null>(null);

  const MIN_SPAN = 0.5;

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

  const rowStart = $derived(Math.max(0, Math.floor(scrollTop / ROW_H) - OVERSCAN));
  const rowEnd = $derived(
    Math.min(
      app.cues.length,
      rowStart + Math.ceil((viewH || 400) / ROW_H) + OVERSCAN * 2,
    ),
  );
  const visibleCues = $derived(app.cues.slice(rowStart, rowEnd));

  const zoomX = $derived(duration > 0 ? Math.max(1, duration / Math.max(viewSpan, 0.001)) : 1);
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

  function setView(start: number, span: number, userAction = true) {
    const next = clampView(start, span);
    viewStart = next.start;
    viewSpan = next.span;
    if (userAction && play.playing && follow) follow = false;
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
    follow = true;
  });

  // ---------------- 波形包络 ----------------
  let peakSeq = 0;
  let peakTimer = 0;

  async function fetchPeaks(id: string, from: number, span: number, width: number) {
    const seq = ++peakSeq;
    loadingPeaks = true;
    try {
      const bins = Math.max(160, Math.min(4000, Math.round(width)));
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
    const sep = css.getPropertyValue('--separator-soft').trim() || 'rgba(0,0,0,.06)';
    const sepStrong = css.getPropertyValue('--separator').trim() || 'rgba(0,0,0,.1)';
    const waveColor = css.getPropertyValue('--wave').trim() || '#7b8a99';
    const accent = css.getPropertyValue('--accent').trim() || '#007aff';
    const text3 = css.getPropertyValue('--text-3').trim() || '#98989d';

    const rulerH = 17;
    const cueH = 11;
    const mid = rulerH + (h - rulerH - cueH) / 2;
    const ampH = Math.max(8, (h - rulerH - cueH) * 0.92);

    // 时间刻度
    const step = pickStep(viewSpan);
    ctx.fillStyle = text3;
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
    ctx.fillRect(0, rulerH - 0.5, w, 1);

    // 波形
    const n = peaks.length;
    if (!n) {
      ctx.fillStyle = sepStrong;
      ctx.fillRect(0, Math.round(mid), w, 1);
    } else {
      ctx.fillStyle = waveColor;
      ctx.globalAlpha = 0.82;
      const span = peaksSpan || 1;
      const barTime = span / n;
      for (let i = 0; i < n; i += 1) {
        const t = peaksFrom + (i + 0.5) * barTime;
        if (t < viewStart || t > viewStart + viewSpan) continue;
        const x = ((t - viewStart) / viewSpan) * w;
        const bw = Math.max(1, (barTime / viewSpan) * w * 0.72);
        constamp(peaks[i], ampH, ctx, x, mid, bw);
      }
      ctx.globalAlpha = 1;
    }

    // 字幕覆盖块（底部一条），让「哪里已经有字幕」一眼可见
    const cueY = h - cueH + 1;
    for (const cue of app.cues) {
      if (cue.end < viewStart || cue.start > viewStart + viewSpan) continue;
      const x0 = Math.max(0, xOf(cue.start));
      const x1 = Math.min(w, xOf(cue.end));
      if (x1 <= x0) continue;
      ctx.fillStyle = sep;
      ctx.fillRect(x0, cueY, Math.max(1, x1 - x0 - 0.5), cueH - 3);
    }
    const sel = play.selected >= 0 ? app.cues[play.selected] : null;
    if (sel) {
      const x0 = Math.max(0, xOf(sel.start));
      const x1 = Math.min(w, xOf(sel.end));
      ctx.fillStyle = accent;
      ctx.globalAlpha = 0.75;
      ctx.fillRect(x0, cueY, Math.max(1, x1 - x0), cueH - 3);
      ctx.globalAlpha = 1;
    }

    // 选中行的区间高亮（不是选区，只是当前条目）
    if (sel) {
      const x0 = Math.max(0, xOf(sel.start));
      const x1 = Math.min(w, xOf(sel.end));
      ctx.fillStyle = accent;
      ctx.globalAlpha = 0.07;
      ctx.fillRect(x0, rulerH, Math.max(1, x1 - x0), h - rulerH - cueH);
      ctx.globalAlpha = 1;
    }
  }

  // 小的辅助函数放外面会让参数一大堆，就地定义更清楚
  function constamp(
    value: number,
    ampH: number,
    ctx: CanvasRenderingContext2D,
    x: number,
    mid: number,
    bw: number,
  ) {
    const amp = Math.max(0.012, Math.min(1, value));
    const bh = amp * ampH;
    ctx.fillRect(x - bw / 2, mid - bh / 2, bw, bh);
  }

  function pickStep(span: number) {
    const candidates = [0.1, 0.2, 0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300, 600];
    for (const c of candidates) {
      if (span / c <= 12) return c;
    }
    return 900;
  }

  function rulerLabel(t: number, step: number) {
    const total = Math.round(t);
    const m = Math.floor(total / 60);
    const s = total % 60;
    if (step < 1) return `${m}:${String(s).padStart(2, '0')}.${String(Math.round((t % 1) * 10))}`;
    if (step < 60) return `${m}:${String(s).padStart(2, '0')}`;
    return `${m}:00`;
  }

  $effect(() => {
    void peaks;
    void viewStart;
    void viewSpan;
    void app.cues;
    void play.selected;
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

  // ---------------- 播放头 ----------------
  let rafId = 0;

  function tick() {
    rafId = requestAnimationFrame(tick);
    if (!video) return;
    // 只在「真的能解码并且在播」时用 video.currentTime 驱动播放头。
    // MKV / HEVC 还没压好代理时 readyState 一直是 0，如果无条件同步，
    // 用户点哪里播放头都会被 video 的 0 覆盖回去——看起来就是「播放头坏了」。
    const ready = video.readyState >= 2 && !video.error;
    const t = ready ? video.currentTime : play.time;
    if (ready) {
      if (!video.paused && !video.ended) play.time = t;
      play.playing = !video.paused && !video.ended;
    } else {
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

  // 所有「定位」入口都通过 seekNonce 进来，视频与播放头不会各走各的
  let seenSeek = 0;
  $effect(() => {
    const nonce = play.seekNonce;
    if (nonce === seenSeek) return;
    seenSeek = nonce;
    if (!video) return;
    // 只依赖 nonce：play.time / playAfterSeek 用 untrack 读，否则「读一下再写回」
    // 会让这个 effect 自己触发自己（effect_update_depth_exceeded）。
    const request = untrack(() => ({ time: play.time, play: play.playAfterSeek }));
    const t = Math.max(0, Math.min(request.time, video.duration || duration || request.time));
    video.currentTime = t;
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
    setView(center - span / 2, span, false);
    selection = { start: req.start, end: req.end };
    follow = false;
  });

  // ---------------- 交互 ----------------
  type DragMode = 'none' | 'select' | 'playhead' | 'resize-l' | 'resize-r' | 'pan';
  let dragMode: DragMode = $state('none');
  let dragAnchor = 0;
  let dragMoved = false;
  let panStartX = 0;
  let panStartView = 0;

  function xPlayhead() {
    return xOf(play.time);
  }

  function togglePlay() {
    if (!video) return;
    if (video.paused) void video.play().catch(() => {});
    else video.pause();
  }

  function seek(time: number) {
    seekTo(time);
  }

  function onWavePointerDown(e: PointerEvent) {
    if (!waveWrap || e.button !== 0) return;
    try {
      (e.currentTarget as HTMLElement).setPointerCapture?.(e.pointerId);
    } catch {
      /* 合成事件 / 已释放的 pointerId：忽略即可，拖动逻辑不依赖捕获 */
    }
    const t = timeAt(e.clientX);
    dragMoved = false;
    const nearPlayhead = Math.abs(e.clientX - (waveWrap.getBoundingClientRect().left + xPlayhead())) < 6;

    if (e.altKey) {
      dragMode = 'pan';
      panStartX = e.clientX;
      panStartView = viewStart;
      return;
    }
    if (nearPlayhead) {
      dragMode = 'playhead';
      seek(t);
      return;
    }
    if (e.shiftKey) {
      const a = play.time;
      dragMode = 'select';
      dragAnchor = a;
      selection = { start: Math.min(a, t), end: Math.max(a, t) };
      return;
    }
    dragMode = 'select';
    dragAnchor = t;
    selection = { start: t, end: t };
  }

  function onWavePointerMove(e: PointerEvent) {
    if (dragMode === 'none') return;
    if (dragMode === 'pan') {
      const dx = e.clientX - panStartX;
      const shift = -(dx / Math.max(1, waveW)) * viewSpan;
      setView(panStartView + shift, viewSpan, false);
      dragMoved = true;
      return;
    }
    const t = Math.max(0, Math.min(duration || t0(), timeAt(e.clientX)));
    if (dragMode === 'playhead') {
      seek(t);
      dragMoved = true;
      return;
    }
    if (dragMode === 'resize-l' && selection) {
      selection = { start: Math.min(t, selection.end - 0.05), end: selection.end };
      dragMoved = true;
      return;
    }
    if (dragMode === 'resize-r' && selection) {
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

  function onWavePointerUp() {
    const mode = dragMode;
    dragMode = 'none';
    if (mode === 'select') {
      if (!selection || !dragMoved || selection.end - selection.start < 0.08) {
        // 单击：跳转并清掉选区
        const t = selection ? selection.start : play.time;
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
    setView(play.time - span / 2, span, false);
    follow = true;
  }

  function focusSelection() {
    if (!selection) return;
    const span = Math.max(1.5, (selection.end - selection.start) * 1.6);
    const center = (selection.start + selection.end) / 2;
    setView(center - span / 2, span, false);
  }

  function clearSelection() {
    selection = null;
  }

  function toggleFollow() {
    follow = !follow;
    if (follow && play.playing) {
      const next = clampView(play.time - viewSpan * 0.15, viewSpan);
      viewStart = next.start;
    }
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

  // 播放时自动滚动到当前句
  $effect(() => {
    if (!play.playing || cueIndex < 0 || !rowsEl) return;
    const top = cueIndex * ROW_H;
    const viewTop = rowsEl.scrollTop;
    const viewBottom = viewTop + rowsEl.clientHeight;
    if (top < viewTop + ROW_H || top + ROW_H > viewBottom - ROW_H) {
      rowsEl.scrollTo({ top: top - rowsEl.clientHeight / 2, behavior: 'smooth' });
    }
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
          onerror={() => (videoFailed = true)}
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
        role="slider"
        tabindex="-1"
        aria-valuenow={play.time}
        onclick={(e) => {
          const el = e.currentTarget as HTMLElement;
          const r = el.getBoundingClientRect();
          seek(Math.max(0, Math.min(1, (e.clientX - r.left) / r.width)) * (duration || 1));
          follow = true;
        }}
      >
        <div class="tp-fill" style="width:{(play.time / (duration || 1)) * 100}%"></div>
        <div class="tp-knob" style="left:{(play.time / (duration || 1)) * 100}%"></div>
      </div>
      <div class="tp-dur">{formatDuration(duration)}</div>
    </div>
  </div>

  <div class="timeline">
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
          class:on={follow}
          onclick={toggleFollow}
          title="播放时视窗跟随播放头"
        >
          跟随
        </button>
      </div>

      <div class="tl-spacer"></div>

      {#if !selection}
        <span class="tl-hint">在波形上拖动框选 · 滚轮/捏合缩放 · 双指横移平移 · ⌥ 拖动平移</span>
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

    <div
      class="wave-wrap"
      bind:this={waveWrap}
      onpointerdown={onWavePointerDown}
      onpointermove={onWavePointerMove}
      onpointerup={onWavePointerUp}
      onpointercancel={onWavePointerUp}
      onwheel={onWaveWheel}
      ondblclick={(e) => {
        const t = timeAt(e.clientX);
        const span = Math.max(1.5, Math.min(10, viewSpan / 5 || 5));
        setView(t - span / 2, span, false);
        follow = true;
      }}
      class:dragging={dragMode !== 'none'}
    >
      <canvas bind:this={canvas}></canvas>

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
            class:playing={cueIndex === i}
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
    height: 4px;
    border-radius: 2px;
    background: var(--fill-strong);
    position: relative;
    cursor: pointer;
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
  }

  /* ---------------- 波形区 ---------------- */
  .timeline {
    padding: 6px 14px 0;
    display: flex;
    flex-direction: column;
    gap: 5px;
    flex: 0 0 auto;
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
  }

  .sel-bar {
    display: flex;
    align-items: center;
    gap: 5px;
    background: var(--accent-soft);
    border-radius: 7px;
    padding: 2px 5px 2px 9px;
    height: 26px;
    margin-top: 1px;
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
    height: 96px;
    border-radius: 8px;
    background: var(--bg-inspector);
    border: 1px solid var(--separator-soft);
    overflow: hidden;
    touch-action: none;
    cursor: crosshair;
  }
  .wave-wrap.dragging {
    cursor: default;
  }
  canvas {
    display: block;
    width: 100%;
    height: 100%;
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
    bottom: 0;
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
