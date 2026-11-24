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
  import Icon from '../components/Icon.svelte';
  import SettingsNav from '../components/settings/SettingsNav.svelte';
  import EngineTab from './settings/EngineTab.svelte';
  import AppearanceTab from './settings/AppearanceTab.svelte';
  import AiTab from './settings/AiTab.svelte';
  import EnvironmentTab from './settings/EnvironmentTab.svelte';
  import { app, loadSettings, loadTtsVoices, settings, tts } from '../lib/store.svelte';
  import { closeSettings } from '../lib/settingsOverlay.svelte';
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

<!-- 设置是**浮层**，不是一页（2026-11-24 方案 A）：⌘, 或左栏「设置」把它压在
     当前页面之上，关掉就回到原处——不再有「双侧栏同屏」的套娃，也不打断核对台。 -->
<div class="set-overlay" role="presentation">
  <button class="set-scrim" aria-label="关闭设置" onclick={() => closeSettings()}></button>

  <div class="set-sheet" role="dialog" aria-modal="true" aria-label="设置">
    <div class="set-sheet-bar">
      <span class="set-sheet-title">设置</span>
      <span class="set-sheet-meta">{installedCount} / {engines.length} 个引擎就绪 · {enabledCount} 个已启用</span>
      <button class="set-close" onclick={() => closeSettings()} title="关闭（Esc）" aria-label="关闭设置">
        <Icon name="close" size={11} />
      </button>
    </div>

    <div class="set-body">
      <SettingsNav {tab} engineCount={engines.length} onchange={select} />

      <div class="set-content settings">
      {#if tab === 'engines'}
        <div id="set-pane-engines" class="pane" role="tabpanel" aria-labelledby="set-tab-engines">
          <EngineTab />
        </div>
      {:else if tab === 'appearance'}
        <div
          id="set-pane-appearance"
          class="pane"
          role="tabpanel"
          aria-labelledby="set-tab-appearance"
        >
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

      <div class="about">
        KikuSub · 本地优先的日语字幕工作台。所有音视频与模型都在本机处理，不上传。
      </div>
      </div>
    </div>
  </div>
</div>

<style>
  /* ---------------- 浮层外壳 ---------------- */
  .set-overlay {
    position: fixed;
    inset: 0;
    z-index: 240;
    display: grid;
    place-items: center;
    padding: var(--sp-6);
  }
  /* 点遮罩关闭；它自己不参与布局，也不抢焦点环 */
  .set-scrim {
    position: absolute;
    inset: 0;
    border: 0;
    padding: 0;
    margin: 0;
    background: rgba(13, 20, 36, 0.28);
    backdrop-filter: blur(2px);
    -webkit-backdrop-filter: blur(2px);
    cursor: default;
    animation: scrimIn 140ms var(--ease) both;
  }
  @keyframes scrimIn {
    from {
      opacity: 0;
    }
  }

  /* 居中偏好窗：820×580，最高不超过视口；内容区自己滚，窗框不滚。 */
  .set-sheet {
    position: relative;
    width: min(820px, 100%);
    height: min(580px, 100%);
    display: flex;
    flex-direction: column;
    overflow: hidden;
    border-radius: 10px;
    background: var(--sheet-bg);
    border: 1px solid var(--sheet-line);
    box-shadow: var(--shadow-pop);
    animation: sheetIn 160ms var(--ease) both;
  }
  @keyframes sheetIn {
    from {
      opacity: 0;
      transform: translateY(6px) scale(0.995);
    }
  }

  /* 一行标题栏取代原来 ~100px 的大字页眉 */
  .set-sheet-bar {
    flex: 0 0 auto;
    display: flex;
    align-items: center;
    gap: var(--sp-3);
    height: 38px;
    padding: 0 var(--sp-3) 0 var(--sp-5);
    border-bottom: 1px solid var(--sheet-line);
  }
  .set-sheet-title {
    font-size: var(--fs-body);
    line-height: 18px;
    font-weight: 600;
    white-space: nowrap;
  }
  .set-sheet-meta {
    margin-left: auto;
    font-size: var(--fs-label);
    color: var(--text-3);
    font-variant-numeric: tabular-nums;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .set-close {
    appearance: none;
    flex: 0 0 auto;
    width: 22px;
    height: 22px;
    padding: 0;
    border: 0;
    border-radius: 5px;
    background: transparent;
    color: var(--text-3);
    display: grid;
    place-items: center;
  }
  .set-close:hover {
    background: var(--fill);
    color: var(--text);
  }
  .set-close:focus-visible {
    outline: 2px solid var(--accent-ring);
    outline-offset: -2px;
  }

  /* 唯一一套左右分栏：196px 通高浅灰类别栏 + 1px 竖线 + 内容区 */
  .set-body {
    flex: 1;
    min-height: 0;
    display: grid;
    grid-template-columns: 196px minmax(0, 1fr);
  }
  .set-body > :global(.set-nav) {
    padding: var(--sp-3) var(--sp-2);
    background: var(--sheet-rail);
    border-right: 1px solid var(--sheet-line);
    overflow-y: auto;
  }

  /* 内容区：浅灰画布，卡片浮在上面 */
  .set-content {
    min-width: 0;
    display: flex;
    flex-direction: column;
    overflow-y: auto;
    padding: var(--sp-4) var(--sp-5) var(--sp-6);
    background: var(--sheet-canvas);
    /* 内容不足一屏时不要把最后一个区块拉满剩余高度（会把画布盖成一条白带） */
    align-content: start;
    /* 浮层里的可用宽度与窗口无关（820 窗 - 196 类别栏 ≈ 620）。
       所以设置子树里的断点必须问「我的容器多宽」，不能问视口 —— 否则
       1440 的窗口会命中 max-width:1120 之外的桌面版布局，把标签挤成竖排。 */
    container-type: inline-size;
    container-name: sheet;
  }
  .pane {
    min-width: 0;
  }
  .about {
    margin-top: var(--sp-6);
    padding-top: var(--sp-3);
    border-top: 1px solid var(--sheet-line);
    font-size: 11px;
    color: var(--text-3);
    text-align: center;
  }

  @media (max-width: 1120px) {
    .set-overlay {
      padding: var(--sp-4);
    }
    .set-body {
      grid-template-columns: 168px minmax(0, 1fr);
    }
  }
  /* 窄窗（1100×760 及以下）：窗体贴满可用高度，类别栏再收一点 */
  @media (max-width: 900px) {
    .set-overlay {
      padding: var(--sp-2);
    }
    .set-sheet {
      width: 100%;
      height: 100%;
    }
    .set-body {
      grid-template-columns: 148px minmax(0, 1fr);
    }
    .set-content {
      padding: var(--sp-3) var(--sp-4) var(--sp-5);
    }
  }
</style>
