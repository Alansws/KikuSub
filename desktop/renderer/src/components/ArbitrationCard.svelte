<script lang="ts">
  /**
   * 单句 AI 辅助卡片：A/B 之外的第三版，也负责「ASR 全没识别 + 听音线索」的还原。
   *
   * 常驻在检查器里：只要选中了任意字幕行（含空字幕块、B 引擎未跑或返回空）就能用。
   * 只读展示，不自动采用；采用走 `adoptArbitration()` → `updateCue()`，服务端压一步
   * 统一历史。多轮对话的完整历史在 `ArbitrationDialog.svelte` 浮窗里。
   */
  import { onDestroy } from 'svelte';
  import Icon from './Icon.svelte';
  import CopyTextButton from './CopyTextButton.svelte';
  import {
    arbitration,
    arbitrationDraft,
    arbitrationHasResult,
    arbitrationMessages,
    arbitrationRecord,
    arbitrationThreadStale,
    arbitrateModelName,
    adoptArbitration,
    cancelArbitration,
    loadArbitrationConfig,
    openArbitrationDialog,
    rejudgeArbitration,
    resetArbitrationThread,
    runArbitration,
    sendArbitrationFollowUp,
    setArbitrationDraft,
    usesArbitrateOverride,
  } from '../lib/arbitration.svelte';
  import {
    MAX_HINT_CHARS,
    adoptLabel,
    arbitrationButtonLabel,
    canAdopt,
    classifyText,
    contextFor,
    hasFollowUpHistory,
    rejudgeButtonLabel,
    type ArbitrationMatch,
  } from '../lib/arbitration';
  import { charDiff } from '../lib/textDiff';
  import {
    app,
    cloneEngineReady,
    setView,
    speakTextTagged,
    stopTts,
    tts,
    ttsVoice,
  } from '../lib/store.svelte';

  let {
    index,
    textA,
    textB,
    bAttempted = false,
  }: { index: number; textA: string; textB: string; bAttempted?: boolean } = $props();

  const cfg = $derived(arbitration.config);
  const record = $derived(arbitrationRecord(index));
  const running = $derived(arbitration.runningIndex === index);
  const busyElsewhere = $derived(
    arbitration.runningIndex >= 0 && arbitration.runningIndex !== index,
  );
  const error = $derived(arbitration.errors[index] || '');
  const override = $derived(usesArbitrateOverride(cfg));
  const modelName = $derived(arbitrateModelName(cfg) || 'AI');
  const match: ArbitrationMatch = $derived(
    record ? classifyText(textA, textB, record.text) : 'third',
  );
  const draft = $derived(arbitrationDraft(index));
  const messages = $derived(arbitrationMessages(index));
  const hasResult = $derived(arbitrationHasResult(index) || Boolean(record));
  const hasHistory = $derived(hasFollowUpHistory(messages));
  const stale = $derived(arbitrationThreadStale(index));
  const bEmpty = $derived(bAttempted && !textB.trim());
  const runLabel = $derived(
    arbitrationButtonLabel({ textA, textB, hint: draft, hasRecord: hasResult }),
  );
  const mainLabel = $derived(
    hasResult ? rejudgeButtonLabel(hasHistory) : runLabel,
  );
  const mainTitle = $derived.by(() => {
    if (!hasResult) return '只发送文本，调用会计入你的模型额度';
    if (hasHistory) {
      return '清空这一句的追问记录与 AI 回复，按原始 A/B 与上下文重新判定；输入框里新写的线索会作为本次线索';
    }
    return '按原始 A/B 与上下文重新判定；输入框里新写的线索会作为本次线索';
  });
  const context = $derived(contextFor(app.cues, index));
  const hasMaterials = $derived(
    Boolean(
      textA.trim() ||
        textB.trim() ||
        draft.trim() ||
        hasResult ||
        context.before.length ||
        context.after.length,
    ),
  );
  const canSendFollowUp = $derived(
    Boolean(hasResult && draft.trim() && !running && !busyElsewhere && !stale),
  );

  const configured = $derived(Boolean(cfg?.base_url && cfg?.model));
  const keyReady = $derived(
    override
      ? arbitration.hasArbKey || arbitration.hasGlobalKey || Boolean(cfg?.arbitrate_key_optional)
      : arbitration.hasGlobalKey || Boolean(cfg?.key_optional),
  );
  const setupHint = $derived.by(() => {
    if (!cfg) return arbitration.configLoading ? '正在读取 AI 配置…' : arbitration.configError;
    if (!cfg.enabled) return 'AI 优化未启用';
    if (!configured) return '还没有配置 AI 服务';
    if (!keyReady) return override ? '单句判定模型还没有配置 Key' : '还没有配置 API Key';
    return '';
  });

  const diff = $derived(charDiff(textA || '', record?.text || ''));
  const tag = $derived(`arb:${index}`);
  const playing = $derived(tts.playing && tts.tag === tag);
  const loading = $derived(tts.loading && tts.tag === tag);
  const ttsBlocked = $derived(
    !tts.loaded || !tts.available || (ttsVoice()?.kind === 'clone' && !cloneEngineReady()),
  );
  const hintId = $derived(`arb-hint-${index}`);

  // 每次卡片挂载都强制读一次配置：设置页改了自动判定 / 档位 / 覆盖模型后，
  // 从设置返回核对台不会拿到模块里的旧缓存。
  $effect(() => {
    void loadArbitrationConfig(true);
  });

  // 切换句子 / 改 A / 改 B 都中断在途判定；卡片卸载（离开核对台）也取消。
  // 请求本身由 AbortController 中断，服务端短请求会自行结束。
  let lastContextKey = '';
  $effect(() => {
    const key = `${index}|${textA}|${textB}`;
    if (!lastContextKey) {
      lastContextKey = key;
      return;
    }
    if (key === lastContextKey) return;
    lastContextKey = key;
    if (arbitration.runningIndex >= 0) cancelArbitration();
  });

  onDestroy(() => {
    if (arbitration.runningIndex >= 0) cancelArbitration();
  });

  function speakResult() {
    if (playing || loading) {
      stopTts();
      return;
    }
    if (record) void speakTextTagged(record.text, tag);
  }

  function runInitial() {
    if (stale) return;
    void runArbitration(index, { mode: 'initial' });
  }

  function sendFollowUp() {
    if (!canSendFollowUp) return;
    sendArbitrationFollowUp(index);
  }

  function rejudge() {
    if (stale) return;
    rejudgeArbitration(index);
  }

  function onHintKeydown(event: KeyboardEvent) {
    if ((event.metaKey || event.ctrlKey) && event.key === 'Enter') {
      event.preventDefault();
      if (hasResult) {
        if (draft.trim()) sendFollowUp();
      } else {
        runInitial();
      }
    }
  }

  function onHintInput(event: Event) {
    const input = event.currentTarget as HTMLTextAreaElement;
    setArbitrationDraft(index, input.value);
  }

  function reset() {
    resetArbitrationThread(index);
  }

  function expand() {
    openArbitrationDialog(index);
  }

  function adopt() {
    void adoptArbitration(index);
  }

  function goSettings() {
    setView('settings');
  }
</script>

<section class="arb" aria-label="AI 判定">
  <div class="arb-head">
    <b>AI 判定</b>
    {#if record}
      <span class="arb-model" title="本次判定使用的模型">{record.model || modelName}</span>
    {/if}
    <button
      class="arb-expand"
      onclick={expand}
      title="展开多轮对话浮窗：完整历史、每轮朗读与采用"
    >
      <Icon name="display" size={11} />
      <span>展开对话</span>
    </button>
  </div>

  {#if stale}
    <p class="arb-tip warn">这一句的时间或文本已改动，之前的对话已失效。</p>
    <button class="arb-run" onclick={reset} title="清掉这一句的临时对话，重新开始">
      <Icon name="sparkle" size={12} />
      <span>重置对话后重新开始</span>
    </button>
  {:else if setupHint && !record}
    <p class="arb-tip warn">{setupHint}</p>
    <button class="arb-run" onclick={goSettings} title="打开设置 → AI 优化">
      <Icon name="gear" size={12} />
      <span>{cfg ? '去设置' : '重试读取配置'}</span>
    </button>
  {:else}
    <div class="arb-hint">
      <div class="arb-hint-head">
        <label for={hintId}>{hasResult ? '补充线索 / 追问' : '听音线索（可选）'}</label>
        {#if hasResult}
          <button class="arb-link" onclick={reset} title="清掉这一句的临时对话与结果">
            重置对话
          </button>
        {/if}
      </div>
      <textarea
        id={hintId}
        rows="2"
        title="空耳 / 罗马音都行：例「斯国一 / sugoi」。只发送文本，不发送时间轴、音频或截图"
        maxlength={MAX_HINT_CHARS}
        value={draft}
        placeholder={hasResult
          ? '补充新的听音线索，或继续追问…'
          : '例：斯国一 / sugoi / 声音很小，像「やばい」'}
        oninput={onHintInput}
        onkeydown={onHintKeydown}
      ></textarea>
      <div class="arb-hint-foot">
        <span>只发文本 · 不进历史</span>
        {#if hasResult}
          <button
            class="arb-send-followup"
            type="button"
            onclick={sendFollowUp}
            disabled={!canSendFollowUp}
            title={!draft.trim()
              ? '先在输入框里写下一条新线索'
              : '把输入框里的线索追加到当前对话并追问 AI（⌘↩）'}
          >发送追问</button>
        {:else}
          <span>⌘↩ 发送</span>
        {/if}
      </div>
    </div>

    {#if bEmpty}
      <p class="arb-tip hint">另一引擎未识别到内容，可补充听音线索直接让 AI 推断。</p>
    {/if}
    {#if !hasMaterials}
      <p class="arb-tip">这一句还没有文本、线索或上下文；先补一条听音线索再让 AI 推断。</p>
    {/if}
    {#if error}
      <p class="arb-tip warn">{error}</p>
    {/if}
    {#if setupHint}
      <p class="arb-tip warn">{setupHint}</p>
    {/if}

    {#if running}
      <div class="arb-running" role="status">
        <span class="spin"></span>
        <span>{arbitration.stage || 'AI 正在判定…'}</span>
        <button class="arb-link" onclick={() => cancelArbitration()}>取消</button>
      </div>
    {:else if !setupHint}
      <button
        class="arb-run"
        onclick={hasResult ? rejudge : runInitial}
        disabled={busyElsewhere || !hasMaterials}
        title={!hasMaterials
          ? '这一句还没有可发送的文本、线索或上下文'
          : busyElsewhere
            ? 'AI 正在判定另一句，等它完成或取消后再试'
            : mainTitle}
      >
        <Icon name="sparkle" size={12} />
        <span>{busyElsewhere ? 'AI 正在判定另一句…' : mainLabel}</span>
      </button>
    {/if}

    {#if record}
      <article class="arb-card">
        <div class="arb-card-head">
          <span class="arb-engine" title={record.model || modelName}>
            <i class="arb-dot" aria-hidden="true"></i>{record.model || modelName}
          </span>
          {#if match === 'a'}
            <span class="arb-badge same">与当前稿一致</span>
          {:else if match === 'b'}
            <span class="arb-badge same">与 B 版相同</span>
          {:else}
            <span class="arb-badge third">第三版 · {diff.hunks} 处不同</span>
          {/if}
          <button
            class="arb-tts"
            class:on={playing}
            onclick={speakResult}
            disabled={ttsBlocked}
            title={loading ? '再点一次取消生成' : '用下方 TTS 对照的同一音色朗读 AI 版'}
            aria-label={playing || loading ? '停止朗读 AI 版' : '朗读 AI 版'}
          >
            {#if loading}
              <span class="spin"></span><span>生成中</span>
            {:else if playing}
              <Icon name="stop" size={10} /><span>停止</span>
            {:else}
              <Icon name="speaker" size={11} /><span>朗读</span>
            {/if}
          </button>
          <CopyTextButton text={record.text} title="复制 AI 判定文本（与当前稿一致时也可复制）" />
        </div>
        <div class="arb-text">
          {#each diff.ops as op, i (i)}
            {#if op.op === 'eq'}
              {op.text}
            {:else if op.op === 'ins'}
              <mark class="ins" title="只在 AI 版里出现">{op.text}</mark>
            {/if}
          {/each}
        </div>
        {#if record.note}
          <p class="arb-note">理由：{record.note}</p>
        {/if}
        {#if canAdopt(match)}
          <div class="arb-actions">
            <button class="btn primary mini" onclick={adopt} title="写回当前字幕（可 ⌘Z 撤销）">
              {adoptLabel(match)}
            </button>
          </div>
        {/if}
      </article>
    {/if}
  {/if}
</section>

<style>
  .arb {
    display: flex;
    flex-direction: column;
    gap: 6px;
    padding-top: 6px;
    border-top: 1px dashed var(--line-2);
  }
  .arb-head {
    display: flex;
    align-items: center;
    gap: var(--sp-2);
    min-width: 0;
  }
  .arb-head b {
    flex: 1 1 auto;
    min-width: 0;
    font-size: 12px;
    line-height: 16px;
    font-weight: 600;
    color: var(--ink-2);
  }
  .arb-model {
    max-width: 132px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    font-size: 10.5px;
    color: var(--text-3);
  }
  .arb-expand {
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
  .arb-expand:hover {
    color: var(--accent-hover);
    border-color: var(--accent-line);
    background: var(--accent-soft);
  }
  .arb-tip {
    margin: 0;
    color: var(--text-3);
    font-size: 11.5px;
    line-height: 1.45;
  }
  .arb-tip.warn {
    color: var(--warn);
  }
  .arb-tip.hint {
    color: var(--accent-hover);
  }
  .arb-hint {
    display: flex;
    flex-direction: column;
    gap: var(--sp-1);
    padding: 7px var(--sp-2) 6px;
    border: 1px solid var(--line-2);
    border-radius: 7px;
    background: var(--raise);
  }
  .arb-hint-head {
    display: flex;
    align-items: center;
    gap: var(--sp-2);
  }
  .arb-hint-head label {
    flex: 1 1 auto;
    min-width: 0;
    font-size: 10.5px;
    font-weight: 600;
    color: var(--text-3);
  }
  .arb-hint textarea {
    width: 100%;
    min-height: 34px;
    max-height: 96px;
    resize: vertical;
    padding: 5px 7px;
    border: 1px solid var(--line-2);
    border-radius: 5px;
    background: var(--base);
    color: var(--ink);
    font: inherit;
    font-size: 12px;
    line-height: 1.45;
  }
  .arb-hint textarea:focus {
    outline: none;
    border-color: var(--accent-line);
    box-shadow: 0 0 0 2px var(--accent-soft);
  }
  .arb-hint-foot {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--sp-2);
    font-size: 10px;
    color: var(--text-3);
  }
  .arb-send-followup {
    appearance: none;
    flex: 0 0 auto;
    height: 22px;
    padding: 0 var(--sp-2);
    border: 1px solid var(--accent-line);
    border-radius: 6px;
    background: var(--accent-soft);
    color: var(--accent-hover);
    font: inherit;
    font-size: 10.5px;
    font-weight: 600;
    line-height: 1;
    white-space: nowrap;
    cursor: pointer;
  }
  .arb-send-followup:hover:not(:disabled) {
    border-color: var(--accent);
    background: color-mix(in srgb, var(--accent-soft) 70%, var(--raise));
  }
  .arb-send-followup:disabled {
    opacity: 0.55;
    cursor: default;
  }
  .arb-running {
    display: flex;
    align-items: center;
    gap: 6px;
    font-size: 11.5px;
    color: var(--text-3);
  }
  .arb-link {
    appearance: none;
    flex: 0 0 auto;
    border: 0;
    background: transparent;
    color: var(--accent-hover);
    font: inherit;
    font-size: 11px;
    cursor: pointer;
    padding: 0;
  }
  .arb-card {
    padding: 7px 9px var(--sp-2);
    border: 1px solid var(--accent-line);
    border-radius: 8px;
    background: color-mix(in srgb, var(--accent-soft) 36%, var(--raise));
    min-width: 0;
  }
  .arb-card-head {
    display: flex;
    align-items: center;
    gap: 6px;
    min-width: 0;
    margin-bottom: var(--sp-1);
  }
  .arb-engine {
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
    color: var(--accent-hover);
  }
  .arb-dot {
    flex: none;
    width: 5px;
    height: 5px;
    border-radius: 50%;
    background: var(--accent);
  }
  .arb-badge {
    flex: 0 0 auto;
    height: 17px;
    padding: 0 6px;
    border-radius: 999px;
    font-size: 10px;
    line-height: 17px;
    font-weight: 600;
    white-space: nowrap;
  }
  .arb-badge.third {
    color: var(--accent-hover);
    background: var(--accent-soft);
  }
  .arb-badge.same {
    color: var(--success);
    background: var(--success-soft);
  }
  .arb-tts {
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
  }
  .arb-tts:hover:not(:disabled),
  .arb-tts.on {
    color: var(--accent-hover);
    border-color: var(--accent-line);
    background: var(--accent-soft);
  }
  .arb-tts:disabled {
    opacity: 0.55;
    cursor: default;
  }
  .arb-text {
    font-family: var(--font-cue);
    font-size: 15px;
    line-height: 1.6;
    font-weight: 500;
    color: var(--ink);
    white-space: pre-wrap;
    word-break: break-word;
    letter-spacing: -0.01em;
    user-select: text;
    -webkit-user-select: text;
    cursor: text;
  }
  mark {
    border-radius: 2px;
    padding: 0 1px;
    color: inherit;
  }
  mark.ins {
    background: color-mix(in srgb, var(--success) 26%, transparent);
  }
  .arb-note {
    margin: var(--sp-1) 0 0;
    color: var(--text-3);
    font-size: 11px;
    line-height: 1.5;
    user-select: text;
    -webkit-user-select: text;
    cursor: text;
  }
  .arb-actions {
    display: flex;
    align-items: center;
    gap: var(--sp-1);
    margin-top: var(--sp-2);
  }
  .arb-run {
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
  }
  .arb-run:hover:not(:disabled) {
    border-color: var(--accent);
    background: color-mix(in srgb, var(--accent-soft) 70%, var(--raise));
  }
  .arb-run:active:not(:disabled) {
    transform: scale(0.99);
  }
  .arb-run:disabled {
    opacity: 0.6;
    cursor: default;
  }
  .mini {
    height: 26px;
    font-size: 12px;
    padding: 0 var(--sp-2);
  }
  .spin {
    width: 9px;
    height: 9px;
    border-radius: 50%;
    border: 1.5px solid currentColor;
    border-top-color: transparent;
    animation: arb-spin 650ms linear infinite;
  }
  @keyframes arb-spin {
    to {
      transform: rotate(360deg);
    }
  }
</style>
