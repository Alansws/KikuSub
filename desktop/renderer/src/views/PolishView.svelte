<script lang="ts">
  /**
   * 润色页：以核对台当前稿（A）为骨架的 1:1 文本建议。
   *
   * 版式（2026-11-21 Step 5 起）：
   *   1. 统一工作条两行：第 1 行「处理什么」= 标题 + 单源/双源 + 模板 + 范围 + 状态；
   *      第 2 行「怎么跑」= 执行通道二选一（自动 API / 外部手动）+ 该通道动作 + 批次；
   *   2. 数据表：**没有提案时也先画表**（A + 虚线待生成的终稿列），拿到提案后原地激活；
   *   3. 底部应用条：只看改动 / 理由 / 全选 / 更多应用 / 应用采纳 —— 失效时主按钮禁用。
   *
   * 时间轴铁律（D-1）不变：第 3 栏与第 1 栏严格 1:1，所有采用粒度都走
   * `apply_polish()`，一次 ⌘Z 全退。
   */
  import Icon from '../components/Icon.svelte';
  import AiBatchToolbar from '../components/ai/AiBatchToolbar.svelte';
  import AiApplyBar from '../components/ai/AiApplyBar.svelte';
  import ProposalMenu from '../components/ai/ProposalMenu.svelte';
  import SourceSwitch from '../components/ai/SourceSwitch.svelte';
  import SegmentRail from '../components/ai/SegmentRail.svelte';
  import '../components/ai/ai-workbench.css';
  import { untrack } from 'svelte';
  import {
    ai,
    aiApiReady,
    aiBatchActive,
    aiBatchKey,
    aiBatchSpan,
    aiEntryLabel,
    aiSetup,
    applyAiAcceptedDiffs,
    applyAiAllDiffs,
    applyAiWholeColumn,
    cancelAiPolish,
    copyAiPrompt,
    discardAiProposal,
    importAiProposal,
    loadAiProposal,
    loadAiSetup,
    parseAiPastedSrt,
    planAiSegments,
    resetAiBatch,
    saveAiProposalAs,
    setAiBatch,
    setAiBatchSize,
    setAiChannel,
    setAiEdit,
    setAiKind,
    setAiMode,
    setAllAiAccept,
    startAiPolish,
    stepAiBatch,
    syncAiBatchScope,
    toggleAiAccept,
    segmentKey,
  } from '../lib/aiWorkspace.svelte';
  import { altEngineLabel, dual, refreshAltReview } from '../lib/dualReview.svelte';
  import { clipSpan } from '../lib/clipRange';
  import { bRefsFor } from '../lib/previewDiff';
  import { loadPrompts, promptItemsFor, prompts, selectPromptTemplate } from '../lib/promptStore.svelte';
  import { recallScroll, rememberScroll } from '../lib/scrollMemory';
  import { app, exporter, focusRange, jumpToCue, setView } from '../lib/store.svelte';
  import { tcShort } from '../lib/time';

  let editing = $state(0);
  let draft = $state('');
  let bCollapsed = $state(false);
  let applyMenuOpen = $state(false);
  /** 逐条理由默认收起：12 行重复同一句会稀释终稿本身。 */
  let showNotes = $state(false);
  /** 表格滚动容器：从核对台回来要停在同一段、同一句附近。 */
  let listEl = $state<HTMLDivElement | null>(null);

  const polishTemplates = $derived(
    promptItemsFor(ai.mode === 'dual' ? 'polish_dual' : 'polish_single'),
  );
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

  /** A 的每一条对应哪段 B（只在时间真正重叠时取，不混入邻句）。 */
  const bRefs = $derived(dual.exists ? bRefsFor(app.cues, dual.cues) : []);

  /** 处理范围 → 全片 1 基区间；全片时区间就是 1…n。 */
  const scopeSpan = $derived(clipSpan(app.cues, exporter.clip));
  const scoped = $derived(exporter.clip.end > 0);
  const restricted = $derived(scoped || aiBatchActive());
  /** 当前处理批次；默认等于整个处理范围（不碰批次控件时与旧行为一致）。 */
  const batch = $derived(aiBatchSpan());
  /**
   * 表格、复制提示词、粘贴回填、应用都只作用于批次区间。批次永远夹在处理范围
   * 之内，所以这里直接按实时 rows 切片——改前面某句的字不会让批次失效。
   */
  const scopedRows = $derived(
    batch.count > 0 ? rows.slice(batch.from - 1, batch.to) : [],
  );
  /** 磁盘上的建议可能来自另一个范围：提示一句，应用时也只写回它自己的范围。 */
  const proposalRange = $derived(ai.proposal?.source.range ?? null);
  const rangeMismatch = $derived(
    Boolean(proposalRange) &&
      restricted &&
      (proposalRange!.from !== batch.from || proposalRange!.to !== batch.to),
  );

  const visibleErrors = $derived(ai.errors.filter((e) => !/还没有提案/.test(e)));
  const changedCount = $derived(scopedRows.filter((r) => r.changed).length);
  const acceptedCount = $derived(scopedRows.filter((r) => r.changed && r.accepted).length);
  const activeSegment = $derived(
    ai.longMode && ai.segments.length
      ? ai.segments[Math.min(ai.segmentIndex, ai.segments.length - 1)]
      : null,
  );
  /**
   * 分段模式下表格只画当前段：分段的意义是「一段一段复制 / 回填」，段外的行
   * 既没有这次回填的结果，也不在粘贴范围内，混在同一张表里会让分段轨看起来
   * 没生效（用户报障）。断句重排页是同一口径。
   */
  const segmentRows = $derived(
    ai.longMode && activeSegment
      ? scopedRows.filter(
          (r) => r.i >= (activeSegment?.from ?? 0) && r.i <= (activeSegment?.to ?? 0),
        )
      : scopedRows,
  );
  const visible = $derived(
    ai.proposal && ai.changedOnly ? segmentRows.filter((r) => r.changed) : segmentRows,
  );
  /**
   * 这一段有没有可看的终稿：手工回填过，或提案本身就是整片生成的
   * （in-app / 技能 / 导入的提案按契约必须覆盖 A 的全部条目）。
   * 只有手动粘贴通道需要逐段攒，`filled` 记的就是这个进度。
   */
  function segmentFilled(segment: (typeof ai.segments)[number]): boolean {
    if (ai.filled[segmentKey(segment)]) return true;
    return Boolean(ai.proposal) && ai.proposal?.entry !== 'manual';
  }
  const filledCount = $derived(ai.segments.filter((seg) => segmentFilled(seg)).length);
  const hasAnyNotes = $derived(Boolean(ai.proposal) && rows.some((row) => row.note.trim().length > 0));
  const dualVisible = $derived(ai.mode === 'dual' && !bCollapsed);
  /** 自动 API 通道是否可用（设置 + Key 都就绪）。 */
  const apiReady = $derived(aiSetup.loaded && aiApiReady());
  const aiNeedsSetup = $derived(aiSetup.loaded && !apiReady);
  /**
   * 源文本已变化（digest 不符）：这份建议已经失效，应用一定会被 409 拒绝。
   * 主按钮必须同时禁用并给出口，不能一边红字告警一边亮着红色提交键。
   */
  const invalid = $derived(Boolean(ai.proposal) && !ai.digestMatch);

  /**
   * 表格滚动位置的 key：换片 / 换源 / 换分段都算另一张表，各自记忆。
   * 点时间码去核对台再回来时（`{#key app.view}` 会重建页面）恢复到离开处。
   */
  const listKey = $derived(
    aiBatchKey(
      `polish:${ai.mode}:${activeSegment ? segmentKey(activeSegment) : 'all'}`,
    ),
  );
  let restoredKey = '';

  $effect(() => {
    const key = listKey;
    if (!listEl || restoredKey === key) return;
    restoredKey = key;
    const target = recallScroll(key);
    const apply = () => {
      if (!listEl) return;
      listEl.scrollTop = target;
      rememberScroll(key, listEl.scrollTop);
    };
    apply();
    // 行高在首帧后才量稳（content-visibility），第二帧再对齐一次。
    requestAnimationFrame(apply);
  });

  function onListScroll() {
    if (listEl) rememberScroll(listKey, listEl.scrollTop);
  }

  /**
   * 点分段轨：换一段看。粘贴框只有一份，换段时必须清掉，否则会把上一段的
   * 回复贴到这一段（条数恰好相同时服务端也拦不住）。
   */
  function selectSegment(index: number) {
    if (index === ai.segmentIndex) return;
    ai.segmentIndex = index;
    ai.pasteText = '';
    ai.pasteOpen = false;
  }

  $effect(() => {
    void app.connected;
    void app.media?.id;
    void ai.lang;
    if (ai.kind !== 'polish') setAiKind('polish');
    if (app.connected) {
      void loadAiProposal();
      void loadPrompts();
      void refreshAltReview();
      void loadAiSetup(true);
    }
  });

  /**
   * 处理范围变了：批次回到「整段」并清空粘贴框。
   * 用 `untrack` 包住，避免把批次状态本身读成依赖造成自触发。
   */
  $effect(() => {
    void exporter.clip.start;
    void exporter.clip.end;
    void exporter.clip.label;
    if (!app.connected) return;
    untrack(() => syncAiBatchScope());
  });


  $effect(() => {
    // 第二版/条数变化后重新切段；长片分段不会因为回填而失效。
    void dual.exists;
    void dual.count;
    void app.cuesRevision;
    void ai.mode;
    void exporter.clip.start;
    void exporter.clip.end;
    if (app.connected && ai.kind === 'polish') {
      if (ai.mode === 'dual' && !dual.exists && dual.mediaId === (app.media?.id ?? '')) {
        setAiMode('single');
        return;
      }
      planAiSegments();
    }
  });

  function goto(row: { i: number; start: number; end: number }) {
    setView('review');
    jumpToCue(row.i - 1, { seek: false });
    focusRange(row.start, row.end);
  }

  function togglePaste() {
    ai.pasteOpen = !ai.pasteOpen;
  }

  async function parsePaste() {
    await parseAiPastedSrt();
    // 成功时解析函数会清空 pasteText；失败时保留内容，面板不关。
    if (!ai.pasteText.trim()) ai.pasteOpen = false;
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

  function railStatus(segment: (typeof ai.segments)[number]): 'done' | 'todo' {
    return segmentFilled(segment) ? 'done' : 'todo';
  }
</script>

<div class="polish aiw-page">
  <AiBatchToolbar
    title="锁轴润色"
    channel={ai.channel}
    channels={['api', 'manual']}
    apiNote="设置 → AI 优化里启用并填写 API Key；也可以直接用「外部手动」"
    onChannel={(next) => setAiChannel(next)}
    templates={{
      items: polishTemplates,
      value: activeTemplateId,
      title: '润色提示词模板',
      onchange: (id) =>
        void selectPromptTemplate(id, ai.mode === 'dual' ? 'polish_dual' : 'polish_single'),
    }}
    busy={ai.generating || ai.applying}
    batch={{
      from: batch.from,
      to: batch.to,
      spanFrom: scopeSpan.from,
      spanTo: scopeSpan.to,
      count: batch.count,
      total: app.cues.length,
      size: ai.batchSize,
      manual: aiBatchActive(),
      disabled: ai.generating || ai.applying,
      onApply: setAiBatch,
      onStep: stepAiBatch,
      onSize: setAiBatchSize,
      onReset: resetAiBatch,
    }}
    progress={ai.generating ? ai.progress : null}
  >
    {#snippet modeConfig()}
      <SourceSwitch
        source={ai.mode}
        hasB={dual.exists}
        aCount={app.cues.length}
        bCount={dual.count}
        bLabel={altEngineLabel()}
        onchange={(next) => setAiMode(next)}
      />
    {/snippet}

    {#snippet laneApi()}
      <button
        class="btn primary"
        onclick={startAiPolish}
        disabled={ai.generating || !app.cues.length || !apiReady}
        title={apiReady
          ? '生成一份润色建议（不修改字幕）'
          : '先在设置 → AI 优化里启用并配置 API Key'}
      >
        {ai.generating ? `生成中 ${ai.progress}%` : '生成润色建议'}
      </button>
      {#if ai.generating}
        <button class="aiw-link" onclick={cancelAiPolish}>取消</button>
        <span class="aiw-hint">{ai.stage || '准备中'}</span>
      {:else if !aiSetup.loaded}
        <span class="aiw-hint">读取配置中…</span>
      {:else if !apiReady}
        <span class="aiw-hint">未启用 / 未配置 Key</span>
        <button class="aiw-chip warn" onclick={() => setView('settings')} title="设置 → AI 优化里打开">
          去设置
        </button>
      {:else}
        <span class="aiw-mono" title={aiSetup.baseUrl}>{aiSetup.model || '未指定模型'}</span>
      {/if}
    {/snippet}

    {#snippet laneManual()}
      <button
        class="btn"
        onclick={() => void copyAiPrompt()}
        disabled={!app.cues.length}
        title={aiBatchActive()
          ? '复制本批的提示词；只包含这一批的条目'
          : ai.longMode
            ? '复制当前分段的提示词'
            : '复制提示词；可粘到任意网页版模型，再把回复粘回来'}
      >{aiBatchActive() ? '复制本批提示词' : ai.longMode ? '复制本段提示词' : '复制提示词'}</button>
      <span class="aiw-arrow" aria-hidden="true">→</span>
      <button
        class="btn"
        onclick={togglePaste}
        disabled={!app.cues.length}
        title={aiBatchActive() || ai.longMode ? '粘贴当前分段的模型回复' : '粘贴模型返回的 SRT，解析后走同一套三栏对照'}
      >{ai.pasteOpen ? '收起粘贴' : '粘贴回复'}</button>
      <button
        class="btn"
        onclick={importAiProposal}
        title="导入外部工具 / Agent 写好的建议文件"
      >导入建议文件</button>
    {/snippet}

    {#snippet note()}
      <Icon name="lock" size={11} />
      <span>只改文字：条数与时间码 1:1 不动，应用后回核对台逐句对照。</span>
      <button class="aiw-link" onclick={() => setView('reshape')}>
        断句本身错了？去重排润色 →
      </button>
    {/snippet}
    {#snippet statusExtra()}
      {#if ai.proposal}
        <span
          class="aiw-chip accent"
          title={ai.proposal.entry === 'manual'
            ? '从外部模型复制提示词、再把回复粘回来的结果'
            : ai.proposal.entry === 'cli'
              ? '外部 Agent 通过 kikusub CLI 提交的提案'
              : ai.proposal.entry === 'skill'
                ? '由随包 Agent 技能写出的提案文件'
                : '在本机「生成润色建议」里调用模型得到的结果'}
        >{aiEntryLabel()}</span>
        {#if ai.proposal.source.digest_b}<span class="aiw-chip">双源</span>{/if}
        {#if ai.proposal.model && ai.proposal.model !== 'manual-paste'}
          <span class="aiw-mono">{ai.proposal.model}</span>
        {/if}
        {#if ai.mode === 'dual'}
          <button
            class="aiw-link"
            onclick={() => (bCollapsed = !bCollapsed)}
            title="折叠 B 栏，给终稿更多宽度"
          >{bCollapsed ? '展开 B 栏' : '折叠 B 栏'}</button>
        {/if}
        <ProposalMenu
          loading={ai.loading}
          generating={ai.generating}
          saving={ai.saving}
          onReload={() => void loadAiProposal(true)}
          onSaveAs={() => void saveAiProposalAs()}
          onDiscard={() => void discardAiProposal()}
        />
      {:else if ai.loading}
        <span class="aiw-hint">正在读取建议…</span>
      {/if}
    {/snippet}

    {#snippet railExtra()}
      {#if ai.mode === 'dual' && ai.longMode && ai.segments.length}
        <SegmentRail
          compact
          label={`长片分段 · 已回填 ${filledCount}/${ai.segments.length}`}
          segments={ai.segments}
          active={ai.segmentIndex}
          status={railStatus}
          onselect={selectSegment}
          hint="点分段切换表格 · 复制 / 粘贴只作用于当前段"
        />
      {/if}
    {/snippet}
  </AiBatchToolbar>

  {#if invalid}
    <div class="note err">
      <Icon name="warn" size={11} />
      <span>
        源文本已变化：这份建议是针对另一版字幕生成的，应用会被拒绝。
        请重新生成（或重新粘贴）一份建议后再应用。
      </span>
      <button
        class="aiw-link"
        onclick={() => {
          setAiChannel('api');
          void startAiPolish();
        }}
      >重新生成</button>
    </div>
  {:else if visibleErrors.length}
    <div class="note err"><Icon name="warn" size={11} /><span>{visibleErrors[0]}</span></div>
  {:else if rangeMismatch && proposalRange}
    <div class="note warn">
      <Icon name="warn" size={11} />
      <span>
        这份建议覆盖第 {proposalRange.from}–{proposalRange.to} 条，当前处理批次是第
        {batch.from}–{batch.to} 条：应用只写回建议自己的范围，范围外不动。
      </span>
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
        {#if aiBatchActive()}
          回填<b>本批第 {batch.from}–{batch.to} 条</b>
          <span class="aiw-hint">复制出去几条就要粘回几条（润色不允许多少条）</span>
        {:else if ai.longMode && activeSegment}
          回填<b>第 {activeSegment.from}–{activeSegment.to} 条</b>
          <span class="aiw-hint">序号可用全局或本段 1 起</span>
        {:else}
          粘贴模型返回的 SRT
          <span class="aiw-hint">只取文本 · 条数必须一致</span>
        {/if}
        {#if ai.proposal}
          <span
            class="aiw-chip warn"
            title="解析成功后，当前建议的手改与采纳状态会被新结果替换"
          >将替换当前建议</span>
        {/if}
      </div>
      <textarea
        class="paste-box"
        bind:value={ai.pasteText}
        spellcheck="false"
        aria-label="粘贴模型返回的 SRT"
        placeholder={'1\n00:00:00,500 --> 00:00:01,500\nおはよう\n\n2\n…'}
      ></textarea>
      <div class="paste-actions">
        <button
          class="btn primary"
          onclick={() => void parsePaste()}
          disabled={ai.parsing || !ai.pasteText.trim()}
        >{ai.parsing
          ? '解析中…'
          : aiBatchActive()
            ? '解析并回填本批'
            : ai.longMode
              ? '解析并回填本段'
              : '解析成建议'}</button>
        <button class="btn" onclick={() => (ai.pasteOpen = false)}>取消</button>
        <div class="aiw-spacer"></div>
        <span class="aiw-hint">条数不符整段拒绝</span>
      </div>
    </div>
  {/if}


  {#if !app.cues.length}
    <div class="aiw-empty">
      <div class="aiw-empty-title">还没有字幕</div>
      <div class="aiw-empty-text">先在转写页跑一次，或从导入页导入一份 SRT。</div>
      <div class="empty-actions">
        <button class="btn primary sm" onclick={() => setView('transcribe')}>去转写页</button>
        <button class="btn ghost sm" onclick={() => setView('import')}>导入字幕</button>
      </div>
    </div>
  {:else}
    <div class="aiw-table">
      <div class="aiw-cols" class:dual={dualVisible}>
        <span>时间码</span>
        <span>A · 核对台（只读）</span>
        {#if dualVisible}
          <span class="ref-head">B · {altEngineLabel()}（参考）</span>
        {/if}
        <span class="final-head">
          AI 终稿
          {#if ai.proposal}
            <span class="aiw-hint">双击可改</span>
          {:else}
            <span class="aiw-chip pending-chip">待生成</span>
          {/if}
        </span>
        <span></span>
      </div>

      <div class="aiw-list" bind:this={listEl} onscroll={onListScroll}>
        {#if !visible.length}
          <div class="aiw-inline-empty">
            <Icon name="check" size={16} />
            <span>{ai.changedOnly ? '这一栏没有改动' : '当前没有字幕'}</span>
            {#if ai.changedOnly}
              <button class="aiw-link" onclick={() => (ai.changedOnly = false)}>看全量</button>
            {/if}
          </div>
        {:else}
          {#each visible as row (row.i)}
            {@const ref = bRefs[row.i - 1]}
            <div
              class="aiw-row"
              class:dual={dualVisible}
              class:changed={Boolean(ai.proposal) && row.changed}
              class:off={Boolean(ai.proposal) && !row.accepted}
            >
              <div class="aiw-time">
                <button class="aiw-tc" onclick={() => goto(row)} title="回到核对台定位这一句">
                  {tcShort(row.start)}
                </button>
                <span class="aiw-idx">#{row.i}</span>
              </div>

              <div class="aiw-cell">{row.before}</div>

              {#if dualVisible}
                <div
                  class="aiw-cell dim ref-cell"
                  title={ref
                    ? `B#${ref.first + 1}${ref.last > ref.first ? `–B#${ref.last + 1}` : ''}`
                    : '这一段没有时间重叠的 B 条目'}
                >
                  {ref?.text ?? ''}
                </div>
              {/if}

              {#if ai.proposal}
                <div
                  class="aiw-cell final-cell"
                  class:changed={row.changed}
                  role="button"
                  tabindex="0"
                  aria-label={`编辑第 ${row.i} 条终稿`}
                  ondblclick={() => startEdit(row.i, row.after)}
                  onkeydown={(event) => {
                    if (event.key === 'Enter' || event.key === ' ') {
                      event.preventDefault();
                      startEdit(row.i, row.after);
                    }
                  }}
                  title="双击可改这一条的终稿"
                >
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
                    {#if showNotes && row.note}
                      <span class="note-inline" title={row.note}>{row.note}</span>
                    {/if}
                  {/if}
                </div>
              {:else}
                <div class="aiw-cell pending-cell" aria-label="等待生成">
                  <span class="aiw-placeholder">—</span>
                </div>
              {/if}

              <div class="pin-cell">
                {#if ai.proposal}
                  <button
                    class="aiw-pin"
                    class:on={row.accepted}
                    onclick={() => toggleAiAccept(row.i)}
                    title={row.accepted ? '已采纳（点击排除）' : '已排除（点击采纳）'}
                    aria-label={row.accepted ? `排除第 ${row.i} 条` : `采纳第 ${row.i} 条`}
                  >
                    <Icon name="check" size={11} />
                  </button>
                {:else}
                  <span class="pin-slot" aria-hidden="true"></span>
                {/if}
              </div>
            </div>
          {/each}
        {/if}
      </div>
    </div>

    {#if ai.proposal}
      <AiApplyBar
        applyLabel={`应用采纳${acceptedCount ? ` · ${acceptedCount}` : ''}`}
        accepted={acceptedCount}
        changed={changedCount}
        busy={ai.applying}
        invalid={invalid}
        changedOnly={ai.changedOnly}
        onChangedOnly={(value) => (ai.changedOnly = value)}
        onAll={setAllAiAccept}
        onApply={applyAiAcceptedDiffs}
      >
        {#snippet extra()}
          {#if hasAnyNotes}
            <label class="aiw-check" title="在终稿下方显示逐条理由">
              <input type="checkbox" bind:checked={showNotes} />
              理由
            </label>
          {/if}
          <div class="aiw-menu-wrap">
            <button
              class="btn ghost"
              onclick={() => (applyMenuOpen = !applyMenuOpen)}
              aria-expanded={applyMenuOpen}
              disabled={invalid}
              title={invalid
                ? '源文本已变化：重新生成后才能应用'
                : '更多应用方式（会忽略右侧的采纳/排除）'}
            >
              更多应用
              <Icon name="chevron-down" size={11} />
            </button>
            {#if applyMenuOpen}
              <button class="aiw-menu-backdrop" aria-label="关闭菜单" onclick={() => (applyMenuOpen = false)}></button>
              <div class="aiw-menu up" role="menu">
                <button
                  role="menuitem"
                  onclick={() => {
                    applyMenuOpen = false;
                    if (window.confirm('应用全部差异？\n\n会忽略右侧逐条的采纳/排除，把所有与 A 不同的条目写回核对台。\n⌘Z 可整批退回。')) {
                      void applyAiAllDiffs();
                    }
                  }}
                >全部差异 · 忽略采纳</button>
                <button
                  role="menuitem"
                  onclick={() => {
                    applyMenuOpen = false;
                    if (window.confirm('整列应用 AI 终稿？\n\n会无视右侧的采纳/排除，把整栏写回核对台。\n⌘Z 可整批退回。')) {
                      void applyAiWholeColumn();
                    }
                  }}
                >整列应用 · 无视采纳</button>
              </div>
            {/if}
          </div>
        {/snippet}
      </AiApplyBar>
    {/if}
  {/if}
</div>

<style>
  .note {
    display: flex;
    align-items: flex-start;
    gap: 6px;
    padding: 6px var(--sp-6);
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

  /* 外部手动粘贴区：纸白台面上的一块独立输入段，
     上沿靠说明 / 告警条的发丝线、下沿靠 --separator 收口，不再铺灰底。 */
  .paste {
    display: flex;
    flex-direction: column;
    gap: var(--sp-2);
    padding: var(--sp-3) var(--sp-6) 14px;
    border-bottom: 1px solid var(--separator);
    background: transparent;
    flex: 0 0 auto;
  }
  .paste-head {
    display: flex;
    align-items: baseline;
    gap: var(--sp-2);
    flex-wrap: wrap;
    font-size: 12px;
    color: var(--text-2);
  }
  .paste-head b {
    color: var(--text);
  }
  /* 粘贴框是「输入框」：台本纸底 + 1px 清晰边线，留白比消息流更宽。 */
  .paste-box {
    width: 100%;
    min-height: 132px;
    max-height: 34vh;
    resize: vertical;
    font-family: var(--font-mono);
    font-size: 12px;
    line-height: 1.6;
    padding: 10px var(--sp-3);
    border-radius: var(--rad-card);
    border: 1px solid var(--well-line);
    background: var(--well-focus);
    color: var(--text);
    outline: none;
    transition: border-color var(--dur-fast) var(--ease), box-shadow var(--dur-fast) var(--ease);
  }
  .paste-box:focus {
    border-color: var(--accent);
    box-shadow: 0 0 0 3px var(--accent-soft);
  }
  .paste-actions {
    display: flex;
    align-items: center;
    gap: var(--sp-2);
    flex-wrap: wrap;
    min-height: 28px;
  }
  .paste-actions .aiw-hint {
    color: var(--text-3);
  }

  .aiw-cols,
  .aiw-row {
    grid-template-columns: 92px minmax(0, 1fr) minmax(0, 1.15fr) 26px;
  }
  .aiw-cols.dual,
  .aiw-row.dual {
    grid-template-columns: 92px minmax(0, 0.9fr) minmax(0, 0.9fr) minmax(0, 1.15fr) 26px;
  }
  .aiw-cols {
    align-items: center;
  }
  .final-head {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    min-width: 0;
  }
  .pending-chip {
    height: 18px;
    line-height: 18px;
    padding: 0 6px;
    font-size: 10.5px;
    color: var(--text-3);
    background: var(--fill);
  }
  .ref-head {
    color: var(--text-3);
  }
  .ref-cell {
    border-left: 1px solid var(--separator-soft);
    padding-left: var(--sp-2);
  }
  .aiw-row.off {
    opacity: 0.42;
  }
  /* 终稿是这一页的「台本纸」：常态与台面同色，有改动才浮出一层
     极淡蓝并加 1px accent-line 勾边；不再是整格一块饱和蓝。 */
  .final-cell {
    border-radius: 5px;
    padding: 2px 6px;
    margin: -2px -6px;
    cursor: text;
    min-height: 20px;
    border: 1px solid transparent;
    transition: background var(--dur-fast) var(--ease), border-color var(--dur-fast) var(--ease);
  }
  .aiw-row.changed .final-cell {
    background: var(--accent-soft);
    border-color: var(--accent-line);
  }
  .final-cell textarea {
    width: 100%;
    min-height: 44px;
    resize: vertical;
    font: inherit;
    line-height: inherit;
    padding: 3px 5px;
    border-radius: 4px;
    border: 1px solid var(--accent);
    background: var(--well-focus);
    color: var(--text);
    outline: none;
  }
  .tag {
    margin-left: 6px;
    font-size: 11px;
    line-height: 16px;
    padding: 0 5px;
    border-radius: 4px;
    background: var(--fill-strong);
    color: var(--text-2);
    white-space: nowrap;
  }
  /* 待生成不是「一个虚线空框」，而是一句很轻的占位：
     没有边框，只有一个比正文更淡的短横。 */
  .pending-cell {
    min-height: 20px;
    display: flex;
    align-items: center;
    padding: 0 6px;
    margin: -1px 0;
  }
  .pending-cell .aiw-placeholder {
    color: color-mix(in srgb, var(--text-3) 46%, transparent);
    letter-spacing: 0.08em;
  }
  .note-inline {
    display: block;
    margin-top: 1px;
    font-size: 11px;
    line-height: 15px;
    color: var(--text-3);
    white-space: pre-wrap;
    word-break: break-word;
  }
  .pin-cell {
    display: grid;
    place-items: center;
    min-height: 20px;
  }
  .pin-slot {
    width: 20px;
    height: 20px;
  }
  .empty-actions {
    display: flex;
    gap: var(--sp-2);
    margin-top: 2px;
  }

  @media (max-width: 900px) {
    .aiw-cols,
    .aiw-row {
      grid-template-columns: 76px minmax(0, 1fr) minmax(0, 1.15fr) 22px;
      gap: 6px;
      padding: 6px 10px;
    }
    .aiw-cols.dual,
    .aiw-row.dual {
      grid-template-columns: 76px minmax(0, 0.9fr) minmax(0, 0.9fr) minmax(0, 1.15fr) 22px;
    }
  }
</style>
