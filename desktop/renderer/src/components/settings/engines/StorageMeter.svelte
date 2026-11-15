<script lang="ts">
  /**
   * 「模型占用」分段条：日语 / 中文 / 音色克隆三类。
   *
   * 已知体积的两段按字节比宽；音色克隆现在拿不到字节数（侧车状态没有 size_bytes），
   * 所以它永远是一个斜纹占位段 + 图例里的「未安装 / 已安装（未计量）」——
   * 不给它编一个假体积，也不让它从条上消失。
   */
  import { formatBytes } from '../../../lib/time';
  import { segmentFlex, segmentLegend, type UsageSummary } from '../../../lib/settings/engineMetrics';

  let { usage }: { usage: UsageSummary } = $props();

  const flex = $derived(segmentFlex(usage));
  const ariaLabel = $derived(
    usage.segments
      .map((segment) => segmentLegend(segment, formatBytes))
      .join('，'),
  );
</script>

<div class="usage">
  <div class="usage-top">
    <span class="usage-k">模型占用</span>
    <span class="usage-v">{formatBytes(usage.totalBytes)}</span>
  </div>

  <div class="meter" role="img" aria-label={`模型占用：${ariaLabel}`}>
    {#each usage.segments as segment, index (segment.id)}
      <span
        class="meter-bar"
        class:known={segment.known}
        class:ja={segment.id === 'ja'}
        class:zh={segment.id === 'zh'}
        class:clone={segment.id === 'clone'}
        class:empty={!segment.known || segment.bytes === 0}
        style={`flex:${flex[index]}`}
      ></span>
    {/each}
  </div>

  <div class="legend">
    {#each usage.segments as segment (segment.id)}
      <span class="legend-item" class:muted={!segment.known || segment.bytes === 0}>
        <i
          class="legend-swatch"
          class:ja={segment.id === 'ja'}
          class:zh={segment.id === 'zh'}
          class:clone={segment.id === 'clone'}
          class:none={!segment.known || segment.bytes === 0}
        ></i>
        {segmentLegend(segment, formatBytes)}
      </span>
    {/each}
  </div>
</div>

<style>
  .usage {
    min-width: 0;
    display: flex;
    flex-direction: column;
  }
  .usage-top {
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    gap: var(--sp-2);
  }
  .usage-k {
    font-size: var(--fs-label);
    color: var(--text-2);
  }
  .usage-v {
    font-size: var(--fs-heading);
    font-weight: 600;
    font-variant-numeric: tabular-nums;
    letter-spacing: -0.01em;
  }
  .meter {
    display: flex;
    gap: 2px;
    height: 9px;
    margin-top: var(--sp-3);
  }
  .meter-bar {
    display: block;
    height: 100%;
    border-radius: 2px;
    min-width: 2px;
  }
  .meter-bar.ja {
    background: var(--meter-a);
  }
  .meter-bar.zh {
    background: var(--meter-b);
  }
  .meter-bar.clone.known {
    background: var(--meter-c);
  }
  .meter-bar.empty {
    background: var(--meter-track);
  }
  .meter-bar.clone.empty {
    background: repeating-linear-gradient(
      135deg,
      var(--meter-track) 0 4px,
      transparent 4px 8px
    );
    box-shadow: inset 0 0 0 1px var(--separator-soft);
  }
  .legend {
    display: flex;
    flex-wrap: wrap;
    gap: var(--sp-3);
    margin-top: var(--sp-3);
  }
  .legend-item {
    display: flex;
    align-items: center;
    gap: 6px;
    font-size: var(--fs-label);
    color: var(--text-2);
    font-variant-numeric: tabular-nums;
  }
  .legend-item.muted {
    color: var(--text-3);
  }
  .legend-swatch {
    width: 7px;
    height: 7px;
    border-radius: 2px;
    flex: 0 0 auto;
  }
  .legend-swatch.ja {
    background: var(--meter-a);
  }
  .legend-swatch.zh {
    background: var(--meter-b);
  }
  .legend-swatch.clone {
    background: var(--meter-c);
  }
  .legend-swatch.none {
    background: transparent;
    box-shadow: inset 0 0 0 1px var(--separator);
  }
</style>
