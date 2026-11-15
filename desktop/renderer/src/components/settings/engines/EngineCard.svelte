<script lang="ts">
  /**
   * 单张转写引擎卡（Bento 单元）。
   *
   * 正面只留四件事：名字与用途、三条能力指标、一句备注、安装状态与主操作。
   * 长路径 / HF 仓库 / 「校验 / 补齐」都进「详情」——但**未安装时「下载模型」必须
   * 在底栏明面上**，不能藏进折叠层（否则用户会以为这张卡没有可操作的东西）。
   *
   * 下载进度替换底栏内容（不是追加），底栏高度固定，进度出现时卡片不跳高。
   */
  import Icon from '../../Icon.svelte';
  import ProgressBar from '../../ProgressBar.svelte';
  import CapabilityMeter from './CapabilityMeter.svelte';
  import EngineDetails from './EngineDetails.svelte';
  import type { EngineInfo } from '../../../lib/api';
  import { engineMetrics } from '../../../lib/settings/engineMetrics';
  import { formatBytes } from '../../../lib/time';

  let {
    engine,
    active = false,
    download = null,
    busy = false,
    onToggle,
    onDownload,
    onOpenDir,
    onReveal,
  }: {
    engine: EngineInfo;
    active?: boolean;
    download?: { percent: number; stage: string; status: 'running' | 'done' | 'error' } | null;
    busy?: boolean;
    onToggle: () => void;
    onDownload: () => void;
    onOpenDir: () => void;
    onReveal: () => void;
  } = $props();

  let open = $state(false);

  const metrics = $derived(engineMetrics(engine.key));
  const downloading = $derived(download?.status === 'running');
  const failed = $derived(download?.status === 'error');
  const sizeText = $derived(
    engine.installed ? `已安装 ${formatBytes(engine.size_bytes)}` : `未下载 · ${engine.approx_label}`,
  );
  const primaryDisabled = $derived(busy || !engine.downloadable || downloading);
</script>

<article class="engine-card" class:inuse={active && engine.enabled} class:off={!engine.enabled}>
  <div class="card-body">
    <div class="card-top">
      <div class="card-id">
        <div class="card-name">
          <span class="state-dot" class:ready={engine.installed}></span>
          {engine.label}
        </div>
        <div class="card-purpose">{engine.purpose}</div>
      </div>
      <div class="card-badges">
        {#if active && engine.enabled}
          <span class="live"><i class="live-dot"></i>在用</span>
        {/if}
        <button
          class="switch"
          class:on={engine.enabled}
          role="switch"
          aria-checked={engine.enabled}
          aria-label={`${engine.enabled ? '停用' : '启用'} ${engine.label}`}
          onclick={onToggle}
        >
          <span class="knob"></span>
        </button>
      </div>
    </div>

    {#if metrics.length}
      <div class="caps">
        {#each metrics as metric (metric.key)}
          <CapabilityMeter
            label={metric.label}
            value={metric.value}
            bar={metric.bar}
            tone={metric.tone}
            detail={metric.detail}
          />
        {/each}
      </div>
    {/if}

    {#if engine.description}
      <!-- 卡正面用「一句话定位」；notes 里的实测数字留给「详情」，避免和指标条重复 -->
      <p class="card-note">{engine.description}</p>
    {/if}
  </div>

  {#if downloading}
    <div class="card-progress">
      <div class="progress-line">
        <span class="progress-stage">{download?.stage || '正在下载…'}</span>
        <b>{download?.percent ?? 0}%</b>
      </div>
      <ProgressBar percent={download?.percent ?? 0} state="running" label={`${engine.label} 下载进度`} />
    </div>
  {:else}
    <div class="card-foot">
      <span class="card-size" class:error={failed}>
        {#if failed}
          下载失败
        {:else}
          {sizeText}
        {/if}
      </span>
      <span class="foot-spacer"></span>
      <button
        class="detail-btn"
        class:open
        aria-expanded={open}
        aria-controls={`eng-detail-${engine.key}`}
        onclick={() => (open = !open)}
      >
        详情
        <span class="chev"><Icon name="chevron-down" size={11} /></span>
      </button>
      {#if !engine.installed}
        <button
          class="btn primary"
          disabled={primaryDisabled}
          onclick={onDownload}
          title={engine.downloadable
            ? '下载缺失权重；已安装但缺文件时等价于校验 / 补齐（进度在卡内）'
            : '该引擎需要手动放置权重'}
        >
          <Icon name="export" size={11} />
          {engine.downloadable ? (failed ? '重试下载' : '下载 / 补齐') : '需手动安装'}
        </button>
      {:else if failed}
        <button class="btn primary" disabled={primaryDisabled} onclick={onDownload}>
          <Icon name="refresh" size={11} />重试
        </button>
      {/if}
    </div>
  {/if}

  <div id={`eng-detail-${engine.key}`}>
    <EngineDetails
      {engine}
      {open}
      {onOpenDir}
      {onReveal}
      onVerify={onDownload}
      verifying={downloading}
    />
  </div>
</article>

<style>
  .engine-card {
    position: relative;
    display: flex;
    flex-direction: column;
    border: 1px solid var(--bento-border);
    border-radius: var(--rad-card);
    background: var(--bento-bg);
    box-shadow: var(--bento-shadow);
    overflow: hidden;
    transition:
      border-color var(--dur) var(--ease),
      box-shadow var(--dur) var(--ease),
      background var(--dur) var(--ease);
  }
  .engine-card.inuse {
    border-color: var(--bento-border-on);
    background: var(--bento-bg-on);
    box-shadow: var(--bento-shadow-on);
  }
  /* 停用只降强调，不做灰化：灰掉会被读成「不可用」 */
  .engine-card.off {
    opacity: 0.9;
  }
  .card-body {
    display: flex;
    flex-direction: column;
    flex: 1;
    padding: var(--sp-4) var(--sp-4) var(--sp-3);
  }
  .card-top {
    display: flex;
    align-items: flex-start;
    gap: var(--sp-2);
  }
  .card-id {
    min-width: 0;
    flex: 1;
  }
  .card-name {
    display: flex;
    align-items: center;
    gap: 7px;
    font-size: var(--fs-heading);
    font-weight: 600;
    line-height: var(--lh-heading);
  }
  .card-purpose {
    margin-top: 3px;
    font-size: var(--fs-label);
    color: var(--text-3);
  }
  .state-dot {
    width: 6px;
    height: 6px;
    border-radius: 50%;
    background: var(--text-3);
    flex: 0 0 6px;
  }
  .state-dot.ready {
    background: var(--success);
  }
  .card-badges {
    display: flex;
    align-items: center;
    gap: 6px;
    flex: 0 0 auto;
  }
  .live {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    height: 20px;
    padding: 0 7px;
    border-radius: var(--rad-control);
    background: var(--accent-soft);
    color: var(--accent);
    font-size: 11px;
    font-weight: 600;
  }
  .live-dot {
    width: 5px;
    height: 5px;
    border-radius: 50%;
    background: var(--accent);
    box-shadow: 0 0 0 3px var(--accent-soft);
  }
  .caps {
    display: flex;
    flex-direction: column;
    gap: var(--sp-2);
    margin-top: var(--sp-4);
  }
  .card-note {
    margin: var(--sp-3) 0 0;
    font-size: var(--fs-label);
    color: var(--text-3);
    line-height: 1.5;
    display: -webkit-box;
    -webkit-line-clamp: 2;
    line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
  }

  .card-foot {
    display: flex;
    align-items: center;
    gap: var(--sp-2);
    /* 固定高度：进度块替换它时卡片不跳高 */
    min-height: 44px;
    padding: var(--sp-2) var(--sp-4);
    border-top: 1px solid var(--separator-soft);
    margin-top: auto;
  }
  .card-size {
    font-size: var(--fs-label);
    color: var(--text-3);
    font-variant-numeric: tabular-nums;
    white-space: nowrap;
  }
  .card-size.error {
    color: var(--danger);
  }
  .foot-spacer {
    margin-left: auto;
  }
  .detail-btn {
    appearance: none;
    border: 0;
    background: transparent;
    font: inherit;
    font-size: var(--fs-label);
    color: var(--text-2);
    display: inline-flex;
    align-items: center;
    gap: var(--sp-1);
    height: 24px;
    padding: 0 6px;
    border-radius: var(--rad-control);
  }
  .detail-btn:hover {
    background: var(--fill);
    color: var(--text);
  }
  .chev {
    display: grid;
    place-items: center;
    transition: transform var(--dur) var(--ease);
  }
  .detail-btn.open .chev {
    transform: rotate(180deg);
  }

  .card-progress {
    min-height: 44px;
    padding: var(--sp-2) var(--sp-4) var(--sp-3);
    border-top: 1px solid var(--separator-soft);
    margin-top: auto;
  }
  .progress-line {
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    gap: var(--sp-2);
    font-size: var(--fs-label);
    color: var(--text-2);
    margin-bottom: var(--sp-1);
  }
  .progress-stage {
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .progress-line b {
    color: var(--text);
    font-weight: 600;
    font-variant-numeric: tabular-nums;
  }
</style>
