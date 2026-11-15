<script lang="ts">
  /**
   * 「引擎与模型」页签：本机总览看板 + 日语主力 / 中文可选两组 Bento + 音色克隆。
   *
   * 卡片数据全部来自 `core/engines.py` 的注册表（EngineInfo），这里不做引擎 key 白名单；
   * 分组只用来决定展示顺序（日语两个在前，中文两个在后）。
   */
  import Icon from '../../components/Icon.svelte';
  import EngineSetup from '../../components/EngineSetup.svelte';
  import SettingsSection from '../../components/settings/SettingsSection.svelte';
  import EngineOverviewBoard from '../../components/settings/engines/EngineOverviewBoard.svelte';
  import EngineCard from '../../components/settings/engines/EngineCard.svelte';
  import VoiceClonePanel from '../../components/settings/engines/VoiceClonePanel.svelte';
  import {
    app,
    downloadEngine,
    loadSettings,
    loadTtsVoices,
    settings,
    toggleEngine,
    tts,
  } from '../../lib/store.svelte';
  import { diagnostics } from '../../lib/settings/diagnostics.svelte';
  import {
    GROUP_CAPTIONS,
    engineGroupOf,
    usageSummary,
    type UsageInput,
  } from '../../lib/settings/engineMetrics';
  import { openPath } from '../../lib/settings/paths.svelte';

  let showEngineSetup = $state(false);

  const engines = $derived(settings.data?.engines ?? []);
  const jaEngines = $derived(engines.filter((engine) => engineGroupOf(engine.key) === 'ja'));
  const zhEngines = $derived(engines.filter((engine) => engineGroupOf(engine.key) === 'zh'));
  const enabledCount = $derived(engines.filter((engine) => engine.enabled).length);

  const usageInputs = $derived<UsageInput[]>(
    engines.map((engine) => ({
      key: engine.key,
      installed: engine.installed,
      sizeBytes: engine.size_bytes,
    })),
  );
  const usage = $derived(usageSummary(usageInputs, Boolean(tts.engine?.installed)));
  const modelsDir = $derived(
    settings.data?.paths.models_dir ?? diagnostics.data?.paths.models_dir ?? '',
  );
  const busy = $derived(
    Boolean(settings.download && settings.download.status === 'running') || settings.loading,
  );

  function downloadOf(key: string) {
    const download = settings.download;
    return download && download.key === key ? download : null;
  }

  function statusFor(list: typeof engines): string {
    if (!list.length) return '';
    const installed = list.filter((engine) => engine.installed).length;
    const enabled = list.filter((engine) => engine.enabled).length;
    return `${installed} 个已安装 · ${enabled} 个启用`;
  }

  function onRefresh() {
    void loadSettings(true);
    void loadTtsVoices();
  }
</script>

<EngineOverviewBoard
  {engines}
  {usage}
  runtime={settings.data?.runtime ?? diagnostics.data?.runtime ?? null}
  ffmpeg={settings.data?.ffmpeg ?? diagnostics.data?.ffmpeg ?? null}
  {modelsDir}
  {busy}
  onSetup={() => (showEngineSetup = true)}
  {onRefresh}
  onOpenModels={() => openPath(modelsDir)}
/>

{#if settings.error}
  <div class="load-error">
    <Icon name="warn" size={13} />
    读取失败：{settings.error}
    <button class="btn sm" onclick={() => loadSettings(true)}>重试</button>
  </div>
{:else if settings.loading && !settings.data}
  <p class="load-hint">正在读取引擎配置…</p>
{/if}

<div class="sections">
  <SettingsSection
    title="日语主力引擎"
    caption={GROUP_CAPTIONS.ja}
    meta={statusFor(jaEngines)}
    layout="grid2"
  >
    {#each jaEngines as engine (engine.key)}
      <EngineCard
        {engine}
        active={app.engine === engine.key}
        download={downloadOf(engine.key)}
        {busy}
        onToggle={() => toggleEngine(engine.key, !engine.enabled)}
        onDownload={() => downloadEngine(engine.key)}
        onOpenDir={() => openPath(engine.model_dir)}
        onReveal={() => window.kikusub.revealInFinder(engine.model_dir)}
      />
    {/each}
  </SettingsSection>

  <SettingsSection
    title="中文可选引擎"
    caption={GROUP_CAPTIONS.zh}
    meta={statusFor(zhEngines)}
    layout="grid2"
  >
    {#each zhEngines as engine (engine.key)}
      <EngineCard
        {engine}
        active={app.engine === engine.key}
        download={downloadOf(engine.key)}
        {busy}
        onToggle={() => toggleEngine(engine.key, !engine.enabled)}
        onDownload={() => downloadEngine(engine.key)}
        onOpenDir={() => openPath(engine.model_dir)}
        onReveal={() => window.kikusub.revealInFinder(engine.model_dir)}
      />
    {/each}
  </SettingsSection>

  <SettingsSection
    title="音色克隆"
    caption="与转写引擎分开的可选层：从视频任意一句切 3–10 秒参考音频，用本机克隆声线朗读日文。"
  >
    <VoiceClonePanel onOpenDir={() => openPath(tts.engine?.model_dir ?? '')} />
  </SettingsSection>
</div>

{#if enabledCount === 0 && engines.length}
  <div class="note-box warn">
    <span class="note-icon"><Icon name="warn" size={13} /></span>
    <span>当前没有启用任何引擎——转写页会无法开始。至少打开一个开关。</span>
  </div>
{/if}

<p class="eng-footnote">
  模型目录：<span class="eng-path" title={modelsDir}>{modelsDir || '—'}</span>
  （可在「环境与诊断」里更改）。
</p>

{#if showEngineSetup}
  <EngineSetup
    ondone={() => {
      showEngineSetup = false;
      void loadSettings(true);
      void loadTtsVoices();
    }}
  />
{/if}

<style>
  .sections {
    display: flex;
    flex-direction: column;
    gap: var(--sp-8);
    margin-top: var(--sp-8);
  }
  .load-error {
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
  .load-error .btn {
    margin-left: auto;
  }
  .load-hint {
    margin: var(--sp-4) 0 0;
    font-size: var(--fs-label);
    color: var(--text-3);
  }
  .eng-footnote {
    margin: var(--sp-4) 0 0;
    font-size: var(--fs-label);
    line-height: 1.6;
    color: var(--text-3);
    word-break: break-all;
  }
  .eng-path {
    font-family: var(--font-mono);
  }
</style>
