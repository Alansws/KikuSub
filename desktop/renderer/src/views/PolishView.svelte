<script lang="ts">
  /**
   * 润色页（原「AI 优化」的润色半边）。
   *
   * 有第二版 B 时可选「单源 / 双源」。双源时展示三栏：
   *   A（只读原文） | B（只读参考，可折叠） | AI 终稿（可双击编辑，与 A 逐字 diff）
   *
   * 时间轴铁律（D-1）：第 3 栏与第 1 栏严格 1:1，所有采用粒度（逐条 / 全部差异 /
   * 整列）都走 `apply_polish()`，一次 ⌘Z 全退。
   */
  import Icon from '../components/Icon.svelte';
  import type { StructureOpView } from '../lib/api';
  import {
    ai,
    applyAiAcceptedDiffs,
    applyAiAllDiffs,
    applyAiWholeColumn,
    cancelAiPolish,
    copyAiPrompt,
    currentPolishTemplateName,
    discardAiProposal,
    importAiProposal,
    loadAiProposal,
    parseAiPastedSrt,
    planAiSegments,
    saveAiProposalAs,
    segmentKey,
    setAiEdit,
    setAiKind,
    setAiMode,
    setAllAiAccept,
    startAiPolish,
    toggleAiAccept,
  } from '../lib/aiWorkspace.svelte';
  import {
    applyStructureOps,
    closeStructurePanel,
    copyStructurePrompt,
    discardStructure,
    loadStructure,
    openStructurePanel,
    parseStructurePaste,
    selectedStructureCount,
    setAllStructureOps,
    structure,
    toggleStructureOp,
  } from '../lib/structure.svelte';
  import { altEngineLabel, dual, loadAltDiff, refreshAltReview } from '../lib/dualReview.svelte';
  import { loadPrompts, promptItemsFor, prompts, selectPromptTemplate } from '../lib/promptStore.svelte';
  import { app, focusRange, jumpToCue, loadTranslations, setView } from '../lib/store.svelte';
  import { tcShort } from '../lib/time';

  let editing = $state(0);
  let draft = $state('');
  let bCollapsed = $state(false);

  const polishTemplates = $derived(promptItemsFor(ai.mode === 'dual' ? 'polish_dual' : 'polish_single'));
  const activeTemplateId = $derived(
    ai.mode === 'dual' ? prompts.selectedPolishDual : prompts.selectedPolishSingle,
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
      };
    });
  });

  /** A 的每一条对应哪段 B（按时间重叠，双源页只读参考用）。 */
  const bTexts = $derived.by(() => {
    const out = new Map<number, string>();
    if (!dual.exists) return out;
    const b = dual.cues;
    let j = 0;
    for (let i = 0; i < app.cues.length; i += 1) {
      const cue = app.cues[i];
      // 只取真正与这条 A 时间重叠的 B：放宽到相邻句会让参考栏混进上一句/下一句。
      while (j < b.length && b[j].end <= cue.start) j += 1;
      let k = j;
      const texts: string[] = [];
      while (k < b.length && b[k].start < cue.end) {
        texts.push(b[k].text);
        k += 1;
      }
      out.set(i + 1, texts.join(''));
    }
    return out;
  });

  const visibleErrors = $derived(ai.errors.filter((e) => !/还没有提案/.test(e)));
  const changedCount = $derived(rows.filter((r) => r.changed).length);
  const acceptedCount = $derived(rows.filter((r) => r.changed && r.accepted).length);
  const visible = $derived(ai.changedOnly ? rows.filter((r) => r.changed) : rows);
  /** 外部粘贴的 SRT 没有逐条理由：此时整列「理由」不出现，避免满屏「手动粘贴」。 */
  const hasNotes = $derived(rows.some((r) => r.note.trim().length > 0));
  const filledCount = $derived(ai.segments.filter((seg) => ai.filled[segmentKey(seg)]).length);

  /** 结构建议按操作类型分组；空组不显示。 */
  const structureGroups = $derived.by(() => {
    const defs = [
      { key: 'merge', label: '合并连续句', ops: [] as StructureOpView[] },
      { key: 'retime', label: '改时间', ops: [] as StructureOpView[] },
      { key: 'replace_text', label: '改文字', ops: [] as StructureOpView[] },
      { key: 'insert', label: '新增', ops: [] as StructureOpView[] },
      { key: 'delete', label: '删除', ops: [] as StructureOpView[] },
    ];
    const map = new Map(defs.map((item) => [item.key, item]));
    for (const op of structure.ops) map.get(op.op)?.ops.push(op);
    return defs.filter((item) => item.ops.length > 0);
  });

  $effect(() => {
    void app.connected;
    void app.media?.id;
    void ai.lang;
    if (ai.kind !== 'polish') setAiKind('polish');
    if (app.connected) {
      void loadAiProposal();
      void loadPrompts();
      void refreshAltReview();
    }
  });

  $effect(() => {
    // 第二版/条数变化后重新切段；长片分段不会因为回填而失效。
    void dual.exists;
    void dual.count;
    void app.cuesRevision;
    void ai.mode;
    if (app.connected && ai.kind === 'polish') {
      if (ai.mode === 'dual' && !dual.exists && dual.mediaId === (app.media?.id ?? '')) {
        setAiMode('single');
        return;
      }
      planAiSegments();
    }
  });

  $effect(() => {
    // 结构建议按「媒体 + 字幕版本」恢复；切页回来不会丢，字幕改过后会自动失效。
    void app.connected;
    void app.media?.id;
    void app.cuesRevision;
    if (app.connected) void loadStructure();
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

  function onEditKey(e: KeyboardEvent, i: number) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      commitEdit(i);
    } else if (e.key === 'Escape') {
      e.preventDefault();
      editing = 0;
    }
  }

  function focusOnMount(node: HTMLTextAreaElement) {
    node.focus();
    node.select();
  }

  function plan() {
    setAiMode('single');
  }

  function planDual() {
    if (!dual.exists) return;
    setAiMode('dual');
    void loadAltDiff();
  }

  function timeRange(start: number, end: number): string {
    return `${tcShort(start)}–${tcShort(end)}`;
  }

  function opLabel(op: string): string {
    return ({ merge: '合并', retime: '改时间', replace_text: '改文字', insert: '新增', delete: '删除' } as Record<string, string>)[op] ?? op;
  }

  function opTime(op: StructureOpView): string {
    const fmt = (value: number | null) => (value === null ? '—' : tcShort(value));
    if (op.op === 'insert') return `${fmt(op.new_start)}–${fmt(op.new_end)}`;
    if (op.op === 'retime') return `${fmt(op.old_start)} → ${fmt(op.new_start)}`;
    if (op.op === 'merge') return `${fmt(op.old_start)}–${fmt(op.old_end)}`;
    return fmt(op.old_start);
  }

  function openStruct() {
    if (structure.open) {
      closeStructurePanel();
      return;
    }
    ai.pasteOpen = false;
    openStructurePanel();
  }

  async function onApplyStructure() {
    const applied = await applyStructureOps();
    if (applied) {
      // 结构改了原文/时间轴：润色建议与译文轨的准确性都要重新拉一次。
      void loadAiProposal(true);
      void loadTranslations();
      void refreshAltReview();
    }
  }
</script>

<div class="ai">
  <div class="head">
    <span class="title">润色</span>
    <div class="segs" role="tablist" aria-label="润色模式">
      <button
        role="tab"
        aria-selected={ai.mode === 'single'}
        class="seg"
        class:on={ai.mode === 'single'}
        onclick={plan}
        title="只吃核对台当前版本"
      >单源</button>
      <button
        role="tab"
        aria-selected={ai.mode === 'dual'}
        class="seg"
        class:on={ai.mode === 'dual'}
        onclick={planDual}
        disabled={!dual.exists}
        title={dual.exists ? '同时参考第二引擎稿（严格以 A 为骨架）' : '还没有第二版字幕'}
      >双源</button>
    </div>

    <span class="dim" title="当前模式绑定的提示词模板；可在「提示词库」对应页签里编辑">
      模板：{currentPolishTemplateName()}
    </span>
    {#if polishTemplates.length}
      <select
        class="lang"
        value={activeTemplateId}
        onchange={(e) =>
          void selectPromptTemplate(
            e.currentTarget.value,
            ai.mode === 'dual' ? 'polish_dual' : 'polish_single',
          )}
        title="润色提示词模板"
      >
        {#each polishTemplates as item (item.id)}
          <option value={item.id}>{item.name}</option>
        {/each}
      </select>
    {/if}
    {#if ai.mode === 'dual' && dual.exists}
      <span class="badge">B：{altEngineLabel()} · {dual.count} 条</span>
      {#if dual.count !== app.cues.length}
        <span
          class="ref-note"
          title="两个引擎的断句本来就可能不同；B 只作参考，AI 终稿仍严格按 A 的序号与时间轴输出"
        >
          B 参考稿，行数不同；AI 仍按 A 输出
        </span>
      {/if}
      <button class="link" onclick={() => setView('dual')} title="打开双引擎复核页">对照</button>
    {/if}

    {#if ai.proposal}
      <span class="badge" title={ai.proposal.entry === 'manual'
        ? '从外部模型（网页版 / 聊天窗）复制提示词、再把回复粘回来的结果'
        : ai.proposal.entry === 'skill'
          ? '由随包 Agent 技能写出的提案文件'
          : '在本机「生成建议」里调用模型得到的结果'}>
        {ai.proposal.entry === 'skill' ? '外部 Agent' : ai.proposal.entry === 'manual' ? '外部粘贴' : '本机生成'}
      </span>
      {#if ai.proposal.source.digest_b}<span class="badge quiet">双源</span>{/if}
      {#if ai.proposal.model && ai.proposal.model !== 'manual-paste'}
        <span class="dim">{ai.proposal.model}</span>
      {/if}
    {/if}

    <div class="spacer"></div>

    <button
      class="btn ghost"
      onclick={() => {
        structure.open = false;
        void copyAiPrompt();
      }}
      disabled={!app.cues.length}
      title={ai.longMode ? '复制当前分段的提示词' : '复制提示词；可粘到任意网页版模型，再把回复粘回来'}
    >
      {ai.longMode ? '复制本段提示词' : '复制提示词'}
    </button>
    <button class="btn ghost" onclick={() => setView('prompts')} title="打开提示词库">提示词库</button>
    <button
      class="btn ghost"
      onclick={() => {
        structure.open = false;
        ai.pasteOpen = !ai.pasteOpen;
      }}
      disabled={!app.cues.length}
      title={ai.longMode ? '粘贴当前分段的模型回复' : '粘贴模型返回的 SRT，解析后走同一套三栏对照'}
    >
      {ai.longMode ? '粘贴本段结果…' : '粘贴结果…'}
    </button>
    <button
      class="btn ghost"
      onclick={openStruct}
      disabled={!app.cues.length}
      title="给外部模型的「结构检查提示词」会要求只返回 ops JSON；解析后先预览再原子应用"
    >
      结构建议…
      {#if structure.ops.length}<span class="count">{structure.ops.length}</span>{/if}
    </button>
    {#if ai.proposal && !structure.open}<div class="tb-div"></div>{/if}
    {#if ai.proposal && !structure.open}
      <button class="btn ghost" onclick={startAiPolish} disabled={ai.generating || !app.cues.length} title="生成一份润色建议（不修改字幕）">
        生成建议
      </button>
      <button class="btn ghost" onclick={importAiProposal}>导入建议…</button>
      <div class="tb-div"></div>
      <button class="btn ghost" onclick={() => void loadAiProposal(true)} disabled={ai.loading || ai.generating}>重新加载</button>
      <button class="btn ghost" onclick={saveAiProposalAs} disabled={ai.saving}>另存</button>
      <button class="btn ghost danger" onclick={discardAiProposal}>丢弃</button>
      <div class="tb-div"></div>
      <button class="btn ghost" onclick={applyAiAllDiffs} disabled={ai.applying} title="把所有与 A 不同的条目一次写回">
        全部差异
      </button>
      <button class="btn ghost" onclick={applyAiWholeColumn} disabled={ai.applying} title="第 3 栏全量写回核对台">
        整列应用
      </button>
      <button
        class="btn primary"
        onclick={applyAiAcceptedDiffs}
        disabled={ai.applying || acceptedCount === 0}
        title="只应用「已采纳且确有差异」的条目；⌘Z 一次全退"
      >
        {ai.applying ? '应用中…' : '应用采纳'}
      </button>
    {/if}
  </div>

  {#if structure.open}
    <div class="struct">
      <div class="struct-head">
        <span class="struct-title">结构建议</span>
        <span class="dim">只改断句 / 时间轴 / 文字，不走润色提案</span>
        <div class="spacer"></div>
        <button class="link" onclick={() => void copyStructurePrompt()} disabled={structure.promptLoading}>
          {structure.promptLoading ? '复制中…' : '复制结构检查提示词'}
        </button>
        {#if structure.ops.length}
          <button class="link danger" onclick={discardStructure}>丢弃</button>
        {/if}
        <button class="link" onclick={closeStructurePanel}>收起</button>
      </div>

      {#if ai.proposal}
        <div class="note warn">
          <Icon name="warn" size={11} />
          <span>当前还有润色建议：结构应用后原文/条数会变，润色建议可能失效；建议先应用或丢弃它。</span>
        </div>
      {/if}

      <textarea
        class="paste-box struct-box"
        bind:value={structure.text}
        spellcheck="false"
        placeholder={'{"ops":[{"op":"merge","from":3,"to":4,"text":"初めてのお客さんですねぇ","reason":"碎轴"},{"op":"retime","i":22,"start":85.829,"end":89.486}]}'}
      ></textarea>
      <div class="paste-actions">
        <button
          class="btn primary"
          onclick={parseStructurePaste}
          disabled={structure.parsing || !structure.text.trim()}
        >
          {structure.parsing ? '解析中…' : '解析建议'}
        </button>
        <span class="paste-hint">
          只接受 &#123;"ops": [...]&#125;；序号按当前字幕 1-based；模型不需要输出 digest / version
        </span>
      </div>

      {#if structure.errors.length}
        <div class="note err"><Icon name="warn" size={11} /><span>{structure.errors[0]}</span></div>
      {/if}
      {#if structure.warnings.length}
        <div class="note warn">
          <Icon name="warn" size={11} />
          <span>{structure.warnings.slice(0, 3).join('；')}{structure.warnings.length > 3 ? ' …' : ''}</span>
        </div>
      {/if}

      {#if structure.ops.length}
        <div class="struct-summary">
          <span>共 <b>{structure.ops.length}</b> 项</span>
          {#if structure.summary}
            <span>结果 <b>{structure.summary.input_count}</b> → <b>{structure.summary.output_count}</b> 条</span>
            {#if structure.summary.conflicts}
              <span class="conflict">冲突 <b>{structure.summary.conflicts}</b></span>
            {/if}
          {/if}
          <div class="spacer"></div>
          <button class="link" onclick={() => setAllStructureOps(true)}>全选</button>
          <button class="link" onclick={() => setAllStructureOps(false)}>全不选</button>
        </div>

        <div class="struct-list">
          {#each structureGroups as group (group.key)}
            <div class="struct-group">
              <div class="struct-group-title">{group.label} <b>{group.ops.length}</b></div>
              {#each group.ops as op (op.id)}
                <label class="struct-row" class:conflict={op.conflict.length > 0}>
                  <input
                    type="checkbox"
                    checked={Boolean(structure.selected[op.id])}
                    disabled={op.conflict.length > 0}
                    onchange={() => toggleStructureOp(op.id)}
                  />
                  <span class="op-badge">{opLabel(op.op)}</span>
                  <span class="op-idx">{op.index_label}</span>
                  <span class="op-body">
                    <span class="op-line">
                      {#if op.op === 'retime' || op.op === 'insert' || op.before === op.after}
                        {op.after}
                      {:else}
                        {op.before}
                        <span class="arrow">→</span>
                        {#if op.op === 'delete'}<span class="muted">（删除）</span>{:else}{op.after}{/if}
                      {/if}
                    </span>
                    {#if op.reason}<span class="op-reason">{op.reason}</span>{/if}
                    {#if op.conflict.length}<span class="op-conflict">{op.conflict.join('；')}</span>{/if}
                  </span>
                  <span class="op-time">{opTime(op)}</span>
                </label>
              {/each}
            </div>
          {/each}
        </div>

        <div class="struct-actions">
          <button
            class="btn primary"
            onclick={onApplyStructure}
            disabled={structure.applying || selectedStructureCount() === 0}
          >
            {structure.applying ? '应用中…' : `应用所选${selectedStructureCount() ? `（${selectedStructureCount()}）` : ''}`}
          </button>
          <span class="paste-hint">⌘Z 一次整批撤回；应用后这份建议会丢弃</span>
        </div>
      {:else if !structure.loading}
        <div class="struct-empty">
          还没有解析出结构建议：先复制上面的提示词给外部模型，再把 &#123;"ops": [...]&#125; 粘回来。
        </div>
      {/if}
    </div>
  {/if}

  {#if !structure.open}
  {#if ai.proposal}
    <div class="bar">
      <span>共 <b>{app.cues.length}</b> 条</span>
      <span class="sep"></span>
      <span>AI 改动 <b class="warn">{changedCount}</b> 处</span>
      <span class="sep"></span>
      <span>已采纳 <b>{acceptedCount}</b></span>
      {#if ai.mode === 'dual'}
        <span class="sep"></span>
        <span>漏句 <b>{dual.stats?.only_a ?? 0}</b> / <b>{dual.stats?.only_b ?? 0}</b></span>
      {/if}
      <div class="spacer"></div>
      <label class="chk">
        <input type="checkbox" bind:checked={ai.changedOnly} />
        只看改动
      </label>
      {#if ai.mode === 'dual'}
        <button class="link" onclick={() => (bCollapsed = !bCollapsed)} title="折叠 B 栏，给终稿更多宽度">
          {bCollapsed ? '展开 B 栏' : '折叠 B 栏'}
        </button>
      {/if}
      <button class="link" onclick={() => setAllAiAccept(true)} disabled={!ai.proposal}>全选</button>
      <button class="link" onclick={() => setAllAiAccept(false)} disabled={!ai.proposal}>全不选</button>
    </div>
  {/if}

  {#if ai.mode === 'dual' && ai.longMode && ai.segments.length}
    <div class="segments">
      <span class="seg-label">长片分段 · 已填 {filledCount}/{ai.segments.length}</span>
      <div class="seg-list">
        {#each ai.segments as seg, index (seg.from)}
          <button
            class="seg-chip"
            class:on={index === ai.segmentIndex}
            class:filled={ai.filled[segmentKey(seg)]}
            onclick={() => (ai.segmentIndex = index)}
            title="切换到这一段；复制/粘贴都只作用于当前段"
          >
            <span>第 {index + 1}/{ai.segments.length} 段</span>
            <em>{seg.from}–{seg.to} · {timeRange(seg.start, seg.end)}</em>
            <b>{ai.filled[segmentKey(seg)] ? '✅' : '未填'}</b>
          </button>
        {/each}
      </div>
      <button
        class="btn tiny"
        onclick={() => {
          const next = ai.segments.findIndex((seg) => !ai.filled[segmentKey(seg)]);
          if (next >= 0) ai.segmentIndex = next;
        }}
        title="跳到下一个还没回填的段"
      >
        下一未填
      </button>
    </div>
  {/if}

  {#if ai.proposal && visibleErrors.length}
    <div class="note err"><Icon name="warn" size={11} /><span>{visibleErrors[0]}</span></div>
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
        {#if ai.mode === 'dual' && ai.longMode && ai.segments.length}
          正在回填<b>第 {ai.segments[Math.min(ai.segmentIndex, ai.segments.length - 1)]?.from}–{ai.segments[Math.min(ai.segmentIndex, ai.segments.length - 1)]?.to} 条</b>。
          序号可以是全局的，也可以是本段从 1 开始的；只按顺序取文本，条数必须正好是本段条数。
        {:else}
          把模型返回的 SRT 整段粘在下面。<b>序号和时间戳会被忽略</b>，只按顺序取文本，时间轴仍用你自己的。
        {/if}
      </div>
      <textarea
        class="paste-box"
        bind:value={ai.pasteText}
        spellcheck="false"
        placeholder={'1\n00:00:00,500 --> 00:00:01,500\nおはよう\n\n2\n…'}
      ></textarea>
      <div class="paste-actions">
        <button class="btn primary" onclick={parseAiPastedSrt} disabled={ai.parsing || !ai.pasteText.trim()}>
          {ai.parsing ? '解析中…' : ai.mode === 'dual' && ai.longMode ? '解析并回填本段' : '解析成建议'}
        </button>
        <button class="btn ghost" onclick={() => (ai.pasteOpen = false)}>取消</button>
        {#if ai.mode === 'dual' && ai.longMode && ai.segments.length}
          <button
            class="btn ghost"
            onclick={() => {
              if (ai.segmentIndex < ai.segments.length - 1) ai.segmentIndex += 1;
            }}
          >
            下一段
          </button>
        {/if}
        <span class="paste-hint">条数不符会整段拒绝，并提示期望条数与实际条数</span>
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
      <span class="blank-icon"><Icon name="sparkle" size={24} /></span>
      <div class="et">还没有可对照的修改建议</div>
      <div class="es">
        {ai.mode === 'dual'
          ? 'AI 会同时拿到 A 与 B，但严格以 A 的序号与时间轴为骨架输出终稿。'
          : '点「生成建议」，或导入外部工具写好的建议；时间码保持不变。'}
      </div>
      {#if visibleErrors.length}
        <div class="blank-err"><Icon name="warn" size={11} />{visibleErrors[0]}</div>
      {/if}
      <div class="ea">
        <button class="btn primary" onclick={startAiPolish} disabled={ai.generating || !app.cues.length}>生成建议</button>
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
    <div class="cols" class:dual={ai.mode === 'dual' && !bCollapsed} class:no-notes={!hasNotes}>
      <span class="c-time">时间码</span>
      <span class="c-side">A · 原文（只读）</span>
      {#if ai.mode === 'dual' && !bCollapsed}
        <span class="c-side">B · 第二引擎（只读）</span>
      {/if}
      <span class="c-side">AI 终稿（双击可改）</span>
      {#if hasNotes}<span class="c-note">理由</span>{/if}
      <span></span>
    </div>
    <div class="list">
      {#each visible as row (row.i)}
        <div
          class="row"
          class:dual={ai.mode === 'dual' && !bCollapsed}
          class:no-notes={!hasNotes}
          class:changed={row.changed}
          class:off={!row.accepted}
        >
          <div class="c-time">
            <button class="tc" onclick={() => goto(row)} title="回到核对台定位这一句">{tcShort(row.start)}</button>
            <span class="idx">#{row.i}</span>
          </div>
          <div class="c-side left">{row.before}</div>
          {#if ai.mode === 'dual' && !bCollapsed}
            <div class="c-side ref">{bTexts.get(row.i) ?? ''}</div>
          {/if}
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
  .title {
    font-size: 13px;
    font-weight: 600;
  }
  .spacer {
    flex: 1;
  }
  .tb-div,
  .sep {
    width: 1px;
    height: 11px;
    background: var(--separator);
  }
  .tb-div {
    height: 16px;
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
    padding: var(--sp-1) var(--sp-3);
    border-radius: 4px;
    cursor: pointer;
  }
  .seg.on {
    background: var(--bg-content);
    color: var(--text);
    box-shadow: 0 1px 2px rgba(0, 0, 0, 0.12);
  }
  .seg:disabled {
    color: var(--text-3);
    cursor: default;
  }
  .lang {
    font: inherit;
    font-size: 12px;
    padding: 3px 6px;
    border-radius: 4px;
    border: 1px solid var(--separator);
    background: var(--bg-content);
    color: var(--text);
    max-width: 180px;
  }
  .badge {
    font-size: 12px;
    padding: 2px 7px;
    border-radius: 999px;
    background: var(--accent-soft);
    color: var(--accent);
    white-space: nowrap;
  }
  .badge.quiet {
    background: var(--fill);
    color: var(--text-2);
  }
  .ref-note {
    font-size: 12px;
    color: var(--text-3);
    white-space: nowrap;
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
  .note.busy {
    background: var(--accent-soft);
    color: var(--text);
  }
  .note.busy .pct {
    margin-left: auto;
    font-variant-numeric: tabular-nums;
  }
  .segments {
    display: flex;
    align-items: center;
    gap: var(--sp-2);
    padding: 7px 14px;
    border-bottom: 1px solid var(--separator-soft);
    background: var(--bg-inspector);
    min-width: 0;
  }
  .seg-label {
    flex: 0 0 auto;
    font-size: 12px;
    color: var(--text-2);
    font-variant-numeric: tabular-nums;
  }
  .seg-list {
    flex: 1;
    display: flex;
    gap: 6px;
    overflow-x: auto;
    min-width: 0;
    padding-bottom: 2px;
  }
  .seg-chip {
    flex: 0 0 auto;
    display: flex;
    align-items: center;
    gap: 6px;
    border: 1px solid var(--separator);
    background: var(--bg-content);
    color: var(--text-2);
    border-radius: 6px;
    padding: 3px 7px;
    font: inherit;
    font-size: 12px;
    cursor: pointer;
    white-space: nowrap;
  }
  .seg-chip em {
    font-style: normal;
    color: var(--text-3);
    font-variant-numeric: tabular-nums;
  }
  .seg-chip b {
    color: var(--text-3);
    font-weight: 500;
  }
  .seg-chip.on {
    border-color: var(--accent);
    background: var(--accent-soft);
    color: var(--accent);
  }
  .seg-chip.filled b {
    color: var(--success);
  }
  .count {
    margin-left: 5px;
    font-size: 11px;
    line-height: 16px;
    padding: 0 5px;
    border-radius: 999px;
    background: var(--accent-soft);
    color: var(--accent);
    font-variant-numeric: tabular-nums;
  }
  .struct {
    display: flex;
    flex-direction: column;
    gap: var(--sp-2);
    padding: 10px 14px;
    border-bottom: 1px solid var(--separator);
    background: var(--bg-inspector);
    flex: 1;
    min-height: 0;
    overflow: auto;
  }
  .struct-head {
    display: flex;
    align-items: center;
    gap: var(--sp-2);
    flex-wrap: wrap;
  }
  .struct-title {
    font-size: 13px;
    font-weight: 600;
  }
  .struct-head .link.danger {
    color: var(--danger);
  }
  .struct-box {
    min-height: 84px;
  }
  .struct .note {
    padding: 4px 0;
    border-bottom: 0;
    background: transparent;
  }
  .struct .note.err {
    background: var(--danger-soft);
    padding: 4px 6px;
    border-radius: 4px;
  }
  .struct .note.warn {
    background: var(--warn-soft);
    padding: 4px 6px;
    border-radius: 4px;
  }
  .struct-summary {
    display: flex;
    align-items: center;
    gap: var(--sp-2);
    font-size: 12px;
    color: var(--text-2);
    flex-wrap: wrap;
  }
  .struct-summary b {
    color: var(--text);
    font-variant-numeric: tabular-nums;
  }
  .struct-summary .conflict,
  .struct-summary .conflict b {
    color: var(--danger);
  }
  .struct-list {
    display: flex;
    flex-direction: column;
    gap: var(--sp-2);
  }
  .struct-group {
    display: flex;
    flex-direction: column;
    gap: 4px;
  }
  .struct-group-title {
    font-size: 11px;
    color: var(--text-3);
    letter-spacing: 0.02em;
  }
  .struct-group-title b {
    color: var(--text-2);
    font-variant-numeric: tabular-nums;
  }
  .struct-row {
    display: flex;
    align-items: flex-start;
    gap: 7px;
    padding: 6px 8px;
    border: 1px solid var(--separator);
    border-radius: 6px;
    background: var(--bg-content);
    cursor: pointer;
  }
  .struct-row:hover {
    background: var(--row-hover);
  }
  .struct-row.conflict {
    border-color: color-mix(in srgb, var(--danger) 45%, transparent);
    background: color-mix(in srgb, var(--danger) 6%, var(--bg-content));
    cursor: default;
  }
  .struct-row input {
    margin-top: 3px;
  }
  .op-badge {
    flex: 0 0 auto;
    font-size: 11px;
    line-height: 18px;
    padding: 0 5px;
    border-radius: 4px;
    background: var(--fill);
    color: var(--text-2);
    white-space: nowrap;
  }
  .op-idx {
    flex: 0 0 auto;
    font-family: var(--mono, ui-monospace, SFMono-Regular, Menlo, monospace);
    font-size: 11px;
    line-height: 18px;
    color: var(--text-3);
    white-space: nowrap;
  }
  .op-body {
    flex: 1;
    min-width: 0;
    display: flex;
    flex-direction: column;
    gap: 1px;
  }
  .op-line {
    font-size: 12.5px;
    line-height: 1.5;
    white-space: pre-wrap;
    word-break: break-word;
  }
  .op-line .arrow {
    color: var(--text-3);
    margin: 0 5px;
  }
  .op-line .muted {
    color: var(--text-3);
  }
  .op-reason {
    font-size: 11px;
    color: var(--text-3);
  }
  .op-conflict {
    font-size: 11px;
    color: var(--danger);
  }
  .op-time {
    flex: 0 0 auto;
    font-family: var(--mono, ui-monospace, SFMono-Regular, Menlo, monospace);
    font-size: 11px;
    line-height: 18px;
    color: var(--text-3);
    white-space: nowrap;
  }
  .struct-actions {
    display: flex;
    align-items: center;
    gap: var(--sp-2);
    flex-wrap: wrap;
  }
  .struct-empty {
    font-size: 12px;
    line-height: 1.6;
    color: var(--text-3);
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
  .cols.dual,
  .row.dual {
    grid-template-columns: 92px minmax(0, 0.95fr) minmax(0, 0.95fr) minmax(0, 1.1fr) 78px 26px;
  }
  .cols.no-notes,
  .row.no-notes {
    grid-template-columns: 92px minmax(0, 1fr) minmax(0, 1fr) 26px;
  }
  .cols.dual.no-notes,
  .row.dual.no-notes {
    grid-template-columns: 92px minmax(0, 0.95fr) minmax(0, 0.95fr) minmax(0, 1.1fr) 26px;
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
  .ref {
    color: var(--text-3);
    border-left: 1px solid var(--separator-soft);
    padding-left: var(--sp-2);
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
    max-width: 460px;
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
