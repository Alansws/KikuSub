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

  let recents = $state<Recent[]>([]);

  /** 字幕默认导出目录：设置页可改；旧配置没有 export_dir 时退回 output_dir。 */
  const exportDir = $derived(app.config?.export_dir || app.settings?.export_dir || app.config?.output_dir || '');

  function persistRecents(next: Recent[]) {
    recents = next;
    try {
      localStorage.setItem('kikusub.recent', JSON.stringify(next));
    } catch {
      /* 隐私模式 / 存储满：界面状态保留在内存里即可 */
    }
  }

  $effect(() => {
    try {
      const raw = JSON.parse(localStorage.getItem('kikusub.recent') || '[]');
      recents = Array.isArray(raw) ? raw.filter((r) => r && typeof r.path === 'string') : [];
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
      <button class="btn tiny primary" onclick={importFromExport} title="从导出文件夹选择字幕并导入核对台">
        <Icon name="export" size={10} />导入字幕…
      </button>
    </div>
  {/if}

  {#if recents.length}
    <div class="ins-h" style="margin-top:22px">最近打开</div>
    <div class="recent">
      {#each recents as r (r.path)}
        <div class="recent-row">
          <button class="recent-main" onclick={() => openMedia(r.path)} title={r.path}>
            <span class="ri">
              <Icon name="film" size={13} />
              <img
                class="ri-img"
                src={mediaThumbUrl(r.path, String(r.size))}
                alt=""
                loading="lazy"
                onerror={(e) => e.currentTarget.remove()}
              />
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
    padding: 48px 20px;
    margin-top: 4px;
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
    margin-bottom: 4px;
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
    padding: 1px 4px;
    border-radius: 4px;
  }

  .export-card {
    display: flex;
    align-items: center;
    gap: 10px;
    border: 1px solid var(--separator-soft);
    border-radius: 8px;
    padding: 10px 12px;
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
    padding: 0 4px 0 12px;
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
</style>
