/**
 * 结构建议（Phase 1）的前端状态。
 *
 * 与润色提案完全独立：这里只处理外部模型返回的 `{"ops":[...]}`，由服务端
 * 绑定 digest/revision 后落成 `{stem}.ai-structure.json`。应用走一次原子
 * 历史（⌘Z 整批退回），应用成功后这份建议即被丢弃——剩余 ops 的旧下标已不可信。
 */

import {
  api,
  type StructureOpView,
  type StructurePayload,
  type StructureSummary,
} from './api';
import { dual } from './dualReview.svelte';
import { applyCueSnapshot, app, scheduleDraftSave, toast } from './store.svelte';

export const structure = $state({
  open: false,
  text: '',
  exists: false,
  loading: false,
  parsing: false,
  applying: false,
  promptLoading: false,
  ops: [] as StructureOpView[],
  selected: {} as Record<number, boolean>,
  warnings: [] as string[],
  errors: [] as string[],
  summary: null as StructureSummary | null,
  revision: '',
  path: '',
  sourceCount: 0,
  currentCount: 0,
  /** 已经为哪份上下文拉过结构建议，避免切页时把刚解析好的状态顶掉。 */
  loadedFor: '',
});

function contextKey(): string {
  return `${app.media?.id ?? ''}:${app.cuesRevision}`;
}

function clearPreview() {
  structure.exists = false;
  structure.ops = [];
  structure.selected = {};
  structure.warnings = [];
  structure.errors = [];
  structure.summary = null;
  structure.revision = '';
  structure.path = '';
  structure.sourceCount = 0;
  structure.currentCount = 0;
}

function clearAll() {
  clearPreview();
  structure.text = '';
  structure.open = false;
  structure.loadedFor = contextKey();
}

function applyPayload(payload: StructurePayload) {
  structure.exists = Boolean(payload.exists);
  structure.ops = payload.ops ?? [];
  structure.selected = {};
  for (const op of structure.ops) {
    structure.selected[op.id] = op.conflict.length === 0;
  }
  structure.warnings = payload.warnings ?? [];
  structure.summary = payload.summary ?? null;
  structure.revision = payload.revision ?? '';
  structure.path = payload.path ?? '';
  structure.sourceCount = payload.source?.count ?? 0;
  structure.currentCount = payload.current_count ?? app.cues.length;
  structure.errors = [];
}

export function loadStructure(force = false): Promise<void> {
  if (!app.connected) return Promise.resolve();
  const key = contextKey();
  if (!force && structure.loadedFor === key) return Promise.resolve();
  structure.loading = true;
  return (async () => {
    try {
      const payload = await api.getStructure();
      applyPayload(payload);
    } catch (err) {
      const message = (err as Error).message;
      clearPreview();
      // 「还没有」是正常空态；「字幕已变化」要让用户知道旧建议为什么消失。
      if (!/还没有结构建议/.test(message)) structure.errors = [message];
    } finally {
      structure.loadedFor = key;
      structure.loading = false;
    }
  })();
}

export function openStructurePanel() {
  structure.open = true;
  if (!structure.ops.length) void loadStructure(true);
}

export function closeStructurePanel() {
  structure.open = false;
}

export async function copyStructurePrompt() {
  if (!app.cues.length) {
    toast('当前没有可检查的字幕', 'warn');
    return;
  }
  if (structure.promptLoading) return;
  structure.promptLoading = true;
  try {
    const mode: 'single' | 'dual' = dual.exists ? 'dual' : 'single';
    const res = await api.getStructurePrompt(mode);
    if (window.kikusub?.writeClipboard) {
      await window.kikusub.writeClipboard(res.prompt);
    } else if (navigator.clipboard) {
      await navigator.clipboard.writeText(res.prompt);
    }
    structure.open = true;
    toast(
      mode === 'dual'
        ? `已复制结构检查提示词：${res.count} 条 A + ${res.alt_count} 条 B 参考`
        : `已复制结构检查提示词：${res.count} 条字幕`,
    );
  } catch (err) {
    toast((err as Error).message, 'error');
  } finally {
    structure.promptLoading = false;
  }
}

export async function parseStructurePaste() {
  const text = structure.text.trim();
  if (!text) {
    toast('先粘贴外部模型返回的 {"ops":[...]}', 'warn');
    return;
  }
  if (structure.parsing) return;
  structure.parsing = true;
  try {
    const payload = await api.parseStructure(text);
    applyPayload(payload);
    structure.open = true;
    structure.loadedFor = contextKey();
    const total = structure.ops.length;
    const conflicts = structure.summary?.conflicts ?? 0;
    if (!total) {
      toast('模型没有给出结构修改（ops 为空）', 'info');
    } else if (conflicts) {
      toast(`已解析 ${total} 项结构建议，其中 ${conflicts} 项冲突（红色项不能应用）`, 'warn');
    } else {
      toast(`已解析 ${total} 项结构建议，勾选后应用`);
    }
  } catch (err) {
    structure.errors = [(err as Error).message];
    toast((err as Error).message, 'error');
  } finally {
    structure.parsing = false;
  }
}

export function toggleStructureOp(id: number) {
  const op = structure.ops.find((item) => item.id === id);
  if (!op || op.conflict.length) return;
  structure.selected[id] = !structure.selected[id];
}

export function setAllStructureOps(value: boolean) {
  for (const op of structure.ops) {
    if (!op.conflict.length) structure.selected[op.id] = value;
  }
}

export function selectedStructureIds(): number[] {
  return structure.ops
    .filter((op) => structure.selected[op.id] && op.conflict.length === 0)
    .map((op) => op.id);
}

export function selectedStructureCount(): number {
  return selectedStructureIds().length;
}

export function structureConflictCount(): number {
  return structure.ops.filter((op) => op.conflict.length > 0).length;
}

export function structureSelectableCount(): number {
  return structure.ops.length - structureConflictCount();
}

export async function applyStructureOps(): Promise<boolean> {
  if (!structure.ops.length || structure.applying) return false;
  const ids = selectedStructureIds();
  if (!ids.length) {
    toast('先勾选至少一项结构建议', 'warn');
    return false;
  }
  structure.applying = true;
  try {
    const res = await api.applyStructure({ accept: ids, revision: structure.revision });
    applyCueSnapshot(res);
    scheduleDraftSave();
    const applied = Number(res.applied ?? 0);
    toast(
      applied
        ? `已应用 ${applied} 项结构修改（⌘Z 可整批撤回）；其余建议已丢弃，请重新粘贴下一轮`
        : '没有实际变化；这份结构建议已丢弃',
      applied ? 'info' : 'warn',
    );
    clearAll();
    return applied > 0;
  } catch (err) {
    toast((err as Error).message, 'error');
    return false;
  } finally {
    structure.applying = false;
  }
}

export async function discardStructure() {
  try {
    await api.deleteStructure();
  } catch {
    /* 文件删不掉也让界面回到空态 */
  }
  clearAll();
  toast('已丢弃结构建议');
}
