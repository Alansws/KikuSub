<script lang="ts">
  /**
   * 底栏：24px，只读状态。
   *
   * 设计约束（DESIGN.md / HIG `windows.md › Desktop (macOS)`）：底栏不放关键动作。
   * 这里只有「引擎是否就绪 / 这份稿有多大 / 这一屏的静态规格 / 任务进度 /
   * 草稿时间 / 质检计数」——全部是读数。暂存、导出、切换都各有自己的位置。
   */
  import Icon from './Icon.svelte';
  import DraftDock from './DraftDock.svelte';
  import { app, qa, toggleQaPanel } from '../lib/store.svelte';
  import { mediaResolution } from '../lib/stagePrefs';

  let { engine = '' }: { engine?: string } = $props();

  const chars = $derived(app.cues.reduce((n, c) => n + c.text.length, 0));
  // 必须跟随标题栏当前选中的引擎：用户切到 Qwen 后这里仍显示 Anime Whisper
  // 会被当成「引擎没切成功」。
  const engineLabel = $derived.by(() => {
    const key = engine || app.engine;
    const found = (app.config?.engines ?? []).find((e) => e.key === key);
    return found?.label ?? (key || '—');
  });
  const pendingQa = $derived<number>(qa.payload?.counts?.pending ?? 0);
  /** 静态媒体规格：分辨率 · fps。 */
  const spec = $derived.by(() => {
    const m = app.media;
    if (!m) return '';
    const parts = [mediaResolution(m)];
    if (m.video_fps && m.video_fps > 0) parts.push(`${m.video_fps.toFixed(3)} fps`);
    return parts.filter(Boolean).join(' · ');
  });
</script>

<footer class="statusbar">
  <span class="st-item">
    <i class="dot" class:off={!app.connected}></i>
    <b>{app.config?.device?.toUpperCase() ?? '—'}</b>
    {app.connected ? '就绪' : '未连接'}
  </span>
  <span class="st-item">{engineLabel}</span>
  {#if app.media}
    <span class="st-item"><b>{app.cues.length}</b> 条 · <b>{chars}</b> 字</span>
    {#if spec}
      <span class="st-item st-spec" title="源视频分辨率 · 帧率">{spec}</span>
    {/if}
  {/if}

  <span class="grow"></span>

  {#if app.view === 'review' && app.cues.length}
    <DraftDock />
    <span class="sb-sep" aria-hidden="true"></span>
  {/if}
  {#if app.job?.status === 'running'}
    <span class="st-item" title="后台任务进度">
      {app.job.kind === 'proxy' ? '压制代理' : app.job.kind === 'export' ? '导出成片' : '转写'}
      {app.job.percent}%
    </span>
  {/if}
  <button class="qa" class:on={qa.open} onclick={() => toggleQaPanel()} title="质检待核队列">
    <Icon name="search" size={11} />
    质检
    {#if pendingQa}
      <b class="count">{pendingQa}</b>
    {/if}
  </button>
</footer>

<style>
  .statusbar {
    height: var(--statusbar-h);
    line-height: 16px;
    flex: 0 0 var(--statusbar-h);
    box-shadow: inset 0 1px 0 var(--line);
    background: var(--bg-status);
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 0 var(--sp-3);
    font-size: 11px;
    color: var(--text-3);
    font-variant-numeric: tabular-nums;
    white-space: nowrap;
    overflow: hidden;
  }
  /* 底栏读数项。**不再叫 .sb-item**（2026-11-25 Step 4.3）：那个类名属于侧栏导航，
     两处同名会让 `document.querySelectorAll('.sb-item')` 把底栏读数一起数进去
     （设置页布局回归按「侧栏最后一项」找入口，于是一直点到「Anime Whisper」）。 */
  .st-item {
    display: inline-flex;
    align-items: center;
    gap: 5px;
  }
  .statusbar .dot {
    margin-right: 0;
  }
  b {
    color: var(--text-2);
    font-weight: 500;
  }
  .grow {
    flex: 1;
  }
  .st-spec {
    color: var(--text-3);
    overflow: hidden;
    text-overflow: ellipsis;
    max-width: 240px;
  }
  .sb-sep {
    width: 1px;
    height: 11px;
    flex: 0 0 1px;
    background: var(--line);
  }
  .qa {
    appearance: none;
    border: 0;
    background: transparent;
    font: inherit;
    font-size: 11px;
    display: inline-flex;
    align-items: center;
    gap: var(--sp-1);
    color: var(--text-3);
    padding: 2px 5px;
    border-radius: 3px;
    height: 18px;
  }
  .qa:hover {
    background: var(--fill);
    color: var(--text-2);
  }
  .qa.on {
    background: var(--accent-soft);
    color: var(--accent-text);
  }
  .count {
    min-width: 15px;
    height: 15px;
    padding: 0 var(--sp-1);
    border-radius: 8px;
    background: var(--accent);
    color: var(--on-accent);
    font-size: 10.5px;
    font-weight: 600;
    display: grid;
    place-items: center;
  }
</style>
