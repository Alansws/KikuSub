/**
 * 模型/资产下载的进度状态机（纯函数，无 Svelte、无网络）。
 *
 * 引擎权重与可选的 VAD 切分器共用同一条下载通道：服务端 job 的
 * `start / progress / done / error` 事件如何折叠成界面状态，只在这里定义一次，
 * `store.svelte.ts` 只负责把它接到 WebSocket 与 toast 上。
 */

import type { JobEvent } from './api';

export interface DownloadProgress {
  key: string;
  label: string;
  percent: number;
  stage: string;
  status: 'running' | 'done' | 'error';
}

export function beginDownload(key: string, label: string): DownloadProgress {
  return { key, label, percent: 0, stage: '准备下载…', status: 'running' };
}

export function failedDownload(key: string, label: string, message: string): DownloadProgress {
  return { key, label, percent: 0, stage: message || '下载失败', status: 'error' };
}

/**
 * 把一条 job 事件折进当前进度；与当前下载无关的事件返回 `null`。
 *
 * 百分比只增不减：下载器的 progress 帧和磁盘估算帧会交错到达。
 */
export function reduceDownload(
  current: DownloadProgress | null,
  key: string,
  event: JobEvent,
): DownloadProgress | null {
  if (!current || current.key !== key) return null;
  if (event.job?.percent != null) {
    current = {
      ...current,
      percent: Math.max(current.percent, event.job.percent),
      stage: event.job.stage || current.stage,
    };
  }
  if (event.type === 'progress') {
    current = {
      ...current,
      percent: Math.max(current.percent, event.percent ?? event.job_percent ?? 0),
      stage: event.stage || current.stage,
    };
  }
  if (event.type === 'done') {
    return { ...current, percent: 100, stage: '下载完成', status: 'done' };
  }
  if (event.type === 'error') {
    return { ...current, stage: event.message || '下载失败', status: 'error' };
  }
  return current;
}
