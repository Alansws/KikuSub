/**
 * 设置页「环境与诊断 → 路径管理」的动作。
 *
 * 三个可改路径各有一对动作（更改 / 恢复默认），模型目录还会重启内核，
 * 所以确认文案与「等内核 ready」的顺序必须原样保留——这些是从 SettingsView 搬过来的，
 * 行为不变，只是不再和模板写在一个文件里。
 */
import { app, loadSettings, settings, toast, updateSettings } from '../store.svelte';
import { logEvent } from '../api';
import { diagnostics, loadDiagnostics } from './diagnostics.svelte';

export const pathState = $state({
  changingModels: false,
  changingExport: false,
});

export function openPath(path: string) {
  if (!path) return;
  void window.kikusub.openPath(path);
}

export function reveal(path: string) {
  if (path) window.kikusub.revealInFinder(path);
}

function trimSlash(value: string) {
  return value.replace(/\/+$/, '');
}

function exportDirNow(): string {
  return (
    settings.data?.paths.export_dir || diagnostics.data?.paths.export_dir || app.config?.export_dir || ''
  );
}

function videoExportDirNow(): string {
  return (
    settings.data?.paths.video_export_dir ||
    diagnostics.data?.paths.video_export_dir ||
    app.config?.video_export_dir ||
    ''
  );
}

function modelsDirNow(): string {
  return diagnostics.data?.paths.models_dir ?? settings.data?.paths.models_dir ?? '';
}

export async function changeExportDir() {
  if (pathState.changingExport) return;
  const current = exportDirNow();
  let picked = '';
  try {
    picked =
      (await window.kikusub.pickDirectory({
        title: '选择字幕默认导出文件夹',
        defaultPath: current,
      })) || '';
  } catch (err) {
    toast((err as Error).message, 'error');
    return;
  }
  if (!picked || trimSlash(picked) === trimSlash(current)) return;
  pathState.changingExport = true;
  try {
    await updateSettings({ export_dir: picked });
    logEvent('info', 'export-dir-change', picked);
    await loadDiagnostics();
  } finally {
    pathState.changingExport = false;
  }
}

export async function resetExportDir() {
  if (pathState.changingExport) return;
  if (!window.confirm('恢复为默认导出文件夹（运行数据目录）？\n\n已经导出的字幕不会被移动或删除。')) {
    return;
  }
  pathState.changingExport = true;
  try {
    await updateSettings({ export_dir: '' });
    logEvent('info', 'export-dir-reset', '');
    await loadDiagnostics();
  } finally {
    pathState.changingExport = false;
  }
}

export async function changeVideoExportDir() {
  if (pathState.changingExport) return;
  const current = videoExportDirNow();
  let picked = '';
  try {
    picked =
      (await window.kikusub.pickDirectory({
        title: '选择成片导出文件夹',
        defaultPath: current,
      })) || '';
  } catch (err) {
    toast((err as Error).message, 'error');
    return;
  }
  if (!picked || trimSlash(picked) === trimSlash(current)) return;
  pathState.changingExport = true;
  try {
    await updateSettings({ video_export_dir: picked });
    logEvent('info', 'video-export-dir-change', picked);
    await loadDiagnostics();
  } finally {
    pathState.changingExport = false;
  }
}

export async function resetVideoExportDir() {
  if (pathState.changingExport) return;
  if (!window.confirm('恢复为跟随字幕导出文件夹？\n\n已经导出的成片不会被移动或删除。')) return;
  pathState.changingExport = true;
  try {
    await updateSettings({ video_export_dir: '' });
    logEvent('info', 'video-export-dir-reset', '');
    await loadDiagnostics();
  } finally {
    pathState.changingExport = false;
  }
}

/**
 * 切换模型目录：会重启内核（当前会话的媒体、字幕与撤回记录清空），
 * 所以先让用户确认，再挂 ready 监听、最后才真正调用——顺序反了会漏掉 ready 事件。
 */
export async function changeModelsDir() {
  if (pathState.changingModels) return;
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
  if (!picked || trimSlash(picked) === trimSlash(modelsDirNow())) return;

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

  pathState.changingModels = true;
  try {
    await window.kikusub.setModelsDir(picked);
    toast('模型目录已切换，正在重启内核…');
    logEvent('info', 'models-dir-change', picked);
    await ready;
    await loadSettings(true);
    await loadDiagnostics();
    toast('内核已重启，新的模型目录已生效');
  } catch (err) {
    toast(`切换失败：${(err as Error).message}`, 'error');
    logEvent('error', 'models-dir-change-failed', picked, String(err));
  } finally {
    pathState.changingModels = false;
  }
}
