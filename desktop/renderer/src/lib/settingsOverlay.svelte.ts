/**
 * 设置浮层的开合状态（2026-11-24 方案 A）。
 *
 * 设置不再是 `View` 里的一页：它是**压在当前页面之上**的居中浮层，关掉就回到
 * 原来那一屏（核对台上下文不丢）。所以它和侧栏折叠（`sidebarPrefs`）同层——
 * 纯界面状态，不进工作区历史、不参与任何转写或导出。
 *
 * 为什么不放在 `store.svelte.ts`：那个文件有行数预算（红线 11，只许变短），
 * 而这些 action 一行都不需要跟 store 放在一起。`setView('settings')` 的旧入口
 * 在 store 里转成 `openSettings()`，调用点一个都不用改。
 */

export const settingsOverlay = $state({ open: false });

export function openSettings(): void {
  settingsOverlay.open = true;
}

export function closeSettings(): void {
  settingsOverlay.open = false;
}

export function toggleSettings(): void {
  settingsOverlay.open = !settingsOverlay.open;
}
