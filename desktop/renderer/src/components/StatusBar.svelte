<script lang="ts">
  import Icon from './Icon.svelte';
  import { app, qa, toggleQaPanel } from '../lib/store.svelte';

  const chars = $derived(app.cues.reduce((n, c) => n + c.text.length, 0));
  const engine = $derived(app.config?.engines?.find((e) => e.key === 'whisper')?.label ?? '—');
  const pendingQa = $derived<number>(qa.payload?.counts?.pending ?? 0);
</script>

<footer class="statusbar">
  <span>
    <i class="dot" class:off={!app.connected}></i>
    <b>{app.config?.device?.toUpperCase() ?? '—'}</b>
    {app.connected ? '加速就绪' : '未连接'}
  </span>
  <span>{engine}</span>
  {#if app.media}
    <span><b>{app.cues.length}</b> 条 · <b>{chars}</b> 字</span>
  {/if}

  <div class="right">
    {#if app.job?.status === 'running'}
      <span>{app.job.kind === 'proxy' ? '压制代理' : '转写'} {app.job.percent}%</span>
    {/if}
    <span class="path">outputs/logs/kikusub.log</span>
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
    height: 26px;
    flex: 0 0 26px;
    border-top: 1px solid var(--separator);
    background: var(--bg-status);
    display: flex;
    align-items: center;
    gap: 14px;
    padding: 0 12px;
    font-size: 11px;
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
    gap: 12px;
    min-width: 0;
  }
  .path {
    overflow: hidden;
    text-overflow: ellipsis;
    max-width: 240px;
  }
  .qa {
    appearance: none;
    border: 0;
    background: transparent;
    font: inherit;
    font-size: 11px;
    display: inline-flex;
    align-items: center;
    gap: 4px;
    color: var(--text-2);
    padding: 2px 6px;
    border-radius: 5px;
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
    min-width: 15px;
    height: 15px;
    padding: 0 4px;
    border-radius: 8px;
    background: var(--accent);
    color: #fff;
    font-size: 10px;
    font-weight: 600;
    display: grid;
    place-items: center;
  }
</style>
