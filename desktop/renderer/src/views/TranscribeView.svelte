<script lang="ts">
  import Icon from '../components/Icon.svelte';
  import { app, cancelJob, startTranscribe } from '../lib/store.svelte';
  import { parseTimeInput } from '../lib/time';

  let { engine = $bindable('whisper') }: { engine?: string } = $props();

  let outputFormat = $state('SRT');
  let startText = $state('');
  let endText = $state('');
  let absolute = $state(true);

  const running = $derived(app.job?.status === 'running' || app.job?.status === 'cancelling');
  const pct = $derived(app.job?.percent ?? 0);

  function go() {
    startTranscribe(
      { engine, outputFormat, startText, endText, absoluteTimeline: absolute },
      parseTimeInput,
    );
  }

  /** 把当前媒体的完整时长填进结束框，省得用户手算。 */
  function fillFull() {
    startText = '0';
    if (app.media) {
      const d = app.media.duration;
      const m = Math.floor(d / 60);
      const s = (d % 60).toFixed(2);
      endText = `${m}:${s.padStart(5, '0')}`;
    }
  }
</script>

<div class="pane">
  <div class="h1">开始转写</div>
  <p class="p">
    {#if app.media}
      当前媒体已就绪。留空时间区间即转写全片。
    {:else}
      还没有导入媒体——先去「导入」挑一个文件。
    {/if}
  </p>

  <div class="form">
    <label for="engine">识别引擎</label>
    <div class="seg" style="justify-self:start">
      {#each app.config?.engines ?? [] as e (e.key)}
        <button class:on={engine === e.key} onclick={() => (engine = e.key)}>{e.label}</button>
      {/each}
    </div>

    <label for="range">时间区间</label>
    <div class="range">
      <div class="field mono" style="width:118px">
        <input id="range" class="mono" bind:value={startText} placeholder="留空 = 片头" />
      </div>
      <span class="dash">–</span>
      <div class="field mono" style="width:118px">
        <input class="mono" bind:value={endText} placeholder="留空 = 片尾" />
      </div>
      <button class="btn ghost" onclick={fillFull} title="填入完整时长">全片</button>
      <label class="check">
        <input type="checkbox" bind:checked={absolute} />
        绝对时间轴
      </label>
    </div>

    <label for="fmt">输出格式</label>
    <div class="seg" style="justify-self:start">
      {#each ['SRT', 'VTT', 'TXT'] as f (f)}
        <button class:on={outputFormat === f} onclick={() => (outputFormat = f)}>{f}</button>
      {/each}
    </div>

    <label for="out">保存位置</label>
    <div class="field" style="max-width:460px">
      <span style="color: var(--text-2)">outputs/</span>
      <span class="out-name">
        {app.media ? app.media.name.replace(/\.[^.]+$/, '') : '—'}_{outputFormat.toLowerCase()}
      </span>
    </div>

    <label></label>
    <div class="actions">
      {#if running}
        <button class="btn danger" onclick={cancelJob}>
          <Icon name="stop" size={12} />中途打断
        </button>
        <span class="hint">同一时间只允许一个重任务</span>
      {:else}
        <button class="btn primary" onclick={go} disabled={!app.media || !app.connected}>
          <Icon name="play" size={12} />开始转写
        </button>
        <span class="hint">⌘R</span>
      {/if}
    </div>
  </div>

  {#if app.job && app.jobKind === 'transcribe'}
    <div class="progress-card">
      <div class="pc-top">
        <div class="pc-stage">{app.job.stage || '准备中…'}</div>
        <div class="pc-pct">{pct}%</div>
      </div>
      <div class="pc-bar"><i style="width:{pct}%"></i></div>
      <div class="pc-meta">
        {#if app.job.status === 'running'}
          <span>已用 {app.job.elapsed?.toFixed?.(1) ?? '0'} s</span>
          <span>引擎 {engine}</span>
        {:else if app.job.status === 'done'}
          <span>完成 · {app.cues.length} 条字幕</span>
        {:else if app.job.status === 'error'}
          <span style="color: #ff453a">{app.job.error}</span>
        {:else}
          <span>{app.job.status}</span>
        {/if}
      </div>
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

  .form {
    display: grid;
    grid-template-columns: 100px 1fr;
    gap: 10px 14px;
    align-items: center;
  }
  label {
    font-size: 12.5px;
    color: var(--text-2);
    text-align: right;
  }

  .range {
    display: flex;
    align-items: center;
    gap: 8px;
  }
  .dash {
    color: var(--text-3);
  }
  .check {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    font-size: 11.5px;
    text-align: left;
    color: var(--text-2);
  }
  .check input {
    margin: 0;
  }

  .out-name {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .actions {
    display: flex;
    gap: 8px;
    align-items: center;
  }
  .hint {
    font-size: 11.5px;
    color: var(--text-3);
  }

  .progress-card {
    margin-top: 22px;
    border: 1px solid var(--separator-soft);
    border-radius: 10px;
    padding: 12px 14px;
  }
  .pc-top {
    display: flex;
    justify-content: space-between;
    align-items: baseline;
    margin-bottom: 8px;
  }
  .pc-stage {
    font-size: 12.5px;
    font-weight: 500;
  }
  .pc-pct {
    font-size: 12px;
    color: var(--text-2);
    font-variant-numeric: tabular-nums;
    font-family: ui-monospace, 'SF Mono', Menlo, monospace;
  }
  .pc-bar {
    height: 5px;
    border-radius: 3px;
    background: var(--fill-strong);
    overflow: hidden;
  }
  .pc-bar > i {
    display: block;
    height: 100%;
    border-radius: 3px;
    background: var(--accent);
    transition: width 300ms var(--ease);
  }
  .pc-meta {
    display: flex;
    gap: 14px;
    margin-top: 8px;
    font-size: 11px;
    color: var(--text-3);
    font-variant-numeric: tabular-nums;
  }
</style>
