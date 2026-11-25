<script lang="ts">
  /**
   * 双引擎复核页：两列只读、逐条对照。
   *
   * 对齐与逐字 diff 由服务端 `core.dual_review` 按**当前两份字幕**实时计算。
   * 对齐是纯 1:1：绝不把多条字幕合并成一行，B 多出来的句子一定以独立 `+` 行出现。
   * 页面不维护静态下标映射；**单句采用**只把 B 的文本走统一历史写回核对台
   * （见 `lib/dualReview.svelte.ts` 的 `adoptAltText`），断句与时间轴不合并。
   */
  import Icon from '../components/Icon.svelte';
  import { app, focusRange, jumpToCue, setView, toast } from '../lib/store.svelte';
  import { chooseTarget } from '../lib/transcribeTask.svelte';
  import { mediaUrl } from '../lib/api';
  import { audition, auditionRange, stopAudition } from '../lib/audition.svelte';
  import { mediaUnplayable } from '../lib/videoFallback';
  import {
    adoptAltText,
    altEngineLabel,
    altParamsLabel,
    altIsImported,
    deleteAltReview,
    dual,
    importAltReview,
    loadAltDiff,
    refreshAltReview,
    replacePrimaryWithAlt,
    setDualSort,
    setIgnorePunct,
  } from '../lib/dualReview.svelte';
  import { tcShort } from '../lib/time';
  import { recallScroll, rememberScroll } from '../lib/scrollMemory';
  import type { DualRow } from '../lib/api';

  let moreOpen = $state(false);
  /** 对照表的滚动容器：去核对台看完一句再回来要停在同一句，而不是回到第 0 行。 */
  let listEl = $state<HTMLDivElement | null>(null);

  // 行内试听与核对台用同一份流：有代理走代理（Chromium 解不开 MKV / HEVC）。
  const mediaSrc = $derived(
    app.media ? mediaUrl(app.media.id, Boolean(app.media.proxy_ready), app.media.proxy_version) : '',
  );

  const filteredRows = $derived(
    dual.onlyDiff ? dual.rows.filter((row) => row.kind !== 'same') : dual.rows,
  );
  /**
   * 呈现顺序。`ratio-asc` 把相似度最低的排在最前——专名听错 / 整句幻觉这类
   * 差异的 ratio 往往接近 0，在 100+ 行的时间序里根本看不到。
   * 只重排呈现，不动 `a_indices` / `b_indices`：「采用 B」写的仍是那一行。
   */
  const rows = $derived(
    dual.sort === 'ratio-asc'
      ? [...filteredRows].sort((a, b) => {
          // 只有 diff 行有「两份文本都在」的可比性；only_a / only_b 的 ratio
          // 恒为 0，直接按 ratio 排会把它们全堆到最上面、把真正的替换挤走。
          const rank = (row: (typeof filteredRows)[number]) =>
            row.kind === 'diff' ? (row.ratio < CHAR_HIGHLIGHT_MIN_RATIO ? 0 : 1) : 2;
          return rank(a) - rank(b) || a.ratio - b.ratio || a.start - b.start;
        })
      : filteredRows,
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
    const when = at ? `${altIsImported() ? '导入于' : '生成于'} ${at}` : '';
    return [name, when].filter(Boolean).join(' · ');
  });

  /** 空态 CTA：去转写页时顺手把产出切到「第二版」，回来只剩选引擎和范围。 */
  function goTranscribe(): void {
    if (app.cues.length) chooseTarget('alt');
    setView('transcribe');
  }

  async function importB() {
    moreOpen = false;
    await importAltReview();
  }

  $effect(() => {
    void app.connected;
    void app.media?.id;
    void app.cuesRevision;
    if (app.connected) void loadAltDiff();
  });

  /** 一行的稳定 key：A/B 的全局序号组合，两列对齐后不会变。 */
  function rowKey(row: DualRow): string {
    return `${row.a_indices.join('-')}:${row.b_indices.join('-')}`;
  }

  /**
   * 滚动位置按「哪份 B + 哪个过滤条件」分别记：换了第二版或切「只看差异」，
   * 行集合就变了，沿用旧偏移只会停在无关的位置。
   */
  const listKey = $derived(
    `dual:${dual.mediaId}:${dual.createdAt}:${dual.onlyDiff ? 'diff' : 'all'}:${
      dual.ignorePunct ? 'punct' : 'strict'
    }:${dual.sort}`,
  );
  let restoredKey = '';

  $effect(() => {
    const key = listKey;
    if (!listEl || !dual.rows.length || restoredKey === key) return;
    restoredKey = key;
    const target = recallScroll(key);
    const apply = () => {
      if (!listEl) return;
      listEl.scrollTop = target;
      rememberScroll(key, listEl.scrollTop);
    };
    apply();
    // 行高首帧后才量稳（content-visibility），第二帧再对齐一次。
    requestAnimationFrame(apply);
  });

  function onListScroll() {
    if (listEl) rememberScroll(listKey, listEl.scrollTop);
  }

  // 离开这一页必须收掉试听：内嵌媒体元素不在界面上，不能留后台声音。
  $effect(() => () => stopAudition());

  function goto(row: DualRow) {
    const index = row.a_indices[0];
    if (index === undefined) {
      toast('这一行只有第二版有，先在核对台补上对应句子再定位', 'warn');
      return;
    }
    dual.anchor = rowKey(row);
    setView('review');
    jumpToCue(index, { seek: false });
    focusRange(row.start, row.end);
  }

  /** 行内试听：只播这一行的时间窗（A 的入出点），再点一次停。 */
  function auditionRow(row: DualRow) {
    auditionRange(rowKey(row), row.start, row.end, mediaSrc, {
      unplayable: mediaUnplayable(app.media),
    });
  }

  /**
   * 采用 B 句：只把文本写回核对台的同一条字幕。
   *
   * 时间轴保持核对台当前值——两套断句的时间不能混着改，否则时间码会悄悄漂移。
   * 一步统一历史、带 label、⌘Z 一次撤回（`adoptAltText` 走的是 `updateCue`）。
   */
  async function adopt(row: DualRow) {
    const index = row.a_indices[0];
    if (index === undefined) {
      toast('这一行只有第二版有，先在核对台插入对应句子再采用', 'warn');
      return;
    }
    if (dual.adopting >= 0) return;
    if (await adoptAltText(index, row.b_text)) {
      toast(`已采用第二版：第 ${index + 1} 条（⌘Z 可撤回）`);
    }
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
   * 反而盖住了真正的差异。相似度低于这个阈值就不再逐字染色。
   *
   * 但**完全不着色也是错的**：专名被听错、整句幻觉这两类最该被看见的差异，
   * 相似度恰恰接近 0（实测 `だーてん` vs `当店、魔族` 是 0.000），
   * 整行只留一个 `~` 等于把它藏起来。所以低相似度改成「整行短语高亮」：
   * 不做逐字着色，而是把 B 里「A 完全没有的连续片段」标成 ins，反之标成 del，
   * 并给这一行打「整句不同」徽标——既保持“别把整行染红”的原意，
   * 又让 0% 相似度的替换一眼可辨。
   */
  const CHAR_HIGHLIGHT_MIN_RATIO = 0.35;

  /** 这一行是不是「相似度低到不适合逐字高亮」，需要对侧做整段短语标记。 */
  function isLowSimilarity(row: (typeof dual.rows)[number]): boolean {
    return Boolean(row.char_ops) && row.ratio < CHAR_HIGHLIGHT_MIN_RATIO;
  }

  /**
   * 低相似度行的短语级标记：把**对侧完全没有**的连续片段挑出来。
   *
   * 与逐字 diff 的区别是“取舍”：逐字 diff 把每次替换都拆成 del+ins，
   * 一行能染十几段；这里先把相邻的同类片段合并成一段，再整段标出来。
   *
   * 不做「最短长度」过滤：整句被替换时 A 侧可能只剩一个字（`…` vs `少し顔が赤いね`），
   * 那一个字恰恰就是该被看见的差异，按长度丢掉等于又把它藏起来。
   */
  function phraseOps(
    row: (typeof dual.rows)[number],
    side: 'a' | 'b',
  ): { op: string; text: string }[] {
    const ops = row.char_ops ?? [];
    // 这一侧「对侧没有」的片段：A 列是 del，B 列是 ins。
    const want = side === 'a' ? 'del' : 'ins';
    const out: { op: string; text: string }[] = [];
    let buffer = '';
    const flush = () => {
      if (!buffer) return;
      out.push({ op: want, text: buffer });
      buffer = '';
    };
    for (const op of ops) {
      if (op.op === want) {
        buffer += op.text;
      } else if (op.op === 'eq') {
        flush();
        out.push({ op: 'eq', text: op.text });
      } else {
        // 对侧独有的片段在这一侧没有字，忽略（它只影响另一列）。
        continue;
      }
    }
    flush();
    return out.length ? out : [{ op: 'eq', text: side === 'a' ? row.a_text : row.b_text }];
  }

  function opText(row: (typeof dual.rows)[number], side: 'a' | 'b'): { op: string; text: string }[] {
    if (!row.char_ops) {
      return [{ op: 'eq', text: side === 'a' ? row.a_text : row.b_text }];
    }
    if (row.ratio < CHAR_HIGHLIGHT_MIN_RATIO) return phraseOps(row, side);
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
                <button class="menu-item" role="menuitem" onclick={importB}>导入字幕替换 B 版…</button>
                <button class="menu-item danger" role="menuitem" onclick={discard}>丢弃第二版</button>
              </div>
            {/if}
          </div>
        {:else}
          <button class="btn ghost" onclick={goTranscribe}>去转写页</button>
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
          {#if dual.ignorePunct && (stats?.punct_only ?? 0) > 0}
            <span
              class="punct-note"
              title="这些行两边只有标点 / 空白不同（、。…「」），是排版分歧不是听写分歧；取消「忽略标点与空格」可以逐条看"
            >已忽略 {stats?.punct_only} 处仅标点差异</span>
          {/if}
        </div>
        <span
          class="legend"
          title="逐条配对后，这一行内只出现在 A / 只出现在 B 的字。A 列只读，不会被改动；整列覆盖只有右侧按钮才会执行。"
        >
          <i class="sw del"></i>本行 A 独有
          <i class="sw ins"></i>本行 B 独有
        </span>
        <div class="head-end">
          <label
            class="chk"
            title="两个引擎对同一句的句读常常不同（、。，…！？「」『』 与空格）。勾选时这些不算文本差异；取消就回到逐字严格比对"
          >
            <input
              type="checkbox"
              checked={dual.ignorePunct}
              onchange={(e) => void setIgnorePunct(e.currentTarget.checked)}
            />
            忽略标点与空格
          </label>
          <label class="chk">
            <input type="checkbox" bind:checked={dual.onlyDiff} />
            只看差异
          </label>
          <label
            class="chk"
            title="相似度最低的排最前：专名被听错、整句幻觉这类差异的相似度往往接近 0，按时间序很容易被埋掉"
          >
            <input
              type="checkbox"
              checked={dual.sort === 'ratio-asc'}
              onchange={(e) => setDualSort(e.currentTarget.checked ? 'ratio-asc' : 'time')}
            />
            按差异大小排
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
        在转写页把产出选成「第二版」，换一个引擎跑同一段（整片或某一章区间都行），
        结果只写这里、核对台一个字不动；也可以把已经做好的另一版字幕直接导入。
        第二版按当前媒体自动保存，切走再切回来仍然在。
      </div>
      <div class="ea">
        <button class="btn primary" onclick={goTranscribe}>去转写页生成第二版</button>
        <button class="btn ghost" onclick={importB}>导入已有字幕作为 B 版…</button>
      </div>
    </div>
  {:else}
    {#if dual.error}
      <div class="note err"><Icon name="warn" size={11} /><span>{dual.error}</span></div>
    {/if}

    <!-- 对照表 = 一张台本纸（与核对台字幕表同一套原语）：表头是 11px 标签，
         行是 30px 起的对照内容；外框留给页面 16px 页边。 -->
    <div class="sheet">
    <div class="cols">
      <span class="c-time">时间码</span>
      <span class="c-side">A · 核对台当前版本（只读）</span>
      <span class="c-mark">对照</span>
      <span class="c-side">B · {altEngineLabel()}（只读参考）</span>
      <span class="c-act">听 / 采纳</span>
    </div>

    {#if !rows.length}
      <div class="blank small">
        <Icon name="check" size={20} />
        <div class="et">没有差异</div>
        <div class="es">两份字幕逐条一致；取消「只看差异」可以看全量对照。</div>
      </div>
    {:else}
      <div class="list" bind:this={listEl} onscroll={onListScroll}>
        {#each rows as row (rowKey(row))}
          <div
            class="row kind-{row.kind}"
            class:anchor={dual.anchor === rowKey(row)}
          >
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
                class:low={isLowSimilarity(row)}
                title={row.kind === 'same'
                  ? '文本一致'
                  : row.kind === 'diff'
                    ? isLowSimilarity(row)
                      ? `文本几乎完全不同（相似度 ${(row.ratio * 100).toFixed(0)}%）：专名听错或整句幻觉多落在这一档，彩色片段是对侧完全没有的字`
                      : `文本不同（相似度 ${(row.ratio * 100).toFixed(0)}%）`
                    : row.kind === 'only_a'
                      ? '仅 A 有（B 漏句）'
                      : '仅 B 有（A 漏句）'}
              >
                {row.kind === 'same' ? '=' : row.kind === 'diff' ? '~' : row.kind === 'only_a' ? '−' : '+'}
              </span>

            </div>

            <div class="c-side b">
              {#if isLowSimilarity(row)}
                <span class="low-tag" title="相似度低于逐字高亮阈值（{CHAR_HIGHLIGHT_MIN_RATIO}）：彩色片段是对侧完全没有的字，多半是专名听错或整句幻觉">整句不同 · 看彩色片段</span>
              {/if}
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

            <div class="c-act">
              {#if row.kind === 'diff'}
                <button
                  class="act-btn"
                  class:on={audition.key === rowKey(row)}
                  onclick={() => auditionRow(row)}
                  title={audition.key === rowKey(row) ? '停止试听' : '试听这一句（A 的入出点，原声）'}
                  aria-label={audition.key === rowKey(row) ? '停止试听这一句' : '试听这一句'}
                >
                  <Icon name={audition.key === rowKey(row) ? 'pause' : 'play'} size={10} />
                  <span class="act-t">{audition.key === rowKey(row) ? '停止' : '试听'}</span>
                </button>
                <button
                  class="act-btn adopt"
                  onclick={() => void adopt(row)}
                  disabled={dual.adopting >= 0}
                  title="把 A 这一句换成 B 的措辞（只换文本，时间轴保持核对台；一步历史，⌘Z 可撤回）"
                  aria-label={`采用第二句：第 ${(row.a_indices[0] ?? 0) + 1} 条`}
                >
                  <Icon name="check" size={10} />
                  <span class="act-t">{dual.adopting === row.a_indices[0] ? '采用中…' : '采用 B'}</span>
                </button>
              {/if}
            </div>
          </div>
        {/each}
      </div>
    {/if}
    </div>
  {/if}
</div>

<style>
  .dual {
    flex: 1;
    min-height: 0;
    display: flex;
    flex-direction: column;
    background: var(--canvas);
  }
  /* 页头与核对台/转写页同一个 16px 页边与同一条发丝线：切页时标题不跳。 */
  .dual-head {
    flex: 0 0 auto;
    padding: var(--sp-4) var(--sp-4) var(--sp-3);
    border-bottom: 1px solid var(--line);
    background: var(--canvas);
  }
  /* 对照表：台本纸原语（纸白 + 1px --rule + 7px 圆角），左右各留 16px。 */
  .sheet {
    flex: 1;
    min-height: 0;
    display: flex;
    flex-direction: column;
    margin: var(--sp-3) var(--sp-4) var(--sp-4);
    background: var(--surface);
    border: 1px solid var(--rule);
    border-radius: var(--rad-card);
    overflow: hidden;
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
  /* 与 PageHeader / .aiw-title 同一套标题规格（22 / 30 / 600 / -0.015em）。
     这一页原来自己写了 20px 且没有 line-height，是四页里唯一的例外。 */
  h1 {
    margin: 0;
    font-size: var(--fs-display);
    line-height: var(--lh-display);
    font-weight: 600;
    letter-spacing: -0.015em;
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
    background: var(--raise);
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
    justify-content: space-between;
    gap: var(--sp-1);
    min-width: 94px;
    font-size: 12px;
    line-height: 22px;
    padding: 0 var(--sp-2);
    border-radius: 6px;
    background: var(--fill);
    color: var(--text-2);
    white-space: nowrap;
    font-variant-numeric: tabular-nums;
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
  .head-end {
    display: inline-flex;
    align-items: center;
    gap: var(--sp-3);
    margin-left: auto;
    min-width: 0;
    flex-wrap: wrap;
    justify-content: flex-end;
  }
  .legend {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    margin-left: 2px;
    padding-left: var(--sp-3);
    border-left: 1px solid var(--separator-soft);
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
  /* 覆盖是危险动作，但也是这一页唯一的整列写回入口：给它实心边界，
     不再和旁边那些 ghost 链接挤成同一层。 */
  .btn.ghost.overwrite {
    white-space: nowrap;
    height: 26px;
    padding: 0 10px;
    background: var(--raise);
    border-color: color-mix(in srgb, var(--danger) 34%, var(--separator));
    color: var(--danger);
    font-weight: 500;
    box-shadow: var(--shadow-btn);
  }
  .btn.ghost.overwrite:hover:not(:disabled) {
    background: var(--danger-soft);
    border-color: var(--danger);
    color: var(--danger);
  }
  /* 第 5 列是行内「试听 / 采用 B」：固定 118px，两枚 20px 高的轻按钮并排。
     宽度是按 11px 字号量出来的（试听 ≈47 + 采用 B ≈59 + gap 4），
     不再从文本列里抠——A/B 各留 minmax(0,1fr)，窗口变小先压文字换行。 */
  .cols,
  .row {
    display: grid;
    grid-template-columns: 92px minmax(0, 1fr) 46px minmax(0, 1fr) 118px;
    gap: 10px;
    align-items: start;
    padding: 6px 14px;
  }
  .cols {
    position: sticky;
    top: 0;
    z-index: 1;
    font-size: var(--fs-label);
    letter-spacing: 0.06em;
    text-transform: uppercase;
    color: var(--ink-3);
    background: var(--raise);
    border-bottom: 1px solid var(--line);
    padding-top: 7px;
    padding-bottom: 7px;
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
  /* 从核对台回来时标出「刚才看的就是这一句」：位置恢复之外再给一个视觉锚点。 */
  .row.anchor {
    background: color-mix(in srgb, var(--accent) 8%, transparent);
    box-shadow: inset 2px 0 0 var(--accent);
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
    font-family: var(--font-mono);
    font-size: 12px;
    line-height: 17px;
    font-weight: 600;
    letter-spacing: -0.01em;
    font-variant-numeric: tabular-nums;
  }
  .idx {
    font-size: 10.5px;
    line-height: 14px;
    font-weight: 400;
    color: color-mix(in srgb, var(--text-3) 66%, transparent);
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
  /* 「整句不同」提示挂在 B 列文本上方：低相似度行的逐字高亮已关掉，
     需要一个文字提示解释「为什么这一行有五颜六色的片段」。 */
  .low-tag {
    display: inline-block;
    margin-bottom: 2px;
    padding: 0 5px;
    height: 15px;
    line-height: 15px;
    border-radius: 3px;
    font-size: 10px;
    font-weight: 600;
    letter-spacing: 0.02em;
    color: color-mix(in srgb, var(--danger) 88%, var(--text));
    background: color-mix(in srgb, var(--danger) 12%, transparent);
    border: 1px solid color-mix(in srgb, var(--danger) 26%, transparent);
  }
  /* 低相似度的对照标记加一圈描边，扫视时不至于和普通 ~ 混掉。 */
  .mark.low {
    outline: 1px solid color-mix(in srgb, var(--danger) 45%, transparent);
    outline-offset: 1px;
    font-weight: 700;
  }
  .c-act {
    display: flex;
    align-items: center;
    justify-content: flex-end;
    gap: var(--sp-1);
    min-width: 0;
  }
  /* 行内动作刻意做小：它们服务于「这一句」，不该比正文更抢眼。 */
  .act-btn {
    appearance: none;
    height: 22px;
    padding: 0 7px;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    gap: 3px;
    border: 1px solid var(--separator-soft);
    border-radius: 5px;
    background: var(--raise);
    color: var(--text-2);
    font: inherit;
    font-size: 11.5px;
    line-height: 1;
    white-space: nowrap;
    cursor: pointer;
    transition: background var(--dur) var(--ease), color var(--dur) var(--ease),
      border-color var(--dur) var(--ease);
  }
  .act-btn:hover:not(:disabled) {
    background: var(--accent-soft);
    border-color: var(--accent-line);
    color: var(--accent);
  }
  .act-btn.on {
    background: var(--accent-soft);
    border-color: var(--accent-line);
    color: var(--accent);
  }
  .act-btn:disabled {
    opacity: 0.45;
  }
  .act-btn.adopt {
    color: var(--text);
    font-weight: 500;
  }
  /* 「已忽略 N 处仅标点差异」：解释性文字，跟 4 个统计片同一行但明显更淡。 */
  .punct-note {
    font-size: 11px;
    line-height: 22px;
    color: var(--text-3);
    white-space: nowrap;
  }
  .mark {
    width: 20px;
    height: 20px;
    border-radius: 5px;
    display: grid;
    place-items: center;
    font-family: var(--font-mono);
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
    color: color-mix(in srgb, var(--text-3) 55%, transparent);
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
      grid-template-columns: 74px minmax(0, 1fr) 34px minmax(0, 1fr) 26px;
      gap: 6px;
      padding: 6px 10px;
    }
    /* 紧凑模式只留图标（title / aria-label 仍在），把宽度还给文本列。 */
    .c-act {
      flex-direction: column;
      gap: 3px;
    }
    /* 26px 装不下「听 / 采纳」，表头这一格整格收起（按钮自己的 aria-label 仍在）。 */
    .cols .c-act {
      display: none;
    }
    .act-btn {
      width: 24px;
      padding: 0;
    }
    .act-t {
      display: none;
    }
    .source-line {
      display: none;
    }
    /* 标题不再随窄屏缩小：22px 是与其余页共用的规格（G4），
       紧凑模式下这页的标题行本来就换行放下了，不需要靠减字号让位。 */
    h1 {
      font-size: var(--fs-display);
    }
  }
</style>
