<script lang="ts">
  /**
   * 一条能力指标：标签 / 轨道 / 数值。
   *
   * 两种语义共用一套视觉：`score`（速度、时间轴，越长越好，用 --meter-a）
   * 与 `cost`（内存，越长越费，用 --meter-muted）。颜色本身就在提示方向，
   * 所以卡片上不需要再写「越大越好」这类说明。
   */
  let {
    label,
    value,
    bar,
    tone = 'score',
    detail = '',
  }: {
    label: string;
    value: string;
    bar: number;
    tone?: 'score' | 'cost';
    detail?: string;
  } = $props();
</script>

<div class="cap" title={detail}>
  <span class="cap-k">{label}</span>
  <span class="cap-track">
    <i class="cap-fill" class:muted={tone === 'cost'} style={`width:${Math.min(100, Math.max(0, bar))}%`}
    ></i>
  </span>
  <span class="cap-v">{value}</span>
</div>

<style>
  .cap {
    display: grid;
    grid-template-columns: 3.4em minmax(0, 1fr) 6.4em;
    align-items: center;
    gap: var(--sp-2);
  }
  .cap-k {
    font-size: 11px;
    color: var(--text-3);
    white-space: nowrap;
  }
  .cap-track {
    display: block;
    height: 4px;
    border-radius: 2px;
    background: var(--meter-track);
    overflow: hidden;
  }
  .cap-fill {
    display: block;
    height: 100%;
    border-radius: 2px;
    background: var(--meter-a);
    transition: width var(--dur) var(--ease);
  }
  .cap-fill.muted {
    background: var(--meter-muted);
  }
  .cap-v {
    font-size: 11px;
    color: var(--text-2);
    text-align: right;
    font-variant-numeric: tabular-nums;
    white-space: nowrap;
  }
</style>
