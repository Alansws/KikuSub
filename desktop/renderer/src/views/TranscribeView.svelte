<script lang="ts">
  import Icon from '../components/Icon.svelte';
  import PageHeader from '../components/PageHeader.svelte';
  import EngineChoiceCards from '../components/transcribe/EngineChoiceCards.svelte';
  import ExpertParamsDrawer from '../components/transcribe/ExpertParamsDrawer.svelte';
  import {
    app,
    cancelJob,
    importSubtitleFromExport,
    importTranslationFromExport,
    setView,
    startTranscribe,
    toast,
  } from '../lib/store.svelte';
  import {
    type ApplyMode,
    applyChoices,
    applyHint,
    confirmDestructiveText,
    dualChoices,
    isDestructiveChoice,
    needsAbsoluteTimeline,
    resolveApplyChoice,
    resolveDualApply,
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
  /**
   * 主区只保留 3 个场景开关。区间输入藏在「仅转写指定片段」后面，
   * 不勾选时等同于整片；从核对台同步区间过来会自动展开并勾上。
   */
  let clipOnly = $state(false);
  let absolute = $state(true);
  /**
   * 「结果处理」不再是 自动/覆盖/追加 三选一：没有「自动」这一档，档位按
   * 「这次是不是整片」变（区间多一档「替换选区」），默认值永远是不破坏已有
   * 字幕的那个。判断与文案都在 `lib/applyMode.ts`，这里只存用户的选择。
   */
  let applyMode = $state<ApplyMode>('replace_range');
  /** 核对台非空时的整片结果去向：覆盖第一版 / 放进第二列。 */
  let destination = $state<'cover' | 'alt'>('cover');
  let lastDestKey = '';
  /** 双引擎顺序协同：第三方目的地；与「结果去向」互斥。 */
  let dualMode = $state(false);
  let secondaryEngine = $state('');

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
  /**
   * 双引擎协同没有「追加」（服务端 422）：主稿 + 第二列不是一张能合并的表。
   * 档位在这里过滤，`effectiveApply` 再把残留的 append 退回该范围的默认档。
   */
  const applyOptions = $derived(dualMode ? dualChoices(applyCtx) : applyChoices(applyCtx));
  const effectiveApply = $derived(
    dualMode ? resolveDualApply(applyMode, applyCtx) : resolveApplyChoice(applyMode, applyCtx),
  );
  const applyHintText = $derived(applyHint(effectiveApply, applyCtx));
  const destructive = $derived(isDestructiveChoice(effectiveApply, applyCtx));
  /** 「替换选区」必须走原片绝对时间轴，否则新区间字幕会落到片头（见 applyMode.ts）。 */
  const absoluteLocked = $derived(needsAbsoluteTimeline(effectiveApply));
  const effectiveAbsolute = $derived(absoluteLocked ? true : absolute);
  const canChooseDest = $derived(app.cues.length > 0 && fullCover && effectiveApply !== 'append');
  /** 可配对的副引擎：另一个已启用的日语 Whisper/Qwen。 */
  const dualCandidates = $derived(
    (app.config?.engines ?? []).filter(
      (item) =>
        item.enabled &&
        item.key !== engine &&
        (item.family === 'whisper' || item.family === 'qwen'),
    ),
  );
  const defaultSecondary = $derived.by(() => {
    const preferred = engine === 'qwen' ? 'whisper' : 'qwen';
    return (
      dualCandidates.find((item) => item.key === preferred)?.key ??
      dualCandidates[0]?.key ??
      ''
    );
  });
  /** 双引擎面板里显示的配对：主引擎名 → 副引擎名。 */
  const secondaryLabel = $derived(
    dualCandidates.find((item) => item.key === secondaryEngine)?.label ?? secondaryEngine,
  );
  const primaryLabel = $derived(currentEngine?.label ?? engine);
  $effect(() => {
    if (!dualMode) return;
    if (!dualCandidates.some((item) => item.key === secondaryEngine)) {
      secondaryEngine = defaultSecondary;
    }
  });
  // 切到只剩一个日语引擎时，不能把「双引擎」留在一个没有副引擎的非法状态。
  $effect(() => {
    if (dualMode && !dualCandidates.length) dualMode = false;
  });
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
    clipOnly = true;
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

  function go() {
    // 区间任务里选「覆盖整片」会清掉区间外的全部字幕。这是用户报障过的那个坑
    // （选覆盖 → 整张表只剩选区结果），破坏性动作必须显式确认一次。
    if (destructive && app.cues.length > 0) {
      if (!window.confirm(confirmDestructiveText(applyCtx))) return;
    }
    if (dualMode && !secondaryEngine) {
      toast('请选择副引擎', 'warn');
      return;
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
        altReview: !dualMode && destination === 'alt' && fullCover,
        dualEngine: dualMode ? secondaryEngine : undefined,
      },
      parseTimeInput,
    );
  }

  /** 交换主副：主引擎在「识别引擎」卡里，副引擎是本卡片的选择；交换要两边一起换。 */
  function swapRoles() {
    if (!secondaryEngine || secondaryEngine === engine) return;
    const oldPrimaryKey = engine;
    const oldPrimaryLabel = primaryLabel;
    const oldSecondaryLabel = secondaryLabel;
    engine = secondaryEngine;
    secondaryEngine = oldPrimaryKey;
    toast(`已交换：${oldSecondaryLabel} 为主，${oldPrimaryLabel} 为副`, 'info');
  }

  /** 「仅转写指定片段」开关：关掉就是整片，清空起止与待填选区。 */
  function setClipOnly(on: boolean) {
    clipOnly = on;
    if (!on) clearRange();
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
    clipOnly = false;
  }

  /** 双引擎开关：只允许在确实存在可配对副引擎时打开。 */
  function setDualMode(on: boolean) {
    if (on && !dualCandidates.length) return;
    dualMode = on;
    if (!on) return;
    destination = 'cover';
    // 双引擎没有「追加」；用户若停在追加档，切过来立刻落到合法档。
    applyMode = resolveDualApply(applyMode, applyCtx);
    if (!secondaryEngine) secondaryEngine = defaultSecondary;
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
  <div class="main-scroll">
    <div class="main-col">
      <!-- 1) 选口径：两个日语主力用卡片讲清楚差别；中文引擎只要启用就保留入口。 -->
      <section class="card">
        <div class="card-head">
          <div class="card-copy">
            <div class="card-title">识别引擎</div>
            <p class="card-sub">按这次的素材选口径；与顶栏引擎胶囊共用同一个值，不需要两处各选一次。</p>
          </div>
          {#if currentEngine}
            <span class="engine-state" class:ready={currentEngine.installed}>
              <span class="state-dot" class:ready={currentEngine.installed}></span>
              {currentEngine.installed ? '当前引擎已就绪' : `未下载 · ${currentEngine.approx_label}`}
            </span>
          {/if}
        </div>

        <EngineChoiceCards bind:engine engines={enabledEngines} onmanage={() => setView('settings')} />

        {#if currentEngine && !currentEngine.installed}
          <p class="hint warn">
            首次使用会先下载 {currentEngine.approx_label}；下载完成后自动开始，期间可以取消。
          </p>
        {/if}
      </section>

      <!-- 2) 只留三个场景开关：强 BGM、只转片段、双引擎协同。 -->
      <section class="card">
        <div class="card-head">
          <div class="card-copy">
            <div class="card-title">这次怎么转</div>
            <p class="card-sub">只保留会影响结果的三个场景开关；其余声学参数在页面底部的专家抽屉里。</p>
          </div>
        </div>

        <div class="switch-grid">
          <label
            class="switch-card"
            class:disabled={!canSeparate}
            title="对整片或已填写的起止区间做 Demucs 人声分离；首次会下载约 80MB 权重，结果会缓存，换引擎重转可复用。"
          >
            <input
              type="checkbox"
              bind:checked={vocalSeparation.enabled}
              disabled={!canSeparate}
            />
            <span class="sw-copy">
              <b>强 BGM / 歌曲人声分离</b>
              <small>先把歌声与伴奏分开，再切分/识别；适合音乐盖过人声的段落。</small>
            </span>
          </label>

          <label class="switch-card" title="只转写一段起止时间；不勾选就是整片">
            <input
              type="checkbox"
              checked={clipOnly}
              onchange={(e) => setClipOnly(e.currentTarget.checked)}
            />
            <span class="sw-copy">
              <b>仅转写指定片段</b>
              <small>填起止时间只处理这一段；留空任一端按片头 / 片尾算。</small>
            </span>
          </label>

          <label
            class="switch-card"
            class:disabled={!dualCandidates.length}
            title={dualCandidates.length
              ? '两遍顺序执行，切换前会释放上一个引擎（需 12GB 以上内存）；副稿只读进第二列。'
              : '需要再启用一个日语引擎才能双引擎协同'}
          >
            <input
              type="checkbox"
              checked={dualMode}
              disabled={!dualCandidates.length}
              onchange={(e) => setDualMode(e.currentTarget.checked)}
            />
            <span class="sw-copy">
              <b>双引擎顺序协同</b>
              <small>{dualCandidates.length
                ? '再顺序跑一个副引擎，生成只读对照（≥12GB 内存）。'
                : '需要另启一个日语引擎；去设置里启用。'}</small>
            </span>
          </label>
        </div>

        {#if clipOnly}
          <div class="detail">
            <span class="detail-label">起止时间</span>
            <div class="range-row">
              <div class="field mono time-field">
                <input class="mono" bind:value={startText} placeholder="片头" aria-label="起始时间" />
              </div>
              <span class="dash">–</span>
              <div class="field mono time-field">
                <input class="mono" bind:value={endText} placeholder="片尾" aria-label="结束时间" />
              </div>
              <button class="btn ghost" type="button" onclick={clearRange} title="清空起止时间 = 转写整片">
                回到整片
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
          </div>
          <p class="hint">留空任一端 = 该端按片头 / 片尾；「回到整片」会清空输入与待填选区。</p>
        {/if}

        {#if vocalSeparation.enabled}
          <div class="detail">
            <span class="detail-label">分离用途</span>
            <div class="seg mode-seg" role="group" aria-label="人声分离用途">
              <button
                type="button"
                class:on={vocalSeparation.mode === 'vad_only'}
                onclick={() => (vocalSeparation.mode = 'vad_only')}
                title="分离人声只用于 VAD 切分，识别仍听原声：不会被削掉日语清辅音"
              >
                仅用于 VAD 切分（推荐）
              </button>
              <button
                type="button"
                class:on={vocalSeparation.mode === 'to_asr'}
                onclick={() => (vocalSeparation.mode = 'to_asr')}
                title="高级：分离人声直接送识别。只在人声被纯歌声/极重混响彻底盖死时用"
              >
                分离人声后送识别
              </button>
            </div>
          </div>
          <p class="hint">
            {vocalSeparation.mode === 'vad_only'
              ? '切分看干净人声、识别听原声——保住日语清辅音细节，只从更准的边界获益。'
              : '分离人声直接送识别，适合人声被纯歌声/极重混响彻底盖死的段落；代价是清辅音可能被一起削掉，建议先只试这一小段。'}
          </p>
        {:else if !canSeparate}
          <p class="hint">先导入媒体或填写起止时间，才能开启分离。</p>
        {/if}

        {#if dualMode}
          <!-- 流向固定：主稿写核对台，副稿只读进第二列并把补漏候选送质检。
               结果去向那档选择因此被收起，避免用户以为还能改。 -->
          <div class="duo">
            <div class="duo-row">
              <span class="duo-role">主引擎</span>
              <b class="duo-name">{primaryLabel}</b>
              <span class="duo-arrow" aria-hidden="true">→</span>
              <span class="duo-dest">写入核对台（主稿）</span>
            </div>
            <div class="duo-row">
              <span class="duo-role">副引擎</span>
              <select class="duo-select" bind:value={secondaryEngine} aria-label="副引擎">
                {#each dualCandidates as item (item.key)}
                  <option value={item.key}>{item.label}</option>
                {/each}
              </select>
              <span class="duo-arrow" aria-hidden="true">→</span>
              <span class="duo-dest">双引擎复核（只读）+ 补漏进质检</span>
            </div>
            <div class="duo-foot">
              <span class="duo-note">
                两遍顺序执行，切换前会释放上一个引擎（需 12GB 以上内存）；副稿永远不改核对台。
              </span>
              <button
                class="btn tiny ghost"
                type="button"
                onclick={swapRoles}
                disabled={!secondaryEngine}
                title="交换主/副引擎；主引擎同时同步到上方「识别引擎」与顶栏胶囊"
              >
                <Icon name="split" size={11} />交换主副
              </button>
            </div>
          </div>
        {/if}
      </section>

      <!-- 3) 结果与输出：保留所有去向/格式逻辑，但把主按钮放到最醒目的位置。 -->
      <section class="card">
        <div class="card-head tight">
          <div class="card-copy">
            <div class="card-title">结果与输出</div>
          </div>
        </div>

        <div class="row-line">
          <span class="line-label">结果处理</span>
          <div class="seg">
            {#each applyOptions as opt (opt.key)}
              <button
                type="button"
                class:on={effectiveApply === opt.key}
                class:danger-opt={opt.key === 'replace' && !fullCover}
                onclick={() => (applyMode = opt.key)}
                title={applyHint(opt.key, applyCtx)}
              >
                {opt.label}
              </button>
            {/each}
          </div>

          {#if canChooseDest && !dualMode}
            <span class="line-label sub">去向</span>
            <div class="seg">
              <button
                type="button"
                class:on={destination === 'cover'}
                onclick={() => (destination = 'cover')}
              >
                覆盖核对台
              </button>
              <button
                type="button"
                class:on={destination === 'alt'}
                onclick={() => (destination = 'alt')}
              >
                放进双引擎复核
              </button>
            </div>
          {/if}

          <span class="line-label sub">格式</span>
          <div class="seg">
            {#each ['SRT', 'VTT', 'TXT'] as f (f)}
              <button type="button" class:on={outputFormat === f} onclick={() => (outputFormat = f)}>
                {f}
              </button>
            {/each}
          </div>
        </div>
        <p class="hint" class:warn-hint={destructive}>{applyHintText}</p>

        {#if canChooseDest && !dualMode}
          <p class="hint">
            {destination === 'alt'
              ? '第二版只进参考列，核对台一个字都不改。'
              : '本次整片结果替换当前核对台。'}
          </p>
          {#if dual.exists}
            <div class="alt-state">
              <span class="alt-label">已有第二版</span>
              <b>{altEngineLabel()} · {dual.count} 条</b>
              <button class="btn tiny" type="button" onclick={() => setView('dual')}>查看对照</button>
              <button
                class="btn tiny ghost"
                type="button"
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

        <div class="run-row">
          {#if running}
            <button class="btn danger" type="button" onclick={cancelJob}>
              <Icon name="stop" size={12} />中途打断
            </button>
            <span class="hint">同一时间只允许一个重任务</span>
          {:else}
            <button
              class="btn primary run-btn"
              type="button"
              onclick={go}
              disabled={!app.media || !app.connected || !hasEnabledEngine}
            >
              <Icon name="play" size={13} />开始转写
            </button>
            <span class="hint">{app.media ? '结果写入导出文件夹' : '先导入媒体，再开始转写'}</span>
          {/if}
        </div>
      </section>

      {#if app.job && app.jobKind === 'transcribe'}
        <section class="card progress-card">
          <div class="card-title">本次任务</div>
          <div class="card-body">
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
                <span class="err-text">{app.job.error}</span>
              {:else}
                <span>{app.job.status}</span>
              {/if}
            </div>
            {#if app.job.status === 'done' && alignNote}
              <div class="pc-note">
                <span>{alignNote}</span>
                {#if app.report?.job_id === app.job.id}
                  <button class="btn tiny ghost" type="button" onclick={() => setView('report')}>
                    对齐明细
                  </button>
                {/if}
              </div>
            {/if}
            {#if app.job.status === 'done' && app.job.result?.dual}
              <div class="alt-done">
                <span class="saved-ok"><Icon name="check" size={10} />双引擎完成</span>
                <span class="saved-path">
                  {app.job.result?.summary || '主稿已保留'}
                  {#if app.job.result?.secondary_error}
                    · {app.job.result.secondary_error}
                  {/if}
                </span>
                <button class="btn tiny" type="button" onclick={() => setView('dual')}>查看第二列</button>
                <button class="btn tiny ghost" type="button" onclick={() => setView('review')}>质检补漏</button>
              </div>
            {:else if app.job.status === 'done' && app.job.result?.alt_review}
              <div class="alt-done">
                <span class="saved-ok"><Icon name="check" size={10} />已放进双引擎复核</span>
                <span class="saved-path">
                  第二引擎 {app.job.result?.alt_engine || engine} · {app.job.result?.alt_count ?? 0} 条；
                  核对台未改动
                </span>
                <button class="btn tiny" type="button" onclick={() => setView('dual')}>打开双引擎复核</button>
              </div>
            {/if}
            {#if app.job.status === 'done' && app.lastSavedPath}
              <div class="saved-row">
                <span class="saved-ok"><Icon name="check" size={10} />已自动保存</span>
                <span class="saved-path mono" title={app.lastSavedPath}>{app.lastSavedPath}</span>
                <button class="btn tiny ghost" type="button" onclick={revealSaved}>在访达中显示</button>
                <button class="btn tiny" type="button" onclick={openExportFolder}>
                  <Icon name="folder" size={10} />导出文件夹
                </button>
              </div>
            {/if}
          </div>
        </section>
      {/if}

      <!-- 90/10 的 10：15 个声学滑块与预设管理收进默认收起的抽屉，
           参数绑定与预设读写逻辑原样保留。 -->
      <ExpertParamsDrawer {engine} />

      <!-- 已有字幕走独立入口：原文轨与译文轨可以分别导入，
           不必为了补一份译文重新跑一次转写。 -->
      <section class="card">
        <div class="card-head">
          <div class="card-copy">
            <div class="card-title">已有字幕</div>
            <p class="card-sub">不重新转写，直接把原文或逐条对齐的译文导进核对台。</p>
          </div>
        </div>
        <div class="si-row">
          <button
            class="si-btn"
            type="button"
            onclick={importSubtitleFromExport}
            disabled={!app.connected || running}
            title="从导出文件夹选择原文字幕，导入核对台（不重新转写）"
          >
            <span class="si-icon"><Icon name="doc" size={13} /></span>
            <span class="si-text"><b>导入原文</b><em>SRT / VTT</em></span>
          </button>
          <button
            class="si-btn"
            type="button"
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
      </section>
    </div>
  </div>
</div>

<style>
  .pane {
    padding: var(--sp-4) var(--sp-6) var(--sp-6);
    overflow: hidden;
    flex: 1;
    min-height: 0;
    display: flex;
    flex-direction: column;
  }

  .main-scroll {
    overflow-y: auto;
    flex: 1;
    min-height: 0;
    padding-right: var(--sp-1);
  }

  .main-col {
    display: flex;
    flex-direction: column;
    gap: 10px;
    width: 100%;
    max-width: 1040px;
    margin: 0 auto;
    min-height: 0;
  }

  .card {
    border: 1px solid var(--separator-soft);
    border-radius: 10px;
    background: var(--bg-content);
    padding: 10px var(--sp-4);
    min-width: 0;
  }

  .card-head {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: var(--sp-3);
    margin-bottom: var(--sp-2);
    min-width: 0;
  }
  .card-head.tight {
    margin-bottom: var(--sp-2);
  }
  .card-copy {
    min-width: 0;
  }
  .card-title {
    font-size: 12.5px;
    font-weight: 600;
    letter-spacing: 0.02em;
    color: var(--text-2);
  }
  .card-sub {
    margin: 3px 0 0;
    font-size: 11.5px;
    line-height: 1.5;
    color: var(--text-3);
    text-wrap: pretty;
  }

  .engine-state {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    flex: 0 0 auto;
    font-size: 11.5px;
    color: var(--text-3);
    white-space: nowrap;
  }
  .state-dot {
    width: 6px;
    height: 6px;
    flex: 0 0 6px;
    border-radius: 50%;
    background: var(--warn);
    box-shadow: 0 0 0 2px var(--warn-soft);
  }
  .state-dot.ready {
    background: var(--success);
    box-shadow: 0 0 0 2px var(--success-soft);
  }

  .switch-grid {
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: var(--sp-2);
    min-width: 0;
  }
  .switch-card {
    display: flex;
    align-items: flex-start;
    gap: var(--sp-2);
    padding: var(--sp-2) 10px;
    border: 1px solid var(--separator);
    border-radius: 8px;
    background: var(--fill);
    cursor: default;
    min-width: 0;
    transition:
      border-color var(--dur) var(--ease),
      background var(--dur) var(--ease);
  }
  .switch-card:hover {
    border-color: var(--accent-line);
    background: var(--accent-soft);
  }
  .switch-card.disabled {
    opacity: 0.55;
  }
  .switch-card input {
    margin: 2px 0 0;
    accent-color: var(--control-on);
    flex: 0 0 auto;
  }
  .sw-copy {
    display: flex;
    flex-direction: column;
    gap: 2px;
    min-width: 0;
  }
  .sw-copy b {
    font-size: 12px;
    font-weight: 600;
    line-height: 16px;
    color: var(--text);
  }
  .sw-copy small {
    font-size: 10.5px;
    line-height: 1.45;
    color: var(--text-3);
    text-wrap: pretty;
  }

  .detail {
    display: flex;
    align-items: center;
    gap: var(--sp-2);
    flex-wrap: wrap;
    margin-top: var(--sp-3);
    padding-top: var(--sp-3);
    border-top: 1px solid var(--separator-soft);
    min-width: 0;
  }
  .detail-label {
    font-size: 11.5px;
    color: var(--text-3);
    min-width: 52px;
  }
  .range-row {
    display: flex;
    align-items: center;
    gap: 6px;
    flex-wrap: wrap;
    min-width: 0;
  }
  .time-field {
    width: 104px;
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
    white-space: nowrap;
  }
  .check input {
    margin: 0;
  }
  .mode-seg {
    flex: 0 1 auto;
  }

  .hint {
    margin: 6px 0 0;
    font-size: 11.5px;
    line-height: 1.5;
    color: var(--text-3);
    text-wrap: pretty;
    overflow-wrap: break-word;
  }
  .hint.warn,
  .hint.warn-hint {
    color: var(--warn);
  }

  /* 双引擎流向：主角是「谁写哪里」，不靠一段长提示解释。 */
  .duo {
    border: 1px solid var(--separator-soft);
    border-radius: 8px;
    background: var(--fill);
    padding: var(--sp-2) 10px;
    display: flex;
    flex-direction: column;
    gap: 7px;
    min-width: 0;
    margin-top: var(--sp-3);
  }
  .duo-row {
    display: flex;
    align-items: center;
    gap: 7px;
    min-width: 0;
    font-size: 12px;
  }
  .duo-role {
    flex: 0 0 44px;
    color: var(--text-3);
  }
  .duo-name {
    color: var(--accent);
    font-weight: 600;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    max-width: 170px;
  }
  .duo-select {
    font: inherit;
    font-size: 12px;
    color: var(--text);
    background: var(--bg-content);
    border: 1px solid var(--separator-soft);
    border-radius: 5px;
    padding: 2px 6px;
    max-width: 190px;
    min-width: 120px;
  }
  .duo-arrow {
    color: var(--text-3);
    flex: 0 0 auto;
  }
  .duo-dest {
    color: var(--text-2);
    min-width: 0;
    overflow-wrap: break-word;
  }
  .duo-foot {
    display: flex;
    align-items: center;
    gap: var(--sp-2);
    padding-top: 6px;
    border-top: 1px solid var(--separator-soft);
    min-width: 0;
  }
  .duo-note {
    flex: 1;
    min-width: 0;
    font-size: 11.5px;
    line-height: 1.45;
    color: var(--text-3);
    text-wrap: pretty;
  }
  .duo-foot .btn {
    flex: 0 0 auto;
  }

  .row-line {
    display: flex;
    align-items: center;
    gap: var(--sp-3);
    flex-wrap: wrap;
    min-width: 0;
  }
  .line-label {
    font-size: 12px;
    color: var(--text-2);
    min-width: 56px;
  }
  .line-label.sub {
    min-width: auto;
    color: var(--text-3);
  }

  .alt-state {
    display: flex;
    align-items: center;
    gap: 7px;
    flex-wrap: wrap;
    margin-top: var(--sp-2);
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

  .run-row {
    display: flex;
    flex-direction: column;
    align-items: stretch;
    gap: var(--sp-1);
    margin-top: var(--sp-3);
    padding-top: 10px;
    border-top: 1px solid var(--separator-soft);
  }
  .run-row .hint {
    margin: 0;
    text-align: center;
  }
  .run-btn {
    width: 100%;
    height: 36px;
    justify-content: center;
    font-size: var(--fs-body);
    font-weight: 600;
  }

  .err-text {
    color: var(--danger);
  }

  .progress-card .card-body {
    display: flex;
    flex-direction: column;
    gap: 0;
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
    flex-wrap: wrap;
  }
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

  .alt-done,
  .saved-row {
    display: flex;
    align-items: center;
    gap: 7px;
    margin-top: 9px;
    padding-top: 9px;
    border-top: 1px solid var(--separator-soft);
    min-width: 0;
    flex-wrap: wrap;
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

  /* 原文 / 译文导入：两张小文件卡，独立成区，不和「开始转写」抢层级。 */
  .si-row {
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

  /* 「覆盖整片」在区间任务里是唯一会丢数据的档位：靠令牌给一点警示色，
     让它在被点之前就与另外两档区分开（点下去还有一次确认）。 */
  .seg button.danger-opt,
  .seg button.danger-opt.on {
    color: var(--warn);
  }

  @media (max-width: 1040px) {
    .switch-grid {
      grid-template-columns: minmax(0, 1fr);
    }
  }

  @media (max-width: 900px) {
    .pane {
      padding: var(--sp-4);
    }
    .card-head {
      flex-wrap: wrap;
    }
    .engine-state {
      white-space: normal;
    }
  }
</style>
