<script lang="ts">
  import Icon from '../components/Icon.svelte';
  import PageHeader from '../components/PageHeader.svelte';
  import ParamPanel from '../components/ParamPanel.svelte';
  import {
    app,
    applyPreset,
    cancelJob,
    deletePreset,
    importSubtitleFromExport,
    importTranslationFromExport,
    savePresetAs,
    setView,
    startTranscribe,
    toast,
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

  const transcribeSub = $derived(
    app.media
      ? '当前媒体已就绪。留空时间区间即转写全片。'
      : '还没有导入媒体——先去「导入」挑一个文件。',
  );

  const running = $derived(
    app.job?.status === 'queued' ||
      app.job?.status === 'running' ||
      app.job?.status === 'cancelling',
  );
  const pct = $derived(app.job?.percent ?? 0);
  const hasEnabledEngine = $derived(
    (app.config?.engines ?? []).some((e) => e.enabled && e.key === engine),
  );
  const enabledEngines = $derived((app.config?.engines ?? []).filter((e) => e.enabled));
  const currentEngine = $derived(enabledEngines.find((e) => e.key === engine) ?? null);

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

  /** 转写线程已经把字幕写到导出文件夹；这里只负责把用户带过去。 */
  function openExportFolder() {
    const dir =
      app.job?.result?.export_dir || app.config?.export_dir || app.config?.output_dir || '';
    if (!dir) {
      toast('还没有可用的导出文件夹，请先到设置里选择', 'warn');
      return;
    }
    void window.kikusub.openPath(dir);
  }

  function revealSaved() {
    if (app.lastSavedPath) window.kikusub.revealInFinder(app.lastSavedPath);
  }
</script>

<div class="pane">
  <PageHeader title="开始转写" subtitle={transcribeSub} />
  <div class="cols">
    <section class="left">
      <div class="form">
        <label for="engine">识别引擎</label>
        {#if enabledEngines.length}
          <!-- 引擎可能到 3–4 个：平铺分段会溢出（4 个中日引擎就放不下），
               表单里改用下拉。顶栏那个胶囊是全局快捷入口，两者绑同一个值。 -->
          <div class="engine-pick">
            <div class="field engine-field">
              <select id="engine" bind:value={engine}>
                {#each enabledEngines as e (e.key)}
                  <option value={e.key}>
                    {e.label}{e.installed ? '' : `（未下载 · ${e.approx_label}）`}
                  </option>
                {/each}
              </select>
              <span class="chev"><Icon name="chevron-down" size={11} /></span>
            </div>
            {#if currentEngine && !currentEngine.installed}
              <span class="engine-hint warn">
                尚未下载 · {currentEngine.approx_label} · 开始转写会先下载
              </span>
            {/if}
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
              class="btn primary lg"
              onclick={go}
              disabled={!app.media || !app.connected || !hasEnabledEngine}
            >
              <Icon name="play" size={12} />开始转写
            </button>
            <span class="hint">
              {app.media ? '结果写入导出文件夹' : '先导入媒体，再开始转写'}
            </span>
          {/if}
        </div>

        <!-- 已有字幕走独立入口：原文轨与译文轨可以分别导入，
             不必为了补一份译文重新跑一次转写。 -->
        <div class="subtitle-imports">
          <span class="si-label">已有字幕</span>
          <div class="si-row">
            <button
              class="si-btn"
              onclick={importSubtitleFromExport}
              disabled={!app.connected || running}
              title="从导出文件夹选择原文字幕，导入核对台（不重新转写）"
            >
              <span class="si-icon"><Icon name="doc" size={13} /></span>
              <span class="si-text"><b>导入原文</b><em>SRT / VTT</em></span>
            </button>
            <button
              class="si-btn"
              onclick={importTranslationFromExport}
              disabled={!app.connected || running || !app.cues.length}
              title={app.cues.length
                ? '选择与当前原文逐条对齐的译文 SRT / VTT，原文与时间轴不动'
                : '先导入原文字幕，再导入译文字幕'}
            >
              <span class="si-icon"><Icon name="quote" size={13} /></span>
              <span class="si-text"><b>导入译文</b><em>逐条对齐</em></span>
            </button>
          </div>
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
              <span style="color: var(--danger)">{app.job.error}</span>
            {:else}
              <span>{app.job.status}</span>
            {/if}
          </div>
          {#if app.job.status === 'done' && app.lastSavedPath}
            <div class="saved-row">
              <span class="saved-ok"><Icon name="check" size={10} />已自动保存</span>
              <span class="saved-path mono" title={app.lastSavedPath}>{app.lastSavedPath}</span>
              <button class="btn tiny ghost" onclick={revealSaved}>在访达中显示</button>
              <button class="btn tiny" onclick={openExportFolder}>
                <Icon name="folder" size={10} />导出文件夹
              </button>
            </div>
          {/if}
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
    padding: var(--sp-8) var(--sp-10) var(--sp-8);
    overflow: hidden;
    flex: 1;
    min-height: 0;
    display: flex;
    flex-direction: column;
  }

  .cols {
    display: grid;
    grid-template-columns: minmax(300px, 360px) minmax(0, 1fr);
    gap: var(--sp-8);
    width: 100%;
    max-width: 1120px;
    margin: 0 auto;
    min-height: 0;
    flex: 1;
  }

  .left {
    overflow-y: auto;
    padding-right: var(--sp-1);
  }

  .right {
    display: flex;
    flex-direction: column;
    gap: var(--sp-3);
    min-height: 0;
    border-left: 1px solid var(--separator-soft);
    padding-left: 22px;
  }

  .engine-pick {
    display: flex;
    align-items: center;
    gap: 10px;
    min-width: 0;
  }
  .engine-field {
    width: 190px;
    position: relative;
    flex: 0 0 auto;
  }
  .engine-field select {
    appearance: none;
    border: 0;
    outline: 0;
    background: transparent;
    color: inherit;
    font: inherit;
    font-size: var(--fs-ui);
    width: 100%;
    padding-right: var(--sp-4);
    cursor: default;
  }
  .engine-field .chev {
    position: absolute;
    right: 8px;
    color: var(--text-3);
    pointer-events: none;
    display: grid;
    place-items: center;
  }
  .engine-hint {
    font-size: 12px;
    color: var(--text-3);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    min-width: 0;
  }
  .engine-hint.warn {
    color: var(--warn);
  }

  .form {
    display: grid;
    grid-template-columns: 72px 1fr;
    gap: 10px var(--sp-3);
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
    font-size: 12px;
    text-align: left;
    color: var(--text-2);
  }
  .check input {
    margin: 0;
  }

  .actions {
    display: flex;
    gap: var(--sp-2);
    align-items: center;
  }
  /* 原文 / 译文导入做成两张小文件卡：比一个“导入字幕…”按钮更明确，
     也不会和主操作「开始转写」抢同一层视觉。 */
  .subtitle-imports {
    grid-column: 1 / -1;
    display: flex;
    gap: var(--sp-3);
    margin-top: 6px;
    align-items: flex-start;
  }
  .si-label {
    flex: 0 0 72px;
    padding-top: var(--sp-3);
    text-align: right;
    font-size: 12.5px;
    color: var(--text-2);
  }
  .si-row {
    flex: 1;
    display: flex;
    gap: var(--sp-2);
    min-width: 0;
  }
  .si-btn {
    flex: 1;
    min-width: 0;
    height: 46px;
    display: flex;
    align-items: center;
    gap: var(--sp-2);
    padding: 0 9px;
    border: 1px solid var(--separator-soft);
    border-radius: 8px;
    background: var(--bg-content);
    color: var(--text);
    font: inherit;
    text-align: left;
    cursor: default;
    transition:
      border-color var(--dur) var(--ease),
      background var(--dur) var(--ease),
      box-shadow var(--dur) var(--ease);
  }
  .si-btn:hover:not(:disabled) {
    border-color: var(--accent-ring);
    background: var(--accent-soft);
    box-shadow: var(--shadow-seg);
  }
  .si-btn:disabled {
    opacity: 0.48;
  }
  .si-icon {
    width: 25px;
    height: 25px;
    flex: 0 0 25px;
    border-radius: 6px;
    background: var(--fill);
    color: var(--text-2);
    display: grid;
    place-items: center;
    transition:
      color var(--dur) var(--ease),
      background var(--dur) var(--ease);
  }
  .si-btn:hover:not(:disabled) .si-icon {
    color: var(--accent);
    background: var(--bg-content);
  }
  .si-text {
    display: flex;
    flex-direction: column;
    gap: 1px;
    min-width: 0;
  }
  .si-text b {
    font-size: 12.5px;
    font-weight: 600;
    line-height: 16px;
    white-space: nowrap;
  }
  .si-text em {
    font-style: normal;
    font-size: 10.5px;
    line-height: 13px;
    color: var(--text-3);
    white-space: nowrap;
  }
  .apply-row {
    display: flex;
    align-items: center;
    gap: var(--sp-2);
    flex-wrap: wrap;
  }
  .no-engine {
    font-size: 12px;
    color: var(--text-3);
    display: flex;
    align-items: center;
    gap: var(--sp-2);
  }
  .hint {
    font-size: 12px;
    color: var(--text-3);
  }

  .btn.lg {
    height: var(--ctl-h-lg);
    padding: 0 14px;
  }

  .progress-card {
    margin-top: 18px;
    border: 1px solid var(--separator-soft);
    border-radius: 8px;
    padding: var(--sp-3) 14px;
  }
  .pc-top {
    display: flex;
    justify-content: space-between;
    align-items: baseline;
    margin-bottom: var(--sp-2);
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
    margin-top: var(--sp-2);
    font-size: 12px;
    color: var(--text-3);
    font-variant-numeric: tabular-nums;
  }

  .saved-row {
    display: flex;
    align-items: center;
    gap: 7px;
    margin-top: 9px;
    padding-top: 9px;
    border-top: 1px solid var(--separator-soft);
    min-width: 0;
  }
  .saved-ok {
    display: inline-flex;
    align-items: center;
    gap: var(--sp-1);
    flex: 0 0 auto;
    font-size: 12px;
    color: var(--success);
  }
  .saved-path {
    flex: 1;
    min-width: 0;
    font-size: 12px;
    color: var(--text-3);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .saved-row .btn {
    flex: 0 0 auto;
  }

  .preset-bar {
    display: flex;
    align-items: center;
    gap: 6px;
    flex: 0 0 auto;
  }
  .pb-label {
    font-size: 12px;
    font-weight: 600;
    color: var(--text-3);
  }
  .preset-bar select {
    appearance: none;
    height: 26px;
    border-radius: 4px;
    border: 1px solid var(--separator);
    background-color: var(--bg-content);
    color: var(--text);
    font: inherit;
    font-size: 12.5px;
    padding: 0 22px 0 var(--sp-2);
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

  /* 紧凑模式（≤900px）：双栏放不下（680 下右栏只剩 200px，标签会竖排），
     改成单栏上下排，整页滚动；右栏的分隔线从左边改成上边。 */
  @media (max-width: 900px) {
    .pane {
      overflow-y: auto;
      padding: var(--sp-5) var(--sp-4) var(--sp-6);
    }
    .cols {
      grid-template-columns: minmax(0, 1fr);
      gap: var(--sp-5);
      flex: 0 0 auto;
    }
    .left {
      overflow: visible;
      padding-right: 0;
    }
    .right {
      border-left: 0;
      border-top: 1px solid var(--separator-soft);
      padding-left: 0;
      padding-top: var(--sp-4);
    }
    .form {
      grid-template-columns: 64px minmax(0, 1fr);
    }
    .si-label {
      flex-basis: 64px;
    }
    .preset-bar {
      flex-wrap: wrap;
    }
    .preset-bar select {
      flex: 1 1 120px;
      max-width: none;
    }
    .preset-name {
      flex: 1 1 120px;
      width: auto;
    }
  }
</style>
