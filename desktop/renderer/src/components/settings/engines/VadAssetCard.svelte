<script lang="ts">
  /**
   * 可选 VAD 切分器权重卡（目前只有 WhisperSeg）。
   *
   * 和引擎卡分开：它不是引擎、不参与启停，只是 Whisper 的一个切分器资产。
   * 未下载时在卡面直接给「下载」；下载中替换底栏为进度，避免设置页跳高。
   */
  import Icon from '../../Icon.svelte';
  import ProgressBar from '../../ProgressBar.svelte';
  import type { VadAsset } from '../../../lib/api';
  import { formatBytes } from '../../../lib/time';

  let {
    asset,
    download = null,
    busy = false,
    onDownload,
    onOpenDir,
  }: {
    asset: VadAsset;
    download?: { percent: number; stage: string; status: 'running' | 'done' | 'error' } | null;
    busy?: boolean;
    onDownload: () => void;
    onOpenDir: () => void;
  } = $props();

  const downloading = $derived(download?.status === 'running');
  const failed = $derived(download?.status === 'error');
  const sizeText = $derived(
    asset.installed
      ? `已就绪 · ${formatBytes(asset.size_bytes)}`
      : `未下载 · 约 ${formatBytes(asset.approx_bytes)}`,
  );
</script>

<article class="vad-card" class:ready={asset.installed}>
  <div class="head">
    <div class="id">
      <div class="name">
        <span class="state-dot" class:ready={asset.installed}></span>
        {asset.label}
      </div>
      <p class="desc">{asset.description}</p>
    </div>
    <span class="badge" class:ready={asset.installed}>
      {asset.installed ? '已就绪' : '可选'}
    </span>
  </div>

  {#if downloading}
    <div class="progress-block">
      <div class="progress-line">
        <span class="stage">{download?.stage || '正在下载…'}</span>
        <span class="pct">{download?.percent ?? 0}%</span>
      </div>
      <ProgressBar percent={download?.percent ?? 0} state="running" label={`下载 ${asset.label}`} />
    </div>
  {:else}
    <div class="foot">
      <span class="size" class:error={failed}>{failed ? '下载失败' : sizeText}</span>
      <button class="link" onclick={onOpenDir} title={asset.model_dir}>
        <Icon name="folder" size={12} /> 目录
      </button>
      <span class="spacer"></span>
      {#if failed}
        <button class="btn sm" disabled={busy} onclick={onDownload}>
          <Icon name="refresh" size={12} /> 重试
        </button>
      {:else if asset.installed}
        <span class="done-hint">转写时自动使用</span>
      {:else}
        <button class="btn sm" disabled={busy} onclick={onDownload}>
          <Icon name="tray" size={12} /> 下载
        </button>
      {/if}
    </div>
  {/if}
</article>

<style>
  .vad-card {
    display: flex;
    flex-direction: column;
    border: 1px solid var(--bento-border);
    border-radius: var(--rad-card);
    background: var(--bento-bg);
    box-shadow: var(--bento-shadow);
    overflow: hidden;
  }
  .head {
    display: flex;
    align-items: flex-start;
    gap: var(--sp-2);
    padding: var(--sp-3) var(--sp-4) var(--sp-2);
  }
  .id {
    min-width: 0;
    flex: 1;
  }
  .name {
    display: flex;
    align-items: center;
    gap: 7px;
    font-size: var(--fs-control);
    font-weight: 600;
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
  .desc {
    margin: 4px 0 0;
    font-size: var(--fs-label);
    color: var(--text-3);
    line-height: 1.5;
  }
  .badge {
    flex: 0 0 auto;
    padding: 2px 7px;
    border-radius: var(--rad-control);
    background: var(--fill);
    color: var(--text-3);
    font-size: 11px;
  }
  .badge.ready {
    background: var(--success-soft);
    color: var(--success);
  }
  .foot {
    display: flex;
    align-items: center;
    gap: var(--sp-2);
    min-height: 42px;
    padding: var(--sp-2) var(--sp-4);
    border-top: 1px solid var(--separator-soft);
  }
  .size {
    font-size: var(--fs-label);
    color: var(--text-3);
    font-variant-numeric: tabular-nums;
  }
  .size.error {
    color: var(--danger);
  }
  .spacer {
    margin-left: auto;
  }
  .link {
    appearance: none;
    border: 0;
    background: transparent;
    font: inherit;
    font-size: var(--fs-label);
    color: var(--text-2);
    display: inline-flex;
    align-items: center;
    gap: 4px;
    height: 24px;
    padding: 0 6px;
    border-radius: var(--rad-control);
  }
  .link:hover {
    background: var(--fill);
    color: var(--text);
  }
  .done-hint {
    font-size: var(--fs-label);
    color: var(--text-3);
  }
  .progress-block {
    min-height: 42px;
    padding: var(--sp-2) var(--sp-4) var(--sp-3);
    border-top: 1px solid var(--separator-soft);
  }
  .progress-line {
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    gap: var(--sp-2);
    margin-bottom: 6px;
    font-size: var(--fs-label);
    color: var(--text-3);
  }
  .stage {
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .pct {
    flex: 0 0 auto;
    font-variant-numeric: tabular-nums;
  }
</style>
