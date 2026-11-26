<script lang="ts">
  /**
   * 「引擎与模型」页顶部的本机总览看板。
   *
   * 三件事：这机器在用什么加速（芯片 / 内存 / MPS）、模型占了多少（按用途分段）、
   * 以及三个快捷动作（首次配置 / 重新检测 / 打开模型根目录）。
   *
   * 芯片型号与物理内存来自主进程 app:info（侧车只有 device/machine），取不到时
   * 退回「Apple Silicon · arm64」这种通用说法，不显示空白。
   */
  import Icon from '../../Icon.svelte';
  import StorageMeter from './StorageMeter.svelte';
  import type { EngineInfo, SettingsPayload } from '../../../lib/api';
  import type { UsageSummary } from '../../../lib/settings/engineMetrics';
  import { chipLabel, ffmpegVersion, hardware, memoryText } from '../../../lib/settings/hardware.svelte';

  let {
    engines,
    usage,
    runtime,
    ffmpeg,
    modelsDir,
    busy = false,
    onSetup,
    onRefresh,
    onOpenModels,
  }: {
    engines: EngineInfo[];
    usage: UsageSummary;
    runtime: SettingsPayload['runtime'] | null;
    ffmpeg: SettingsPayload['ffmpeg'] | null;
    modelsDir: string;
    busy?: boolean;
    onSetup: () => void;
    onRefresh: () => void;
    onOpenModels: () => void;
  } = $props();

  const installedCount = $derived(engines.filter((engine) => engine.installed).length);
  const enabledCount = $derived(engines.filter((engine) => engine.enabled).length);
  const chip = $derived(chipLabel(hardware.info, runtime?.machine ?? ''));
  const arch = $derived(runtime?.machine ?? '');
  const memory = $derived(memoryText(hardware.info?.totalMemBytes ?? 0));
  const isMps = $derived((runtime?.device ?? '').toLowerCase() === 'mps');

  /** 路径只留最后两段：看板里不需要整条绝对路径（「详情」里有完整的）。 */
  function shortPath(value: string): string {
    if (!value) return '—';
    const parts = value.split('/').filter(Boolean);
    return parts.length <= 2 ? value : `…/${parts.slice(-2).join('/')}`;
  }
</script>

<div class="hero">
  <div class="hero-main">
    <div class="hero-id">
      <div class="hero-eyebrow">
        <span class="eyebrow-dot" class:ok={isMps}></span>
        {isMps ? '本机推理就绪' : 'CPU 模式运行'}
      </div>
      <div class="hero-device">
        <b>{chip}</b>
        <span>{arch}{isMps ? ' · MPS 加速' : ''}</span>
      </div>
      <div class="hero-chips">
        <span class="chip" class:ok={isMps} class:warn={!isMps}>
          <b>{isMps ? 'MPS' : (runtime?.device ?? 'CPU')}</b>
          {isMps ? '可用' : '无加速'}
        </span>
        {#if memory}
          <span class="chip"><b>{memory}</b> 内存</span>
        {/if}
        {#if runtime?.python}
          <span class="chip">Python <b>{runtime.python}</b></span>
        {/if}
        {#if ffmpeg?.ok}
          <span class="chip">ffmpeg <b>{ffmpegVersion(ffmpeg.version)}</b></span>
        {:else}
          <span class="chip warn">ffmpeg 未找到</span>
        {/if}
        {#if runtime?.version}
          <span class="chip">v{runtime.version}</span>
        {/if}
      </div>
      <div class="hero-stats">
        <div class="stat">
          <div class="stat-k">已就绪引擎</div>
          <div class="stat-v">{installedCount} / {engines.length}</div>
        </div>
        <div class="stat">
          <div class="stat-k">已启用</div>
          <div class="stat-v">{enabledCount} 个</div>
        </div>
        <div class="stat">
          <div class="stat-k">模型目录</div>
          <div class="stat-v mono" title={modelsDir}>{shortPath(modelsDir)}</div>
        </div>
      </div>
    </div>

    <div class="hero-usage">
      <StorageMeter {usage} />
    </div>
  </div>

  <div class="hero-foot">
    <button class="btn primary" onclick={onSetup}>
      <Icon name="export" size={12} />运行首次配置
    </button>
    <button class="btn" onclick={onRefresh} disabled={busy}>
      <Icon name="refresh" size={12} />{busy ? '检测中…' : '重新检测'}
    </button>
    <button class="btn ghost" onclick={onOpenModels} disabled={!modelsDir}>
      <Icon name="folder" size={12} />打开模型根目录
    </button>
    <span class="foot-note">模型只在本机处理，不上传</span>
  </div>
</div>

<style>
  .hero {
    border: 1px solid var(--hero-border);
    border-radius: var(--rad-hero);
    background: var(--hero-bg);
    box-shadow: var(--bento-shadow);
    overflow: hidden;
  }
  .hero-main {
    display: grid;
    grid-template-columns: minmax(0, 1fr) minmax(300px, 360px);
    gap: var(--sp-8);
    padding: var(--sp-5) var(--sp-6);
  }
  .hero-eyebrow {
    display: flex;
    align-items: center;
    gap: 6px;
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 0.06em;
    color: var(--text-3);
  }
  .eyebrow-dot {
    width: 6px;
    height: 6px;
    border-radius: 50%;
    background: var(--warn);
  }
  .eyebrow-dot.ok {
    background: var(--success);
  }
  .hero-device {
    display: flex;
    align-items: baseline;
    gap: var(--sp-2);
    margin-top: var(--sp-2);
    min-width: 0;
  }
  .hero-device b {
    font-size: var(--fs-hero);
    line-height: var(--lh-hero);
    font-weight: 600;
    letter-spacing: -0.02em;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .hero-device span {
    font-size: var(--fs-ui);
    color: var(--text-2);
    flex: 0 0 auto;
  }
  .hero-chips {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
    margin-top: var(--sp-3);
  }
  .hero-stats {
    display: flex;
    gap: var(--sp-5);
    margin-top: var(--sp-4);
    min-width: 0;
  }
  .stat {
    min-width: 0;
  }
  .stat-k {
    font-size: 11px;
    color: var(--text-3);
  }
  .stat-v {
    font-size: var(--fs-ui);
    font-weight: 500;
    font-variant-numeric: tabular-nums;
    margin-top: 2px;
  }
  .stat-v.mono {
    font-family: var(--font-mono);
    font-size: var(--fs-label);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .hero-usage {
    min-width: 0;
    display: flex;
    flex-direction: column;
  }
  .hero-foot {
    display: flex;
    align-items: center;
    gap: var(--sp-2);
    padding: var(--sp-3) var(--sp-6);
    border-top: 1px solid var(--hero-border);
    background: var(--surface);
  }
  .foot-note {
    margin-left: auto;
    font-size: var(--fs-label);
    color: var(--text-3);
    white-space: nowrap;
  }
  @media (max-width: 1120px) {
    .hero-main {
      grid-template-columns: minmax(0, 1fr);
      gap: var(--sp-5);
    }
    .hero-foot {
      flex-wrap: wrap;
    }
    .foot-note {
      display: none;
    }
  }
</style>
