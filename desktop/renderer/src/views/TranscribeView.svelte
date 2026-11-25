<script lang="ts">
  import Icon from '../components/Icon.svelte';
  import PageHeader from '../components/PageHeader.svelte';
  import EngineChoiceList from '../components/transcribe/EngineChoiceList.svelte';
  import ExpertParamsDrawer from '../components/transcribe/ExpertParamsDrawer.svelte';
  import RunDock from '../components/transcribe/RunDock.svelte';
  import TranscriptState from '../components/transcribe/TranscriptState.svelte';
  import { app, cancelJob, setView, startTranscribe, toast } from '../lib/store.svelte';
  import { shortcuts } from '../lib/shortcuts.svelte';
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
    return `${cues.length} 条主稿 · ${alt}。先定这一趟要产什么，再选引擎。`;
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
      // alt_count 只是这一趟落下的条数；区间合并后 B 的总数要读 dual.count。
      return {
        text: `第二版已生成 · 共 ${dual.count} 条`,
        note: `本次 ${Number(result.alt_count ?? 0)} 条 · 核对台未改动`,
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
  <div class="pane-head">
    <PageHeader title="转写" {subtitle}>
      <button
        class="btn ghost sm"
        type="button"
        onclick={() => setView('report')}
        disabled={!app.report}
        title={app.report ? '查看本次转写的任务详报' : '跑完一次转写后才有报告'}
      >
        任务报告
      </button>
      <button class="btn ghost sm" type="button" onclick={() => (shortcuts.open = true)}>
        快捷键
      </button>
    </PageHeader>
  </div>

  <div class="main-scroll">
    <div class="page-wrap">
      <div class="tr-layout">
        <div class="tr-main">
          <!-- 01 先定「这一趟做什么」：产出 → 写入方式 -->
          <section class="step">
            <div class="step-margin"><span class="step-idx">01</span></div>
            <div class="step-body">
              <h2 class="step-title">这次产出什么</h2>
              <p class="step-hint">主稿写进核对台；第二版只做对照，不会改动主稿。</p>

              <div class="step-row">
                <span class="row-label">产出</span>
                <div class="seg" role="group" aria-label="本次产出">
                  <button
                    type="button"
                    class:on={transcribeTask.target === 'primary'}
                    aria-pressed={transcribeTask.target === 'primary'}
                    onclick={() => chooseTarget('primary')}
                    title="转写结果写进核对台（主稿）"
                  >
                    主稿
                  </button>
                  <button
                    type="button"
                    class:on={transcribeTask.target === 'alt'}
                    aria-pressed={transcribeTask.target === 'alt'}
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
                    aria-pressed={transcribeTask.target === 'both'}
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
                <div class="step-row">
                  <span class="row-label">写入方式</span>
                  <div class="seg" role="group" aria-label="结果写入方式">
                    {#each plan.choices as opt (opt.key)}
                      <button
                        type="button"
                        class:on={plan.apply === opt.key}
                        aria-pressed={plan.apply === opt.key}
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

              {#if plan.warning}
                <p class="row-warn">{plan.warning}</p>
              {/if}
            </div>
          </section>

          <!-- 02 处理哪一段：范围 → 选项 → 格式 -->
          <section class="step">
            <div class="step-margin"><span class="step-idx">02</span></div>
            <div class="step-body">
              <h2 class="step-title">处理哪一段</h2>
              <p class="step-hint">
                先整片跑一遍，再对不确定的段落单独重转；区间结果保留原片绝对时间轴。
              </p>

              <div class="step-row">
                <span class="row-label">范围</span>
                <div class="seg" role="group" aria-label="本次范围">
                  <button
                    type="button"
                    class:on={!rangeEditing}
                    aria-pressed={!rangeEditing}
                    onclick={useWhole}
                    title="处理整片"
                  >
                    整片
                  </button>
                  <button
                    type="button"
                    class:on={rangeEditing}
                    aria-pressed={rangeEditing}
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
                  <span class="dash" aria-hidden="true">–</span>
                  <input
                    class="range-input mono"
                    value={transcribeTask.scope.endText}
                    placeholder="片尾"
                    aria-label="结束时间"
                    spellcheck="false"
                    oninput={(e) =>
                      touchScope(transcribeTask.scope.startText, e.currentTarget.value)}
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

              <div class="step-row">
                <span class="row-label">选项</span>
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
                <div class="step-row sub-row">
                  <span class="row-label">分离用途</span>
                  <div class="seg" role="group" aria-label="人声分离用途">
                    <button
                      type="button"
                      class:on={vocalSeparation.mode === 'vad_only'}
                      aria-pressed={vocalSeparation.mode === 'vad_only'}
                      onclick={() => (vocalSeparation.mode = 'vad_only')}
                      title="分离人声只用于 VAD 切分，识别仍听原声：不会被削掉日语清辅音"
                    >
                      仅 VAD 切分
                    </button>
                    <button
                      type="button"
                      class:on={vocalSeparation.mode === 'to_asr'}
                      aria-pressed={vocalSeparation.mode === 'to_asr'}
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

              <div class="step-row">
                <span class="row-label">格式</span>
                <div class="seg" role="group" aria-label="输出格式">
                  {#each ['SRT', 'VTT', 'TXT'] as f (f)}
                    <button
                      type="button"
                      class:on={outputFormat === f}
                      aria-pressed={outputFormat === f}
                      onclick={() => (outputFormat = f)}
                    >
                      {f}
                    </button>
                  {/each}
                </div>
                <span class="row-note">写进导出文件夹的文件格式</span>
              </div>
            </div>
          </section>

          <!-- 03 用哪个引擎：主力讲清差别；副引擎只在「两版一起」出现 -->
          <section class="step">
            <div class="step-margin"><span class="step-idx">03</span></div>
            <div class="step-body">
              <h2 class="step-title">用哪个引擎</h2>
              <p class="step-hint">
                {#if transcribeTask.target === 'alt'}
                  {primaryEngineLabel
                    ? `主稿来自 ${primaryEngineLabel}；这里选的是第二版要用的引擎。`
                    : '主稿来源未知；这里选的是第二版要用的引擎。'}
                {:else if transcribeTask.target === 'both'}
                  主稿用这个引擎，副引擎在下面单独选。
                {:else}
                  两个日语主力各有所长；这次只能选一个。第二版可以之后再跑。
                {/if}
              </p>

              <EngineChoiceList
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
                      class="btn ghost sm"
                      type="button"
                      onclick={swapRoles}
                      disabled={!secondaryEngine}
                      title="交换主 / 副引擎；主引擎同时同步到标题栏胶囊"
                    >
                      <Icon name="split" size={11} />交换主副
                    </button>
                  </div>
                </div>
              {/if}

              <div class="params">
                <ExpertParamsDrawer {engine} />
              </div>
            </div>
          </section>
        </div>

        <div class="tr-rail">
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

    </div>
  </div>

  <!-- 执行栏是**停靠**的：它是 pane 的最后一个 flex 子项，不随内容滚动，
       也不是浮在页面上的贴片。内容列（1120px）与上面的三步共用同一条左缘。 -->
  <div class="dock-wrap">
    <div class="dock-inner">
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
    padding: 0;
    overflow: hidden;
    flex: 1;
    min-height: 0;
    display: flex;
    flex-direction: column;
    background: var(--canvas);
  }

  .pane-head {
    flex: 0 0 auto;
    padding: var(--sp-6) var(--sp-8) 0;
  }

  .main-scroll {
    overflow-y: auto;
    flex: 1;
    min-height: 0;
    padding: 0 var(--sp-8);
  }

  .page-wrap {
    width: 100%;
    max-width: 1120px;
    margin: 0 auto;
    min-height: 100%;
    display: flex;
    flex-direction: column;
  }

  /* 左：三个步骤（一条纸上的三段）；右：现状（像检查器，不是又一张表单） */
  .tr-layout {
    flex: 1;
    min-height: 0;
    display: grid;
    grid-template-columns: minmax(0, 1fr) 320px;
    gap: 28px;
    padding-bottom: var(--sp-4);
  }
  .tr-main {
    min-width: 0;
  }
  /* 分隔线挂在网格单元上（而不是右栏内容上）：内容短时线也不会断在半空 */
  .tr-rail {
    min-width: 0;
    border-left: 1px solid var(--line);
    padding-left: var(--sp-5);
  }

  /* 步骤 = 台本的一段：左侧 44px 页边写段号，右侧是内容。
     这不是装饰性的「01 / 02 / 03」——三步有先后，必须按这个顺序做。 */
  .step {
    display: grid;
    grid-template-columns: var(--cue-margin-w) minmax(0, 1fr);
    border-top: 1px solid var(--line);
  }
  .step:first-child {
    border-top: 0;
  }
  .step-margin {
    border-right: 1px solid var(--line-2);
    padding-top: 21px;
    display: flex;
    justify-content: center;
  }
  .step-idx {
    font-family: var(--font-mono);
    font-size: 11px;
    line-height: 16px;
    letter-spacing: 0.04em;
    color: var(--text-3);
  }
  .step-body {
    min-width: 0;
    padding: 18px 0 20px var(--sp-4);
  }
  .step-title {
    margin: 0 0 3px;
    font-size: 13.5px;
    line-height: 20px;
    font-weight: 600;
    color: var(--text);
  }
  .step-hint {
    margin: 0 0 10px;
    font-size: 12px;
    line-height: 1.5;
    color: var(--text-3);
    text-wrap: pretty;
  }

  .step-row {
    display: flex;
    align-items: center;
    gap: 10px;
    flex-wrap: wrap;
    min-width: 0;
  }
  .step-row + .step-row {
    margin-top: var(--sp-2);
  }
  .step-row.sub-row {
    margin-top: 6px;
    padding-left: var(--sp-2);
  }
  .row-label {
    width: 62px;
    flex: 0 0 62px;
    font-size: 11.5px;
    color: var(--text-3);
  }
  .row-note {
    font-size: 11px;
    color: var(--text-3);
  }
  .row-warn {
    margin: var(--sp-2) 0 0;
    font-size: 11.5px;
    line-height: 1.5;
    color: var(--warn);
    text-wrap: pretty;
  }

  /* 页面内唯一的说明文字档：只有「读了才知道下一步」的句子用它 */
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
    height: 26px;
    border: 1px solid var(--line);
    border-radius: var(--rad-control);
    background: var(--raise);
    color: var(--text);
    font-size: 12px;
    padding: 0 7px;
  }
  .range-input.mono {
    font-family: var(--font-mono);
    font-variant-numeric: tabular-nums;
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

  .params {
    margin-top: var(--sp-3);
  }

  /* 两版一起的流向：主角是「谁写哪里」，不靠一段长提示解释 */
  .duo {
    border: 1px solid var(--line);
    border-radius: var(--rad-card);
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
    color: var(--accent-text);
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
    background: var(--raise);
    border: 1px solid var(--line);
    border-radius: var(--rad-control);
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
    border-top: 1px solid var(--line-2);
    min-width: 0;
  }
  .duo-note {
    flex: 1;
    min-width: 0;
    font-size: 11px;
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

  /* 停靠栏：通栏的纸面色带 + 一条上发丝线。它不再用半透明模糊的白条浮在
     画布上，也不在两侧内缩——内容列与上面三步共用同一条左缘。 */
  .dock-wrap {
    flex: 0 0 auto;
    padding: 0 var(--sp-8);
    border-top: 1px solid var(--line);
    /* 比纸面更靠画布一档：色带只是「台面下沉了 1px」，不是贴上去的白条。
       真正的分隔由那条上发丝线负责（DESIGN.md：层级靠明度，不靠边框堆叠）。 */
    background: color-mix(in srgb, var(--paper) 55%, var(--canvas));
    min-width: 0;
  }
  /* 与 `.main-scroll` 的内边距 + `.page-wrap` 的 1120 内容列完全同一套几何，
     这样底栏的复述文字和上面三步的左缘严格对齐（差 4px 都会被截图抓出来）。 */
  .dock-inner {
    width: 100%;
    max-width: 1120px;
    margin: 0 auto;
  }

  /* 1080（最小窗口）下仍保留右栏：它是「我现在有什么 / 下一步去哪」的锚点，
     掉到三步之后就要滚到底才看得见。窄到这个程度也够放三个控件行。 */
  @media (max-width: 1180px) {
    .tr-layout {
      grid-template-columns: minmax(0, 1fr) 272px;
      gap: var(--sp-5);
    }
  }
  @media (max-width: 1000px) {
    .tr-layout {
      grid-template-columns: minmax(0, 1fr);
    }
    .tr-rail {
      order: 2;
      border-left: 0;
      padding-left: 0;
      border-top: 1px solid var(--line);
      padding-top: var(--sp-4);
    }
  }

  @media (max-width: 900px) {
    .pane {
      padding: var(--sp-4) var(--sp-4) 0;
    }
    .step-body {
      padding-left: var(--sp-3);
    }
    .row-label {
      width: 52px;
      flex-basis: 52px;
    }
  }
</style>
