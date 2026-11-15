<script lang="ts">
  /**
   * 单源 / 双源开关（润色、断句重排共用）。
   *
   * B 不存在时按钮置灰，并给一个「导入 B…」的引导：两个页面都不该让用户
   * 为了加一份参考稿先切去双引擎复核页。条数徽标只在有稿时显示，避免顶栏
   * 出现「A 0 · B 0」这种没有信息量的装饰。
   */
  let {
    source,
    hasB,
    aCount,
    bCount,
    bLabel = '第二版',
    dualLabel = '双源',
    onchange,
    onimport,
  }: {
    source: 'single' | 'dual';
    hasB: boolean;
    aCount: number;
    bCount: number;
    bLabel?: string;
    dualLabel?: string;
    onchange: (next: 'single' | 'dual') => void;
    onimport?: () => void;
  } = $props();

  const countsTitle = $derived(
    hasB
      ? `A 核对台 ${aCount} 条 · B ${bLabel} ${bCount} 条`
      : `A 核对台 ${aCount} 条；还没有第二版字幕`,
  );
</script>

<div class="aiw-source">
  <div class="seg" role="group" aria-label="底稿来源">
    <button
      class:on={source === 'single'}
      aria-pressed={source === 'single'}
      onclick={() => onchange('single')}
      title="只吃核对台当前版本"
    >单源</button>
    <button
      class:on={source === 'dual'}
      aria-pressed={source === 'dual'}
      onclick={() => onchange('dual')}
      disabled={!hasB}
      title={hasB ? `同时参考 B（${bLabel}，${bCount} 条）` : '还没有第二版字幕：可转写或导入一份'}
    >{dualLabel}</button>
  </div>
  <span class="aiw-count" title={countsTitle}>
    <b>A</b>&nbsp;{aCount}
    {#if hasB}
      <span class="aiw-count-sep">·</span>
      <b>B</b>&nbsp;{bCount}
    {/if}
  </span>
  {#if !hasB && onimport}
    <button class="aiw-link" onclick={onimport} title="导入一份已经做好的 SRT / VTT 作为第二版">
      导入 B…
    </button>
  {/if}
</div>
