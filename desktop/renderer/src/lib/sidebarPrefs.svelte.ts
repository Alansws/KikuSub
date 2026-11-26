/**
 * 侧栏折叠偏好：236px 完整宽度 ↔ 52px 图标条，`⌃⌘S` 或按钮切换并持久化。
 *
 * 纯界面偏好，和磁吸吸附（`snapPrefs`）、跟随播放头同层；不属于工作区历史，
 * 也不参与任何一次转写 / 导出。**自持一份状态**而不是塞进 `store.svelte.ts`：
 * 那个文件有行数预算（红线 11，只许变短），而这条偏好没有一行是需要跟 store
 * 放在一起的。
 *
 * 收起后的开关不能留在左栏：那 52px 里 macOS 系统红绿灯占 x≈19–71，按钮会被
 * 压在红绿灯上点不到。所以由 `SidebarToggle.svelte` 按状态决定挂在左栏还是顶栏。
 */

const STORAGE_KEY = 'kikusub.sidebarCollapsed';

function initial(): boolean {
  try {
    return localStorage.getItem(STORAGE_KEY) === '1';
  } catch {
    return false;
  }
}

export const sidebarPrefs = $state({ collapsed: initial() });

export function toggleSidebar(): void {
  sidebarPrefs.collapsed = !sidebarPrefs.collapsed;
  try {
    localStorage.setItem(STORAGE_KEY, sidebarPrefs.collapsed ? '1' : '0');
  } catch {
    /* 隐私模式 / 配额满了：记不住偏好不影响本次使用 */
  }
}
