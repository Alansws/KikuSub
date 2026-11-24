<script lang="ts">
  /**
   * 检查器里的「章节标记」面板（独立组件，避免 Inspector 继续膨胀）。
   *
   * 三种入口都必须支持：播放头插时刻点、选区设为章节（输入标题回车即添加）、
   * 列表里改标题 / 微调起止 / 删除 / 点击跳转。所有写操作都经
   * `lib/chapters.svelte.ts` → `POST /api/chapters`，服务端整表替换并记一步历史，
   * 所以 ⌘Z 能退掉这里的每一次操作（没有第二套撤销栈）。
   */
  import Icon from './Icon.svelte';
  import {
    addPointAtPlayhead,
    addRangeChapter,
    beginChapterDraft,
    cancelChapterDraft,
    chapters,
    removeMark,
    saveChapterDraft,
    seekToMark,
    setChapterDraftEdge,
    updateMark,
  } from '../lib/chapters.svelte';
  import { pendingEdge, readyError, span as draftSpan } from '../lib/chapterDraft';
  import { setExportClip, toast } from '../lib/store.svelte';
  import { play } from '../lib/store.svelte';
  import { clipCaption, scopeForChapter } from '../lib/clipRange';
  import { parseTimeInput, tcShort } from '../lib/time';

  let title = $state('');
  /** 正在编辑的那一条（同一时间只允许一条，避免多个输入框抢历史）。 */
  let editing = $state<{ id: string; title: string; start: string; end: string } | null>(null);

  const hasSelection = $derived(
    Boolean(chapters.selection && chapters.selection.end - chapters.selection.start >= 0.2),
  );

  /** 章节草稿（把一个时刻点补成区间）：状态在 lib/chapters.svelte.ts。 */
  const draft = $derived(chapters.draft);
  const preview = $derived(draftSpan(draft, play.time));
  const draftError = $derived(readyError(draft));
  /** 两端都落位但差太短时才提示；「待定」本身已经写在槽位里。 */
  const shortDraft = $derived(
    Boolean(draft && draft.start !== null && draft.end !== null && draftError),
  );
  /** 还缺哪一端：另一端就是已锁定的锚点，不能在这里被误按覆盖。 */
  const draftPending = $derived(draft ? pendingEdge(draft) : null);

  function submitNew() {
    const text = title.trim();
    title = '';
    if (hasSelection && chapters.selection) {
      void addRangeChapter(chapters.selection, text);
    } else {
      void addPointAtPlayhead(text);
    }
  }

  function onNewKeydown(e: KeyboardEvent) {
    if (e.key === 'Enter') {
      e.preventDefault();
      submitNew();
    }
  }

  function beginEdit(mark: { id: string; title: string; start: number; end: number | null }) {
    editing = {
      id: mark.id,
      title: mark.title,
      start: tcShort(mark.start),
      end: mark.end === null ? '' : tcShort(mark.end),
    };
  }

  function commitEdit() {
    const draft = editing;
    if (!draft) return;
    editing = null;
    const start = parseTimeInput(draft.start);
    if (start === null) return; // 起点非法：保持原值，不写历史
    const end = parseTimeInput(draft.end);
    const patch: { start: number; end: number | null; title: string } = {
      start,
      // 结束时间留空 = 时刻点；早于起点时把它当作时刻点，避免生成非法区间
      end: end !== null && end > start ? end : null,
      title: draft.title.trim() || `时刻点 ${tcShort(start)}`,
    };
    void updateMark(draft.id, patch);
  }

  function cancelEdit() {
    editing = null;
  }

  /**
   * 把这个区间章节设为「处理范围」：润色、翻译、导出三处共用这一份。
   * 时刻点不提供这个入口——它是点，不是可处理的片段。
   */
  function useAsClip(mark: { id: string; title: string; start: number; end: number | null }) {
    if (mark.end === null) return;
    const scope = scopeForChapter({
      id: mark.id,
      title: mark.title || '未命名章节',
      start: mark.start,
      end: mark.end,
      label: mark.title,
    });
    setExportClip(scope);
    toast(`处理范围已设为 ${clipCaption(scope)}（润色 / 翻译 / 导出通用）`);
  }
</script>

<section class="chapters-panel" aria-label="章节标记">
  <header>
    <b>章节标记</b>
    <span class="count" title="时刻点会自动衔接到下一个标记或片尾">
      {chapters.marks.length} 个标记
      {#if chapters.layoutCount && chapters.layoutCount !== chapters.marks.length}
        · 写入后 {chapters.layoutCount} 段
      {/if}
    </span>
  </header>

  {#if draft}
    <div class="draft" aria-label="章节草稿">
      <div class="draft-head">
        <b>补章节</b>
        <span class="draft-title" title={draft.title}>{draft.title || '未命名'}</span>
        <button
          class="iconbtn"
          onclick={() => cancelChapterDraft()}
          title="取消草稿（Esc）"
          aria-label="取消草稿"
        >
          <Icon name="close" size={10} />
        </button>
      </div>
      <div class="draft-rows">
        <div class="draft-slot" class:todo={draft.start === null}>
          <span class="k">起点</span>
          <span class="v">{draft.start === null ? '待定' : tcShort(draft.start)}</span>
        </div>
        <span class="arrow" aria-hidden="true">→</span>
        <div class="draft-slot" class:todo={draft.end === null}>
          <span class="k">终点</span>
          <span class="v">{draft.end === null ? '待定' : tcShort(draft.end)}</span>
        </div>
      </div>
      {#if preview}
        <p class="draft-live">
          播放头 {tcShort(play.time)} · 预览 {tcShort(preview.start)} → {tcShort(preview.end)}
          （{tcShort(preview.end - preview.start)}）
        </p>
      {/if}
      <div class="draft-actions">
        <button
          class="btn tiny"
          disabled={Boolean(draftPending && draftPending !== 'start')}
          title={draftPending === 'end' ? '终点是这一端的锚点，先补起点' : '把当前播放头设为章首'}
          onclick={() => setChapterDraftEdge('start', play.time)}
        >
          设为起点 <kbd>I</kbd>
        </button>
        <button
          class="btn tiny"
          disabled={Boolean(draftPending && draftPending !== 'end')}
          title={draftPending === 'start' ? '起点是这一端的锚点，先补终点' : '把当前播放头设为章末'}
          onclick={() => setChapterDraftEdge('end', play.time)}
        >
          设为终点 <kbd>O</kbd>
        </button>
        <button class="btn tiny" disabled={Boolean(draftError)} onclick={() => void saveChapterDraft()}>
          保存章节
        </button>
      </div>
      {#if shortDraft}
        <p class="err">{draftError}</p>
      {/if}
    </div>
  {/if}

  <div class="add-row" class:hidden={Boolean(draft)}>
    <input
      class="ch-title"
      type="text"
      placeholder="新标记标题（回车添加）"
      bind:value={title}
      onkeydown={onNewKeydown}
      disabled={chapters.saving}
      maxlength="120"
    />
    <div class="add-actions">
      <button
        class="btn tiny"
        onclick={() => {
          const text = title.trim();
          title = '';
          void addPointAtPlayhead(text);
        }}
        disabled={chapters.saving}
        title="在播放头插入时刻点（不选区间时回车走这个）"
      >
        <Icon name="flag" size={10} /> 插时刻点
      </button>
      <button
        class="btn tiny"
        onclick={() => {
          const text = title.trim();
          title = '';
          void addRangeChapter(chapters.selection, text);
        }}
        disabled={chapters.saving || !hasSelection}
        title={hasSelection ? '把当前波形选区设为一个章节' : '先在波形上框选一段'}
      >
        选区设为章节
      </button>
    </div>
  </div>

  {#if chapters.error}
    <p class="err">{chapters.error}</p>
  {/if}

  {#if !chapters.marks.length}
    <p class="chapter-empty">
      还没有标记。在播放头点「插时刻点」，或先框选一段波形再「选区设为章节」——两者都会写进成片容器，IINA
      等播放器可直接跳转。
    </p>
  {:else}
    <ul class="list">
      {#each [...chapters.marks].sort((a, b) => a.start - b.start) as mark (mark.id)}
        <li class="item" class:point={mark.end === null} class:is-draft={draft?.from === mark.id}>
          {#if editing && editing.id === mark.id}
            <div class="edit">
              <input
                class="e-title"
                type="text"
                bind:value={editing.title}
                maxlength="120"
                placeholder="标题"
                onkeydown={(e) => {
                  if (e.key === 'Enter') {
                    e.preventDefault();
                    commitEdit();
                  } else if (e.key === 'Escape') {
                    cancelEdit();
                  }
                }}
              />
              <div class="e-times">
                <input class="e-time" type="text" bind:value={editing.start} title="起点（mm:ss.mmm）" />
                <span>→</span>
                <input
                  class="e-time"
                  type="text"
                  bind:value={editing.end}
                  title="终点；留空 = 时刻点（自动衔接到下一个标记或片尾）"
                  placeholder="片尾"
                />
              </div>
              <div class="e-actions">
                <button class="btn tiny" onclick={commitEdit}>保存</button>
                <button class="btn tiny ghost" onclick={cancelEdit}>取消</button>
              </div>
            </div>
          {:else}
            <button
              class="jump"
              onclick={() => seekToMark(mark.id)}
              title={`跳到 ${tcShort(mark.start)}`}
            >
              <span class="kind" aria-hidden="true">{mark.end === null ? '◆' : '▭'}</span>
              <span class="t">{mark.title || '未命名'}</span>
              <span class="times">
                {tcShort(mark.start)}{mark.end === null ? '' : ` → ${tcShort(mark.end)}`}
              </span>
            </button>
            <div class="ops">
              {#if mark.end === null}
                <button
                  class="iconbtn"
                  onclick={() => beginChapterDraft(mark.id, 'end')}
                  title="把这个时刻当作章末，补一个起点"
                  aria-label="补起点"
                >
                  <Icon name="chevron-left" size={11} />
                </button>
                <button
                  class="iconbtn"
                  onclick={() => beginChapterDraft(mark.id, 'start')}
                  title="把这个时刻当作章首，补一个终点"
                  aria-label="补终点"
                >
                  <Icon name="chevron-right" size={11} />
                </button>
              {/if}
              {#if mark.end !== null}
                <button
                  class="iconbtn"
                  onclick={() => useAsClip(mark)}
                  title="仅处理此片段：把这一章设为润色 / 翻译 / 导出范围"
                  aria-label="仅处理此片段"
                >
                  <Icon name="film" size={11} />
                </button>
              {/if}
              <button class="iconbtn" onclick={() => beginEdit(mark)} title="编辑标题与时间" aria-label="编辑标记">
                <Icon name="pencil" size={11} />
              </button>
              <button
                class="iconbtn"
                onclick={() => void removeMark(mark.id)}
                title="删除这个标记（可 ⌘Z 撤回）"
                aria-label="删除标记"
              >
                <Icon name="trash" size={11} />
              </button>
            </div>
          {/if}
        </li>
      {/each}
    </ul>
  {/if}

  <p class="hint">
    单击标记跳转；标题与时间可在这里改。标记随影片保存（换片 / 重启不丢），导出时按顺序写入容器。
    区间章节右侧的「仅处理此片段」会把这一段设为润色 / 翻译 / 导出的范围。
    {#if play.duration > 0}
      当前播放头 {tcShort(play.time)}。
    {/if}
  </p>
</section>

<style>
  .chapters-panel {
    padding: 10px var(--sp-3) 14px;
    display: flex;
    flex-direction: column;
    gap: var(--sp-2);
    min-height: 0;
    overflow: auto;
  }

  header {
    display: flex;
    align-items: baseline;
    gap: var(--sp-2);
    justify-content: space-between;
  }

  header b {
    font-size: 12px;
  }

  .count {
    font-size: 11px;
    color: var(--text-3);
    font-variant-numeric: tabular-nums;
  }

  .add-row {
    display: flex;
    flex-direction: column;
    gap: 6px;
  }

  .ch-title {
    width: 100%;
    height: 26px;
    padding: 0 var(--sp-2);
    font-size: 12px;
    border-radius: 6px;
    border: 1px solid var(--line);
    background: var(--field);
    color: var(--text);
  }

  .add-row.hidden {
    display: none;
  }

  .add-actions {
    display: flex;
    gap: 6px;
  }

  .list {
    list-style: none;
    margin: 0;
    padding: 0;
    display: flex;
    flex-direction: column;
    gap: 2px;
  }

  .item {
    display: flex;
    align-items: center;
    gap: var(--sp-1);
    border-radius: 6px;
    padding: 2px var(--sp-1);
  }

  .item:hover {
    background: var(--hover);
  }

  .jump {
    flex: 1;
    min-width: 0;
    display: flex;
    align-items: center;
    gap: 6px;
    background: transparent;
    border: 0;
    padding: 3px 2px;
    text-align: left;
    color: var(--text);
    font-size: 12px;
    cursor: pointer;
  }

  .kind {
    color: var(--accent);
    font-size: 10px;
    width: 10px;
    flex: none;
  }

  .t {
    overflow: hidden;
    white-space: nowrap;
    text-overflow: ellipsis;
  }

  .times {
    margin-left: auto;
    flex: none;
    font-size: 11px;
    color: var(--text-3);
    font-variant-numeric: tabular-nums;
  }

  .ops {
    display: flex;
    gap: 2px;
    opacity: 0;
  }

  .item:hover .ops,
  .item:focus-within .ops {
    opacity: 1;
  }

  .iconbtn {
    display: grid;
    place-items: center;
    width: 20px;
    height: 20px;
    border-radius: 4px;
    border: 0;
    background: transparent;
    color: var(--text-3);
    cursor: pointer;
  }

  .iconbtn:hover {
    background: var(--line);
    color: var(--text);
  }

  .edit {
    flex: 1;
    display: flex;
    flex-direction: column;
    gap: var(--sp-1);
    padding: var(--sp-1) 0;
  }

  .e-title,
  .e-time {
    height: 24px;
    padding: 0 6px;
    font-size: 12px;
    border-radius: 5px;
    border: 1px solid var(--line);
    background: var(--field);
    color: var(--text);
  }

  .e-title {
    width: 100%;
  }

  .e-times {
    display: flex;
    align-items: center;
    gap: var(--sp-1);
    font-size: 11px;
    color: var(--text-3);
  }

  .e-time {
    width: 84px;
    font-variant-numeric: tabular-nums;
  }

  .e-actions {
    display: flex;
    gap: 6px;
  }

  .chapter-empty,
  .hint {
    margin: 0;
    font-size: 11px;
    line-height: 16px;
    color: var(--text-3);
  }

  .err {
    margin: 0;
    font-size: 11px;
    color: var(--danger);
  }

  .draft {
    border: 1px dashed var(--accent);
    border-radius: 8px;
    padding: var(--sp-2);
    display: flex;
    flex-direction: column;
    gap: 6px;
    background: color-mix(in srgb, var(--accent) 6%, transparent);
  }

  .draft-head {
    display: flex;
    align-items: center;
    gap: 6px;
  }

  .draft-head b {
    font-size: 12px;
    flex: none;
  }

  .draft-title {
    flex: 1;
    min-width: 0;
    font-size: 11px;
    color: var(--text-3);
    overflow: hidden;
    white-space: nowrap;
    text-overflow: ellipsis;
  }

  .draft-rows {
    display: flex;
    align-items: center;
    gap: 6px;
  }

  .draft-slot {
    flex: 1;
    min-width: 0;
    display: flex;
    flex-direction: column;
    gap: 1px;
    padding: 3px 6px;
    border-radius: 5px;
    border: 1px solid var(--line);
    background: var(--field);
  }

  .draft-slot .k {
    font-size: 10px;
    color: var(--text-3);
  }

  .draft-slot .v {
    font-size: 12px;
    font-variant-numeric: tabular-nums;
  }

  .draft-slot.todo .v {
    color: var(--text-3);
  }

  .arrow {
    flex: none;
    font-size: 11px;
    color: var(--text-3);
  }

  .draft-live {
    margin: 0;
    font-size: 11px;
    line-height: 16px;
    color: var(--text-2);
    font-variant-numeric: tabular-nums;
  }

  .draft-actions {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
  }

  .draft-actions .btn {
    height: 24px;
    padding: 0 var(--sp-2);
    font-size: 11px;
  }

  kbd {
    font: inherit;
    font-size: 10px;
    padding: 0 3px;
    border-radius: 3px;
    border: 1px solid var(--line);
    color: var(--text-3);
  }

  .item.is-draft {
    background: color-mix(in srgb, var(--accent) 10%, transparent);
  }
</style>
