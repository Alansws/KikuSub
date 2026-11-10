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

  const items = $derived<any[]>(qa.payload?.items ?? []);
  const statuses = $derived<Record<string, any>>(qa.payload?.statuses ?? {});
  const counts = $derived<any>(qa.payload?.counts ?? {});
  const scanned = $derived<any>(qa.payload?.scanned ?? {});
  const phase = $derived<string>(qa.payload?.phase ?? 'idle');
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
</script>

{#if qa.open}
  <div class="qa-panel">
    <div class="qa-head">
      <button class="icon-btn" onclick={() => toggleQaPanel(false)} title="收起">
        <Icon name="close" size={11} />
      </button>
      <span class="title">质检待核</span>
      <span class="meta">{viewDone} / {viewTotal} 已核对</span>
      <button class="icon-btn" onclick={() => refreshQa()} title="刷新队列">
        <Icon name="undo" size={11} />
      </button>
    </div>

    <div class="progress">
      <i style="width:{viewTotal ? (viewDone / viewTotal) * 100 : 0}%"></i>
    </div>

    <div class="tabs">
      {#each [['pending', '待核'], ['all', '全部'], ['done', '已处理']] as [key, label] (key)}
        <button class:on={filter === key} onclick={() => (filter = key as typeof filter)}>
          {label}
          {#if key === 'pending' && viewPending}
            <b>{viewPending}</b>
          {/if}
        </button>
      {/each}
      <div class="tabs-spacer"></div>
      <button class="next-btn" onclick={jumpNext} title="定位到下一条待核">
        下一个 <Icon name="play" size={9} />
      </button>
    </div>

    <div class="groups">
      <button class:on={group === 'miss'} onclick={() => (group = 'miss')}>
        漏检 <b>{missCount}</b>
      </button>
      <button class:on={group === 'low'} onclick={() => (group = 'low')}>
        低置信 <b>{lowCount}</b>
      </button>
      <button class:on={group === 'all'} onclick={() => (group = 'all')}>全部</button>
    </div>

    <div class="qa-body">
      {#if !items.length}
        <div class="empty">
          {#if phase === 'idle' && reportFindings > 0}
            <div class="empty-title">队列为空，但报告里有 {reportFindings} 处待核</div>
            <div class="empty-sub">
              这通常是旧版本局部转写没有把队列落盘。请重新转写一次；若仍为空，到「设置 →
              日志与诊断」复制日志发给我。
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
          <div class="item" class:done={st !== 'pending'}>
            <button
              class="check"
              class:on={st !== 'pending'}
              onclick={() => toggle(item)}
              role="checkbox"
              aria-checked={st !== 'pending'}
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
                  <span class="stamp">{RESOLUTION_LABEL[res] ?? (st === 'skipped' ? '已跳过' : '已核对')}</span>
                {/if}
              </div>

              {#if item.text}
                <div class="text">{item.text}</div>
              {/if}

              <div class="acts">
                <button class="btn tiny" onclick={() => locate(item)}>
                  <Icon name="search" size={9} />定位
                </button>

                {#if item.kind === 'coverage' || item.kind === 'missed'}
                  <button class="btn tiny primary" onclick={() => fill(item)} disabled={busy}>
                    {#if app.qaFillId === item.id}<span class="spin"></span>{/if}
                    补录
                  </button>
                  <button
                    class="btn tiny ghost"
                    onclick={() => act(item, { action: 'mark', status: 'done', resolution: 'not-speech' })}
                  >不是台词</button>
                {:else if item.kind === 'dropped'}
                  <button class="btn tiny" onclick={() => act(item, { action: 'restore' })}>
                    恢复原句
                  </button>
                  <button
                    class="btn tiny ghost"
                    onclick={() => act(item, { action: 'mark', status: 'done', resolution: 'confirmed' })}
                  >确认删除</button>
                {:else}
                  <button
                    class="btn tiny"
                    onclick={() => act(item, { action: 'mark', status: 'done', resolution: 'kept' })}
                  >保留</button>
                  <button class="btn tiny ghost danger" onclick={() => act(item, { action: 'delete_cue' })}>
                    删除此句
                  </button>
                {/if}

                <button class="btn tiny ghost" onclick={() => act(item, { action: 'skip' })}>跳过</button>
                {#if st !== 'pending'}
                  <button class="btn tiny ghost" onclick={() => toggle(item)}>放回</button>
                {/if}
              </div>
            </div>
          </div>
        {/each}
      {/if}
    </div>
  </div>
{/if}

<style>
  .qa-panel {
    position: absolute;
    right: 14px;
    bottom: 40px;
    width: 438px;
    max-height: min(66vh, 600px);
    background: var(--bg-content);
    border: 1px solid var(--separator);
    border-radius: 12px;
    box-shadow: var(--shadow-pop);
    display: flex;
    flex-direction: column;
    z-index: 60;
    overflow: hidden;
  }

  .qa-head {
    display: flex;
    align-items: center;
    gap: 7px;
    padding: 8px 9px 7px 9px;
    border-bottom: 1px solid var(--separator-soft);
    flex: 0 0 auto;
  }
  .title {
    font-size: 12.5px;
    font-weight: 600;
  }
  .meta {
    flex: 1;
    font-size: 11px;
    color: var(--text-3);
    font-variant-numeric: tabular-nums;
  }

  .progress {
    height: 2px;
    background: var(--fill);
    flex: 0 0 2px;
  }
  .progress i {
    display: block;
    height: 100%;
    background: var(--accent);
    transition: width 240ms var(--ease);
  }

  .tabs {
    display: flex;
    align-items: center;
    gap: 2px;
    padding: 5px 8px;
    border-bottom: 1px solid var(--separator-soft);
    flex: 0 0 auto;
  }
  .tabs button {
    appearance: none;
    border: 0;
    background: transparent;
    font: inherit;
    font-size: 11px;
    color: var(--text-2);
    height: 20px;
    padding: 0 7px;
    border-radius: 5px;
    display: inline-flex;
    align-items: center;
    gap: 4px;
  }
  .tabs button:hover {
    background: var(--fill);
  }
  .tabs button.on {
    background: var(--accent-soft);
    color: var(--accent);
    font-weight: 500;
  }
  .tabs b {
    font-size: 10px;
    min-width: 14px;
    height: 14px;
    border-radius: 7px;
    background: var(--accent);
    color: #fff;
    display: grid;
    place-items: center;
    font-weight: 600;
    padding: 0 3px;
  }
  .tabs-spacer {
    flex: 1;
  }
  .groups {
    display: flex;
    gap: 4px;
    padding: 5px 9px;
    border-bottom: 1px solid var(--separator-soft);
    flex: 0 0 auto;
  }
  .groups button {
    appearance: none;
    border: 0;
    background: transparent;
    font: inherit;
    font-size: 10.5px;
    color: var(--text-3);
    padding: 2px 7px;
    border-radius: 6px;
    display: inline-flex;
    align-items: center;
    gap: 4px;
  }
  .groups button:hover {
    background: var(--fill);
    color: var(--text-2);
  }
  .groups button.on {
    background: var(--accent-soft);
    color: var(--accent);
    font-weight: 500;
  }
  .groups b {
    font-size: 10px;
    min-width: 14px;
    height: 14px;
    border-radius: 7px;
    background: var(--fill);
    color: var(--text-2);
    display: grid;
    place-items: center;
    font-weight: 600;
    padding: 0 3px;
  }
  .groups button.on b {
    background: var(--accent);
    color: #fff;
  }
  .next-btn {
    appearance: none;
    border: 0;
    background: transparent;
    font: inherit;
    font-size: 10.5px;
    color: var(--text-3);
    display: inline-flex;
    align-items: center;
    gap: 3px;
    padding: 2px 5px;
    border-radius: 5px;
  }
  .next-btn:hover {
    background: var(--fill);
    color: var(--text-2);
  }

  .qa-body {
    overflow-y: auto;
    padding: 2px 0;
  }

  .empty {
    padding: 18px 15px 16px;
    display: flex;
    flex-direction: column;
    gap: 5px;
  }
  .empty-title {
    font-size: 12.5px;
    font-weight: 500;
    color: var(--text);
  }
  .empty-sub {
    font-size: 11px;
    color: var(--text-3);
    line-height: 1.55;
  }
  .coverage {
    display: flex;
    gap: 6px;
    margin-top: 6px;
    flex-wrap: wrap;
  }
  .cov {
    font-size: 10px;
    padding: 2px 7px;
    border-radius: 8px;
    background: var(--accent-soft);
    color: var(--accent);
    font-variant-numeric: tabular-nums;
  }
  .cov.off {
    background: var(--fill);
    color: var(--text-3);
  }

  .item {
    display: flex;
    gap: 8px;
    padding: 8px 11px 9px 10px;
    border-bottom: 1px solid var(--separator-soft);
  }
  .item:last-child {
    border-bottom: 0;
  }
  .item.done {
    opacity: 0.62;
  }

  .check {
    appearance: none;
    width: 15px;
    height: 15px;
    flex: 0 0 15px;
    margin-top: 1px;
    border-radius: 4px;
    border: 1px solid var(--separator);
    background: var(--bg-content);
    display: grid;
    place-items: center;
    color: #fff;
    padding: 0;
  }
  .check:hover {
    border-color: var(--accent);
  }
  .check.on {
    background: var(--accent);
    border-color: var(--accent);
  }

  .body {
    flex: 1;
    min-width: 0;
    display: flex;
    flex-direction: column;
    gap: 4px;
  }

  .line1 {
    display: flex;
    align-items: baseline;
    gap: 7px;
    font-size: 10.5px;
  }
  .kind {
    font-weight: 600;
    font-size: 10px;
    padding: 1px 6px;
    border-radius: 8px;
    background: var(--fill);
    color: var(--text-2);
    white-space: nowrap;
  }
  .k-coverage {
    background: rgba(255, 59, 48, 0.16);
    color: #c0392b;
  }
  .k-missed {
    background: rgba(255, 159, 10, 0.16);
    color: #b26a00;
  }
  .k-dropped {
    background: rgba(255, 69, 58, 0.14);
    color: #c0392b;
  }
  .k-suspect {
    background: rgba(10, 132, 255, 0.14);
    color: var(--accent);
  }
  html[data-theme='dark'] .k-coverage {
    color: #ff8a80;
  }
  html[data-theme='dark'] .k-missed {
    color: #ffb340;
  }
  html[data-theme='dark'] .k-dropped {
    color: #ff7b70;
  }

  .time {
    font-family: ui-monospace, 'SF Mono', Menlo, monospace;
    color: var(--text-2);
    font-variant-numeric: tabular-nums;
    white-space: nowrap;
  }
  .dur {
    font-family: ui-monospace, 'SF Mono', Menlo, monospace;
    color: var(--text-3);
    font-variant-numeric: tabular-nums;
  }
  .stamp {
    margin-left: auto;
    color: var(--text-3);
    white-space: nowrap;
  }

  .text {
    font-size: 12.5px;
    line-height: 1.45;
    color: var(--text);
    display: -webkit-box;
    -webkit-line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
  }

  .acts {
    display: flex;
    gap: 4px;
    flex-wrap: wrap;
    margin-top: 1px;
  }
  .tiny {
    height: 20px;
    font-size: 10.5px;
    padding: 0 6px;
  }
  .tiny.primary {
    background: var(--accent);
    color: #fff;
  }
  .tiny.danger {
    color: #ff453a;
  }

  .icon-btn {
    appearance: none;
    border: 0;
    background: transparent;
    width: 20px;
    height: 20px;
    border-radius: 5px;
    display: grid;
    place-items: center;
    color: var(--text-3);
    padding: 0;
  }
  .icon-btn:hover {
    background: var(--fill);
    color: var(--text);
  }

  .spin {
    width: 8px;
    height: 8px;
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
</style>
