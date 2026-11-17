/**
 * 磁吸吸附偏好：默认为开，`N` 切换并持久化。
 *
 * 纯界面偏好，与 TTS 音色 / 跟随播放头同层；不属于工作区历史。
 */

import { toast } from './store.svelte';

const STORAGE_KEY = 'kikusub.snap';

function initial(): boolean {
  try {
    return localStorage.getItem(STORAGE_KEY) !== '0';
  } catch {
    return true;
  }
}

export const snapPrefs = $state({ enabled: initial() });

export function toggleSnap(): void {
  snapPrefs.enabled = !snapPrefs.enabled;
  try {
    localStorage.setItem(STORAGE_KEY, snapPrefs.enabled ? '1' : '0');
  } catch {
    /* 隐私模式 / 配额满了：偏好记不住不影响本次使用 */
  }
  toast(`磁吸吸附：${snapPrefs.enabled ? '开' : '关'}`);
}
