<script lang="ts">
  /**
   * 断句重排页：把「切得不像人话」的字幕整份交给外部模型重排，再整段换回核对台。
   *
   * 版式：上半是紧凑顶栏 + 自适应分段轨道；下半是「左操作工作台（约 40%） +
   * 右本段预览（约 60%）」。右栏默认只读原稿（双源时 A | B），粘入新稿后
   * 原地切换为「原稿 ↔ 新稿」对照，覆盖前能先看清每一处变化。
   *
   * 契约不变：
   * - 整份重写只收标准 SRT；时间码是模型给的，服务端只体检不改数；
   * - 应用锚点是原稿条目区间，分段计划冻结，覆盖一次只动本段；
   * - 条数腰斩/翻倍才二次确认，digest 对不上整批拒绝；
   * - 「只改几处」走 ops JSON，勾选后一次原子应用。
   */
  import Icon from '../components/Icon.svelte';
  import SourceSwitch from '../components/ai/SourceSwitch.svelte';
  import TemplatePicker from '../components/ai/TemplatePicker.svelte';
  import SegmentRail from '../components/ai/SegmentRail.svelte';
  import '../components/ai/ai-workbench.css';
  import type { StructureOpView } from '../lib/api';
  import type { AiSegment } from '../lib/aiSegments';
  import { alignPreviewRows, bRefsFor, type PreviewRow } from '../lib/previewDiff';
  import {
    activeDraft,
    appliedCount,
    applyReshapeDraft,
    copyReshapePrompt,
    currentRangeFor,
    currentSegment,
    discardDraft,
    ensurePromptInfo,
    ensureReshapePlan,
    parseReshapeText,
    promptCategory,
    removeDraftCue,
    reshape,
    resetReshape,
    segmentState,
    setMode,
    setSegment,
    setSource,
    updateDraftCue,
  } from '../lib/reshape.svelte';
  import {
    applyStructureOps,
    copyStructurePrompt,
    discardStructure,
    loadStructure,
    parseStructurePaste,
    selectedStructureCount,
    setAllStructureOps,
    structure,
    toggleStructureOp,
  } from '../lib/structure.svelte';
  import {
    altEngineLabel,
    dual,
    importAltReview,
    refreshAltReview,
  } from '../lib/dualReview.svelte';
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
  let dragging = $state(false);

  const segment = $derived(currentSegment());
  const draft = $derived(activeDraft());
  const templates = $derived(promptItemsFor(promptCategory()));
  const activeTemplate = $derived(promptSelectedId(promptCategory()));
  const isOps = $derived(reshape.mode === 'ops');

  /** 当前段在当前表里的条目区间（长片按已覆盖段的条数差平移）。 */
  const range = $derived.by(() => {
    if (!segment) return { from: 1, to: 0 };
    return reshape.longMode ? currentRangeFor(segment) : { from: 1, to: app.cues.length };
  });
  const segmentCues = $derived(
    range.to >= range.from ? app.cues.slice(range.from - 1, range.to) : [],
  );
  const segmentSpan = $derived.by(() => {
    if (!segmentCues.length) return null;
    return {
      start: segmentCues[0].start,
      end: segmentCues[segmentCues.length - 1].end,
    };
  });
  const rangeLabel = $derived.by(() => {
    if (!segment) return '全片';
    if (!reshape.longMode) return `全片 ${segment.count} 条`;
    return `第 ${range.from}–${range.to} 条`;
  });
  const segmentNo = $derived(String((reshape.longMode ? reshape.segmentIndex : 0) + 1).padStart(2, '0'));

  /** 分段轨道：短片也显示一格「全片」，让左卡与右表始终有明确的当前对象。 */
  const railSegments: AiSegment[] = $derived.by(() => {
    if (isOps || !app.cues.length) return [];
    if (reshape.longMode && reshape.segments.length) {
      // 覆盖过一段之后，段轨显示的是这一段的**新条数**；后续段的计划条数不变。
      return reshape.segments.map((item) => {
        const delta = reshape.applied[`${item.from}-${item.to}`]?.delta ?? 0;
        return delta ? { ...item, count: item.count + delta } : item;
      });
    }
    const first = app.cues[0];
    const last = app.cues[app.cues.length - 1];
    return [{ from: 1, to: app.cues.length, start: first.start, end: last.end, count: app.cues.length }];
  });

  const step = $derived.by(() => {
    if (isOps) {
      if (structure.ops.length) return 3;
      return structure.text.trim() || opsPasting ? 2 : 1;
    }
    if (draft) return 3;
    return reshape.text.trim() ? 2 : 1;
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

  /** 结构建议命中哪些原稿行（1 基）：右侧表格据此高亮。 */
  const hitMap = $derived.by(() => {
    const map = new Map<number, string[]>();
    const add = (index: number | null, label: string) => {
      if (!index || index < 1) return;
      const list = map.get(index) ?? [];
      if (!list.includes(label)) list.push(label);
      map.set(index, list);
    };
    const rangeAdd = (from: number | null, to: number | null, label: string) => {
      if (!from) return;
      const start = from;
      const end = Math.max(from, to ?? from);
      for (let index = start; index <= end; index += 1) add(index, label);
    };
    const indexesFromLabel = (label: string): number[] => {
      if (!label) return [];
      if (label.startsWith('最前')) return [1];
      const match = /#(\d+)(?:\s*[–-]\s*#(\d+))?/.exec(label);
      if (!match) return [];
      const start = Number(match[1]);
      const end = match[2] ? Number(match[2]) : start;
      if (!Number.isFinite(start) || !Number.isFinite(end) || end < start) return [];
      return Array.from({ length: Math.min(end - start + 1, 500) }, (_, step) => start + step);
    };
    for (const op of structure.ops) {
      const label = opLabel(op.op);
      if (op.op === 'merge' && op.from_index) {
        rangeAdd(op.from_index, op.to_index, label);
      } else if (op.op === 'insert') {
        add(op.after_index === 0 ? 1 : op.after_index, label);
      } else {
        const indexes = op.from_index ? [op.from_index] : indexesFromLabel(op.index_label);
        for (const index of indexes) add(index, label);
      }
    }
    return map;
  });

  const previewRows = $derived(alignPreviewRows(segmentCues, draft?.cues ?? null));
  const bRefs = $derived(dual.exists ? bRefsFor(segmentCues, dual.cues) : []);
  const warnNotes = $derived(draft ? draft.notes.filter((note) => note.level === 'warn') : []);
  const countBefore = $derived(draft?.diagnostics.count_before ?? 0);
  const countAfter = $derived(draft?.cues.length ?? 0);
  const countDelta = $derived(countAfter - countBefore);
  const previewDual = $derived(reshape.source === 'dual' && dual.exists);

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

  const copyLabel = $derived.by(() => {
    if (isOps) return '复制提示词';
    if (!app.cues.length) return '复制提示词';
    if (reshape.longMode && segment) {
      const current = currentRangeFor(segment);
      return `复制第 ${current.from}–${current.to} 条提示词`;
    }
    return '复制整份提示词';
  });

  const metaText = $derived.by(() => {
    if (isOps) {
      if (structure.promptLoading) return '正在准备提示词…';
      return app.cues.length
        ? `共 ${app.cues.length} 条 · 模型只回 ops JSON`
        : '还没有字幕';
    }
    const info = reshape.prompt;
    if (!info) return reshape.loadingPrompt ? '正在准备提示词…' : '';
    const parts = [info.alt_count ? `参考 ${info.alt_count} 条` : `${info.count} 条`];
    parts.push(`≈${(info.chars / 1000).toFixed(1)}k 字`);
    return parts.join(' · ');
  });

  const applyLabel = $derived.by(() => {
    if (!draft) return '';
    if (reshape.applying) return '覆盖中…';
    if (needsArm && isArmed) return `再点一次：覆盖 ${draft.cues.length} 条`;
    if (needsArm) return `确认覆盖 · ${draft.cues.length} 条`;
    if (draft.range.full) return `覆盖核对台 · ${draft.cues.length} 条`;
    return `覆盖第 ${segmentNo} 段 · ${draft.cues.length} 条`;
  });

  // 换片 / 换源：清掉上一部片留下的草稿，否则段号和指纹都会对不上。
  $effect(() => {
    void app.media?.id;
    resetReshape();
    opsPasting = false;
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
    setMode(mode);
    opsPasting = false;
    dragging = false;
    if (mode === 'ops') void loadStructure();
  }

  function switchSource(source: 'single' | 'dual') {
    if (source === 'dual' && !dual.exists) {
      toast('还没有第二版字幕：先在转写页用另一个引擎转一次，或到双引擎复核页导入一份', 'warn');
      return;
    }
    setSource(source);
  }

  async function importB() {
    await importAltReview();
  }

  async function copyPrompt() {
    if (isOps) {
      const ok = await copyStructurePrompt(reshape.source);
      if (ok) opsPasting = true;
      return;
    }
    await copyReshapePrompt();
  }

  async function parsePaste() {
    if (isOps) {
      await parseStructurePaste();
      if (structure.ops.length) opsPasting = false;
      return;
    }
    await parseReshapeText();
  }

  async function applyDraft() {
    if (isOps) {
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

  function repaste() {
    if (isOps) {
      opsPasting = true;
      structure.text = '';
      return;
    }
    discardDraft();
  }

  function onDropFile(event: DragEvent) {
    event.preventDefault();
    event.stopPropagation();
    dragging = false;
    const file = event.dataTransfer?.files?.[0];
    if (!file) return;
    void file.text().then((text) => {
      if (!text.trim()) return;
      if (isOps) {
        structure.text = text;
        opsPasting = true;
      } else {
        reshape.text = text;
      }
      void parsePaste();
    });
  }

  function onDragOver(event: DragEvent) {
    event.preventDefault();
    event.stopPropagation();
    dragging = true;
  }

  function onDragLeave(event: DragEvent) {
    event.stopPropagation();
    dragging = false;
  }

  function pasteBoxEmpty(): boolean {
    return isOps ? !structure.text.trim() : !reshape.text.trim();
  }

  function onPaste(event: ClipboardEvent) {
    const text = event.clipboardData?.getData('text') ?? '';
    if (text.trim().length < 40) return;
    // 只在空框里自动解析：往已有内容里补粘一段时，不该直接覆盖整份稿。
    if ((isOps ? structure.text : reshape.text).trim()) return;
    setTimeout(() => {
      if (!pasteBoxEmpty()) return;
      void parsePaste();
    }, 180);
  }

  function onApplyClick() {
    if (!draft) return;
    if (needsArm && !isArmed) {
      armed = draft.digest;
      return;
    }
    void applyDraft();
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

  function clock(value: number): string {
    const total = Math.max(0, Number(value) || 0);
    const hours = Math.floor(total / 3600);
    const minutes = Math.floor((total % 3600) / 60);
    const seconds = Math.floor(total % 60);
    const body = `${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`;
    return hours ? `${hours}:${body}` : body;
  }

  function opLabel(op: string): string {
    return (
      ({
        merge: '合并',
        retime: '改时间',
        replace_text: '改文字',
        insert: '新增',
        delete: '删除',
      }) as Record<string, string>
    )[op] ?? op;
  }

  function opTime(op: StructureOpView): string {
    const fmt = (value: number | null) => (value === null ? '—' : tcShort(value));
    if (op.op === 'insert') return `${fmt(op.new_start)}–${fmt(op.new_end)}`;
    if (op.op === 'retime') return `${fmt(op.old_start)} → ${fmt(op.new_start)}`;
    if (op.op === 'merge') return `${fmt(op.old_start)}–${fmt(op.old_end)}`;
    return fmt(op.old_start);
  }

  function oldIndexLabel(row: PreviewRow): string {
    if (!row.oldIndexes.length) return '';
    const first = row.oldIndexes[0] + range.from;
    const last = row.oldIndexes[row.oldIndexes.length - 1] + range.from;
    return first === last ? `#${first}` : `#${first}–${last}`;
  }

  function newIndexLabel(row: PreviewRow): string {
    if (!row.newIndexes.length) return '';
    const first = row.newIndexes[0] + 1;
    const last = row.newIndexes[row.newIndexes.length - 1] + 1;
    return first === last ? `#${first}` : `#${first}–${last}`;
  }

  function rowMark(row: PreviewRow): string {
    return row.kind === 'same' ? '=' : row.kind === 'diff' ? '~' : row.kind === 'old' ? '−' : '+';
  }

  function issuesForRow(row: PreviewRow): string[] {
    if (!draft) return [];
    return row.newIndexes
      .map((index) => draft?.issues[index + 1] ?? '')
      .filter((label) => Boolean(label));
  }

  function jumpToFirstIssue() {
    document
      .querySelector('.preview-row.compare.flagged')
      ?.scrollIntoView({ block: 'center', behavior: 'smooth' });
  }

  function railStatus(item: AiSegment): 'done' | 'ready' | 'todo' {
    return reshape.longMode ? segmentState(item) : 'todo';
  }
</script>

<div class="reshape aiw-page">
  <header class="aiw-head">
    <div class="aiw-title-row">
      <h1 class="aiw-title">断句重排</h1>

      <div class="aiw-config">
        <span class="aiw-label">做法</span>
        <div class="seg" role="tablist" aria-label="做法">
          <button
            role="tab"
            aria-selected={reshape.mode === 'rewrite'}
            class:on={reshape.mode === 'rewrite'}
            onclick={() => switchMode('rewrite')}
            title="让模型自由重切，整份换掉这一段（条数与时间码都可变）"
          >整份重写</button>
          <button
            role="tab"
            aria-selected={reshape.mode === 'ops'}
            class:on={reshape.mode === 'ops'}
            onclick={() => switchMode('ops')}
            title="只改模型点名的那几处（合并 / 改时间 / 增删），逐项可拒"
          >只改几处</button>
        </div>

        <span class="aiw-divider" aria-hidden="true"></span>

        <span class="aiw-label">底稿</span>
        <SourceSwitch
          source={reshape.source}
          hasB={dual.exists}
          aCount={app.cues.length}
          bCount={dual.count}
          bLabel={altEngineLabel()}
          dualLabel="双源 A+B"
          onchange={switchSource}
          onimport={() => void importB()}
        />

        {#if !isOps}
          <TemplatePicker
            items={templates}
            value={activeTemplate}
            title="断句重排提示词模板"
            onchange={(id) => void selectPromptTemplate(id, promptCategory())}
          />
        {/if}
      </div>

      <div class="aiw-spacer"></div>

      <div class="aiw-head-end">
        {#if !isOps && reshape.longMode}
          <span class="aiw-chip">已覆盖 <b>{appliedCount()}</b>/<b>{reshape.segments.length}</b> 段</span>
        {:else if app.cues.length}
          <span class="aiw-chip">共 <b>{app.cues.length}</b> 条</span>
        {/if}
        <button class="btn ghost sm" onclick={() => setView('prompts')} title="打开提示词库">
          提示词库
        </button>
      </div>
    </div>

    {#if railSegments.length}
      <SegmentRail
        label={reshape.longMode ? '智能分段' : '当前分段'}
        segments={railSegments}
        active={reshape.longMode ? reshape.segmentIndex : 0}
        status={railStatus}
        onselect={(index) => {
          if (reshape.longMode) setSegment(index);
        }}
        disabled={!reshape.longMode}
      />
    {/if}
  </header>

  {#if reshape.errors.length}
    <div class="note err"><Icon name="warn" size={11} /><span>{reshape.errors[0]}</span></div>
  {/if}
  {#if isOps && structure.errors.length}
    <div class="note err"><Icon name="warn" size={11} /><span>{structure.errors[0]}</span></div>
  {/if}

  <div class="body">
    <aside class="side">
      <section class="aiw-card">
        <div class="aiw-card-head">
          {#if isOps}
            <span class="aiw-card-title">结构建议</span>
            <span class="aiw-card-sub">{app.cues.length} 条 · 勾选后应用</span>
          {:else}
            <span class="aiw-card-title">第 <b>{segmentNo}</b> 段</span>
            <span class="aiw-card-sub">{rangeLabel}</span>
          {/if}
        </div>

        <ol class="aiw-steps">
          <!-- Step 1 -->
          <li class="aiw-step" class:on={step === 1} class:done={step > 1}>
            <span class="aiw-step-no">{step > 1 ? '✓' : '1'}</span>
            <div class="aiw-step-body">
              <button
                class="btn aiw-wide"
                class:primary={step === 1}
                onclick={() => void copyPrompt()}
                disabled={!app.cues.length || (isOps ? structure.promptLoading : reshape.loadingPrompt)}
              >
                {isOps
                  ? structure.promptLoading
                    ? '正在准备…'
                    : '复制提示词'
                  : reshape.loadingPrompt
                    ? '正在准备…'
                    : copyLabel}
              </button>
              <p class="aiw-step-meta">{metaText || ' '}</p>
            </div>
          </li>

          <!-- Step 2 -->
          <li
            class="aiw-step"
            class:on={step === 2}
            class:done={isOps ? structure.ops.length > 0 : Boolean(draft)}
          >
            <span class="aiw-step-no">{isOps ? (structure.ops.length ? '✓' : '2') : draft ? '✓' : '2'}</span>
            <div class="aiw-step-body">
              {#if isOps && structure.ops.length && !opsPasting}
                <div class="parsed-line">
                  <span class="parsed-icon"><Icon name="check" size={12} /></span>
                  <span>已解析 <b>{structure.ops.length}</b> 项</span>
                  <div class="aiw-spacer"></div>
                  <button class="aiw-link" onclick={repaste}>重新粘贴</button>
                </div>
                {#if structure.summary}
                  <p class="aiw-step-meta">
                    结果 {structure.summary.input_count} → {structure.summary.output_count} 条{#if structure.summary.conflicts}
                      · <span class="warn-ink">冲突 {structure.summary.conflicts}</span>{/if}
                  </p>
                {/if}
              {:else if !isOps && draft}
                <div class="parsed-line">
                  <span class="parsed-icon"><Icon name="check" size={12} /></span>
                  <span>已预检 <b>{draft.cues.length}</b> 条</span>
                  <div class="aiw-spacer"></div>
                  <button class="aiw-link" onclick={repaste}>重新粘贴</button>
                </div>
                <p class="aiw-step-meta">右栏对照 · 双击新稿可改</p>
              {:else}
                <div
                  class="aiw-drop"
                  class:hot={dragging}
                  role="group"
                  aria-label="粘贴或拖入模型返回的文件"
                  ondragover={onDragOver}
                  ondragleave={onDragLeave}
                  ondrop={onDropFile}
                >
                  {#if !(isOps ? structure.text.trim() : reshape.text.trim())}
                    <div class="aiw-drop-hint">
                      <b>{isOps ? '粘贴模型返回的 ops JSON' : '粘贴模型返回的 SRT'}</b>
                      <span class="aiw-kbd">⌘V 自动预检</span>
                      <span>{isOps ? '或拖入 .json 文件' : '或拖入 .srt 文件'}</span>
                    </div>
                  {/if}
                  {#if isOps}
                    <textarea
                      bind:value={structure.text}
                      onpaste={onPaste}
                      spellcheck="false"
                      aria-label="粘贴 ops JSON"
                    ></textarea>
                  {:else}
                    <textarea
                      bind:value={reshape.text}
                      onpaste={onPaste}
                      spellcheck="false"
                      aria-label="粘贴重排后的 SRT"
                    ></textarea>
                  {/if}
                </div>
                <div class="aiw-step-actions">
                  <button
                    class="btn"
                    class:primary={step === 2}
                    onclick={() => void parsePaste()}
                    disabled={(isOps ? structure.parsing : reshape.parsing) ||
                      !(isOps ? structure.text.trim() : reshape.text.trim())}
                  >
                    {isOps
                      ? structure.parsing
                        ? '解析中…'
                        : '解析改动'
                      : reshape.parsing
                        ? '解析中…'
                        : '解析并预检'}
                  </button>
                  {#if isOps ? structure.text.trim() : reshape.text.trim()}
                    <button
                      class="aiw-link"
                      onclick={() => {
                        if (isOps) {
                          structure.text = '';
                          opsPasting = false;
                        } else {
                          reshape.text = '';
                        }
                      }}
                    >清空</button>
                  {/if}
                  <span class="aiw-hint">{isOps ? '只收 ops JSON' : '必须带时间码'}</span>
                </div>
              {/if}
            </div>
          </li>

          <!-- Step 3 -->
          <li
            class="aiw-step"
            class:on={step === 3}
          >
            <span class="aiw-step-no">3</span>
            <div class="aiw-step-body">
              {#if isOps}
                {#if structure.ops.length}
                  <div class="aiw-step-actions ops-tools">
                    <span class="aiw-chip">已选 <b>{selectedStructureCount()}</b></span>
                    <button class="aiw-link" onclick={() => setAllStructureOps(true)}>全选</button>
                    <button class="aiw-link" onclick={() => setAllStructureOps(false)}>全不选</button>
                    <div class="aiw-spacer"></div>
                    <button class="aiw-link danger" onclick={() => void discardStructure()}>丢弃</button>
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
                                  <span class="op-arrow">→</span>
                                  {#if op.op === 'delete'}<span class="op-dim">（删除）</span>{:else}{op.after}{/if}
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
                  <button
                    class="btn primary aiw-wide"
                    onclick={() => void applyDraft()}
                    disabled={structure.applying || selectedStructureCount() === 0}
                  >
                    {structure.applying
                      ? '应用中…'
                      : `应用所选${selectedStructureCount() ? ` · ${selectedStructureCount()}` : ''}`}
                  </button>
                  <p class="aiw-step-meta">⌘Z 一次整批撤回；应用后这份建议即被丢弃</p>
                {:else}
                  <div class="aiw-idle">粘贴后在这里勾选要应用的改动</div>
                {/if}
              {:else}
                {#if draft}
                  <div class="aiw-delta">
                    <span class="aiw-fig muted">{countBefore}</span>
                    <span class="aiw-fig-arrow">→</span>
                    <span class="aiw-fig">{countAfter}</span>
                    <span class="aiw-hint">条</span>
                    {#if warnNotes.length}
                      <button class="aiw-chip warn" onclick={jumpToFirstIssue} title="跳到第一处体检提示">
                        体检 {warnNotes.length}
                      </button>
                    {:else}
                      <span class="aiw-chip ok">体检通过</span>
                    {/if}
                    {#if countDelta !== 0}
                      <span class="aiw-chip">{countDelta > 0 ? '+' : ''}{countDelta}</span>
                    {/if}
                  </div>
                  {#if warnNotes.length}
                    <p class="aiw-step-meta warn-ink">
                      {warnNotes.slice(0, 2).map((note) => note.text).join(' · ')}{warnNotes.length > 2
                        ? ` …另有 ${warnNotes.length - 2} 条`
                        : ''}
                    </p>
                  {/if}
                  <button
                    class="btn primary aiw-wide"
                    class:armed={needsArm && isArmed}
                    onclick={onApplyClick}
                    disabled={reshape.applying || !draft.cues.length}
                  >
                    {applyLabel}
                  </button>
                  <div class="aiw-step-actions">
                    <span class="aiw-hint">⌘Z 一次整批撤回{draft.range.full ? '' : '；只替换这一段'}</span>
                    <div class="aiw-spacer"></div>
                    <button class="aiw-link" onclick={() => discardDraft()} disabled={reshape.applying}>丢弃</button>
                  </div>
                {:else}
                  <div class="aiw-idle">粘贴后在这里确认覆盖</div>
                {/if}
              {/if}
            </div>
          </li>
        </ol>
      </section>

      <section class="aiw-card brief-card">
        <div class="aiw-card-head">
          <span class="aiw-card-title">{isOps ? '结构速览' : '本段速览'}</span>
          <span class="aiw-card-sub">{isOps ? '勾选后应用' : '只读'}</span>
        </div>
        <div class="brief-grid">
          <div class="brief-item">
            <span class="brief-k">{isOps ? '原稿' : '本段'}</span>
            <span class="brief-v">{isOps ? app.cues.length : segmentCues.length} 条</span>
          </div>
          <div class="brief-item">
            <span class="brief-k">{isOps ? '命中' : '覆盖后'}</span>
            <span class="brief-v">
              {isOps
                ? `${hitMap.size} 条`
                : draft
                  ? `${draft.cues.length} 条`
                  : '—'}
            </span>
          </div>
          <div class="brief-item">
            <span class="brief-k">{isOps ? '结果' : '时长'}</span>
            <span class="brief-v mono">
              {isOps
                ? structure.summary
                  ? `${structure.summary.input_count}→${structure.summary.output_count}`
                  : '—'
                : segmentSpan
                  ? `${clock(segmentSpan.start)}–${clock(segmentSpan.end)}`
                  : '—'}
            </span>
          </div>
          <div class="brief-item">
            <span class="brief-k">{isOps ? '冲突' : '体检'}</span>
            <span class="brief-v" class:warn-ink={isOps ? (structure.summary?.conflicts ?? 0) > 0 : warnNotes.length > 0}>
              {isOps
                ? structure.summary?.conflicts ?? 0
                : draft
                  ? warnNotes.length
                    ? `${warnNotes.length} 项`
                    : '通过'
                  : '—'}
            </span>
          </div>
        </div>
      </section>

      <div class="side-foot">
        <span>{isOps ? '⌘V 粘贴 ops JSON' : '⌘V 粘贴 / 拖入 SRT'}</span>
        <span>{isOps ? '应用后建议即丢弃' : '覆盖只动本段'}</span>
      </div>
    </aside>

    <section class="preview">
      <div class="preview-head">
        <span class="preview-title">{isOps ? '原稿预览' : '本段预览'}</span>
        {#if !isOps}
          <span class="aiw-chip">{rangeLabel}</span>
        {/if}
        {#if draft}
          <span class="aiw-chip accent">新稿 <b>{draft.cues.length}</b> 条</span>
          <span class="aiw-hint">原稿 ↔ 新稿 · 双击新稿可改</span>
        {:else if isOps}
          <span class="aiw-chip">命中 <b>{hitMap.size}</b> 条</span>
          <span class="aiw-hint">受影响的句子已在表中标出</span>
        {:else if previewDual}
          <span class="aiw-chip">B · {altEngineLabel()} <b>{dual.count}</b> 条</span>
        {/if}
        <div class="aiw-spacer"></div>
        {#if draft}
          <span class="legend">= 同 · ~ 改 · − 删 · + 增</span>
        {/if}
      </div>

      {#if !app.cues.length}
        <div class="aiw-empty">
          <div class="aiw-empty-title">还没有字幕</div>
          <div class="aiw-empty-text">先在转写页跑一次，或从导入页导入一份 SRT，再回来重排断句。</div>
          <div class="empty-actions">
            <button class="btn primary sm" onclick={() => setView('transcribe')}>去转写页</button>
            <button class="btn ghost sm" onclick={() => setView('import')}>导入字幕</button>
          </div>
        </div>
      {:else if isOps}
        <div class="aiw-table">
          <div class="aiw-cols preview-cols ops">
            <span>时间码</span>
            <span>原稿（全部）</span>
            <span>结构</span>
          </div>
          <div class="aiw-list">
            {#each app.cues as cue, index (index)}
              {@const hits = hitMap.get(index + 1) ?? []}
              <div class="aiw-row preview-row ops" class:hit={hits.length > 0}>
                <div class="aiw-time">
                  <span class="aiw-tc">{tcShort(cue.start)}</span>
                  <span class="aiw-idx">#{index + 1}</span>
                </div>
                <div class="aiw-cell">{cue.text}</div>
                <div class="struct-cell">
                  {#each hits as hit (hit)}
                    <span class="struct-chip">{hit}</span>
                  {/each}
                </div>
              </div>
            {/each}
          </div>
        </div>
      {:else if draft}
        <div class="aiw-table">
          <div class="aiw-cols preview-cols compare">
            <span>时间码</span>
            <span>原稿 · 第 {range.from}–{range.to} 条</span>
            <span class="mark-head">对照</span>
            <span>新稿 · {draft.cues.length} 条</span>
          </div>
          <div class="aiw-list">
            {#each previewRows as row, rowIndex (`${row.start}-${row.oldIndexes.join('-')}:${row.newIndexes.join('-')}-${rowIndex}`)}
              {@const rowIssues = issuesForRow(row)}
              <div
                class="aiw-row preview-row compare"
                class:changed={row.kind === 'diff'}
                class:only-old={row.kind === 'old'}
                class:only-new={row.kind === 'new'}
                class:flagged={rowIssues.length > 0}
              >
                <div class="aiw-time">
                  <span class="aiw-tc">{tcShort(row.start)}</span>
                  <span class="aiw-idx">
                    {#if row.oldIndexes.length}{oldIndexLabel(row)}{:else}+{/if}
                    {#if row.newIndexes.length}<span class="idx-arrow">→</span>{newIndexLabel(row)}{/if}
                  </span>
                </div>
                <div class="aiw-cell old-cell">
                  {#each row.oldIndexes as oldIndex (oldIndex)}
                    <span class="line">{segmentCues[oldIndex]?.text ?? ''}</span>
                  {/each}
                  {#if !row.oldIndexes.length}<span class="aiw-placeholder">—</span>{/if}
                </div>
                <div class="aiw-mark">
                  <span class={row.kind === 'same' ? 'same' : row.kind === 'diff' ? 'diff' : row.kind === 'old' ? 'old' : 'new'}>
                    {rowMark(row)}
                  </span>
                </div>
                <div class="aiw-cell new-cell">
                  {#each row.newIndexes as newIndex (newIndex)}
                    {@const number = newIndex + 1}
                    {#if editing === number}
                      <textarea
                        use:focusOnMount
                        bind:value={editingText}
                        onkeydown={(event) => onEditKey(event, number)}
                        onblur={() => commitEdit(number)}
                        spellcheck="false"
                      ></textarea>
                    {:else}
                      <div class="new-line">
                        <span
                          class="line editable"
                          role="button"
                          tabindex="0"
                          aria-label={`编辑新稿第 ${number} 条`}
                          ondblclick={() => beginEdit(number, draft?.cues[newIndex]?.text ?? '')}
                          onkeydown={(event) => {
                            if (event.key === 'Enter' || event.key === ' ') {
                              event.preventDefault();
                              beginEdit(number, draft?.cues[newIndex]?.text ?? '');
                            }
                          }}
                          title="双击可改这一条"
                        >{draft?.cues[newIndex]?.text ?? ''}</span>
                        <button
                          class="line-del"
                          onclick={() => removeDraftCue(number)}
                          title="删除这一条"
                          aria-label={`删除新稿第 ${number} 条`}
                        ><Icon name="close" size={9} /></button>
                      </div>
                      {#if draft?.issues[number]}
                        <span class="cue-issue">
                          <Icon name="warn" size={9} />{draft.issues[number]}
                        </span>
                      {/if}
                    {/if}
                  {/each}
                  {#if !row.newIndexes.length}<span class="aiw-placeholder">—</span>{/if}
                </div>
              </div>
            {/each}
          </div>
        </div>
      {:else}
        <div class="aiw-table">
          {#if previewDual}
            <div class="aiw-cols preview-cols ref-dual">
              <span>时间码</span>
              <span>A · 原稿</span>
              <span>B · {altEngineLabel()}（参考）</span>
            </div>
          {:else}
            <div class="aiw-cols preview-cols ref-single">
              <span>时间码</span>
              <span>原文 · 第 {range.from}–{range.to} 条</span>
            </div>
          {/if}
          <div class="aiw-list">
            {#each segmentCues as cue, index (index)}
              {@const ref = previewDual ? (bRefs[index] ?? null) : null}
              <div class="aiw-row preview-row" class:ref-dual={previewDual} class:ref-single={!previewDual}>
                <div class="aiw-time">
                  <span class="aiw-tc">{tcShort(cue.start)}</span>
                  <span class="aiw-idx">#{range.from + index}</span>
                  {#if previewDual}
                    <span class="aiw-idx b-idx">
                      {ref ? `B#${ref.first + 1}${ref.last > ref.first ? `–B#${ref.last + 1}` : ''}` : 'B —'}
                    </span>
                  {/if}
                </div>
                <div class="aiw-cell">{cue.text}</div>
                {#if previewDual}
                  <div class="aiw-cell dim ref-cell">
                    {#if ref}
                      {#each ref.lines as line, lineIndex (lineIndex)}
                        <span class="line">{line}</span>
                      {/each}
                    {:else}
                      <span class="aiw-placeholder">—</span>
                    {/if}
                  </div>
                {/if}
              </div>
            {/each}
          </div>
        </div>
      {/if}
    </section>
  </div>
</div>

<style>
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

  .body {
    flex: 1;
    min-height: 0;
    display: grid;
    grid-template-columns: minmax(350px, 40%) minmax(0, 1fr);
    background: var(--paper);
  }
  .side {
    min-height: 0;
    display: flex;
    flex-direction: column;
    align-items: stretch;
    gap: var(--sp-2);
    padding: var(--sp-3);
    border-right: 1px solid var(--separator);
    background: var(--canvas);
    overflow-y: auto;
  }
  .side .aiw-card {
    flex: 0 0 auto;
    width: 100%;
  }
  .brief-grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 7px var(--sp-3);
    padding: 9px var(--sp-3) 10px;
  }
  .brief-item {
    display: flex;
    flex-direction: column;
    gap: 1px;
    min-width: 0;
  }
  .brief-k {
    font-size: 10.5px;
    line-height: 14px;
    color: var(--text-3);
    white-space: nowrap;
  }
  .brief-v {
    font-size: 13px;
    line-height: 18px;
    font-weight: 600;
    color: var(--text);
    font-variant-numeric: tabular-nums;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .brief-v.mono {
    font-family: var(--font-mono);
    font-size: 11.5px;
    font-weight: 500;
  }
  .brief-v.warn-ink {
    color: var(--warn);
  }
  .side-foot {
    margin-top: auto;
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--sp-2);
    padding: 2px;
    font-size: 11px;
    line-height: 15px;
    color: var(--text-3);
    white-space: nowrap;
  }

  /* ---- 左卡内的行内状态 ---- */
  .parsed-line {
    display: flex;
    align-items: center;
    gap: 6px;
    min-height: 24px;
    font-size: 12px;
    color: var(--text-2);
  }
  .parsed-line b {
    color: var(--text);
    font-variant-numeric: tabular-nums;
  }
  .parsed-icon {
    display: grid;
    place-items: center;
    color: var(--success);
  }
  .warn-ink {
    color: var(--warn);
  }
  .aiw-step-meta.warn-ink {
    color: var(--warn);
  }
  .idx-arrow {
    color: var(--text-3);
    margin: 0 2px;
  }

  /* ---- 结构建议 ops ---- */
  .ops-tools {
    flex: 0 0 auto;
  }
  .ops-list {
    flex: 0 0 auto;
    display: flex;
    flex-direction: column;
    gap: var(--sp-2);
    padding-right: 2px;
  }
  .ops-group {
    display: flex;
    flex-direction: column;
    gap: var(--sp-1);
  }
  .ops-group-title {
    font-size: 10.5px;
    line-height: 15px;
    letter-spacing: 0.02em;
    color: var(--text-3);
  }
  .ops-group-title b {
    color: var(--text-2);
    font-variant-numeric: tabular-nums;
  }
  .op-row {
    display: flex;
    align-items: flex-start;
    gap: 6px;
    padding: 5px 7px;
    border: 1px solid var(--separator);
    border-radius: var(--rad-card);
    background: var(--bg-content);
    cursor: pointer;
    content-visibility: auto;
    contain-intrinsic-size: auto 40px;
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
    flex: 0 0 auto;
  }
  .op-badge {
    flex: 0 0 auto;
    font-size: 10.5px;
    line-height: 17px;
    padding: 0 var(--sp-1);
    border-radius: 3px;
    background: var(--fill);
    color: var(--text-2);
    white-space: nowrap;
  }
  .op-idx {
    flex: 0 0 auto;
    font-family: var(--font-mono);
    font-size: 10.5px;
    line-height: 17px;
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
    font-size: 12px;
    line-height: 1.45;
    white-space: pre-wrap;
    word-break: break-word;
  }
  .op-arrow {
    color: var(--text-3);
    margin: 0 var(--sp-1);
  }
  .op-dim {
    color: var(--text-3);
  }
  .op-reason {
    font-size: 10.5px;
    line-height: 15px;
    color: var(--text-3);
  }
  .op-conflict {
    font-size: 10.5px;
    line-height: 15px;
    color: var(--danger);
  }
  .op-time {
    flex: 0 0 auto;
    font-family: var(--font-mono);
    font-size: 10.5px;
    line-height: 17px;
    color: var(--text-3);
    white-space: nowrap;
  }

  /* ---- 右栏预览 ---- */
  .preview {
    min-width: 0;
    min-height: 0;
    display: flex;
    flex-direction: column;
    background: var(--paper);
  }
  .preview-head {
    flex: 0 0 auto;
    display: flex;
    align-items: center;
    gap: var(--sp-2);
    padding: 9px 14px 7px;
    border-bottom: 1px solid var(--separator-soft);
    flex-wrap: wrap;
    min-width: 0;
  }
  .preview-title {
    font-size: 13px;
    line-height: 18px;
    font-weight: 600;
    color: var(--text);
    white-space: nowrap;
  }
  .legend {
    font-size: 11px;
    line-height: 16px;
    color: var(--text-3);
    white-space: nowrap;
  }
  .preview-cols.ref-single,
  .preview-row.ref-single {
    grid-template-columns: 96px minmax(0, 1fr);
  }
  .preview-cols.ref-dual,
  .preview-row.ref-dual {
    grid-template-columns: 96px minmax(0, 1fr) minmax(0, 1fr);
  }
  .preview-cols.compare,
  .preview-row.compare {
    grid-template-columns: 96px minmax(0, 1fr) 44px minmax(0, 1fr);
  }
  .preview-row.compare {
    border-left: 3px solid transparent;
    padding-left: 11px;
  }
  .preview-row.compare.flagged {
    border-left-color: var(--warn);
    background: color-mix(in srgb, var(--warn) 4%, transparent);
  }
  .preview-cols.ops,
  .preview-row.ops {
    grid-template-columns: 96px minmax(0, 1fr) minmax(0, 0.55fr);
  }
  .preview-row.ref-single {
    grid-template-columns: 96px minmax(0, 1fr);
  }
  .preview-row.ref-dual {
    grid-template-columns: 96px minmax(0, 1fr) minmax(0, 1fr);
  }
  .mark-head {
    text-align: center;
  }
  .ref-cell {
    border-left: 1px solid var(--separator-soft);
    padding-left: var(--sp-2);
  }
  .b-idx {
    color: color-mix(in srgb, var(--text-3) 60%, transparent);
  }
  .line {
    display: block;
    min-width: 0;
  }
  .old-cell .line + .line,
  .ref-cell .line + .line {
    margin-top: 2px;
  }
  .new-line + .new-line {
    margin-top: 2px;
  }
  .new-cell .line {
    border-radius: 3px;
  }
  .new-line {
    display: flex;
    align-items: flex-start;
    gap: var(--sp-1);
    min-width: 0;
  }
  .new-line .editable {
    flex: 1;
    min-width: 0;
    cursor: text;
    margin: 0 -3px;
    padding: 0 3px;
  }
  .new-line .editable:hover {
    background: var(--fill);
  }
  .line-del {
    flex: 0 0 18px;
    width: 18px;
    height: 18px;
    border: 0;
    border-radius: 3px;
    background: transparent;
    color: var(--text-3);
    display: grid;
    place-items: center;
    cursor: pointer;
    opacity: 0;
    transition: opacity var(--dur-fast) var(--ease);
  }
  .new-line:hover .line-del,
  .line-del:focus-visible {
    opacity: 1;
  }
  .line-del:hover {
    background: var(--danger-soft);
    color: var(--danger);
  }
  .cue-issue {
    display: inline-flex;
    align-items: center;
    gap: 3px;
    margin-top: 1px;
    font-size: 10.5px;
    line-height: 14px;
    color: var(--warn);
  }
  .new-cell textarea {
    width: 100%;
    min-height: 38px;
    resize: vertical;
    font: inherit;
    line-height: inherit;
    padding: 3px 5px;
    margin-bottom: 2px;
    border-radius: var(--rad-control);
    border: 1px solid var(--accent);
    background: var(--bg-content);
    color: var(--text);
    outline: none;
  }
  .struct-cell {
    display: flex;
    flex-wrap: wrap;
    gap: var(--sp-1);
    align-content: flex-start;
    min-height: 20px;
  }
  .struct-chip {
    display: inline-flex;
    align-items: center;
    height: 19px;
    padding: 0 5px;
    border-radius: 4px;
    background: var(--accent-soft);
    color: var(--accent);
    font-size: 11px;
    line-height: 19px;
    white-space: nowrap;
  }
  .empty-actions {
    display: flex;
    gap: var(--sp-2);
    margin-top: 2px;
  }
  .aiw-config {
    display: inline-flex;
    align-items: center;
    gap: var(--sp-2);
    flex-wrap: wrap;
    min-width: 0;
  }

  /* 二次确认时主按钮换成警示色（仍然是主题令牌） */
  .btn.armed {
    background: var(--danger-soft);
    border-color: var(--danger);
    color: var(--danger);
    font-weight: 600;
  }
  .btn.armed:hover:not(:disabled) {
    background: color-mix(in srgb, var(--danger) 16%, transparent);
    border-color: var(--danger);
    color: var(--danger);
  }

  @media (max-width: 1100px) {
    .body {
      grid-template-columns: minmax(320px, 42%) minmax(0, 1fr);
    }
  }
  @media (max-width: 900px) {
    .body {
      grid-template-columns: 1fr;
      overflow: auto;
    }
    .side {
      border-right: 0;
      border-bottom: 1px solid var(--separator);
      min-height: 420px;
    }
    .preview {
      min-height: 460px;
    }
    .aiw-title-row {
      padding: var(--sp-2) var(--sp-3) var(--sp-2);
    }
    .preview-cols.ref-single,
    .preview-row.ref-single {
      grid-template-columns: 80px minmax(0, 1fr);
    }
    .preview-cols.ref-dual,
    .preview-row.ref-dual {
      grid-template-columns: 80px minmax(0, 1fr) minmax(0, 1fr);
    }
    .preview-cols.compare,
    .preview-row.compare {
      grid-template-columns: 80px minmax(0, 1fr) 34px minmax(0, 1fr);
    }
    .preview-cols.ops,
    .preview-row.ops {
      grid-template-columns: 80px minmax(0, 1fr) minmax(0, 0.55fr);
    }
  }
</style>
