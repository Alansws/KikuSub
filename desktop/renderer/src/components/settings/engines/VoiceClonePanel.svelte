<script lang="ts">
  /**
   * 音色克隆（OmniVoice）：横向特色卡，与 ASR 转写引擎区隔开。
   *
   * 它解决的是另一个问题（用片中角色的声线朗读日文），所以不放进 Bento 网格，
   * 而是单独一层：左边身份、中间三步流程、右边状态与动作。
   */
  import Icon from '../../Icon.svelte';
  import ProgressBar from '../../ProgressBar.svelte';
  import { tts } from '../../../lib/store.svelte';
  import {
    onDownloadTts,
    ttsBarState,
    ttsPercent,
    ttsPrefs,
    ttsProgressVisible,
    ttsRightText,
    ttsStageLine,
  } from '../../../lib/settings/ttsPrefs.svelte';

  let { onOpenDir }: { onOpenDir: () => void } = $props();

  const installed = $derived(Boolean(tts.engine?.installed));
  const packageReady = $derived(Boolean(tts.engine?.package_installed));
  const running = $derived(tts.download?.status === 'running');
  const percent = $derived(ttsPercent());
  const barState = $derived(ttsBarState());
  const rightText = $derived(ttsRightText());
  const stageLine = $derived(ttsStageLine());
  const showProgress = $derived(ttsProgressVisible());
</script>

<div class="feature">
  <div class="feature-id">
    <span class="feature-glyph"><Icon name="mic" size={17} /></span>
    <div class="feature-copy">
      <div class="feature-name">
        <span class="state-dot" class:ready={installed}></span>
        OmniVoice
      </div>
      <div class="feature-purpose">零样本克隆 · 可选</div>
    </div>
  </div>

  <div class="feature-flow" aria-label="使用步骤">
    <span class="step"><span class="step-n">1</span>切 <b>3–10s</b> 音频</span>
    <span class="step-arrow"><Icon name="chevron-right" size={12} /></span>
    <span class="step"><span class="step-n">2</span>克隆声线</span>
    <span class="step-arrow"><Icon name="chevron-right" size={12} /></span>
    <span class="step"><span class="step-n">3</span>朗读日文</span>
  </div>

  <div class="feature-act">
    <span class="status-chip" class:ok={installed}>
      {installed ? '已安装' : (tts.engine?.approx_label ?? '约 3.3 GB')}
    </span>
    <div class="feature-buttons">
      {#if installed}
        <button class="btn" onclick={onOpenDir}>
          <Icon name="folder" size={11} />打开模型目录
        </button>
        <button class="btn ghost" onclick={onDownloadTts} disabled={running || ttsPrefs.checking}>
          {ttsPrefs.checking ? '校验中…' : '校验 / 补齐'}
        </button>
      {:else}
        <button class="btn primary" onclick={onDownloadTts} disabled={running || !packageReady}>
          <Icon name="export" size={11} />
          {packageReady ? '下载模型' : '依赖缺失'}
        </button>
      {/if}
    </div>
    <span class="feature-hint">
      {#if tts.engine && !tts.engine.package_installed}
        当前构建缺少 omnivoice 依赖，只能使用系统语音
      {:else}
        首次合成才加载权重，空闲 5 分钟卸载
      {/if}
    </span>
  </div>
</div>

{#if showProgress}
  <div class="feature-progress">
    <div class="progress-line">
      <span class="progress-stage">{stageLine}</span>
      <b>{rightText}</b>
    </div>
    <ProgressBar {percent} state={barState} label="OmniVoice 校验与下载进度" />
  </div>
{/if}

<style>
  .feature {
    /* 两行网格：第一行「身份 + 状态/动作」，第二行「三步流程」整宽。
       原来是三列 `1fr | 1.5fr | auto`：浮层内容栏只有 ~573px 时，
       auto 列（两个按钮 + 状态）吃掉 211px，剩下 274px 要分给 1fr / 1.5fr，
       步骤列被压到 163px 而内容要 328px —— 直接溢出盖住按钮。
       流程链单独占一整行后，525px 的内宽放得下 328px 的三步。 */
    display: grid;
    grid-template-columns: minmax(0, 1fr) auto;
    grid-template-areas:
      'id act'
      'flow flow';
    align-items: start;
    gap: var(--sp-3) var(--sp-5);
    padding: var(--sp-4) var(--sp-5);
    border: 1px solid var(--bento-border);
    border-radius: var(--rad-card);
    background: var(--bento-bg);
    box-shadow: var(--bento-shadow);
  }
  .feature-id {
    grid-area: id;
    display: flex;
    align-items: center;
    gap: var(--sp-3);
    min-width: 0;
  }
  .feature-glyph {
    width: 34px;
    height: 34px;
    flex: 0 0 34px;
    border-radius: var(--rad-control);
    background: var(--accent-soft);
    color: var(--accent);
    display: grid;
    place-items: center;
  }
  .feature-copy {
    min-width: 0;
  }
  .feature-name {
    display: flex;
    align-items: center;
    gap: 7px;
    font-size: var(--fs-heading);
    font-weight: 600;
    line-height: var(--lh-heading);
  }
  .feature-purpose {
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
  .feature-flow {
    grid-area: flow;
    display: flex;
    align-items: center;
    gap: 6px;
    /* 三步链最长 ~328px；放不下时**自己折行**，不许溢出压到右侧按钮上。
       （2026-11-24 实测：浮层内容栏 573px 时这一列只有 163px，第三步
        「3 朗读日文」直接盖住了「打开模型目录」。） */
    flex-wrap: wrap;
    min-width: 0;
  }
  .step {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    height: 26px;
    padding: 0 7px;
    border-radius: var(--rad-control);
    background: var(--fill);
    color: var(--text-2);
    font-size: var(--fs-label);
    white-space: nowrap;
  }
  .step b {
    color: var(--text);
    font-weight: 600;
  }
  .step-n {
    width: 15px;
    height: 15px;
    border-radius: 50%;
    background: var(--raise);
    box-shadow: inset 0 0 0 1px var(--separator);
    display: grid;
    place-items: center;
    font-size: 10px;
    color: var(--text-2);
  }
  .step-arrow {
    color: var(--text-3);
    display: grid;
    place-items: center;
    flex: 0 0 auto;
  }
  .feature-act {
    grid-area: act;
    display: flex;
    flex-direction: column;
    align-items: flex-end;
    gap: var(--sp-2);
    flex: 0 0 auto;
  }
  .status-chip {
    display: inline-flex;
    align-items: center;
    height: 22px;
    padding: 0 var(--sp-2);
    border-radius: var(--rad-control);
    background: var(--warn-soft);
    color: var(--warn);
    font-size: var(--fs-label);
    white-space: nowrap;
  }
  .status-chip.ok {
    background: var(--success-soft);
    color: var(--success);
  }
  .feature-buttons {
    display: flex;
    gap: 6px;
  }
  .feature-hint {
    font-size: 11px;
    color: var(--text-3);
    text-align: right;
  }
  .feature-progress {
    margin-top: var(--sp-2);
    padding: var(--sp-2) var(--sp-1) 0;
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
  /* 内容栏再窄（≤520px 容器）：动作列也压不动了，整张卡改成竖排三段。 */
  @container sheet (max-width: 520px) {
    .feature {
      grid-template-columns: minmax(0, 1fr);
      grid-template-areas:
        'id'
        'flow'
        'act';
      gap: var(--sp-3);
    }
    .feature-act {
      align-items: flex-start;
    }
    .feature-hint {
      text-align: left;
    }
  }
</style>
