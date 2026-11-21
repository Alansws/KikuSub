/**
 * 外部提案观察器：CLI / agent 提交提案后，让已打开的界面自己发现并刷新。
 *
 * 为什么是 2 秒轮询而不是 SSE：sidecar 是本地 FastAPI，轮询 `/api/proposals/status`
 * 只是一次 stat（不读提案正文），失败模式只有「这次没拉到」；SSE 要处理重连、
 * token 走查询参数、窗口休眠与连接生命周期，收益（最多快 2 秒）与风险不成比例。
 * 窗口不可见时不轮询，重新聚焦立即拉一次。
 *
 * 不覆盖用户草稿：润色/翻译有未提交的 accept/edits 时只提示、不重载；结构建议
 * 只在面板打开时刷新；断句重排只提示，由用户在页面上点「载入外部提案」。
 */

import { api } from './api';
import { ai, loadAiProposal } from './aiWorkspace.svelte';
import { loadStructure, structure } from './structure.svelte';
import { reshape } from './reshape.svelte';
import { app, toast } from './store.svelte';

export const externalProposals = $state({
  revision: '',
  /** 外部断句重排提案的摘要；ReshapeView 据此显示「载入」入口。 */
  reshape: null as null | { path: string; count: number; stale: boolean; at: number },
});

const POLL_MS = 2000;

let timer: number | undefined;
let started = false;
let seen: Map<string, number> | null = null;
let polling = false;

function keyOf(item: { kind: string; lang: string }): string {
  return `${item.kind}:${item.lang || ''}`;
}

function aiDirty(): boolean {
  if (ai.saving || ai.applying) return true;
  if (Object.keys(ai.edits).length > 0) return true;
  return Object.values(ai.accept).some((value) => value === false);
}

async function refreshPolish(item: { kind: string; lang: string }): Promise<void> {
  if (item.kind !== ai.kind) return;
  if (item.kind === 'translate' && item.lang !== ai.lang) return;
  if (aiDirty()) {
    toast('外部 Agent 更新了提案，但你还有未应用的修改；已保留当前内容，点「重新加载」查看新版', 'warn');
    return;
  }
  await loadAiProposal(true);
  toast(
    item.kind === 'translate'
      ? `已载入外部 Agent 的新翻译提案（${item.lang}）`
      : '已载入外部 Agent 的新润色提案',
  );
}

async function watchRevision(items: { kind: string; lang: string; mtime: number }[]): Promise<void> {
  const current = new Map(items.map((item) => [keyOf(item), item.mtime]));
  if (seen === null) {
    seen = current;
    return;
  }
  const changed = items.filter((item) => seen?.get(keyOf(item)) !== item.mtime);
  // 被删除的提案不提示；把 seen 对齐到当前，重新出现时才会再次触发。
  seen = current;
  if (!changed.length) return;

  const messages: string[] = [];
  for (const item of changed) {
    if (item.kind === 'polish' || item.kind === 'translate') {
      const isCurrent =
        item.kind === ai.kind && (item.kind !== 'translate' || item.lang === ai.lang);
      if (isCurrent) {
        await refreshPolish(item);
      } else if (!messages.length) {
        messages.push(
          item.kind === 'translate'
            ? `外部 Agent 提交了翻译提案（${item.lang}）`
            : '外部 Agent 提交了润色提案',
        );
      }
    } else if (item.kind === 'structure') {
      if (structure.open) {
        await loadStructure(true);
        messages.push('结构建议已刷新');
      } else {
        messages.push('外部 Agent 提交了结构建议，到「润色 / 断句重排」页查看');
      }
    } else if (item.kind === 'reshape') {
      try {
        const payload = await api.getReshapeProposal();
        externalProposals.reshape = {
          path: payload.path,
          count: payload.cues.length,
          stale: payload.stale,
          at: Date.now(),
        };
        messages.push(
          payload.stale
            ? '断句重排提案已过期（字幕变过），请让 agent 重新提交'
            : `外部 Agent 提交了断句重排提案（${payload.cues.length} 条），到「断句重排」页载入`,
        );
      } catch {
        messages.push('外部 Agent 提交了断句重排提案，到「断句重排」页查看');
      }
    }
  }
  if (messages.length) toast(messages.join('；'));
}

async function poll(): Promise<void> {
  if (!app.connected || polling) return;
  polling = true;
  try {
    const payload = await api.proposalStatus();
    externalProposals.revision = payload.revision || '';
    await watchRevision(payload.items || []);
  } catch {
    /* 轮询失败不打扰用户：下一次 tick 会再试 */
  } finally {
    polling = false;
  }
}

export function startProposalWatcher(): void {
  if (started) return;
  started = true;
  const kick = () => {
    if (document.visibilityState === 'visible') void poll();
  };
  timer = window.setInterval(kick, POLL_MS);
  document.addEventListener('visibilitychange', kick);
  window.addEventListener('focus', kick);
  void poll();
}

/** 页面主动「载入外部提案」：只填粘贴框，解析/覆盖仍由用户点。 */
export async function loadExternalReshape(): Promise<boolean> {
  try {
    const payload = await api.getReshapeProposal();
    if (payload.stale) {
      toast('这份断句重排提案是旧字幕的（digest 对不上），已拒绝载入', 'warn');
      return false;
    }
    reshape.text = payload.text;
    reshape.pasteOpen = true;
    reshape.errors = [];
    toast(`已填入外部提案（${payload.cues.length} 条）：确认批次范围后点「解析」`);
    return true;
  } catch (err) {
    toast((err as Error).message, 'error');
    return false;
  }
}

/** 仅供测试重置（页面生命周期里不需要）。 */
export function stopProposalWatcher(): void {
  if (timer !== undefined) window.clearInterval(timer);
  timer = undefined;
  started = false;
  seen = null;
}
