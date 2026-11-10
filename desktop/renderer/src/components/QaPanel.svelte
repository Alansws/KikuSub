<script lang="ts">
  import Icon from './Icon.svelte';
  import { play, qa, qaAction, refreshQa, toggleQaPanel } from '../lib/store.svelte';
  import { tcShort } from '../lib/time';

  const items = $derived<any[]>(qa.payload?.items ?? []);
  const statuses = $derived<Record<string, any>>(qa.payload?.statuses ?? {});
  const counts = $derived<any>(qa.payload?.counts ?? {});

  function statusOf(id: string): string {
    return statuses[id]?.status ?? 'pending';
  }

  /** 待核的排在前面，处理过的沉底，避免用户翻半天。 */
  const sorted = $derived(
    [...items].sort((a, b) => {
      const sa = statusOf(a.id) === 'pending' ? 0 : 1;
      const sb = statusOf(b.id) === 'pending' ? 0 : 1;
      if (sa !== sb) return sa - sb;
      return Number(a.start) - Number(b.start);
    }),
  );

  const KIND_LABEL: Record<string, string> = {
    missed: '可能漏句',
    dropped: '误删待核',
    suspect: '短句待确认',
  };

  function focus(item: any) {
    play.selected = 0;
    play.time = Number(item.start) + 0.02;
  }
</script>

{#if qa.open}
  <div class="qa-panel">
    <div class="qa-head">
      <span class="title">质检待核队列</span>
      <span class="meta">
        {counts.pending ?? 0} 待核 · {counts.done ?? 0} 已处理 · {counts.skipped ?? 0} 跳过
      </span>
      <button class="btn icon ghost" onclick={() => refreshQa()} title="刷新">
        <Icon name="undo" size={12} />
      </button>
      <button class="btn icon ghost" onclick={() => toggleQaPanel(false)} title="关闭">
        <Icon name="warn" size={12} />
      </button>
    </div>

    <div class="qa-body">
      {#if !items.length}
        <div class="empty">
          本次转写没有需要人工试听复核的片段。队列入口会一直保留。
        </div>
      {:else}
        {#each sorted as item (item.id)}
          {@const st = statusOf(item.id)}
          <div class="item" class:done={st !== 'pending'}>
            <div class="line1">
              <span class="kind k-{item.kind}">{KIND_LABEL[item.kind] ?? item.kind}</span>
              <span class="time">{tcShort(Number(item.start))} → {tcShort(Number(item.end))}</span>
              <span class="dur">{Number(item.dur ?? 0).toFixed(2)}s</span>
              {#if st !== 'pending'}
                <span class="stamp">{st === 'skipped' ? '已跳过' : '已处理'}</span>
              {/if}
            </div>

            {#if item.text}
              <div class="text">{item.text}</div>
            {/if}

            <div class="acts">
              <button class="btn tiny" onclick={() => focus(item)}>
                <Icon name="play" size={10} />定位
              </button>

              {#if item.kind === 'dropped'}
                <button
                  class="btn tiny"
                  onclick={() => qaAction({ id: item.id, action: 'restore' })}
                >恢复原句</button>
                <button
                  class="btn tiny ghost"
                  onclick={() =>
                    qaAction({ id: item.id, action: 'mark', status: 'done', resolution: 'confirmed' })}
                >确认删除</button>
              {:else if item.kind === 'suspect'}
                <button
                  class="btn tiny"
                  onclick={() =>
                    qaAction({ id: item.id, action: 'mark', status: 'done', resolution: 'kept' })}
                >保留</button>
                <button
                  class="btn tiny ghost danger"
                  onclick={() => qaAction({ id: item.id, action: 'delete_cue' })}
                >删除此句</button>
              {:else}
                <button
                  class="btn tiny"
                  onclick={() =>
                    qaAction({ id: item.id, action: 'mark', status: 'done', resolution: 'not-speech' })}
                >不是台词</button>
              {/if}

              <button
                class="btn tiny ghost"
                onclick={() => qaAction({ id: item.id, action: 'skip' })}
              >跳过</button>
              {#if st !== 'pending'}
                <button
                  class="btn tiny ghost"
                  onclick={() =>
                    qaAction({ id: item.id, action: 'mark', status: 'pending' })}
                >放回</button>
              {/if}
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
    bottom: 44px;
    width: 400px;
    max-height: min(60vh, 520px);
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
    gap: 8px;
    padding: 9px 10px 9px 12px;
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

  .qa-body {
    overflow-y: auto;
    padding: 4px 0;
  }

  .empty {
    padding: 18px 14px;
    font-size: 12px;
    color: var(--text-3);
    line-height: 1.6;
  }

  .item {
    padding: 9px 12px;
    border-bottom: 1px solid var(--separator-soft);
    display: flex;
    flex-direction: column;
    gap: 5px;
  }
  .item:last-child {
    border-bottom: 0;
  }
  .item.done {
    opacity: 0.55;
  }

  .line1 {
    display: flex;
    align-items: baseline;
    gap: 8px;
    font-size: 11px;
  }
  .kind {
    font-weight: 600;
    font-size: 10.5px;
    padding: 1px 6px;
    border-radius: 8px;
    background: var(--fill);
    color: var(--text-2);
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
  }
  .dur {
    font-family: ui-monospace, 'SF Mono', Menlo, monospace;
    color: var(--text-3);
    font-variant-numeric: tabular-nums;
  }
  .stamp {
    margin-left: auto;
    color: var(--text-3);
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
    gap: 5px;
    flex-wrap: wrap;
  }
  .tiny {
    height: 21px;
    font-size: 11px;
    padding: 0 7px;
  }
  .tiny.danger {
    color: #ff453a;
  }
</style>
