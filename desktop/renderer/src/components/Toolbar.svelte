<script lang="ts">
  import Icon from './Icon.svelte';
  import { app, redo, toggleTheme, undo } from '../lib/store.svelte';
  import { formatBytes, formatDuration } from '../lib/time';

  let { engine = $bindable('whisper') }: { engine?: string } = $props();

  // 设置页可以停用引擎；工具栏只显示启用的那几个，引擎变多也不会挤爆。
  const engines = $derived((app.config?.engines ?? []).filter((e) => e.enabled));

  const sub = $derived.by(() => {
    const m = app.media;
    if (!m) return '拖入即用';
    switch (app.view) {
      case 'import':
        return `${formatBytes(m.size)} · ${formatDuration(m.duration)} · ${m.video_codec || '—'}`;
      case 'transcribe':
        return app.job?.status === 'running'
          ? `转写中 ${app.job.percent}%`
          : `${app.cues.length} 条 · 待转写`;
      case 'review':
        return `${app.cues.length} 条 · ${formatDuration(m.duration)}`;
      case 'report':
        return app.report ? `${app.cues.length} 条字幕` : '尚无报告';
      case 'settings':
        return '引擎与模型 · 日志与诊断';
      default:
        return '';
    }
  });
</script>

<header class="toolbar">
  <div class="tb-title" title={app.media?.path ?? ''}>{app.media?.name ?? 'KikuSub'}</div>
  <div class="tb-sub">{sub}</div>
  <div class="tb-sep"></div>

  {#if engines.length}
    <div class="seg">
      {#each engines as e (e.key)}
        <button
          class:on={engine === e.key}
          onclick={() => (engine = e.key)}
          title={e.desc ?? e.description}
        >
          {e.short_label ?? e.label}
        </button>
      {/each}
    </div>
  {:else}
    <button class="btn ghost" onclick={() => (app.view = 'settings')}>
      <Icon name="warn" size={12} />没有启用的引擎
    </button>
  {/if}

  <div class="tb-spacer"></div>

  {#if app.view === 'review'}
    <button
      class="btn icon ghost"
      onclick={undo}
      disabled={!app.canUndo}
      title="撤回（⌘Z）"
    >
      <Icon name="undo" size={14} />
    </button>
    <button
      class="btn icon ghost"
      onclick={redo}
      disabled={!app.canRedo}
      title="重做（⇧⌘Z）"
    >
      <Icon name="redo" size={14} />
    </button>
  {/if}

  <button class="btn icon ghost" onclick={toggleTheme} title="切换外观（⇧⌘A）">
    <Icon name="moon" size={14} />
  </button>
  <button
    class="btn icon ghost"
    onclick={() => (app.inspectorOpen = !app.inspectorOpen)}
    title="显示/隐藏检查器（⌥⌘I）"
    disabled={app.view !== 'review'}
  >
    <Icon name="sidebar" size={14} />
  </button>
</header>

<style>
  .toolbar {
    height: 44px;
    flex: 0 0 44px;
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 0 12px 0 14px;
    border-bottom: 1px solid var(--separator);
    background: var(--bg-toolbar);
    backdrop-filter: saturate(180%) blur(20px);
    -webkit-backdrop-filter: saturate(180%) blur(20px);
    -webkit-app-region: drag;
  }
  .toolbar > * {
    -webkit-app-region: no-drag;
  }

  .tb-title {
    font-size: 13px;
    font-weight: 600;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    max-width: 260px;
  }
  .tb-sub {
    font-size: 11px;
    color: var(--text-3);
    font-variant-numeric: tabular-nums;
    white-space: nowrap;
  }
  .tb-sep {
    width: 1px;
    height: 18px;
    background: var(--separator);
    flex: 0 0 1px;
  }
  .tb-spacer {
    flex: 1;
  }
</style>
