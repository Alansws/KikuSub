<script lang="ts">
  /**
   * 核对台的字幕表：表头 + 虚拟列表 + 查找栏。
   *
   * 2026-11-24 从 `ReviewView.svelte` 抽出来（界面原生化 Phase 2）。红线 11 要求
   * 「先抽、再改列」——下一步要在这里加**状态列**，所以先把它整块搬出来，行为不变。
   *
   * 组件不拥有状态：窗口计算（`lib/reviewTable.ts`）、查找命中（`lib/findMatches.ts`）、
   * 选择（`lib/selection.ts`）仍在父组件，这里只渲染 + 回调。这样「单击跳转 vs 4px 框选」
   * 与「⌘ 多选 / ⇧ 连选」的口径只有一份。
   *
   * 行高是固定值（双语双行），绝不能在这里自动测量——虚拟滚动按 `rowHeight` 算偏移，
   * 自动测量会让偏移算错（开发文档 §6.3.2）。
   */
  import Icon from '../Icon.svelte';
  import { tcShort } from '../../lib/time';
  import type { Cue } from '../../lib/api';

  /** 查找栏要用的一整组状态与动作（父组件持有）。 */
  export interface FindBindings {
    open: boolean;
    query: string;
    replacement: string;
    caseSensitive: boolean;
    count: number;
    total: number;
    rawTotal: number;
    skipped: number;
    busy: boolean;
    prevKey: string;
    nextKey: string;
    onInput: () => void;
    onGo: (delta: number) => void;
    onReplace: () => void;
    onSkip: () => void;
    onReplaceAll: () => void;
    onToggleCase: () => void;
    onClose: () => void;
  }



  export interface TableBindings {
    track: 'source' | 'target' | 'both';
    rows: Cue[];
    rowStart: number;
    rowEnd: number;
    total: number;
    rowHeight: number;
    padTop: number;
    padBottom: number;
    selected: number;
    multiKeys: string[];
    activeKey: string;
    matchedSet: Set<number>;
    findCue: number;
    busy: boolean;
    /** 每行 / 每轨的高亮切分与译文取值（由父组件的查找上下文决定）。 */
    displayText: (text: string) => string;
    translationAt: (index: number) => string;
    isStale: (index: number) => boolean;
    highlight: (
      text: string,
      track: 'source' | 'target',
      ordinal: number,
      skipped?: Set<number>,
    ) => { text: string; hit: boolean; cur: boolean; skipped: boolean }[];
    ordinalFor: (index: number, track: 'source' | 'target') => number;
    skippedFor: (index: number, track: 'source' | 'target') => Set<number> | undefined;
  }

  let {
    view,
    find,
    onscroll,
    rowclick,
    rowcontext,
    rowaudition,
    rowretranscribe,
    onrows,
    findInput,
  }: {
    view: TableBindings;
    find: FindBindings;
    onscroll: (scrollTop: number) => void;
    rowclick: (index: number, e: MouseEvent) => void;
    rowcontext: (e: MouseEvent, index: number) => void;
    rowaudition: (index: number) => void;
    rowretranscribe: (index: number) => void;
    onrows: (node: HTMLDivElement) => void;
    findInput: (node: HTMLInputElement) => void;
  } = $props();

  let rowsNode = $state<HTMLDivElement | null>(null);
  let findNode = $state<HTMLInputElement | null>(null);

  $effect(() => {
    if (rowsNode) onrows(rowsNode);
  });
  $effect(() => {
    if (findNode) findInput(findNode);
  });

  /** 行是否在多选里：多选状态看块键，否则看当前行。 */
  function isSelected(cue: Cue, index: number): boolean {
    const key = `${cue.start}:${cue.end}`;
    return view.multiKeys.length > 1
      ? view.multiKeys.some((k) => k === key)
      : view.selected === index;
  }

  function keyOf(cue: Cue): string {
    return `${cue.start}:${cue.end}`;
  }

  function placeholder(): string {
    if (view.track === 'target') return '查找译文…';
    if (view.track === 'both') return '查找原文 / 译文…';
    return '查找原文…';
  }

  function countLabel(): string {
    if (!find.query) return '0';
    if (find.count) return `${find.total + 1} / ${find.count}`;
    if (find.rawTotal) return '已全部跳过';
    return '无结果';
  }
</script>

<div class="table-area">
  {#if find.open}
    <div class="find-bar">
      <Icon name="search" size={12} />
      <input
        bind:this={findNode}
        class="find-input"
        value={find.query}
        oninput={() => find.onInput()}
        onkeydown={(e) => {
          if (e.key === 'Enter') {
            e.preventDefault();
            find.onGo(e.shiftKey ? -1 : 1);
          } else if (e.key === 'Escape') {
            e.preventDefault();
            find.onClose();
          }
        }}
        placeholder={placeholder()}
        spellcheck="false"
      />
      <span class="find-count">
        {#if find.query}
          {#if find.count}
            {find.total + 1} / {find.count}
          {:else if find.rawTotal}
            已全部跳过
          {:else}
            无结果
          {/if}
        {:else}
          0
        {/if}
      </span>
      {#if find.skipped}
        <span
          class="find-skipped"
          title="本轮已跳过 {find.skipped} 处；改查找词或重开查找可恢复"
        >
          跳过 {find.skipped}
        </span>
      {/if}
      <button
        class="btn icon ghost"
        onclick={() => find.onGo(-1)}
        disabled={!find.count}
        title={`上一处（${find.prevKey} / ⇧Enter）`}
      >
        <Icon name="chevron-left" size={11} />
      </button>
      <button
        class="btn icon ghost"
        onclick={() => find.onGo(1)}
        disabled={!find.count}
        title={`下一处（${find.nextKey} / Enter）`}
      >
        <Icon name="chevron-right" size={11} />
      </button>
      <button
        class="find-case"
        class:on={find.caseSensitive}
        onclick={() => find.onToggleCase()}
        title="区分大小写"
      >
        Aa
      </button>
      <div class="find-sep"></div>
      <input
        class="find-input replace"
        value={find.replacement}
        oninput={() => find.onInput()}
        onkeydown={(e) => {
          if (e.key === 'Enter') {
            e.preventDefault();
            find.onReplace();
          } else if (e.key === 'Escape') {
            e.preventDefault();
            find.onClose();
          }
        }}
        placeholder="替换为（可留空）"
        spellcheck="false"
      />
      <button class="btn tiny" onclick={() => find.onReplace()} disabled={!find.count || find.busy}>
        替换
      </button>
      <button
        class="btn tiny"
        onclick={() => find.onSkip()}
        disabled={!find.count || find.busy}
        title="跳过这一处，本轮不再回到它（不修改文本）"
      >
        跳过
      </button>
      <button
        class="btn tiny primary"
        onclick={() => find.onReplaceAll()}
        disabled={!find.count || find.busy}
        title={find.skipped
          ? `替换本轮未跳过的 ${find.count} 处（已跳过 ${find.skipped} 处保持原样）`
          : '替换全部匹配'}
      >
        {find.skipped ? '替换剩余' : '全部替换'}
      </button>
      <div class="tl-spacer"></div>
      <button class="btn icon ghost" onclick={() => find.onClose()} title="关闭（Esc）">
        <Icon name="close" size={11} />
      </button>
    </div>
  {/if}

  <div class="thead">
    <div class="c-idx">#</div>
    <div class="c-t">开始</div>
    <div class="c-t">结束</div>
    <div class="c-dur">时长</div>
    <div class="c-text">字幕文本</div>
    <div class="c-acts"></div>
  </div>

  <div
    class="rows"
    bind:this={rowsNode}
    onscroll={(e) => onscroll(e.currentTarget.scrollTop)}
  >
    {#if !view.rows.length && view.total === 0}
      <div class="empty-rows">还没有字幕。到「转写」跑一次，或导入 SRT。</div>
    {:else}
      <div style="height:{view.padTop}px"></div>
      {#each view.rows as cue, k (view.rowStart + k)}
        {@const i = view.rowStart + k}
        <div
          class="row"
          class:dual={view.track === 'both'}
          class:row-sel={isSelected(cue, i)}
          class:row-match={view.matchedSet.has(i)}
          class:row-cur={view.findCue === i}
          class:playing={Boolean(view.activeKey) && keyOf(cue) === view.activeKey}
          data-i={i}
          onmousedown={(e) => e.shiftKey && e.preventDefault()}
          onclick={(e) => rowclick(i, e)}
          oncontextmenu={(e) => rowcontext(e, i)}
          ondblclick={() => rowaudition(i)}
          role="button"
          tabindex="-1"
          title="单击跳转 · ⌘ 单击多选 · ⇧ 单击连选 · 双击试听"
        >
          <div class="c-idx">{i + 1}</div>
          <div class="c-t">{tcShort(cue.start)}</div>
          <div class="c-t">{tcShort(cue.end)}</div>
          <div class="c-dur">{(cue.end - cue.start).toFixed(2)}s</div>
          <div class="c-text" class:dual={view.track === 'both'}>
            {#if view.track === 'target'}
              <span class="line" class:stale={view.isStale(i)}>
                {#if view.translationAt(i)}
                  {#each view.highlight(
                    view.displayText(view.translationAt(i)),
                    'target',
                    view.ordinalFor(i, 'target'),
                    view.skippedFor(i, 'target'),
                  ) as part}
                    <span
                      class:text-hit={part.hit}
                      class:cur={part.cur}
                      class:skipped={part.skipped}>{part.text}</span
                    >
                  {/each}
                {:else}
                  （这条还没有译文）
                {/if}
              </span>
            {:else if view.track === 'both'}
              <span class="line">
                {#each view.highlight(
                  view.displayText(cue.text),
                  'source',
                  view.ordinalFor(i, 'source'),
                  view.skippedFor(i, 'source'),
                ) as part}
                  <span
                    class:text-hit={part.hit}
                    class:cur={part.cur}
                    class:skipped={part.skipped}>{part.text}</span
                  >
                {/each}
              </span>
              <span class="line sub" class:stale={view.isStale(i)}>
                {#each view.highlight(
                  view.displayText(view.translationAt(i)),
                  'target',
                  view.ordinalFor(i, 'target'),
                  view.skippedFor(i, 'target'),
                ) as part}
                  <span
                    class:text-hit={part.hit}
                    class:cur={part.cur}
                    class:skipped={part.skipped}>{part.text}</span
                  >
                {/each}
              </span>
            {:else}
              <span class="line">
                {#each view.highlight(
                  view.displayText(cue.text),
                  'source',
                  view.ordinalFor(i, 'source'),
                  view.skippedFor(i, 'source'),
                ) as part}
                  <span
                    class:text-hit={part.hit}
                    class:cur={part.cur}
                    class:skipped={part.skipped}>{part.text}</span
                  >
                {/each}
              </span>
            {/if}
          </div>
          <div class="c-acts">
            <button
              class="row-btn"
              onclick={(e) => {
                e.stopPropagation();
                rowaudition(i);
              }}
              title="试听此句"
            >
              <Icon name="play" size={10} />
            </button>
            <button
              class="row-btn"
              onclick={(e) => {
                e.stopPropagation();
                rowretranscribe(i);
              }}
              disabled={view.busy}
              title="单独重转此句（只替换这一条）"
            >
              <Icon name="wave" size={10} />
            </button>
          </div>
        </div>
      {/each}
      <div style="height:{view.padBottom}px"></div>
    {/if}
  </div>
</div>

<style>
  /* ---------------- 表格 ---------------- */
  .table-area {
    flex: 1;
    min-height: 0;
    display: flex;
    flex-direction: column;
    margin: 6px 26px 0;
    border-top: 1px solid var(--line);
  }
  .thead {
    display: grid;
    grid-template-columns: 34px 100px 100px 54px minmax(0, 1fr) 44px;
    column-gap: 6px;
    align-items: center;
    height: 30px;
    padding: 0 10px;
    font-size: 12px;
    line-height: 16px;
    font-weight: 500;
    color: var(--text-2);
    box-shadow: inset 0 -1px 0 var(--line-2);
    flex: 0 0 30px;
  }
  .rows {
    flex: 1;
    min-height: 0;
    overflow-y: auto;
    overflow-x: hidden;
    padding-bottom: 0;
    mask-image: linear-gradient(to bottom, #000 calc(100% - 18px), transparent 100%);
    -webkit-mask-image: linear-gradient(to bottom, #000 calc(100% - 18px), transparent 100%);
  }

  .row {
    display: grid;
    grid-template-columns: 34px 100px 100px 54px minmax(0, 1fr) 44px;
    column-gap: 6px;
    align-items: center;
    height: 30px;
    padding: 0 10px;
    font-size: 15px;
    line-height: 20px; /* 15/20：行内上下各 5px，基线稳定，不出现 20.25 的分数行高 */
    /* 发丝线用 inset shadow：border 会吃掉 1px，行内 20px 文字就变成上下 4.5/5.5 */
    box-shadow: inset 0 -1px 0 var(--line-2);
    position: relative;
    transition: background 120ms var(--ease);
  }
  .row:hover {
    background: var(--line-2);
  }
  .row.row-match {
    background: var(--hit-row);
  }
  .row.row-sel {
    background: var(--accent-soft);
  }
  .row.playing::before,
  .row.row-sel::before {
    content: '';
    position: absolute;
    left: 0;
    top: 0;
    bottom: 0;
    width: 2px;
    background: var(--accent);
  }
  .row.playing .c-idx {
    color: var(--accent);
    font-weight: 600;
  }
  /* 查找当前项：即使播放头把选中行带走了，序号仍指出正在处理哪一条 */
  .row.row-cur .c-idx {
    color: var(--accent);
    font-weight: 600;
  }
  .row.playing .c-text {
    font-weight: 500;
  }

  @media (max-width: 1400px) {
    /* 1360 默认窗口：给字幕文本多 16px，当前句不要被时间码/图标挤掉尾巴 */
    .thead,
    .row {
      grid-template-columns: 34px 94px 94px 54px minmax(0, 1fr) 42px;
    }
  }

  @media (max-width: 1220px) {
    /* 窄窗口里选区工具条会挤出右边界：只留时长，把时间范围让给按钮 */
    .sel-range {
      display: none;
    }
    .thead,
    .row {
      grid-template-columns: 30px 88px 88px 48px minmax(0, 1fr) 38px;
      column-gap: var(--sp-1);
    }
    .thead {
      padding: 0 var(--sp-2);
    }
    .row {
      padding: 0 var(--sp-2);
    }
  }

  .c-idx {
    font-size: 12px;
    line-height: 16px;
    color: var(--text-3);
    font-variant-numeric: tabular-nums;
    font-family: var(--font-mono);
  }
  .c-t {
    font-family: var(--font-mono);
    font-size: 12px;
    line-height: 16px;
    color: var(--ink-2);
    font-variant-numeric: tabular-nums;
    letter-spacing: -0.02em;
  }
  .c-dur {
    font-family: var(--font-mono);
    font-size: 12px;
    line-height: 16px;
    color: var(--text-3);
    font-variant-numeric: tabular-nums;
  }
  .c-text {
    min-width: 0;
    font-family: var(--font-cue);
    font-size: 15px;
    line-height: 20px;
    color: var(--ink);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    padding-right: 6px;
  }
  /* 双语：固定两行，行高与虚拟列表的 60px 对齐 */
  .row.dual {
    height: 60px;
  }
  .c-text.dual {
    display: flex;
    flex-direction: column;
    justify-content: center;
    /* 20 + 16 + 2 = 38：(60 - 38) / 2 = 11，双语的上下留白落在整数像素上 */
    gap: 2px;
    line-height: 20px;
  }
  .c-text .line {
    display: block;
    min-width: 0;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .c-text .line.sub {
    /* 译文轨始终跟界面字体：12px 的明朝在浅底上太细，读起来像印刷品缩印 */
    font-family: var(--font-sans);
    font-size: 12px;
    line-height: 16px;
    color: var(--text-2);
  }
  .c-text .line.stale {
    color: var(--warn);
  }
  .c-text .text-hit {
    background: var(--hit);
    border-radius: 2px;
    color: inherit;
  }
  /* 当前正在处理的这一处：比普通命中更深，同一句里有多处也能一眼分清 */
  .c-text .text-hit.cur {
    background: var(--accent);
    color: var(--on-accent);
    box-shadow: 0 0 0 1px var(--accent);
  }
  /* 本轮已跳过：仍在文本里，但本轮不再回来处理 */
  .c-text .text-hit.skipped {
    background: transparent;
    color: var(--text-3);
    text-decoration: line-through;
    text-decoration-thickness: 1px;
  }
  .c-acts {
    display: flex;
    justify-content: flex-end;
    gap: var(--sp-1);
    opacity: 0;
    transition: opacity 120ms var(--ease);
  }
  .row:hover .c-acts,
  .row.row-sel .c-acts {
    opacity: 1;
  }
  .row-btn {
    appearance: none;
    border: 0;
    background: transparent;
    color: var(--text-3);
    width: 19px;
    height: 19px;
    border-radius: 4px;
    display: grid;
    place-items: center;
    position: relative;
  }
  /* 视觉 19px，热区 24px：伪元素只扩大命中范围，不改变行高与列宽 */
  .row-btn::after {
    content: '';
    position: absolute;
    inset: -2.5px -2px;
  }
  .row-btn:hover {
    background: var(--fill-strong);
    color: var(--accent);
  }
  .row-btn:disabled {
    opacity: 0.35;
  }

  .empty-rows {
    padding: 22px 14px;
    color: var(--text-3);
    font-size: 12.5px;
  }

  /* ---------------- 查找与替换 ---------------- */
  .find-bar {
    display: flex;
    /* 桌面宽度下宁可让两个输入框收缩，也不要让关闭按钮掉到第二行 */
    flex-wrap: nowrap;
    align-items: center;
    gap: var(--sp-1);
    padding: 5px 14px;
    flex: 0 0 auto;
    border-bottom: 1px solid var(--separator-soft);
    background: color-mix(in srgb, var(--accent) 5%, var(--bg-content));
  }
  .find-input {
    height: 24px;
    width: 160px;
    min-width: 96px;
    flex: 0 1 160px;
    border-radius: 4px;
    border: 1px solid var(--separator);
    background: var(--bg-content);
    color: var(--text);
    font: inherit;
    font-size: 12px;
    padding: 0 7px;
  }
  .find-input:focus {
    outline: none;
    border-color: var(--accent);
    box-shadow: 0 0 0 2px var(--accent-soft);
  }
  .find-input.replace {
    width: 130px;
    flex-basis: 130px;
  }
  .find-count {
    min-width: 58px;
    text-align: right;
    font-size: 12px;
    color: var(--text-3);
    font-variant-numeric: tabular-nums;
    font-family: ui-monospace, 'SF Mono', Menlo, monospace;
    white-space: nowrap;
  }
  .find-skipped {
    height: 18px;
    padding: 0 5px;
    border: 1px solid var(--separator);
    border-radius: 3px;
    font-size: 11px;
    line-height: 16px;
    color: var(--text-3);
    white-space: nowrap;
    font-variant-numeric: tabular-nums;
  }
  /* 1280 以下查找栏已经很挤：跳过数量不单列徽标，靠删除线和计数变化判断 */
  @media (max-width: 1280px) {
    .find-skipped {
      display: none;
    }
  }
  .find-case {
    appearance: none;
    border: 1px solid transparent;
    background: transparent;
    color: var(--text-3);
    font: inherit;
    font-size: 12px;
    font-weight: 600;
    height: 22px;
    padding: 0 5px;
    border-radius: 4px;
    cursor: pointer;
  }
  .find-case:hover {
    background: var(--fill-strong);
  }
  .find-case.on {
    background: var(--accent-soft);
    border-color: var(--accent-ring);
    color: var(--accent);
  }
  .find-sep {
    width: 1px;
    height: 16px;
    background: var(--separator);
    margin: 0 3px;
    flex: 0 0 1px;
  }

  /* 查找栏在 680/540 宽下要留在一行：隐藏「Aa」与分隔线，输入框可收缩。
     折行会把表格再吃掉一行高度，关闭按钮也会单独掉到第二行。
     （2026-11-24 随表格一起搬进来：这些规则只作用于本组件里的节点。） */
  @media (max-width: 900px) {
    .find-bar {
      padding: 5px 6px;
      gap: 3px;
      flex-wrap: wrap;
    }
    .find-input {
      width: auto;
      flex: 1 1 110px;
      min-width: 80px;
    }
    .find-input.replace {
      width: auto;
      flex: 1 1 96px;
      min-width: 72px;
    }
    .find-count {
      min-width: 42px;
    }
    /* 窄窗口优先保住「替换 / 跳过 / 全部替换」一行；跳过数量靠删除线判断 */
    .find-skipped {
      display: none;
    }
    .find-case,
    .find-sep {
      display: none;
    }
  }

</style>
