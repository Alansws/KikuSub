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
  import CopyTextButton from './CopyTextButton.svelte';
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
    openArbitrationDialog,
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
    void runArbitration(index, { mode: 'auto' });
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

  // 说明只有一行：这一块占的是「无需滚动即可操作」的高度预算，第二句交给 AI 卡片自己说。
  const tip = $derived.by(() => {
    const target = readyLabel || '另一个引擎';
    return `把这一句送给「${target}」再听一遍；采用后才进历史。`;
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

  /** 「展开对话」原来在 ArbitrationCard 的标题行里；三版合流后标题行只有一个。 */
  function expandDialog() {
    openArbitrationDialog(index);
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

<section class="second-opinion" aria-label="三版对照">
  <div class="so-head">
    <b>三版对照</b>
    <div class="so-pick">
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
    <button
      class="so-expand arb-expand"
      type="button"
      onclick={expandDialog}
      title="展开多轮对话浮窗：完整历史、每轮朗读与采用"
    >
      <Icon name="display" size={11} />
      <span>展开对话</span>
    </button>
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
            <i class="so-dot" aria-hidden="true"></i>
            <b class="so-role">当前稿</b>
            <span class="so-name">{currentEngineShortLabel()}</span>
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
          <CopyTextButton text={text} title="复制当前稿这句文本" />
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
            <i class="so-dot" aria-hidden="true"></i>
            <b class="so-role">另一引擎</b>
            <span class="so-name">{readyShort}</span>
          </span>
          {#if !text.trim() && !altText.trim()}
            <span class="so-badge same">两版均无内容</span>
          {:else if diff.equal}
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
          <CopyTextButton text={altText} title="复制另一引擎这句文本" />
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

    <div class="so-actions">
      <button
        class="btn primary mini"
        onclick={adopt}
        disabled={!altText.trim()}
        title={!altText.trim()
          ? '另一引擎没有识别到内容，暂无可采用的文本'
          : '把这一版写回当前字幕（可 ⌘Z 撤销）'}
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

  <ArbitrationCard {index} textA={text} textB={altText} bAttempted={has} />
</section>

<style>
  /* 三版对照：整块是一张卡，A / B / AI 各占一行。行内不再各套一圈边框——
     348px 宽的右栏里，三张卡 + 两个标题行光边框和内边距就要 ~90px（见契约
     「右侧检查器预算」）。 */
  /* 2026-11-24（Phase 2）去卡片化：这张「卡里再套两张卡」的结构读起来像网页表单。
     现在外层只是检查器里的一个分段（1px 上分割线 + 紧凑内边距），
     A / B 两版之间同样用 1px 线分隔——层级靠线，不靠边框。 */
  .second-opinion {
    display: flex;
    flex-direction: column;
    gap: var(--sp-1);
    margin-top: var(--sp-3);
    padding: var(--sp-3) 0 0;
    border: 0;
    border-top: 1px solid var(--line);
    border-radius: 0;
    background: transparent;
    box-shadow: none;
  }

  .so-head {
    display: flex;
    align-items: center;
    gap: var(--sp-2);
    min-width: 0;
  }
  /* 分区标题与「质检速览 / 任务报告」同一档：11px + 字距，不是 12px 粗体 ——
     检查器里只有台词是主角，分区标题不该和它抢字号。 */
  .so-head b {
    flex: 0 0 auto;
    font-size: var(--fs-label);
    line-height: 16px;
    font-weight: 600;
    letter-spacing: 0.06em;
    color: var(--ink-3);
    white-space: nowrap;
  }
  .so-pick {
    flex: 0 0 auto;
    margin-left: auto;
    display: flex;
    align-items: center;
    gap: var(--sp-1);
    min-width: 0;
  }
  /* 和 A/B 行里的引擎名同一套手感：22px 高的幽灵按钮，不抢标题的注意力 */
  .so-expand {
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
    font-size: 10.5px;
    line-height: 1;
    white-space: nowrap;
    cursor: pointer;
  }
  .so-expand:hover {
    color: var(--accent-hover);
    border-color: var(--accent-line);
    background: var(--accent-soft);
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
    line-height: 1.45;
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
  }
  /* 一行 = 标签行 + 文本行；行与行之间只用一条 1px 分隔线 */
  .so-card {
    padding: 2px 0 3px;
    border: 0;
    border-radius: 0;
    background: transparent;
    box-shadow: none;
    min-width: 0;
  }
  .so-card + .so-card {
    border-top: 1px solid var(--line);
    padding-top: var(--sp-2);
    margin-top: var(--sp-1);
  }
  .so-card.alt {
    border-color: var(--line-2);
    background: transparent;
  }
  .so-card-head {
    display: flex;
    align-items: center;
    gap: 6px;
    min-width: 0;
    margin-bottom: 1px;
  }
  .so-engine {
    flex: 1 1 auto;
    min-width: 0;
    display: inline-flex;
    align-items: center;
    gap: 5px;
    overflow: hidden;
    white-space: nowrap;
    font-size: 10.5px;
    line-height: 14px;
    color: var(--text-3);
  }
  /* 「当前稿 / 另一引擎」是角色，引擎名是值：角色加粗一点，值可以截断 */
  .so-role {
    flex: 0 0 auto;
    font-size: 10.5px;
    font-weight: 600;
    color: var(--ink-2);
  }
  .so-name {
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .so-engine.alt .so-role {
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

  /* 文本行：15px / 1.5，短句一行、长句两行，整块卡的高度才不会随句子抖动 */
  .so-text {
    font-family: var(--font-cue);
    font-size: 15px;
    line-height: 1.5;
    font-weight: 500;
    color: var(--ink);
    white-space: pre-wrap;
    word-break: break-word;
    letter-spacing: -0.01em;
    user-select: text;
    -webkit-user-select: text;
    cursor: text;
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

  /* 复核 CTA：二级按钮（纸面 + 发丝线），不是一条通栏的蓝底横幅。
     一屏只有一个主操作（「更新此行」），蓝色填充留给它；这里靠位置与字数说明
     「这一块可以开始复核」。 */
  .so-run {
    display: inline-flex;
    align-items: center;
    align-self: flex-start;
    gap: 5px;
    height: var(--ctl-h);
    padding: 0 10px;
    border: 1px solid var(--line);
    border-radius: var(--rad-control);
    background: var(--surface);
    color: var(--ink);
    font: inherit;
    font-size: 12px;
    font-weight: 500;
    line-height: 1;
    white-space: nowrap;
    cursor: pointer;
    transition: background var(--dur-fast) var(--ease), border-color var(--dur-fast) var(--ease);
  }
  .so-run :global(svg) {
    color: var(--ink-3);
  }
  .so-run:hover:not(:disabled) {
    border-color: var(--accent-line);
    color: var(--accent-text);
  }
  .so-run:hover:not(:disabled) :global(svg) {
    color: var(--accent-text);
  }
  .so-run:disabled {
    color: var(--ink-muted);
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
