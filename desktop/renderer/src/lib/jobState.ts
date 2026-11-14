/**
 * 「有没有任务在跑」的唯一判据。
 *
 * **不要用 `!!app.job` 判断**：任务跑完后 `app.job` 会保留最后一份快照给状态栏与工具栏
 * 读（进度、耗时、阶段文案），于是 `!!app.job` 永远为真——2026-11-14 实测「另一引擎复核」
 * 按钮在第一次转写之后永久变灰就是这个原因。
 *
 * 放在独立文件而不是 store 里，是为了不动 `store.svelte.ts` 的行数预算（只许变短）。
 */
import { app } from './store.svelte';

export function jobBusy(): boolean {
  const status = app.job?.status;
  return status === 'running' || status === 'queued' || status === 'cancelling';
}
