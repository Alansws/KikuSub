<script lang="ts">
  import Icon from '../components/Icon.svelte';
  import { app, openMedia } from '../lib/store.svelte';
  import { formatBytes, formatDuration } from '../lib/time';

  interface Recent {
    path: string;
    name: string;
    size: number;
    duration: number;
    at: number;
  }

  let recents = $state<Recent[]>([]);

  $effect(() => {
    try {
      recents = JSON.parse(localStorage.getItem('kikusub.recent') || '[]');
    } catch {
      recents = [];
    }
  });

  // 媒体变化时记一笔「最近打开」
  $effect(() => {
    const m = app.media;
    if (!m) return;
    const entry: Recent = {
      path: m.path,
      name: m.name,
      size: m.size,
      duration: m.duration,
      at: Date.now(),
    };
    const next = [entry, ...recents.filter((r) => r.path !== m.path)].slice(0, 6);
    recents = next;
    localStorage.setItem('kikusub.recent', JSON.stringify(next));
  });

  async function pick() {
    const file = await window.kikusub.pickMedia();
    if (file) await openMedia(file);
  }

  function when(at: number) {
    const d = new Date(at);
    const today = new Date();
    const sameDay = d.toDateString() === today.toDateString();
    if (sameDay) return `今天 ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
    return `${d.getMonth() + 1} 月 ${d.getDate()} 日`;
  }
</script>

<div class="pane">
  <div class="h1">导入素材</div>
  <p class="p">把视频拖进窗口，或按 <b>⌘O</b> 选择文件。导入不会复制文件——只记录路径。</p>

  <button class="dropzone" onclick={pick}>
    <span class="dz-ico"><Icon name="tray" size={20} /></span>
    <span class="dz-title">拖入视频或字幕</span>
    <span class="dz-sub">
      <code>.mkv</code> <code>.mp4</code> <code>.mov</code> <code>.srt</code> <code>.vtt</code>
    </span>
  </button>

  <p class="note">
    Chromium 解不开 MKV / HEVC，导入后会在后台自动压一份 480p 监看代理，拖动进度条才能流畅秒开。
  </p>

  {#if recents.length}
    <div class="ins-h" style="margin-top:22px">最近打开</div>
    <div class="recent">
      {#each recents as r (r.path)}
        <button class="recent-row" onclick={() => openMedia(r.path)} title={r.path}>
          <span class="ri"><Icon name="film" size={13} /></span>
          <span class="rn-wrap">
            <span class="rn">{r.name}</span>
            <span class="rm">
              {formatBytes(r.size)} · {formatDuration(r.duration)}
            </span>
          </span>
          <span class="rt">{when(r.at)}</span>
        </button>
      {/each}
    </div>
  {/if}
</div>

<style>
  .pane {
    padding: 22px 26px 28px;
    overflow-y: auto;
    flex: 1;
  }
  .pane > * {
    max-width: 720px;
  }

  .h1 {
    font-size: 19px;
    font-weight: 600;
    letter-spacing: -0.01em;
    margin: 2px 0 4px;
  }
  .p {
    font-size: 12.5px;
    color: var(--text-2);
    margin: 0 0 16px;
  }
  .note {
    font-size: 11.5px;
    line-height: 1.6;
    color: var(--text-3);
    margin: 14px 0 0;
  }

  .dropzone {
    appearance: none;
    display: block;
    width: 100%;
    border: 1.5px dashed var(--separator);
    border-radius: 12px;
    padding: 46px 20px;
    text-align: center;
    background: transparent;
    color: inherit;
    font: inherit;
    transition: border-color var(--dur) var(--ease), background var(--dur) var(--ease);
  }
  .dropzone:hover {
    border-color: var(--accent-ring);
    background: var(--accent-soft);
  }
  .dz-ico {
    width: 40px;
    height: 40px;
    margin: 0 auto 10px;
    border-radius: 11px;
    background: var(--fill);
    display: grid;
    place-items: center;
    color: var(--text-2);
  }
  .dz-title {
    display: block;
    font-size: 13.5px;
    font-weight: 500;
    margin-bottom: 3px;
  }
  .dz-sub {
    display: block;
    font-size: 12px;
    color: var(--text-3);
  }
  code {
    font-family: ui-monospace, 'SF Mono', Menlo, monospace;
    font-size: 11px;
    background: var(--fill);
    padding: 1px 4px;
    border-radius: 4px;
  }

  .recent {
    border: 1px solid var(--separator-soft);
    border-radius: 10px;
    overflow: hidden;
  }
  .recent-row {
    appearance: none;
    border: 0;
    background: transparent;
    color: inherit;
    font: inherit;
    width: 100%;
    display: flex;
    align-items: center;
    gap: 10px;
    height: 44px;
    padding: 0 12px;
    border-bottom: 1px solid var(--separator-soft);
    text-align: left;
    transition: background var(--dur) var(--ease);
  }
  .recent-row:last-child {
    border-bottom: 0;
  }
  .recent-row:hover {
    background: var(--row-hover);
  }
  .ri {
    width: 26px;
    height: 26px;
    border-radius: 6px;
    background: var(--fill);
    display: grid;
    place-items: center;
    color: var(--text-2);
    flex: 0 0 26px;
  }
  .rn-wrap {
    display: flex;
    flex-direction: column;
    gap: 1px;
    min-width: 0;
    flex: 1;
  }
  .rn {
    font-size: 12.5px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .rm {
    font-size: 11px;
    color: var(--text-3);
    font-variant-numeric: tabular-nums;
  }
  .rt {
    font-size: 11px;
    color: var(--text-3);
    flex: 0 0 auto;
  }
</style>
