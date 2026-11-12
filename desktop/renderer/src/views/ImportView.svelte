<script lang="ts">
  import { untrack } from 'svelte';
  import Icon from '../components/Icon.svelte';
  import PageHeader from '../components/PageHeader.svelte';
  import { app, openMedia, openSubtitle, toast } from '../lib/store.svelte';
  import { mediaThumbUrl } from '../lib/api';
  import { formatBytes, formatDuration } from '../lib/time';

  interface Recent {
    path: string;
    name: string;
    size: number;
    duration: number;
    at: number;
  }

  type RecentView = 'list' | 'grid';

  let recents = $state<Recent[]>([]);
  /** 「最近打开」的呈现方式：列表（信息密度高）或图标（封面画廊）。 */
  let recentView = $state<RecentView>('list');

  /** 字幕默认导出目录：设置页可改；旧配置没有 export_dir 时退回 output_dir。 */
  const exportDir = $derived(app.config?.export_dir || app.settings?.export_dir || app.config?.output_dir || '');

  /**
   * 缩略图必须等握手完成再挂载。
   *
   * `<img>` 的 URL 里带 `?token=`；内核还没 ready 时 TOKEN 是空串，请求必然 401，
   * 而 onerror 会把这张图摘掉——冷启动时「最近打开」就只能看到胶片图标。
   * 等 `app.connected` 变 true 再挂 `<img>`，一次就成功。
   */
  const thumbsReady = $derived(app.connected);

  function persistRecents(next: Recent[]) {
    recents = next;
    try {
      localStorage.setItem('kikusub.recent', JSON.stringify(next));
    } catch {
      /* 隐私模式 / 存储满：界面状态保留在内存里即可 */
    }
  }

  function setRecentView(next: RecentView) {
    if (recentView === next) return;
    recentView = next;
    try {
      localStorage.setItem('kikusub.recent.view', next);
    } catch {
      /* 同上：记不住偏好不影响使用 */
    }
  }

  $effect(() => {
    try {
      const raw = JSON.parse(localStorage.getItem('kikusub.recent') || '[]');
      recents = Array.isArray(raw) ? raw.filter((r) => r && typeof r.path === 'string') : [];
      const saved = localStorage.getItem('kikusub.recent.view');
      if (saved === 'grid' || saved === 'list') recentView = saved;
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
    // 读 recents 必须 unrack：否则「读一下再写回」会让 effect 自己触发自己，
    // 表现为 Svelte 的 effect_update_depth_exceeded，整个界面白屏。
    const prev = untrack(() => recents);
    persistRecents([entry, ...prev.filter((r) => r.path !== m.path)].slice(0, 6));
  });

  /** 单条删除最近打开记录；不影响磁盘上的视频与字幕。 */
  function removeRecent(path: string) {
    const prev = untrack(() => recents);
    const item = prev.find((r) => r.path === path);
    persistRecents(prev.filter((r) => r.path !== path));
    toast(item ? `已从最近打开中移除「${item.name}」` : '已从最近打开中移除');
  }

  function openExportFolder() {
    if (!exportDir) {
      toast('还没有可用的导出文件夹，请先到设置里选择', 'warn');
      return;
    }
    void window.kikusub.openPath(exportDir);
  }

  /** 原生对话框直接落在导出文件夹，用户挑一个上次转写的 SRT/VTT 就进核对台。 */
  async function importFromExport() {
    if (!exportDir) {
      toast('还没有可用的导出文件夹，请先到设置里选择', 'warn');
      return;
    }
    const file = await window.kikusub.pickSubtitle(exportDir);
    if (file) await openSubtitle(file);
  }

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

  /** 画廊封面请求更大尺寸的缩略图：卡片约 220px 宽，2x 屏需要 ~440px。 */
  function coverUrl(r: Recent) {
    return mediaThumbUrl(r.path, String(r.size));
  }
</script>

<div class="pane">
  <PageHeader
    title="导入素材"
    subtitle="把视频拖进窗口，或按 ⌘O 选择文件。导入不会复制文件——只记录路径。"
  />

  <button class="dropzone" onclick={pick}>
    <span class="dz-ico"><Icon name="tray" size={20} /></span>
    <span class="dz-title">拖入视频或字幕</span>
    <span class="dz-sub">
      <code>.mkv</code> <code>.mp4</code> <code>.mov</code> <code>.srt</code> <code>.vtt</code>
    </span>
  </button>

  <p class="note" title="Chromium 解不开 MKV / HEVC；高码率 H.264 有时能播但拖动很卡。导入后可在核对台手动压制代理。">
    MKV / HEVC 自动压一份 480p 监看代理，拖动才能秒开；也可以在核对台手动压制。
  </p>

  {#if exportDir}
    <div class="ins-h" style="margin-top:22px">导出文件夹</div>
    <div class="export-card">
      <span class="ec-ico"><Icon name="folder" size={15} /></span>
      <span class="ec-main">
        <b>上次转写的字幕在这里</b>
        <span class="ec-path mono" title={exportDir}>{exportDir}</span>
      </span>
      <button class="btn tiny" onclick={openExportFolder} title="在访达中打开导出文件夹">
        打开文件夹
      </button>
      <button class="btn tiny primary" onclick={importFromExport} title="从导出文件夹选择原文字幕并导入核对台">
        <Icon name="export" size={10} />导入原文…
      </button>
    </div>
  {/if}

  {#if recents.length}
    <div class="ins-h" style="margin-top:22px">
      <span>最近打开</span>
      <div class="seg compact" role="group" aria-label="最近打开的显示方式">
        <button
          class:on={recentView === 'list'}
          aria-pressed={recentView === 'list'}
          title="列表：一次看清大小、时长与打开时间"
          aria-label="列表视图"
          onclick={() => setRecentView('list')}
        >
          <Icon name="rows" size={12} />
        </button>
        <button
          class:on={recentView === 'grid'}
          aria-pressed={recentView === 'grid'}
          title="图标：封面画廊，找片子更快"
          aria-label="图标视图"
          onclick={() => setRecentView('grid')}
        >
          <Icon name="grid" size={12} />
        </button>
      </div>
    </div>

    {#if recentView === 'list'}
      <div class="recent">
        {#each recents as r (r.path)}
          <div class="recent-row">
            <button class="recent-main" onclick={() => openMedia(r.path)} title={r.path}>
              <span class="ri">
                <Icon name="film" size={13} />
                {#if thumbsReady}
                  <img
                    class="ri-img"
                    src={mediaThumbUrl(r.path, String(r.size))}
                    alt=""
                    loading="lazy"
                    draggable="false"
                    onerror={(e) => e.currentTarget.remove()}
                  />
                {/if}
              </span>
              <span class="rn-wrap">
                <span class="rn">{r.name}</span>
                <span class="rm">
                  {formatBytes(r.size)} · {formatDuration(r.duration)}
                </span>
              </span>
              <span class="rt">{when(r.at)}</span>
            </button>
            <button
              class="recent-del"
              onclick={() => removeRecent(r.path)}
              title="从最近打开中移除（不删除文件）"
              aria-label={`从最近打开中移除 ${r.name}`}
            >
              <Icon name="trash" size={12} />
            </button>
          </div>
        {/each}
      </div>
    {:else}
      <div class="gallery">
        {#each recents as r, index (r.path)}
          <div class="gcard" style={`--i:${index}`}>
            <button class="gcard-main" onclick={() => openMedia(r.path)} title={r.path}>
              <span class="cover">
                <span class="cover-fb"><Icon name="film" size={22} /></span>
                {#if thumbsReady}
                  <img
                    class="cover-img"
                    src={coverUrl(r)}
                    alt=""
                    loading="lazy"
                    draggable="false"
                    onerror={(e) => e.currentTarget.remove()}
                  />
                {/if}
                <span class="cover-play" aria-hidden="true"><Icon name="play" size={15} /></span>
                {#if r.duration > 0}
                  <span class="cover-dur">{formatDuration(r.duration)}</span>
                {/if}
              </span>
              <span class="gcard-body">
                <span class="gcard-name">{r.name}</span>
                <span class="gcard-meta">{formatBytes(r.size)} · {when(r.at)}</span>
              </span>
            </button>
            <button
              class="gcard-del"
              onclick={() => removeRecent(r.path)}
              title="从最近打开中移除（不删除文件）"
              aria-label={`从最近打开中移除 ${r.name}`}
            >
              <Icon name="trash" size={12} />
            </button>
          </div>
        {/each}
      </div>
    {/if}
  {/if}
</div>

<style>
  .pane {
    flex: 1;
    min-height: 0;
    overflow-y: auto;
    padding: var(--sp-8) var(--sp-10) var(--sp-12);
    display: grid;
    grid-template-columns: minmax(0, 720px);
    justify-content: center;
    align-content: start;
  }

  .note {
    font-size: var(--fs-label);
    line-height: 1.7;
    color: var(--text-3);
    margin: 14px 0 0;
    max-width: 640px;
  }

  .dropzone {
    appearance: none;
    display: block;
    width: 100%;
    border: 1.5px dashed var(--separator);
    border-radius: var(--rad-panel);
    padding: var(--sp-12) var(--sp-5);
    margin-top: var(--sp-1);
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
    border-radius: 8px;
    background: var(--fill);
    display: grid;
    place-items: center;
    color: var(--text-2);
  }
  .dz-title {
    display: block;
    font-size: var(--fs-heading);
    font-weight: 600;
    margin-bottom: var(--sp-1);
  }
  .dz-sub {
    display: block;
    font-size: var(--fs-label);
    color: var(--text-3);
  }
  code {
    font-family: ui-monospace, 'SF Mono', Menlo, monospace;
    font-size: 12px;
    background: var(--fill);
    padding: 1px var(--sp-1);
    border-radius: 4px;
  }

  .export-card {
    display: flex;
    align-items: center;
    gap: 10px;
    border: 1px solid var(--separator-soft);
    border-radius: 8px;
    padding: 10px var(--sp-3);
    background: var(--bg-content);
  }
  .ec-ico {
    width: 30px;
    height: 30px;
    border-radius: 8px;
    background: var(--fill);
    display: grid;
    place-items: center;
    color: var(--text-2);
    flex: 0 0 30px;
  }
  .ec-main {
    display: flex;
    flex-direction: column;
    gap: 2px;
    min-width: 0;
    flex: 1;
  }
  .ec-main b {
    font-size: 12.5px;
    font-weight: 500;
  }
  .ec-path {
    font-size: 12px;
    color: var(--text-3);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .recent {
    border: 1px solid var(--separator-soft);
    border-radius: 8px;
    overflow: hidden;
  }
  .recent-row {
    display: flex;
    align-items: stretch;
    border-bottom: 1px solid var(--separator-soft);
  }
  .recent-row:last-child {
    border-bottom: 0;
  }
  .recent-row:hover {
    background: var(--row-hover);
  }
  .recent-main {
    appearance: none;
    border: 0;
    background: transparent;
    color: inherit;
    font: inherit;
    min-width: 0;
    flex: 1;
    display: flex;
    align-items: center;
    gap: 10px;
    height: 52px;
    padding: 0 var(--sp-1) 0 var(--sp-3);
    text-align: left;
    cursor: default;
  }
  .recent-del {
    appearance: none;
    border: 0;
    background: transparent;
    color: var(--text-3);
    width: 38px;
    flex: 0 0 38px;
    display: grid;
    place-items: center;
    cursor: default;
    border-left: 1px solid transparent;
    transition: color var(--dur) var(--ease), background var(--dur) var(--ease);
  }
  .recent-del:hover {
    color: var(--danger);
    background: var(--danger-soft);
    border-left-color: var(--separator-soft);
  }
  .ri {
    position: relative;
    width: 54px;
    height: 31px;
    border-radius: 4px;
    background: var(--fill);
    display: grid;
    place-items: center;
    color: var(--text-2);
    flex: 0 0 54px;
    overflow: hidden;
  }
  .ri-img {
    position: absolute;
    inset: 0;
    width: 100%;
    height: 100%;
    object-fit: cover;
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
    font-size: 12px;
    color: var(--text-3);
    font-variant-numeric: tabular-nums;
  }
  .rt {
    font-size: 12px;
    color: var(--text-3);
    flex: 0 0 auto;
  }

  /* ---------- 画廊（图标视图）---------- */
  .gallery {
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: var(--sp-4) 14px;
  }

  .gcard {
    position: relative;
    min-width: 0;
    animation: card-in 220ms var(--ease) both;
    animation-delay: calc(var(--i, 0) * 26ms);
  }

  @keyframes card-in {
    from {
      opacity: 0;
      transform: translateY(4px);
    }
    to {
      opacity: 1;
      transform: none;
    }
  }

  .gcard-main {
    appearance: none;
    border: 0;
    background: transparent;
    color: inherit;
    font: inherit;
    display: flex;
    flex-direction: column;
    gap: 7px;
    width: 100%;
    padding: 0;
    text-align: left;
    cursor: default;
  }
  .gcard-main:focus-visible {
    outline: 2px solid var(--accent-ring);
    outline-offset: 3px;
    border-radius: var(--rad-card);
  }

  .cover {
    position: relative;
    display: block;
    width: 100%;
    aspect-ratio: 16 / 9;
    border-radius: var(--rad-card);
    background: var(--fill);
    overflow: hidden;
  }
  .cover-fb {
    position: absolute;
    inset: 0;
    display: grid;
    place-items: center;
    color: var(--text-3);
  }
  .cover-img {
    position: absolute;
    inset: 0;
    width: 100%;
    height: 100%;
    object-fit: cover;
    transform: scale(1);
    transition: transform 320ms var(--ease), filter var(--dur) var(--ease);
  }
  .gcard-main:hover .cover-img {
    transform: scale(1.035);
  }
  .gcard-main:hover .gcard-name {
    color: var(--text);
  }

  /* 封面上的控件是「压在媒体上的浮层」，黑白半透明在明暗两套主题下都成立。 */
  .cover-play {
    position: absolute;
    left: 50%;
    top: 50%;
    width: 34px;
    height: 34px;
    margin: -17px 0 0 -17px;
    border-radius: 50%;
    display: grid;
    place-items: center;
    color: #fff;
    background: rgba(0, 0, 0, 0.46);
    backdrop-filter: blur(2px);
    opacity: 0;
    transform: scale(0.9);
    transition: opacity 180ms var(--ease), transform 180ms var(--ease);
  }
  .gcard-main:hover .cover-play,
  .gcard-main:focus-visible .cover-play {
    opacity: 1;
    transform: scale(1);
  }

  .cover-dur {
    position: absolute;
    right: 6px;
    bottom: 6px;
    padding: 1px 5px;
    border-radius: 3px;
    background: rgba(0, 0, 0, 0.55);
    color: #fff;
    font-size: 11px;
    line-height: 1.5;
    font-variant-numeric: tabular-nums;
  }

  .gcard-del {
    position: absolute;
    top: 6px;
    right: 6px;
    width: 22px;
    height: 22px;
    border: 0;
    border-radius: 50%;
    display: grid;
    place-items: center;
    color: #fff;
    background: rgba(0, 0, 0, 0.5);
    cursor: default;
    opacity: 0;
    transform: scale(0.92);
    transition: opacity 160ms var(--ease), background var(--dur) var(--ease),
      transform 160ms var(--ease);
  }
  .gcard:hover .gcard-del,
  .gcard-del:focus-visible {
    opacity: 1;
    transform: scale(1);
  }
  .gcard-del:hover {
    background: var(--danger);
  }
  .gcard-del:focus-visible {
    outline: 2px solid var(--accent-ring);
    outline-offset: 2px;
  }

  .gcard-body {
    display: flex;
    flex-direction: column;
    gap: 2px;
    min-width: 0;
  }
  .gcard-name {
    font-size: 12.5px;
    color: var(--text-2);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    transition: color var(--dur) var(--ease);
  }
  .gcard-meta {
    font-size: 12px;
    color: var(--text-3);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    font-variant-numeric: tabular-nums;
  }

  /* 窄窗口（分屏、小尺寸窗口）退成两列，封面仍然比列表缩略图大得多。 */
  @media (max-width: 720px) {
    .pane {
      padding-left: var(--sp-6);
      padding-right: var(--sp-6);
    }
    .gallery {
      grid-template-columns: repeat(2, minmax(0, 1fr));
    }
  }
</style>
