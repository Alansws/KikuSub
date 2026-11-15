/**
 * 设置页「外观与朗读 → 朗读」的偏好与 OmniVoice 状态机。
 *
 * 状态机从 `views/SettingsView.svelte` 原样搬出（行为不变）：
 * 下载（真实百分比）与校验（不确定进度）共用一条轨道，完成/失败闪一下再回 idle。
 * 搬到模块级是为了切页签不打断进度轮询，也让这块逻辑不再和页面模板纠缠。
 */
import { api } from '../api';
import {
  downloadTtsModel,
  loadTtsVoices,
  setTtsDefaultKind,
  setTtsDefaultVoiceId,
  toast,
  tts,
} from '../store.svelte';

export type TtsUiState = 'idle' | 'verifying' | 'downloading' | 'done' | 'error';

export const ttsPrefs = $state({
  uiState: 'idle' as TtsUiState,
  stageText: '',
  checking: false,
});

let uiTimer: ReturnType<typeof setTimeout> | undefined;
let lastDownloadStatus = '';

export function clearTtsTimer() {
  if (uiTimer) {
    clearTimeout(uiTimer);
    uiTimer = undefined;
  }
}

export function showTtsState(state: TtsUiState, stage = '', timeout = 0) {
  clearTtsTimer();
  ttsPrefs.uiState = state;
  ttsPrefs.stageText = stage;
  if (timeout > 0) {
    uiTimer = setTimeout(() => {
      ttsPrefs.uiState = 'idle';
      ttsPrefs.stageText = '';
      uiTimer = undefined;
    }, timeout);
  }
}

/** 由页签在挂载时调用一次：订阅 store 里的下载状态，转成 UI 状态。 */
export function syncTtsDownloadState() {
  const status = tts.download?.status ?? 'idle';
  if (!lastDownloadStatus) {
    lastDownloadStatus = status;
    if (status === 'running') ttsPrefs.uiState = 'downloading';
    return;
  }
  if (status === lastDownloadStatus) return;
  if (status === 'running') {
    clearTtsTimer();
    ttsPrefs.uiState = 'downloading';
    ttsPrefs.stageText = '';
  } else if (status === 'done' && (lastDownloadStatus === 'running' || ttsPrefs.uiState === 'downloading')) {
    showTtsState('done', 'OmniVoice 模型已就绪', 1600);
  } else if (status === 'error' && (lastDownloadStatus === 'running' || ttsPrefs.uiState === 'downloading')) {
    showTtsState('error', tts.download?.error || 'OmniVoice 下载失败', 4500);
  }
  lastDownloadStatus = status;
}

export const ttsPercent = () =>
  ttsPrefs.uiState === 'downloading'
    ? (tts.download?.percent ?? 0)
    : ttsPrefs.uiState === 'done'
      ? 100
      : null;

export const ttsBarState = () =>
  ttsPrefs.uiState === 'done' ? 'done' : ttsPrefs.uiState === 'error' ? 'error' : 'running';

export const ttsRightText = () =>
  ttsPrefs.uiState === 'verifying'
    ? '校验中'
    : ttsPrefs.uiState === 'error'
      ? '失败'
      : `${ttsPercent() ?? 0}%`;

export const ttsStageLine = () =>
  ttsPrefs.uiState === 'verifying'
    ? '正在校验 OmniVoice 权重…'
    : ttsPrefs.uiState === 'downloading'
      ? tts.download?.stage || '正在下载 OmniVoice 模型…'
      : ttsPrefs.stageText;

export const ttsProgressVisible = () => ttsPrefs.uiState !== 'idle';

const ttsRunning = () => tts.download?.status === 'running';

/**
 * OmniVoice 的「校验 / 补齐」。
 *
 * 已安装时先走只读校验：完整就立刻给出结果，缺文件才弹下载确认。之前它无条件
 * 弹「是否下载」，与两个 ASR 引擎的行为不一致（用户明明装好了还会被问一遍）。
 */
export async function onDownloadTts() {
  if (ttsRunning() || ttsPrefs.checking) return;
  let needsDownload = !tts.engine?.installed;
  if (!needsDownload) {
    ttsPrefs.checking = true;
    showTtsState('verifying', '正在校验 OmniVoice 权重…');
    const started = Date.now();
    try {
      const result = await api.verifyTtsModel();
      // 只读校验通常几十毫秒；给不确定进度至少 450ms，避免进度条一闪而过。
      const remaining = 450 - (Date.now() - started);
      if (remaining > 0) await new Promise((resolve) => setTimeout(resolve, remaining));
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
      ttsPrefs.checking = false;
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
  if (!tts.download) showTtsState('error', '下载没有启动，请查看日志', 4000);
}

export function onTtsDefault(kind: 'system' | 'clone') {
  if (kind === 'clone' && !tts.custom.length) {
    toast('还没有克隆音色：先在核对台上传参考音频，或选中一句「从当前句截取」', 'warn');
    return;
  }
  setTtsDefaultKind(kind);
  toast(kind === 'clone' ? '默认朗读音色已切换为克隆音色' : '默认朗读音色已切换为系统语音');
}

export function onTtsDefaultVoice(event: Event) {
  setTtsDefaultVoiceId((event.currentTarget as HTMLSelectElement).value);
}

/** 当前默认克隆音色（找不到时 null：界面显示「最近保存的音色」）。 */
export function ttsDefaultVoice() {
  return tts.custom.find((voice) => voice.id === tts.defaultVoiceId) ?? null;
}
