<script lang="ts">
  /**
   * 检查器里的「章节」页签。
   *
   * 2026-11-25 重做布局：原来的卡片里塞了三段解释文字、新建输入框和列表挤在一起，
   * 用户说「功能逻辑不清晰、说明文字太多」。现在只分两层：
   *
   * 1. **上面是「新建」**：一个可选标题 + 两枚动作（时刻点 / 选区章节）；
   * 2. **下面每条标记一行**：名称 + 时间（点击跳转），行内图标是「对这一段做什么」
   *    —— 处理范围 / 加入转写选区 / 补端点 / 编辑 / 删除，解释都收进 title。
   *
   * 所有写操作仍经 `lib/chapters.svelte.ts` → `POST /api/chapters`（一步历史）。
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
    useChapterAsTranscribe,
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

  /** 章节草稿（把一个时刻点补成区间）。 */
  const draft = $derived(chapters.draft);
  const preview = $derived(draftSpan(draft, play.time));
  const draftError = $derived(readyError(draft));
  /** 还缺哪一端：另一端就是已锁定的锚点，不能在这里被误按覆盖。 */
  const draftPending = $derived(draft ? pendingEdge(draft) : null);
  /** 两端都落位但差太短时才提示；「待定」本身已经写在槽位里。 */
  const shortDraft = $derived(
    Boolean(draft && draft.start !== null && draft.end !== null && draftError),
  );

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

  function addPoint() {
    const text = title.trim();
    title = '';
    void addPointAtPlayhead(text);
  }

  function addRange() {
    const text = title.trim();
    title = '';
    void addRangeChapter(chapters.selection, text);
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
    const draftEdit = editing;
    if (!draftEdit) return;
    editing = null;
    const start = parseTimeInput(draftEdit.start);
    if (start === null) return; // 起点非法：保持原值，不写历史
    const end = parseTimeInput(draftEdit.end);
    const patch: { start: number; end: number | null; title: string } = {
      start,
      // 结束时间留空 = 时刻点；早于起点时把它当作时刻点，避免生成非法区间
      end: end !== null && end > start ? end : null,
      title: draftEdit.title.trim() || `时刻点 ${tcShort(start)}`,
    };
    void updateMark(draftEdit.id, patch);
  }

  function cancelEdit() {
    editing = null;
  }

  /** 把区间章节设为「处理范围」：润色、翻译、导出三处共用这一份。 */
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

  function useAsTranscribe(mark: {
    id: string;
    title: string;
    start: number;
    end: number | null;
  }) {
    if (mark.end === null) return;
    useChapterAsTranscribe(mark);
  }
</script>

<section class="chapters-panel" aria-label="章节标记">
  <header>
    <b>章节</b>
    <span class="count" title="时刻点会自动衔接到下一个标记或片尾；导出时按顺序写入容器">
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
          预览 {tcShort(preview.start)} → {tcShort(preview.end)} · 时长 {tcShort(
            preview.end - preview.start,
          )}
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
        <button
          class="btn tiny"
          disabled={Boolean(draftError)}
          onclick={() => void saveChapterDraft()}
        >
          保存章节
        </button>
      </div>
      {#if shortDraft}
        <p class="err">{draftError}</p>
      {/if}
    </div>
  {:else}
    <div class="compose">
      <input
        class="ch-title"
        type="text"
        placeholder="标题（可选，回车添加）"
        bind:value={title}
        onkeydown={onNewKeydown}
        disabled={chapters.saving}
        maxlength="120"
      />
      <div class="compose-actions">
        <button
          class="btn tiny"
          onclick={addPoint}
          disabled={chapters.saving}
          title="在播放头插入时刻点（不框选时回车走这个）"
        >
          <Icon name="flag" size={10} /> 时刻点
        </button>
        <button
          class="btn tiny"
          onclick={addRange}
          disabled={chapters.saving || !hasSelection}
          title={hasSelection ? '把波形上的时间选区设为一个章节' : '先在波形上框选一段'}
        >
          <Icon name="range" size={10} /> 选区章节
        </button>
      </div>
    </div>
  {/if}

  {#if chapters.error}
    <p class="err">{chapters.error}</p>
  {/if}

  {#if !chapters.marks.length && !draft}
    <p class="chapter-empty">还没有标记：上方回车插入时刻点，或先框选一段再点「选区章节」。</p>
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
            </button>
            <span class="times">
              {tcShort(mark.start)}{mark.end === null ? '' : ` → ${tcShort(mark.end)}`}
            </span>
            <div class="ops">
              {#if mark.end !== null}
                <button
                  class="iconbtn"
                  onclick={() => useAsClip(mark)}
                  title="处理范围：润色 / 翻译 / 导出都只用这一段"
                  aria-label="处理此片段"
                >
                  <Icon name="film" size={11} />
                </button>
                <button
                  class="iconbtn"
                  onclick={() => useAsTranscribe(mark)}
                  title="加入转写页的时间区间（只转这一段）"
                  aria-label="加入转写选区"
                >
                  <Icon name="range" size={11} />
                </button>
              {:else}
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
              <button
                class="iconbtn"
                onclick={() => beginEdit(mark)}
                title="编辑标题与时间"
                aria-label="编辑标记"
              >
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

  .compose {
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

  .compose-actions {
    display: flex;
    gap: 6px;
  }

  .compose-actions .btn {
    height: 24px;
    padding: 0 var(--sp-2);
    font-size: 11px;
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

  .item.is-draft {
    background: color-mix(in srgb, var(--accent) 10%, transparent);
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
    flex: none;
    font-size: 11px;
    color: var(--text-3);
    font-variant-numeric: tabular-nums;
  }

  /*
   * 行内操作：默认半透明（3 枚图标在 348px 里不算挤，但全显会抢名字的注意力），
   * hover / 键盘聚焦时变实。完全藏起来的话用户不会知道这一行能操作。
   */
  .ops {
    display: flex;
    gap: 2px;
    opacity: 0.55;
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

  .chapter-empty {
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

</style>
