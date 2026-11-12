<script lang="ts">
  /**
   * 设置：引擎与模型、运行环境、日志诊断、工作流偏好。
   *
   * 引擎卡片完全由服务端 `core/engines.py` 的注册表驱动：以后加引擎只改后端，
   * 这里自动多一张卡（语种、体积、安装状态、下载按钮都不用在 UI 里写死）。
   */
  import Icon from '../components/Icon.svelte';
  import PageHeader from '../components/PageHeader.svelte';
  import EngineSetup from '../components/EngineSetup.svelte';
  import ProgressBar from '../components/ProgressBar.svelte';
  import { api, logEvent, type EngineInfo } from '../lib/api';
  import {
    app,
    downloadEngine,
    downloadTtsModel,
    loadSettings,
    loadTtsVoices,
    setMode,
    setSkin,
    setTtsDefaultKind,
    setTtsDefaultVoiceId,
    settings,
    toast,
    toggleEngine,
    tts,
    updateSettings,
  } from '../lib/store.svelte';
  import { SCHEMES, SKINS, skinOf } from '../lib/themes';
  import { formatBytes } from '../lib/time';
  import { onDestroy } from 'svelte';

  type Diag = Awaited<ReturnType<typeof api.diagnostics>>;

  let diag = $state<Diag | null>(null);
  let diagLoading = $state(false);
  let copying = $state('');
  let changingModels = $state(false);
  let changingExport = $state(false);
  let cleaningLogs = $state(false);
  let wasConnected = false;
  let showEngineSetup = $state(false);
  const ttsRunning = $derived(tts.download?.status === 'running');
  let ttsChecking = $state(false);

  // OmniVoice 的进度展示：校验（不确定进度）与下载（真实百分比）共用一条轨道。
  type TtsUiState = 'idle' | 'verifying' | 'downloading' | 'done' | 'error';
  let ttsUiState = $state<TtsUiState>('idle');
  let ttsStageText = $state('');
  let ttsUiTimer: ReturnType<typeof setTimeout> | undefined;
  let lastTtsDownloadStatus = '';

  const ttsPercent = $derived(
    ttsUiState === 'downloading'
      ? (tts.download?.percent ?? 0)
      : ttsUiState === 'done'
        ? 100
        : null,
  );
  const ttsBarState = $derived(
    ttsUiState === 'done' ? 'done' : ttsUiState === 'error' ? 'error' : 'running',
  );
  const ttsRightText = $derived(
    ttsUiState === 'verifying'
      ? '校验中'
      : ttsUiState === 'error'
        ? '失败'
        : `${ttsPercent ?? 0}%`,
  );
  const ttsStageLine = $derived(
    ttsUiState === 'verifying'
      ? '正在校验 OmniVoice 权重…'
      : ttsUiState === 'downloading'
        ? tts.download?.stage || '正在下载 OmniVoice 模型…'
        : ttsStageText,
  );
  const ttsProgressVisible = $derived(ttsUiState !== 'idle');

  function clearTtsTimer() {
    if (ttsUiTimer) {
      clearTimeout(ttsUiTimer);
      ttsUiTimer = undefined;
    }
  }

  function showTtsState(state: TtsUiState, stage = '', timeout = 0) {
    clearTtsTimer();
    ttsUiState = state;
    ttsStageText = stage;
    if (timeout > 0) {
      ttsUiTimer = setTimeout(() => {
        ttsUiState = 'idle';
        ttsStageText = '';
        ttsUiTimer = undefined;
      }, timeout);
    }
  }

  onDestroy(clearTtsTimer);

  // 下载进度来自 store 的轮询；这里只做「状态机 → 完成/失败闪一下」。
  $effect(() => {
    const status = tts.download?.status ?? 'idle';
    if (!lastTtsDownloadStatus) {
      lastTtsDownloadStatus = status;
      if (status === 'running') ttsUiState = 'downloading';
      return;
    }
    if (status === lastTtsDownloadStatus) return;
    if (status === 'running') {
      clearTtsTimer();
      ttsUiState = 'downloading';
      ttsStageText = '';
    } else if (status === 'done' && (lastTtsDownloadStatus === 'running' || ttsUiState === 'downloading')) {
      showTtsState('done', 'OmniVoice 模型已就绪', 1600);
    } else if (status === 'error' && (lastTtsDownloadStatus === 'running' || ttsUiState === 'downloading')) {
      showTtsState('error', tts.download?.error || 'OmniVoice 下载失败', 4500);
    }
    lastTtsDownloadStatus = status;
  });
  const ttsDefaultVoice = $derived(
    tts.custom.find((voice) => voice.id === tts.defaultVoiceId) ?? null,
  );

  // ---- AI 优化（实验功能）----
  type AiCfg = Awaited<ReturnType<typeof api.getAiConfig>>;
  let aiCfg = $state<AiCfg | null>(null);
  let aiKeyReady = $state(true); // 本机加密可用（正常恒为 true）
  let aiHasKey = $state(false);
  let aiKeyBroken = $state(false); // 有密文但解不开，需要重填
  let aiKeyLegacy = $state(false); // 更早版本用钥匙串存的，本版本读不了
  let aiKeyInput = $state('');
  let aiTesting = $state(false);
  let aiTestMsg = $state('');
  let aiSaving = $state(false);

  // ---- Agent 技能（一键配置）----
  interface SkillInfo {
    targetDir: string;
    installed: boolean;
    upToDate: boolean;
    fileCount: number;
    installedAt: number;
    error?: string;
  }
  let skillInfo = $state<SkillInfo | null>(null);
  let skillBusy = $state(false);
  const aiEnabled = $derived(aiCfg?.enabled ?? false);

  // 内核重启（改模型目录 / 崩溃恢复）后重新拉设置，否则路径与安装状态还是旧的。
  $effect(() => {
    if (!app.connected) {
      wasConnected = false;
      return;
    }
    if (wasConnected) return;
    wasConnected = true;
    void loadSettings(true);
    void loadDiag();
    void loadAi();
    void loadSkill();
    void loadTtsVoices();
  });

  const engines = $derived(settings.data?.engines ?? []);
  const enabledCount = $derived(engines.filter((e) => e.enabled).length);
  const installedCount = $derived(engines.filter((e) => e.installed).length);
  const autoProxy = $derived(settings.data?.settings.auto_proxy ?? true);
  const exportDir = $derived(
    settings.data?.paths.export_dir || diag?.paths.export_dir || app.config?.export_dir || '',
  );
  const exportDirIsCustom = $derived(Boolean(settings.data?.settings.export_dir));
  const videoExportDir = $derived(
    settings.data?.paths.video_export_dir ||
      diag?.paths.video_export_dir ||
      app.config?.video_export_dir ||
      '',
  );
  const videoExportDirIsCustom = $derived(Boolean(settings.data?.settings.video_export_dir));
  const pathInfo = $derived(settings.data?.paths ?? diag?.paths ?? null);
  const downloading = $derived(settings.download);

  async function loadAi() {
    try {
      aiCfg = await api.getAiConfig();
    } catch {
      aiCfg = null;
    }
    await refreshAiKey();
  }

  async function refreshAiKey() {
    try {
      const st = await window.kikusub?.aiKey?.status?.();
      aiKeyReady = st?.available !== false;
      aiHasKey = Boolean(st?.has);
      aiKeyBroken = Boolean(st?.broken);
      aiKeyLegacy = Boolean(st?.legacy);
    } catch {
      aiKeyReady = false;
      aiHasKey = false;
      aiKeyBroken = false;
      aiKeyLegacy = false;
    }
  }

  async function loadSkill() {
    try {
      const res = await window.kikusub?.skill?.status?.();
      skillInfo = res ? (res as SkillInfo) : null;
    } catch {
      skillInfo = null;
    }
  }

  async function installSkill() {
    if (skillBusy) return;
    skillBusy = true;
    try {
      const res = await window.kikusub.skill.install({
        output_dir: app.config?.output_dir || '',
        export_dir: app.config?.export_dir || '',
      });
      if (!res?.ok) {
        toast(res?.error || '技能配置失败', 'error');
        return;
      }
      skillInfo = res as SkillInfo;
      toast(`已配置到 ${res.targetDir}`);
    } catch (err) {
      toast((err as Error).message, 'error');
    } finally {
      skillBusy = false;
    }
  }

  async function patchAi(patch: Parameters<typeof api.patchAiConfig>[0]) {
    try {
      aiCfg = await api.patchAiConfig(patch);
      return true;
    } catch (err) {
      toast((err as Error).message, 'error');
      return false;
    }
  }

  async function toggleAi() {
    if (!aiCfg) return;
    const next = !aiCfg.enabled;
    if (await patchAi({ enabled: next })) {
      toast(next ? 'AI 优化已启用' : 'AI 优化已关闭');
    }
  }

  async function saveAiEndpoint() {
    if (!aiCfg || aiSaving) return;
    aiSaving = true;
    try {
      const ok = await patchAi({
        base_url: aiCfg.base_url.trim(),
        model: aiCfg.model.trim(),
        chunk_cues: Number(aiCfg.chunk_cues) || 200,
        translate_chunk_cues: Number(aiCfg.translate_chunk_cues) || 120,
        context_cues: Number(aiCfg.context_cues) || 0,
      });
      if (ok) toast('AI 配置已保存');
    } finally {
      aiSaving = false;
    }
  }

  async function saveAiKey() {
    const text = aiKeyInput.trim();
    if (!text) return;
    try {
      const res = await window.kikusub.aiKey.set(text);
      if (!res?.ok) {
        toast('保存失败：应用数据目录不可写', 'error');
        return;
      }
      aiKeyBroken = false;
      aiKeyInput = '';
      await refreshAiKey();
      toast('API Key 已加密保存');
    } catch (err) {
      toast((err as Error).message, 'error');
    }
  }

  async function clearAiKey() {
    try {
      await window.kikusub.aiKey.clear();
      await refreshAiKey();
      aiKeyBroken = false;
      aiTestMsg = '';
      toast('已清除 API Key');
    } catch (err) {
      toast((err as Error).message, 'error');
    }
  }

  async function testAi() {
    if (!aiCfg || aiTesting) return;
    aiTesting = true;
    aiTestMsg = '';
    try {
      const key = await window.kikusub.aiKey.get();
      if (!key) {
        aiTestMsg = '还没有保存 API Key';
        return;
      }
      const res = await api.testAi({ base_url: aiCfg.base_url, model: aiCfg.model }, key);
      aiTestMsg = `连接正常 · ${res.latency_ms}ms · ${res.host}`;
    } catch (err) {
      aiTestMsg = `连接失败：${(err as Error).message}`;
    } finally {
      aiTesting = false;
    }
  }

  async function loadDiag() {
    diagLoading = true;
    try {
      diag = await api.diagnostics(120);
    } catch (err) {
      toast(`诊断信息读取失败：${(err as Error).message}`, 'warn');
    } finally {
      diagLoading = false;
    }
  }

  async function copy(text: string, tag: string) {
    try {
      if (window.kikusub.writeClipboard) {
        await window.kikusub.writeClipboard(text);
      } else {
        await navigator.clipboard.writeText(text);
      }
      copying = tag;
      setTimeout(() => (copying = ''), 1600);
      toast('已复制到剪贴板');
    } catch (err) {
      toast(`复制失败：${(err as Error).message}`, 'error');
    }
  }

  /** 单行截断：日志里的 detail 可能带 8000 字符的 JSON，整段复制会卡死备忘录。 */
  function clipLine(line: string, limit = 500): string {
    const text = String(line ?? '');
    return text.length > limit ? `${text.slice(0, limit)}…` : text;
  }

  async function copyLogs() {
    try {
      // 最近 80 行足够定位；每行再截断，避免把超长 detail 全部塞进剪贴板。
      const data = await api.diagnosticsLog(80);
      if (!data.text) {
        toast('日志还是空的：先跑一次转写再试', 'warn');
        return;
      }
      const lines = data.text.split('\n').filter(Boolean).slice(-80);
      const text = [
        `# KikuSub 最近日志（${lines.length} 行）`,
        `# 文件：${data.path}`,
        ...lines.map((line) => clipLine(line)),
      ].join('\n');
      await copy(text, 'log');
    } catch (err) {
      toast((err as Error).message, 'error');
    }
  }

  async function copyDiagnostics() {
    try {
      const payload = diag ?? (await api.diagnostics(120));
      const problems = (payload.recent_problems ?? []).slice(-8).map((line) => clipLine(line));
      const tail = (payload.log_tail ?? '')
        .split('\n')
        .filter(Boolean)
        .slice(-20)
        .map((line) => clipLine(line));
      const summary = {
        note: '精简诊断：完整日志请用「复制最近日志」或直接查看 log_path。',
        runtime: payload.runtime,
        paths: payload.paths,
        ffmpeg: payload.ffmpeg,
        settings: payload.settings,
        engines: payload.engines.map((e) => ({
          key: e.key,
          label: e.label,
          installed: e.installed,
          enabled: e.enabled,
          size_bytes: e.size_bytes,
        })),
        log_bytes: payload.log_bytes,
        recent_problems: problems,
        log_tail: tail,
      };
      let text = JSON.stringify(summary, null, 2);
      if (text.length > 24000) text = `${text.slice(0, 24000)}\n…（已截断）`;
      await copy(text, 'diag');
    } catch (err) {
      toast(`诊断信息读取失败：${(err as Error).message}`, 'error');
    }
  }

  /**
   * OmniVoice 的「校验 / 补齐」。
   *
   * 之前它无条件弹「是否下载」，用户明明已经装好模型也会被问一遍——这是与
   * 上面两个 ASR 引擎最不一致的地方。现在已安装时先走只读校验：完整就立刻
   * 给出结果，缺文件才弹下载确认。
   */
  async function onDownloadTts() {
    if (ttsRunning || ttsChecking) return;
    let needsDownload = !tts.engine?.installed;
    if (!needsDownload) {
      ttsChecking = true;
      showTtsState('verifying', '正在校验 OmniVoice 权重…');
      const started = Date.now();
      try {
        const result = await api.verifyTtsModel();
        // 只读校验通常几十毫秒；给不确定进度至少 450ms，避免进度条一闪而过。
        const remaining = 450 - (Date.now() - started);
        if (remaining > 0) {
          await new Promise((resolve) => setTimeout(resolve, remaining));
        }
        if (result.installed) {
          toast('校验完成：OmniVoice 权重文件完整');
          await loadTtsVoices();
          showTtsState('done', 'OmniVoice 权重完整', 1600);
          return;
        }
        const missing = result.missing?.length ? `（缺少 ${result.missing.join('、')}）` : '';
        needsDownload = window.confirm(
          `OmniVoice 权重不完整${missing}。\n\n要现在重新下载补齐吗？系统语音不受影响。`,
        );
        if (!needsDownload) {
          showTtsState('idle');
          return;
        }
      } catch (err) {
        toast(`校验失败：${(err as Error).message}`, 'error');
        showTtsState('error', `校验失败：${(err as Error).message}`, 4000);
        return;
      } finally {
        ttsChecking = false;
      }
    } else if (
      !window.confirm(
        '下载 OmniVoice 克隆模型（约 3.3GB）？\n\n下载后可离线使用；系统语音兜底不受影响。',
      )
    ) {
      return;
    }
    showTtsState('downloading', '准备下载 OmniVoice 模型…');
    await downloadTtsModel();
    if (!tts.download) {
      showTtsState('error', '下载没有启动，请查看日志', 4000);
    }
  }

  function onTtsDefault(kind: 'system' | 'clone') {
    if (kind === 'clone' && !tts.custom.length) {
      toast('还没有克隆音色：先在核对台上传参考音频，或选中一句「从当前句截取」', 'warn');
      return;
    }
    setTtsDefaultKind(kind);
    toast(kind === 'clone' ? '默认朗读音色已切换为克隆音色' : '默认朗读音色已切换为系统语音');
  }

  function onTtsDefaultVoice(event: Event) {
    const value = (event.currentTarget as HTMLSelectElement).value;
    setTtsDefaultVoiceId(value);
  }

  function openPath(path: string) {
    if (!path) return;
    void window.kikusub.openPath(path);
  }

  function reveal(path: string) {
    if (path) window.kikusub.revealInFinder(path);
  }

  function sizeText(bytes: number): string {
    return bytes > 0 ? formatBytes(bytes) : '0 B';
  }

  function statusText(engine: EngineInfo) {
    if (engine.installed) return `已安装 · ${formatBytes(engine.size_bytes)}`;
    return `未下载 · ${engine.approx_label}`;
  }

  function downloadState(key: string) {
    return downloading && downloading.key === key ? downloading : null;
  }

  async function onDownload(engine: EngineInfo) {
    await downloadEngine(engine.key);
  }

  async function onToggle(engine: EngineInfo) {
    await toggleEngine(engine.key, !engine.enabled);
  }

  async function onAutoProxy() {
    await updateSettings({ auto_proxy: !autoProxy });
  }

  async function cleanOldLogs() {
    if (cleaningLogs) return;
    if (
      !window.confirm(
        '清理所有轮转日志备份（kikusub.log.1 / main.log.1 等）。\n\n正在写入的日志会保留，只删除过期或超量的旧文件。',
      )
    ) {
      return;
    }
    cleaningLogs = true;
    try {
      const result = await api.cleanLogs();
      if (result.removed > 0) {
        toast(`已清理 ${result.removed} 个旧日志，释放 ${formatBytes(result.freed)}`);
      } else {
        toast(
          `当前没有过期备份；日志共 ${sizeText(diag?.log_bytes ?? result.total_bytes)}。要立即释放空间，点「清空全部日志」。`,
          'warn',
        );
      }
      logEvent('info', 'logs-clean', `removed=${result.removed} freed=${result.freed}`);
      await loadDiag();
    } catch (err) {
      toast(`清理失败：${(err as Error).message}`, 'error');
    } finally {
      cleaningLogs = false;
    }
  }

  async function clearAllLogs() {
    if (cleaningLogs) return;
    if (
      !window.confirm(
        '清空全部日志？\n\n会清掉 kikusub.log、main.log 以及所有轮转备份；设置、字幕和媒体都不受影响。',
      )
    ) {
      return;
    }
    cleaningLogs = true;
    try {
      const main = await api.clearAllLogs();
      let removed = main.removed;
      let freed = main.freed;
      try {
        const renderer = await window.kikusub.clearMainLog?.();
        if (renderer) {
          removed += renderer.removed;
          freed += renderer.freed;
        }
      } catch {
        /* 主进程日志清不掉时，至少 sidecar 的已经清掉 */
      }
      toast(
        removed > 0
          ? `已清空日志：删除 ${removed} 个文件，释放 ${formatBytes(freed)}`
          : `日志已清空，释放 ${formatBytes(freed)}`,
      );
      logEvent('info', 'logs-clear', `removed=${removed} freed=${freed}`);
      await loadDiag();
    } catch (err) {
      toast(`清空失败：${(err as Error).message}`, 'error');
    } finally {
      cleaningLogs = false;
    }
  }

  async function changeVideoExportDir() {
    if (changingExport) return;
    let picked = '';
    try {
      picked = (await window.kikusub.pickDirectory({
        title: '选择成片导出文件夹',
        defaultPath: videoExportDir,
      })) || '';
    } catch (err) {
      toast((err as Error).message, 'error');
      return;
    }
    if (!picked) return;
    const current = (videoExportDir || '').replace(/\/+$/, '');
    if (picked.replace(/\/+$/, '') === current) return;
    changingExport = true;
    try {
      await updateSettings({ video_export_dir: picked });
      logEvent('info', 'video-export-dir-change', picked);
      await loadDiag();
    } finally {
      changingExport = false;
    }
  }

  async function resetVideoExportDir() {
    if (changingExport) return;
    if (!window.confirm('恢复为跟随字幕导出文件夹？\n\n已经导出的成片不会被移动或删除。')) return;
    changingExport = true;
    try {
      await updateSettings({ video_export_dir: '' });
      logEvent('info', 'video-export-dir-reset', '');
      await loadDiag();
    } finally {
      changingExport = false;
    }
  }

  async function changeExportDir() {
    if (changingExport) return;
    let picked = '';
    try {
      picked = (await window.kikusub.pickDirectory({
        title: '选择字幕默认导出文件夹',
        defaultPath: exportDir,
      })) || '';
    } catch (err) {
      toast((err as Error).message, 'error');
      return;
    }
    if (!picked) return;
    const current = (exportDir || '').replace(/\/+$/, '');
    if (picked.replace(/\/+$/, '') === current) return;
    changingExport = true;
    try {
      await updateSettings({ export_dir: picked });
      logEvent('info', 'export-dir-change', picked);
      await loadDiag();
    } finally {
      changingExport = false;
    }
  }

  async function resetExportDir() {
    if (changingExport) return;
    if (!window.confirm('恢复为默认导出文件夹（运行数据目录）？\n\n已经导出的字幕不会被移动或删除。')) {
      return;
    }
    changingExport = true;
    try {
      await updateSettings({ export_dir: '' });
      logEvent('info', 'export-dir-reset', '');
      await loadDiag();
    } finally {
      changingExport = false;
    }
  }

  async function changeModelsDir() {
    if (changingModels) return;
    if (app.job?.status === 'running') {
      toast('任务进行中，先等它结束或打断后再切换模型目录', 'warn');
      return;
    }
    let picked = '';
    try {
      picked = (await window.kikusub.pickModelsDir()) || '';
    } catch (err) {
      toast((err as Error).message, 'error');
      return;
    }
    if (!picked) return;
    const current = (diag?.paths.models_dir ?? settings.data?.paths.models_dir ?? '').replace(/\/+$/, '');
    if (picked.replace(/\/+$/, '') === current) return;
    const sessionWarning = app.media
      ? '\n\n注意：切换会重启内核，当前会话的媒体、字幕与撤回记录会清空；请先导出 SRT。'
      : '';
    const ok = window.confirm(
      `将模型目录切换到：\n${picked}\n\n` +
        '已下载的模型不会自动搬迁，需要重新下载或手动复制。' +
        sessionWarning +
        '\n\n确定继续吗？',
    );
    if (!ok) return;

    // 先挂好「内核重启完成」的监听，再触发重启，避免 ready 比调用返回更早。
    const ready = new Promise<void>((resolve) => {
      let done = false;
      const finish = () => {
        if (done) return;
        done = true;
        off();
        resolve();
      };
      const off = window.kikusub.onSidecarReady(() => finish());
      setTimeout(finish, 30000);
    });

    changingModels = true;
    try {
      await window.kikusub.setModelsDir(picked);
      toast('模型目录已切换，正在重启内核…');
      logEvent('info', 'models-dir-change', picked);
      await ready;
      await loadSettings(true);
      await loadDiag();
      toast('内核已重启，新的模型目录已生效');
    } catch (err) {
      toast(`切换失败：${(err as Error).message}`, 'error');
      logEvent('error', 'models-dir-change-failed', picked, String(err));
    } finally {
      changingModels = false;
    }
  }
</script>

<div class="settings">
  <PageHeader title="设置" subtitle="引擎与模型、运行环境、日志诊断与工作流偏好。">
    <div class="head-meta">
      <span>{installedCount} / {engines.length} 个引擎已就绪</span>
      <span>·</span>
      <span>{enabledCount} 个已启用</span>
      <kbd class="head-key" title="⌘, 可从任意页面回到设置">⌘,</kbd>
    </div>
  </PageHeader>

  <!-- 引擎 -->
  <section class="sec">
    <div class="sec-head">
      <div>
        <div class="sec-title">引擎与模型</div>
        <div class="sec-desc">
          模型按需下载。启用的引擎会出现在顶部切换栏；第一次转写前至少启用一个。
        </div>
      </div>
      <div class="head-actions">
        <button class="btn ghost" onclick={() => (showEngineSetup = true)} title="重新选择并下载模型">
          运行首次配置…
        </button>
        <button class="btn ghost" onclick={() => loadSettings(true)} title="重新检测安装状态">
          <Icon name="undo" size={11} />重新检测
        </button>
      </div>
    </div>

    {#if settings.loading && !settings.data}
      <div class="loading">正在读取引擎配置…</div>
    {:else if settings.error}
      <div class="error-box">
        <Icon name="warn" size={13} />
        读取失败：{settings.error}
        <button class="btn tiny" onclick={() => loadSettings(true)}>重试</button>
      </div>
    {:else}
      <div class="engines">
        {#each engines as engine (engine.key)}
          {@const dl = downloadState(engine.key)}
          <div class="engine" class:off={!engine.enabled}>
            <div class="eng-top">
              <div class="eng-name">
                <span class="dot" class:ready={engine.installed}></span>
                <b>{engine.label}</b>
                <span class="eng-purpose">{engine.purpose}</span>
              </div>
              <label class="enable" title={engine.enabled ? '在顶部切换栏中隐藏' : '显示在顶部切换栏'}>
                <span>{engine.enabled ? '已启用' : '已停用'}</span>
                <button
                  class="switch"
                  class:on={engine.enabled}
                  role="switch"
                  aria-checked={engine.enabled}
                  onclick={() => onToggle(engine)}
                >
                  <span class="knob"></span>
                </button>
              </label>
            </div>

            <p class="eng-desc">{engine.description}</p>

            <div class="meta">
              <span class="pill">
                <Icon name="wave" size={10} />{engine.languages.join(' / ')}
              </span>
              <span class="pill">{engine.installed ? formatBytes(engine.size_bytes) : engine.approx_label}</span>
              <span class="pill">建议内存 {engine.min_ram_gb} GB</span>
              <span class="pill mono" title={engine.hf_repo}>{engine.hf_repo.split('/').pop()}</span>
              <span class="status" class:ok={engine.installed} class:missing={!engine.installed}>
                {statusText(engine)}
              </span>
            </div>

            {#if engine.notes}
              <div class="notes">{engine.notes}</div>
            {/if}

            <div class="eng-actions">
              {#if engine.installed}
                <button class="btn" onclick={() => openPath(engine.model_dir)}>
                  <Icon name="folder" size={11} />打开模型目录
                </button>
                <button
                  class="btn ghost"
                  onclick={() => onDownload(engine)}
                  disabled={Boolean(downloading && downloading.status === 'running')}
                  title="检查权重是否完整，缺文件时自动补齐"
                >
                  校验 / 补齐
                </button>
              {:else}
                <button
                  class="btn primary"
                  onclick={() => onDownload(engine)}
                  disabled={!engine.downloadable || Boolean(downloading && downloading.status === 'running')}
                >
                  <Icon name="export" size={11} />
                  {engine.downloadable ? '下载模型' : '需手动安装'}
                </button>
              {/if}
              <button class="btn ghost" onclick={() => reveal(engine.model_dir)}>
                在访达中显示
              </button>
              <span class="path mono" title={engine.model_dir}>{engine.model_dir}</span>
            </div>

            {#if dl}
              <div class="dl">
                <div class="dl-top">
                  <span>{dl.stage}</span>
                  <b>{dl.percent}%</b>
                </div>
                <ProgressBar
                  percent={dl.percent}
                  state={dl.status === 'error' ? 'error' : dl.status === 'done' ? 'done' : 'running'}
                  label="模型下载进度"
                />
              </div>
            {/if}
          </div>
        {/each}
      </div>

      <div class="engine tts-engine">
        <div class="eng-top">
          <div class="eng-name">
            <span class="dot" class:ready={tts.engine?.installed}></span>
            <b>OmniVoice 音色克隆</b>
            <span class="eng-purpose">可选 · 零样本克隆</span>
          </div>
          <span
            class="status"
            class:ok={tts.engine?.installed}
            class:missing={!tts.engine?.installed}
          >
            {tts.engine?.installed ? '已安装' : '未下载'}
          </span>
        </div>
        <p class="eng-desc">
          从视频任意一句切出 3–10 秒参考音频，用本地克隆声线朗读日文。默认音色可在下方
          「TTS 对照」里切换；不下载也不影响转写与系统语音。
        </p>
        <div class="meta">
          <span class="pill">日语</span>
          <span class="pill">
            {tts.engine?.installed
              ? '已就绪'
              : (tts.engine?.approx_label ?? '约 3.3 GB')}
          </span>
          <span class="pill">建议内存 {tts.engine?.min_ram_gb ?? 8} GB</span>
          <span class="pill mono" title={tts.engine?.repo ?? 'k2-fsa/OmniVoice'}>
            {(tts.engine?.repo ?? 'k2-fsa/OmniVoice').split('/').pop()}
          </span>
        </div>
        {#if tts.engine && !tts.engine.package_installed}
          <div class="notes">当前构建缺少 omnivoice 依赖，只能使用系统语音。</div>
        {:else}
          <div class="notes">首次合成才加载权重，空闲 5 分钟自动卸载。</div>
        {/if}
        <div class="eng-actions">
          {#if tts.engine?.installed}
            <button class="btn" onclick={() => openPath(tts.engine?.model_dir ?? '')}>
              <Icon name="folder" size={11} />打开模型目录
            </button>
            <button class="btn ghost" onclick={onDownloadTts} disabled={ttsRunning || ttsChecking}>
              {ttsChecking ? '校验中…' : '校验 / 补齐'}
            </button>
          {:else}
            <button
              class="btn primary"
              onclick={onDownloadTts}
              disabled={ttsRunning || !tts.engine?.package_installed}
            >
              <Icon name="export" size={11} />
              {tts.engine?.package_installed ? '下载模型' : '依赖缺失'}
            </button>
          {/if}
        </div>

        {#if ttsProgressVisible}
          <div class="dl" class:error={ttsUiState === 'error'}>
            <div class="dl-top">
              <span>{ttsStageLine}</span>
              <b>{ttsRightText}</b>
            </div>
            <ProgressBar
              percent={ttsPercent}
              state={ttsBarState}
              label="OmniVoice 校验与下载进度"
            />
          </div>
        {/if}
      </div>

      {#if enabledCount === 0}
        <div class="warn-box">
          <Icon name="warn" size={13} />
          当前没有启用任何引擎——转写页会无法开始。至少打开一个开关。
        </div>
      {/if}
      <p class="footnote">
        模型目录：<span class="mono">{settings.data?.paths.models_dir ?? '—'}</span>
        （可在「运行环境」里更改）。
      </p>
    {/if}
  </section>

  <!-- TTS 对照 -->
  <section class="sec">
    <div class="sec-head">
      <div>
        <div class="sec-title">TTS 对照</div>
        <div class="sec-desc">决定核对台「朗读」默认用哪一层声音；切换后立即生效。</div>
      </div>
    </div>

    <div class="pref">
      <div>
        <b>默认朗读音色</b>
        <span>
          系统语音零显存、秒出；克隆音色按角色声线朗读，首次合成要加载模型。
          保存过的克隆音色不会丢，随时可以在核对台「音色库」里复用。
        </span>
      </div>
      <div class="seg">
        <button class:on={tts.defaultKind === 'system'} onclick={() => onTtsDefault('system')}>
          系统语音
        </button>
        <button
          class:on={tts.defaultKind === 'clone'}
          onclick={() => onTtsDefault('clone')}
          disabled={!tts.custom.length}
          title={!tts.custom.length ? '先在核对台上传参考音频，或选中一句「从当前句截取」' : ''}
        >
          克隆音色
        </button>
      </div>
    </div>

    <div class="pref">
      <div>
        <b>默认克隆音色</b>
        <span>
          {tts.custom.length
            ? ttsDefaultVoice
              ? `当前默认：${ttsDefaultVoice.name}`
              : '未指定时使用最近保存的音色。'
            : '还没有保存的克隆音色。去核对台「TTS 对照」上传参考音频，或选中一句「从当前句截取」。'}
        </span>
      </div>
      <select
        class="tts-pick"
        value={tts.defaultVoiceId}
        onchange={onTtsDefaultVoice}
        disabled={!tts.custom.length}
      >
        <option value="">最近保存的音色</option>
        {#each tts.custom as voice (voice.id)}
          <option value={voice.id}>{voice.name}</option>
        {/each}
      </select>
    </div>

    <div class="paths">
      <div class="path-row">
        <span>音色目录</span>
        <b class="mono" title={tts.voicesDir}>{tts.voicesDir || '—'}</b>
        <div class="path-actions">
          <button
            class="btn tiny"
            onclick={() => tts.voicesDir && openPath(tts.voicesDir)}
            disabled={!tts.voicesDir}
          >
            在访达中显示
          </button>
        </div>
      </div>
    </div>
    <p class="footnote">参考音频建议 3–10 秒、单人干声、无背景音乐；会自动去首尾静音，超长只保留前 10 秒。</p>
  </section>

  <!-- 运行环境 -->
  <section class="sec">
    <div class="sec-head">
      <div>
        <div class="sec-title">运行环境</div>
        <div class="sec-desc">
          所有会写文件的文件夹都汇总在这里。字幕与成片可以分开放；日志、代理缓存与
          运行数据留在应用数据目录，清理时不会误伤交付物。
        </div>
      </div>
    </div>

    <div class="grid">
      <div class="kv"><span>加速设备</span><b>{diag?.runtime.device ?? app.config?.device ?? '—'}</b></div>
      <div class="kv"><span>应用版本</span><b>v{diag?.runtime.version ?? app.config?.version ?? '—'}</b></div>
      <div class="kv"><span>Python</span><b>{diag?.runtime.python ?? '—'}</b></div>
      <div class="kv"><span>打包运行</span><b>{diag?.runtime.frozen ? '是' : '否（源码模式）'}</b></div>
      <div class="kv wide">
        <span>ffmpeg</span>
        <b class="mono" title={diag?.ffmpeg.version ?? ''}>
          {diag?.ffmpeg.path || '未找到（导入会失败）'}
        </b>
      </div>
    </div>

    {#if pathInfo}
      <div class="paths">
        <div class="path-row">
          <span>导出文件夹</span>
          <b class="mono" title={exportDir}>{exportDir || '—'}</b>
          <div class="path-actions">
            <button class="btn tiny ghost" onclick={() => openPath(exportDir)}>打开</button>
            <button class="btn tiny" onclick={changeExportDir} disabled={changingExport}>
              {changingExport ? '切换中…' : '更改…'}
            </button>
            {#if exportDirIsCustom}
              <button class="btn tiny ghost" onclick={resetExportDir} disabled={changingExport}>
                恢复默认
              </button>
            {/if}
          </div>
        </div>

        <div class="path-row">
          <span>成片目录</span>
          <b class="mono" title={videoExportDir}>{videoExportDir || '—'}</b>
          <div class="path-actions">
            <button class="btn tiny ghost" onclick={() => openPath(videoExportDir)}>打开</button>
            <button class="btn tiny" onclick={changeVideoExportDir} disabled={changingExport}>
              {changingExport ? '切换中…' : '更改…'}
            </button>
            {#if videoExportDirIsCustom}
              <button
                class="btn tiny ghost"
                onclick={resetVideoExportDir}
                disabled={changingExport}
              >
                恢复默认
              </button>
            {/if}
          </div>
        </div>

        <div class="path-row">
          <span>运行数据目录</span>
          <b class="mono" title={pathInfo.output_dir}>{pathInfo.output_dir}</b>
          <div class="path-actions">
            <button class="btn tiny ghost" onclick={() => openPath(pathInfo.output_dir)}>
              打开
            </button>
          </div>
        </div>

        <div class="path-row">
          <span>模型目录</span>
          <b class="mono" title={pathInfo.models_dir}>{pathInfo.models_dir}</b>
          <div class="path-actions">
            <button
              class="btn tiny ghost"
              onclick={() => openPath(pathInfo.models_dir)}
            >
              打开
            </button>
            <button class="btn tiny" onclick={changeModelsDir} disabled={changingModels}>
              {changingModels ? '切换中…' : '更改…'}
            </button>
          </div>
        </div>

        <div class="path-row">
          <span>代理缓存</span>
          <b class="mono" title={pathInfo.proxy_dir}>{pathInfo.proxy_dir}</b>
          <div class="path-actions">
            <button class="btn tiny ghost" onclick={() => openPath(pathInfo.proxy_dir)}>
              打开
            </button>
          </div>
        </div>

        <div class="path-row">
          <span>TTS 缓存</span>
          <b class="mono" title={pathInfo.tts_cache_dir}>{pathInfo.tts_cache_dir}</b>
          <div class="path-actions">
            <button class="btn tiny ghost" onclick={() => openPath(pathInfo.tts_cache_dir)}>
              打开
            </button>
          </div>
        </div>

        <div class="path-row">
          <span>克隆音色</span>
          <b class="mono" title={pathInfo.voices_dir}>{pathInfo.voices_dir}</b>
          <div class="path-actions">
            <button class="btn tiny ghost" onclick={() => openPath(pathInfo.voices_dir)}>
              打开
            </button>
          </div>
        </div>

        <div class="path-row">
          <span>TTS 模型</span>
          <b class="mono" title={pathInfo.tts_model_dir}>{pathInfo.tts_model_dir}</b>
          <div class="path-actions">
            <button class="btn tiny ghost" onclick={() => openPath(pathInfo.tts_model_dir)}>
              打开
            </button>
          </div>
        </div>

        <div class="path-row">
          <span>日志目录</span>
          <b class="mono" title={pathInfo.log_dir}>{pathInfo.log_dir}</b>
          <div class="path-actions">
            <button class="btn tiny ghost" onclick={() => openPath(pathInfo.log_dir)}>
              打开
            </button>
          </div>
        </div>

        <div class="path-row">
          <span>预设文件</span>
          <b class="mono" title={pathInfo.presets_path}>{pathInfo.presets_path}</b>
          <div class="path-actions">
            <button class="btn tiny ghost" onclick={() => reveal(pathInfo.presets_path)}>
              显示
            </button>
          </div>
        </div>

        <div class="path-row">
          <span>设置文件</span>
          <b class="mono" title={pathInfo.settings_path}>{pathInfo.settings_path}</b>
          <div class="path-actions">
            <button class="btn tiny ghost" onclick={() => reveal(pathInfo.settings_path)}>
              显示
            </button>
          </div>
        </div>
      </div>
    {:else}
      <div class="loading">正在读取路径…</div>
    {/if}
  </section>

  <!-- 日志与诊断 -->
  <section class="sec">
    <div class="sec-head">
      <div>
        <div class="sec-title">日志与诊断</div>
        <div class="sec-desc">
          遇到问题先点「复制精简诊断」，它包含版本、目录、引擎状态与最近问题，体积控制在一屏以内。
        </div>
      </div>
      <button class="btn ghost" onclick={loadDiag} disabled={diagLoading}>
        <Icon name="undo" size={11} />{diagLoading ? '读取中…' : '刷新'}
      </button>
    </div>

    <div class="log-row">
      <span class="mono log-path" title={diag?.log_path ?? ''}>{diag?.log_path ?? '—'}</span>
      <button class="btn" onclick={() => pathInfo && openPath(pathInfo.log_dir)}>
        <Icon name="folder" size={11} />打开日志目录
      </button>
      <button class="btn" onclick={copyLogs} title="复制最近 80 行，每行超长部分会截断">
        <Icon name="doc" size={11} />{copying === 'log' ? '已复制' : '复制最近日志'}
      </button>
      <button class="btn" onclick={cleanOldLogs} disabled={cleaningLogs} title="只按保留策略清理过期轮转备份">
        <Icon name="undo" size={11} />{cleaningLogs ? '清理中…' : '清理旧日志'}
      </button>
      <button class="btn danger" onclick={clearAllLogs} disabled={cleaningLogs} title="清空活动日志与全部轮转备份">
        <Icon name="trash" size={11} />{cleaningLogs ? '清理中…' : '清空全部日志'}
      </button>
      <button class="btn primary" onclick={copyDiagnostics} title="复制精简诊断，体积控制在一屏以内">
        <Icon name="export" size={11} />{copying === 'diag' ? '已复制' : '复制精简诊断'}
      </button>
    </div>

    {#if diag}
      <div class="log-meta">
        <span>日志：{diag.log_exists ? '已写入' : '尚未生成'} · {sizeText(diag.log_bytes ?? 0)}</span>
        <span>最近问题：{diag.recent_problems.length} 条</span>
        <span>日志目录：{pathInfo?.log_dir ?? '—'}</span>
      </div>
      {#if diag.log_bytes > 8 * 1024 * 1024}
        <div class="warn-box">
          <Icon name="warn" size={13} />
          日志已超过 {sizeText(diag.log_bytes)}。可以点「清空全部日志」立即释放；不会影响字幕和设置。
        </div>
      {/if}
      {#if diag.recent_problems.length}
        <pre class="log-tail">{diag.recent_problems.join('\n')}</pre>
      {:else}
        <div class="empty-log">最近日志里没有 ERROR / WARNING。</div>
      {/if}
      <details class="tail">
        <summary>查看最近日志原文（{diag.log_tail.split('\n').filter(Boolean).length} 行）</summary>
        <pre class="log-tail">{diag.log_tail || '（空）'}</pre>
      </details>
    {/if}
  </section>

  <!-- AI 优化（实验功能） -->
  <section class="sec">
    <div class="sec-head">
      <div>
        <div class="sec-title">AI 优化（实验功能）</div>
        <div class="sec-desc">
          用你自己的模型按全片语境修正识别错误。结果只生成<b>建议</b>，在 AI 优化台里逐条对照，
          确认后才写进核对台。
        </div>
      </div>
    </div>

    {#if aiCfg}
      <div class="pref">
        <div>
          <b>启用 AI 优化</b>
          <span>关闭后「AI 优化台」仍可查看/导入已有建议，只是不能再生成。</span>
        </div>
        <button
          class="switch"
          class:on={aiEnabled}
          role="switch"
          aria-checked={aiEnabled}
          onclick={toggleAi}
        >
          <span class="knob"></span>
        </button>
      </div>

      <div class="ai-form">
        <label>
          <span>Base URL</span>
          <input bind:value={aiCfg.base_url} spellcheck="false" placeholder="https://api.deepseek.com" />
        </label>
        <label>
          <span>模型</span>
          <input bind:value={aiCfg.model} spellcheck="false" placeholder="deepseek-flash" />
        </label>
        <div class="ai-grid3">
          <label>
            <span>每块条数</span>
            <input type="number" min="20" max="2000" bind:value={aiCfg.chunk_cues} />
          </label>
          <label>
            <span>翻译每块条数</span>
            <input type="number" min="20" max="2000" bind:value={aiCfg.translate_chunk_cues} />
          </label>
          <label>
            <span>上下文条数</span>
            <input type="number" min="0" max="30" bind:value={aiCfg.context_cues} />
          </label>
          <div class="ai-actions">
            <button class="btn" onclick={saveAiEndpoint} disabled={aiSaving}>保存</button>
            <button class="btn ghost" onclick={testAi} disabled={aiTesting || !aiHasKey}>
              {aiTesting ? '测试中…' : '测试连接'}
            </button>
          </div>
        </div>
      </div>

      <div class="ai-key">
        <label>
          <span>API Key</span>
          <input
            type="password"
            bind:value={aiKeyInput}
            spellcheck="false"
            autocomplete="off"
            placeholder={aiHasKey ? '已保存（输入新值可替换）' : 'sk-…'}
          />
        </label>
        <div class="ai-actions">
          <button class="btn" onclick={saveAiKey} disabled={!aiKeyInput.trim() || !aiKeyReady}>
            保存 Key
          </button>
          <button class="btn ghost" onclick={clearAiKey} disabled={!aiHasKey}>清除</button>
          <span class="status" class:ok={aiHasKey} class:missing={!aiHasKey}>
            {aiHasKey ? '已配置' : '未配置'}
          </span>
        </div>
      </div>

      {#if aiKeyBroken}
        <div class="notes warn">
          检测到已保存的密钥解不开（主密钥文件丢了或密文被改过）{aiKeyLegacy ? '，它来自更早的钥匙串版本' : ''}。
          请在上面的输入框重新填一次。
        </div>
      {/if}
      {#if !aiKeyReady}
        <div class="notes warn">应用数据目录不可写，密钥无法保存；请检查磁盘权限。</div>
      {/if}
      {#if aiTestMsg}
        <div class="notes">{aiTestMsg}</div>
      {/if}
      <div
        class="notes"
        title="Key 以本机主密钥（AES-256-GCM）加密存放在应用数据目录，文件权限 600；不写进 settings.json、不写日志，也不依赖系统钥匙串，升级或重装应用都不会丢。"
      >
        Key 只保存在本机、加密存储，升级或重装应用都不会丢；每次请求时才解密，只发给上面填的服务地址。
        <b>调用会把字幕文本发送到该地址。</b>
      </div>

      <div class="skill-box">
        <div class="skill-head">
          <b>Agent 技能</b>
          <span class="muted">让外部 agent（DeepSeek Harness 等）自己读字幕、产出建议</span>
        </div>
        <div class="skill-row">
          <span class="mono skill-path">{skillInfo?.targetDir || '—'}</span>
          <span
            class="status"
            class:ok={Boolean(skillInfo?.installed && skillInfo?.upToDate)}
            class:missing={!skillInfo?.installed || !skillInfo?.upToDate}
          >
            {skillInfo?.installed
              ? skillInfo.upToDate
                ? '已配置'
                : '需更新'
              : '未配置'}
          </span>
          <button class="btn" onclick={installSkill} disabled={skillBusy}>
            {skillBusy ? '配置中…' : '一键配置'}
          </button>
          <button class="btn ghost" onclick={loadSkill} disabled={skillBusy}>刷新</button>
        </div>
        <div class="notes">
          配置后，在 agent 里说「帮我把 KikuSub 这份字幕润色一遍 / 翻译成中文」，它会按技能说明读
          字幕、写出建议文件；你回到「AI 优化台 → 重新加载」即可逐条对照后应用。
          <b>技能不直接改字幕</b>，也不写入任何密钥。
        </div>
      </div>
    {:else}
      <div class="notes">AI 配置读取失败，内核可能还没连上。</div>
    {/if}
  </section>

  <!-- 工作流 -->
  <section class="sec">
    <div class="sec-head">
      <div>
        <div class="sec-title">工作流与外观</div>
        <div class="sec-desc">这些偏好只影响当前这台机器。</div>
      </div>
    </div>

    <div class="pref">
      <div>
        <b>导入时自动压制 480p 监看代理</b>
        <span>
          MKV / HEVC 或码率高于 25 Mbps 的视频会自动压一份；关闭后仍可在核对台点
          「压制代理」手动处理。高码率 H.264 有时能播但拖动很卡，自动判定难免有遗漏。
        </span>
      </div>
      <button
        class="switch"
        class:on={autoProxy}
        role="switch"
        aria-checked={autoProxy}
        onclick={onAutoProxy}
      >
        <span class="knob"></span>
      </button>
    </div>

    <div class="pref">
      <div>
        <b>主题</b>
        <span>切换后立即生效，可随时改回。</span>
      </div>
      <div class="seg theme">
        {#each SKINS as skin (skin.id)}
          <button
            class:on={skinOf(app.theme) === skin.id}
            onclick={() => setSkin(skin.id)}
            title={skin.note}
          >
            <i
              class="swatch"
              aria-hidden="true"
              style="--sw-bg:{skin.swatch[0]};--sw-accent:{skin.swatch[1]}"
            ></i>
            {skin.name}
          </button>
        {/each}
      </div>
    </div>

    <div class="pref">
      <div>
        <b>明暗</b>
        <span>
          {#if skinOf(app.theme) === 'mincho'}
            「明朝墨」是单色主题，固定浅色。
          {:else}
            青空有浅色与深色两套；深色下侧栏毛玻璃也会跟着变深。
          {/if}
        </span>
      </div>
      <div class="seg" class:dim={skinOf(app.theme) === 'mincho'}>
        {#each SCHEMES as scheme (scheme.id)}
          <button
            class:on={app.theme === scheme.id}
            disabled={skinOf(app.theme) === 'mincho'}
            onclick={() => setMode(scheme.id)}>{scheme.name}</button
          >
        {/each}
      </div>
    </div>

  </section>

  <div class="about">
    KikuSub · 本地优先的日语字幕工作台。所有音视频与模型都在本机处理，不上传。
  </div>
</div>

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
  .settings {
    flex: 1;
    min-height: 0;
    overflow-y: auto;
    padding: var(--sp-8) var(--sp-10) var(--sp-12);
    display: grid;
    grid-template-columns: minmax(0, 960px);
    justify-content: center;
    align-content: start;
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
  .head-meta {
    display: flex;
    gap: 6px;
    font-size: 12px;
    color: var(--text-3);
    font-variant-numeric: tabular-nums;
    white-space: nowrap;
  }

  .sec {
    border-top: 1px solid var(--separator-soft);
    padding: 18px 0 6px;
  }
  .sec-head {
    display: flex;
    align-items: flex-start;
    gap: 12px;
    margin-bottom: 12px;
  }
  .sec-title {
    font-size: var(--fs-heading);
    font-weight: 600;
    margin-bottom: 3px;
  }
  .sec-desc {
    font-size: var(--fs-label);
    color: var(--text-2);
    line-height: 1.6;
    max-width: 640px;
  }
  .sec-head > .btn {
    margin-left: auto;
    flex: 0 0 auto;
  }
  .head-actions {
    margin-left: auto;
    display: flex;
    align-items: center;
    gap: 6px;
    flex: 0 0 auto;
  }
  .tts-engine {
    margin-top: 10px;
  }

  .engines {
    display: flex;
    flex-direction: column;
    gap: 10px;
  }
  .engine {
    border: 1px solid var(--separator-soft);
    border-radius: 8px;
    padding: 13px 15px 12px;
    background: var(--bg-content);
    transition: opacity 160ms var(--ease), border-color 160ms var(--ease);
  }
  .engine.off {
    opacity: 0.72;
  }
  .eng-top {
    display: flex;
    align-items: center;
    gap: 10px;
  }
  .eng-name {
    display: flex;
    align-items: baseline;
    gap: 8px;
    min-width: 0;
  }
  .eng-name b {
    font-size: var(--fs-heading);
    font-weight: 600;
  }
  .eng-purpose {
    font-size: 12px;
    color: var(--text-3);
  }
  .dot {
    width: 7px;
    height: 7px;
    border-radius: 50%;
    background: var(--text-3);
    flex: 0 0 7px;
  }
  .dot.ready {
    background: var(--success);
  }

  .enable {
    margin-left: auto;
    display: flex;
    align-items: center;
    gap: 7px;
    font-size: 12px;
    color: var(--text-3);
    flex: 0 0 auto;
  }

  .eng-desc {
    margin: 7px 0 8px;
    font-size: 12.5px;
    color: var(--text-2);
    line-height: 1.5;
  }

  .meta {
    display: flex;
    flex-wrap: wrap;
    gap: 5px;
    align-items: center;
  }
  .pill {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    height: 19px;
    padding: 0 7px;
    border-radius: 4px;
    background: var(--fill);
    color: var(--text-2);
    font-size: 12px;
    font-variant-numeric: tabular-nums;
  }
  .pill.mono {
    font-family: ui-monospace, 'SF Mono', Menlo, monospace;
    max-width: 260px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .status {
    margin-left: auto;
    font-size: 12px;
    font-variant-numeric: tabular-nums;
  }
  .status.ok {
    color: var(--success);
  }
  .status.missing {
    color: var(--warn);
  }

  .notes.warn {
    color: var(--warn);
  }

  .notes {
    margin-top: 7px;
    font-size: 12px;
    color: var(--text-3);
    line-height: 1.5;
  }

  .eng-actions {
    display: flex;
    align-items: center;
    gap: 6px;
    margin-top: 10px;
  }
  .path {
    font-size: 12px;
    color: var(--text-3);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    min-width: 0;
  }

  .dl {
    margin-top: 9px;
  }
  .dl-top {
    display: flex;
    justify-content: space-between;
    font-size: 12px;
    color: var(--text-2);
    margin-bottom: 4px;
    font-variant-numeric: tabular-nums;
  }
  .dl.error .dl-top {
    color: var(--danger);
  }

  .switch {
    appearance: none;
    width: 30px;
    height: 18px;
    border-radius: 4px;
    border: 0;
    background: var(--fill-strong);
    position: relative;
    padding: 0;
    transition: background 160ms var(--ease);
    flex: 0 0 30px;
  }
  .switch .knob {
    position: absolute;
    top: 2px;
    left: 2px;
    width: 14px;
    height: 14px;
    border-radius: 50%;
    background: #fff;
    box-shadow: 0 1px 2px rgba(0, 0, 0, 0.25);
    transition: transform 160ms var(--ease);
  }
  .switch.on {
    background: var(--control-on);
  }
  .switch.on .knob {
    transform: translateX(12px);
  }

  .grid {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 0 22px;
    border: 1px solid var(--separator-soft);
    border-radius: 8px;
    padding: 9px 14px;
  }
  .kv {
    display: flex;
    align-items: center;
    gap: 9px;
    padding: 6px 0;
    border-bottom: 1px solid var(--separator-soft);
    font-size: 12px;
    min-width: 0;
  }
  .kv.wide {
    grid-column: 1 / -1;
  }
  .kv > span {
    color: var(--text-3);
    flex: 0 0 76px;
  }
  .kv > b {
    font-weight: 500;
    color: var(--text);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    min-width: 0;
  }
  .kv > b.mono {
    font-family: ui-monospace, 'SF Mono', Menlo, monospace;
    font-size: 12px;
  }
  .paths {
    margin-top: 10px;
    border: 1px solid var(--separator-soft);
    border-radius: 8px;
    overflow: hidden;
  }
  .path-row {
    display: flex;
    align-items: center;
    gap: 10px;
    min-width: 0;
    padding: 8px 12px;
    border-bottom: 1px solid var(--separator-soft);
    font-size: 12px;
  }
  .path-row:last-child {
    border-bottom: 0;
  }
  .path-row > span {
    flex: 0 0 96px;
    color: var(--text-3);
    white-space: nowrap;
  }
  .path-row > b {
    flex: 1 1 auto;
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    font-weight: 500;
    color: var(--text);
  }
  .path-row > b.mono {
    font-family: ui-monospace, 'SF Mono', Menlo, monospace;
    font-size: 12px;
  }
  .path-actions {
    margin-left: auto;
    display: flex;
    align-items: center;
    gap: 6px;
    flex: 0 0 auto;
  }

  .log-row {
    display: flex;
    align-items: center;
    gap: 6px;
    flex-wrap: wrap;
  }
  .log-path {
    flex: 1 1 320px;
    min-width: 0;
    font-size: 12px;
    color: var(--text-3);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .log-meta {
    display: flex;
    gap: 14px;
    font-size: 12px;
    color: var(--text-3);
    margin-top: 9px;
    flex-wrap: wrap;
  }
  .log-tail {
    margin: 8px 0 0;
    max-height: 180px;
    overflow: auto;
    background: var(--fill);
    border-radius: 8px;
    padding: 9px 11px;
    font-family: ui-monospace, 'SF Mono', Menlo, monospace;
    font-size: 12px;
    line-height: 1.55;
    color: var(--text-2);
    user-select: text;
    white-space: pre-wrap;
    word-break: break-all;
  }
  .empty-log {
    margin-top: 9px;
    font-size: 12px;
    color: var(--text-3);
  }
  .tail {
    margin-top: 8px;
  }
  .tail summary {
    font-size: 12px;
    color: var(--text-3);
    cursor: default;
    list-style: none;
  }
  .tail summary::-webkit-details-marker {
    display: none;
  }
  .tail summary:hover {
    color: var(--text-2);
  }

  .skill-box {
    margin-top: 14px;
    padding-top: 12px;
    border-top: 1px solid var(--separator-soft);
  }
  .skill-head {
    display: flex;
    align-items: baseline;
    gap: 8px;
    margin-bottom: 8px;
  }
  .skill-head .muted {
    font-size: 12px;
    color: var(--text-3);
  }
  .skill-row {
    display: flex;
    align-items: center;
    gap: 8px;
    flex-wrap: wrap;
  }
  .skill-path {
    flex: 1;
    min-width: 220px;
    font-size: 12px;
    color: var(--text-3);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .ai-form,
  .ai-key {
    display: flex;
    flex-direction: column;
    gap: 9px;
    padding: 12px 0;
    border-top: 1px solid var(--separator-soft);
  }
  .ai-form label,
  .ai-key label {
    display: flex;
    flex-direction: column;
    gap: 4px;
    flex: 1;
    min-width: 0;
  }
  .ai-form label > span,
  .ai-key label > span {
    font-size: 12px;
    color: var(--text-3);
  }
  .ai-form input,
  .ai-key input {
    font: inherit;
    font-size: 12px;
    padding: 6px 9px;
    border-radius: 4px;
    border: 1px solid var(--separator);
    background: var(--bg-content);
    color: var(--text);
    outline: none;
    min-width: 0;
  }
  .ai-form input:focus,
  .ai-key input:focus {
    border-color: var(--accent);
    box-shadow: 0 0 0 3px var(--accent-soft);
  }
  .ai-grid3 {
    display: flex;
    align-items: flex-end;
    gap: 9px;
    flex-wrap: wrap;
  }
  .ai-grid3 label {
    max-width: 130px;
  }
  .ai-actions {
    display: flex;
    align-items: center;
    gap: 8px;
  }
  .ai-key {
    flex-direction: row;
    align-items: flex-end;
    flex-wrap: wrap;
  }
  .ai-key label {
    max-width: 360px;
  }

  .pref {
    display: flex;
    align-items: center;
    gap: 16px;
    padding: 11px 0;
    border-bottom: 1px solid var(--separator-soft);
  }
  .pref:last-child {
    border-bottom: 0;
  }
  .pref > div:first-child {
    flex: 1;
    min-width: 0;
    display: flex;
    flex-direction: column;
    gap: 2px;
  }
  .pref b {
    font-size: 12.5px;
    font-weight: 500;
  }
  .pref span {
    font-size: 12px;
    color: var(--text-3);
    line-height: 1.45;
  }
  /* 主题选择：实心色点 + 名字，别让用户先点一遍才知道长什么样 */
  .seg button {
    display: inline-flex;
    align-items: center;
    gap: 6px;
  }
  .swatch {
    width: 10px;
    height: 10px;
    border-radius: 50%;
    background: var(--sw-accent);
    box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--text) 12%, transparent);
    flex: 0 0 auto;
  }
  /* 选中态靠一条墨边，不只靠阴影：白胶囊压浅灰轨道只有 1.05:1 */
  .seg.theme button.on {
    box-shadow: inset 0 0 0 1px var(--line), var(--shadow-seg);
  }
  /* 单色主题下的明暗：整行退成描边 + 常规字色，说明为什么不能点 */
  .seg.dim {
    background: transparent;
    box-shadow: inset 0 0 0 1px var(--separator-soft);
  }
  .seg.dim button {
    color: var(--text-3);
  }

  .warn-box,
  .error-box {
    display: flex;
    align-items: center;
    gap: 6px;
    font-size: 12px;
    color: var(--warn);
    background: var(--warn-soft);
    border-radius: 8px;
    padding: 8px 10px;
    margin-top: 10px;
  }
  .error-box {
    color: var(--danger);
    background: var(--danger-soft);
  }
  .error-box .btn {
    margin-left: auto;
  }
  .loading {
    font-size: 12px;
    color: var(--text-3);
    padding: 16px 2px;
  }
  .footnote {
    font-size: 12px;
    color: var(--text-3);
    line-height: 1.6;
    margin: 10px 0 0;
  }
  code {
    font-family: ui-monospace, 'SF Mono', Menlo, monospace;
    background: var(--fill);
    border-radius: 4px;
    padding: 0 4px;
  }
  .about {
    margin-top: 26px;
    padding-top: 14px;
    border-top: 1px solid var(--separator-soft);
    font-size: 12px;
    color: var(--text-3);
    text-align: center;
  }

  .seg {
    display: inline-flex;
    background: var(--fill);
    border-radius: 4px;
    padding: 1px;
    flex: 0 0 auto;
  }
  .seg button {
    appearance: none;
    border: 0;
    background: transparent;
    font: inherit;
    font-size: 12px;
    height: 22px;
    padding: 0 9px;
    border-radius: 4px;
    color: var(--text-2);
  }
  .seg button.on {
    background: var(--bg-content);
    color: var(--text);
    box-shadow: 0 0.5px 1.5px rgba(0, 0, 0, 0.12);
  }
  .seg button:disabled {
    opacity: 0.45;
  }
  .tts-pick {
    height: 28px;
    max-width: 260px;
    border: 1px solid var(--separator);
    border-radius: 4px;
    background: var(--fill);
    color: var(--text-2);
    font: inherit;
    font-size: 12px;
    padding: 0 7px;
    flex: 0 0 auto;
  }
  .tts-pick:disabled {
    opacity: 0.5;
  }
  .tiny {
    height: 20px;
    font-size: 12px;
    padding: 0 6px;
  }
</style>
