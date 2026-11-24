<script lang="ts">
  /**
   * 运行环境的三张指标卡：硬件加速 / Python / ffmpeg。
   *
   * 任一项不可用会直接影响导入或转写（ffmpeg 缺失时导入会失败），所以失败态
   * 用 warn 底色整卡提示，而不是只在数字后面加一行小字。
   */
  import Icon from '../../Icon.svelte';
  import { diagnostics } from '../../../lib/settings/diagnostics.svelte';
  import {
    chipLabel,
    ffmpegVersion,
    hardware,
    memoryText,
  } from '../../../lib/settings/hardware.svelte';

  const runtime = $derived(diagnostics.data?.runtime ?? null);
  const ffmpeg = $derived(diagnostics.data?.ffmpeg ?? null);
  const device = $derived((runtime?.device ?? '').toLowerCase());
  const isMps = $derived(device === 'mps');
  const chip = $derived(chipLabel(hardware.info, runtime?.machine ?? ''));
  const memory = $derived(memoryText(hardware.info?.totalMemBytes ?? 0));
</script>

<div class="metrics">
  <div class="metric">
    <div class="metric-top">
      <span class="metric-icon"><Icon name="chip" size={12} /></span>硬件加速
    </div>
    <div class="metric-v">{isMps ? 'MPS' : (runtime?.device ?? '—')}</div>
    <div class="metric-sub">
      {chip}{#if memory} · {memory}{/if}{#if runtime?.machine} · {runtime.machine}{/if}
    </div>
  </div>

  <div class="metric">
    <div class="metric-top">
      <span class="metric-icon"><Icon name="doc" size={12} /></span>Python
    </div>
    <div class="metric-v">{runtime?.python ?? '—'}</div>
    <div class="metric-sub">{runtime?.frozen ? '打包运行' : '源码模式'} · v{runtime?.version ?? '—'}</div>
  </div>

  <div class="metric" class:warn={ffmpeg ? !ffmpeg.ok : false}>
    <div class="metric-top">
      <span class="metric-icon"><Icon name="wave" size={12} /></span>ffmpeg
    </div>
    <div class="metric-v">{ffmpeg?.ok ? ffmpegVersion(ffmpeg.version) : '未找到'}</div>
    <div class="metric-sub path" title={ffmpeg?.path ?? ''}>
      {ffmpeg?.ok ? ffmpeg.path : '导入会失败：先安装 ffmpeg'}
    </div>
  </div>
</div>

<style>
  .metrics {
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: var(--sp-3);
  }
  .metric {
    display: flex;
    flex-direction: column;
    gap: 3px;
    min-width: 0;
    padding: var(--sp-3) var(--sp-4);
    border: 1px solid var(--bento-border);
    border-radius: var(--rad-card);
    background: var(--bento-bg);
    box-shadow: var(--bento-shadow);
  }
  .metric.warn {
    border-color: var(--warn);
    background: var(--warn-soft);
  }
  .metric-top {
    display: flex;
    align-items: center;
    gap: 6px;
    font-size: 11px;
    color: var(--text-3);
  }
  .metric.warn .metric-top,
  .metric.warn .metric-v {
    color: var(--warn);
  }
  .metric-icon {
    display: grid;
    place-items: center;
  }
  .metric-v {
    font-size: var(--fs-heading);
    font-weight: 600;
    letter-spacing: -0.01em;
    font-variant-numeric: tabular-nums;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .metric-sub {
    font-size: var(--fs-label);
    color: var(--text-3);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .metric-sub.path {
    font-family: var(--font-mono);
    font-size: 11px;
  }
  @container sheet (max-width: 560px) {
    .metrics {
      grid-template-columns: minmax(0, 1fr);
    }
  }
</style>
