<script lang="ts">
  /**
   * 单句 AI 判定卡片：A/B 两版之外的第三版建议。
   *
   * 只读展示，不自动采用；采用走 `adoptArbitration()` → `updateCue()`，
   * 服务端压一步统一历史。
   */
  import { onDestroy } from 'svelte';
  import Icon from './Icon.svelte';
  import {
    arbitration,
    arbitrationRecord,
    arbitrateModelName,
    adoptArbitration,
    cancelArbitration,
    dismissArbitration,
    loadArbitrationConfig,
    runArbitration,
    usesArbitrateOverride,
  } from '../lib/arbitration.svelte';
  import { adoptLabel, canAdopt, classifyText, type ArbitrationMatch } from '../lib/arbitration';
  import { charDiff } from '../lib/textDiff';
  import {
    cloneEngineReady,
    setView,
    speakTextTagged,
    stopTts,
    tts,
    ttsVoice,
  } from '../lib/store.svelte';

  let { index, textA, textB }: { index: number; textA: string; textB: string } = $props();

  const cfg = $derived(arbitration.config);
  const record = $derived(arbitrationRecord(index));
  const running = $derived(arbitration.runningIndex === index);
  const error = $derived(arbitration.errors[index] || '');
  const override = $derived(usesArbitrateOverride(cfg));
  const modelName = $derived(arbitrateModelName(cfg) || 'AI');
  const match: ArbitrationMatch = $derived(
    record ? classifyText(textA, textB, record.text) : 'third',
  );
  const different = $derived(Boolean((textA.trim() || textB.trim()) && textA.trim() !== textB.trim()));

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

  // 每次卡片挂载都强制读一次配置：设置页改了自动判定 / 档位 / 覆盖模型后，
  // 从设置返回核对台不会拿到模块里的旧缓存。
  $effect(() => {
    void loadArbitrationConfig(true);
  });

  // 切换句子 / 改 A / 改 B 都中断在途判定；卡片卸载（换到没有 B 的句子、离开核对台）
  // 也取消。请求本身由 AbortController 中断，服务端短请求会自行结束。
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

  function adopt() {
    void adoptArbitration(index);
  }

  function retry() {
    void runArbitration(index);
  }

  function dismiss() {
    dismissArbitration(index);
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
  </div>

  {#if running}
    <div class="arb-running" role="status">
      <span class="spin"></span>
      <span>{arbitration.stage || 'AI 正在判定…'}</span>
      <button class="arb-link" onclick={() => cancelArbitration()}>取消</button>
    </div>
  {:else if record}
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
      <div class="arb-actions">
        {#if canAdopt(match)}
          <button class="btn primary mini" onclick={adopt} title="写回当前字幕（可 ⌘Z 撤销）">
            {adoptLabel(match)}
          </button>
        {/if}
        <button class="btn ghost mini" onclick={retry}>重新判定</button>
        <button class="btn ghost mini" onclick={dismiss}>收起</button>
      </div>
    </article>
  {:else}
    {#if !different}
      <p class="arb-tip">两版一致，不需要 AI 判定。</p>
    {:else if setupHint}
      <p class="arb-tip warn">{setupHint}</p>
      <button class="arb-run" onclick={goSettings} title="打开设置 → AI 优化">
        <Icon name="gear" size={12} />
        <span>{cfg ? '去设置' : '重试读取配置'}</span>
      </button>
    {:else}
      <p class="arb-tip">
        把这一句的 A/B 两版和前后各 3 句上下文交给 AI；不发送时间轴、音频或截图。
      </p>
      {#if error}
        <p class="arb-tip warn">{error}</p>
      {/if}
      <button class="arb-run" onclick={retry} title="只发送文本，调用会计入你的模型额度">
        <Icon name="sparkle" size={12} />
        <span>{error ? '重试 AI 判定' : '让 AI 判定'}</span>
      </button>
    {/if}
  {/if}
</section>

<style>
  .arb {
    display: flex;
    flex-direction: column;
    gap: var(--sp-2);
    padding-top: var(--sp-2);
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
  .arb-tip {
    margin: 0;
    color: var(--text-3);
    font-size: 11.5px;
    line-height: 1.55;
  }
  .arb-tip.warn {
    color: var(--warn);
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
  .arb-run:hover {
    border-color: var(--accent);
    background: color-mix(in srgb, var(--accent-soft) 70%, var(--raise));
  }
  .arb-run:active {
    transform: scale(0.99);
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
