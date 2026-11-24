<script lang="ts">
  import Icon from '../components/Icon.svelte';
  import PageHeader from '../components/PageHeader.svelte';
  import EngineChoiceCards from '../components/transcribe/EngineChoiceCards.svelte';
  import ExpertParamsDrawer from '../components/transcribe/ExpertParamsDrawer.svelte';
  import RunDock from '../components/transcribe/RunDock.svelte';
  import TranscriptState from '../components/transcribe/TranscriptState.svelte';
  import { app, cancelJob, setView, startTranscribe, toast } from '../lib/store.svelte';
  import * as kernel from '../lib/applyMode';
  import {
    type ApplyMode,
    applyHint,
    confirmDestructiveText,
    needsAbsoluteTimeline,
  } from '../lib/applyMode';
  import { defaultTarget, resolvePlan, targetLabel } from '../lib/transcribePlan';
  import {
    applySliceScope,
    chooseTarget,
    noteSubmit,
    resetForMedia,
    restoreScope,
    setScopeFull,
    touchScope,
    transcribeTask,
    type LastRunView,
  } from '../lib/transcribeTask.svelte';
  import { altEngineLabel, dual, refreshAltReview } from '../lib/dualReview.svelte';
  import { takeSlice } from '../lib/transcribeSlice';
  import { parseTimeInput } from '../lib/time';
  import { type AlignStats, alignDoneText } from '../lib/transcribeJob';
  import { vocalSeparation } from '../lib/vocalSeparation.svelte';
  import { tick } from 'svelte';

  let { engine = $bindable('whisper') }: { engine?: string } = $props();

  let outputFormat = $state('SRT');
  let absolute = $state(true);
  let applyMode = $state<ApplyMode>('replace_range');
  let secondaryEngine = $state('');
  let rangeEditing = $state(false);
  let startInput: HTMLInputElement | undefined = $state();
  /** 自动默认产出的判据（换片 / 换引擎时重算一次；用户亲手选过就不再覆盖）。 */
  let targetKey = '';

  const running = $derived(
    app.job?.status === 'queued' ||
      app.job?.status === 'running' ||
      app.job?.status === 'cancelling',
  );
  const pct = $derived(app.job?.percent ?? 0);
  const enabledEngines = $derived((app.config?.engines ?? []).filter((e) => e.enabled));
  const hasEnabledEngine = $derived(enabledEngines.some((e) => e.key === engine));
  const currentEngine = $derived(enabledEngines.find((e) => e.key === engine) ?? null);
  const cues = $derived(app.cues);

  /** 主稿引擎：服务端来源优先；逐章 replace_range 不写来源，退回本页上次提交。 */
  const primaryEngineKey = $derived(
    String(app.reviewSource?.engine || transcribeTask.lastSubmit?.engine || ''),
  );

  function labelOf(key: string): string {
    if (!key) return '';
    return app.config?.engines.find((item) => item.key === key)?.label ?? key;
  }

  const primaryEngineLabel = $derived(labelOf(primaryEngineKey));

  const fullCover = $derived.by(() => {
    const start = parseTimeInput(transcribeTask.scope.startText);
    const end = parseTimeInput(transcribeTask.scope.endText);
    const duration = app.media?.duration || 0;
    const startCovers = start === null || start <= 0.001;
    const endCovers = end === null || end >= duration - 0.5;
    return startCovers && endCovers;
  });
  const ctx = $derived({
    fullCover,
    start: transcribeTask.scope.startText,
    end: transcribeTask.scope.endText,
  });

  /** 可配对的副引擎：另一个已启用的日语 Whisper / Qwen。 */
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
      dualCandidates.find((item) => item.key === preferred)?.key ?? dualCandidates[0]?.key ?? ''
    );
  });

  const plan = $derived(
    resolvePlan(
      {
        target: transcribeTask.target,
        ctx,
        apply: applyMode,
        hasCues: cues.length > 0,
        engineLabel: currentEngine?.label ?? engine,
        primaryEngineLabel,
        secondary: secondaryEngine,
        secondaryLabel: labelOf(secondaryEngine),
        candidates: dualCandidates.map((item) => item.key),
        alt: { exists: dual.exists, count: dual.count, engineLabel: altEngineLabel() },
      },
      kernel,
    ),
  );

  /** 「替换选区」必须走原片绝对时间轴（见 applyMode.ts），第二版区间同理。 */
  const absoluteLocked = $derived(needsAbsoluteTimeline(plan.apply));
  const effectiveAbsolute = $derived(absoluteLocked ? true : absolute);

  const canSeparate = $derived.by(() => {
    const start = parseTimeInput(transcribeTask.scope.startText);
    const end = parseTimeInput(transcribeTask.scope.endText);
    if (start !== null && end !== null && end > start + 0.2) return true;
    return (app.media?.duration || 0) > 0;
  });

  /** 「区间」按钮只是展开输入框；真正是不是区间由起止值决定（空 = 整片）。 */
  $effect(() => {
    if (transcribeTask.scope.from !== 'full') rangeEditing = true;
  });

  // 换片：范围 / 上次提交 / 自动产出全部归零。必须在消费 slice 之前跑。
  $effect(() => {
    const id = app.media?.id ?? '';
    if (resetForMedia(id)) {
      rangeEditing = false;
      applyMode = 'replace_range';
      absolute = true;
    }
  });

  // 核对台 / 章节「加入转写选区」带过来的区间：读走即清空，但值留在页面记忆里。
  $effect(() => {
    const req = takeSlice(app);
    if (!req) return;
    applySliceScope(req);
    rangeEditing = true;
  });

  // 换引擎 / 换片时套一次默认产出：已有一稿就默认写第二版，不覆盖主稿。
  $effect(() => {
    const key = `${app.media?.id ?? ''}:${engine}:${primaryEngineKey}`;
    if (targetKey === key) return;
    targetKey = key;
    if (transcribeTask.targetTouched) return;
    transcribeTask.target = defaultTarget({
      hasCues: cues.length > 0,
      engine,
      primaryEngine: primaryEngineKey,
    });
  });

  // 副引擎候选变化（切引擎 / 改设置）后，不能把一个非法配对留在面板里。
  $effect(() => {
    if (!dualCandidates.some((item) => item.key === secondaryEngine)) {
      secondaryEngine = defaultSecondary;
    }
  });

  // 当前媒体的第二版随时可能被别处改动（导入 / 删除），切回本页就重拉一次。
  $effect(() => {
    void app.connected;
    void app.media?.id;
    if (app.connected) void refreshAltReview();
  });

  const scopeText = $derived.by(() => {
    if (fullCover) return '整片';
    const span = `${transcribeTask.scope.startText || '片头'} – ${transcribeTask.scope.endText || '片尾'}`;
    return transcribeTask.scope.from === 'chapter' && transcribeTask.scope.label
      ? `${transcribeTask.scope.label} ${span}`
      : span;
  });
  const dockSummary = $derived(
    `${currentEngine?.label ?? engine} · ${scopeText} → ${targetLabel(transcribeTask.target)}`,
  );

  const sourceText = $derived.by(() => {
    if (!rangeEditing) return '';
    if (transcribeTask.scope.from === 'chapter' && transcribeTask.scope.label) {
      return `来源：章节「${transcribeTask.scope.label}」`;
    }
    if (transcribeTask.scope.from === 'review') return '来源：核对台选区';
    if (transcribeTask.scope.from === 'manual') return '来源：手动填写';
    return '';
  });

  const subtitle = $derived.by(() => {
    if (!app.media) return '还没有导入媒体——先去「导入」挑一个文件。';
    if (!cues.length) return '还没有字幕；这次转写会写进核对台。';
    const alt = dual.exists ? `第二版 ${dual.count} 条` : '第二版还没有';
    return `${cues.length} 条主稿 · ${alt}。换一个引擎跑同一段，就能逐句对照两份原文。`;
  });

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

  /** 只有「本页提交的这次任务」才归底栏管；核对台发起的区间任务不在这一页报进度。 */
  const mine = $derived(
    app.jobKind === 'transcribe' && app.jobMeta?.origin === 'transcribe' && app.job
      ? app.job
      : null,
  );
  const dockSig = $derived(
    `${engine}|${transcribeTask.target}|${transcribeTask.scope.startText}|${transcribeTask.scope.endText}|${plan.apply}`,
  );
  const submittedSig = $derived(
    transcribeTask.lastSubmit
      ? `${transcribeTask.lastSubmit.engine}|${transcribeTask.lastSubmit.target}|${transcribeTask.lastSubmit.startText}|${transcribeTask.lastSubmit.endText}|${transcribeTask.lastSubmit.apply}`
      : '',
  );

  const dockState = $derived.by<'idle' | 'running' | 'done' | 'error'>(() => {
    if (!mine) return 'idle';
    if (mine.status === 'queued' || mine.status === 'running' || mine.status === 'cancelling') {
      return 'running';
    }
    // 完成 / 失败只在「设置没变」时展示；改过引擎或范围就回到待命，避免旧结果冒充新配置。
    if (!submittedSig || submittedSig !== dockSig) return 'idle';
    if (mine.status === 'done') return 'done';
    if (mine.status === 'error') return 'error';
    return 'idle';
  });

  const doneInfo = $derived.by(() => {
    if (dockState !== 'done' || !app.job) return { text: '', note: '' };
    const result = app.job.result ?? {};
    if (result.alt_review) {
      return {
        text: `第二版已生成 · ${Number(result.alt_count ?? dual.count)} 条`,
        note: '核对台未改动',
      };
    }
    if (result.dual) {
      return {
        text: `双引擎完成 · 主稿 ${cues.length} 条`,
        note: `第二版 ${dual.count} 条`,
      };
    }
    return {
      text: `转写完成 · ${cues.length} 条字幕`,
      note: alignNote || (app.lastSavedPath ? '已自动保存' : ''),
    };
  });

  const doneCta = $derived.by<null | { label: string; onclick: () => void }>(() => {
    if (dockState !== 'done') return null;
    const result = app.job?.result ?? {};
    if (result.alt_review || result.dual) {
      return { label: '查看差异', onclick: () => setView('dual') };
    }
    return null;
  });

  const lastRunView = $derived.by<LastRunView | null>(() => {
    const sub = transcribeTask.lastSubmit;
    if (!sub) return null;
    const result = app.job?.result ?? {};
    const countText = result.alt_review
      ? `第二版 ${dual.count} 条`
      : result.dual
        ? `主稿 ${cues.length} 条 · 第二版 ${dual.count} 条`
        : `核对台 ${cues.length} 条`;
    return {
      engineLabel: labelOf(sub.engine),
      targetText: targetLabel(sub.target),
      rangeText:
        sub.startText || sub.endText
          ? `${sub.startText || '片头'} – ${sub.endText || '片尾'}`
          : '整片',
      countText,
      canReplay: Boolean((sub.startText || sub.endText) && cues.length > 0),
      at: sub.at,
    };
  });

  async function startRangeEditing() {
    rangeEditing = true;
    await tick();
    startInput?.focus();
  }

  function useWhole() {
    setScopeFull();
    rangeEditing = false;
  }

  function swapRoles() {
    if (!secondaryEngine || secondaryEngine === engine) return;
    const oldPrimaryKey = engine;
    const oldPrimaryLabel = currentEngine?.label ?? engine;
    const oldSecondaryLabel = labelOf(secondaryEngine);
    engine = secondaryEngine;
    secondaryEngine = oldPrimaryKey;
    toast(`已交换：${oldSecondaryLabel} 为主，${oldPrimaryLabel} 为副`, 'info');
  }

  function suggestAlt(engineKey: string) {
    engine = engineKey;
    chooseTarget('alt');
  }

  function replayLastAsAlt() {
    const sub = transcribeTask.lastSubmit;
    if (!sub) return;
    restoreScope(sub.startText, sub.endText);
    rangeEditing = true;
    chooseTarget('alt');
    toast('已填回上一趟的范围，产出改为「第二版」；确认引擎后点生成第二版');
  }

  function revealSaved() {
    if (app.lastSavedPath) window.kikusub.revealInFinder(app.lastSavedPath);
  }

  function go() {
    if (plan.blocked) {
      toast(plan.blocked, 'warn');
      return;
    }
    if (plan.destructive && cues.length > 0) {
      if (!window.confirm(confirmDestructiveText(ctx))) return;
    }
    // 整片重做第二版且换了引擎：现有 B 会被整列替换，先问一次（只影响 B）。
    if (
      transcribeTask.target === 'alt' &&
      plan.apply === 'replace' &&
      dual.exists &&
      dual.engine !== engine
    ) {
      if (
        !window.confirm(
          `整片重转会把第二版整列换成 ${labelOf(engine)} 的结果（现有 ${altEngineLabel()} · ${dual.count} 条）。\n核对台不受影响。继续？`,
        )
      ) {
        return;
      }
    }
    noteSubmit({
      engine,
      target: transcribeTask.target,
      startText: transcribeTask.scope.startText,
      endText: transcribeTask.scope.endText,
      label: transcribeTask.scope.label,
      apply: plan.apply,
    });
    void startTranscribe(
      {
        engine,
        outputFormat,
        startText: transcribeTask.scope.startText,
        endText: transcribeTask.scope.endText,
        absoluteTimeline: effectiveAbsolute,
        apply: plan.apply,
        altReview: plan.altReview,
        dualEngine: plan.dualEngine || undefined,
      },
      parseTimeInput,
    );
  }
</script>

<div class="pane">
  <PageHeader title="开始转写" {subtitle} />

  <div class="main-scroll">
    <div class="layout">
      <div class="col-main">
        <!-- ① 先定「这一趟做什么」：产出 → 写入方式 → 范围 → 选项。 -->
        <section class="card">
          <div class="card-head">
            <div class="card-copy">
              <div class="card-title">这次做什么</div>
              <p class="card-sub">先定产出，再定范围；底栏会把「谁 × 哪一段 → 写到哪」复述一遍。</p>
            </div>
          </div>

          <div class="row-line">
            <span class="line-label">产出</span>
            <div class="seg" role="group" aria-label="本次产出">
              <button
                type="button"
                class:on={transcribeTask.target === 'primary'}
                onclick={() => chooseTarget('primary')}
                title="转写结果写进核对台（主稿）"
              >
                主稿
              </button>
              <button
                type="button"
                class:on={transcribeTask.target === 'alt'}
                onclick={() => chooseTarget('alt')}
                disabled={!cues.length}
                title={cues.length
                  ? '只写第二版（双引擎复核的 B），核对台不动'
                  : '先有一版主稿，第二版才有东西可对照'}
              >
                第二版
              </button>
              <button
                type="button"
                class:on={transcribeTask.target === 'both'}
                onclick={() => chooseTarget('both')}
                disabled={!dualCandidates.length}
                title={dualCandidates.length
                  ? '顺序跑两个引擎：主稿进核对台，副稿进第二版'
                  : '需要再启用一个日语引擎'}
              >
                两版一起
              </button>
            </div>
          </div>

          {#if plan.choices.length}
            <div class="row-line">
              <span class="line-label">写入方式</span>
              <div class="seg" role="group" aria-label="结果写入方式">
                {#each plan.choices as opt (opt.key)}
                  <button
                    type="button"
                    class:on={plan.apply === opt.key}
                    class:danger-opt={opt.key === 'replace' && !fullCover}
                    onclick={() => (applyMode = opt.key)}
                    title={applyHint(opt.key, ctx)}
                  >
                    {opt.label}
                  </button>
                {/each}
              </div>
            </div>
          {/if}

          <div class="row-line">
            <span class="line-label">范围</span>
            <div class="seg" role="group" aria-label="本次范围">
              <button type="button" class:on={!rangeEditing} onclick={useWhole} title="处理整片">
                整片
              </button>
              <button
                type="button"
                class:on={rangeEditing}
                onclick={() => void startRangeEditing()}
                title="只处理一段起止时间；留空任一端按片头 / 片尾算"
              >
                区间
              </button>
            </div>
            {#if rangeEditing}
              <input
                class="range-input mono"
                bind:this={startInput}
                value={transcribeTask.scope.startText}
                placeholder="片头"
                aria-label="起始时间"
                spellcheck="false"
                oninput={(e) => touchScope(e.currentTarget.value, transcribeTask.scope.endText)}
              />
              <span class="dash">–</span>
              <input
                class="range-input mono"
                value={transcribeTask.scope.endText}
                placeholder="片尾"
                aria-label="结束时间"
                spellcheck="false"
                oninput={(e) => touchScope(transcribeTask.scope.startText, e.currentTarget.value)}
              />
              <label
                class="check"
                title={absoluteLocked
                  ? '「替换选区」必须用原片绝对时间轴：相对时间轴会让新区间的字幕从 0 秒开始编号'
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
            {/if}
          </div>
          {#if rangeEditing}
            <p class="hint">
              {sourceText}{sourceText ? ' · ' : ''}留空任一端 = 该端按片头 / 片尾；点「整片」清空范围。
            </p>
          {/if}

          {#if plan.warning}
            <p class="hint warn">{plan.warning}</p>
          {/if}

          <div class="row-line">
            <span class="line-label">选项</span>
            <label
              class="check"
              title="对整片或已填写的起止区间做 Demucs 人声分离；首次会下载约 80MB 权重，结果会缓存，换引擎重转可复用。"
            >
              <input
                type="checkbox"
                bind:checked={vocalSeparation.enabled}
                disabled={!canSeparate}
              />
              强 BGM / 歌曲人声分离
            </label>
          </div>
          {#if vocalSeparation.enabled}
            <div class="row-line sub-row">
              <span class="line-label">分离用途</span>
              <div class="seg" role="group" aria-label="人声分离用途">
                <button
                  type="button"
                  class:on={vocalSeparation.mode === 'vad_only'}
                  onclick={() => (vocalSeparation.mode = 'vad_only')}
                  title="分离人声只用于 VAD 切分，识别仍听原声：不会被削掉日语清辅音"
                >
                  仅 VAD 切分
                </button>
                <button
                  type="button"
                  class:on={vocalSeparation.mode === 'to_asr'}
                  onclick={() => (vocalSeparation.mode = 'to_asr')}
                  title="高级：分离人声直接送识别，只在人声被彻底盖死时用"
                >
                  送识别
                </button>
              </div>
            </div>
            <p class="hint">
              {vocalSeparation.mode === 'vad_only'
                ? '切分看干净人声、识别听原声——保住日语清辅音细节，只从更准的边界获益。'
                : '分离人声直接送识别，适合人声被纯歌声 / 极重混响彻底盖死的段落；代价是清辅音可能被一起削掉。'}
            </p>
          {:else if !canSeparate}
            <p class="hint">先导入媒体或填写起止时间，才能开启分离。</p>
          {/if}

          <div class="row-line">
            <span class="line-label">格式</span>
            <div class="seg" role="group" aria-label="输出格式">
              {#each ['SRT', 'VTT', 'TXT'] as f (f)}
                <button type="button" class:on={outputFormat === f} onclick={() => (outputFormat = f)}>
                  {f}
                </button>
              {/each}
            </div>
            <span class="row-note">写进导出文件夹的文件格式</span>
          </div>
        </section>

        <!-- ② 用谁做：两个日语主力讲清差别；副引擎只在「两版一起」出现。 -->
        <section class="card">
          <div class="card-head">
            <div class="card-copy">
              <div class="card-title">用哪个引擎</div>
              <p class="card-sub">
                {#if transcribeTask.target === 'alt'}
                  {primaryEngineLabel
                    ? `主稿来自 ${primaryEngineLabel}；这里选的是第二版要用的引擎。`
                    : '主稿来源未知；这里选的是第二版要用的引擎。'}
                {:else if transcribeTask.target === 'both'}
                  主稿用这个引擎，副引擎在下面单独选。
                {:else}
                  按这次的素材选口径；两个主力各自擅长什么，卡片上写着。
                {/if}
              </p>
            </div>
            {#if currentEngine}
              <span class="engine-state" class:ready={currentEngine.installed}>
                <span class="state-dot" class:ready={currentEngine.installed}></span>
                {currentEngine.installed ? '当前引擎已就绪' : `未下载 · ${currentEngine.approx_label}`}
              </span>
            {/if}
          </div>

          <EngineChoiceCards
            bind:engine
            engines={enabledEngines}
            onmanage={() => setView('settings')}
          />

          {#if currentEngine && !currentEngine.installed}
            <p class="hint warn">
              首次使用会先下载 {currentEngine.approx_label}；下载完成后自动开始，期间可以取消。
            </p>
          {/if}

          {#if transcribeTask.target === 'both'}
            <div class="duo">
              <div class="duo-row">
                <span class="duo-role">主引擎</span>
                <b class="duo-name">{currentEngine?.label ?? engine}</b>
                <span class="duo-arrow" aria-hidden="true">→</span>
                <span class="duo-dest">写进核对台（主稿）</span>
              </div>
              <div class="duo-row">
                <span class="duo-role">副引擎</span>
                <select class="duo-select" bind:value={secondaryEngine} aria-label="副引擎">
                  {#each dualCandidates as item (item.key)}
                    <option value={item.key}>{item.label}</option>
                  {/each}
                </select>
                <span class="duo-arrow" aria-hidden="true">→</span>
                <span class="duo-dest">写进第二版（只读对照）</span>
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
                  title="交换主 / 副引擎；主引擎同时同步到顶栏胶囊"
                >
                  <Icon name="split" size={11} />交换主副
                </button>
              </div>
            </div>
          {/if}

          <div class="params">
            <ExpertParamsDrawer {engine} />
          </div>
        </section>
      </div>

      <div class="col-side">
        <TranscriptState
          {primaryEngineKey}
          {primaryEngineLabel}
          target={transcribeTask.target}
          lastRun={lastRunView}
          onSuggestAlt={suggestAlt}
          onPickAlt={() => chooseTarget('alt')}
          onReplayAlt={replayLastAsAlt}
        />
      </div>
    </div>

    <div class="dock-wrap">
      <RunDock
        summary={dockSummary}
        detail={plan.hint}
        blocked={plan.blocked}
        buttonLabel={plan.button}
        disabled={!app.media || !app.connected || !hasEnabledEngine}
        state={dockState}
        {pct}
        stage={app.job?.stage ?? ''}
        statusText={doneInfo.text}
        statusNote={doneInfo.note}
        error={app.job?.error ?? ''}
        doneCta={doneCta}
        savedPath={dockState === 'done' ? app.lastSavedPath : ''}
        onrun={go}
        oncancel={cancelJob}
        onreveal={revealSaved}
      />
    </div>
  </div>
</div>

<style>
  .pane {
    padding: var(--sp-8) var(--sp-6) 0;
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

  /* 左：设置（卡片）；右：现状（平面，像检查器而不是又一张表单）。 */
  .layout {
    display: grid;
    grid-template-columns: minmax(0, 1fr) 300px;
    gap: 14px;
    width: 100%;
    max-width: 1040px;
    margin: 0 auto;
    min-height: 0;
  }
  .col-main {
    display: flex;
    flex-direction: column;
    gap: 10px;
    min-width: 0;
  }
  .col-side {
    min-width: 0;
  }

  /* 任务条跟在内容后面：内容短时自然收在卡片下方，内容长（展开参数）时
     吸附在滚动区底部——两种情况下都“始终看得见”，又不会在短页面上留一大块空白。 */
  .dock-wrap {
    position: sticky;
    bottom: 0;
    z-index: 2;
    width: 100%;
    max-width: 1040px;
    margin: 0 auto;
    padding-top: 10px;
    background: var(--paper);
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

  .row-line {
    display: flex;
    align-items: center;
    gap: var(--sp-2);
    flex-wrap: wrap;
    min-width: 0;
    margin-top: 9px;
  }
  .card-head + .row-line {
    margin-top: 0;
  }
  .row-line.sub-row {
    margin-top: 7px;
    padding-left: var(--sp-2);
  }
  .line-label {
    font-size: 12px;
    color: var(--text-2);
    min-width: 56px;
    flex: 0 0 auto;
  }
  .row-note {
    font-size: 11px;
    color: var(--text-3);
  }

  .hint {
    margin: 6px 0 0;
    font-size: 11.5px;
    line-height: 1.5;
    color: var(--text-3);
    text-wrap: pretty;
    overflow-wrap: break-word;
  }
  .hint.warn {
    color: var(--warn);
  }

  .range-input {
    width: 104px;
    height: 27px;
    border: 1px solid var(--separator);
    border-radius: 5px;
    background: var(--bg-content);
    color: var(--text);
    font-size: 12px;
    padding: 0 7px;
  }
  .range-input:focus-visible {
    outline: 2px solid var(--accent-ring);
    outline-offset: -2px;
  }
  .dash {
    color: var(--text-3);
  }
  .check {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    font-size: 12px;
    color: var(--text-2);
    white-space: nowrap;
  }
  .check input {
    margin: 0;
    accent-color: var(--control-on);
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

  .params {
    margin-top: var(--sp-3);
  }

  /* 两版一起的流向：主角是「谁写哪里」，不靠一段长提示解释。 */
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

  .seg button.danger-opt,
  .seg button.danger-opt.on {
    color: var(--warn);
  }

  @media (max-width: 1120px) {
    .layout {
      grid-template-columns: minmax(0, 1fr);
    }
    .col-side {
      order: 2;
    }
  }

  @media (max-width: 900px) {
    .pane {
      padding: var(--sp-4) var(--sp-6) 0;
    }
    .card-head {
      flex-wrap: wrap;
    }
    .engine-state {
      white-space: normal;
    }
    .line-label {
      min-width: 52px;
    }
  }
</style>
