<script lang="ts">
  import Icon from './Icon.svelte';
  import { app, setView, type View } from '../lib/store.svelte';

  const items: { view: View; icon: string; label: string }[] = [
    { view: 'import', icon: 'tray', label: '导入' },
    { view: 'transcribe', icon: 'wave', label: '转写' },
    { view: 'review', icon: 'listcheck', label: '核对' },
    { view: 'report', icon: 'doc', label: '报告' },
  ];
</script>

<aside class="sidebar">
  <div class="sb-label">工作区</div>

  {#each items as item (item.view)}
    <button
      class="sb-item"
      class:active={app.view === item.view}
      onclick={() => setView(item.view)}
      title={item.label}
    >
      <span class="ico"><Icon name={item.icon} /></span>
      <span>{item.label}</span>
      {#if item.view === 'review' && app.cues.length}
        <span class="sb-count">{app.cues.length}</span>
      {/if}
    </button>
  {/each}

  <div class="sb-spacer"></div>

  <div class="sb-env">
    <div class="row">
      <span><i class="dot" class:off={!app.connected}></i>设备</span>
      <b>{app.config?.device?.toUpperCase() ?? '—'}</b>
    </div>
    <div class="row"><span>引擎</span><b>{app.config?.engines?.[0]?.label ?? '—'}</b></div>
    <div class="row">
      <span>状态</span>
      <b>{app.connected ? '就绪' : app.connecting ? '连接中' : '未连接'}</b>
    </div>
  </div>

  <button class="sb-item" onclick={() => (app.view = 'report')} title="设置（待实现）">
    <span class="ico"><Icon name="gear" /></span>
    <span>设置</span>
  </button>
</aside>

<style>
  .sb-label {
    font-size: 11px;
    font-weight: 600;
    color: var(--text-3);
    padding: 10px 8px 4px;
    letter-spacing: 0.01em;
  }

  .sb-item {
    appearance: none;
    border: 0;
    background: transparent;
    height: 28px;
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 0 8px;
    border-radius: 6px;
    color: var(--text);
    font: inherit;
    font-size: 13px;
    text-align: left;
    transition: background var(--dur) var(--ease);
    width: 100%;
  }
  .sb-item:hover {
    background: var(--fill);
  }
  .sb-item.active {
    background: var(--accent-soft);
    color: var(--accent);
    font-weight: 500;
  }
  .sb-item.active .ico {
    color: var(--accent);
  }
  .ico {
    width: 16px;
    height: 16px;
    flex: 0 0 16px;
    color: var(--text-2);
    display: grid;
    place-items: center;
  }

  .sb-count {
    margin-left: auto;
    font-size: 10.5px;
    color: var(--text-3);
    font-variant-numeric: tabular-nums;
  }
  .sb-item.active .sb-count {
    color: var(--accent);
  }

  .sb-spacer {
    flex: 1;
  }

  .sb-env {
    margin: 6px 4px 4px;
    padding: 8px 9px;
    border-radius: 8px;
    background: var(--fill);
    display: flex;
    flex-direction: column;
    gap: 5px;
  }
  .sb-env .row {
    display: flex;
    justify-content: space-between;
    align-items: baseline;
    font-size: 11px;
    color: var(--text-2);
  }
  .sb-env b {
    font-weight: 500;
    color: var(--text);
    font-size: 11px;
    font-variant-numeric: tabular-nums;
  }
</style>
