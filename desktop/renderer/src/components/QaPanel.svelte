<script lang="ts">
  /**
   * 质检待核队列。
   *
   * 用户的实际动作是「逐条试听、逐项确认」，所以这里是一个可勾选的清单，
   * 不是只读列表：
   *
   * - 每条都有复选框，勾上 = 已核对（与转写报告里的三类清单同源）；
   * - 定位真的会跳到核对台并把波形缩放到该区间；
   * - 「补录」会直接对该区间做局部转写，成功后才标记完成；
   * - 处理完自动推进到下一条待核，形成一条不被打断的流水线。
   */
  import Icon from './Icon.svelte';
  import {
    app,
    focusRange,
    qa,
    qaAction,
    refreshQa,
    setView,
    toggleQaPanel,
    toast,
    transcribeRange,
  } from '../lib/store.svelte';
  import { tcShort } from '../lib/time';
  import { cubicOut } from 'svelte/easing';

  /**
   * 浮层从右下角「弹」出来：10px 上移 + 0.985→1 的轻微放大，
   * 比单纯淡入更接近 macOS popover 的手感；收起时反向收回。
   */
  function popIn(_node: HTMLElement, { duration }: { duration: number }) {
    return {
      duration,
      easing: cubicOut,
      css: (t: number) =>
        `opacity:${t};transform:translateY(${(1 - t) * 10}px) scale(${0.985 + 0.015 * t});`,
    };
  }

  function popOut(_node: HTMLElement, { duration }: { duration: number }) {
    return {
      duration,
      easing: cubicOut,
      css: (t: number) =>
        `opacity:${t};transform:translateY(${(1 - t) * 8}px) scale(${0.985 + 0.015 * t});`,
    };
  }

  /**
   * 当前核对表不是转写结果时（导入字幕 / 恢复草稿），媒体同名的质检队列
   * 与这张表已经对不上。服务端会返回 detached 空态，这里再按前端来源兜一层，
   * 避免刷新队列完成前的旧 item 被误点。
   */
  const detached = $derived(
    qa.payload?.detached === true ||
      app.reviewSource?.kind === 'import' ||
      app.reviewSource?.kind === 'draft',
  );
  const detachedReason = $derived.by(() => {
    const fromServer = String(qa.payload?.detached_reason ?? '').trim();
    if (fromServer) return fromServer;
    const name = app.reviewSource?.name || '外部字幕';
    if (app.reviewSource?.kind === 'draft') {
      return `当前核对表来自暂存草稿「${name}」，不与这次转写的质检队列对应。`;
    }
    return `当前核对表来自导入的「${name}」，这次转写的质检队列只对应转写结果。`;
  });
  const detachedSource = $derived(app.reviewSource?.name || '外部字幕');

  const items = $derived<any[]>(detached ? [] : (qa.payload?.items ?? []));
  const statuses = $derived<Record<string, any>>(qa.payload?.statuses ?? {});
  const counts = $derived<any>(qa.payload?.counts ?? {});
  const scanned = $derived<any>(qa.payload?.scanned ?? {});
  const phase = $derived<string>(detached ? 'idle' : (qa.payload?.phase ?? 'idle'));
  /** 动效：系统开启减少动态效果时，面板与列表直接出现。 */
  const motion =
    typeof window === 'undefined' ||
    !window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  // 报告有数字、队列却是空的时候必须说出来，而不是让用户看到「0 条」
  const reportFindings = $derived(
    Number(app.report?.quality?.coverage ?? 0) +
      Number(app.report?.quality?.low_confidence ?? 0),
  );

  let filter = $state<'pending' | 'all' | 'done'>('pending');
  type GroupFilter = 'miss' | 'low' | 'all';
  let group = $state<GroupFilter>('miss');

  const byGroup = $derived<Record<string, number>>(counts.by_group ?? {});
  const groupOf = (item: any): string =>
    item.group ?? (item.kind === 'coverage' ? 'miss' : 'low');
  const missCount = $derived(
    Number(byGroup.miss ?? items.filter((item) => groupOf(item) === 'miss').length),
  );
  const lowCount = $derived(
    Number(byGroup.low ?? items.filter((item) => groupOf(item) === 'low').length),
  );

  const busy = $derived(
    app.job?.status === 'queued' ||
      app.job?.status === 'running' ||
      app.job?.status === 'cancelling',
  );

  function statusOf(id: string): string {
    return statuses[id]?.status ?? 'pending';
  }

  function resolutionOf(id: string): string {
    return statuses[id]?.resolution ?? '';
  }

  const RESOLUTION_LABEL: Record<string, string> = {
    filled: '已补录',
    restored: '已恢复',
    deleted: '已删除',
    kept: '已保留',
    confirmed: '已确认删除',
    'not-speech': '不是台词',
    skipped: '已跳过',
  };

  const KIND_LABEL: Record<string, string> = {
    coverage: '未覆盖空白',
    missed: '切片内为空',
    dropped: '误删待核',
    suspect: '短句待确认',
  };

  /** 待核的排前面；同组按时间。 */
  const ordered = $derived(
    [...items].sort((a, b) => {
      const sa = statusOf(a.id) === 'pending' ? 0 : 1;
      const sb = statusOf(b.id) === 'pending' ? 0 : 1;
      if (sa !== sb) return sa - sb;
      const ga = groupOf(a) === 'miss' ? 0 : 1;
      const gb = groupOf(b) === 'miss' ? 0 : 1;
      if (ga !== gb) return ga - gb;
      return Number(a.start) - Number(b.start);
    }),
  );

  const shown = $derived(
    ordered.filter((item) => {
      if (group !== 'all' && groupOf(item) !== group) return false;
      const st = statusOf(item.id);
      if (filter === 'pending') return st === 'pending';
      if (filter === 'done') return st !== 'pending';
      return true;
    }),
  );

  const total = $derived(Number(counts.total ?? 0));
  const doneCount = $derived(Number(counts.done ?? 0) + Number(counts.skipped ?? 0));
  const groupItems = $derived(
    ordered.filter((item) => group === 'all' || groupOf(item) === group),
  );
  const viewTotal = $derived(group === 'all' ? total : groupItems.length);
  const viewDone = $derived(
    group === 'all'
      ? doneCount
      : groupItems.filter((item) => statusOf(item.id) !== 'pending').length,
  );
  const viewPending = $derived(
    group === 'all' ? Number(counts.pending ?? 0) : groupItems.filter((item) => statusOf(item.id) === 'pending').length,
  );

  function locate(item: any) {
    setView('review');
    focusRange(Number(item.start), Number(item.end));
  }

  async function toggle(item: any) {
    const st = statusOf(item.id);
    if (st === 'pending') {
      await qaAction({ id: item.id, action: 'mark', status: 'done', resolution: 'checked' });
      advance(item.id);
    } else {
      await qaAction({ id: item.id, action: 'mark', status: 'pending' });
    }
  }

  /** 处理完一条后，自动定位到下一条待核——「逐项核对」的手感全靠这一下。 */
  function inGroup(item: any): boolean {
    return group === 'all' || groupOf(item) === group;
  }

  function advance(justHandled: string) {
    const next = ordered.find(
      (it) => it.id !== justHandled && inGroup(it) && statusOf(it.id) === 'pending',
    );
    if (next) {
      setView('review');
      focusRange(Number(next.start), Number(next.end));
    }
  }

  async function act(item: any, cmd: { action: string; status?: string; resolution?: string }) {
    await qaAction({ id: item.id, ...cmd });
    advance(item.id);
  }

  async function fill(item: any) {
    if (busy) {
      toast('已有任务在跑，请稍后再补录', 'warn');
      return;
    }
    locate(item);
    app.qaFillId = item.id;
    const gapStart = item.gap_start != null ? Number(item.gap_start) : NaN;
    const gapEnd = item.gap_end != null ? Number(item.gap_end) : NaN;
    await transcribeRange({
      start: Number(item.start),
      end: Number(item.end),
      engine: app.engine,
      label: '质检补录',
      padStart: 0.2,
      padEnd: 0.3,
      // 覆盖项带 gap_start/gap_end：补录区间不能越过空白边界，否则 0.3s
      // 的尾部 padding 会切进下一句，Whisper 把下一句的开头也一起转出来。
      clampStart: Number.isFinite(gapStart) ? gapStart : undefined,
      clampEnd: Number.isFinite(gapEnd) ? gapEnd : undefined,
    });
  }

  function jumpNext() {
    const next = ordered.find((it) => inGroup(it) && statusOf(it.id) === 'pending');
    if (next) locate(next);
    else toast('这一组没有待核项了');
  }

  /** 导入 / 草稿状态下，唯一能让质检重新对应字幕的动作是重新整片转写。 */
  function goTranscribe() {
    void toggleQaPanel(false);
    setView('transcribe');
  }
</script>

{#if qa.open}
  <aside
    class="qa-panel"
    class:detached
    aria-label="质检待核队列"
    in:popIn={motion ? { duration: 220 } : { duration: 0 }}
    out:popOut={motion ? { duration: 130 } : { duration: 0 }}
  >
    <header class="qa-head" class:bare={detached || !items.length}>
      <span class="qa-mark" class:off={detached}>
        <Icon name={detached ? 'doc' : 'search'} size={12} />
      </span>
      <div class="qa-title">
        <span class="title">质检待核</span>
        <span class="meta">
          {#if detached}
            已暂停 · 字幕不是转写结果
          {:else if total}
            {viewDone} / {viewTotal} 已核对 · {viewPending} 待核
          {:else}
            还没有可核对的结果
          {/if}
        </span>
      </div>
      <button
        class="icon-btn"
        onclick={jumpNext}
        disabled={!viewPending || detached}
        title="定位到下一条待核"
        aria-label="定位到下一条待核"
      >
        <Icon name="play" size={10} />
      </button>
      <button class="icon-btn" onclick={() => refreshQa()} title="刷新队列" aria-label="刷新队列">
        <Icon name="undo" size={11} />
      </button>
      <button
        class="icon-btn"
        onclick={() => toggleQaPanel(false)}
        title="收起（Esc）"
        aria-label="收起质检面板"
      >
        <Icon name="close" size={11} />
      </button>
    </header>

    {#if !detached && items.length}
      <div class="progress" aria-hidden="true">
        <i style="width:{viewTotal ? (viewDone / viewTotal) * 100 : 0}%"></i>
      </div>

      <div class="filters">
        <div class="groups" role="group" aria-label="问题类型">
          <button class:on={group === 'miss'} onclick={() => (group = 'miss')}>
            <i class="gdot miss"></i>漏检 <b>{missCount}</b>
          </button>
          <button class:on={group === 'low'} onclick={() => (group = 'low')}>
            <i class="gdot low"></i>低置信 <b>{lowCount}</b>
          </button>
          <button class:on={group === 'all'} onclick={() => (group = 'all')}>全部</button>
        </div>
        <div class="tabs" role="group" aria-label="核对状态">
          {#each [['pending', '待核'], ['done', '已核'], ['all', '全部']] as [key, label] (key)}
            <button class:on={filter === key} onclick={() => (filter = key as typeof filter)}>
              {label}
              {#if key === 'pending' && viewPending}
                <b>{viewPending}</b>
              {/if}
            </button>
          {/each}
        </div>
      </div>
    {/if}

    <div class="qa-body">
      {#if detached}
        <div class="empty">
          <div class="empty-icon"><Icon name="doc" size={18} /></div>
          <div class="empty-title">当前字幕不是这次转写的结果</div>
          <div class="empty-sub">{detachedReason}</div>
          <div class="source-chip" title={app.reviewSource?.path ?? ''}>
            <span>{app.reviewSource?.kind === 'draft' ? '暂存草稿' : '导入字幕'}</span>
            <b>{detachedSource}</b>
          </div>
          <div class="empty-tip">
            质检查的是转写结果；换一版字幕后队列暂停，避免删错句或补错区间。
          </div>
          {#if app.media}
            <button class="btn primary empty-cta" onclick={goTranscribe}>去转写并生成质检</button>
          {/if}
        </div>
      {:else if !items.length}
        <div class="empty">
          <div class="empty-icon"><Icon name={phase === 'idle' ? 'wave' : 'check'} size={18} /></div>
          {#if phase === 'idle' && reportFindings > 0}
            <div class="empty-title">队列为空，但报告里有 {reportFindings} 处待核</div>
            <div class="empty-sub">
              这通常是旧版本局部转写没有把队列落盘。请重新转写一次；若仍为空，到「设置 →
              日志与诊断」复制日志反馈。
            </div>
          {:else if phase === 'idle'}
            <div class="empty-title">还没有可核对的转写</div>
            <div class="empty-sub">转写完成后，这里会列出需要人工试听确认的片段；入口会一直保留。</div>
          {:else}
            <div class="empty-title">本次检查完成 · 0 处待核</div>
            <div class="empty-sub">
              检查了 {scanned.segments ?? 0} 个切片 / {scanned.cues ?? 0} 条字幕；
              另审计出 {scanned.coverage ?? 0} 段未覆盖空白。
            </div>
          {/if}
          <div class="coverage">
            <span class="cov" class:off={missCount === 0}>漏检 <b>{missCount}</b></span>
            <span class="cov" class:off={lowCount === 0}>低置信 <b>{lowCount}</b></span>
            <span class="cov off">
              空 {scanned.missed ?? 0} / 删 {scanned.dropped ?? 0} / 短 {scanned.suspect ?? 0}
            </span>
          </div>
        </div>
      {:else if !shown.length}
        <div class="empty">
          <div class="empty-icon"><Icon name={group === 'miss' ? 'search' : 'check'} size={18} /></div>
          <div class="empty-title">
            {#if group === 'miss' && missCount === 0}
              没有未覆盖空白
            {:else if group === 'low' && lowCount === 0}
              没有低置信条目
            {:else}
              {filter === 'pending' ? '所有条目都已核对' : '这一栏没有条目'}
            {/if}
          </div>
          <div class="empty-sub">
            {#if group === 'miss' && missCount === 0}
              主 VAD 的切片里没有发现新的空白语音；可切到「低置信」查看切片内异常。
            {:else if group === 'low' && lowCount === 0}
              切片内没有空结果 / 短句 / 误删。
            {:else}
              可以切到「全部」回看已处理的记录。
            {/if}
          </div>
        </div>
      {:else}
        {#each shown as item (item.id)}
          {@const st = statusOf(item.id)}
          {@const res = resolutionOf(item.id)}
          <article class="item" class:done={st !== 'pending'}>
            <button
              class="check"
              class:on={st !== 'pending'}
              onclick={() => toggle(item)}
              role="checkbox"
              aria-checked={st !== 'pending'}
              aria-label={st === 'pending' ? '标记为已核对' : '重新放回待核'}
              title={st === 'pending' ? '标记为已核对' : '重新放回待核'}
            >
              {#if st !== 'pending'}<Icon name="check" size={10} />{/if}
            </button>

            <div class="body">
              <div class="line1">
                <span class="kind k-{item.kind}">{KIND_LABEL[item.kind] ?? item.kind}</span>
                <span class="time">{tcShort(Number(item.start))} → {tcShort(Number(item.end))}</span>
                <span class="dur">{Number(item.dur ?? 0).toFixed(2)}s</span>
                {#if st !== 'pending'}
                  <span class="stamp">
                    <Icon name="check" size={8} />
                    {RESOLUTION_LABEL[res] ?? (st === 'skipped' ? '已跳过' : '已核对')}
                  </span>
                {/if}
              </div>

              {#if item.text}
                <div class="text">{item.text}</div>
              {/if}

              <div class="acts">
                <button class="act" onclick={() => locate(item)} title="在核对台定位这一段">
                  <Icon name="target" size={10} />定位
                </button>

                {#if item.kind === 'coverage' || item.kind === 'missed'}
                  <button class="act primary" onclick={() => fill(item)} disabled={busy}>
                    {#if app.qaFillId === item.id}<span class="spin"></span>{/if}
                    补录
                  </button>
                  <button
                    class="act"
                    onclick={() => act(item, { action: 'mark', status: 'done', resolution: 'not-speech' })}
                  >不是台词</button>
                {:else if item.kind === 'dropped'}
                  <button class="act primary-ghost" onclick={() => act(item, { action: 'restore' })}>
                    恢复原句
                  </button>
                  <button
                    class="act"
                    onclick={() => act(item, { action: 'mark', status: 'done', resolution: 'confirmed' })}
                  >确认删除</button>
                {:else}
                  <button
                    class="act primary-ghost"
                    onclick={() => act(item, { action: 'mark', status: 'done', resolution: 'kept' })}
                  >保留</button>
                  <button class="act danger" onclick={() => act(item, { action: 'delete_cue' })}>
                    删除此句
                  </button>
                {/if}

                <button class="act skip" onclick={() => act(item, { action: 'skip' })}>跳过</button>
                {#if st !== 'pending'}
                  <button class="act" onclick={() => toggle(item)}>放回</button>
                {/if}
              </div>
            </div>
          </article>
        {/each}
      {/if}
    </div>
  </aside>
{/if}

<style>
  .qa-panel {
    position: absolute;
    right: 14px;
    bottom: 40px;
    width: 438px;
    max-height: min(68vh, 620px);
    background: var(--raise);
    border: 1px solid var(--line);
    border-radius: 14px;
    box-shadow: var(--shadow-pop);
    display: flex;
    flex-direction: column;
    z-index: 60;
    overflow: hidden;
    transform-origin: 100% 100%;
  }

  .qa-head {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 10px 10px 9px 12px;
    flex: 0 0 auto;
  }
  .qa-head.bare {
    box-shadow: inset 0 -1px 0 var(--separator-soft);
  }
  .qa-mark {
    width: 24px;
    height: 24px;
    flex: 0 0 24px;
    border-radius: 7px;
    background: var(--accent-soft);
    color: var(--accent);
    display: grid;
    place-items: center;
  }
  .qa-mark.off {
    background: var(--fill);
    color: var(--text-3);
  }
  .qa-title {
    flex: 1;
    min-width: 0;
    display: flex;
    flex-direction: column;
    gap: 1px;
  }
  .title {
    font-size: 13px;
    line-height: 17px;
    font-weight: 600;
  }
  .meta {
    font-size: 11.5px;
    line-height: 15px;
    color: var(--text-3);
    font-variant-numeric: tabular-nums;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .icon-btn {
    appearance: none;
    border: 0;
    background: transparent;
    width: 24px;
    height: 24px;
    border-radius: 6px;
    display: grid;
    place-items: center;
    color: var(--text-3);
    padding: 0;
    transition: background var(--dur-fast) var(--ease), color var(--dur-fast) var(--ease);
  }
  .icon-btn:hover:not(:disabled) {
    background: var(--fill);
    color: var(--text);
  }
  .icon-btn:disabled {
    opacity: 0.35;
  }

  .progress {
    height: 3px;
    flex: 0 0 3px;
    margin: 0 12px;
    border-radius: 999px;
    background: var(--fill);
    overflow: hidden;
  }
  .progress i {
    display: block;
    height: 100%;
    border-radius: 999px;
    background: linear-gradient(
      90deg,
      color-mix(in srgb, var(--accent) 68%, #fff),
      var(--accent)
    );
    transition: width 260ms var(--ease);
  }

  .filters {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 8px;
    padding: 9px 10px 8px 12px;
    flex: 0 0 auto;
    box-shadow: inset 0 -1px 0 var(--separator-soft);
  }
  .groups {
    display: inline-flex;
    align-items: center;
    gap: 2px;
    padding: 2px;
    border-radius: 6px;
    background: var(--fill);
  }
  .groups button {
    appearance: none;
    border: 0;
    background: transparent;
    font: inherit;
    font-size: 12px;
    line-height: 16px;
    color: var(--text-2);
    height: 22px;
    padding: 0 8px;
    border-radius: 4px;
    display: inline-flex;
    align-items: center;
    gap: 4px;
    white-space: nowrap;
  }
  .groups button:hover {
    color: var(--text);
  }
  .groups button.on {
    background: var(--raise);
    color: var(--text);
    font-weight: 500;
    box-shadow: 0 1px 2px rgba(27, 39, 64, 0.1), 0 0 0 0.5px rgba(27, 39, 64, 0.04);
  }
  :global(html[data-theme='dark']) .groups button.on {
    background: rgba(236, 241, 250, 0.14);
  }
  .groups b {
    min-width: 15px;
    height: 15px;
    padding: 0 3px;
    border-radius: 4px;
    background: var(--fill);
    color: var(--text-3);
    display: grid;
    place-items: center;
    font-size: 11.5px;
    font-weight: 600;
    font-variant-numeric: tabular-nums;
  }
  .groups button.on b {
    background: var(--accent-soft);
    color: var(--accent);
  }
  .gdot {
    width: 5px;
    height: 5px;
    border-radius: 50%;
    display: inline-block;
  }
  .gdot.miss {
    background: var(--danger);
  }
  .gdot.low {
    background: var(--warn);
  }

  .tabs {
    display: inline-flex;
    align-items: center;
    gap: 1px;
  }
  .tabs button {
    appearance: none;
    border: 0;
    background: transparent;
    font: inherit;
    font-size: 12px;
    line-height: 16px;
    color: var(--text-3);
    height: 24px;
    padding: 0 7px;
    border-radius: 4px;
    display: inline-flex;
    align-items: center;
    gap: 4px;
    position: relative;
    white-space: nowrap;
  }
  .tabs button:hover {
    background: var(--fill);
    color: var(--text-2);
  }
  .tabs button.on {
    color: var(--accent);
    font-weight: 500;
  }
  .tabs button.on::after {
    content: '';
    position: absolute;
    left: 7px;
    right: 7px;
    bottom: 2px;
    height: 2px;
    border-radius: 1px;
    background: var(--accent);
  }
  .tabs b {
    min-width: 15px;
    height: 15px;
    padding: 0 3px;
    border-radius: 999px;
    background: var(--accent);
    color: var(--on-accent);
    display: grid;
    place-items: center;
    font-size: 11px;
    font-weight: 600;
  }

  .qa-body {
    overflow-y: auto;
    padding: 2px 0 4px;
  }

  .empty {
    padding: 24px 20px 22px;
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 6px;
    text-align: center;
  }
  .empty-icon {
    width: 40px;
    height: 40px;
    border-radius: 12px;
    background: var(--fill);
    color: var(--text-3);
    display: grid;
    place-items: center;
    margin-bottom: 2px;
  }
  .empty-title {
    font-size: 13px;
    line-height: 18px;
    font-weight: 600;
    color: var(--text);
  }
  .empty-sub {
    font-size: 12px;
    line-height: 18px;
    color: var(--text-3);
    max-width: 330px;
  }
  .empty-tip {
    font-size: 11.5px;
    line-height: 16px;
    color: var(--text-3);
    max-width: 330px;
  }
  .source-chip {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    max-width: 100%;
    margin-top: 3px;
    padding: 3px 8px;
    border-radius: 6px;
    background: var(--fill);
    font-size: 12px;
    color: var(--text-2);
  }
  .source-chip span {
    color: var(--text-3);
    flex: 0 0 auto;
  }
  .source-chip b {
    min-width: 0;
    font-weight: 500;
    font-family: var(--font-mono);
    font-size: 11.5px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .empty-cta {
    margin-top: 8px;
  }

  .coverage {
    display: flex;
    gap: 6px;
    margin-top: 8px;
    flex-wrap: wrap;
    justify-content: center;
  }
  .cov {
    font-size: 11.5px;
    line-height: 16px;
    padding: 2px 8px;
    border-radius: 999px;
    background: var(--accent-soft);
    color: var(--accent);
    font-variant-numeric: tabular-nums;
  }
  .cov b {
    font-weight: 600;
  }
  .cov.off {
    background: var(--fill);
    color: var(--text-3);
  }

  .item {
    display: flex;
    gap: 9px;
    padding: 11px 13px 10px 12px;
    position: relative;
    transition: background var(--dur-fast) var(--ease);
    animation: qaItemIn 180ms var(--ease) both;
  }
  @keyframes qaItemIn {
    from {
      opacity: 0;
      transform: translateY(3px);
    }
  }
  .item + .item {
    box-shadow: inset 0 1px 0 var(--separator-soft);
  }
  .item:hover {
    background: var(--row-hover);
  }
  .item.done {
    opacity: 0.64;
  }
  .item.done:hover {
    opacity: 0.82;
  }

  .check {
    appearance: none;
    width: 16px;
    height: 16px;
    flex: 0 0 16px;
    margin-top: 1px;
    border-radius: 5px;
    border: 1px solid var(--line);
    background: var(--raise);
    display: grid;
    place-items: center;
    color: var(--on-accent);
    padding: 0;
    transition: background var(--dur-fast) var(--ease),
      border-color var(--dur-fast) var(--ease), transform var(--dur-fast) var(--ease);
  }
  .check:hover {
    border-color: var(--accent);
  }
  .check:active {
    transform: scale(0.92);
  }
  .check.on {
    background: var(--control-on);
    border-color: var(--control-on);
  }

  .body {
    flex: 1;
    min-width: 0;
    display: flex;
    flex-direction: column;
    gap: 5px;
  }

  .line1 {
    display: flex;
    align-items: baseline;
    gap: 7px;
    min-width: 0;
    font-size: 12px;
    line-height: 16px;
  }
  .kind {
    font-weight: 600;
    font-size: 11.5px;
    line-height: 16px;
    padding: 1px 7px;
    border-radius: 999px;
    background: var(--fill);
    color: var(--text-2);
    white-space: nowrap;
  }
  .k-coverage {
    background: var(--danger-soft);
    color: var(--danger);
  }
  .k-missed {
    background: var(--warn-soft);
    color: var(--warn);
  }
  .k-dropped {
    background: var(--danger-soft);
    color: var(--danger);
  }
  .k-suspect {
    background: var(--accent-soft);
    color: var(--accent);
  }
  .time {
    font-family: var(--font-mono);
    color: var(--text-2);
    font-variant-numeric: tabular-nums;
    white-space: nowrap;
  }
  .dur {
    font-family: var(--font-mono);
    color: var(--text-3);
    font-variant-numeric: tabular-nums;
  }
  .stamp {
    margin-left: auto;
    display: inline-flex;
    align-items: center;
    gap: 3px;
    color: var(--success);
    white-space: nowrap;
  }

  .text {
    font-size: 13px;
    line-height: 19px;
    color: var(--text);
    display: -webkit-box;
    -webkit-line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
  }

  .acts {
    display: flex;
    gap: 2px;
    flex-wrap: wrap;
    margin-top: 1px;
  }
  .act {
    appearance: none;
    border: 1px solid transparent;
    background: transparent;
    font: inherit;
    font-size: 12px;
    line-height: 16px;
    height: 22px;
    padding: 0 7px;
    border-radius: 5px;
    display: inline-flex;
    align-items: center;
    gap: 3px;
    color: var(--text-2);
    white-space: nowrap;
    transition: background var(--dur-fast) var(--ease), color var(--dur-fast) var(--ease),
      border-color var(--dur-fast) var(--ease);
  }
  .act:hover:not(:disabled) {
    background: var(--fill);
    color: var(--text);
  }
  .act:disabled {
    opacity: 0.45;
  }
  .act.primary {
    background: var(--btn-primary-bg);
    border-color: var(--btn-primary-bg);
    color: var(--on-accent);
    font-weight: 500;
  }
  .act.primary:hover:not(:disabled) {
    background: var(--btn-primary-hover);
    border-color: var(--accent-hover);
  }
  .act.primary-ghost {
    color: var(--accent);
    background: var(--accent-soft);
  }
  .act.primary-ghost:hover:not(:disabled) {
    background: color-mix(in srgb, var(--accent) 16%, transparent);
    color: var(--accent);
  }
  .act.danger {
    color: var(--danger);
  }
  .act.danger:hover:not(:disabled) {
    background: rgba(179, 38, 30, 0.08);
    color: var(--danger);
  }
  .act.skip {
    margin-left: auto;
    color: var(--text-3);
  }

  .spin {
    width: 9px;
    height: 9px;
    flex: 0 0 9px;
    border-radius: 50%;
    border: 1.4px solid currentColor;
    border-top-color: transparent;
    animation: spin 650ms linear infinite;
  }
  @keyframes spin {
    to {
      transform: rotate(360deg);
    }
  }

  /* 紧凑模式（≤900px）：面板铺满工作区宽度，层级压到检查器抽屉（z 20）之下，
     打开抽屉时面板不会盖住正在编辑的当前句。 */
  @media (max-width: 900px) {
    .qa-panel {
      left: 8px;
      right: 8px;
      bottom: 8px;
      width: auto;
      max-height: min(58vh, 520px);
      z-index: 18;
    }
    .empty {
      padding: 18px 14px;
    }
    .filters {
      flex-wrap: wrap;
    }
    .tabs {
      margin-left: auto;
    }
  }
</style>
