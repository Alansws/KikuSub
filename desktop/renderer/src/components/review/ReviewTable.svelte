<script lang="ts">
  /**
   * 核对台的字幕表：页边 + 表头 + 虚拟列表 + 查找栏。
   *
   * 2026-11-24 从 `ReviewView.svelte` 抽出来（界面原生化 Phase 2）。
   * 2026-11-25（Step 4.2）接上 Cue Script 的**签名动作**：左缘 44px 是台本的
   * 「页边」，已核打勾、AI 蓝铅笔、待核朱点都在这一列里，当前句在页边落一道
   * 2px 朱线、序号转朱。记号来源是 `lib/reviewMargin.ts`（只认质检队列与译文轨，
   * 不另造状态），由父组件算好传进来。
   *
   * 组件不拥有状态：窗口计算（`lib/reviewTable.ts`）、查找命中（`lib/findMatches.ts`）、
   * 选择（`lib/selection.ts`）仍在父组件，这里只渲染 + 回调。这样「单击跳转 vs 4px 框选」
   * 与「⌘ 多选 / ⇧ 连选」的口径只有一份。
   *
   * 行高是固定值（双语双行），绝不能在这里自动测量——虚拟滚动按 `rowHeight` 算偏移，
   * 自动测量会让偏移算错（开发文档 §6.3.2）。页边在虚拟列表里也必须**等宽等线**：
   * 每行都画自己的右边线，滚动时不会出现断裂。
   */
  import Icon from '../Icon.svelte';
  import { tcShort } from '../../lib/time';
  import { cueMarkTitle, type CueMark } from '../../lib/reviewMargin';
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
    onQuery: (value: string) => void;
    onReplacement: (value: string) => void;
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
    /** 页边记号：下标 → 待核 / 已核 / 有译文（`lib/reviewMargin.ts`）。 */
    marks: Map<number, CueMark>;
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

  /** 当前句：表格里选中的这一行，或播放头正落在的那一块（双语多行算一块）。 */
  function isCurrent(cue: Cue, index: number): boolean {
    return (
      view.selected === index ||
      (Boolean(view.activeKey) && keyOf(cue) === view.activeKey)
    );
  }

  function placeholder(): string {
    // 输入框的占位文字也不带尾部省略号（2026-11-26 全站口径：`…` 只留给
    // 「正在进行」与「内容被截断」，不再当「点开对话框」的暗示）。
    if (view.track === 'target') return '查找译文';
    if (view.track === 'both') return '查找原文 / 译文';
    return '查找原文';
  }
</script>

<div class="table-area cue-sheet">
  {#if find.open}
    <div class="find-bar">
      <Icon name="search" size={12} />
      <input
        bind:this={findNode}
        class="find-input"
        value={find.query}
        oninput={(e) => find.onQuery(e.currentTarget.value)}
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
        oninput={(e) => find.onReplacement(e.currentTarget.value)}
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
    <div class="c-margin" title="页边：已核打勾、有译文蓝铅笔、待核朱点；当前句落朱线"></div>
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
        {@const mark = view.marks.get(i)}
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
          <div
            class="cue-margin"
            class:active={isCurrent(cue, i)}
            title={cueMarkTitle(mark)}
          >
            <span class="cue-mark" class:warn={mark === 'warn'} class:ok={mark === 'ok'} class:ai={mark === 'ai'}>
              {#if mark === 'ok'}
                <Icon name="check" size={11} />
              {:else if mark === 'ai'}
                <Icon name="pencil" size={10} />
              {:else if mark === 'warn'}
                <i></i>
              {/if}
            </span>
            <span class="c-idx">{i + 1}</span>
          </div>
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
                  <!-- 局部转写新加进来的句子：只有原文，还没有译文。 -->
                  <span class="todo">待译</span>
                {/if}
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
  /* ---------------- 台本纸 ---------------- */
  /* 表格是一张**台本纸**（`.cue-sheet` 原语：纸白 + 1px 发丝线 + 7px 圆角），
     不是飘在画布上的白块。左右只留 16px 页边，把宽度让给字幕文本。 */
  .table-area {
    flex: 1;
    min-height: 0;
    display: flex;
    flex-direction: column;
    margin: var(--sp-1) var(--sp-4) var(--sp-2);
    overflow: hidden;
  }
  .thead,
  .row {
    display: grid;
    grid-template-columns: var(--cue-margin-w) 84px 84px 46px minmax(0, 1fr) 44px;
    align-items: center;
  }
  .thead {
    height: 28px;
    flex: 0 0 28px;
    font-size: var(--fs-label);
    line-height: 16px;
    font-weight: 500;
    letter-spacing: 0.06em;
    color: var(--ink-3);
    box-shadow: inset 0 -1px 0 var(--line);
  }
  /* 表头不是数据行：`字幕文本` 这一格复用了 `.c-text`（列宽对得上），
     但它必须回到 11px 标签色与界面字体，不能继承台本字与正文墨。 */
  .thead > div {
    color: var(--ink-3);
    font-family: var(--font-sans);
    font-size: var(--fs-label);
    line-height: 16px;
    font-weight: 500;
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

  /* ---------------- 页边（签名动作） ---------------- */
  /* 44px 不是缩进，是**页边**：右缘一条 1px 线把它和正文分开，像台本纸印好的那一列。
     每行自己画这条线（虚拟滚动时不会断），当前句在页边落一道 2px 朱线、序号转朱。 */
  .c-margin,
  .cue-margin {
    align-self: stretch;
    display: flex;
    align-items: center;
    gap: 2px;
    padding: 0 6px 0 var(--sp-1);
    border-right: 1px solid var(--rule);
    min-width: 0;
    overflow: hidden;
  }
  .cue-margin {
    position: relative;
    width: auto;
    flex: initial;
    justify-content: flex-start;
    color: var(--ink-3);
  }
  .cue-margin.active {
    color: var(--danger);
  }
  .cue-margin.active::before {
    content: '';
    position: absolute;
    left: 0;
    top: 0;
    bottom: 0;
    width: 2px;
    background: var(--danger);
  }

  .row {
    height: 30px;
    font-size: 15px;
    line-height: 20px; /* 15/20：行内上下各 5px，基线稳定，不出现 20.25 的分数行高 */
    /* 发丝线用 inset shadow：border 会吃掉 1px，行内 20px 文字就变成上下 4.5/5.5 */
    box-shadow: inset 0 -1px 0 var(--line);
    position: relative;
    transition: background 120ms var(--ease);
  }
  .row:hover {
    background: var(--row-hover);
  }
  .row.row-match {
    background: var(--hit-row);
  }
  .row.row-sel {
    background: var(--accent-soft);
  }
  /* 查找当前项：即使播放头把选中行带走了，序号仍指出正在处理哪一条 */
  .row.row-cur .c-idx {
    color: var(--accent-text);
    font-weight: 600;
  }
  .row.playing .c-text {
    font-weight: 500;
  }

  /* 时间码：等宽 + tabular，逐位对齐。11px 是 Data 档（DESIGN.md §字阶），
     比正文退后一档，读数才不抢台词。 */
  .c-idx {
    flex: 0 0 auto;
    margin-left: auto;
    font-size: var(--fs-mono);
    line-height: 16px;
    color: var(--ink-3);
    font-variant-numeric: tabular-nums;
    font-family: var(--font-mono);
  }
  .cue-margin.active .c-idx {
    color: var(--danger);
    font-weight: 600;
  }
  .c-t {
    padding-left: 10px;
    font-family: var(--font-mono);
    font-size: var(--fs-mono);
    line-height: 16px;
    color: var(--ink-2);
    font-variant-numeric: tabular-nums;
    letter-spacing: -0.01em;
  }
  .c-dur {
    padding-left: 10px;
    font-family: var(--font-mono);
    font-size: var(--fs-mono);
    line-height: 16px;
    color: var(--ink-3);
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
    padding-left: var(--sp-2);
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
  /* 待译不是错误，只是还没翻：用第三级文字色，别跟 stale 的 warn 抢注意力。 */
  .c-text .line .todo {
    color: var(--text-3);
    font-size: 0.92em;
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
    align-items: center;
    gap: 2px;
    padding-right: 6px;
    opacity: 0;
    transition: opacity 120ms var(--ease);
  }
  .row:hover .c-acts,
  .row.row-sel .c-acts,
  .row.row-cur .c-acts {
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
    color: var(--accent-text);
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
  /* 查找栏是表格顶部的一条「工作托盘」：纸面无染色，只用一条发丝线压在表头上，
     蓝色只出现在主按钮与当前命中上（DESIGN.md §Segmented / One Colour One Job）。 */
  .find-bar {
    display: flex;
    flex-wrap: nowrap;
    align-items: center;
    gap: var(--sp-1);
    padding: 5px 10px;
    flex: 0 0 auto;
    border-bottom: 1px solid var(--line);
    background: var(--paper);
    color: var(--ink-3);
  }
  .find-input {
    height: 24px;
    width: 160px;
    min-width: 96px;
    flex: 0 1 160px;
    border-radius: var(--rad-control);
    border: 1px solid var(--well-line);
    background: var(--well);
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
    font-size: var(--fs-mono);
    color: var(--text-3);
    font-variant-numeric: tabular-nums;
    font-family: var(--font-mono);
    white-space: nowrap;
  }
  .find-skipped {
    height: 18px;
    padding: 0 5px;
    border: 1px solid var(--line);
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
    color: var(--accent-text);
  }
  .find-sep {
    width: 1px;
    height: 16px;
    background: var(--line);
    margin: 0 3px;
    flex: 0 1 1px;
  }
  .tl-spacer {
    flex: 1;
  }

  @media (max-width: 1400px) {
    /* 1360 默认窗口：时间码各让 6px 给字幕文本 */
    .thead,
    .row {
      grid-template-columns: var(--cue-margin-w) 78px 78px 46px minmax(0, 1fr) 40px;
    }
  }

  @media (max-width: 1220px) {
    .thead,
    .row {
      grid-template-columns: var(--cue-margin-w) 72px 72px 44px minmax(0, 1fr) 34px;
    }
    .c-t,
    .c-dur {
      padding-left: var(--sp-2);
    }
    .c-text {
      padding-left: 6px;
    }
    .c-acts {
      padding-right: 2px;
    }
  }

  /* 查找栏在 680/540 宽下要留在一行：隐藏「Aa」与分隔线，输入框可收缩。
     折行会把表格再吃掉一行高度，关闭按钮也会单独掉到第二行。
     （2026-11-24 随表格一起搬进来：这些规则只作用于本组件里的节点。） */
  @media (max-width: 900px) {
    /* 紧凑模式：表格保底 200px、最多 300px（虚拟列表自己滚），
       让画面 / 波形 / 表格能整屏纵向滚动。规则从父组件搬回来——
       scoped 样式跨不过组件边界，写在外面从来没生效。 */
    .table-area {
      flex: 0 0 auto;
      height: clamp(200px, 52vh, 300px);
      margin: 4px var(--sp-4) var(--sp-4);
    }
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
