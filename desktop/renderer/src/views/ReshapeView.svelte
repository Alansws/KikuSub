<script lang="ts">
  /**
   * 断句重排页：把「切得不像人话」的字幕整份交给外部模型重排，再整段换回核对台。
   *
   * 与润色页的分工只有一句话：**润色改字、时间轴不动；这里改切分、时间轴可以动。**
   * 两种做法共用一个粘贴入口：
   * - 整份重写：提示词不要求 1:1，粘回来的一整份 SRT 覆盖当前段（条数会话可变）；
   * - 只改几处：沿用 ops JSON，只动模型点名的那几处，逐项可拒。
   *
   * 主操作只有一条、文案随状态变：复制 → 贴回 → 扫一遍并覆盖。
   */
  import Icon from '../components/Icon.svelte';
  import type { StructureOpView } from '../lib/api';
  import {
    activeDraft,
    appliedCount,
    applyReshapeDraft,
    closePaste,
    copyReshapePrompt,
    currentRangeFor,
    currentSegment,
    discardDraft,
    ensurePromptInfo,
    ensureReshapePlan,
    openPaste,
    parseReshapeText,
    promptCategory,
    removeDraftCue,
    reshape,
    resetReshape,
    segmentKey,
    segmentState,
    setMode,
    setSegment,
    setSource,
    updateDraftCue,
  } from '../lib/reshape.svelte';
  import {
    applyStructureOps,
    closeStructurePanel,
    copyStructurePrompt,
    discardStructure,
    loadStructure,
    parseStructurePaste,
    selectedStructureCount,
    setAllStructureOps,
    structure,
    toggleStructureOp,
  } from '../lib/structure.svelte';
  import { altEngineLabel, dual, refreshAltReview } from '../lib/dualReview.svelte';
  import {
    loadPrompts,
    promptItemsFor,
    prompts,
    selectPromptTemplate,
    promptSelectedId,
  } from '../lib/promptStore.svelte';
  import { app, loadTranslations, setView, toast } from '../lib/store.svelte';
  import { tcShort } from '../lib/time';
  import { loadAiProposal } from '../lib/aiWorkspace.svelte';

  let editing = $state(0);
  let editingText = $state('');
  /** 已确认过一次的草稿 digest：条数腰斩时要再点一下才真覆盖。 */
  let armed = $state('');
  /** 「只改几处」的粘贴卡是否展开（不能靠 text 是否为空判断，否则清空输入框就整块消失）。 */
  let opsPasting = $state(false);

  const segment = $derived(currentSegment());
  const draft = $derived(activeDraft());
  const templates = $derived(promptItemsFor(promptCategory()));
  const activeTemplate = $derived(promptSelectedId(promptCategory()));

  /** 当前处于第几步：1 复制提示词 / 2 贴回结果 / 3 扫一遍并覆盖。 */
  const step = $derived.by(() => {
    if (reshape.mode === 'ops') {
      if (structure.ops.length) return 3;
      return opsPasting ? 2 : 1;
    }
    if (draft) return 3;
    return reshape.pasteOpen ? 2 : 1;
  });

  const opsGroups = $derived.by(() => {
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

  // 换片 / 换源：清掉上一部片留下的草稿，否则段号和指纹都会对不上。
  $effect(() => {
    void app.media?.id;
    resetReshape();
  });

  // 分段计划：换片 / 换做法 / 换源 / 第二版变化时才重切，之后冻结。
  $effect(() => {
    void app.connected;
    void app.media?.id;
    void app.cues.length;
    void dual.exists;
    void dual.count;
    void reshape.mode;
    void reshape.source;
    if (app.connected) ensureReshapePlan();
  });

  // 提示词元信息（条数 / 字数 / 模板名）：只用于界面显示，复制时复用同一份。
  $effect(() => {
    void app.connected;
    void app.cuesRevision;
    void dual.exists;
    void reshape.mode;
    void reshape.source;
    void reshape.segmentIndex;
    void prompts.selectedReshapeSingle;
    void prompts.selectedReshapeDual;
    if (app.connected) void ensurePromptInfo();
  });

  // 「只改几处」：把当前媒体 / 字幕版本上的 ops 建议读回来。
  $effect(() => {
    void app.connected;
    void app.media?.id;
    void app.cuesRevision;
    void reshape.mode;
    if (app.connected && reshape.mode === 'ops') void loadStructure();
  });

  $effect(() => {
    void app.connected;
    if (app.connected) void loadPrompts();
  });

  function switchMode(mode: 'rewrite' | 'ops') {
    if (reshape.mode === mode) return;
    if (reshape.mode === 'ops') closeStructurePanel();
    setMode(mode);
    if (mode === 'ops') void loadStructure();
  }

  function switchSource(source: 'single' | 'dual') {
    if (source === 'dual' && !dual.exists) {
      toast('还没有第二版字幕：先在转写页用另一个引擎转一次，或到双引擎复核页导入一份', 'warn');
      return;
    }
    setSource(source);
  }

  async function copyPrompt() {
    if (reshape.mode === 'ops') {
      // 复制完直接把粘贴框打开：仓库里没有别的入口告诉用户「贴哪里」。
      if (await copyStructurePrompt(reshape.source)) opsPasting = true;
      return;
    }
    await copyReshapePrompt();
  }

  async function parsePaste() {
    if (reshape.mode === 'ops') await parseStructurePaste();
    else await parseReshapeText();
  }

  async function applyDraft() {
    if (reshape.mode === 'ops') {
      const applied = await applyStructureOps();
      if (applied) {
        opsPasting = false;
        afterApply();
      }
      return;
    }
    const ok = await applyReshapeDraft();
    if (ok) afterApply();
  }

  /** 表格被换掉之后，润色提案、译文轨、第二版对齐都该重新对齐一次。 */
  function afterApply() {
    void loadTranslations();
    void refreshAltReview();
    void loadAiProposal(true);
  }

  function openPastePanel() {
    if (reshape.mode === 'ops') opsPasting = true;
    else openPaste();
  }

  function cancelPastePanel() {
    if (reshape.mode === 'ops') {
      opsPasting = false;
      structure.text = '';
    } else {
      closePaste();
    }
  }

  function pasteBoxEmpty(): boolean {
    return reshape.mode === 'ops' ? !structure.text.trim() : !reshape.text.trim();
  }

  function onPaste(event: ClipboardEvent) {
    const text = event.clipboardData?.getData('text') ?? '';
    if (text.trim().length < 40) return;
    const target = reshape.mode === 'ops' ? structure.text : reshape.text;
    // 只在空框里自动解析：往已有内容里补粘一段时，不该直接覆盖整份稿。
    if (target.trim()) return;
    setTimeout(() => {
      if (!pasteBoxEmpty()) return;
      void parsePaste();
    }, 180);
  }

  function jumpToFirstIssue() {
    document.querySelector('.row.flagged')?.scrollIntoView({ block: 'center' });
  }

  function beginEdit(index: number, text: string) {
    editing = index;
    editingText = text;
  }

  function commitEdit(index: number) {
    if (editing !== index) return;
    updateDraftCue(index, editingText);
    editing = 0;
  }

  function onEditKey(event: KeyboardEvent, index: number) {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      commitEdit(index);
    } else if (event.key === 'Escape') {
      event.preventDefault();
      editing = 0;
    }
  }

  function focusOnMount(node: HTMLTextAreaElement) {
    node.focus();
  }

  /** 紧凑时间码：`mm:ss.cc`，超过一小时才带小时位（列宽才不会把正文挤掉）。 */
  function shortTime(value: number): string {
    const total = Math.max(0, Number(value) || 0);
    const hours = Math.floor(total / 3600);
    const minutes = Math.floor((total % 3600) / 60);
    const seconds = total % 60;
    const body = `${String(minutes).padStart(2, '0')}:${seconds.toFixed(2).padStart(5, '0')}`;
    return hours ? `${hours}:${body}` : body;
  }

  /** 段轨用的短时钟：`mm:ss`，超过一小时带小时位。 */
  function shortClock(value: number): string {
    const total = Math.max(0, Number(value) || 0);
    const hours = Math.floor(total / 3600);
    const minutes = Math.floor((total % 3600) / 60);
    const seconds = Math.floor(total % 60);
    const body = `${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`;
    return hours ? `${hours}:${body}` : body;
  }

  function opLabel(op: string): string {
    return (
      ({ merge: '合并', retime: '改时间', replace_text: '改文字', insert: '新增', delete: '删除' }) as Record<
        string,
        string
      >
    )[op] ?? op;
  }

  function opTime(op: StructureOpView): string {
    const fmt = (value: number | null) => (value === null ? '—' : tcShort(value));
    if (op.op === 'insert') return `${fmt(op.new_start)}–${fmt(op.new_end)}`;
    if (op.op === 'retime') return `${fmt(op.old_start)} → ${fmt(op.new_start)}`;
    if (op.op === 'merge') return `${fmt(op.old_start)}–${fmt(op.old_end)}`;
    return fmt(op.old_start);
  }

  /** 覆盖前后的条数差；0 表示没变，界面不显示。 */
  /**
   * 条数掉一半以上（或翻倍）时要求二次确认。
   *
   * 正常重排 208→127 不触发；但只贴了半份、或把 Prompt 的示例内容粘进来时，
   * 一键覆盖会把整份稿换掉——这类错误一次就够痛，值得多一次点击。
   */
  const needsArm = $derived.by(() => {
    if (!draft) return false;
    const before = draft.diagnostics.count_before;
    if (!before) return false;
    return draft.cues.length < before * 0.5 || draft.cues.length > before * 2;
  });
  const isArmed = $derived(Boolean(draft && armed === draft.digest));

  function onApplyClick() {
    if (!draft) return;
    if (needsArm && !isArmed) {
      armed = draft.digest;
      return;
    }
    void applyDraft();
  }

  function countDelta(): number {
    if (!draft) return 0;
    return draft.cues.length - draft.diagnostics.count_before;
  }

  const metaText = $derived.by(() => {
    const info = reshape.prompt;
    if (!info) return '';
    const parts = [rangeLabel];
    if (info.alt_count) parts.push(`参考 ${info.alt_count} 条`);
    parts.push(`约 ${(info.chars / 1000).toFixed(1)}k 字`);
    return parts.join(' · ');
  });

  const rangeLabel = $derived.by(() => {
    const value = segment;
    if (!value) return '';
    if (!reshape.longMode) return `全片 ${value.count} 条`;
    const range = currentRangeFor(value);
    return `第 ${range.from}–${range.to} 条`;
  });
</script>

<div class="reshape">
  <header class="head">
    <div class="head-copy">
      <h1>断句重排</h1>
      <p>合并碎句、重切长句、调整时间与结构</p>
    </div>
    <div class="spacer"></div>
    <button class="btn ghost" onclick={() => setView('prompts')} title="打开提示词库">
      提示词库
    </button>
  </header>

  <div class="config">
    <span class="dim">做法</span>
    <div class="segs" role="tablist" aria-label="做法">
      <button
        role="tab"
        aria-selected={reshape.mode === 'rewrite'}
        class="seg"
        class:on={reshape.mode === 'rewrite'}
        onclick={() => switchMode('rewrite')}
        title="让模型自由重切，整份换掉这一段（条数与时间码都可变）"
      >整份重写</button>
      <button
        role="tab"
        aria-selected={reshape.mode === 'ops'}
        class="seg"
        class:on={reshape.mode === 'ops'}
        onclick={() => switchMode('ops')}
        title="只改模型点名的那几处（合并 / 改时间 / 增删），逐项可拒"
      >只改几处</button>
    </div>

    <span class="config-sep" aria-hidden="true"></span>
    <span class="dim">底稿</span>
    <div class="segs" role="group" aria-label="参考来源">
      <button
        class="seg"
        class:on={reshape.source === 'single'}
        onclick={() => switchSource('single')}
        title="只吃核对台当前版本"
      >当前稿</button>
      <button
        class="seg"
        class:on={reshape.source === 'dual'}
        onclick={() => switchSource('dual')}
        disabled={!dual.exists}
        title={dual.exists ? `同时参考第二引擎（${altEngineLabel()}，${dual.count} 条）` : '还没有第二版字幕（可转写或导入）'}
      >+ 第二引擎</button>
    </div>

    {#if reshape.mode === 'rewrite' && templates.length}
      <select
        class="select"
        value={activeTemplate}
        onchange={(event) =>
          void selectPromptTemplate(event.currentTarget.value, promptCategory())}
        title="断句重排提示词模板"
      >
        {#each templates as item (item.id)}
          <option value={item.id}>{item.name}</option>
        {/each}
      </select>
    {/if}

    <div class="spacer"></div>

    {#if reshape.mode === 'rewrite' && reshape.longMode}
      <span class="progress-title">已覆盖 {appliedCount()}/{reshape.segments.length} 段</span>
    {:else if app.cues.length && !draft}
      <span class="progress-title">{app.cues.length} 条</span>
    {/if}
  </div>

  {#if reshape.mode === 'rewrite' && reshape.longMode}
    <div class="rail" role="tablist" aria-label="长片分段">
      {#each reshape.segments as item, index (segmentKey(item))}
        {@const state = segmentState(item)}
        <button
          class="rail-item"
          class:on={index === reshape.segmentIndex}
          class:done={state === 'done'}
          onclick={() => setSegment(index)}
          title={`第 ${item.count} 条 · 复制与粘贴都只作用于这一段`}
        >
          <span class="rail-no">{String(index + 1).padStart(2, '0')}</span>
          <span class="rail-body">
            <!-- 已覆盖段显示覆盖后的条数（计划条数 + 这一段的增减），否则段轨会说谎 -->
            <span class="rail-count"
              >{item.count + (reshape.applied[segmentKey(item)]?.delta ?? 0)} 条</span
            >
            <span class="rail-time">{shortClock(item.start)}–{shortClock(item.end)}</span>
          </span>
          {#if state === 'done'}
            <span class="rail-flag done" title="已覆盖"><Icon name="check" size={11} /></span>
          {:else if state === 'ready'}
            <span class="rail-flag ready" title="已贴回，待覆盖">●</span>
          {/if}
        </button>
      {/each}
    </div>
  {/if}

  <div class="steps" aria-label="这一步做什么">
    <span class="step" class:on={step === 1} class:done={step > 1}>
      <b>{step > 1 ? '✓' : '1'}</b>复制提示词
    </span>
    <span class="step-line" class:done={step > 2}></span>
    <span class="step" class:on={step === 2} class:done={step > 2}>
      <b>{step > 2 ? '✓' : '2'}</b>贴回结果
    </span>
    <span class="step-line"></span>
    <span class="step" class:on={step === 3}>
      <b>3</b>{reshape.mode === 'ops' ? '勾选并应用' : '扫一遍并覆盖'}
    </span>
    <div class="spacer"></div>
    {#if reshape.mode === 'rewrite' && reshape.prompt}
      <span class="step-meta">{metaText}</span>
    {:else if reshape.mode === 'ops' && structure.exists}
      <span class="step-meta">已用 {structure.sourceCount} 条稿生成</span>
    {:else if reshape.mode === 'rewrite' && !app.cues.length}
      <span class="step-meta warn">还没有字幕：先导入或转写</span>
    {/if}
  </div>

  {#if reshape.errors.length}
    <div class="note err"><Icon name="warn" size={11} /><span>{reshape.errors[0]}</span></div>
  {/if}
  {#if structure.errors.length && reshape.mode === 'ops'}
    <div class="note err"><Icon name="warn" size={11} /><span>{structure.errors[0]}</span></div>
  {/if}

  <div class="body">
    {#if reshape.mode === 'ops'}
      <!-- ---------------- 只改几处（ops） ---------------- -->
      {#if structure.ops.length}
        <div class="ops-bar">
          <span>共 <b>{structure.ops.length}</b> 项</span>
          {#if structure.summary}
            <span class="dim">结果 <b>{structure.summary.input_count}</b> → <b>{structure.summary.output_count}</b> 条</span>
            {#if structure.summary.conflicts}
              <span class="conflict">冲突 <b>{structure.summary.conflicts}</b>（红色项不能应用）</span>
            {/if}
          {/if}
          <div class="spacer"></div>
          <button class="link" onclick={() => setAllStructureOps(true)}>全选</button>
          <button class="link" onclick={() => setAllStructureOps(false)}>全不选</button>
          <button class="link danger" onclick={() => discardStructure()}>丢弃</button>
        </div>

        <div class="ops-list">
          {#each opsGroups as group (group.key)}
            <div class="ops-group">
              <div class="ops-group-title">{group.label} <b>{group.ops.length}</b></div>
              {#each group.ops as op (op.id)}
                <label class="op-row" class:conflict={op.conflict.length > 0}>
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

        <div class="apply-bar">
          <button
            class="btn primary apply"
            onclick={() => void applyDraft()}
            disabled={structure.applying || selectedStructureCount() === 0}
          >
            {structure.applying ? '应用中…' : `应用所选${selectedStructureCount() ? `（${selectedStructureCount()}）` : ''}`}
          </button>
          <button class="btn ghost" onclick={openPastePanel}>再贴一份</button>
          <span class="hint">⌘Z 一次整批撤回；应用后这份建议即被丢弃</span>
        </div>
      {:else if opsPasting || structure.parsing}
        <div class="paste-card">
          <div class="paste-head">把模型返回的 ops JSON 粘在这里</div>
          <textarea
            class="paste-box"
            bind:value={structure.text}
            onpaste={onPaste}
            spellcheck="false"
            placeholder={'把模型回复的 ops JSON 粘在这里'}
          ></textarea>
          <div class="paste-actions">
            <button class="btn primary" onclick={() => void parsePaste()} disabled={structure.parsing || !structure.text.trim()}>
              {structure.parsing ? '解析中…' : '解析改动'}
            </button>
            <button class="btn ghost" onclick={cancelPastePanel}>取消</button>
            <span class="hint">只收 &#123;"ops": [...]&#125;；序号按当前字幕 1-based</span>
          </div>
        </div>
      {:else}
        <div class="cta">
          <p class="cta-title">先拿提示词</p>
          <button class="btn primary big" onclick={() => void copyPrompt()} disabled={!app.cues.length || structure.promptLoading}>
            {structure.promptLoading ? '正在准备…' : '复制提示词'}
          </button>
          <p class="cta-meta">
            模型只回 <code>&#123;"ops": [...]&#125;</code>，只动你点名的几处
          </p>
          <button class="link" onclick={openPastePanel} disabled={!app.cues.length}>已有结果？直接粘贴</button>
        </div>
      {/if}
    {:else if draft}
      <!-- ---------------- 整份重写：预览 ---------------- -->
      <div class="preview-bar">
        {#each draft.notes as note (note.text)}
          {#if note.level === 'warn'}
            <button class="chip warn" onclick={jumpToFirstIssue} title="跳到第一处有问题的地方">
              {note.text}
            </button>
          {:else}
            <span class="chip">{note.text}</span>
          {/if}
        {/each}
        <span class="preview-hint">双击改字</span>
        <button
          class="link"
          onclick={() => {
            discardDraft();
            openPastePanel();
          }}
        >重新粘贴</button>
      </div>

      <div class="draft-list">
        {#each draft.cues as cue, index (index)}
          {@const number = index + 1}
          <div class="row" class:flagged={Boolean(draft.issues[number])}>
            <span class="row-mark">
              {#if draft.issues[number]}<Icon name="warn" size={12} />{/if}
            </span>
            <div class="row-time" title={`第 ${number} 条 · ${tcShort(cue.start)} → ${tcShort(cue.end)}`}>
              <span class="tc">{shortTime(cue.start)}</span>
              <span class="tc end">– {shortTime(cue.end)}</span>
            </div>
            <div class="row-text" ondblclick={() => beginEdit(number, cue.text)}>
              {#if editing === number}
                <textarea
                  use:focusOnMount
                  bind:value={editingText}
                  onkeydown={(event) => onEditKey(event, number)}
                  onblur={() => commitEdit(number)}
                  spellcheck="false"
                ></textarea>
              {:else}
                <span class="txt">{cue.text}</span>
              {/if}
            </div>
            <span class="row-flag">
              {#if draft.issues[number] && editing !== number}{draft.issues[number]}{/if}
            </span>
            <button
              class="row-del"
              onclick={() => removeDraftCue(number)}
              title="删掉这一条"
              aria-label={`删除第 ${number} 条`}
            ><Icon name="close" size={11} /></button>
          </div>
        {/each}
      </div>

      <div class="apply-bar">
        <button
          class="btn primary apply"
          class:armed={needsArm && isArmed}
          onclick={onApplyClick}
          disabled={reshape.applying || !draft.cues.length}
        >
          {#if reshape.applying}
            覆盖中…
          {:else if needsArm && isArmed}
            再点一次：覆盖 {draft.cues.length} 条
          {:else if needsArm}
            确认覆盖 · {draft.cues.length} 条
          {:else if draft.range.full}
            覆盖核对台 · {draft.cues.length} 条
          {:else}
            覆盖这一段 · {draft.cues.length} 条
          {/if}
        </button>
        {#if countDelta()}
          <span class="delta" class:less={countDelta() < 0}>
            {countDelta() > 0 ? '多' : '少'} {Math.abs(countDelta())} 条
          </span>
        {/if}
        <span class="hint">⌘Z 一次整批撤回{draft.range.full ? '' : '；只替换这一段，其余段不动'}</span>
        <div class="spacer"></div>
        <button class="btn ghost" onclick={() => discardDraft()} disabled={reshape.applying}>丢弃</button>
      </div>
    {:else if reshape.pasteOpen}
      <!-- ---------------- 整份重写：粘贴 ---------------- -->
      <div class="paste-card">
        <div class="paste-head">
          把模型返回的整份 SRT 粘在这里
          {#if reshape.longMode}<b>（只覆盖 {rangeLabel}）</b>{/if}
        </div>
        <textarea
          class="paste-box"
          bind:value={reshape.text}
          onpaste={onPaste}
          spellcheck="false"
          placeholder={'把模型回复的整段 SRT 粘在这里（必须带时间码）'}
        ></textarea>
        <div class="paste-actions">
          <button class="btn primary" onclick={() => void parsePaste()} disabled={reshape.parsing || !reshape.text.trim()}>
            {reshape.parsing ? '解析中…' : '解析这份新稿'}
          </button>
          <button class="btn ghost" onclick={cancelPastePanel}>取消</button>
          <span class="hint">必须带时间码；条数与时间都可以和原稿不一样</span>
        </div>
      </div>
    {:else}
      <!-- ---------------- 整份重写：空态 ---------------- -->
      <div class="cta">
        <p class="cta-title">
          {#if !app.cues.length}
            还没有字幕
          {:else if reshape.longMode}
            {rangeLabel} 交给模型重排
          {:else}
            整份交给模型重排
          {/if}
        </p>
        <button
          class="btn primary big"
          onclick={() => void copyPrompt()}
          disabled={!app.cues.length || reshape.loadingPrompt}
        >
          {reshape.loadingPrompt ? '正在准备…' : reshape.longMode ? `复制${rangeLabel}的提示词` : '复制整份提示词'}
        </button>
        <p class="cta-meta">
          {#if reshape.longMode}
            模型回一份新的 SRT，只覆盖这一段；条数可以变
          {:else}
            模型回一份新的 SRT，允许合并、拆分、改时间码
          {/if}
        </p>
        <button class="link" onclick={openPastePanel} disabled={!app.cues.length}>已有结果？直接粘贴</button>
        {#if appliedCount() && !draft}
          <button class="link" onclick={() => setView('review')}>刚才覆盖过，去核对台看看</button>
        {/if}
      </div>
    {/if}
  </div>
</div>

<style>
  .reshape {
    flex: 1;
    min-height: 0;
    display: flex;
    flex-direction: column;
    background: var(--paper);
  }
  .head {
    display: flex;
    align-items: flex-end;
    gap: var(--sp-3);
    padding: var(--sp-3) 16px var(--sp-2);
  }
  .head-copy h1 {
    margin: 0;
    font-size: 20px;
    line-height: 26px;
    font-weight: 600;
    letter-spacing: -0.01em;
    color: var(--text);
  }
  .head-copy p {
    margin: 2px 0 0;
    font-size: var(--fs-label);
    line-height: var(--lh-label);
    color: var(--text-3);
  }
  .spacer {
    flex: 1;
  }

  .config {
    display: flex;
    align-items: center;
    gap: var(--sp-2);
    padding: 0 16px var(--sp-3);
    flex-wrap: wrap;
    border-bottom: 1px solid var(--separator);
  }
  .segs {
    display: inline-flex;
    padding: 2px;
    border-radius: var(--rad-control);
    background: var(--fill);
  }
  .seg {
    border: 0;
    background: transparent;
    color: var(--text-2);
    font: inherit;
    font-size: var(--fs-label);
    line-height: 16px;
    padding: 3px var(--sp-2);
    border-radius: 3px;
    cursor: pointer;
    white-space: nowrap;
    transition: background var(--dur-fast) var(--ease), color var(--dur-fast) var(--ease);
  }
  .seg:hover {
    color: var(--text);
  }
  .seg.on {
    background: var(--bg-content);
    color: var(--text);
    box-shadow: 0 1px 2px rgba(0, 0, 0, 0.1);
  }
  .seg:disabled {
    color: var(--text-3);
    cursor: default;
    opacity: 0.4;
  }
  .dim {
    font-size: var(--fs-label);
    color: var(--text-3);
  }
  .select {
    font: inherit;
    font-size: var(--fs-label);
    padding: 3px 6px;
    border-radius: var(--rad-control);
    border: 1px solid var(--separator);
    background: var(--bg-content);
    color: var(--text);
    max-width: 190px;
  }
  .progress-title {
    font-size: var(--fs-label);
    color: var(--text-2);
    font-variant-numeric: tabular-nums;
  }

  /* ---- 段轨：块宽按时长，当前段抬起来一格 ---- */
  .rail {
    display: flex;
    gap: 6px;
    padding: 10px var(--sp-4);
    border-bottom: 1px solid var(--separator-soft);
    background: var(--bg-inspector);
    overflow-x: auto;
    min-width: 0;
  }
  .rail-item {
    /* 按内容定宽、不按比例撑开：比例宽度在段数一多时必然溢出，把最后一格切掉更像 bug */
    flex: 0 0 auto;
    min-width: 112px;
    display: flex;
    align-items: center;
    gap: 7px;
    padding: 6px 9px;
    border: 1px solid var(--separator);
    border-radius: var(--rad-card);
    background: var(--bg-content);
    color: var(--text-2);
    font: inherit;
    text-align: left;
    cursor: pointer;
    transition: border-color var(--dur) var(--ease), background var(--dur) var(--ease),
      box-shadow var(--dur) var(--ease), transform var(--dur) var(--ease);
  }
  .rail-item:hover {
    border-color: var(--accent-line);
  }
  .rail-item.on {
    border-color: var(--accent);
    background: var(--accent-soft);
    color: var(--text);
    box-shadow: 0 1px 3px rgba(0, 0, 0, 0.06);
    transform: translateY(-1px);
  }
  .rail-item.done {
    border-color: color-mix(in srgb, var(--success) 45%, var(--separator));
  }
  .rail-no {
    font-family: var(--font-mono);
    font-size: 11px;
    color: var(--text-3);
    font-variant-numeric: tabular-nums;
  }
  .rail-item.on .rail-no {
    color: var(--accent);
  }
  .rail-item.done .rail-no {
    color: var(--success);
  }
  .rail-body {
    display: flex;
    flex-direction: column;
    gap: 1px;
    min-width: 0;
  }
  .rail-count {
    font-size: var(--fs-label);
    line-height: 15px;
    font-variant-numeric: tabular-nums;
  }
  .rail-time {
    font-family: var(--font-mono);
    font-size: 10.5px;
    line-height: 14px;
    color: var(--text-3);
    font-variant-numeric: tabular-nums;
    white-space: nowrap;
  }
  .rail-flag {
    margin-left: auto;
    font-size: 11px;
    line-height: 16px;
    white-space: nowrap;
    flex: 0 0 auto;
  }
  /* 状态用点/勾代替「未开始」三个字：段一多，文字会把每格撑得放不下 */
  .rail-flag.done {
    color: var(--success);
    display: grid;
    place-items: center;
  }
  .rail-flag.ready {
    color: var(--accent);
    font-size: 9px;
  }

  /* ---- 步骤：一眼看出现在走哪一步 ---- */
  .steps {
    display: flex;
    align-items: center;
    gap: 7px;
    padding: var(--sp-2) var(--sp-4);
    border-bottom: 1px solid var(--separator-soft);
    font-size: var(--fs-label);
    color: var(--text-3);
    min-width: 0;
  }
  .step {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    white-space: nowrap;
  }
  .step b {
    width: 16px;
    height: 16px;
    border-radius: 999px;
    border: 1px solid var(--separator);
    display: grid;
    place-items: center;
    font-size: 10.5px;
    font-weight: 500;
    font-variant-numeric: tabular-nums;
    color: var(--text-3);
    background: var(--bg-content);
  }
  .step.on {
    color: var(--text);
  }
  .step.on b {
    border-color: var(--accent);
    background: var(--accent);
    color: var(--on-accent);
  }
  .step.done {
    color: var(--text-2);
  }
  .step.done b {
    border-color: transparent;
    background: var(--success-soft);
    color: var(--success);
  }
  .step-line {
    width: 18px;
    height: 1px;
    background: var(--separator);
    flex: 0 0 18px;
  }
  .step-line.done {
    background: color-mix(in srgb, var(--success) 45%, transparent);
  }
  .step-meta {
    font-size: 12px;
    color: var(--text-3);
    font-variant-numeric: tabular-nums;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .step-meta.warn {
    color: var(--warn);
  }

  .note {
    display: flex;
    align-items: flex-start;
    gap: 6px;
    padding: 6px var(--sp-4);
    font-size: var(--fs-label);
    line-height: 1.5;
    border-bottom: 1px solid var(--separator-soft);
  }
  .note.err {
    background: var(--danger-soft);
    color: var(--danger);
  }

  .body {
    flex: 1;
    min-height: 0;
    display: flex;
    flex-direction: column;
  }

  /* ---- 空态：一个动作，不写说明书 ---- */
  .cta {
    flex: 1;
    display: flex;
    flex-direction: column;
    /* 左对齐到步骤 1 下面：和步骤条共用一条轴线，动作读起来是「下一步」而不是浮在空白里 */
    align-items: flex-start;
    justify-content: flex-start;
    gap: 10px;
    padding: 44px var(--sp-6) var(--sp-10);
    text-align: left;
  }
  .cta-title {
    margin: 0;
    font-size: var(--fs-heading);
    line-height: var(--lh-heading);
    font-weight: 600;
    color: var(--text);
  }
  .cta-meta {
    margin: 0;
    font-size: var(--fs-label);
    line-height: 1.6;
    color: var(--text-3);
    max-width: 420px;
  }
  .cta-meta {
    max-width: 460px;
  }
  .cta-meta code {
    font-family: var(--font-mono);
    font-size: 11.5px;
  }

  .btn {
    appearance: none;
    font: inherit;
    font-size: var(--fs-ui);
    height: var(--ctl-h);
    padding: 0 var(--sp-3);
    border-radius: var(--rad-control);
    border: 1px solid var(--separator);
    background: var(--bg-content);
    color: var(--text);
    cursor: pointer;
    display: inline-flex;
    align-items: center;
    gap: 6px;
    white-space: nowrap;
  }
  .btn:hover {
    background: var(--fill);
  }
  .btn:disabled {
    opacity: 0.5;
    cursor: default;
  }
  .btn.primary {
    background: var(--btn-primary-bg);
    border-color: transparent;
    color: var(--on-accent);
    font-weight: 500;
  }
  .btn.primary:hover {
    background: var(--btn-primary-hover);
  }
  .btn.primary.armed {
    background: var(--danger);
  }
  .btn.ghost {
    background: transparent;
  }
  .btn.big {
    height: var(--ctl-h-xl);
    padding: 0 var(--sp-6);
    font-size: var(--fs-body);
  }
  .link {
    border: 0;
    background: transparent;
    color: var(--accent);
    font: inherit;
    font-size: var(--fs-label);
    cursor: pointer;
    padding: 2px var(--sp-1);
  }
  .link:disabled {
    color: var(--text-3);
    cursor: default;
  }
  .link.danger {
    color: var(--danger);
  }

  /* ---- 粘贴卡 ---- */
  .paste-card {
    display: flex;
    flex-direction: column;
    gap: var(--sp-2);
    padding: 14px var(--sp-4);
    flex: 1;
    min-height: 0;
  }
  .paste-head {
    font-size: var(--fs-label);
    color: var(--text-2);
  }
  .paste-box {
    flex: 1;
    min-height: 150px;
    resize: none;
    font-family: var(--font-mono);
    font-size: var(--fs-mono);
    line-height: 1.6;
    padding: 10px var(--sp-3);
    border-radius: var(--rad-card);
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
  .hint {
    margin-left: auto;
    font-size: 12px;
    color: var(--text-3);
  }

  /* ---- 预览 ---- */
  .preview-bar {
    display: flex;
    align-items: center;
    gap: 6px;
    padding: var(--sp-2) var(--sp-4);
    border-bottom: 1px solid var(--separator-soft);
    background: var(--bg-inspector);
    flex-wrap: wrap;
  }
  .chip {
    font-size: 12px;
    line-height: 18px;
    padding: 0 7px;
    border-radius: 999px;
    background: var(--fill);
    color: var(--text-2);
    font-variant-numeric: tabular-nums;
    white-space: nowrap;
  }
  .chip.warn {
    background: var(--warn-soft);
    color: var(--warn);
  }

  .draft-list {
    flex: 1;
    min-height: 0;
    overflow: auto;
  }
  .row {
    display: grid;
    /* 正文列封顶 520（一行约 40 字），提示列从固定 x 起排：告警原因也能成一条竖轴 */
    grid-template-columns: 14px 84px minmax(0, 520px) minmax(0, 1fr) 22px;
    align-items: start;
    gap: 10px;
    padding: 5px var(--sp-4) 5px 13px;
    border-bottom: 1px solid var(--separator-soft);
    border-left: 3px solid transparent;
    font-size: 13px;
    line-height: 1.55;
    content-visibility: auto;
    contain-intrinsic-size: auto 36px;
  }
  .row:hover {
    background: var(--row-hover);
  }
  .row.flagged {
    border-left-color: color-mix(in srgb, var(--warn) 75%, transparent);
    background: color-mix(in srgb, var(--warn) 6%, var(--paper));
  }
  .row-mark {
    display: grid;
    place-items: center;
    color: var(--warn);
    margin-top: 1px;
  }
  .row-time {
    display: flex;
    flex-direction: column;
    gap: 1px;
  }
  .tc {
    font-family: var(--font-mono);
    font-size: 11px;
    line-height: 15px;
    color: var(--text-2);
    font-variant-numeric: tabular-nums;
    white-space: nowrap;
  }
  .tc.end {
    color: var(--text-3);
  }
  .row-text {
    min-width: 0;
    white-space: pre-wrap;
    word-break: break-word;
    color: var(--text);
    cursor: text;
    border-radius: 3px;
    padding: 0 3px;
    margin: 0 -3px;
  }
  .row-text:hover {
    background: var(--fill);
  }
  .row-text textarea {
    width: 100%;
    min-height: 34px;
    resize: vertical;
    font: inherit;
    line-height: inherit;
    padding: 2px 5px;
    border-radius: var(--rad-control);
    border: 1px solid var(--accent);
    background: var(--bg-content);
    color: var(--text);
    outline: none;
  }
  /* 提示独立成列：正文封顶后，所有告警原因从同一个 x 起排，扫一列就能看完 */
  .row-flag {
    display: block;
    font-size: 12px;
    line-height: 1.5;
    color: var(--warn);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    padding-top: 1px;
  }
  .row-del {
    width: 20px;
    height: 20px;
    border: 0;
    border-radius: var(--rad-control);
    background: transparent;
    color: var(--text-3);
    display: grid;
    place-items: center;
    cursor: pointer;
    opacity: 0;
    transition: opacity var(--dur-fast) var(--ease);
  }
  .row:hover .row-del {
    opacity: 1;
  }
  .row-del:hover {
    background: var(--danger-soft);
    color: var(--danger);
  }

  /* ---- 应用条 ---- */
  .apply-bar {
    display: flex;
    align-items: center;
    gap: var(--sp-2);
    min-width: 0;
    padding: 10px var(--sp-4);
    border-top: 1px solid var(--separator);
    background: var(--bg-inspector);
    flex: 0 0 auto;
  }
  .btn.apply {
    height: var(--ctl-h-lg);
    padding: 0 var(--sp-4);
  }
  .delta {
    font-size: 12px;
    line-height: 18px;
    padding: 0 7px;
    border-radius: 999px;
    background: var(--fill);
    color: var(--text-2);
    font-variant-numeric: tabular-nums;
    white-space: nowrap;
  }
  .delta.less {
    background: var(--warn-soft);
    color: var(--warn);
  }
  .preview-hint {
    margin-left: auto;
    margin-right: var(--sp-2);
    font-size: 12px;
    color: var(--text-3);
    white-space: nowrap;
  }
  .config-sep {
    width: 1px;
    height: 14px;
    background: var(--separator);
    margin: 0 2px;
    flex: 0 0 1px;
  }

  /* ---- ops 面板 ---- */
  .ops-bar {
    display: flex;
    align-items: center;
    gap: var(--sp-2);
    padding: var(--sp-2) var(--sp-4);
    border-bottom: 1px solid var(--separator-soft);
    font-size: var(--fs-label);
    color: var(--text-2);
    flex-wrap: wrap;
  }
  .ops-bar b {
    color: var(--text);
    font-variant-numeric: tabular-nums;
  }
  .ops-bar .conflict,
  .ops-bar .conflict b {
    color: var(--danger);
  }
  .ops-bar .dim {
    color: var(--text-3);
  }
  .ops-bar .spacer {
    flex: 1;
  }
  .ops-list {
    flex: 1;
    min-height: 0;
    overflow: auto;
    padding: 10px var(--sp-4) var(--sp-4);
    display: flex;
    flex-direction: column;
    gap: var(--sp-2);
  }
  .ops-group {
    display: flex;
    flex-direction: column;
    gap: var(--sp-1);
  }
  .ops-group-title {
    font-size: 11px;
    color: var(--text-3);
    letter-spacing: 0.02em;
  }
  .ops-group-title b {
    color: var(--text-2);
    font-variant-numeric: tabular-nums;
  }
  .op-row {
    display: flex;
    align-items: flex-start;
    gap: 7px;
    padding: 6px var(--sp-2);
    border: 1px solid var(--separator);
    border-radius: var(--rad-card);
    background: var(--bg-content);
    cursor: pointer;
    content-visibility: auto;
    contain-intrinsic-size: auto 44px;
  }
  .op-row:hover {
    background: var(--row-hover);
  }
  .op-row.conflict {
    border-color: color-mix(in srgb, var(--danger) 45%, transparent);
    background: color-mix(in srgb, var(--danger) 6%, var(--bg-content));
    cursor: default;
  }
  .op-row input {
    margin-top: 3px;
  }
  .op-badge {
    flex: 0 0 auto;
    font-size: 11px;
    line-height: 18px;
    padding: 0 5px;
    border-radius: 3px;
    background: var(--fill);
    color: var(--text-2);
    white-space: nowrap;
  }
  .op-idx {
    flex: 0 0 auto;
    font-family: var(--font-mono);
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
    font-family: var(--font-mono);
    font-size: 11px;
    line-height: 18px;
    color: var(--text-3);
    white-space: nowrap;
  }
</style>
