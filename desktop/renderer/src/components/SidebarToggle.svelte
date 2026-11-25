<script lang="ts">
  /**
   * 侧栏折叠 / 展开开关。
   *
   * 2026-11-25 起它常驻标题栏最左（红绿灯安全区右侧）：标题栏横跨整窗，
   * 侧栏从标题栏底边开始，所以不再有「展开态放左栏、收起态换到顶栏」的分支，
   * 也不会再压到原生红绿灯。
   *
   * **图标不是尖角箭头**（2026-11-24 用户裁定）：左右尖角会被读成
   * 「上一页 / 下一页」，而它实际是「显隐侧栏」。两态用同一颗「侧栏」图标，
   * 状态靠 `aria-expanded` + title 表达。
   */
  import Icon from './Icon.svelte';
  import { sidebarPrefs, toggleSidebar } from '../lib/sidebarPrefs.svelte';
</script>

<button
  class="sb-toggle"
  onclick={toggleSidebar}
  aria-expanded={!sidebarPrefs.collapsed}
  title={sidebarPrefs.collapsed ? '展开侧边栏（⌃⌘S）' : '收起侧边栏（⌃⌘S）'}
  aria-label={sidebarPrefs.collapsed ? '展开侧边栏' : '收起侧边栏'}
>
  <Icon name="sidebar-toggle" size={13} />
</button>

<style>
  .sb-toggle {
    appearance: none;
    width: 22px;
    height: 22px;
    padding: 0;
    border: 0;
    border-radius: var(--rad-control);
    background: transparent;
    color: var(--text-3);
    display: grid;
    place-items: center;
    -webkit-app-region: no-drag;
    transition:
      background var(--dur-fast) var(--ease),
      color var(--dur-fast) var(--ease);
  }
  .sb-toggle:hover {
    background: var(--fill);
    color: var(--text);
  }
  .sb-toggle:focus-visible {
    outline: 2px solid var(--accent-ring);
    outline-offset: -2px;
  }
</style>
