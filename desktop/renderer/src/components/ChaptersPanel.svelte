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
    chapters,
    removeMark,
    seekToMark,
    updateMark,
  } from '../lib/chapters.svelte';
  import { play } from '../lib/store.svelte';
  import { parseTimeInput, tcShort } from '../lib/time';

  let title = $state('');
  /** 正在编辑的那一条（同一时间只允许一条，避免多个输入框抢历史）。 */
  let editing = $state<{ id: string; title: string; start: string; end: string } | null>(null);

  const hasSelection = $derived(
    Boolean(chapters.selection && chapters.selection.end - chapters.selection.start >= 0.2),
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

  <div class="add-row">
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
        <li class="item" class:point={mark.end === null}>
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
</style>
