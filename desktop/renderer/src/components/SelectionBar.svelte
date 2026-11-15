<script lang="ts">
  /**
   * 选区工具条：时间框选、轨道多选、以及「⇧ 连选」出来的两者同时存在。
   *
   * 从 `ReviewView.svelte` 抽出来的原因有两条：
   * - 那个文件有行数预算（只许变短），而这一块是一个完整的小界面单元；
   * - 批量复核入口已按产品决定删除（Q1/R1）；单句复核仍留在检查器与质检面板。
   *
   * 组件不拥有状态：选区归 ReviewView 管，这里只读 + 回调。
   * 两种选中同时存在时只出一根条：先报块数，再报时间范围，删除与转写一起给，
   * 否则 ⇧ 连选后时间选区会被「该不该显示」的条件藏掉。
   */
  import Icon from './Icon.svelte';
  import { tcShort } from '../lib/time';
  import { vocalSeparation } from '../lib/vocalSeparation.svelte';

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

  const laneCount = $derived(laneSelection.length);

  function clearAll() {
    onClearLane();
    if (selection) onClearSelection();
  }
</script>

{#if laneCount > 1 || selection}
  <div class="sel-bar">
    <span class="sel-info">
      {#if laneCount > 1}
        <span class="sel-count">已选 {laneCount} 块字幕</span>
      {/if}
      {#if selection}
        <span class="sel-range">{tcShort(selection.start)} → {tcShort(selection.end)}</span>
        <b>{(selection.end - selection.start).toFixed(2)}s</b>
      {:else}
        <b>可一起删除</b>
      {/if}
    </span>
    {#if laneCount > 1}
      <button class="btn tiny danger" onclick={onDelete} title="删除选中的全部字幕（⌘Z 可撤销）">
        <Icon name="trash" size={10} />删除
      </button>
    {/if}
    {#if selection}
      <button class="btn tiny" onclick={onSeekSelection} title="只播放选区">
        <Icon name="play" size={10} />试听
      </button>
      <label
        class="sel-sep"
        title="人声分离（强 BGM / 歌曲）：只对本次选区生效；首次会下载约 80MB 权重，分离结果会缓存"
      >
        <input type="checkbox" bind:checked={vocalSeparation.enabled} />
        分离
      </label>
      <button class="btn tiny primary" onclick={onTranscribe} disabled={rangeBusy}>
        {#if rangeBusy}
          <span class="spin"></span>转写中
        {:else}
          <Icon name="wave" size={10} />转写选区
        {/if}
      </button>
      <button
        class="btn tiny"
        onclick={onSendSelection}
        title="把当前起止时间（含在音轨上微调后的结果）填到转写页的局部区间"
      >
        同步到转写页
      </button>
      <button class="btn tiny" onclick={onFocus} title="放大到选区">聚焦</button>
    {/if}
    <div class="tl-spacer"></div>
    <button class="btn tiny ghost" onclick={clearAll} title="取消选择">
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
    display: inline-flex;
    align-items: center;
    gap: 6px;
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
  .sel-count {
    font-family: var(--font-sans);
  }
  .sel-sep {
    display: inline-flex;
    align-items: center;
    gap: var(--sp-1);
    font-size: 12px;
    color: var(--text-2);
    white-space: nowrap;
    cursor: default;
  }
  .sel-sep input {
    margin: 0;
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
    /* 窄窗口里选区工具条会挤出右边界：只留块数，把时间范围让给按钮 */
    .sel-range {
      display: none;
    }
    .sel-sep {
      font-size: 0;
    }
  }
</style>
