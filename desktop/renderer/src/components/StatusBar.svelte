<script lang="ts">
  import Icon from './Icon.svelte';
  import { app, qa, toggleQaPanel } from '../lib/store.svelte';

  let { engine = '' }: { engine?: string } = $props();

  const chars = $derived(app.cues.reduce((n, c) => n + c.text.length, 0));
  // 必须跟随顶栏当前选中的引擎，不能写死 whisper：用户切到 Qwen 后这里仍显示
  // Anime Whisper 会被当成“引擎没切成功”。
  const engineLabel = $derived.by(() => {
    const key = engine || app.engine;
    const found = (app.config?.engines ?? []).find((e) => e.key === key);
    return found?.label ?? (key || '—');
  });
  const pendingQa = $derived<number>(qa.payload?.counts?.pending ?? 0);
</script>

<footer class="statusbar">
  <span>
    <i class="dot" class:off={!app.connected}></i>
    <b>{app.config?.device?.toUpperCase() ?? '—'}</b>
    {app.connected ? '加速就绪' : '未连接'}
  </span>
  <span title="当前识别引擎">{engineLabel}</span>
  {#if app.media}
    <span><b>{app.cues.length}</b> 条 · <b>{chars}</b> 字</span>
  {/if}

  <div class="right">
    {#if app.job?.status === 'running'}
      <span>{app.job.kind === 'proxy' ? '压制代理' : app.job.kind === 'export' ? '导出成片' : '转写'} {app.job.percent}%</span>
    {/if}
    <button class="qa" class:on={qa.open} onclick={() => toggleQaPanel()} title="质检待核队列">
      <Icon name="search" size={11} />
      质检
      {#if pendingQa}
        <b class="count">{pendingQa}</b>
      {/if}
    </button>
  </div>
</footer>

<style>
  .statusbar {
    height: 28px;
    line-height: 16px;
    flex: 0 0 28px;
    box-shadow: inset 0 1px 0 var(--separator);
    background: var(--bg-status);
    display: flex;
    align-items: center;
    gap: 14px;
    padding: 0 14px;
    font-size: 12px;
    color: var(--text-3);
    font-variant-numeric: tabular-nums;
    white-space: nowrap;
    overflow: hidden;
  }
  b {
    color: var(--text-2);
    font-weight: 500;
  }
  .right {
    margin-left: auto;
    display: flex;
    align-items: center;
    gap: var(--sp-3);
    min-width: 0;
  }
  .qa {
    appearance: none;
    border: 0;
    background: transparent;
    font: inherit;
    font-size: 12px;
    display: inline-flex;
    align-items: center;
    gap: var(--sp-1);
    color: var(--text-2);
    padding: 2px 6px;
    border-radius: 4px;
    height: 20px;
  }
  .qa:hover {
    background: var(--fill);
  }
  .qa.on {
    background: var(--accent-soft);
    color: var(--accent);
  }
  .count {
    min-width: 16px;
    height: 16px;
    padding: 0 var(--sp-1);
    border-radius: 8px;
    background: var(--accent);
    color: var(--on-accent);
    font-size: 12px;
    font-weight: 600;
    display: grid;
    place-items: center;
  }
</style>
