<script lang="ts">
  /**
   * 双引擎复核页：两列只读、逐条对照。
   *
   * 对齐与逐字 diff 由服务端 `core.dual_review` 按**当前两份字幕**实时计算。
   * 对齐是纯 1:1：绝不把多条字幕合并成一行，B 多出来的句子一定以独立 `+` 行出现。
   * 页面不维护静态下标映射，所有编辑仍回核对台。
   */
  import Icon from '../components/Icon.svelte';
  import { app, focusRange, jumpToCue, setView, toast } from '../lib/store.svelte';
  import {
    altEngineLabel,
    altParamsLabel,
    deleteAltReview,
    dual,
    loadAltDiff,
    refreshAltReview,
    replacePrimaryWithAlt,
  } from '../lib/dualReview.svelte';
  import { tcShort } from '../lib/time';

  let moreOpen = $state(false);

  const rows = $derived(
    dual.onlyDiff ? dual.rows.filter((row) => row.kind !== 'same') : dual.rows,
  );
  const stats = $derived(dual.stats);
  const aCount = $derived(stats?.a_count ?? app.cues.length);
  const bCount = $derived(stats?.b_count ?? dual.count);
  const countsDiffer = $derived(dual.exists && aCount !== bCount);
  const sourceLabel = $derived.by(() => {
    const name = String(dual.source?.name ?? '').trim();
    const at = dual.createdAt
      ? new Date(dual.createdAt * 1000).toLocaleString()
      : '';
    return [name, at ? `生成于 ${at}` : ''].filter(Boolean).join(' · ');
  });

  $effect(() => {
    void app.connected;
    void app.media?.id;
    void app.cuesRevision;
    if (app.connected) void loadAltDiff();
  });

  function goto(row: { a_indices: number[]; start: number; end: number }) {
    const index = row.a_indices[0];
    if (index === undefined) {
      toast('这一行只有第二版有，先在核对台补上对应句子再定位', 'warn');
      return;
    }
    setView('review');
    jumpToCue(index, { seek: false });
    focusRange(row.start, row.end);
  }

  async function refresh() {
    moreOpen = false;
    await loadAltDiff();
  }

  async function discard() {
    moreOpen = false;
    if (!window.confirm('丢弃第二版字幕？\n\n核对台不会改动；下次切回这部片也不会再出现。')) return;
    if (await deleteAltReview()) await refreshAltReview();
  }

  async function replaceAll() {
    if (!window.confirm(
      '用第二版整列覆盖核对台？\n\n' +
        `核对台当前 ${app.cues.length} 条会被 ${dual.count} 条替换；\n` +
        '这一步只压一次历史，⌘Z 可以整批退回。\n覆盖成功后第二版会被清空。',
    )) return;
    if (await replacePrimaryWithAlt(true)) {
      setView('review');
    }
  }

  /**
   * 逐字高亮只在两份文本“确实像同一句”时才有意义。
   *
   * 两个引擎断句不同时，1:1 配对可能把 A 的整句和 B 的另半句放在一行；
   * 此时逐字 diff 会把大半行都染成红色，看起来像“这些字要被删掉”，
   * 反而盖住了真正的差异。相似度低于这个阈值就只保留整行 `~`，不做逐字染色。
   */
  const CHAR_HIGHLIGHT_MIN_RATIO = 0.35;

  function opText(row: (typeof dual.rows)[number], side: 'a' | 'b'): { op: string; text: string }[] {
    if (!row.char_ops || row.ratio < CHAR_HIGHLIGHT_MIN_RATIO) {
      return [{ op: 'eq', text: side === 'a' ? row.a_text : row.b_text }];
    }
    return row.char_ops
      .filter((op) => (side === 'a' ? op.op !== 'ins' : op.op !== 'del'))
      .map((op) => ({ op: op.op, text: op.text }));
  }
</script>

<div class="dual">
  <header class="dual-head">
    <div class="head-top">
      <div class="head-title">
        <h1>双引擎复核</h1>
        {#if dual.exists}
          <div class="versions">
            <span class="ver a"><b>A</b> 核对台 <i>{aCount}</i> 条</span>
            <span class="arrow" aria-hidden="true">⇄</span>
            <span class="ver b" title={altParamsLabel()}>
              <b>B</b> {altEngineLabel()} <i>{bCount}</i> 条
            </span>
            {#if countsDiffer}
              <span
                class="count-note"
                title="两个引擎的断句本来就可能不同；复核页按逐条时间对齐，B 多出的句子会以 + 行单独显示"
              >行数不同</span>
            {/if}
          </div>
        {/if}
      </div>

      <div class="head-actions">
        {#if dual.exists}
          <button class="icon-btn" onclick={refresh} title="刷新对照" aria-label="刷新对照">
            <Icon name="refresh" size={13} />
          </button>
          <div class="more-wrap">
            <button
              class="icon-btn more-btn"
              onclick={() => (moreOpen = !moreOpen)}
              title="更多操作"
              aria-label="更多操作"
              aria-expanded={moreOpen}
            >⋯</button>
            {#if moreOpen}
              <button class="menu-backdrop" aria-label="关闭菜单" onclick={() => (moreOpen = false)}></button>
              <div class="menu" role="menu">
                <button class="menu-item" role="menuitem" onclick={refresh}>刷新对照</button>
                <button class="menu-item danger" role="menuitem" onclick={discard}>丢弃第二版</button>
              </div>
            {/if}
          </div>
        {:else}
          <button class="btn ghost" onclick={() => setView('transcribe')}>去转写页</button>
        {/if}
      </div>
    </div>

    {#if dual.exists && sourceLabel}
      <div class="source-line" title={String(dual.source?.path ?? '')}>{sourceLabel}</div>
    {/if}

    {#if dual.exists}
      <div class="head-stats">
        <div class="stats">
          <span class="chip same">= 一致 <b>{stats?.same ?? 0}</b></span>
          <span class="chip diff">~ 文本不同 <b>{stats?.diff ?? 0}</b></span>
          <span class="chip only-a">− 仅 A <b>{stats?.only_a ?? 0}</b></span>
          <span class="chip only-b">+ 仅 B <b>{stats?.only_b ?? 0}</b></span>
        </div>
        <span
          class="legend"
          title="逐条配对后，这一行内只出现在 A / 只出现在 B 的字。A 列只读，不会被改动；整列覆盖只有右侧按钮才会执行。"
        >
          <i class="sw del"></i>本行 A 独有
          <i class="sw ins"></i>本行 B 独有
        </span>
        <div class="spacer"></div>
        <label class="chk">
          <input type="checkbox" bind:checked={dual.onlyDiff} />
          只看差异
        </label>
        <button
          class="btn ghost danger overwrite"
          onclick={replaceAll}
          disabled={dual.loading || dual.replacing}
          title="整列用第二版覆盖核对台；只压一步历史，⌘Z 可整批退回"
        >
          {dual.replacing ? '覆盖中…' : '用 B 覆盖核对台…'}
        </button>
      </div>
    {/if}
  </header>

  {#if dual.loading && !dual.rows.length}
    <div class="blank"><div class="et">正在对齐两份字幕…</div></div>
  {:else if !dual.exists}
    <div class="blank">
      <span class="blank-icon"><Icon name="rows" size={24} /></span>
      <div class="et">还没有第二版字幕</div>
      <div class="es">
        在转写页换一个引擎（或同一引擎换一组参数）再整片转一次，结果选「放进双引擎复核」即可。
        第二版会按当前媒体自动保存在工作草稿目录，切走再切回来仍然在。
      </div>
      <div class="ea">
        <button class="btn primary" onclick={() => setView('transcribe')}>去转写页</button>
      </div>
    </div>
  {:else}
    {#if dual.error}
      <div class="note err"><Icon name="warn" size={11} /><span>{dual.error}</span></div>
    {/if}

    <div class="cols">
      <span class="c-time">时间码</span>
      <span class="c-side">A · 核对台当前版本（只读）</span>
      <span class="c-mark">对照</span>
      <span class="c-side">B · {altEngineLabel()}（只读参考）</span>
    </div>

    {#if !rows.length}
      <div class="blank small">
        <Icon name="check" size={20} />
        <div class="et">没有差异</div>
        <div class="es">两份字幕逐条一致；取消「只看差异」可以看全量对照。</div>
      </div>
    {:else}
      <div class="list">
        {#each rows as row (`${row.a_indices.join('-')}:${row.b_indices.join('-')}`)}
          <div class="row kind-{row.kind}">
            <button class="c-time" onclick={() => goto(row)} title={row.a_indices.length ? '回到核对台定位这一句' : 'B 独有的句子'}>
              <span class="tc">{tcShort(row.start)}</span>
              <span class="idx">
                {#if row.a_indices.length}#{row.a_indices[0] + 1}{/if}
                {#if row.b_indices.length}B#{row.b_indices[0] + 1}{/if}
              </span>
            </button>

            <div class="c-side a">
              {#if row.a_indices.length}
                {#if row.char_ops}
                  {#each opText(row, 'a') as op}
                    {#if op.op === 'del'}<mark class="del" title="只在 A 中出现（第二版这里没有对应文字）">{op.text}</mark>{:else}{op.text}{/if}
                  {/each}
                {:else}
                  {row.a_text}
                {/if}
              {:else}
                <span class="placeholder">—</span>
              {/if}
            </div>

            <div class="c-mark">
              <span
                class="mark"
                class:same={row.kind === 'same'}
                class:diff={row.kind === 'diff'}
                class:only-a={row.kind === 'only_a'}
                class:only-b={row.kind === 'only_b'}
                title={row.kind === 'same'
                  ? '文本一致'
                  : row.kind === 'diff'
                    ? `文本不同（相似度 ${(row.ratio * 100).toFixed(0)}%）`
                    : row.kind === 'only_a'
                      ? '仅 A 有（B 漏句）'
                      : '仅 B 有（A 漏句）'}
              >
                {row.kind === 'same' ? '=' : row.kind === 'diff' ? '~' : row.kind === 'only_a' ? '−' : '+'}
              </span>
            </div>

            <div class="c-side b">
              {#if row.b_indices.length}
                {#if row.char_ops}
                  {#each opText(row, 'b') as op}
                    {#if op.op === 'ins'}<mark class="ins" title="只在第二版中出现">{op.text}</mark>{:else}{op.text}{/if}
                  {/each}
                {:else}
                  {row.b_text}
                {/if}
              {:else}
                <span class="placeholder">—</span>
              {/if}
            </div>
          </div>
        {/each}
      </div>
    {/if}
  {/if}
</div>

<style>
  .dual {
    flex: 1;
    min-height: 0;
    display: flex;
    flex-direction: column;
    background: var(--paper);
  }
  .dual-head {
    flex: 0 0 auto;
    padding: var(--sp-3) 14px var(--sp-2);
    border-bottom: 1px solid var(--separator);
    background: var(--paper);
  }
  .head-top {
    display: flex;
    align-items: center;
    gap: var(--sp-3);
    min-width: 0;
  }
  .head-title {
    flex: 1;
    min-width: 0;
    display: flex;
    align-items: center;
    gap: 14px;
    flex-wrap: wrap;
  }
  h1 {
    margin: 0;
    font-size: 20px;
    font-weight: 600;
    letter-spacing: -0.01em;
    white-space: nowrap;
  }
  .versions {
    display: flex;
    align-items: center;
    gap: 7px;
    min-width: 0;
    flex-wrap: wrap;
  }
  .ver {
    display: inline-flex;
    align-items: baseline;
    gap: var(--sp-1);
    font-size: 12px;
    color: var(--text-2);
    white-space: nowrap;
  }
  .ver b {
    font-size: 11px;
    font-weight: 700;
    color: var(--text-3);
  }
  .ver i {
    font-style: normal;
    font-size: 13px;
    font-weight: 600;
    color: var(--text);
    font-variant-numeric: tabular-nums;
  }
  .arrow {
    color: var(--text-3);
    font-size: 12px;
  }
  .count-note {
    font-size: 11px;
    line-height: 17px;
    padding: 0 6px;
    border-radius: 999px;
    background: var(--fill);
    color: var(--text-3);
    white-space: nowrap;
  }
  .head-actions {
    flex: 0 0 auto;
    display: flex;
    align-items: center;
    gap: var(--sp-1);
  }
  .icon-btn {
    appearance: none;
    border: 0;
    background: transparent;
    color: var(--text-2);
    width: 28px;
    height: 28px;
    border-radius: 6px;
    display: grid;
    place-items: center;
    font: inherit;
    font-size: 16px;
    cursor: pointer;
  }
  .icon-btn:hover {
    background: var(--fill);
    color: var(--text);
  }
  .more-wrap {
    position: relative;
  }
  .more-btn {
    line-height: 1;
    padding-bottom: 5px;
  }
  .menu-backdrop {
    position: fixed;
    inset: 0;
    z-index: 20;
    border: 0;
    background: transparent;
    cursor: default;
  }
  .menu {
    position: absolute;
    z-index: 21;
    top: 32px;
    right: 0;
    min-width: 150px;
    padding: var(--sp-1);
    border: 1px solid var(--separator);
    border-radius: 8px;
    background: var(--bg-content);
    box-shadow: var(--shadow-pop);
    display: flex;
    flex-direction: column;
    gap: 1px;
  }
  .menu-item {
    appearance: none;
    border: 0;
    background: transparent;
    color: var(--text);
    font: inherit;
    font-size: 12px;
    text-align: left;
    padding: 6px var(--sp-2);
    border-radius: 5px;
    cursor: pointer;
    white-space: nowrap;
  }
  .menu-item:hover {
    background: var(--fill);
  }
  .menu-item.danger {
    color: var(--danger);
  }
  .source-line {
    margin-top: 3px;
    font-size: 11px;
    line-height: 16px;
    color: var(--text-3);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .head-stats {
    display: flex;
    align-items: center;
    gap: var(--sp-2);
    margin-top: 7px;
    min-width: 0;
    flex-wrap: wrap;
  }
  .stats {
    display: flex;
    align-items: center;
    gap: 6px;
    flex-wrap: wrap;
  }
  .chip {
    display: inline-flex;
    align-items: baseline;
    gap: var(--sp-1);
    font-size: 12px;
    line-height: 22px;
    padding: 0 var(--sp-2);
    border-radius: 6px;
    background: var(--fill);
    color: var(--text-2);
    white-space: nowrap;
  }
  .chip b {
    font-size: 12px;
    font-weight: 600;
    color: var(--text);
    font-variant-numeric: tabular-nums;
  }
  .chip.same b {
    color: var(--success);
  }
  .chip.diff b {
    color: var(--warn);
  }
  .chip.only-a b {
    color: var(--danger);
  }
  .chip.only-b b {
    color: var(--accent);
  }
  .spacer {
    flex: 1;
  }
  .legend {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    font-size: 11px;
    line-height: 22px;
    color: var(--text-3);
    white-space: nowrap;
  }
  .legend .sw {
    width: 9px;
    height: 9px;
    border-radius: 2px;
    display: inline-block;
  }
  .legend .sw.del {
    background: color-mix(in srgb, var(--danger) 20%, transparent);
  }
  .legend .sw.ins {
    background: color-mix(in srgb, var(--success) 24%, transparent);
  }
  .legend .sw + .sw {
    margin-left: var(--sp-1);
  }
  .chk {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    font-size: 12px;
    color: var(--text-2);
    cursor: pointer;
    user-select: none;
    white-space: nowrap;
  }
  .overwrite {
    white-space: nowrap;
  }
  .cols,
  .row {
    display: grid;
    grid-template-columns: 92px minmax(0, 1fr) 46px minmax(0, 1fr);
    gap: 10px;
    align-items: start;
    padding: 6px 14px;
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
  .cols .c-mark {
    text-align: center;
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
  .row.kind-only_a {
    background: color-mix(in srgb, var(--danger) 5%, transparent);
  }
  .row.kind-only_b {
    background: color-mix(in srgb, var(--accent) 5%, transparent);
  }
  .c-time {
    display: flex;
    flex-direction: column;
    gap: 1px;
    border: 0;
    background: transparent;
    padding: 0;
    text-align: left;
    cursor: pointer;
    font: inherit;
  }
  .tc {
    color: var(--accent);
    font-family: var(--mono, ui-monospace, SFMono-Regular, Menlo, monospace);
    font-size: 12px;
    font-variant-numeric: tabular-nums;
  }
  .idx {
    font-size: 12px;
    color: var(--text-3);
    font-variant-numeric: tabular-nums;
  }
  .c-side {
    white-space: pre-wrap;
    word-break: break-word;
    min-width: 0;
  }
  .c-side.a {
    color: var(--text);
  }
  .c-side.b {
    color: var(--text-2);
  }
  .c-mark {
    display: grid;
    place-items: center;
  }
  .mark {
    width: 20px;
    height: 20px;
    border-radius: 5px;
    display: grid;
    place-items: center;
    font-family: var(--mono, ui-monospace, SFMono-Regular, Menlo, monospace);
    font-size: 13px;
    font-weight: 700;
    line-height: 1;
  }
  .mark.same {
    color: var(--text-3);
    background: var(--fill);
  }
  .mark.diff {
    color: var(--warn);
    background: var(--warn-soft);
  }
  .mark.only-a {
    color: var(--danger);
    background: var(--danger-soft);
  }
  .mark.only-b {
    color: var(--accent);
    background: var(--accent-soft);
  }
  mark {
    border-radius: 2px;
    padding: 0 1px;
    color: inherit;
  }
  mark.del {
    background: color-mix(in srgb, var(--danger) 18%, transparent);
  }
  mark.ins {
    background: color-mix(in srgb, var(--success) 26%, transparent);
  }
  .placeholder {
    color: var(--text-3);
  }
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
  .blank {
    flex: 1;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 9px;
    padding: var(--sp-10) var(--sp-6);
    text-align: center;
    color: var(--text-2);
  }
  .blank.small {
    padding: var(--sp-8);
    flex: 0 0 auto;
  }
  .blank-icon {
    width: 44px;
    height: 44px;
    border-radius: 10px;
    display: grid;
    place-items: center;
    background: var(--accent-soft);
    color: var(--accent);
    margin-bottom: var(--sp-1);
  }
  .et {
    font-size: 15px;
    font-weight: 600;
    color: var(--text);
  }
  .es {
    font-size: 13px;
    line-height: 1.7;
    max-width: 480px;
  }
  .ea {
    display: flex;
    gap: var(--sp-2);
    margin-top: 6px;
  }
  @media (max-width: 900px) {
    .cols,
    .row {
      grid-template-columns: 74px minmax(0, 1fr) 34px minmax(0, 1fr);
      gap: 6px;
      padding: 6px 10px;
    }
    .source-line {
      display: none;
    }
    h1 {
      font-size: 17px;
    }
  }
</style>
