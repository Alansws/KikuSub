<script lang="ts">
  /**
   * 引擎卡的「详情」抽屉：长路径、HF 仓库、必需文件、备注与次要动作。
   *
   * 这些是技术字段，默认收起——卡片正面只留用途、三条指标与安装状态。
   * 只有**已安装**的引擎才渲染它：未安装时底栏就是「下载模型」主按钮，
   * 不能让「补齐」这个主操作藏在折叠层里。
   */
  import Icon from '../../Icon.svelte';
  import type { EngineInfo } from '../../../lib/api';

  let {
    engine,
    open = false,
    onOpenDir,
    onReveal,
    onVerify,
    verifying = false,
  }: {
    engine: EngineInfo;
    open?: boolean;
    onOpenDir: () => void;
    onReveal: () => void;
    onVerify: () => void;
    verifying?: boolean;
  } = $props();
</script>

<div class="eng-detail" class:open aria-hidden={!open}>
  {#if open}
    <div class="detail-row">
      <span class="detail-k">模型目录</span>
      <span class="detail-v mono" title={engine.model_dir}>{engine.model_dir || '—'}</span>
    </div>
    <div class="detail-row">
      <span class="detail-k">HF 仓库</span>
      <span class="detail-v mono" title={engine.hf_repo}>{engine.hf_repo || '—'}</span>
    </div>
    <div class="detail-row">
      <span class="detail-k">运行时</span>
      <span class="detail-v">{engine.family ?? '—'} · 建议内存 {engine.min_ram_gb} GB</span>
    </div>
    <div class="detail-row">
      <span class="detail-k">说明</span>
      <span class="detail-v detail-multi">{engine.description}</span>
    </div>
    {#if engine.notes}
      <div class="detail-row">
        <span class="detail-k">备注</span>
        <span class="detail-v detail-multi">{engine.notes}</span>
      </div>
    {/if}
    <div class="detail-actions">
      <button class="btn sm" onclick={onOpenDir}>
        <Icon name="folder" size={11} />打开目录
      </button>
      <button class="btn sm ghost" onclick={onReveal}>在访达中显示</button>
      <button class="btn sm ghost" onclick={onVerify} disabled={verifying}>
        {verifying ? '校验中…' : '校验 / 补齐'}
      </button>
    </div>
  {/if}
</div>

<style>
  .eng-detail {
    display: none;
    padding: var(--sp-3) var(--sp-4) var(--sp-4);
    border-top: 1px dashed var(--separator);
    background: var(--fill);
  }
  .eng-detail.open {
    display: block;
  }
  .detail-row {
    display: grid;
    grid-template-columns: 4.6em minmax(0, 1fr);
    gap: var(--sp-2);
    align-items: baseline;
    padding: 3px 0;
    font-size: var(--fs-label);
  }
  .detail-k {
    color: var(--text-3);
  }
  .detail-v {
    color: var(--text-2);
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .detail-v.mono {
    font-family: var(--font-mono);
    font-size: 12px;
  }
  .detail-v.detail-multi {
    white-space: normal;
    line-height: 1.5;
    overflow: visible;
  }
  .detail-actions {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
    margin-top: var(--sp-2);
  }
</style>
