/**
 * 提示词模板库的前端状态。
 *
 * 从 `store.svelte.ts` 拆出来（那个文件有行数预算，只许变短）。模板分三类：
 * 单源润色 / 双源润色 / 翻译，**各自记住自己的当前选中**；旧版只有翻译，
 * 所以服务端会把没有分类的模板归入翻译，这里不需要兼容分支。
 */

import { api, type PromptLibrary, type PromptTemplate } from './api';
import { app } from './store.svelte';
import { toast } from './store.svelte';

export type PromptCategory = 'polish_single' | 'polish_dual' | 'translate';

export const prompts = $state({
  items: [] as PromptTemplate[],
  /** 翻译分类的选中项（旧字段名保留，服务端也仍写 `selected`）。 */
  selected: '',
  selectedPolishSingle: '',
  selectedPolishDual: '',
  path: '',
  loading: false,
  error: '',
});

let promptsLoaded = false;

export function promptSelectedId(category: PromptCategory = 'translate'): string {
  if (category === 'polish_single') return prompts.selectedPolishSingle;
  if (category === 'polish_dual') return prompts.selectedPolishDual;
  return prompts.selected;
}

export function promptItemsFor(category: PromptCategory): PromptTemplate[] {
  return prompts.items.filter((item) => (item.category || 'translate') === category);
}

export function applyPromptLibrary(lib: PromptLibrary) {
  prompts.items = lib.templates ?? [];
  prompts.selected = lib.selected || '';
  prompts.selectedPolishSingle = lib.selected_polish_single || '';
  prompts.selectedPolishDual = lib.selected_polish_dual || '';
  prompts.path = lib.path || '';
  prompts.error = '';
}

export async function loadPrompts(force = false) {
  if (!app.connected) return;
  if (promptsLoaded && !force && prompts.items.length) return;
  prompts.loading = true;
  try {
    applyPromptLibrary(await api.getPrompts());
    promptsLoaded = true;
  } catch (err) {
    prompts.error = (err as Error).message;
  } finally {
    prompts.loading = false;
  }
}

export function selectedPromptTemplate(category: PromptCategory = 'translate'): PromptTemplate | null {
  const id = promptSelectedId(category);
  return (
    prompts.items.find((item) => item.id === id) ??
    promptItemsFor(category)[0] ??
    null
  );
}

export async function selectPromptTemplate(id: string, category: PromptCategory = 'translate') {
  if (!id) return;
  if (id === promptSelectedId(category)) return;
  try {
    applyPromptLibrary(await api.selectPrompt(id, category));
    const name = prompts.items.find((item) => item.id === id)?.name ?? id;
    toast(`已切换到「${name}」`);
  } catch (err) {
    toast((err as Error).message, 'error');
  }
}

export async function savePromptTemplate(
  id: string,
  patch: { name?: string; description?: string; content?: string },
) {
  try {
    applyPromptLibrary(await api.updatePrompt(id, patch));
    promptsLoaded = true;
    toast('提示词模板已保存');
    return true;
  } catch (err) {
    toast((err as Error).message, 'error');
    return false;
  }
}

export async function createPromptTemplate(
  name: string,
  content: string,
  description = '',
  category: PromptCategory = 'translate',
) {
  try {
    const lib = await api.createPrompt({ name, content, description, category });
    applyPromptLibrary(lib);
    promptsLoaded = true;
    toast('已新建提示词模板');
    return lib.created;
  } catch (err) {
    toast((err as Error).message, 'error');
    return '';
  }
}

export async function resetPromptTemplate(id: string) {
  try {
    applyPromptLibrary(await api.resetPrompt(id));
    toast('已恢复内置模板');
    return true;
  } catch (err) {
    toast((err as Error).message, 'error');
    return false;
  }
}

export async function deletePromptTemplate(id: string) {
  try {
    applyPromptLibrary(await api.deletePrompt(id));
    toast('模板已删除');
    return true;
  } catch (err) {
    toast((err as Error).message, 'error');
    return false;
  }
}
