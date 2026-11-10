<script lang="ts">
  import Icon from '../components/Icon.svelte';
  import { api, mediaUrl } from '../lib/api';
  import { app, play } from '../lib/store.svelte';
  import { tc, tcShort } from '../lib/time';

  let { lod = 'mid' }: { lod?: string } = $props();

  let video = $state<HTMLVideoElement | null>(null);
  let waveWrap = $state<HTMLDivElement | null>(null);
  let canvas = $state<HTMLCanvasElement | null>(null);
  let rowsEl = $state<HTMLDivElement | null>(null);

  let peaks = $state<number[]>([]);
  let peakDuration = $state(0);
  let videoFailed = $state(false);
  let scrollTop = $state(0);

  const src = $derived(app.media ? mediaUrl(app.media.id) : '');
  const cueIndex = $derived.by(() => {
    const t = play.time;
    const cues = app.cues;
    // 字幕按时间有序，用二分找当前句
    let lo = 0;
    let hi = cues.length - 1;
    let found = -1;
    while (lo <= hi) {
      const mid = (lo + hi) >> 1;
      const c = cues[mid];
      if (t < c.start) hi = mid - 1;
      else if (t >= c.end) lo = mid + 1;
      else {
        found = mid;
        break;
      }
    }
    return found;
  });
  const caption = $derived(cueIndex >= 0 ? app.cues[cueIndex]?.text ?? '' : '');

  // ---------------- 播放头：rVFC 取 mediaTime + rAF 插值 ----------------
  let lastMedia = 0;
  let lastTs = 0;
  let rafId = 0;

  function tick() {
    if (!video) return;
    rafId = requestAnimationFrame(tick);
    if (!video.paused && !video.seeking) {
      // 影片只有 24/30 帧，rVFC 每秒只来那么几次；用 rAF 在两次之间插值，
      // 播放头才能真的按 60fps 走（规划 §5 指标 1）
      const now = performance.now();
      const dt = lastTs ? (now - lastTs) / 1000 : 0;
      lastTs = now;
      const t = lastMedia + dt;
      if (t < (video.duration || Infinity)) play.time = t;
    } else {
      lastTs = performance.now();
    }
    play.playing = !video.paused;
  }

  function bindVideo(node: HTMLVideoElement) {
    video = node;
    play.duration = app.media?.duration ?? 0;

    const onFrame = (_now: number, meta: { mediaTime: number }) => {
      lastMedia = meta.mediaTime;
      lastTs = performance.now();
      node.requestVideoFrameCallback?.(onFrame);
    };
    if (node.requestVideoFrameCallback) node.requestVideoFrameCallback(onFrame);

    rafId = requestAnimationFrame(tick);
    return {
      destroy() {
        cancelAnimationFrame(rafId);
        video = null;
      },
    };
  }

  // ---------------- 波形 ----------------
  async function loadPeaks() {
    if (!app.media) return;
    try {
      const data = await api.peaks(app.media.id, {
        lod: lod as 'overview' | 'mid' | 'fine',
      });
      peaks = data.peaks;
      peakDuration = data.duration;
    } catch {
      peaks = [];
    }
  }

  $effect(() => {
    // 依赖：媒体 id 与缩放档位
    void app.media?.id;
    void lod;
    loadPeaks();
  });

  let dpr = 1;
  function drawWave() {
    if (!canvas || !waveWrap) return;
    const w = waveWrap.clientWidth;
    const h = waveWrap.clientHeight;
    if (!w || !h) return;
    dpr = window.devicePixelRatio || 1;
    canvas.width = Math.round(w * dpr);
    canvas.height = Math.round(h * dpr);
    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);

    const mid = h / 2;
    const n = peaks.length;
    const waveColor = getComputedStyle(document.documentElement).getPropertyValue('--wave').trim();
    const sepColor = getComputedStyle(document.documentElement).getPropertyValue('--separator-soft').trim();

    // 秒刻度
    ctx.fillStyle = sepColor;
    const total = peakDuration || 1;
    const step = total > 600 ? 60 : total > 120 ? 10 : 1;
    for (let t = 0; t <= total; t += step) {
      const x = (t / total) * w;
      ctx.fillRect(x, 0, 1, t % (step * 5) === 0 ? h : h * 0.3);
    }

    if (!n) {
      ctx.fillStyle = sepColor;
      ctx.fillRect(0, Math.round(mid), w, 1);
      return;
    }

    ctx.fillStyle = waveColor;
    ctx.globalAlpha = 0.85;
    const bw = w / n;
    for (let i = 0; i < n; i++) {
      const amp = Math.max(0.015, peaks[i]);
      const bh = amp * (h * 0.84);
      ctx.fillRect(i * bw, mid - bh / 2, Math.max(1, bw * 0.72), bh);
    }
    ctx.globalAlpha = 1;

    ctx.fillStyle = sepColor;
    ctx.fillRect(0, Math.round(mid), w, 1);
  }

  $effect(() => {
    void peaks;
    void app.theme;
    requestAnimationFrame(drawWave);
  });

  $effect(() => {
    if (!waveWrap) return;
    const ro = new ResizeObserver(() => drawWave());
    ro.observe(waveWrap);
    return () => ro.disconnect();
  });

  // ---------------- 交互 ----------------
  function togglePlay() {
    if (!video) return;
    if (video.paused) video.play();
    else video.pause();
  }

  function seek(t: number) {
    if (!video) return;
    const clamped = Math.max(0, Math.min(t, video.duration || t));
    video.currentTime = clamped;
    play.time = clamped;
    lastMedia = clamped;
    lastTs = performance.now();
  }

  function seekFromWave(e: MouseEvent) {
    if (!waveWrap) return;
    const r = waveWrap.getBoundingClientRect();
    const ratio = Math.max(0, Math.min(1, (e.clientX - r.left) / r.width));
    seek(ratio * (peakDuration || play.duration));
  }

  function seekFromTrack(e: MouseEvent) {
    const el = e.currentTarget as HTMLElement;
    const r = el.getBoundingClientRect();
    const ratio = Math.max(0, Math.min(1, (e.clientX - r.left) / r.width));
    seek(ratio * (play.duration || peakDuration));
  }

  function selectCue(i: number, doSeek = true) {
    play.selected = i;
    if (doSeek) seek(app.cues[i].start + 0.02);
  }

  // 播放时自动滚动到当前句
  $effect(() => {
    if (!play.playing || cueIndex < 0 || !rowsEl) return;
    const row = rowsEl.querySelector<HTMLElement>(`[data-i="${cueIndex}"]`);
    if (!row) return;
    const top = row.offsetTop;
    const bottom = top + row.offsetHeight;
    const viewTop = rowsEl.scrollTop;
    const viewBottom = viewTop + rowsEl.clientHeight;
    if (top < viewTop + 26 || bottom > viewBottom - 26) {
      rowsEl.scrollTo({ top: top - rowsEl.clientHeight / 2, behavior: 'smooth' });
    }
  });

  // 暴露给菜单/快捷键
  export function api_play() {
    togglePlay();
  }
  export function api_step(delta: number) {
    const next = Math.max(0, Math.min(app.cues.length - 1, play.selected + delta));
    selectCue(next);
  }
</script>

<div class="review">
  <div class="stage">
    <div class="player">
      {#if src}
        <video
          {@attach bindVideo}
          src={src}
          preload="auto"
          playsinline
          onerror={() => (videoFailed = true)}
        ></video>
      {:else}
        <div class="empty">还没有导入媒体</div>
      {/if}

      {#if caption}
        <div class="caption">{caption}</div>
      {/if}

      {#if videoFailed || (app.media?.needs_proxy && !play.playing)}
        <div class="notice">
          <Icon name="warn" size={13} />
          {videoFailed
            ? 'Chromium 无法直接解码这个容器，需要 480p 代理'
            : '正在后台压制 480p 监看代理，压制完成后即可流畅拖动'}
        </div>
      {/if}
    </div>

    <div class="transport">
      <button class="btn icon" onclick={togglePlay} title="播放 / 暂停（空格）">
        <Icon name={play.playing ? 'pause' : 'play'} size={13} />
      </button>
      <div class="tp-time">
        <b>{tc(play.time, false)}.{String(Math.floor((play.time % 1) * 10))}</b>
        <span>/ {tc(play.duration, true)}</span>
      </div>
      <div
        class="tp-track"
        role="slider"
        tabindex="-1"
        aria-valuenow={play.time}
        onclick={seekFromTrack}
      >
        <div class="tp-fill" style="width:{(play.time / (play.duration || 1)) * 100}%"></div>
        <div class="tp-knob" style="left:{(play.time / (play.duration || 1)) * 100}%"></div>
      </div>
    </div>

    <div class="wave-wrap" bind:this={waveWrap} onclick={seekFromWave}>
      <canvas bind:this={canvas}></canvas>
      <div
        class="wave-playhead"
        style="transform:translateX({((play.time / (peakDuration || 1)) * 100).toFixed(3)}%)"
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
    </div>
    <div class="rows" bind:this={rowsEl} onscroll={(e) => (scrollTop = e.currentTarget.scrollTop)}>
      {#each app.cues as cue, i (i)}
        <div
          class="row"
          class:sel={play.selected === i}
          class:playing={cueIndex === i}
          data-i={i}
          onclick={() => selectCue(i)}
          role="button"
          tabindex="-1"
        >
          <div class="c-idx">{i + 1}</div>
          <div class="c-t">{tcShort(cue.start)}</div>
          <div class="c-t">{tcShort(cue.end)}</div>
          <div class="c-dur">{(cue.end - cue.start).toFixed(2)}s</div>
          <div class="c-text">{cue.text}</div>
        </div>
      {:else}
        <div class="empty-rows">还没有字幕。到「转写」跑一次。</div>
      {/each}
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
    gap: 10px;
    flex: 0 0 auto;
  }

  .player {
    position: relative;
    width: 100%;
    /* 高度跟窗口走：固定 max-height 会把 16:9 挤成超宽盒，两侧出现大片黑边。
       窗口越高越接近 16:9，黑边越少。 */
    height: min(46vh, 400px);
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
    max-width: 82%;
    background: var(--caption-bg);
    backdrop-filter: blur(6px);
    color: #fff;
    font-size: 14px;
    line-height: 1.45;
    padding: 4px 12px;
    border-radius: 6px;
    text-align: center;
    text-shadow: 0 1px 2px rgba(0, 0, 0, 0.5);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    pointer-events: none;
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
  .tp-track {
    flex: 1;
    height: 4px;
    border-radius: 2px;
    background: var(--fill-strong);
    position: relative;
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

  .wave-wrap {
    position: relative;
    height: 66px;
    border-radius: 8px;
    background: var(--bg-inspector);
    border: 1px solid var(--separator-soft);
    overflow: hidden;
  }
  canvas {
    display: block;
    width: 100%;
    height: 100%;
  }
  .wave-playhead {
    position: absolute;
    top: 0;
    bottom: 0;
    left: 0;
    width: 1.5px;
    background: var(--accent);
    box-shadow: 0 0 0 0.5px rgba(255, 255, 255, 0.55);
    will-change: transform;
    pointer-events: none;
  }

  .table-area {
    flex: 1;
    min-height: 0;
    display: flex;
    flex-direction: column;
    margin-top: 2px;
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
  .row.sel {
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

  .empty-rows {
    padding: 22px 14px;
    color: var(--text-3);
    font-size: 12.5px;
  }
</style>
