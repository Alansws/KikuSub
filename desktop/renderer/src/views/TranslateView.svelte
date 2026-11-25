<script lang="ts">
  /**
   * 翻译页（原「AI 优化」的翻译半边）。
   *
   * 版式（2026-11-21 Step 5 起与润色 / 断句重排共用顶部工作条）：
   *   第 1 行「处理什么」= 标题 + 目标语种 + 模板 + 处理范围 + 状态；
   *   第 2 行「怎么跑」= 执行通道二选一（自动 API / 外部手动）+ 该通道动作 + 批次。
   * 模板只有一个入口（下拉框）：以前「模板：AV专用版_V2」的静态文字和下拉框
   * 并排出现，看起来像两个同名下拉框。
   *
   * 翻译永远只吃「定稿后的原文一列」，不参与双引擎比较（D-3/D-4）。应用后
   * 写进译文平行轨，核对台可切到双语；原文与时间轴一个字节都不改。
   */
  import Icon from '../components/Icon.svelte';
  import GapFillCard from '../components/GapFillCard.svelte';
  import AiBatchToolbar from '../components/ai/AiBatchToolbar.svelte';
  import AiApplyBar from '../components/ai/AiApplyBar.svelte';
  import ProposalMenu from '../components/ai/ProposalMenu.svelte';
  import '../components/ai/ai-workbench.css';
  import { untrack } from 'svelte';
  import {
    ai,
    aiApiReady,
    aiBatchActive,
    aiBatchSpan,
    aiEntryLabel,
    aiSetup,
    applyAiProposal,
    cancelAiPolish,
    copyAiPrompt,
    discardAiProposal,
    importAiProposal,
    loadAiProposal,
    loadAiSetup,
    parseAiPastedSrt,
    resetAiBatch,
    saveAiProposalAs,
    setAiBatch,
    setAiBatchSize,
    setAiChannel,
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
  } from '../lib/promptStore.svelte';
  import { clipSpan } from '../lib/clipRange';
  import { app, exporter, focusRange, jumpToCue, setView } from '../lib/store.svelte';
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

  const apiReady = $derived(aiSetup.loaded && aiApiReady());
  /**
   * 源文本已变化（digest 不符）：应用一定会被 409 拒绝。底部主按钮必须禁用，
   * 不能一边亮着红字告警一边留着可点的红色提交键。
   */
  const invalid = $derived(Boolean(ai.proposal) && !ai.digestMatch);
  /** 空态引导跟着执行通道走：自动 API 不通时给外部手动一条明路。 */
  const channel = $derived(ai.channel);

  $effect(() => {
    void app.connected;
    void app.media?.id;
    void ai.lang;
    if (ai.kind !== 'translate') setAiKind('translate');
    if (app.connected) {
      void loadAiProposal();
      void loadPrompts();
      void loadAiSetup(true);
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

  function togglePaste() {
    ai.pasteOpen = !ai.pasteOpen;
  }

  async function parsePaste() {
    await parseAiPastedSrt();
    if (!ai.pasteText.trim()) ai.pasteOpen = false;
  }
</script>

<div class="ai aiw-page">
  <GapFillCard />
  <AiBatchToolbar
    title="双语翻译"
    channel={ai.channel}
    channels={['api', 'manual']}
    apiNote="设置 → AI 优化里启用并填写 API Key；也可以直接用「外部手动」"
    onChannel={(next) => setAiChannel(next)}
    templates={{
      items: translateTemplates,
      value: prompts.selected,
      title: '翻译提示词模板（在提示词库的「翻译」页签里编辑）',
      onchange: (id) => void selectPromptTemplate(id, 'translate'),
    }}
    busy={ai.generating || ai.applying}
    actionsVisible={Boolean(ai.proposal)}
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
      <label class="lang-pick" title="目标语种">
        <span class="aiw-label">译为</span>
        <select
          class="aiw-select"
          value={ai.lang}
          onchange={(e) => setAiLang(e.currentTarget.value)}
        >
          <option value="zh-Hans">简体中文</option>
          <option value="zh-Hant">繁體中文</option>
          <option value="en">English</option>
        </select>
      </label>
    {/snippet}

    {#snippet laneApi()}
      <button
        class="btn primary"
        onclick={startAiTranslate}
        disabled={ai.generating || !app.cues.length || !apiReady}
        title={apiReady
          ? '把原文字幕翻译成所选语种（只生成建议，不改原文）'
          : '先在设置 → AI 优化里启用并配置 API Key'}
      >
        {ai.generating ? `生成中 ${ai.progress}%` : '生成译文建议'}
      </button>
      {#if ai.generating}
        <button class="aiw-link" onclick={cancelAiPolish}>取消</button>
        <span class="aiw-hint">{ai.stage || '准备中'}</span>
      {:else if !aiSetup.loaded}
        <span class="aiw-hint">读取配置…</span>
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
          : '复制提示词；可粘到任意网页版模型，再把回复粘回来'}
      >{aiBatchActive() ? '复制本批提示词' : '复制提示词'}</button>
      <span class="aiw-arrow" aria-hidden="true">→</span>
      <button
        class="btn ghost"
        onclick={togglePaste}
        disabled={!app.cues.length}
        title="粘贴模型返回的 SRT，按时间轴对齐原句"
      >{ai.pasteOpen ? '收起粘贴' : '粘贴结果…'}</button>
      <button class="btn ghost" onclick={importAiProposal} title="导入一份外部生成的提案文件">
        导入建议…
      </button>
    {/snippet}

    {#snippet statusExtra()}
      {#if ai.proposal}
        <span
          class="aiw-chip accent"
          title={ai.proposal.entry === 'manual'
            ? '从外部模型复制提示词、再把回复粘回来的结果'
            : ai.proposal.entry === 'skill'
              ? '由随包 Agent 技能写出的提案文件'
              : '在本机「生成译文建议」里调用模型得到的结果'}
        >{aiEntryLabel()}</span>
        {#if ai.proposal.model && ai.proposal.model !== 'manual-paste'}
          <span class="aiw-mono">{ai.proposal.model}</span>
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
  </AiBatchToolbar>

  {#if invalid}
    <div class="note err">
      <Icon name="warn" size={11} />
      <span>
        源文本已变化：这份译文是针对另一版字幕生成的，应用会被拒绝。
        请重新生成（或重新粘贴）一份建议后再应用。
      </span>
      <button
        class="aiw-link"
        onclick={() => {
          setAiChannel('api');
          void startAiTranslate();
        }}
      >重新生成</button>
    </div>
  {:else if ai.proposal && visibleErrors.length}
    <div class="note err">
      <Icon name="warn" size={11} />
      <span>{visibleErrors[0]}</span>
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
        aria-label="粘贴模型返回的译文 SRT"
        placeholder={'1\n00:00:00,500 --> 00:00:01,500\n早上好\n\n2\n…'}
      ></textarea>
      <div class="paste-actions">
        <button class="btn primary" onclick={parsePaste} disabled={ai.parsing || !ai.pasteText.trim()}>
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

  {#if ai.loading}
    <div class="aiw-blank">
      <div class="aiw-blank-card">
        <div class="aiw-blank-head">
          <span class="aiw-blank-icon"><Icon name="doc" size={18} /></span>
          <div class="aiw-blank-title">正在读取建议…</div>
        </div>
      </div>
    </div>
  {:else if !app.cues.length}
    <div class="aiw-blank">
      <div class="aiw-blank-card">
        <div class="aiw-blank-head">
          <span class="aiw-blank-icon"><Icon name="doc" size={18} /></span>
          <div class="aiw-blank-title">还没有字幕</div>
        </div>
        <p class="aiw-blank-sub">先转写或导入一份日文字幕，翻译只读取核对台里的原文一列。</p>
        <div class="aiw-blank-actions">
          <button class="btn primary" onclick={() => setView('transcribe')}>去转写页</button>
          <button class="btn ghost" onclick={() => setView('import')}>导入字幕</button>
        </div>
      </div>
    </div>
  {:else if !ai.proposal}
    <div class="aiw-blank">
      <div class="aiw-blank-card">
        <div class="aiw-blank-head">
          <span class="aiw-blank-icon">
            <Icon name={channel === 'api' ? 'sparkle' : 'paste'} size={18} />
          </span>
          <div class="aiw-blank-title">还没有译文建议</div>
        </div>
        {#if channel === 'api'}
          <p class="aiw-blank-sub">
            用设置里配置的模型把原文翻译成「{ai.lang === 'en' ? 'English' : ai.lang === 'zh-Hant' ? '繁體中文' : '简体中文'}」，
            生成后只写进译文轨，原文与时间轴一个字节都不动。
          </p>
          <ol class="aiw-blank-steps">
            {#if apiReady}
              <li><i>1</i><span>点下面的 <b>生成译文建议</b>，等本机模型跑完。</span></li>
            {:else}
              <li><i>1</i><span>先按下方提示启用 AI 并填好 API Key，或切到 <b>外部手动</b>。</span></li>
            {/if}
            <li><i>2</i><span>逐条检查右侧表格，再点底部 <b>应用译文</b> 写入译文轨。</span></li>
          </ol>
          {#if !apiReady && aiSetup.loaded}
            <div class="aiw-blank-note">
              <Icon name="warn" size={11} />
              <span>
                本机 API 还没启用或没填 Key。去
                <button class="aiw-link" onclick={() => setView('settings')}>设置 → AI 优化</button>
                配好后回到本页重试；也可以直接切到上方的「外部手动」。
              </span>
            </div>
          {/if}
          <div class="aiw-blank-actions">
            <button
              class="btn primary"
              onclick={startAiTranslate}
              disabled={ai.generating || !apiReady}
            >{ai.generating ? `生成中 ${ai.progress}%` : '生成译文建议'}</button>
            <button class="aiw-link" onclick={importAiProposal}>导入建议文件…</button>
            {#if visibleErrors.length}
              <span class="aiw-blank-note"><Icon name="warn" size={11} />{visibleErrors[0]}</span>
            {/if}
          </div>
        {:else}
          <p class="aiw-blank-sub">
            自动 API 是可选的。把提示词复制到任意网页版 / 聊天模型（ChatGPT、Claude…），
            再把回复整段粘回来，一样能写进译文轨。
          </p>
          <ol class="aiw-blank-steps">
            <li><i>1</i><span>点 <b>复制提示词</b>，粘到外部模型，让它按模板返回 SRT。</span></li>
            <li><i>2</i><span>把回复粘进 <b>粘贴结果</b>，条数不同也能按时间轴自动对齐。</span></li>
          </ol>
          <div class="aiw-blank-actions">
            <button class="btn primary" onclick={() => void copyAiPrompt()} disabled={!app.cues.length}>
              复制提示词
            </button>
            <button class="btn ghost" onclick={togglePaste}>粘贴结果…</button>
            <button class="aiw-link" onclick={importAiProposal}>导入建议文件…</button>
            {#if visibleErrors.length}
              <span class="aiw-blank-note"><Icon name="warn" size={11} />{visibleErrors[0]}</span>
            {/if}
          </div>
        {/if}
      </div>
    </div>
  {:else if !visible.length}
    <div class="aiw-blank">
      <div class="aiw-blank-card">
        <div class="aiw-blank-head">
          <span class="aiw-blank-icon"><Icon name="check" size={18} /></span>
          <div class="aiw-blank-title">这一栏没有内容</div>
        </div>
        <p class="aiw-blank-sub">
          {ai.changedOnly ? '这一栏没有改动；取消「只看改动」可以看全量。' : '当前没有字幕。'}
        </p>
      </div>
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

    <AiApplyBar
      applyLabel="应用译文"
      accepted={acceptedCount}
      requireAccepted={false}
      busy={ai.applying}
      invalid={invalid}
      changedOnly={ai.changedOnly}
      onChangedOnly={(value) => (ai.changedOnly = value)}
      onAll={setAllAiAccept}
      onApply={applyAiProposal}
    />
  {/if}
</div>

<style>
  .ai {
    flex: 1;
    min-height: 0;
    display: flex;
    flex-direction: column;
  }
  .lang-pick {
    display: inline-flex;
    align-items: center;
    gap: 6px;
  }
  .note {
    display: flex;
    align-items: flex-start;
    gap: 6px;
    padding: 6px 14px;
    font-size: 12px;
    line-height: 1.5;
    border-bottom: 1px solid var(--separator-soft);
    flex: 0 0 auto;
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
    flex: 0 0 auto;
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
    font-family: var(--font-mono);
    font-size: 12px;
    line-height: 1.5;
    padding: var(--sp-2) 10px;
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
    flex-wrap: wrap;
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
    font-family: var(--font-mono);
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
    color: var(--on-accent);
  }
  .align-tag.drift {
    background: var(--warn);
    color: var(--on-accent);
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
</style>
