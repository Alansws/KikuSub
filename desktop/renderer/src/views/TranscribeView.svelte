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
  import {
    type ApplyMode,
    applyChoices,
    applyHint,
    confirmDestructiveText,
    isDestructiveChoice,
    needsAbsoluteTimeline,
    resolveApplyChoice,
  } from '../lib/applyMode';
  import { altEngineLabel, deleteAltReview, dual, refreshAltReview } from '../lib/dualReview.svelte';
  import { type AlignStats, alignDoneText } from '../lib/transcribeJob';
  import { takeSlice } from '../lib/transcribeSlice';
  import { parseTimeInput } from '../lib/time';
  import { vocalSeparation } from '../lib/vocalSeparation.svelte';

  let { engine = $bindable('whisper') }: { engine?: string } = $props();

  let outputFormat = $state('SRT');
  let startText = $state('');
  let endText = $state('');
  let absolute = $state(true);
  /**
   * 「结果处理」不再是 自动/覆盖/追加 三选一：没有「自动」这一档，档位按
   * 「这次是不是整片」变（区间多一档「替换选区」），默认值永远是不破坏已有
   * 字幕的那个。判断与文案都在 `lib/applyMode.ts`，这里只存用户的选择。
   */
  let applyMode = $state<ApplyMode>('replace_range');
  let presetName = $state('');
  let picked = $state('');
  /** 核对台非空时的整片结果去向：覆盖第一版 / 放进第二列。 */
  let destination = $state<'cover' | 'alt'>('cover');
  let lastDestKey = '';

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
  const primaryEngine = $derived(String(app.reviewSource?.engine ?? ''));
  /** 空区间或区间已覆盖整片：只有整片转写才允许写第二列。 */
  const fullCover = $derived.by(() => {
    const start = parseTimeInput(startText);
    const end = parseTimeInput(endText);
    const duration = app.media?.duration || 0;
    const startCovers = start === null || start <= 0.001;
    const endCovers = end === null || end >= duration - 0.5;
    return startCovers && endCovers;
  });
  /** 「结果处理」的档位表：整片两档，区间三档（见 lib/applyMode.ts 的文件头）。 */
  const applyCtx = $derived({ fullCover, start: startText, end: endText });
  const applyOptions = $derived(applyChoices(applyCtx));
  /** 档位在当前范围下不成立时（如整片下的「替换选区」）退回该范围的默认档。 */
  const effectiveApply = $derived(resolveApplyChoice(applyMode, applyCtx));
  const applyHintText = $derived(applyHint(effectiveApply, applyCtx));
  const destructive = $derived(isDestructiveChoice(effectiveApply, applyCtx));
  /** 「替换选区」必须走原片绝对时间轴，否则新区间字幕会落到片头（见 applyMode.ts）。 */
  const absoluteLocked = $derived(needsAbsoluteTimeline(effectiveApply));
  const effectiveAbsolute = $derived(absoluteLocked ? true : absolute);
  const canChooseDest = $derived(app.cues.length > 0 && fullCover && effectiveApply !== 'append');
  /**
   * 人声分离对整片 / 区间都生效：知道总时长（有媒体）或填了完整区间就能勾。
   * 整片由服务端按 0..总时长分离；长片会自动分段，不再拦截。
   */
  const canSeparate = $derived.by(() => {
    const start = parseTimeInput(startText);
    const end = parseTimeInput(endText);
    if (start !== null && end !== null && end > start + 0.2) return true;
    return (app.media?.duration || 0) > 0;
  });

  // 核对台「同步到转写页」：把框选/⇧ 连选的区间带过来。
  // **必须消费式读取**：`App.svelte` 用 `{#key app.view}` 重建视图，组件内的
  // nonce 守卫会跟着归零；只靠它的话，整片转完自动跳核对台、再回转写页时，
  // 旧区间会从 `app.slice` 里复活，输入框显示区间而实际提交的是整片（用户报障）。
  // 带过来时把「结果处理」定到「替换选区」：用户同步一个区间过来，意图就是重做
  // 这一段（40:20–44:25 的歌词段换引擎重听），不是把整张表冲掉。
  $effect(() => {
    const req = takeSlice(app);
    if (!req) return;
    startText = req.start;
    endText = req.end;
    applyMode = 'replace_range';
  });

  // 默认去向：引擎不同 → 第二列；引擎相同（含主稿来源未知）→ 覆盖。
  // 用户手动切换后，只有“换引擎”才重新套默认，不会在点按钮时被覆盖。
  $effect(() => {
    const key = `${app.media?.id ?? ''}:${engine}:${primaryEngine}`;
    if (!app.cues.length) {
      lastDestKey = key;
      return;
    }
    if (lastDestKey === key) return;
    lastDestKey = key;
    destination = primaryEngine && primaryEngine !== engine ? 'alt' : 'cover';
  });

  // 当前媒体如果有第二版，转写页也要能看见并清理。
  $effect(() => {
    void app.connected;
    void app.media?.id;
    if (app.connected) void refreshAltReview();
  });

  // 只列出与当前引擎绑定的预设；未绑定/别的引擎的一律不显示，免得选错。
  const presetsForEngine = $derived(
    tuning.presets.filter((p) => p.engine === engine),
  );
  /** 当前引擎自己的「已载入预设」；切引擎后不能把上一个引擎的预设当成可删对象。 */
  const deletablePreset = $derived(
    picked || (tuning.activePresetEngine === engine ? tuning.activePreset : ''),
  );

  // 换引擎时清掉上一套引擎的选中项；参数面板本身按引擎分开存，不互相污染。
  let lastPresetEngine = engine;
  $effect(() => {
    if (lastPresetEngine === engine) return;
    lastPresetEngine = engine;
    picked = '';
    if (tuning.activePresetEngine && tuning.activePresetEngine !== engine) {
      tuning.activePreset = '';
      tuning.activePresetEngine = '';
    }
  });

  function go() {
    // 区间任务里选「覆盖整片」会清掉区间外的全部字幕。这是用户报障过的那个坑
    // （选覆盖 → 整张表只剩选区结果），破坏性动作必须显式确认一次。
    if (destructive && app.cues.length > 0) {
      if (!window.confirm(confirmDestructiveText(applyCtx))) return;
    }
    startTranscribe(
      {
        engine,
        outputFormat,
        startText,
        endText,
        // 「替换选区」由 applyMode.ts 强制原片绝对时间轴：相对时间轴会让新区间
        // 的字幕从 0 秒起编号，结果是选区旧句被删、新句子插到片头。
        absoluteTimeline: effectiveAbsolute,
        apply: effectiveApply,
        altReview: destination === 'alt' && fullCover,
      },
      parseTimeInput,
    );
  }

  /**
   * 「全片」= 不限制区间：清空起止输入与待填选区。
   * 不再把 0–片尾填进两个框——那会让整片任务带上 `_00m00s-...s` 的区间后缀，
   * 也会让「输入框里有时间」和「实际按整片转写」看起来互相矛盾。
   */
  function clearRange() {
    startText = '';
    endText = '';
    app.slice = null;
  }

  /** 本次任务提交时锁定的范围（来自 jobMeta，不跟随输入框，避免显示与执行不一致）。 */
  const jobScopeText = $derived.by(() => {
    const meta = app.jobMeta;
    if (!meta) return '';
    return meta.scope === 'full' ? '整片' : meta.label;
  });

  /**
   * Qwen 的 CTC 对齐说明。非 CTC 引擎（关闭 CTC 的 Whisper、中文引擎）不显示，
   * 更不会出现 `0/0` 的汇总行。
   */
  const alignNote = $derived(
    alignDoneText(
      (app.job?.result?.align_stats ?? null) as AlignStats | null,
      String(
        app.job?.result?.report?.quality?.engine_family ??
          app.report?.quality?.engine_family ??
          '',
      ),
    ),
  );

  async function onPick(name: string) {
    picked = name;
    if (!name) return;
    const ok = await applyPreset(name, engine);
    if (!ok) picked = '';
  }

  async function onSave() {
    await savePresetAs(presetName || picked, engine);
    presetName = '';
  }

  async function onDelete() {
    const target = deletablePreset;
    if (!target) return;
    await deletePreset(target);
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
          <button class="btn ghost" onclick={clearRange} title="清空起止时间 = 转写整片（不写区间后缀）">
            全片
          </button>
          <label
            class="check"
            title={absoluteLocked
              ? '「替换选区」必须用原片绝对时间轴：相对时间轴会让新区间的字幕从 0 秒开始编号，插入位置就错了'
              : '用原片时间轴编号，而不是从区间起点重新计时'}
          >
            <input
              type="checkbox"
              checked={effectiveAbsolute}
              disabled={absoluteLocked}
              onchange={(e) => (absolute = e.currentTarget.checked)}
            />
            绝对时间轴
          </label>
        </div>

        <label>人声分离</label>
        <div class="sep-row">
          <label
            class="check"
            title="对整片或已填写的起止区间做 Demucs 人声分离；首次会下载约 80MB 权重，结果会缓存，换引擎重转可复用。长片自动分段分离，单次长度不再设上限，代价是耗时随长度增长"
          >
            <input
              id="sep"
              type="checkbox"
              bind:checked={vocalSeparation.enabled}
              disabled={!canSeparate}
            />
            强 BGM / 歌曲
          </label>
          <span class="hint">
            {#if !canSeparate}
              先导入媒体或填写起止时间
            {:else if fullCover}
              整片先分离人声再识别（长片自动分段）
            {:else}
              先分离区间人声再识别；换引擎重转复用缓存
            {/if}
          </span>
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
            {#each applyOptions as opt (opt.key)}
              <button
                class:on={effectiveApply === opt.key}
                class:danger-opt={opt.key === 'replace' && !fullCover}
                onclick={() => (applyMode = opt.key)}
                title={applyHint(opt.key, applyCtx)}
              >
                {opt.label}
              </button>
            {/each}
          </div>
          <span class="hint" class:warn-hint={destructive}>{applyHintText}</span>
        </div>

        {#if canChooseDest}
          <label>结果去向</label>
          <div class="dest">
            <div class="seg">
              <button class:on={destination === 'cover'} onclick={() => (destination = 'cover')}>
                覆盖核对台
              </button>
              <button class:on={destination === 'alt'} onclick={() => (destination = 'alt')}>
                放进双引擎复核
              </button>
            </div>
            <span class="hint">
              {destination === 'alt'
                ? '第二版只进参考列，核对台一个字都不改'
                : '本次整片结果替换当前核对台'}
            </span>
          </div>
          {#if dual.exists}
            <label></label>
            <div class="alt-state">
              <span class="alt-label">已有第二版</span>
              <b>{altEngineLabel()} · {dual.count} 条</b>
              <button class="btn tiny" onclick={() => setView('dual')}>查看对照</button>
              <button
                class="btn tiny ghost"
                onclick={async () => {
                  if (window.confirm('删除当前第二版？核对台不受影响。')) {
                    await deleteAltReview();
                  }
                }}
              >
                删除
              </button>
            </div>
          {/if}
        {/if}

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
            {#if jobScopeText}
              <span title="本次任务提交时锁定的范围，不随输入框变化">本次任务：{jobScopeText}</span>
            {/if}
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
          {#if app.job.status === 'done' && alignNote}
            <div class="pc-note">
              <span>{alignNote}</span>
              {#if app.report?.job_id === app.job.id}
                <button class="btn tiny ghost" onclick={() => setView('report')}>对齐明细</button>
              {/if}
            </div>
          {/if}
          {#if app.job.status === 'done' && app.job.result?.alt_review}
            <div class="alt-done">
              <span class="saved-ok"><Icon name="check" size={10} />已放进双引擎复核</span>
              <span class="saved-path">
                第二引擎 {app.job.result?.alt_engine || engine} · {app.job.result?.alt_count ?? 0} 条；
                核对台未改动
              </span>
              <button class="btn tiny" onclick={() => setView('dual')}>打开双引擎复核</button>
            </div>
          {/if}
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
        <select
          value={picked}
          title="只显示与当前识别引擎绑定的预设"
          onchange={(e) => onPick(e.currentTarget.value)}
        >
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
        <button class="btn ghost" onclick={onDelete} disabled={!deletablePreset}>
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
    /* 左栏原来 360px：区间行 + 结果处理提示会横向被切。这里把宽屏下原本空着的
       左侧留白收进内容区（max-width 1120 → 1280），并给左栏 440px；右栏仍可伸缩。 */
    grid-template-columns: minmax(360px, 440px) minmax(0, 1fr);
    gap: var(--sp-8);
    width: 100%;
    max-width: 1280px;
    margin: 0 auto;
    min-height: 0;
    flex: 1;
  }

  .left {
    overflow-y: auto;
    min-width: 0;
    padding-right: var(--sp-1);
  }

  .right {
    display: flex;
    flex-direction: column;
    gap: var(--sp-3);
    min-width: 0;
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
  .sep-row {
    display: flex;
    align-items: center;
    gap: var(--sp-2);
    flex-wrap: wrap;
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
  .apply-row,
  .dest {
    display: flex;
    align-items: center;
    gap: var(--sp-2);
    flex-wrap: wrap;
  }
  /* 提示文字是 flex 子项：不给 min-width:0 时它会按整句宽度把左栏顶出可视区。 */
  .apply-row .hint,
  .dest .hint {
    flex: 1 1 140px;
    min-width: 0;
    overflow-wrap: anywhere;
  }
  /* 「覆盖整片」在区间任务里是唯一会丢数据的档位：靠令牌给一点警示色，
     让它在被点之前就与另外两档区分开（点下去还有一次确认）。 */
  .seg button.danger-opt,
  .seg button.danger-opt.on {
    color: var(--warn);
  }
  .apply-row .hint.warn-hint {
    color: var(--warn);
  }
  .alt-state {
    display: flex;
    align-items: center;
    gap: 7px;
    font-size: 12px;
    color: var(--text-2);
  }
  .alt-label {
    color: var(--text-3);
    white-space: nowrap;
  }
  .alt-state b {
    color: var(--accent);
    font-weight: 500;
    white-space: nowrap;
  }
  .alt-done {
    display: flex;
    align-items: center;
    gap: 7px;
    margin-top: 9px;
    padding-top: 9px;
    border-top: 1px solid var(--separator-soft);
    min-width: 0;
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

  /* 对齐说明：一句话解释 230/257 的口径，右侧给一个进报告页的入口。 */
  .pc-note {
    display: flex;
    align-items: flex-start;
    gap: var(--sp-2);
    margin-top: var(--sp-2);
    font-size: 12px;
    line-height: 1.5;
    color: var(--text-3);
  }

  .pc-note .btn {
    flex: 0 0 auto;
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
