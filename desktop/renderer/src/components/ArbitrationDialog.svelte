<script lang="ts">
  /**
   * 单句 AI 多轮对话浮窗。
   *
   * 右侧检查器太窄，长对话放不下；这里把「上下文 + 完整追问历史 + 每轮朗读/采用」
   * 摊开。浮窗固定在打开时那一句（`arbitration.dialogIndex`），不随选中句跳动；
   * 拖动 / 缩放参考质检浮窗，默认落点避开右侧「试听原声」按钮。
   */
  import { untrack } from 'svelte';
  import Icon from './Icon.svelte';
  import CopyTextButton from './CopyTextButton.svelte';
  import {
    arbitration,
    adoptArbitrationMessage,
    arbitrateModelName,
    arbitrationDraft,
    arbitrationMessages,
    arbitrationThread,
    arbitrationThreadStale,
    canUndoArbitrationFollowUp,
    cancelArbitration,
    closeArbitrationDialog,
    loadArbitrationConfig,
    rejudgeArbitration,
    resetArbitrationThread,
    runArbitration,
    sendArbitrationFollowUp,
    setArbitrationDraft,
    undoArbitrationFrom,
    undoLastArbitrationFollowUp,
  } from '../lib/arbitration.svelte';
  import {
    MAX_HINT_CHARS,
    contextFor,
    hasFollowUpHistory,
    rejudgeButtonLabel,
    type ArbitrationMessage,
  } from '../lib/arbitration';
  import {
    clampFloatBox,
    defaultFloatBox,
    parseFloatBox,
    type FloatBox,
    type Viewport,
  } from '../lib/floatBox';
  import { alternativeText } from '../lib/secondOpinion.svelte';
  import {
    app,
    cloneEngineReady,
    speakTextTagged,
    stopTts,
    tts,
    ttsVoice,
  } from '../lib/store.svelte';
  import { tcShort } from '../lib/time';

  const FLOAT_KEY = 'kikusub.arbitrationDialog.v1';
  const BOX_OPTIONS = { minW: 380, minH: 320, preferredW: 500, preferredH: 580 };
  const EMPTY = '∅';

  function viewport(): Viewport {
    if (typeof window === 'undefined') return { w: 1440, h: 900 };
    return { w: window.innerWidth, h: window.innerHeight };
  }

  function loadBox(): FloatBox {
    const raw = typeof localStorage !== 'undefined' ? localStorage.getItem(FLOAT_KEY) : null;
    return parseFloatBox(raw, viewport(), BOX_OPTIONS) ?? defaultFloatBox(viewport(), BOX_OPTIONS);
  }

  let floatBox = $state<FloatBox>(loadBox());
  let dragState = $state<{ sx: number; sy: number; x: number; y: number } | null>(null);
  let resizeState = $state<{ sx: number; sy: number; w: number; h: number } | null>(null);
  let listEl = $state<HTMLDivElement | null>(null);
  const dragging = $derived(Boolean(dragState));
  const resizing = $derived(Boolean(resizeState));
  const panelStyle = $derived(
    `left:${floatBox.x}px;top:${floatBox.y}px;width:${floatBox.w}px;height:${floatBox.h}px;`,
  );

  const index = $derived(arbitration.dialogIndex);
  const cue = $derived(app.cues[index]);
  const textA = $derived(cue?.text ?? '');
  const textB = $derived(cue ? alternativeText(index) : '');
  const thread = $derived(arbitrationThread(index));
  const messages = $derived(arbitrationMessages(index));
  const draft = $derived(arbitrationDraft(index));
  const stale = $derived(arbitrationThreadStale(index));
  const running = $derived(arbitration.runningIndex === index);
  const busyElsewhere = $derived(
    arbitration.runningIndex >= 0 && arbitration.runningIndex !== index,
  );
  const error = $derived(arbitration.errors[index] || '');
  const cfg = $derived(arbitration.config);
  const modelName = $derived(arbitrateModelName(cfg) || 'AI');
  const context = $derived(contextFor(app.cues, index));
  const hasConversation = $derived(messages.length > 0);
  const hasHistory = $derived(hasFollowUpHistory(messages));
  const rejudgeLabel = $derived(rejudgeButtonLabel(hasHistory));
  const canSend = $derived(
    !stale &&
      !running &&
      !busyElsewhere &&
      (hasConversation ? Boolean(draft.trim()) : true),
  );
  const canUndoLast = $derived(canUndoArbitrationFollowUp(index));
  const ttsBlocked = $derived(
    !tts.loaded || !tts.available || (ttsVoice()?.kind === 'clone' && !cloneEngineReady()),
  );

  $effect(() => {
    void loadArbitrationConfig();
  });

  $effect(() => {
    if (arbitration.dialogOpen && !app.cues[arbitration.dialogIndex]) {
      closeArbitrationDialog();
    }
  });

  // 新消息后滚到底部；只在条数变化时触发，不打断用户往上翻。
  $effect(() => {
    void messages.length;
    const el = listEl;
    if (!el) return;
    requestAnimationFrame(() => {
      el.scrollTop = el.scrollHeight;
    });
  });

  function persistBox() {
    try {
      localStorage.setItem(FLOAT_KEY, JSON.stringify(floatBox));
    } catch {
      /* 忽略 */
    }
  }

  function resetPosition() {
    floatBox = defaultFloatBox(viewport(), BOX_OPTIONS);
    persistBox();
  }

  function onHeadPointerDown(event: PointerEvent) {
    const target = event.target as HTMLElement | null;
    if (target?.closest('button, input, textarea, select, a, summary')) return;
    event.preventDefault();
    dragState = { sx: event.clientX, sy: event.clientY, x: floatBox.x, y: floatBox.y };
  }

  function onHeadDblClick(event: MouseEvent) {
    if ((event.target as HTMLElement | null)?.closest('button')) return;
    resetPosition();
  }

  function onResizePointerDown(event: PointerEvent) {
    event.preventDefault();
    event.stopPropagation();
    resizeState = { sx: event.clientX, sy: event.clientY, w: floatBox.w, h: floatBox.h };
  }

  // window 级监听：面板移出指针下方后仍能继续拖动 / 缩放。
  $effect(() => {
    if (!dragState && !resizeState) return;
    const move = (event: PointerEvent) => {
      const box = untrack(() => floatBox);
      if (dragState) {
        floatBox = clampFloatBox(
          {
            ...box,
            x: dragState.x + event.clientX - dragState.sx,
            y: dragState.y + event.clientY - dragState.sy,
          },
          viewport(),
          BOX_OPTIONS,
        );
      } else if (resizeState) {
        floatBox = clampFloatBox(
          {
            ...box,
            w: resizeState.w + event.clientX - resizeState.sx,
            h: resizeState.h + event.clientY - resizeState.sy,
          },
          viewport(),
          BOX_OPTIONS,
        );
      }
    };
    const up = () => {
      dragState = null;
      resizeState = null;
      persistBox();
    };
    window.addEventListener('pointermove', move);
    window.addEventListener('pointerup', up);
    window.addEventListener('pointercancel', up);
    return () => {
      window.removeEventListener('pointermove', move);
      window.removeEventListener('pointerup', up);
      window.removeEventListener('pointercancel', up);
    };
  });

  $effect(() => {
    const onResize = () => {
      floatBox = clampFloatBox(floatBox, viewport(), BOX_OPTIONS);
      persistBox();
    };
    window.addEventListener('resize', onResize);
    return () => window.removeEventListener('resize', onResize);
  });

  function send() {
    if (!cue || stale || running || busyElsewhere) return;
    if (hasConversation) {
      if (!draft.trim()) return;
      sendArbitrationFollowUp(index);
      return;
    }
    void runArbitration(index, { mode: 'initial' });
  }

  function rejudge() {
    if (!cue || stale || running || busyElsewhere) return;
    rejudgeArbitration(index);
  }

  function undoFrom(position: number) {
    undoArbitrationFrom(index, position);
  }

  function undoLast() {
    undoLastArbitrationFollowUp(index);
  }

  function onInput(event: Event) {
    setArbitrationDraft(index, (event.currentTarget as HTMLTextAreaElement).value);
  }

  function onKeydown(event: KeyboardEvent) {
    if ((event.metaKey || event.ctrlKey) && event.key === 'Enter') {
      event.preventDefault();
      send();
    }
  }

  function reset() {
    resetArbitrationThread(index);
  }

  function tagFor(pos: number): string {
    return `arbdlg:${thread?.key || index}:${pos}`;
  }

  function isPlaying(pos: number): boolean {
    return tts.playing && tts.tag === tagFor(pos);
  }

  function isLoading(pos: number): boolean {
    return tts.loading && tts.tag === tagFor(pos);
  }

  function speak(message: ArbitrationMessage, pos: number) {
    const tag = tagFor(pos);
    if (isPlaying(pos) || isLoading(pos)) {
      stopTts();
      return;
    }
    void speakTextTagged(message.text, tag);
  }

  function adopt(message: ArbitrationMessage) {
    void adoptArbitrationMessage(index, message);
  }

  function sameAsCurrent(message: ArbitrationMessage): boolean {
    return message.text.trim() === textA.trim();
  }

  function close() {
    closeArbitrationDialog();
  }
</script>

<div
  class="arb-dialog"
  class:dragging
  class:resizing
  style={panelStyle}
  role="dialog"
  aria-label="AI 多轮对话"
>
  <header
    class="dlg-head"
    role="group"
    aria-label="浮窗标题栏（可拖动）"
    onpointerdown={onHeadPointerDown}
    ondblclick={onHeadDblClick}
  >
    <span class="dlg-mark"><Icon name="sparkle" size={13} /></span>
    <div class="dlg-title">
      <b>AI 多轮对话</b>
      <span>
        {#if cue}
          第 {index + 1} 句 · {tcShort(cue.start)} · {app.cues.length} 条
        {:else}
          这一句已不存在
        {/if}
      </span>
    </div>
    {#if running}
      <span class="dlg-running" role="status"><span class="spin"></span>判定中</span>
    {/if}
    <button class="dlg-icon" onclick={resetPosition} title="归位（双击标题栏同效）" aria-label="归位">
      <Icon name="target" size={12} />
    </button>
    <button class="dlg-icon" onclick={close} title="关闭浮窗（Esc）" aria-label="关闭">
      <Icon name="close" size={12} />
    </button>
  </header>

  {#if !cue}
    <div class="dlg-empty">
      <p>这一句已经被删除或替换，浮窗会自动关闭。</p>
    </div>
  {:else}
    <div class="dlg-body">
      <details class="ctx">
        <summary>上下文与 A/B 文本</summary>
        <div class="ctx-body">
          <div class="ctx-row">
            <span class="ctx-label">前文</span>
            <span class="ctx-text">
              {#if context.before.length}
                {#each context.before as line, i (i)}<span class="ctx-line">{line}</span>{/each}
              {:else}
                {EMPTY}
              {/if}
            </span>
          </div>
          <div class="ctx-row">
            <span class="ctx-label">A 版</span>
            <span class="ctx-text" class:blank={!textA}>{textA || EMPTY}</span>
          </div>
          <div class="ctx-row">
            <span class="ctx-label">B 版</span>
            <span class="ctx-text" class:blank={!textB}>{textB || EMPTY}</span>
          </div>
          <div class="ctx-row">
            <span class="ctx-label">后文</span>
            <span class="ctx-text">
              {#if context.after.length}
                {#each context.after as line, i (i)}<span class="ctx-line">{line}</span>{/each}
              {:else}
                {EMPTY}
              {/if}
            </span>
          </div>
        </div>
      </details>

      {#if stale}
        <div class="dlg-stale">
          <p>这一句的时间或文本已改动，之前的对话已失效。</p>
          <button class="btn ghost mini" onclick={reset}>重置对话</button>
        </div>
      {/if}

      <div class="thread" bind:this={listEl}>
        {#if !messages.length}
          <p class="thread-empty">
            还没有对话。可以在下方直接输入听音线索（空耳 / 罗马音），或让 AI 结合上下文先推断。
          </p>
        {/if}
        {#each messages as message, pos (pos)}
          {#if message.role === 'user'}
            <div class="msg user">
              <div class="msg-user-head">
                <span class="msg-role">你</span>
                <button
                  class="msg-undo"
                  type="button"
                  onclick={() => undoFrom(pos)}
                  title="撤销这条追问以及它之后的 AI 回复；右侧结果卡会同步回上一层，不重新请求模型"
                >撤销这轮及之后</button>
              </div>
              <p>{message.text}</p>
            </div>
          {:else}
            <article class="msg ai">
              <div class="msg-head">
                <span class="msg-model" title={message.model || modelName}>{message.model || modelName}</span>
                <button
                  class="msg-tts"
                  class:on={isPlaying(pos)}
                  onclick={() => speak(message, pos)}
                  disabled={ttsBlocked}
                  title={isLoading(pos) ? '再点一次取消生成' : '朗读这一轮 AI 回复'}
                >
                  {#if isLoading(pos)}
                    <span class="spin"></span><span>生成中</span>
                  {:else if isPlaying(pos)}
                    <Icon name="stop" size={10} /><span>停止</span>
                  {:else}
                    <Icon name="speaker" size={11} /><span>朗读</span>
                  {/if}
                </button>
                <CopyTextButton
                  text={message.text}
                  compact
                  title="复制这一轮 AI 回复（与当前稿一致时也可复制）"
                />
              </div>
              <p class="msg-text">{message.text}</p>
              {#if message.note}
                <p class="msg-note">理由：{message.note}</p>
              {/if}
              <div class="msg-actions">
                <button
                  class="btn primary mini"
                  onclick={() => adopt(message)}
                  disabled={stale || sameAsCurrent(message)}
                  title={stale
                    ? '这一句已改动，先重置对话再采用'
                    : sameAsCurrent(message)
                      ? '这一轮与当前稿一致'
                      : '写回当前字幕（可 ⌘Z 撤销）'}
                >
                  {stale ? '已失效' : sameAsCurrent(message) ? '当前稿' : '采用这一轮'}
                </button>
              </div>
            </article>
          {/if}
        {/each}
      </div>
    </div>

    <footer class="dlg-foot">
      {#if error}
        <p class="dlg-error">{error}</p>
      {/if}
      <textarea
        rows="3"
        maxlength={MAX_HINT_CHARS}
        value={draft}
        placeholder="补充听音线索（空耳 / 罗马音）或继续追问；⌘↩ 发送"
        oninput={onInput}
        onkeydown={onKeydown}
        disabled={stale}
      ></textarea>
      <div class="dlg-actions">
        <div class="dlg-links">
          <button
            class="link"
            type="button"
            onclick={rejudge}
            disabled={stale || running || busyElsewhere}
            title={hasHistory
              ? '清空这一句的追问历史与 AI 回复，按原始 A/B 与上下文重新判定；输入框里的新线索会作为本次线索'
              : '按原始 A/B 与上下文重新判定；输入框里的新线索会作为本次线索'}
          >{rejudgeLabel}</button>
          {#if canUndoLast}
            <button
              class="link"
              type="button"
              onclick={undoLast}
              title="只截断前端内存里的上一轮追问与回复，不重新请求模型"
            >↩ 撤回上一轮追问</button>
          {/if}
          <button class="link" type="button" onclick={reset} title="清掉这一句的临时对话与结果">
            重置对话
          </button>
        </div>
        <span class="dlg-budget">{draft.length}/{MAX_HINT_CHARS} · 只发送文本</span>
        {#if running}
          <button class="btn ghost" onclick={() => cancelArbitration()}>取消</button>
        {:else}
          <button
            class="btn primary"
            onclick={send}
            disabled={!canSend}
            title={busyElsewhere
              ? 'AI 正在判定另一句，等它完成或取消后再试'
              : hasConversation && !draft.trim()
                ? '先在输入框里写下一条新线索'
                : '只发送文本'}
          >
            {busyElsewhere ? '等待另一句…' : hasConversation ? '发送追问' : '让 AI 判定'}
          </button>
        {/if}
      </div>
    </footer>
  {/if}

  <div class="dlg-resize" onpointerdown={onResizePointerDown} aria-hidden="true"></div>
</div>

<style>
  .arb-dialog {
    position: fixed;
    z-index: 70;
    display: flex;
    flex-direction: column;
    min-width: 380px;
    min-height: 320px;
    border: 1px solid var(--line);
    border-radius: 14px;
    background: var(--raise);
    box-shadow: var(--shadow-pop);
    overflow: hidden;
  }
  .arb-dialog.dragging,
  .arb-dialog.resizing {
    user-select: none;
  }
  .dlg-head {
    flex: 0 0 auto;
    display: flex;
    align-items: center;
    gap: var(--sp-2);
    padding: 9px 8px 9px var(--sp-3);
    border-bottom: 1px solid var(--separator-soft);
    background: var(--paper);
    cursor: grab;
    touch-action: none;
  }
  .arb-dialog.dragging .dlg-head {
    cursor: grabbing;
  }
  .dlg-mark {
    flex: 0 0 24px;
    width: 24px;
    height: 24px;
    display: grid;
    place-items: center;
    border-radius: 7px;
    background: var(--accent-soft);
    color: var(--accent);
  }
  .dlg-title {
    flex: 1 1 auto;
    min-width: 0;
    display: flex;
    flex-direction: column;
    gap: 1px;
  }
  .dlg-title b {
    font-size: 12.5px;
    color: var(--ink);
  }
  .dlg-title span {
    font-size: 10.5px;
    color: var(--text-3);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .dlg-running {
    display: inline-flex;
    align-items: center;
    gap: var(--sp-1);
    font-size: 10.5px;
    color: var(--text-3);
  }
  .dlg-icon {
    appearance: none;
    flex: 0 0 auto;
    width: 24px;
    height: 24px;
    display: grid;
    place-items: center;
    border: 1px solid transparent;
    border-radius: 6px;
    background: transparent;
    color: var(--text-3);
    cursor: pointer;
  }
  .dlg-icon:hover {
    color: var(--ink);
    border-color: var(--line-2);
    background: var(--raise);
  }
  .dlg-body {
    flex: 1 1 auto;
    min-height: 0;
    display: flex;
    flex-direction: column;
    gap: var(--sp-2);
    padding: var(--sp-2) var(--sp-3);
    overflow: hidden;
  }
  .ctx {
    flex: 0 0 auto;
    border: 1px solid var(--line-2);
    border-radius: 7px;
    background: var(--paper);
    padding: 0 var(--sp-2);
  }
  .ctx summary {
    padding: 6px 0;
    font-size: 11px;
    font-weight: 600;
    color: var(--text-3);
    cursor: pointer;
  }
  .ctx-body {
    display: flex;
    flex-direction: column;
    gap: 5px;
    padding: 0 0 var(--sp-2);
  }
  .ctx-row {
    display: flex;
    gap: 7px;
    font-size: 11px;
    line-height: 1.5;
  }
  .ctx-label {
    flex: 0 0 34px;
    color: var(--text-3);
  }
  .ctx-text {
    flex: 1 1 auto;
    color: var(--ink-2);
    word-break: break-word;
    user-select: text;
    -webkit-user-select: text;
    cursor: text;
  }
  .ctx-text.blank {
    color: var(--text-3);
  }
  .ctx-line {
    display: block;
  }
  .ctx-line + .ctx-line {
    margin-top: 2px;
  }
  .dlg-stale {
    flex: 0 0 auto;
    display: flex;
    align-items: center;
    gap: var(--sp-2);
    padding: 7px 9px;
    border: 1px solid color-mix(in srgb, var(--warn) 40%, transparent);
    border-radius: 7px;
    background: color-mix(in srgb, var(--warn) 10%, transparent);
    font-size: 11.5px;
    color: var(--warn);
  }
  .dlg-stale p {
    flex: 1 1 auto;
    margin: 0;
  }
  .thread {
    flex: 1 1 auto;
    min-height: 0;
    overflow: auto;
    display: flex;
    flex-direction: column;
    gap: var(--sp-2);
    padding-right: 2px;
  }
  .thread-empty {
    margin: var(--sp-2) 0;
    color: var(--text-3);
    font-size: 11.5px;
    line-height: 1.6;
  }
  .msg {
    border-radius: 9px;
    padding: 7px 10px;
    font-size: 12px;
    line-height: 1.55;
  }
  .msg.user {
    align-self: flex-end;
    max-width: 86%;
    background: var(--accent-soft);
    color: var(--ink-2);
  }
  .msg.user p {
    margin: 2px 0 0;
    white-space: pre-wrap;
    word-break: break-word;
    user-select: text;
    -webkit-user-select: text;
    cursor: text;
  }
  .msg-user-head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--sp-2);
  }
  .msg-role {
    font-size: 10px;
    font-weight: 600;
    color: var(--accent-hover);
  }
  .msg-undo {
    appearance: none;
    flex: 0 0 auto;
    border: 0;
    background: transparent;
    color: var(--text-3);
    font: inherit;
    font-size: 10px;
    line-height: 1.2;
    padding: 0;
    cursor: pointer;
    white-space: nowrap;
  }
  .msg-undo:hover {
    color: var(--accent-hover);
    text-decoration: underline;
    text-underline-offset: 2px;
  }
  .msg.ai {
    border: 1px solid var(--accent-line);
    background: color-mix(in srgb, var(--accent-soft) 30%, var(--raise));
  }
  .msg-head {
    display: flex;
    align-items: center;
    gap: 6px;
    margin-bottom: 3px;
  }
  .msg-model {
    flex: 1 1 auto;
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    font-size: 10px;
    color: var(--accent-hover);
  }
  .msg-tts {
    appearance: none;
    flex: 0 0 auto;
    display: inline-flex;
    align-items: center;
    gap: 3px;
    height: 21px;
    padding: 0 7px;
    border: 1px solid var(--line-2);
    border-radius: 6px;
    background: transparent;
    color: var(--ink-2);
    font: inherit;
    font-size: 10.5px;
    cursor: pointer;
  }
  .msg-tts:hover:not(:disabled),
  .msg-tts.on {
    color: var(--accent-hover);
    border-color: var(--accent-line);
    background: var(--accent-soft);
  }
  .msg-tts:disabled {
    opacity: 0.55;
    cursor: default;
  }
  .msg-text {
    margin: 0;
    font-family: var(--font-cue);
    font-size: 14px;
    line-height: 1.6;
    color: var(--ink);
    white-space: pre-wrap;
    word-break: break-word;
    user-select: text;
    -webkit-user-select: text;
    cursor: text;
  }
  .msg-note {
    margin: var(--sp-1) 0 0;
    font-size: 10.5px;
    color: var(--text-3);
    user-select: text;
    -webkit-user-select: text;
    cursor: text;
  }
  .msg-actions {
    display: flex;
    gap: var(--sp-1);
    margin-top: 6px;
  }
  .dlg-foot {
    flex: 0 0 auto;
    display: flex;
    flex-direction: column;
    gap: 6px;
    padding: var(--sp-2) var(--sp-3) var(--sp-3);
    border-top: 1px solid var(--separator-soft);
    background: var(--paper);
  }
  .dlg-foot textarea {
    width: 100%;
    min-height: 54px;
    max-height: 140px;
    resize: vertical;
    padding: 6px var(--sp-2);
    border: 1px solid var(--line-2);
    border-radius: 6px;
    background: var(--base);
    color: var(--ink);
    font: inherit;
    font-size: 12px;
    line-height: 1.5;
  }
  .dlg-foot textarea:focus {
    outline: none;
    border-color: var(--accent-line);
    box-shadow: 0 0 0 2px var(--accent-soft);
  }
  .dlg-actions {
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    gap: 6px var(--sp-2);
  }
  .dlg-links {
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    gap: var(--sp-2);
    flex: 1 1 auto;
    min-width: 0;
  }
  .dlg-budget {
    flex: 1 1 auto;
    min-width: 0;
    text-align: right;
    font-size: 10px;
    color: var(--text-3);
  }
  .dlg-error {
    margin: 0;
    font-size: 11.5px;
    color: var(--warn);
  }
  .dlg-empty {
    padding: var(--sp-4);
    color: var(--text-3);
    font-size: 12px;
  }
  .link {
    appearance: none;
    border: 0;
    background: transparent;
    color: var(--accent-hover);
    font: inherit;
    font-size: 11px;
    cursor: pointer;
    padding: 0;
    white-space: nowrap;
  }
  .link:disabled {
    color: var(--text-3);
    cursor: default;
  }
  .dlg-resize {
    position: absolute;
    right: 0;
    bottom: 0;
    width: 16px;
    height: 16px;
    cursor: nwse-resize;
    background: linear-gradient(
      135deg,
      transparent 0 55%,
      var(--line-2) 55% 62%,
      transparent 62% 72%,
      var(--line-2) 72% 79%,
      transparent 79%
    );
  }
  .spin {
    width: 9px;
    height: 9px;
    border-radius: 50%;
    border: 1.5px solid currentColor;
    border-top-color: transparent;
    animation: dlg-spin 650ms linear infinite;
  }
  @keyframes dlg-spin {
    to {
      transform: rotate(360deg);
    }
  }
</style>
