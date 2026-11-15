<script lang="ts">
  /**
   * 「环境与诊断」页签：三张指标卡 + 路径管理（3 条明面 / 8 条折叠）+ 日志诊断（原文默认收起）。
   *
   * 这一页做减法：原来 5 行键值对 + 11 条路径 + 120 行日志平铺，现在首屏只剩
   * 「硬件是否就绪、交付物写在哪、出问题看哪里」三件事。
   */
  import Icon from '../../components/Icon.svelte';
  import SettingsSection from '../../components/settings/SettingsSection.svelte';
  import HardwareMetrics from '../../components/settings/env/HardwareMetrics.svelte';
  import PathManager from '../../components/settings/env/PathManager.svelte';
  import LogPanel from '../../components/settings/env/LogPanel.svelte';
  import { diagnostics, loadDiagnostics, sizeText } from '../../lib/settings/diagnostics.svelte';

  const diag = $derived(diagnostics.data);
  const logMeta = $derived(
    diag
      ? `日志 ${sizeText(diag.log_bytes)} · 最近问题 ${diag.recent_problems.length} 条`
      : '',
  );
</script>

<div class="sections">
  <SettingsSection
    title="运行环境"
    caption="硬件加速与外部依赖；任一项不可用会直接影响导入或转写。"
    meta={diagnostics.loading ? '读取中…' : ''}
  >
    <HardwareMetrics />
    {#if diagnostics.data === null && !diagnostics.loading}
      <div class="env-error">
        <Icon name="warn" size={13} />
        诊断信息读取失败，内核可能还没连上。
        <button class="btn sm" onclick={() => loadDiagnostics()}>重试</button>
      </div>
    {/if}
  </SettingsSection>

  <SettingsSection
    title="路径管理"
    caption="只有交付物相关的三个目录可以改；其余内部路径只读，需要时展开查看。"
  >
    <PathManager />
  </SettingsSection>

  <SettingsSection
    title="日志与诊断"
    caption="遇到问题先点「复制精简诊断」：它包含版本、目录、引擎状态与最近问题，体积控制在一屏以内。"
    meta={logMeta}
  >
    <LogPanel />
  </SettingsSection>
</div>

<style>
  .sections {
    display: flex;
    flex-direction: column;
    gap: var(--sp-8);
  }
  .env-error {
    display: flex;
    align-items: center;
    gap: 6px;
    margin-top: var(--sp-3);
    padding: var(--sp-2) var(--sp-3);
    border-radius: var(--rad-card);
    background: var(--danger-soft);
    color: var(--danger);
    font-size: var(--fs-label);
  }
  .env-error .btn {
    margin-left: auto;
  }
</style>
