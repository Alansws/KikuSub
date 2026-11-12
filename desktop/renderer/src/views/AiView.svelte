<script lang="ts">
  /**
   * AI 优化台（M1）。
   *
   * 只做「读取提案 → 双栏对照 → 逐条采纳 → 应用」这一条链路，**不调用任何模型**。
   * 提案可以由软件内生成（M2），也可以由外部 agent 写好再导入（M4）——两者在这里
   * 长得完全一样，因为界面只认 `proposal.json` 这个契约。
   *
   * 左栏是核对台当前的原文，**只读**；右栏是 AI 建议，双击可改。
   * 时间码只用来跳回核对台定位，永远不会被写回字幕（开发文档 D-1）。
   */
  import Icon from '../components/Icon.svelte';
  import {
    ai,
    app,
    applyAiProposal,
    cancelAiPolish,
    copyAiPrompt,
    discardAiProposal,
    focusRange,
    importAiProposal,
    jumpToCue,
    loadAiProposal,
    loadPrompts,
    parseAiPastedSrt,
    prompts,
    selectedPromptTemplate,
    startAiPolish,
    startAiTranslate,
    saveAiProposalAs,
    setAiEdit,
    setAiKind,
    setAiLang,
    setAllAiAccept,
    setView,
    toggleAiAccept,
  } from '../lib/store.svelte';
  import { tcShort } from '../lib/time';

  let editing = $state(0);
  let draft = $state('');

  const rows = $derived.by(() => {
    const map = new Map((ai.proposal?.items ?? []).map((it) => [it.i, it]));
    return app.cues.map((cue, idx) => {
      const i = idx + 1;
      const item = map.get(i);
      const after = ai.edits[i] !== undefined ? ai.edits[i] : (item?.after ?? cue.text);
      return {
        i,
        start: cue.start,
        end: cue.end,
        before: cue.text,
        after,
        note: item?.note ?? '',
        changed: after !== cue.text,
        accepted: ai.accept[i] !== false,
      };
    });
  });

  /**
   * “还没有提案文件”只是首次打开的正常状态，不能当成错误丢给用户；
   * 真正的加载/生成失败才显示。
   */
  const visibleErrors = $derived(
    ai.errors.filter((e) => !/还没有提案/.test(e)),
  );

  const changedCount = $derived(rows.filter((r) => r.changed).length);
  const acceptedCount = $derived(rows.filter((r) => r.changed && r.accepted).length);
  const visible = $derived(ai.changedOnly ? rows.filter((r) => r.changed) : rows);

  $effect(() => {
    // 依赖显式列出：连接状态 / 当前媒体 / 类型 / 语种，换任意一个都重新拉一次
    void app.connected;
    void app.media?.id;
    void ai.kind;
    void ai.lang;
    if (app.connected) {
      void loadAiProposal();
      void loadPrompts();
    }
  });

  function goto(row: { i: number; start: number; end: number }) {
    setView('review');
    // 先把选中行落下去，右侧检查器才会跟着切到这一条；再聚焦波形。
    jumpToCue(row.i - 1, { seek: false });
    focusRange(row.start, row.end);
  }

  function startEdit(i: number, text: string) {
    editing = i;
    draft = text;
  }

  function commitEdit(i: number) {
    if (editing !== i) return;
    setAiEdit(i, draft);
    editing = 0;
  }

  function cancelEdit() {
    editing = 0;
  }

  function onEditKey(e: KeyboardEvent, i: number) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      commitEdit(i);
    } else if (e.key === 'Escape') {
      e.preventDefault();
      cancelEdit();
    }
  }

  function focusOnMount(node: HTMLTextAreaElement) {
    node.focus();
    node.select();
  }

</script>

<div class="ai">
  <div class="head">
    <div class="segs" role="tablist" aria-label="建议类型">
      <button
        role="tab"
        aria-selected={ai.kind === 'polish'}
        class="seg"
        class:on={ai.kind === 'polish'}
        title="润色：按全片语境修正识别错误"
        onclick={() => setAiKind('polish')}>润色</button
      >
      <button
        role="tab"
        aria-selected={ai.kind === 'translate'}
        class="seg"
        class:on={ai.kind === 'translate'}
        title="翻译：生成与原文逐条对齐的译文平行轨"
        onclick={() => setAiKind('translate')}>翻译</button
      >
    </div>

    {#if ai.kind === 'translate'}
      <span class="dim" title="当前使用的提示词模板；可在「提示词库」里切换或编辑">
        模板：{prompts.items.find((p) => p.id === prompts.selected)?.name ?? '—'}
      </span>
      <select
        class="lang"
        value={ai.lang}
        onchange={(e) => setAiLang(e.currentTarget.value)}
        title="目标语种"
      >
        <option value="zh-Hans">简体中文</option>
        <option value="zh-Hant">繁體中文</option>
        <option value="en">English</option>
      </select>
    {/if}

    {#if ai.proposal}
      <span class="badge">
        {ai.proposal.entry === 'skill'
          ? '外部 agent'
          : ai.proposal.entry === 'manual'
            ? '手动粘贴'
            : '本机生成'}
      </span>
      {#if ai.proposal.model}<span class="dim">{ai.proposal.model}</span>{/if}
    {/if}

    <div class="spacer"></div>

    <button
      class="btn ghost"
      onclick={copyAiPrompt}
      disabled={!app.cues.length}
      title={ai.kind === 'translate'
        ? `使用「${selectedPromptTemplate()?.name ?? '当前模板'}」生成提示词；可粘到任意网页版模型，再把回复粘回来`
        : '复制润色提示词；可粘到任意网页版模型，再把修正后的 SRT 粘回来'}
    >
      复制提示词
    </button>
    {#if ai.kind === 'translate'}
      <button
        class="btn ghost"
        onclick={() => setView('prompts')}
        title="打开提示词库：选中、编辑并保存翻译提示词模板"
      >
        提示词库
      </button>
    {/if}
    <button
      class="btn ghost"
      onclick={() => (ai.pasteOpen = !ai.pasteOpen)}
      disabled={!app.cues.length}
      title="粘贴模型返回的 SRT，解析后照样走双栏对照"
    >
      粘贴结果…
    </button>
    {#if ai.proposal}<div class="tb-div"></div>{/if}

    {#if ai.proposal}
      <button
        class="btn ghost"
        onclick={() => (ai.kind === 'translate' ? startAiTranslate() : startAiPolish())}
        disabled={ai.generating || !app.cues.length}
        title={ai.kind === 'translate' ? '把原文字幕翻译成所选语种（只生成建议）' : '用设置里的模型生成一份修改建议（不修改字幕）'}
      >
        生成建议
      </button>
      <button class="btn ghost" onclick={importAiProposal} title="导入一份外部生成的 proposal.json">
        导入建议…
      </button>
      <div class="tb-div"></div>
      <button
        class="btn ghost"
        onclick={() => void loadAiProposal(true)}
        disabled={ai.loading || ai.generating}
      >
        重新加载
      </button>
      <button class="btn ghost" onclick={saveAiProposalAs} disabled={ai.saving}>另存</button>
      <button class="btn ghost danger" onclick={discardAiProposal}>丢弃</button>
      <div class="tb-div"></div>
      <button
        class="btn primary"
        onclick={applyAiProposal}
        disabled={ai.applying || acceptedCount === 0}
        title={ai.kind === 'translate'
          ? '写进译文轨并把核对台切到双语（不改动原文与时间轴）'
          : '写回核对台，⌘Z 可整批撤回'}
      >
        {ai.applying ? '应用中…' : '应用'}
      </button>
    {/if}
  </div>

  {#if ai.proposal}
  <div class="bar">
    <span>共 <b>{app.cues.length}</b> 条</span>
    <span class="sep"></span>
    <span>AI 改动 <b class="warn">{changedCount}</b> 处</span>
    <span class="sep"></span>
    <span>已采纳 <b>{acceptedCount}</b></span>
    <div class="spacer"></div>
    <label class="chk">
      <input type="checkbox" bind:checked={ai.changedOnly} />
      只看改动
    </label>
    <button class="link" onclick={() => setAllAiAccept(true)} disabled={!ai.proposal}>全选</button>
    <button class="link" onclick={() => setAllAiAccept(false)} disabled={!ai.proposal}>全不选</button>
  </div>
  {/if}

  {#if ai.proposal && visibleErrors.length}
    <div class="note err">
      <Icon name="warn" size={11} />
      <span>{visibleErrors[0]}</span>
    </div>
  {:else if ai.proposal && !ai.digestMatch}
    <div class="note err">
      <Icon name="warn" size={11} />
      <span>源文本已变化：这份建议是针对另一版字幕生成的，应用会被拒绝。</span>
    </div>
  {/if}

  {#if ai.warnings.length}
    <div class="note warn">
      <Icon name="warn" size={11} />
      <span>
        {ai.warnings.slice(0, 3).join('；')}{ai.warnings.length > 3
          ? ` …另有 ${ai.warnings.length - 3} 条提示`
          : ''}
      </span>
    </div>
  {/if}

  {#if ai.pasteOpen}
    <div class="paste">
      <div class="paste-head">
        把模型返回的 SRT 整段粘在下面。<b>序号和时间戳会被忽略</b>，只按顺序取文本，时间轴仍用你自己的。
      </div>
      <textarea
        class="paste-box"
        bind:value={ai.pasteText}
        spellcheck="false"
        placeholder={'1\n00:00:00,500 --> 00:00:01,500\n早上好\n\n2\n…'}
      ></textarea>
      <div class="paste-actions">
        <button
          class="btn primary"
          onclick={parseAiPastedSrt}
          disabled={ai.parsing || !ai.pasteText.trim()}
        >
          {ai.parsing ? '解析中…' : '解析成建议'}
        </button>
        <button class="btn ghost" onclick={() => (ai.pasteOpen = false)}>取消</button>
        <span class="paste-hint">条数必须与当前字幕一致，否则整批拒绝</span>
      </div>
    </div>
  {/if}

  {#if ai.generating}
    <div class="note busy">
      <Icon name="wave" size={11} />
      <span>正在生成建议：{ai.stage || '准备中'}</span>
      <b class="pct">{ai.progress}%</b>
      <button class="link" onclick={cancelAiPolish}>取消</button>
    </div>
  {/if}

  {#if ai.loading}
    <div class="empty"><div class="et">正在读取建议…</div></div>
  {:else if !ai.proposal}
    <div class="empty">
      <span class="empty-icon"><Icon name="doc" size={24} /></span>
      <div class="et">{ai.kind === 'translate' ? '还没有译文建议' : '还没有可对照的修改建议'}</div>
      <div class="es">
        点「生成建议」，或导入外部工具写好的建议；时间码保持不变。
      </div>
      {#if visibleErrors.length}
        <div class="empty-err"><Icon name="warn" size={11} />{visibleErrors[0]}</div>
      {/if}
      <div class="ea">
        <button
          class="btn primary"
          onclick={() => (ai.kind === 'translate' ? startAiTranslate() : startAiPolish())}
          disabled={ai.generating || !app.cues.length}
        >
          生成建议
        </button>
        <button class="btn ghost" onclick={importAiProposal}>导入建议…</button>
      </div>
    </div>
  {:else if !visible.length}
    <div class="empty">
      <Icon name="check" size={22} />
      <div class="et">这一栏没有内容</div>
      <div class="es">
        {ai.changedOnly ? '这一栏没有改动；取消「只看改动」可以看全量。' : '当前没有字幕。'}
      </div>
    </div>
  {:else}
    <div class="cols">
      <span class="c-time">时间码</span>
      <span class="c-side">原文（只读）</span>
      <span class="c-side">{ai.kind === 'translate' ? 'AI 译文（双击可改）' : 'AI 建议（双击可改）'}</span>
      <span class="c-note">理由</span>
      <span></span>
    </div>

    <div class="list">
      {#each visible as row (row.i)}
        <div class="row" class:changed={row.changed} class:off={!row.accepted}>
          <div class="c-time">
            <button class="tc" onclick={() => goto(row)} title="回到核对台定位这一句">
              {tcShort(row.start)}
            </button>
            <span class="idx">#{row.i}</span>
          </div>

          <div class="c-side left">{row.before}</div>

          <div class="c-side right" ondblclick={() => startEdit(row.i, row.after)}>
            {#if editing === row.i}
              <textarea
                use:focusOnMount
                bind:value={draft}
                onkeydown={(e) => onEditKey(e, row.i)}
                onblur={() => commitEdit(row.i)}
                spellcheck="false"
              ></textarea>
            {:else}
              <span class="txt">{row.after}</span>
              {#if ai.edits[row.i] !== undefined}
                <span class="tag">已手改</span>
              {/if}
            {/if}
          </div>

          <div class="c-note">{row.note}</div>

          <button
            class="pin"
            class:on={row.accepted}
            onclick={() => toggleAiAccept(row.i)}
            title={row.accepted ? '采纳这一条（点击排除）' : '已排除（点击采纳）'}
          >
            <Icon name="check" size={11} />
          </button>
        </div>
      {/each}
    </div>
  {/if}
</div>

<style>
  .ai {
    flex: 1;
    min-height: 0;
    display: flex;
    flex-direction: column;
    background: var(--paper);
  }

  .head,
  .bar {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 8px 14px;
    border-bottom: 1px solid var(--separator);
  }

  .head {
    flex-wrap: wrap;
  }

  .bar {
    gap: 8px;
    font-size: 12px;
    color: var(--text-2);
    background: var(--bg-inspector);
  }

  .bar b {
    color: var(--text);
    font-variant-numeric: tabular-nums;
  }

  .bar b.warn {
    color: var(--warn);
  }

  .sep {
    width: 1px;
    height: 11px;
    background: var(--separator);
  }

  .spacer {
    flex: 1;
  }

  .tb-div {
    width: 1px;
    height: 16px;
    background: var(--separator);
    flex: 0 0 1px;
  }

  .segs {
    display: inline-flex;
    padding: 2px;
    border-radius: 8px;
    background: var(--fill);
  }

  .seg {
    border: 0;
    background: transparent;
    color: var(--text-2);
    font: inherit;
    font-size: 12px;
    padding: 4px 12px;
    border-radius: 4px;
    cursor: pointer;
  }

  .seg.on {
    background: var(--bg-content);
    color: var(--text);
    box-shadow: 0 1px 2px rgba(0, 0, 0, 0.12);
  }

  .lang {
    font: inherit;
    font-size: 12px;
    padding: 3px 6px;
    border-radius: 4px;
    border: 1px solid var(--separator);
    background: var(--bg-content);
    color: var(--text);
  }

  .badge {
    font-size: 12px;
    padding: 2px 7px;
    border-radius: 999px;
    background: var(--accent-soft);
    color: var(--accent);
  }

  .dim {
    font-size: 12px;
    color: var(--text-3);
    font-family: var(--mono, ui-monospace, SFMono-Regular, Menlo, monospace);
  }

  .note {
    display: flex;
    align-items: flex-start;
    gap: 6px;
    padding: 6px 14px;
    font-size: 12px;
    line-height: 1.5;
    border-bottom: 1px solid var(--separator-soft);
  }

  .note.err {
    background: var(--danger-soft);
    color: var(--danger);
  }

  .note.warn {
    background: var(--warn-soft);
    color: var(--warn);
  }

  .paste {
    display: flex;
    flex-direction: column;
    gap: 8px;
    padding: 10px 14px;
    border-bottom: 1px solid var(--separator);
    background: var(--bg-inspector);
  }

  .paste-head {
    font-size: 12px;
    color: var(--text-2);
    line-height: 1.6;
  }

  .paste-box {
    width: 100%;
    min-height: 130px;
    max-height: 40vh;
    resize: vertical;
    font-family: var(--mono, ui-monospace, SFMono-Regular, Menlo, monospace);
    font-size: 12px;
    line-height: 1.5;
    padding: 8px 10px;
    border-radius: 8px;
    border: 1px solid var(--separator);
    background: var(--bg-content);
    color: var(--text);
    outline: none;
  }

  .paste-box:focus {
    border-color: var(--accent);
    box-shadow: 0 0 0 3px var(--accent-soft);
  }

  .paste-actions {
    display: flex;
    align-items: center;
    gap: 8px;
  }

  .paste-hint {
    margin-left: auto;
    font-size: 12px;
    color: var(--text-3);
  }

  .note.busy {
    background: var(--accent-soft);
    color: var(--text);
  }

  .note.busy .pct {
    margin-left: auto;
    font-variant-numeric: tabular-nums;
  }

  .chk {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    cursor: pointer;
    user-select: none;
  }

  .link {
    border: 0;
    background: transparent;
    color: var(--accent);
    font: inherit;
    font-size: 12px;
    cursor: pointer;
    padding: 2px 4px;
  }

  .link:disabled {
    color: var(--text-3);
    cursor: default;
  }

  .cols,
  .row {
    display: grid;
    grid-template-columns: 92px minmax(0, 1fr) minmax(0, 1fr) 78px 26px;
    gap: 10px;
    align-items: start;
    padding: 6px 14px;
  }

  .cols {
    position: sticky;
    top: 0;
    z-index: 1;
    font-size: 12px;
    color: var(--text-3);
    background: var(--bg-content);
    border-bottom: 1px solid var(--separator);
    padding-top: 5px;
    padding-bottom: 5px;
  }

  .list {
    flex: 1;
    min-height: 0;
    overflow: auto;
  }

  .row {
    border-bottom: 1px solid var(--separator-soft);
    font-size: 12.5px;
    line-height: 1.55;
    content-visibility: auto;
    contain-intrinsic-size: auto 42px;
  }

  .row:hover {
    background: var(--row-hover);
  }

  .row.off {
    opacity: 0.42;
  }

  .c-time {
    display: flex;
    flex-direction: column;
    gap: 1px;
  }

  .tc {
    border: 0;
    background: transparent;
    padding: 0;
    color: var(--accent);
    font-family: var(--mono, ui-monospace, SFMono-Regular, Menlo, monospace);
    font-size: 12px;
    font-variant-numeric: tabular-nums;
    cursor: pointer;
    text-align: left;
  }

  .idx {
    font-size: 12px;
    color: var(--text-3);
    font-variant-numeric: tabular-nums;
  }

  .c-side,
  .c-note {
    white-space: pre-wrap;
    word-break: break-word;
    min-width: 0;
  }

  .left {
    color: var(--text-2);
  }

  .right {
    border-radius: 4px;
    padding: 1px 4px;
    margin: -1px -4px;
    cursor: text;
    min-height: 18px;
  }

  .row.changed .right {
    background: var(--accent-soft);
  }

  .row.changed .left {
    color: var(--text);
  }

  .right textarea {
    width: 100%;
    min-height: 46px;
    resize: vertical;
    font: inherit;
    line-height: inherit;
    padding: 3px 5px;
    border-radius: 4px;
    border: 1px solid var(--accent);
    background: var(--bg-content);
    color: var(--text);
    outline: none;
  }

  .tag {
    margin-left: 6px;
    font-size: 12px;
    padding: 1px 5px;
    border-radius: 4px;
    background: var(--fill-strong);
    color: var(--text-2);
    white-space: nowrap;
  }

  .c-note {
    font-size: 12px;
    color: var(--text-3);
  }

  .pin {
    width: 22px;
    height: 22px;
    border-radius: 4px;
    border: 1px solid var(--separator);
    background: transparent;
    color: var(--text-3);
    display: grid;
    place-items: center;
    cursor: pointer;
  }

  .pin.on {
    border-color: transparent;
    background: var(--accent);
    color: var(--on-accent);
  }

  .empty {
    flex: 1;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 9px;
    padding: 40px 24px;
    text-align: center;
    color: var(--text-2);
  }

  .empty-icon {
    width: 44px;
    height: 44px;
    border-radius: 10px;
    display: grid;
    place-items: center;
    background: var(--accent-soft);
    color: var(--accent);
    margin-bottom: 4px;
  }

  .et {
    font-size: 15px;
    font-weight: 600;
    color: var(--text);
  }

  .es {
    font-size: 13px;
    line-height: 1.7;
    max-width: 440px;
  }

  .empty-err {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    font-size: 12px;
    color: var(--warn);
    max-width: 460px;
  }

  .es code {
    font-size: 12px;
    padding: 1px 4px;
    border-radius: 4px;
    background: var(--fill);
  }

  .ea {
    display: flex;
    gap: 8px;
    margin-top: 6px;
  }
</style>
