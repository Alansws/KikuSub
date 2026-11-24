<script lang="ts">
  /**
   * 侧栏折叠 / 展开开关。
   *
   * 为什么要单独一个组件并换位置：展开态里它可以安静地待在左栏顶部的红绿灯
   * 留白区右侧（`position: absolute`）；但收起态只有 52px，而 macOS 由系统绘制的
   * 红绿灯就在 x≈19–71 —— 开关放在那里会**压在红绿灯上**，物理上点不到。
   * 所以收起后开关改挂到顶栏最左侧（见 `Toolbar.svelte`），职责仍是同一个
   * `toggleSidebar()`，状态只有一个。
   */
  import Icon from './Icon.svelte';
  import { sidebarPrefs, toggleSidebar } from '../lib/sidebarPrefs.svelte';

  let { floating = false }: { floating?: boolean } = $props();
</script>

<button
  class="sb-toggle"
  class:floating
  onclick={toggleSidebar}
  aria-expanded={!sidebarPrefs.collapsed}
  title={sidebarPrefs.collapsed ? '展开侧边栏（⌃⌘S）' : '收起侧边栏（⌃⌘S）'}
  aria-label={sidebarPrefs.collapsed ? '展开侧边栏' : '收起侧边栏'}
>
  <Icon name={sidebarPrefs.collapsed ? 'chevron-right' : 'chevron-left'} size={12} />
</button>

<style>
  .sb-toggle {
    appearance: none;
    width: 22px;
    height: 22px;
    padding: 0;
    border: 0;
    border-radius: 5px;
    background: transparent;
    color: var(--text-3);
    display: grid;
    place-items: center;
    -webkit-app-region: no-drag;
    transition: background var(--dur-fast) var(--ease), color var(--dur-fast) var(--ease);
  }
  /* 展开态：钉在左栏顶部红绿灯留白区的右侧 */
  .sb-toggle.floating {
    position: absolute;
    top: 13px;
    right: 10px;
    z-index: 1;
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
