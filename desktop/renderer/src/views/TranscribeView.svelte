<script lang="ts">
  import Icon from '../components/Icon.svelte';
  import ParamPanel from '../components/ParamPanel.svelte';
  import {
    app,
    applyPreset,
    cancelJob,
    deletePreset,
    savePresetAs,
    setView,
    startTranscribe,
    tuning,
  } from '../lib/store.svelte';
  import { parseTimeInput } from '../lib/time';

  let { engine = $bindable('whisper') }: { engine?: string } = $props();

  let outputFormat = $state('SRT');
  let startText = $state('');
  let endText = $state('');
  let absolute = $state(true);
  let applyMode = $state<'auto' | 'replace' | 'append'>('auto');
  let presetName = $state('');
  let picked = $state('');

  const running = $derived(
    app.job?.status === 'queued' ||
      app.job?.status === 'running' ||
      app.job?.status === 'cancelling',
  );
  const pct = $derived(app.job?.percent ?? 0);
  const hasEnabledEngine = $derived(
    (app.config?.engines ?? []).some((e) => e.enabled && e.key === engine),
  );

  // 核对台「填入转写」：把框选区间带过来。nonce 变一次填一次，
  // 不能每次渲染都覆盖用户手输的内容。
  let seenSlice = 0;
  $effect(() => {
    const req = app.slice;
    if (!req || req.nonce === seenSlice) return;
    seenSlice = req.nonce;
    startText = req.start;
    endText = req.end;
    applyMode = 'auto';
  });

  // 只列出当前引擎可用的预设
  const presetsForEngine = $derived(
    tuning.presets.filter((p) => !p.engine || p.engine === engine),
  );

  function go() {
    startTranscribe(
      {
        engine,
        outputFormat,
        startText,
        endText,
        absoluteTimeline: absolute,
        apply: applyMode === 'auto' ? undefined : applyMode,
      },
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

  async function onPick(name: string) {
    picked = name;
    if (name) await applyPreset(name);
  }

  async function onSave() {
    await savePresetAs(presetName || picked, engine);
    presetName = '';
  }

  async function onDelete() {
    await deletePreset(picked || tuning.activePreset);
    picked = '';
  }
</script>

<div class="pane">
  <div class="cols">
    <section class="left">
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
        {#if (app.config?.engines ?? []).some((e) => e.enabled)}
          <div class="seg" style="justify-self:start">
            {#each (app.config?.engines ?? []).filter((e) => e.enabled) as e (e.key)}
              <button class:on={engine === e.key} onclick={() => (engine = e.key)}>{e.label}</button>
            {/each}
          </div>
        {:else}
          <div class="no-engine">
            没有启用的引擎。
            <button class="btn tiny" onclick={() => setView('settings')}>去设置里启用</button>
          </div>
        {/if}

        <label for="range">时间区间</label>
        <div class="range">
          <div class="field mono" style="width:104px">
            <input id="range" class="mono" bind:value={startText} placeholder="片头" />
          </div>
          <span class="dash">–</span>
          <div class="field mono" style="width:104px">
            <input class="mono" bind:value={endText} placeholder="片尾" />
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

        <label for="apply">结果处理</label>
        <div class="apply-row">
          <div class="seg">
            <button class:on={applyMode === 'auto'} onclick={() => (applyMode = 'auto')}>自动</button>
            <button class:on={applyMode === 'replace'} onclick={() => (applyMode = 'replace')}>
              覆盖
            </button>
            <button class:on={applyMode === 'append'} onclick={() => (applyMode = 'append')}>
              追加
            </button>
          </div>
          <span class="hint">
            {applyMode === 'auto' ? '整片覆盖核对台，区间去重后追加' : applyMode === 'replace' ? '用本次结果替换整张表' : '与现有时间轴合并去重'}
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
            <button
              class="btn primary"
              onclick={go}
              disabled={!app.media || !app.connected || !hasEnabledEngine}
            >
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
            {#if app.job.status === 'queued'}
              <span>正在唤醒推理内核，通常需要几秒</span>
            {:else if app.job.status === 'running'}
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
    </section>

    <section class="right">
      <div class="preset-bar">
        <span class="pb-label">预设</span>
        <select value={picked} onchange={(e) => onPick(e.currentTarget.value)}>
          <option value="">（未选择）</option>
          {#each presetsForEngine as p (p.name)}
            <option value={p.name}>{p.name}</option>
          {/each}
        </select>
        <div class="field preset-name">
          <input
            bind:value={presetName}
            placeholder="存为新预设…"
            onkeydown={(e) => {
              if (e.key === 'Enter') onSave();
            }}
          />
        </div>
        <button class="btn" onclick={onSave} disabled={!presetName.trim() && !picked}>
          <Icon name="check" size={11} />保存
        </button>
        <button class="btn ghost" onclick={onDelete} disabled={!picked && !tuning.activePreset}>
          <Icon name="trash" size={11} />
        </button>
      </div>

      <ParamPanel {engine} />
    </section>
  </div>
</div>

<style>
  .pane {
    padding: 18px 22px 22px;
    overflow: hidden;
    flex: 1;
    min-height: 0;
    display: flex;
  }

  .cols {
    display: grid;
    grid-template-columns: minmax(300px, 360px) minmax(0, 1fr);
    gap: 26px;
    width: 100%;
    min-height: 0;
  }

  .left {
    overflow-y: auto;
    padding-right: 4px;
  }

  .right {
    display: flex;
    flex-direction: column;
    gap: 12px;
    min-height: 0;
    border-left: 1px solid var(--separator-soft);
    padding-left: 22px;
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
    grid-template-columns: 72px 1fr;
    gap: 10px 12px;
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
    gap: 6px;
    flex-wrap: wrap;
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

  .actions {
    display: flex;
    gap: 8px;
    align-items: center;
  }
  .apply-row {
    display: flex;
    align-items: center;
    gap: 8px;
    flex-wrap: wrap;
  }
  .no-engine {
    font-size: 12px;
    color: var(--text-3);
    display: flex;
    align-items: center;
    gap: 8px;
  }
  .hint {
    font-size: 11.5px;
    color: var(--text-3);
  }

  .progress-card {
    margin-top: 18px;
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

  .preset-bar {
    display: flex;
    align-items: center;
    gap: 6px;
    flex: 0 0 auto;
  }
  .pb-label {
    font-size: 11px;
    font-weight: 600;
    color: var(--text-3);
  }
  .preset-bar select {
    appearance: none;
    height: 26px;
    border-radius: 6px;
    border: 1px solid var(--separator);
    background-color: var(--bg-content);
    color: var(--text);
    font: inherit;
    font-size: 12.5px;
    padding: 0 22px 0 8px;
    max-width: 190px;
    background-image: linear-gradient(45deg, transparent 50%, var(--text-3) 50%),
      linear-gradient(135deg, var(--text-3) 50%, transparent 50%);
    background-position: calc(100% - 12px) 11px, calc(100% - 8px) 11px;
    background-size: 4px 4px, 4px 4px;
    background-repeat: no-repeat;
  }
  .preset-name {
    width: 132px;
    flex: 0 1 132px;
  }
</style>
