/**
 * 成片导出面板的本地持久化（样式 / 预览文案）。
 *
 * 从 `store.svelte.ts` 拆出来：那个文件有行数预算（只许变短），而「读写
 * localStorage 里的导出样式」是纯函数、与 runes 无关，拆走后 store 只保留接线。
 * 键名与旧版本完全一致，老用户的已保存样式不会丢。
 */

import type { SubtitleStylePayload } from './api';

export const DEFAULT_EXPORT_STYLE: SubtitleStylePayload = {
  preset: 'fansub',
  font: 'pingfang',
  weight: 'bold',
  size: 1,
  outline: 1,
  shadow: true,
  position: 'bottom',
  margin: 4.5,
  fill: '#FFFFFF',
  outline_color: '#000000',
};

export const EXPORT_STYLE_KEY = 'kikusub.exportStyle';
export const EXPORT_PREVIEW_TEXT_KEY = 'kikusub.exportPreviewText';

/** 读本地保存的烧录样式；坏数据一律回默认（并标记成未保存）。 */
export function readSavedExportStyle(): { style: SubtitleStylePayload; saved: boolean } {
  if (typeof localStorage === 'undefined') {
    return { style: { ...DEFAULT_EXPORT_STYLE }, saved: false };
  }
  try {
    const raw = JSON.parse(localStorage.getItem(EXPORT_STYLE_KEY) || 'null');
    if (raw && typeof raw === 'object') {
      return { style: { ...DEFAULT_EXPORT_STYLE, ...raw }, saved: true };
    }
  } catch {
    /* 坏数据忽略，回默认 */
  }
  return { style: { ...DEFAULT_EXPORT_STYLE }, saved: false };
}

export function readSavedPreviewText(): string {
  if (typeof localStorage === 'undefined') return '';
  return localStorage.getItem(EXPORT_PREVIEW_TEXT_KEY) || '';
}

export function saveExportStyleLocal(style: SubtitleStylePayload, previewText: string): void {
  if (typeof localStorage === 'undefined') return;
  try {
    localStorage.setItem(EXPORT_STYLE_KEY, JSON.stringify(style));
    localStorage.setItem(EXPORT_PREVIEW_TEXT_KEY, previewText.slice(0, 120));
  } catch {
    /* 存储不可用时忽略：样式本来也只是一次性的界面偏好 */
  }
}
