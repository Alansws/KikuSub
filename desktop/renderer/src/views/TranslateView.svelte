<script lang="ts">
  /**
   * 翻译页（原「AI 优化」的翻译半边）。
   *
   * 翻译永远只吃「定稿后的原文一列」，不参与双引擎比较（D-3/D-4）。应用后
   * 写进译文平行轨，核对台可切到双语；原文与时间轴一个字节都不改。
   */
  import Icon from '../components/Icon.svelte';
  import ClipScopePicker from '../components/ClipScopePicker.svelte';
  import BatchRangeBar from '../components/ai/BatchRangeBar.svelte';
  import { untrack } from 'svelte';
  import {
    ai,
    aiBatchActive,
    aiBatchSpan,
    applyAiProposal,
    cancelAiPolish,
    copyAiPrompt,
    discardAiProposal,
    importAiProposal,
    loadAiProposal,
    parseAiPastedSrt,
    resetAiBatch,
    saveAiProposalAs,
    setAiBatch,
    setAiBatchSize,
    setAiEdit,
    setAiKind,
    setAiLang,
    setAllAiAccept,
    startAiTranslate,
    stepAiBatch,
    syncAiBatchScope,
    toggleAiAccept,
  } from '../lib/aiWorkspace.svelte';
  import {
    loadPrompts,
    prompts,
    promptItemsFor,
    selectPromptTemplate,
    selectedPromptTemplate,
  } from '../lib/promptStore.svelte';
  import { clipSpan, formatRange } from '../lib/clipRange';
  import { app, exporter, focusRange, jumpToCue, setExportClip, setView } from '../lib/store.svelte';
  import { tcShort } from '../lib/time';

  let editing = $state(0);
  let draft = $state('');

  /** 时间轴对齐结果：行号 → 状态（合并覆盖 / 空缺 / 时间戳偏差）。 */
  const alignmentRows = $derived(
    new Map((ai.proposal?.alignment?.rows ?? []).map((row) => [row.i, row])),
  );

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
        align: alignmentRows.get(i) ?? null,
      };
    });
  });

  /** 处理范围 → 全片 1 基区间；批次默认就是整个范围。 */
  const scopeSpan = $derived(clipSpan(app.cues, exporter.clip));
  const scoped = $derived(exporter.clip.end > 0);
  const restricted = $derived(scoped || aiBatchActive());
  const batch = $derived(aiBatchSpan());
  const scopeTitle = $derived(
    scoped ? `${exporter.clip.label ? `${exporter.clip.label} · ` : ''}${formatRange(exporter.clip)}` : '',
  );
  /** 表格 / 复制 / 回填只作用于当前批次（实时索引切片，改文字不会让批次失效）。 */
  const scopedRows = $derived(
    batch.count > 0 ? rows.slice(batch.from - 1, batch.to) : [],
  );
  /** 磁盘上的译文建议可能来自另一个范围：提示一句，避免以为是当前这一段。 */
  const proposalRange = $derived(ai.proposal?.source.range ?? null);
  const rangeMismatch = $derived(
    Boolean(proposalRange) &&
      restricted &&
      (proposalRange!.from !== batch.from || proposalRange!.to !== batch.to),
  );

  const visibleErrors = $derived(ai.errors.filter((e) => !/还没有提案/.test(e)));
  const changedCount = $derived(scopedRows.filter((r) => r.changed).length);
  const acceptedCount = $derived(scopedRows.filter((r) => r.changed && r.accepted).length);
  const visible = $derived(ai.changedOnly ? scopedRows.filter((r) => r.changed) : scopedRows);
  const hasNotes = $derived(scopedRows.some((r) => r.note.trim().length > 0));
  const translateTemplates = $derived(promptItemsFor('translate'));
  const alignment = $derived(ai.proposal?.alignment ?? null);
  const alignmentNote = $derived.by(() => {
    if (!alignment) return '';
    const counts = alignment.counts;
    const parts = [
      counts.merged ? `合并覆盖 ${counts.merged} 个槽位` : '',
      counts.missing ? `空缺 ${counts.missing} 条` : '',
      counts.out_of_range ? `范围外 ${counts.out_of_range} 条` : '',
      counts.drift ? `时间戳偏差 ${counts.drift} 条` : '',
    ].filter(Boolean);
    return parts.join(' · ');
  });

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

  /** 处理范围变化 → 批次回到整段（避免把上一范围的批次带到新范围）。 */
  $effect(() => {
    void exporter.clip.start;
    void exporter.clip.end;
    void exporter.clip.label;
    if (!app.connected) return;
    untrack(() => syncAiBatchScope());
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
    <ClipScopePicker compact label="处理范围" disabled={ai.generating} />
    <BatchRangeBar
      from={batch.from}
      to={batch.to}
      spanFrom={scopeSpan.from}
      spanTo={scopeSpan.to}
      count={batch.count}
      total={app.cues.length}
      size={ai.batchSize}
      manual={aiBatchActive()}
      disabled={ai.generating || ai.applying}
      onApply={setAiBatch}
      onStep={stepAiBatch}
      onSize={setAiBatchSize}
      onReset={resetAiBatch}
    />
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
      {#if aiBatchActive()}
        <span class="scope-chip" title="只写回这一批；范围外与批次外译文原样保留">
          本批 · 第 <b>{batch.from}–{batch.to}</b> 条 · {batch.count} / {app.cues.length} 条
        </span>
        <button class="link" onclick={resetAiBatch}>整段</button>
        <span class="sep"></span>
      {:else if scoped}
        <span class="scope-chip" title="只处理这一段；范围外译文原样保留">
          片段 · {scopeTitle} · <b>{scopeSpan.count}</b> / {app.cues.length} 条
        </span>
        <button class="link" onclick={() => setExportClip({ start: 0, end: 0, label: '' })}>
          全片
        </button>
        <span class="sep"></span>
      {:else}
        <span>共 <b>{app.cues.length}</b> 条</span>
      {/if}
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
  {:else if rangeMismatch && proposalRange}
    <div class="note warn">
      <Icon name="warn" size={11} />
      <span>
        这份译文建议覆盖第 {proposalRange.from}–{proposalRange.to} 条，当前处理批次是第
        {batch.from}–{batch.to} 条：应用会按建议自己的范围写回。
      </span>
    </div>
  {/if}

  {#if alignment && alignmentNote}
    <div class="note warn" class:align-out={alignment.counts.out_of_range > 0}>
      <Icon name="warn" size={11} />
      <span>
        时间轴对齐：{alignmentNote}。合并覆盖的槽位保持空位，不重复写入；时间轴仍用原文。
      </span>
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
        把模型返回的 SRT 粘在下面。<b>序号不参与对齐，时间轴仍用你自己的</b>。
        {#if ai.strictCount}
          条数必须与本批复制出去的一致，否则整批拒绝。
        {:else}
          条数可以不同：带时间轴的译文按时间戳区间交集挂回原句槽位，合并/空缺会高亮。
        {/if}
      </div>
      <textarea
        class="paste-box"
        bind:value={ai.pasteText}
        spellcheck="false"
        placeholder={'1\n00:00:00,500 --> 00:00:01,500\n早上好\n\n2\n…'}
      ></textarea>
      <div class="paste-actions">
        <button class="btn primary" onclick={parseAiPastedSrt} disabled={ai.parsing || !ai.pasteText.trim()}>
          {ai.parsing ? '解析中…' : aiBatchActive() ? '解析并回填本批' : '解析成建议'}
        </button>
        <button class="btn ghost" onclick={() => (ai.pasteOpen = false)}>取消</button>
        <label class="chk" title="开启后回到旧的等条数强校验：条数不符整批拒绝">
          <input type="checkbox" bind:checked={ai.strictCount} />
          严格要求条数一致
        </label>
        <span class="paste-hint">
          {ai.strictCount
            ? '等条数强校验'
            : '默认关闭 · 带时间轴可少条 / 合并'}
        </span>
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
        {@const align = row.align}
        <div
          class="row"
          class:no-notes={!hasNotes}
          class:changed={row.changed}
          class:off={!row.accepted}
          class:align-drift={Boolean(align && (align.drift ?? 0) > 0.5)}
          class:align-merged={align?.state === 'merged'}
          class:align-missing={align?.state === 'missing'}
        >
          <div class="c-time">
            <button class="tc" onclick={() => goto(row)} title="回到核对台定位这一句">{tcShort(row.start)}</button>
            <span class="idx">#{row.i}</span>
            {#if align && (align.state !== 'ok' || (align.drift ?? 0) > 0.5)}
              <span
                class="align-tag"
                class:merged={align.state === 'merged'}
                class:missing={align.state === 'missing'}
                class:drift={(align.drift ?? 0) > 0.5}
                title={align.label}
              >{align.state === 'merged' ? '合并覆盖' : align.state === 'missing' ? '空缺' : '时间轴'}</span>
            {/if}
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
            {:else if row.after}
              <span class="txt">{row.after}</span>
              {#if ai.edits[row.i] !== undefined}<span class="tag">已手改</span>{/if}
            {:else if align}
              <span class="align-empty" title={align.label}>
                {align.state === 'merged' ? '（合并覆盖，槽位置空）' : '（没有匹配到译文）'}
              </span>
            {:else}
              <span class="align-empty">（空位）</span>
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
  .scope-chip {
    color: var(--accent);
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
  /* 时间轴对齐异常：行级底色 + 左侧状态标签，一眼能看出哪几行需要复核 */
  .row.align-drift {
    background: var(--warn-soft);
  }
  .row.align-merged {
    background: var(--accent-soft);
  }
  .row.align-missing {
    background: var(--danger-soft);
  }
  .align-tag {
    margin-top: 2px;
    align-self: flex-start;
    font-size: 10.5px;
    line-height: 15px;
    padding: 0 5px;
    border-radius: 4px;
    background: var(--fill-strong);
    color: var(--text-2);
    white-space: nowrap;
  }
  .align-tag.merged {
    background: var(--accent);
    color: var(--on-accent);
  }
  .align-tag.missing {
    background: var(--danger);
    color: var(--on-accent, #fff);
  }
  .align-tag.drift {
    background: var(--warn);
    color: var(--on-accent, #fff);
  }
  .align-empty {
    color: var(--text-3);
    font-style: italic;
  }
  .note.align-out {
    border-left: 3px solid var(--danger);
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
