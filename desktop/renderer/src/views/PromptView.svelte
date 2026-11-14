<script lang="ts">
  /**
   * 提示词库。
   *
   * 一个模板一张卡片：单击选中、双击就地编辑。复制时服务端把当前字幕的 SRT
   * 填进 {{SRT}}（没有占位符就自动追加），结果和旧版「复制提示词」完全同一条链路。
   */
  import { tick } from 'svelte';
  import Icon from '../components/Icon.svelte';
  import PageHeader from '../components/PageHeader.svelte';
  import { copyPromptTemplateForCategory } from '../lib/aiWorkspace.svelte';
  import {
    createPromptTemplate,
    deletePromptTemplate,
    loadPrompts,
    prompts,
    promptItemsFor,
    promptSelectedId,
    resetPromptTemplate,
    savePromptTemplate,
    selectPromptTemplate,
    type PromptCategory,
  } from '../lib/promptStore.svelte';
  import { app, setView, toast } from '../lib/store.svelte';

  const CATEGORIES: { id: PromptCategory; label: string; hint: string }[] = [
    { id: 'polish_single', label: '单源润色', hint: '使用 {{SRT}}，只修正识别错误，不改写风格。' },
    { id: 'polish_dual', label: '双源润色', hint: '使用 {{SRT_A}} / {{SRT_B}}；以 A 为骨架，参考 B 修正错听与漏字。' },
    { id: 'translate', label: '翻译', hint: '使用 {{SRT}} / {{LANG}}；只在原文定稿后使用。' },
  ];

  let category = $state<PromptCategory>('translate');
  const activeCategory = $derived(CATEGORIES.find((item) => item.id === category) ?? CATEGORIES[2]);
  const items = $derived(promptItemsFor(category));
  const selectedId = $derived(promptSelectedId(category));

  let editingId = $state('');
  let draftName = $state('');
  let draftDescription = $state('');
  let draftContent = $state('');
  let saving = $state(false);
  let editorEl = $state<HTMLTextAreaElement | null>(null);
  let wasConnected = false;
  /** 哪些卡片的模板正文已经「展开全文」 */
  let expanded = $state<Record<string, boolean>>({});

  function toggleExpand(id: string) {
    expanded = { ...expanded, [id]: !expanded[id] };
  }

  const isNew = $derived(editingId === '__new__');
  const editingItem = $derived(
    isNew ? null : (prompts.items.find((item) => item.id === editingId) ?? null),
  );
  const canCopy = $derived(app.cues.length > 0);
  const canCopyDual = $derived(canCopy);

  $effect(() => {
    if (!app.connected) {
      wasConnected = false;
      return;
    }
    if (wasConnected) return;
    wasConnected = true;
    void loadPrompts(true);
  });

  async function beginEdit(id: string) {
    if (id === '__new__') {
      editingId = id;
      draftName = '新模板';
      draftDescription = '';
      draftContent =
        category === 'polish_dual'
          ? '你是日语影视字幕校对员。请以 A 为主稿、参考 B 修正识别错误；\n严格沿用 A 的序号与时间轴，只输出修订后的 SRT。\n{{RANGE_HINT}}\n\n【A】\n{{SRT_A}}\n\n【B】\n{{SRT_B}}'
          : category === 'polish_single'
            ? '你是日语影视字幕校对员。只修正明显的识别错误，不改写风格。\n严格保留原序号与时间戳，只输出修正后的 SRT。\n{{RANGE_HINT}}\n{{SRT}}'
            : '请将以下 SRT 日语字幕翻译为{{LANG}}：\n\n内容如下：\n{{SRT}}';
    } else {
      const item = prompts.items.find((entry) => entry.id === id);
      if (!item) return;
      editingId = id;
      draftName = item.name;
      draftDescription = item.description;
      draftContent = item.content;
    }
    await tick();
    editorEl?.focus();
    editorEl?.setSelectionRange(editorEl.value.length, editorEl.value.length);
  }

  function cancelEdit() {
    editingId = '';
    saving = false;
  }

  async function saveEdit() {
    if (saving) return;
    if (!draftContent.trim()) {
      toast('模板内容不能为空', 'warn');
      return;
    }
    saving = true;
    try {
      if (isNew) {
        const created = await createPromptTemplate(
          draftName.trim() || '新模板',
          draftContent,
          draftDescription,
          category,
        );
        if (created) {
          editingId = '';
          await selectPromptTemplate(created, category);
        }
      } else if (editingItem) {
        const ok = await savePromptTemplate(editingId, {
          name: draftName.trim() || editingItem.name,
          description: draftDescription,
          content: draftContent,
        });
        if (ok) editingId = '';
      }
    } finally {
      saving = false;
    }
  }

  async function remove(itemId: string) {
    const item = prompts.items.find((entry) => entry.id === itemId);
    if (!item || item.builtin) return;
    if (!window.confirm(`删除模板「${item.name}」？\n\n删除后不能恢复。`)) return;
    if (await deletePromptTemplate(itemId)) {
      if (editingId === itemId) editingId = '';
    }
  }

  async function reset(itemId: string) {
    const item = prompts.items.find((entry) => entry.id === itemId);
    if (!item?.builtin) return;
    if (!window.confirm(`把「${item.name}」恢复为内置文案？\n\n你改过的内容会被覆盖。`)) return;
    if (await resetPromptTemplate(itemId)) {
      if (editingId === itemId) editingId = '';
    }
  }

  async function copy(itemId: string) {
    if (!canCopy) {
      toast('当前还没有字幕；导入并转写后再复制', 'warn');
      return;
    }
    if (category === 'polish_dual' && !canCopyDual) {
      toast('双源模板需要第二版字幕', 'warn');
      return;
    }
    await copyPromptTemplateForCategory(itemId, category);
  }

  function switchCategory(next: PromptCategory) {
    if (next === category) return;
    if (editingId) cancelEdit();
    category = next;
  }

  function onKey(e: KeyboardEvent) {
    if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') {
      e.preventDefault();
      void saveEdit();
    } else if (e.key === 'Escape') {
      e.preventDefault();
      cancelEdit();
    }
  }

  /** 折叠时只显示开头几行，由 CSS 渐隐；展开后显示全文（超长时卡片内部滚动）。 */
  function preview(text: string) {
    const lines = text.split('\n');
    return lines.slice(0, 40).join('\n');
  }
</script>

<div class="prompts">
  <PageHeader
    title="提示词库"
    subtitle={'单击选中、双击编辑；复制时自动填入当前字幕与目标语种。'}
  >
    <span class="cue-meta">{app.cues.length} 条字幕</span>
    <button class="btn ghost" onclick={() => setView('polish')} title="回到润色页">
      <Icon name="doc" size={11} />润色页
    </button>
    <button class="btn ghost" onclick={() => setView('translate')} title="回到翻译页">
      <Icon name="quote" size={11} />翻译页
    </button>
    <button class="btn primary" onclick={() => beginEdit('__new__')} disabled={Boolean(editingId)}>
      <Icon name="plus" size={11} />新建模板
    </button>
  </PageHeader>

  <div class="tabs" role="tablist" aria-label="提示词分类">
    {#each CATEGORIES as item (item.id)}
      <button
        role="tab"
        aria-selected={category === item.id}
        class="tab"
        class:on={category === item.id}
        onclick={() => switchCategory(item.id)}
      >
        {item.label}
        <span class="tab-count">{promptItemsFor(item.id).length}</span>
      </button>
    {/each}
    <span class="tab-hint">{activeCategory.hint}</span>
  </div>

  {#if prompts.error}
    <div class="note err"><Icon name="warn" size={12} /><span>{prompts.error}</span></div>
  {/if}

  {#if prompts.loading && !prompts.items.length}
    <div class="loading">正在读取提示词模板…</div>
  {:else if !items.length}
    <div class="empty">
      <Icon name="doc" size={22} />
      <div>还没有提示词模板</div>
      <button class="btn primary" onclick={() => beginEdit('__new__')}>新建一个</button>
    </div>
  {:else}
    <div class="grid">
      {#each items as item (item.id)}
        <article
          class="card"
          class:selected={item.id === selectedId}
          class:editing={editingId === item.id}
          onclick={() => {
            if (!editingId) void selectPromptTemplate(item.id, category);
          }}
          ondblclick={(e) => {
            e.preventDefault();
            if (!editingId) void beginEdit(item.id);
          }}
          role="button"
          tabindex="0"
          onkeydown={(e) => {
            if (e.key === 'Enter' && !editingId) void selectPromptTemplate(item.id, category);
            if (e.key === 'F2' && !editingId) void beginEdit(item.id);
          }}
          title="单击选中；双击编辑"
        >
          <div class="card-top">
            <div class="card-name">
              <b>{item.name}</b>
              {#if item.id === selectedId}
                <span class="badge">使用中</span>
              {:else if item.builtin}
                <span class="tag">内置</span>
              {/if}
            </div>
            <div class="card-ops" onclick={(e) => e.stopPropagation()}>
              {#if editingId !== item.id}
                <button class="link" onclick={() => beginEdit(item.id)}>编辑</button>
                {#if item.builtin}
                  <button class="link muted" onclick={() => reset(item.id)}>恢复</button>
                {:else}
                  <button class="link danger" onclick={() => remove(item.id)}>删除</button>
                {/if}
              {/if}
            </div>
          </div>

          {#if editingId === item.id}
            <div class="editor" onclick={(e) => e.stopPropagation()}>
              <label>
                <span>名称</span>
                <input bind:value={draftName} maxlength="60" spellcheck="false" />
              </label>
              <label>
                <span>说明</span>
                <input
                  bind:value={draftDescription}
                  maxlength="200"
                  spellcheck="false"
                  placeholder="一句话说明这个模板的用途"
                />
              </label>
              <label>
                <span>模板内容</span>
                <textarea
                  bind:this={editorEl}
                  bind:value={draftContent}
                  spellcheck="false"
                  onkeydown={onKey}
                ></textarea>
              </label>
              <div class="editor-foot">
                <span class="hint">
                  占位符：<code>&#123;&#123;SRT&#125;&#125;</code> 当前字幕 · <code>&#123;&#123;LANG&#125;&#125;</code> 目标语种。
                  没有 <code>&#123;&#123;SRT&#125;&#125;</code> 时自动追加到末尾。
                </span>
                <div class="editor-actions">
                  <button class="btn ghost" onclick={cancelEdit}>取消</button>
                  <button class="btn primary" onclick={saveEdit} disabled={saving}>
                    {saving ? '保存中…' : '保存模板'}
                  </button>
                </div>
              </div>
            </div>
          {:else}
            {#if item.description}
              <p class="desc">{item.description}</p>
            {/if}
            <pre class="preview" class:expanded={expanded[item.id]}>{preview(item.content) || '（空模板）'}</pre>
            <div class="card-foot">
              <button
                class="link expand"
                onclick={(e) => {
                  e.stopPropagation();
                  toggleExpand(item.id);
                }}
                title={expanded[item.id] ? '收起模板正文' : '展开模板全文'}
              >
                {expanded[item.id] ? '收起' : '展开全文'}
              </button>
              <span class="chars">{item.content.length.toLocaleString()} 字符</span>
              <div class="spacer"></div>
              {#if item.id !== selectedId}
                <button class="btn tiny" onclick={(e) => { e.stopPropagation(); void selectPromptTemplate(item.id, category); }}>
                  设为当前
                </button>
              {/if}
              <button
                class="btn tiny primary"
                onclick={(e) => { e.stopPropagation(); void copy(item.id); }}
                disabled={!canCopy}
                title={canCopy ? '把当前字幕填进这个模板并复制' : '导入并转写字幕后才能复制'}
              >
                <Icon name="export" size={10} />复制提示词
              </button>
            </div>
          {/if}
        </article>
      {/each}

      {#if isNew}
        <article class="card editing new">
          <div class="card-top">
            <div class="card-name"><b>新模板</b><span class="tag">未保存</span></div>
            <div class="card-ops" onclick={(e) => e.stopPropagation()}>
              <button class="link" onclick={cancelEdit}>取消</button>
            </div>
          </div>
          <div class="editor" onclick={(e) => e.stopPropagation()}>
            <label>
              <span>名称</span>
              <input bind:value={draftName} maxlength="60" spellcheck="false" />
            </label>
            <label>
              <span>说明</span>
              <input bind:value={draftDescription} maxlength="200" spellcheck="false" />
            </label>
            <label>
              <span>模板内容</span>
              <textarea
                bind:this={editorEl}
                bind:value={draftContent}
                spellcheck="false"
                onkeydown={onKey}
              ></textarea>
            </label>
            <div class="editor-foot">
              <span class="hint">保存后会自动选中它。</span>
              <div class="editor-actions">
                <button class="btn ghost" onclick={cancelEdit}>取消</button>
                <button class="btn primary" onclick={saveEdit} disabled={saving}>
                  {saving ? '保存中…' : '保存模板'}
                </button>
              </div>
            </div>
          </div>
        </article>
      {/if}
    </div>

    <div class="footnote">
      复制出来的提示词可以粘到任意聊天窗，再把模型回复的 SRT 粘回对应的「润色」或「翻译」页逐条对照。
      三个分类互不混杂：润色只读自己的分类，翻译只读翻译分类。
    </div>
  {/if}
</div>

<style>
  .prompts {
    flex: 1;
    min-height: 0;
    overflow-y: auto;
    padding: var(--sp-8) var(--sp-10) var(--sp-12);
    display: grid;
    grid-template-columns: minmax(0, 1120px);
    justify-content: center;
    align-content: start;
  }
  .tabs {
    display: flex;
    align-items: center;
    gap: var(--sp-1);
    margin-bottom: var(--sp-3);
    padding-bottom: var(--sp-2);
    border-bottom: 1px solid var(--separator-soft);
    flex-wrap: wrap;
  }
  .tab {
    border: 0;
    background: transparent;
    color: var(--text-2);
    font: inherit;
    font-size: 13px;
    padding: 5px 11px;
    border-radius: 7px;
    cursor: pointer;
    display: inline-flex;
    align-items: center;
    gap: 6px;
  }
  .tab:hover {
    background: var(--fill);
  }
  .tab.on {
    background: var(--accent-soft);
    color: var(--accent);
    font-weight: 500;
  }
  .tab-count {
    font-size: 11px;
    color: var(--text-3);
    font-variant-numeric: tabular-nums;
  }
  .tab.on .tab-count {
    color: var(--accent);
  }
  .tab-hint {
    margin-left: auto;
    font-size: 12px;
    color: var(--text-3);
  }
  .hint code {
    font-family: var(--mono, ui-monospace, SFMono-Regular, Menlo, monospace);
    font-size: 12px;
    padding: 1px var(--sp-1);
    border-radius: 4px;
    background: var(--fill);
  }
  .cue-meta {
    font-size: 12px;
    color: var(--text-3);
    font-variant-numeric: tabular-nums;
  }
  .grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(420px, 1fr));
    gap: 14px;
  }
  .card {
    border: 1px solid var(--line-2);
    border-radius: 12px;
    background: var(--raise);
    padding: var(--sp-4) var(--sp-4) var(--sp-3);
    display: flex;
    flex-direction: column;
    min-height: 220px;
    transition: border-color 160ms var(--ease), box-shadow 160ms var(--ease),
      transform 160ms var(--ease);
    cursor: pointer;
    min-width: 0;
  }
  .card:hover {
    border-color: var(--fill-strong);
    box-shadow: 0 4px 16px rgba(0, 0, 0, 0.06);
  }
  .card.selected {
    border-color: var(--accent);
    box-shadow: 0 0 0 3px var(--accent-soft);
  }
  .card.editing {
    cursor: default;
    border-color: var(--accent);
  }
  .card.new {
    border-style: dashed;
  }
  .card-top {
    display: flex;
    align-items: center;
    gap: var(--sp-2);
    margin-bottom: var(--sp-2);
  }
  .card-name {
    display: flex;
    align-items: baseline;
    gap: 7px;
    min-width: 0;
  }
  .card-name b {
    font-size: var(--fs-heading);
    font-weight: 600;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .badge {
    font-size: 12px;
    padding: 1px 7px;
    border-radius: 999px;
    background: var(--accent-soft);
    color: var(--accent);
    white-space: nowrap;
  }
  .tag {
    font-size: 12px;
    color: var(--text-3);
    padding: 1px 5px;
    border-radius: 4px;
    background: var(--fill);
    white-space: nowrap;
  }
  .card-ops {
    margin-left: auto;
    display: flex;
    gap: var(--sp-2);
    flex: 0 0 auto;
  }
  .link {
    border: 0;
    background: transparent;
    color: var(--accent);
    font: inherit;
    font-size: 12px;
    cursor: pointer;
    padding: 2px 3px;
  }
  .link.muted {
    color: var(--text-3);
  }
  .link.danger {
    color: var(--danger);
  }
  .desc {
    margin: 0 0 var(--sp-2);
    font-size: 13px;
    line-height: 1.7;
    color: var(--text-2);
  }
  .preview {
    flex: 1;
    margin: 0;
    font-family: var(--mono, ui-monospace, SFMono-Regular, Menlo, monospace);
    font-size: 13px;
    line-height: 1.7;
    color: var(--text-2);
    white-space: pre-wrap;
    word-break: break-word;
    /* 收起时按整行截断并带省略号，不再用渐隐切穿字身 */
    display: -webkit-box;
    -webkit-box-orient: vertical;
    -webkit-line-clamp: 9;
    overflow: hidden;
    min-height: 70px;
  }
  .preview.expanded {
    display: block;
    -webkit-line-clamp: unset;
    max-height: 420px;
    overflow-y: auto;
  }
  .link.expand {
    font-size: 12px;
    padding: 0;
    color: var(--text-2);
    white-space: nowrap;
  }
  .link.expand:hover {
    color: var(--accent);
  }
  .card-foot {
    display: flex;
    align-items: center;
    gap: 7px;
    margin-top: 10px;
    padding-top: 9px;
    border-top: 1px solid var(--separator-soft);
  }
  .chars {
    font-size: 12px;
    color: var(--text-3);
    font-variant-numeric: tabular-nums;
  }
  .spacer {
    flex: 1;
  }
  .editor {
    display: flex;
    flex-direction: column;
    gap: 9px;
    cursor: default;
  }
  .editor label {
    display: flex;
    flex-direction: column;
    gap: var(--sp-1);
  }
  .editor label > span {
    font-size: 12px;
    color: var(--text-3);
  }
  .editor input,
  .editor textarea {
    font: inherit;
    font-size: 12px;
    padding: 6px 9px;
    border-radius: 4px;
    border: 1px solid var(--separator);
    background: var(--bg-content);
    color: var(--text);
    outline: none;
    min-width: 0;
  }
  .editor textarea {
    min-height: 260px;
    resize: vertical;
    font-family: var(--mono, ui-monospace, SFMono-Regular, Menlo, monospace);
    font-size: 12px;
    line-height: 1.55;
  }
  .editor input:focus,
  .editor textarea:focus {
    border-color: var(--accent);
    box-shadow: 0 0 0 3px var(--accent-soft);
  }
  .editor-foot {
    display: flex;
    align-items: flex-end;
    gap: 10px;
    flex-wrap: wrap;
  }
  .hint {
    flex: 1;
    min-width: 220px;
    font-size: 12px;
    color: var(--text-3);
    line-height: 1.6;
  }
  .editor-actions {
    display: flex;
    gap: 7px;
  }
  .note {
    display: flex;
    align-items: flex-start;
    gap: 6px;
    padding: var(--sp-2) 10px;
    border-radius: 8px;
    font-size: 12px;
    margin-bottom: 10px;
  }
  .note.err {
    background: var(--danger-soft);
    color: var(--danger);
  }
  .loading,
  .empty {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: var(--sp-2);
    padding: 60px var(--sp-5);
    color: var(--text-2);
    font-size: 12px;
  }
  .empty .btn {
    margin-top: var(--sp-1);
  }
  .footnote {
    margin-top: var(--sp-4);
    font-size: 12px;
    color: var(--text-3);
    line-height: 1.6;
  }
  .mono {
    font-family: var(--mono, ui-monospace, SFMono-Regular, Menlo, monospace);
  }
</style>
