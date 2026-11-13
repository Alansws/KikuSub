<script lang="ts">
  /**
   * 选区工具条（轨道多选 / 时间框选两态）。
   *
   * 从 `ReviewView.svelte` 抽出来的原因有两条：
   * - 那个文件有行数预算（只许变短），而这一块是一个完整的小界面单元；
   * - 「另一引擎复核」的批量入口本来就要挂在这条工具条上，抽出来之后复核的 UI
   *   不再散落在两个文件里。
   *
   * 组件不拥有状态：选区归 ReviewView 管，这里只读 + 回调。
   */
  import Icon from './Icon.svelte';
  import { app } from '../lib/store.svelte';
  import { indicesForLaneKeys, indicesInRange } from '../lib/selection';
  import { runSecondOpinion, secondOpinion } from '../lib/secondOpinion.svelte';
  import { jobBusy } from '../lib/jobState';
  import { tcShort } from '../lib/time';

  let {
    selection = null,
    laneSelection = [],
    rangeBusy = false,
    onDelete,
    onTranscribe,
    onFocus,
    onSendSelection,
    onSeekSelection,
    onClearLane,
    onClearSelection,
  }: {
    selection?: { start: number; end: number } | null;
    laneSelection?: string[];
    rangeBusy?: boolean;
    onDelete: () => void;
    onTranscribe: () => void;
    onFocus: () => void;
    onSendSelection: () => void;
    onSeekSelection: () => void;
    onClearLane: () => void;
    onClearSelection: () => void;
  } = $props();

  function reviewLane(): void {
    runSecondOpinion(indicesForLaneKeys(app.cues, laneSelection));
  }

  function reviewSelection(): void {
    if (!selection) return;
    runSecondOpinion(indicesInRange(app.cues, selection.start, selection.end));
  }
</script>

{#if laneSelection.length > 1}
  <div class="sel-bar lane-bar">
    <span class="sel-info">
      <span class="sel-range">已选 {laneSelection.length} 块字幕</span>
      <b>可一起删除</b>
    </span>
    <button class="btn tiny danger" onclick={onDelete} title="删除选中的全部字幕（⌘Z 可撤销）">
      <Icon name="trash" size={10} />删除
    </button>
    <button
      class="btn tiny"
      onclick={reviewLane}
      disabled={jobBusy() || secondOpinion.status === 'running' || laneSelection.length > 40}
      title={laneSelection.length > 40 ? '一次最多 40 条' : '用另一个引擎把选中的字幕各听一遍'}>
      {#if secondOpinion.status === 'running'}<span class="spin"></span>复核中{:else}🎧 复核 {laneSelection.length} 条{/if}
    </button>
    <div class="tl-spacer"></div>
    <button class="btn tiny ghost" onclick={onClearLane} title="取消多选">
      <Icon name="close" size={10} />
    </button>
  </div>
{:else if selection}
  <div class="sel-bar">
    <span class="sel-info">
      <span class="sel-range">{tcShort(selection.start)} → {tcShort(selection.end)}</span>
      <b>{(selection.end - selection.start).toFixed(2)}s</b>
    </span>
    <button class="btn tiny" onclick={onSeekSelection} title="只播放选区">
      <Icon name="play" size={10} />试听
    </button>
    <button class="btn tiny primary" onclick={onTranscribe} disabled={rangeBusy}>
      {#if rangeBusy}
        <span class="spin"></span>转写中
      {:else}
        <Icon name="wave" size={10} />转写选区
      {/if}
    </button>
    <button class="btn tiny" onclick={onSendSelection} title="填到转写页的区间">填入转写</button>
    <button class="btn tiny" onclick={onFocus} title="放大到选区">聚焦</button>
    <button
      class="btn tiny"
      onclick={reviewSelection}
      disabled={jobBusy() || secondOpinion.status === 'running'}
      title="把选区里的字幕送给另一个引擎各听一遍">🎧 复核选区</button>
    <div class="tl-spacer"></div>
    <button class="btn tiny ghost" onclick={onClearSelection} title="清除选区">
      <Icon name="close" size={10} />
    </button>
  </div>
{/if}

<style>
  /* 组件内的按钮样式：Svelte 的 scoped style 不跨组件，所以这里保留一份与
     ReviewView 里等价的 .tiny / .spin（`.btn` 本身是 app.css 的全局类）。 */
  .tl-spacer {
    flex: 1;
  }
  .sel-bar {
    animation: selIn 140ms var(--ease);
    display: flex;
    align-items: center;
    gap: 5px;
    /* 悬浮在工具行上层：出现/消失不能让波形上下跳，
       否则刚拖完选区的下一次点击会落到别的位置。 */
    position: absolute;
    inset: 0;
    z-index: 2;
    background: color-mix(in srgb, var(--accent) 8%, var(--paper));
    box-shadow: inset 0 0 0 1px var(--accent-ring);
    border-radius: 4px;
    padding: 0 6px 0 9px;
    height: 30px;
  }
  @keyframes selIn {
    from {
      opacity: 0;
    }
  }
  .sel-info {
    font-size: 12px;
    line-height: 16px;
    color: var(--text-2);
    font-variant-numeric: tabular-nums;
    font-family: ui-monospace, 'SF Mono', Menlo, monospace;
    white-space: nowrap;
  }
  .sel-info b {
    color: var(--accent);
    font-weight: 600;
    margin-left: 3px;
  }
  .tiny {
    height: 22px;
    font-size: 12px;
    padding: 0 7px;
    background: var(--raise);
  }
  .btn.primary.tiny {
    background: var(--btn-primary-bg);
    color: var(--on-accent);
  }
  .spin {
    width: 9px;
    height: 9px;
    border-radius: 50%;
    border: 1.5px solid currentColor;
    border-top-color: transparent;
    animation: spin 650ms linear infinite;
  }
  @keyframes spin {
    to {
      transform: rotate(360deg);
    }
  }
  @media (max-width: 1220px) {
    /* 窄窗口里选区工具条会挤出右边界：只留时长，把时间范围让给按钮 */
    .sel-range {
      display: none;
    }
  }
</style>
