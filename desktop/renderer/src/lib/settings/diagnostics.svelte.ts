/**
 * 设置页「环境与诊断 → 日志与诊断」的状态与动作。
 *
 * 从 `views/SettingsView.svelte` 搬出：诊断数据在页面打开时就要预热（引擎页的
 * 就绪数量也读它），切页签不能丢；四个动作（复制精简诊断 / 复制最近日志 /
 * 清理旧日志 / 清空全部日志）都要带确认与 toast，集中在一处比散在模板里安全。
 */
import { api, logEvent } from '../api';
import { toast } from '../store.svelte';
import { formatBytes } from '../time';

export type Diagnostics = Awaited<ReturnType<typeof api.diagnostics>>;

export const diagnostics = $state({
  data: null as Diagnostics | null,
  loading: false,
  /** 最近一次复制的目标：'' | 'log' | 'diag' */
  copying: '',
  cleaning: false,
});

export async function loadDiagnostics(lines = 120) {
  diagnostics.loading = true;
  try {
    diagnostics.data = await api.diagnostics(lines);
  } catch (err) {
    toast(`诊断信息读取失败：${(err as Error).message}`, 'warn');
  } finally {
    diagnostics.loading = false;
  }
}

export function sizeText(bytes: number): string {
  return bytes > 0 ? formatBytes(bytes) : '0 B';
}

/** 单行截断：日志里的 detail 可能带 8000 字符的 JSON，整段复制会卡死备忘录。 */
export function clipLine(line: string, limit = 500): string {
  const text = String(line ?? '');
  return text.length > limit ? `${text.slice(0, limit)}…` : text;
}

async function copy(text: string, tag: string) {
  try {
    if (window.kikusub.writeClipboard) {
      await window.kikusub.writeClipboard(text);
    } else {
      await navigator.clipboard.writeText(text);
    }
    diagnostics.copying = tag;
    setTimeout(() => {
      if (diagnostics.copying === tag) diagnostics.copying = '';
    }, 1600);
    toast('已复制到剪贴板');
  } catch (err) {
    toast(`复制失败：${(err as Error).message}`, 'error');
  }
}

export async function copyRecentLogs() {
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

export async function copyDiagnosticsSummary() {
  try {
    const payload = diagnostics.data ?? (await api.diagnostics(120));
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
      engines: payload.engines.map((engine) => ({
        key: engine.key,
        label: engine.label,
        installed: engine.installed,
        enabled: engine.enabled,
        size_bytes: engine.size_bytes,
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

export async function cleanOldLogs() {
  if (diagnostics.cleaning) return;
  if (
    !window.confirm(
      '清理所有轮转日志备份（kikusub.log.1 / main.log.1 等）。\n\n正在写入的日志会保留，只删除过期或超量的旧文件。',
    )
  ) {
    return;
  }
  diagnostics.cleaning = true;
  try {
    const result = await api.cleanLogs();
    if (result.removed > 0) {
      toast(`已清理 ${result.removed} 个旧日志，释放 ${formatBytes(result.freed)}`);
    } else {
      toast(
        `当前没有过期备份；日志共 ${sizeText(diagnostics.data?.log_bytes ?? result.total_bytes)}。要立即释放空间，点「清空全部日志」。`,
        'warn',
      );
    }
    logEvent('info', 'logs-clean', `removed=${result.removed} freed=${result.freed}`);
    await loadDiagnostics();
  } catch (err) {
    toast(`清理失败：${(err as Error).message}`, 'error');
  } finally {
    diagnostics.cleaning = false;
  }
}

export async function clearAllLogs() {
  if (diagnostics.cleaning) return;
  if (
    !window.confirm(
      '清空全部日志？\n\n会清掉 kikusub.log、main.log 以及所有轮转备份；设置、字幕和媒体都不受影响。',
    )
  ) {
    return;
  }
  diagnostics.cleaning = true;
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
    await loadDiagnostics();
  } catch (err) {
    toast(`清空失败：${(err as Error).message}`, 'error');
  } finally {
    diagnostics.cleaning = false;
  }
}
