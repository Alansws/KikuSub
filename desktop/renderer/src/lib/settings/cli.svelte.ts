/**
 * 设置页「命令行工具」状态：把 app 内的 kikusub 软链到 ~/.local/bin。
 *
 * 与 Agent 技能是配套的两件事：技能告诉 agent「怎么用」，CLI 提供「用什么」。
 * 状态与动作放主进程（desktop/main/cli.cjs），这里只负责界面状态。
 */
import { toast } from '../store.svelte';

export interface CliHint {
  binDir: string;
  line: string;
  command: string;
  note: string;
}

export interface CliInfo {
  ok: boolean;
  error?: string;
  command: string;
  target: string;
  linkPath: string;
  binDir: string;
  targetExists: boolean;
  installed: boolean;
  upToDate: boolean;
  inPath: boolean;
  conflict: boolean;
  hint?: CliHint;
}

export const cliState = $state({
  info: null as CliInfo | null,
  busy: false,
  loaded: false,
});

export async function loadCli() {
  try {
    const res = await window.kikusub?.cli?.status?.();
    cliState.info = res ? (res as CliInfo) : null;
  } catch {
    cliState.info = null;
  } finally {
    cliState.loaded = true;
  }
}

export async function installCli() {
  if (cliState.busy) return;
  cliState.busy = true;
  try {
    const res = await window.kikusub.cli.install();
    if (!res?.ok) {
      toast(res?.error || '安装命令行工具失败', 'error');
      return;
    }
    await loadCli();
    toast(`已安装：${res.linkPath}`);
  } catch (err) {
    toast((err as Error).message, 'error');
  } finally {
    cliState.busy = false;
  }
}

export async function uninstallCli() {
  if (cliState.busy) return;
  cliState.busy = true;
  try {
    const res = await window.kikusub.cli.uninstall();
    if (!res?.ok) {
      toast(res?.error || '卸载失败', 'error');
      return;
    }
    await loadCli();
    toast(res?.removed ? '已移除 ~/.local/bin/kikusub' : '本来就没有安装');
  } catch (err) {
    toast((err as Error).message, 'error');
  } finally {
    cliState.busy = false;
  }
}

export type CliStatusLabel = '已安装' | '需重装' | '未安装' | '安装被占用';

export function cliStatusLabel(info: CliInfo | null): CliStatusLabel {
  if (!info) return '未安装';
  if (info.conflict) return '安装被占用';
  if (!info.installed) return '未安装';
  return info.upToDate ? '已安装' : '需重装';
}

export function cliStatusOk(info: CliInfo | null): boolean {
  return Boolean(info?.installed && info?.upToDate && !info?.conflict);
}
