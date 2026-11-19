<script lang="ts">
  /**
   * 「另一引擎复核」卡片（右侧检查器）。
   *
   * 用户要做的判断是「这一句到底该用哪一版」，所以卡片把三份证据放在同一屏：
   *  1. 原片这一句的声音（上方「试听原声」，与核对其余操作在一起）；
   *  2. 当前稿的 TTS 朗读；
   *  3. 另一引擎的 TTS 朗读，并标出两版字面上的差异。
   *
   * 刻意只读：复核结果不会自动覆盖字幕，采用走既有 `updateCue()`（一步历史）。
   */
  import Icon from './Icon.svelte';
  import ArbitrationCard from './ArbitrationCard.svelte';
  import { jobBusy } from '../lib/jobState';
  import {
    app,
    cloneEngineReady,
    setView,
    speakCue,
    speakTextTagged,
    stopTts,
    tts,
    ttsVoice,
  } from '../lib/store.svelte';
  import {
    adoptAlternative,
    alternativeText,
    cancelSecondOpinion,
    currentEngineLabel,
    currentEngineShortLabel,
    dismissAlternative,
    hasAlternative,
    resultEngineLabel,
    retrySecondOpinion,
    reviewEngineCandidates,
    runSecondOpinion,
    secondOpinion,
    selectedReviewEngine,
    selectedReviewEngineLabel,
    selectedReviewEngineShortLabel,
    setReviewEngine,
  } from '../lib/secondOpinion.svelte';
  import { charDiff } from '../lib/textDiff';
  import {
    arbitration,
    hasArbitration,
    loadArbitrationConfig,
    runArbitration,
    takeAutoArbitrationKey,
  } from '../lib/arbitration.svelte';

  let { index, text }: { index: number; text: string } = $props();

  const altText = $derived(alternativeText(index));
  const has = $derived(hasAlternative(index));
  const diff = $derived(charDiff(text || '', altText));
  const candidates = $derived(reviewEngineCandidates());
  const readyEngine = $derived(selectedReviewEngine());
  const readyLabel = $derived(selectedReviewEngineLabel());
  const readyShort = $derived(selectedReviewEngineShortLabel());
  const currentLabel = $derived(currentEngineLabel());
  const altLabel = $derived(resultEngineLabel() || readyLabel || '另一引擎');
  const running = $derived(secondOpinion.status === 'running');
  const failed = $derived(secondOpinion.status === 'error' ? secondOpinion.error : '');
  const busy = $derived(jobBusy() || running);

  // P2-4：两版不一致时自动判定。只在用户开启开关后生效，同一句 + 同一 B 文本
  // 只自动跑一次；切换句子 / 编辑 / 取消由 ArbitrationCard 的 AbortController 中断。
  $effect(() => {
    const cfg = arbitration.config;
    if (!cfg) {
      void loadArbitrationConfig();
      return;
    }
    if (!cfg.auto_arbitrate || !cfg.enabled) return;
    if (secondOpinion.status !== 'done' || !has) return;
    const cue = app.cues[index];
    if (!cue) return;
    const a = (text || '').trim();
    const b = (altText || '').trim();
    if (!a || !b || a === b) return;
    if (hasArbitration(index) || arbitration.runningIndex >= 0) return;
    const key = `${app.media?.id || ''}:${index}:${cue.start}:${cue.end}:${b}`;
    if (!takeAutoArbitrationKey(key)) return;
    void runArbitration(index);
  });

  /**
   * 两版文本的 TTS 用同一套音色：
   * - 当前稿复用 `speakCue()`，与下方 TTS 面板的播放状态天然同步（同一句、同一音色）；
   * - 备选稿是字幕表之外的一段文字，用 `tag` 单独标记，避免被当成当前句。
   */
  const tagAlt = $derived(`so:${index}:alt`);
  const playingCurrent = $derived(tts.playing && !tts.tag && tts.index === index);
  const loadingCurrent = $derived(tts.loading && !tts.tag && tts.index === index);
  const playingAlt = $derived(tts.playing && tts.tag === tagAlt);
  const loadingAlt = $derived(tts.loading && tts.tag === tagAlt);

  const ttsBlocked = $derived(
    !tts.loaded || !tts.available || (ttsVoice()?.kind === 'clone' && !cloneEngineReady()),
  );
  const ttsTitle = $derived.by(() => {
    if (!tts.loaded) return '正在读取朗读音色…';
    if (!tts.available) return '没有可用的朗读音色：到设置里检查 TTS';
    if (ttsVoice()?.kind === 'clone' && !cloneEngineReady()) {
      return '克隆模型还没下载：先下载模型或改用系统语音';
    }
    return '用下方 TTS 对照的同一音色朗读这句';
  });

  /** 没有就绪引擎时，把「差什么」说清楚，而不是只把按钮变灰。 */
  const engineHint = $derived.by(() => {
    if (readyEngine) return '';
    if (!candidates.length) {
      return '当前稿没有可复核的同语种引擎：到「设置 → 引擎与模型」启用另一个同语种引擎。';
    }
    const detail = candidates
      .map((engine) => {
        if (!engine.enabled) return `${engine.label}（已停用）`;
        if (!engine.installed) return `${engine.label}（未下载）`;
        return engine.label;
      })
      .join(' / ');
    return `${detail} 还不能用：到「设置 → 引擎与模型」启用并下载模型。`;
  });

  const tip = $derived.by(() => {
    const target = readyLabel || '另一个引擎';
    return `把这一句的时间窗送给「${target}」再听一遍；不会改动当前字幕，采用后才进历史。`;
  });

  const retryLabel = $derived.by(() => {
    if (!secondOpinion.engine || !readyEngine) return '再听一遍';
    return secondOpinion.engine === readyEngine ? '再听一遍' : '换引擎重听';
  });

  function onEngineChange(event: Event) {
    const select = event.currentTarget as HTMLSelectElement;
    setReviewEngine(select.value);
  }

  function run() {
    void runSecondOpinion([index]);
  }

  function retry() {
    retrySecondOpinion();
  }

  function adopt() {
    void adoptAlternative(index);
  }

  function speakCurrent() {
    if (playingCurrent || loadingCurrent) {
      stopTts();
      return;
    }
    void speakCue(index);
  }

  function speakAlt() {
    if (playingAlt || loadingAlt) {
      stopTts();
      return;
    }
    void speakTextTagged(altText || '', tagAlt);
  }
</script>

<section class="second-opinion" aria-label="另一引擎复核">
  <div class="so-head">
    <b>另一引擎复核</b>
    <div class="so-pick">
      <span class="so-from" title="当前稿的引擎">{currentEngineShortLabel()}</span>
      <span class="so-arrow" aria-hidden="true">→</span>
      {#if candidates.length}
        <label
          class="so-select-wrap"
          title="选一个引擎当「另一个引擎」：只列与当前稿同语种、支持窗口复核的引擎"
        >
          <select
            class="so-select"
            value={readyEngine}
            onchange={onEngineChange}
            aria-label="复核引擎"
          >
            {#if !readyEngine}
              <option value="" disabled>未就绪</option>
            {/if}
            {#each candidates as engine (engine.key)}
              <option
                value={engine.key}
                disabled={!engine.enabled || !engine.installed}
                title={engine.label}
              >
                {engine.shortLabel}{engine.enabled ? '' : ' · 已停用'}{engine.installed
                  ? ''
                  : ' · 未下载'}
              </option>
            {/each}
          </select>
          <Icon name="chevron-down" size={10} />
        </label>
      {:else}
        <span class="so-none" title="没有与当前稿同语种、且支持窗口复核的引擎">无可用引擎</span>
      {/if}
    </div>
  </div>

  {#if running}
    <div
      class="so-progress"
      role="progressbar"
      aria-label="复核进度"
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={Math.round(secondOpinion.ratio * 100)}
    >
      <i style="width:{Math.round(secondOpinion.ratio * 100)}%"></i>
    </div>
    <div class="so-stage">
      {#if secondOpinion.stage}{secondOpinion.stage}{:else}正在用 {readyShort || '另一引擎'} 复核…{/if}
    </div>
    <div class="so-actions">
      <button class="btn mini ghost" onclick={() => cancelSecondOpinion()}>取消</button>
    </div>
  {:else if has}
    <div class="so-pair">
      <article class="so-card current">
        <div class="so-card-head">
          <span class="so-engine" title={currentLabel}>
            <i class="so-dot" aria-hidden="true"></i>{currentLabel}
          </span>
          <button
            class="so-tts"
            class:on={playingCurrent}
            onclick={speakCurrent}
            disabled={ttsBlocked}
            title={loadingCurrent ? '再点一次取消生成' : ttsTitle}
            aria-label={playingCurrent || loadingCurrent ? '停止朗读当前稿' : '朗读当前稿'}
          >
            {#if loadingCurrent}
              <span class="spin"></span><span>生成中</span>
            {:else if playingCurrent}
              <Icon name="stop" size={10} /><span>停止</span>
            {:else}
              <Icon name="speaker" size={11} /><span>朗读</span>
            {/if}
          </button>
        </div>
        <div class="so-text" class:blank={!text}>
          {#if text}
            {#each diff.ops as op, i (i)}
              {#if op.op === 'eq'}
                {op.text}
              {:else if op.op === 'del'}
                <mark class="del" title="只在当前稿里出现">{op.text}</mark>
              {/if}
            {/each}
          {:else}
            <span class="placeholder">∅</span>
          {/if}
        </div>
      </article>

      <article class="so-card alt">
        <div class="so-card-head">
          <span class="so-engine alt" title={altLabel}>
            <i class="so-dot" aria-hidden="true"></i>{altLabel}
          </span>
          {#if diff.equal}
            <span class="so-badge same">两版一致</span>
          {:else}
            <span class="so-badge diff">{diff.hunks} 处不同</span>
          {/if}
          <button
            class="so-tts"
            class:on={playingAlt}
            onclick={speakAlt}
            disabled={ttsBlocked}
            title={loadingAlt ? '再点一次取消生成' : ttsTitle}
            aria-label={playingAlt || loadingAlt ? '停止朗读另一引擎稿' : '朗读另一引擎稿'}
          >
            {#if loadingAlt}
              <span class="spin"></span><span>生成中</span>
            {:else if playingAlt}
              <Icon name="stop" size={10} /><span>停止</span>
            {:else}
              <Icon name="speaker" size={11} /><span>朗读</span>
            {/if}
          </button>
        </div>
        <div class="so-text" class:blank={!altText}>
          {#if altText}
            {#each diff.ops as op, i (i)}
              {#if op.op === 'eq'}
                {op.text}
              {:else if op.op === 'ins'}
                <mark class="ins" title="只在另一引擎稿里出现">{op.text}</mark>
              {/if}
            {/each}
          {:else}
            <span class="placeholder">∅</span>
          {/if}
        </div>
      </article>
    </div>

    <ArbitrationCard {index} textA={text} textB={altText} />

    <div class="so-actions">
      <button
        class="btn primary mini"
        onclick={adopt}
        title="把这一版写回当前字幕（可 ⌘Z 撤销）"
      >采用 B 版</button>
      <button
        class="btn ghost mini"
        onclick={retry}
        disabled={busy || !readyEngine}
        title={readyLabel
          ? `用 ${readyLabel} 重新听这一句（换引擎要重新加载模型，约 20–40 秒）`
          : '没有可用的复核引擎'}
      >{retryLabel}</button>
      <button class="btn ghost mini" onclick={() => dismissAlternative()}>收起</button>
    </div>
  {:else}
    {#if failed}
      <div class="so-tip warn">{failed}</div>
    {:else if !engineHint}
      <p class="so-tip">{tip}</p>
    {/if}
    {#if engineHint}
      <p class="so-tip hint">{engineHint}</p>
    {:else}
      <p class="so-tip">出两版后，可在这里让 AI 结合上下文判定第三版。</p>
    {/if}
    {#if !readyEngine}
      <button
        class="so-run"
        onclick={() => setView('settings')}
        title="到「设置 → 引擎与模型」启用并下载一个与当前稿同语种的引擎"
      >
        <Icon name="gear" size={12} />
        <span>去设置启用复核引擎</span>
      </button>
    {:else}
      <button
        class="so-run"
        onclick={run}
        disabled={busy}
        title={busy
          ? '有任务在跑（同一时间只允许一个重任务），结束后再复核'
          : `把这一句送给 ${readyLabel} 再听一遍（换引擎约 20–40 秒）`}
      >
        <Icon name="speaker" size={12} />
        <span>{failed ? '重试' : `用 ${readyShort} 再听一遍`}</span>
      </button>
    {/if}
  {/if}
</section>

<style>
  .second-opinion {
    margin-top: var(--sp-4);
    padding: var(--sp-3) 0 0;
    border-top: 1px solid var(--line-2);
    display: flex;
    flex-direction: column;
    gap: var(--sp-2);
  }

  .so-head {
    display: flex;
    align-items: center;
    gap: var(--sp-2);
    min-width: 0;
  }
  .so-head b {
    flex: 1 1 auto;
    min-width: 0;
    font-size: 12px;
    line-height: 16px;
    font-weight: 600;
    color: var(--ink-2);
    white-space: nowrap;
  }
  .so-pick {
    flex: 0 0 auto;
    display: flex;
    align-items: center;
    gap: var(--sp-1);
    min-width: 0;
  }
  .so-from {
    max-width: 92px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    font-size: 11px;
    line-height: 15px;
    color: var(--text-3);
  }
  .so-arrow {
    color: var(--text-3);
    font-size: 10px;
    line-height: 1;
  }
  .so-none {
    display: inline-flex;
    align-items: center;
    height: 22px;
    padding: 0 7px;
    border-radius: 6px;
    background: var(--fill);
    color: var(--text-3);
    font-size: 11px;
    line-height: 12px;
    white-space: nowrap;
  }
  .so-select-wrap {
    position: relative;
    display: flex;
    align-items: center;
    height: 26px;
    border-radius: 6px;
    background: var(--fill);
  }
  .so-select {
    appearance: none;
    -webkit-appearance: none;
    width: 100%;
    height: 100%;
    min-width: 0;
    max-width: 132px;
    padding: 0 19px 0 var(--sp-2);
    border: 0;
    border-radius: 6px;
    background: transparent;
    color: var(--ink);
    font: inherit;
    font-size: 12px;
    line-height: 16px;
    cursor: pointer;
    text-overflow: ellipsis;
  }
  .so-select:disabled {
    color: var(--text-3);
    cursor: default;
  }
  .so-select:focus-visible {
    outline: 2px solid var(--accent-ring);
    outline-offset: 1px;
  }
  .so-select-wrap > :global(svg) {
    position: absolute;
    right: 6px;
    pointer-events: none;
    color: var(--ink-3);
  }

  .so-progress {
    height: 3px;
    border-radius: 2px;
    background: var(--line-2);
    overflow: hidden;
  }
  .so-progress i {
    display: block;
    height: 100%;
    background: var(--accent);
    transition: width 0.12s linear;
  }
  .so-stage {
    color: var(--text-3);
    font-size: 11px;
    line-height: 15px;
  }

  .so-tip {
    margin: 0;
    color: var(--text-3);
    font-size: 11.5px;
    line-height: 1.55;
  }
  .so-tip.hint {
    color: var(--warn);
  }
  .so-tip.warn {
    color: var(--danger);
  }

  .so-pair {
    display: flex;
    flex-direction: column;
    gap: 6px;
  }
  .so-card {
    padding: 7px 9px var(--sp-2);
    border: 1px solid var(--line-2);
    border-radius: 8px;
    background: var(--raise);
    box-shadow: 0 1px 1px rgba(27, 39, 64, 0.03);
    min-width: 0;
  }
  .so-card.alt {
    border-color: var(--accent-line);
    background: color-mix(in srgb, var(--accent-soft) 40%, var(--raise));
  }
  .so-card-head {
    display: flex;
    align-items: center;
    gap: 6px;
    min-width: 0;
    margin-bottom: var(--sp-1);
  }
  .so-engine {
    flex: 1 1 auto;
    min-width: 0;
    display: inline-flex;
    align-items: center;
    gap: 5px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    font-size: 10.5px;
    line-height: 14px;
    color: var(--text-3);
  }
  .so-engine.alt {
    color: var(--accent-hover);
  }
  .so-dot {
    flex: none;
    width: 5px;
    height: 5px;
    border-radius: 50%;
    background: var(--ink-3);
  }
  .so-engine.alt .so-dot {
    background: var(--accent);
  }

  .so-badge {
    flex: 0 0 auto;
    height: 17px;
    padding: 0 6px;
    border-radius: 999px;
    font-size: 10px;
    line-height: 17px;
    font-weight: 600;
    white-space: nowrap;
  }
  .so-badge.diff {
    color: var(--warn);
    background: var(--warn-soft);
  }
  .so-badge.same {
    color: var(--success);
    background: var(--success-soft);
  }

  .so-tts {
    appearance: none;
    flex: 0 0 auto;
    display: inline-flex;
    align-items: center;
    gap: 3px;
    height: 22px;
    padding: 0 7px;
    border: 1px solid var(--line-2);
    border-radius: 6px;
    background: transparent;
    color: var(--ink-2);
    font: inherit;
    font-size: 11px;
    line-height: 1;
    white-space: nowrap;
    cursor: pointer;
    transition: color var(--dur-fast) var(--ease), border-color var(--dur-fast) var(--ease),
      background var(--dur-fast) var(--ease);
  }
  .so-tts:hover:not(:disabled),
  .so-tts.on {
    color: var(--accent-hover);
    border-color: var(--accent-line);
    background: var(--accent-soft);
  }
  .so-tts:focus-visible,
  .so-run:focus-visible {
    outline: 2px solid var(--accent-ring);
    outline-offset: 2px;
  }
  .so-tts:disabled {
    opacity: 0.55;
    cursor: default;
  }
  .so-tts .spin {
    width: 9px;
    height: 9px;
    border-width: 1.4px;
  }

  .so-text {
    font-family: var(--font-cue);
    font-size: 15px;
    line-height: 1.6;
    font-weight: 500;
    color: var(--ink);
    white-space: pre-wrap;
    word-break: break-word;
    letter-spacing: -0.01em;
  }
  .so-text.blank {
    color: var(--text-3);
    font-weight: 400;
  }
  .placeholder {
    color: color-mix(in srgb, var(--text-3) 60%, transparent);
  }
  mark {
    border-radius: 2px;
    padding: 0 1px;
    color: inherit;
  }
  mark.del {
    background: color-mix(in srgb, var(--danger) 20%, transparent);
    text-decoration: line-through;
    text-decoration-color: color-mix(in srgb, var(--danger) 60%, transparent);
    text-decoration-thickness: 1px;
  }
  mark.ins {
    background: color-mix(in srgb, var(--success) 26%, transparent);
  }

  .so-actions {
    display: flex;
    align-items: center;
    gap: var(--sp-1);
  }
  .so-actions .btn.primary {
    flex: 0 0 auto;
  }
  .mini {
    height: 26px;
    font-size: 12px;
    padding: 0 var(--sp-2);
  }

  .so-run {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 5px;
    width: 100%;
    height: 30px;
    padding: 0 10px;
    border: 1px solid var(--accent-line);
    border-radius: 7px;
    background: var(--accent-soft);
    color: var(--accent-hover);
    font: inherit;
    font-size: 12px;
    font-weight: 600;
    line-height: 1;
    white-space: nowrap;
    cursor: pointer;
    transition: background var(--dur-fast) var(--ease), border-color var(--dur-fast) var(--ease);
  }
  .so-run:hover:not(:disabled) {
    border-color: var(--accent);
    background: color-mix(in srgb, var(--accent-soft) 70%, var(--raise));
  }
  .so-run:active:not(:disabled) {
    transform: scale(0.99);
  }
  .so-run:disabled {
    color: var(--text-3);
    border-color: var(--line-2);
    background: var(--fill);
    cursor: default;
  }

  .spin {
    width: 9px;
    height: 9px;
    border-radius: 50%;
    border: 1.5px solid currentColor;
    border-top-color: transparent;
    animation: so-spin 650ms linear infinite;
  }
  @keyframes so-spin {
    to {
      transform: rotate(360deg);
    }
  }
</style>
