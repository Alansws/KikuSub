<script lang="ts">
  /**
   * 翻译页（原「AI 优化」的翻译半边）。
   *
   * 翻译永远只吃「定稿后的原文一列」，不参与双引擎比较（D-3/D-4）。应用后
   * 写进译文平行轨，核对台可切到双语；原文与时间轴一个字节都不改。
   */
  import Icon from '../components/Icon.svelte';
  import {
    ai,
    applyAiProposal,
    cancelAiPolish,
    copyAiPrompt,
    discardAiProposal,
    importAiProposal,
    loadAiProposal,
    parseAiPastedSrt,
    saveAiProposalAs,
    setAiEdit,
    setAiKind,
    setAiLang,
    setAllAiAccept,
    startAiTranslate,
    toggleAiAccept,
  } from '../lib/aiWorkspace.svelte';
  import {
    loadPrompts,
    prompts,
    promptItemsFor,
    selectPromptTemplate,
    selectedPromptTemplate,
  } from '../lib/promptStore.svelte';
  import { app, focusRange, jumpToCue, setView } from '../lib/store.svelte';
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

  const visibleErrors = $derived(ai.errors.filter((e) => !/还没有提案/.test(e)));
  const changedCount = $derived(rows.filter((r) => r.changed).length);
  const acceptedCount = $derived(rows.filter((r) => r.changed && r.accepted).length);
  const visible = $derived(ai.changedOnly ? rows.filter((r) => r.changed) : rows);
  const hasNotes = $derived(rows.some((r) => r.note.trim().length > 0));
  const translateTemplates = $derived(promptItemsFor('translate'));

  $effect(() => {
    void app.connected;
    void app.media?.id;
    void ai.lang;
    if (ai.kind !== 'translate') setAiKind('translate');
    if (app.connected) {
      void loadAiProposal();
      void loadPrompts();
    }
  });

  function goto(row: { i: number; start: number; end: number }) {
    setView('review');
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
    <span class="title">翻译</span>
    <span class="dim" title="翻译只读取 translate 分类的模板">
      模板：{selectedPromptTemplate('translate')?.name ?? '—'}
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
    {#if translateTemplates.length}
      <select
        class="lang"
        value={prompts.selected}
        onchange={(e) => void selectPromptTemplate(e.currentTarget.value, 'translate')}
        title="翻译提示词模板（在提示词库的「翻译」页签里编辑）"
      >
        {#each translateTemplates as item (item.id)}
          <option value={item.id}>{item.name}</option>
        {/each}
      </select>
    {/if}

    {#if ai.proposal}
      <span class="badge" title={ai.proposal.entry === 'manual'
        ? '从外部模型（网页版 / 聊天窗）复制提示词、再把回复粘回来的结果'
        : ai.proposal.entry === 'skill'
          ? '由随包 Agent 技能写出的提案文件'
          : '在本机「生成建议」里调用模型得到的结果'}>
        {ai.proposal.entry === 'skill' ? '外部 Agent' : ai.proposal.entry === 'manual' ? '外部粘贴' : '本机生成'}
      </span>
      {#if ai.proposal.model && ai.proposal.model !== 'manual-paste'}
        <span class="dim">{ai.proposal.model}</span>
      {/if}
    {/if}

    <div class="spacer"></div>

    <button
      class="btn ghost"
      onclick={copyAiPrompt}
      disabled={!app.cues.length}
      title="用当前 translate 模板生成提示词；可粘到任意网页版模型，再把回复粘回来"
    >
      复制提示词
    </button>
    <button
      class="btn ghost"
      onclick={() => setView('prompts')}
      title="打开提示词库：翻译模板在「翻译」页签"
    >
      提示词库
    </button>
    <button
      class="btn ghost"
      onclick={() => (ai.pasteOpen = !ai.pasteOpen)}
      disabled={!app.cues.length}
      title="粘贴模型返回的 SRT，解析后走同一套双栏对照"
    >
      粘贴结果…
    </button>
    {#if ai.proposal}<div class="tb-div"></div>{/if}
    {#if ai.proposal}
      <button
        class="btn ghost"
        onclick={startAiTranslate}
        disabled={ai.generating || !app.cues.length}
        title="把原文字幕翻译成所选语种（只生成建议）"
      >
        生成建议
      </button>
      <button class="btn ghost" onclick={importAiProposal} title="导入一份外部生成的 proposal.json">
        导入建议…
      </button>
      <div class="tb-div"></div>
      <button class="btn ghost" onclick={() => void loadAiProposal(true)} disabled={ai.loading || ai.generating}>
        重新加载
      </button>
      <button class="btn ghost" onclick={saveAiProposalAs} disabled={ai.saving}>另存</button>
      <button class="btn ghost danger" onclick={discardAiProposal}>丢弃</button>
      <div class="tb-div"></div>
      <button
        class="btn primary"
        onclick={applyAiProposal}
        disabled={ai.applying || acceptedCount === 0}
        title="写进译文轨并把核对台切到双语（不改动原文与时间轴）"
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
        {ai.warnings.slice(0, 3).join('；')}{ai.warnings.length > 3 ? ` …另有 ${ai.warnings.length - 3} 条提示` : ''}
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
        <button class="btn primary" onclick={parseAiPastedSrt} disabled={ai.parsing || !ai.pasteText.trim()}>
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
    <div class="blank"><div class="et">正在读取建议…</div></div>
  {:else if !ai.proposal}
    <div class="blank">
      <span class="blank-icon"><Icon name="doc" size={24} /></span>
      <div class="et">还没有译文建议</div>
      <div class="es">点「生成建议」，或导入外部工具写好的建议；时间码保持不变。</div>
      {#if visibleErrors.length}
        <div class="blank-err"><Icon name="warn" size={11} />{visibleErrors[0]}</div>
      {/if}
      <div class="ea">
        <button class="btn primary" onclick={startAiTranslate} disabled={ai.generating || !app.cues.length}>
          生成建议
        </button>
        <button class="btn ghost" onclick={importAiProposal}>导入建议…</button>
      </div>
    </div>
  {:else if !visible.length}
    <div class="blank">
      <Icon name="check" size={22} />
      <div class="et">这一栏没有内容</div>
      <div class="es">{ai.changedOnly ? '这一栏没有改动；取消「只看改动」可以看全量。' : '当前没有字幕。'}</div>
    </div>
  {:else}
    <div class="cols" class:no-notes={!hasNotes}>
      <span class="c-time">时间码</span>
      <span class="c-side">原文（只读）</span>
      <span class="c-side">AI 译文（双击可改）</span>
      {#if hasNotes}<span class="c-note">理由</span>{/if}
      <span></span>
    </div>
    <div class="list">
      {#each visible as row (row.i)}
        <div class="row" class:no-notes={!hasNotes} class:changed={row.changed} class:off={!row.accepted}>
          <div class="c-time">
            <button class="tc" onclick={() => goto(row)} title="回到核对台定位这一句">{tcShort(row.start)}</button>
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
              {#if ai.edits[row.i] !== undefined}<span class="tag">已手改</span>{/if}
            {/if}
          </div>
          {#if hasNotes}<div class="c-note">{row.note}</div>{/if}
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
    padding: var(--sp-2) 14px;
    border-bottom: 1px solid var(--separator);
  }
  .head {
    flex-wrap: wrap;
  }
  .title {
    font-size: 13px;
    font-weight: 600;
  }
  .bar {
    gap: var(--sp-2);
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
    gap: var(--sp-2);
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
    padding: var(--sp-2) 10px;
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
    gap: var(--sp-2);
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
    padding: 2px var(--sp-1);
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
  .cols.no-notes,
  .row.no-notes {
    grid-template-columns: 92px minmax(0, 1fr) minmax(0, 1fr) 26px;
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
    padding: 1px var(--sp-1);
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
  .blank {
    flex: 1;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 9px;
    padding: var(--sp-10) var(--sp-6);
    text-align: center;
    color: var(--text-2);
  }
  .blank-icon {
    width: 44px;
    height: 44px;
    border-radius: 10px;
    display: grid;
    place-items: center;
    background: var(--accent-soft);
    color: var(--accent);
    margin-bottom: var(--sp-1);
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
  .blank-err {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    font-size: 12px;
    color: var(--warn);
    max-width: 460px;
  }
  .ea {
    display: flex;
    gap: var(--sp-2);
    margin-top: 6px;
  }
</style>
