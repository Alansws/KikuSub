/**
 * 设置页「本机总览」用的硬件信息。
 *
 * 侧车只回 `device`（mps/cpu）与 `machine`（arm64）——拿不到芯片型号与物理内存，
 * 所以这两项由主进程的 `app:info` 提供（`main.cjs` 里的 os.cpus/os.totalmem）。
 * 主进程没给（旧包、或被裁掉的构建）时退回「Apple Silicon / arm64」这种通用说法，
 * 界面不会出现空白或占位符。
 */
import { formatBytes } from '../time';

export interface HardwareInfo {
  chip: string;
  cores: number;
  totalMemBytes: number;
  platform: string;
  arch: string;
}

export const hardware = $state({
  loaded: false,
  info: null as HardwareInfo | null,
});

function sanitizeChip(raw: unknown): string {
  // macOS 上 os.cpus()[0].model 就是 "Apple M4 Pro"；Intel 机器会带 "CPU @ 2.6GHz"
  return String(raw ?? '')
    .replace(/\s*CPU\s*@.*$/i, '')
    .replace(/\s+/g, ' ')
    .trim();
}

export async function loadHardware(force = false) {
  if (hardware.loaded && !force) return;
  try {
    const info = await window.kikusub?.info?.();
    hardware.info = info
      ? {
          chip: sanitizeChip(info.chip),
          cores: Number(info.cores) || 0,
          totalMemBytes: Number(info.totalMemBytes) || 0,
          platform: String(info.platform ?? ''),
          arch: String(info.arch ?? ''),
        }
      : null;
  } catch {
    hardware.info = null;
  } finally {
    hardware.loaded = true;
  }
}

/** 芯片行：`Apple M4 Pro`，取不到时退成 `Apple Silicon` / `Intel Mac` / `本机`。 */
export function chipLabel(info: HardwareInfo | null, arch: string): string {
  if (info?.chip) return info.chip;
  if (arch === 'arm64') return 'Apple Silicon';
  if (arch) return 'Intel Mac';
  return '本机';
}

/** 内存行：`48 GB`，取不到时给空字符串（调用方决定要不要显示）。 */
export function memoryText(bytes: number): string {
  return bytes > 0 ? formatBytes(bytes) : '';
}

/**
 * `ffmpeg -version` 的第一行 → 版本号。
 * 形如 `ffmpeg version 9.0.2 Copyright (c) 2000-2025 the FFmpeg developers`。
 */
export function ffmpegVersion(version: string): string {
  const text = String(version ?? '').trim();
  if (!text) return '';
  const match = text.match(/version\s+([^\s]+)/i);
  return match ? match[1] : text.split(/\s+/).slice(0, 2).join(' ');
}
