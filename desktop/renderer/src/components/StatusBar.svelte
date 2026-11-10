<script lang="ts">
  import Icon from './Icon.svelte';
  import { app } from '../lib/store.svelte';

  const chars = $derived(app.cues.reduce((n, c) => n + c.text.length, 0));
  const engine = $derived(app.config?.engines?.find((e) => e.key === 'whisper')?.label ?? '—');
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
    <span class="qa" title="质检队列（待实现展开面板）">
      <Icon name="search" size={11} />
      质检
      {#if app.report?.quality?.suspect}
        <b class="count">{app.report.quality.suspect}</b>
      {/if}
    </span>
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
    display: inline-flex;
    align-items: center;
    gap: 4px;
    color: var(--text-2);
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
