<script lang="ts">
  /**
   * 设置：四个页签（引擎与模型 / 外观与朗读 / AI 与技能 / 环境与诊断）。
   *
   * 这个文件只做骨架：页头、页签、四个 pane 的条件渲染，以及"连上内核时把四个域
   * 各拉一次"。各域的状态与动作在 `lib/settings/*`，页面内容在 `views/settings/*`，
   * Bento 卡与 Inset 列表在 `components/settings/*`。
   *
   * 页签记忆走 localStorage（`kikusub.settingsTab`）：⌘, 回来时停在上次那一页。
   * 侧栏的 ⌘1–⌘8 主导航不受影响。
   */
  import PageHeader from '../components/PageHeader.svelte';
  import SettingsTabs from '../components/settings/SettingsTabs.svelte';
  import EngineTab from './settings/EngineTab.svelte';
  import AppearanceTab from './settings/AppearanceTab.svelte';
  import AiTab from './settings/AiTab.svelte';
  import EnvironmentTab from './settings/EnvironmentTab.svelte';
  import { app, loadSettings, loadTtsVoices, settings, tts } from '../lib/store.svelte';
  import { readSettingsTab, saveSettingsTab, type SettingsTabId } from '../lib/settings/tabs';
  import { loadAiConfig } from '../lib/settings/aiConfig.svelte';
  import { loadDiagnostics } from '../lib/settings/diagnostics.svelte';
  import { loadSkill } from '../lib/settings/skill.svelte';
  import { loadCli } from '../lib/settings/cli.svelte';
  import { loadHardware } from '../lib/settings/hardware.svelte';
  import { clearTtsTimer, syncTtsDownloadState } from '../lib/settings/ttsPrefs.svelte';
  import { onDestroy } from 'svelte';

  let tab = $state<SettingsTabId>(readSettingsTab());
  let wasConnected = false;

  const engines = $derived(settings.data?.engines ?? []);
  const installedCount = $derived(engines.filter((engine) => engine.installed).length);
  const enabledCount = $derived(engines.filter((engine) => engine.enabled).length);

  // 内核重启（改模型目录 / 崩溃恢复）后重新拉设置，否则路径与安装状态还是旧的。
  $effect(() => {
    if (!app.connected) {
      wasConnected = false;
      return;
    }
    if (wasConnected) return;
    wasConnected = true;
    void loadSettings(true);
    void loadDiagnostics(120);
    void loadAiConfig();
    void loadSkill();
    void loadCli();
    void loadTtsVoices();
    void loadHardware(true);
  });

  // 下载进度来自 store 的轮询；这里只做「状态机 → 完成/失败闪一下」。
  // 先读一下 status，effect 才会在下载状态变化时重跑。
  $effect(() => {
    const status = tts.download?.status ?? 'idle';
    void status;
    syncTtsDownloadState();
  });

  onDestroy(clearTtsTimer);

  function select(id: SettingsTabId) {
    tab = id;
    saveSettingsTab(id);
  }
</script>

<div class="settings">
  <PageHeader
    title="设置"
    subtitle="引擎与模型、外观与朗读、AI 与技能、环境与诊断。"
  >
    <div class="head-meta">
      <span>{installedCount} / {engines.length} 个引擎已就绪</span>
      <span>·</span>
      <span>{enabledCount} 个已启用</span>
      <kbd class="head-key" title="⌘, 可从任意页面回到设置">⌘,</kbd>
    </div>
  </PageHeader>

  <SettingsTabs {tab} engineCount={engines.length} onchange={select} />

  {#if tab === 'engines'}
    <div id="set-pane-engines" class="pane" role="tabpanel" aria-labelledby="set-tab-engines">
      <EngineTab />
    </div>
  {:else if tab === 'appearance'}
    <div id="set-pane-appearance" class="pane" role="tabpanel" aria-labelledby="set-tab-appearance">
      <AppearanceTab />
    </div>
  {:else if tab === 'ai'}
    <div id="set-pane-ai" class="pane" role="tabpanel" aria-labelledby="set-tab-ai">
      <AiTab />
    </div>
  {:else}
    <div id="set-pane-env" class="pane" role="tabpanel" aria-labelledby="set-tab-env">
      <EnvironmentTab />
    </div>
  {/if}

  <div class="about">KikuSub · 本地优先的日语字幕工作台。所有音视频与模型都在本机处理，不上传。</div>
</div>

<style>
  .settings {
    flex: 1;
    min-height: 0;
    overflow-y: auto;
    padding: var(--sp-8) var(--sp-10) var(--sp-12);
    display: grid;
    grid-template-columns: minmax(0, 1000px);
    justify-content: center;
    align-content: start;
  }
  .head-meta {
    display: flex;
    align-items: center;
    gap: 6px;
    font-size: var(--fs-label);
    color: var(--text-3);
    font-variant-numeric: tabular-nums;
    white-space: nowrap;
  }
  .head-key {
    margin-left: 6px;
    padding: 1px 6px;
    border: 1px solid var(--line);
    border-radius: 5px;
    background: var(--bg-content);
    color: var(--text-3);
    font-family: var(--font-sans);
    font-size: 11.5px;
    line-height: 16px;
  }
  .pane {
    min-width: 0;
  }
  .about {
    margin-top: var(--sp-10);
    padding-top: var(--sp-3);
    border-top: 1px solid var(--separator-soft);
    font-size: var(--fs-label);
    color: var(--text-3);
    text-align: center;
  }
  @media (max-width: 1120px) {
    .settings {
      padding: var(--sp-6) var(--sp-6) var(--sp-10);
    }
  }
</style>
