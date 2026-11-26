<script lang="ts">
  /**
   * 设置页的类别导航（2026-11-24，MacWhisper 风格）。
   *
   * 从「顶部横向分段控件」改成**左侧类别列表**：这是 macOS 设置窗格的通用语言
   * （系统设置、MacWhisper、Xcode 偏好都是这个形状），也让右侧内容能拿到整条
   * 宽度的分组卡片，而不是被顶部一排胶囊压窄。
   *
   * 只做展示与键盘（↑/↓ 绕回、roving tabindex）；选中态由父组件持有并持久化。
   * 侧栏的 ⌘1–⌘8 主导航与这里无关。
   */
  import Icon from '../Icon.svelte';
  import {
    SETTINGS_TABS,
    stepSettingsTab,
    type SettingsTabId,
  } from '../../lib/settings/tabs';

  let {
    tab,
    engineCount = null,
    onchange,
  }: {
    tab: SettingsTabId;
    engineCount?: number | null;
    onchange: (id: SettingsTabId) => void;
  } = $props();

  function focusTab(id: SettingsTabId) {
    const el = document.getElementById(`set-tab-${id}`);
    el?.focus();
  }

  function onKeydown(event: KeyboardEvent) {
    if (event.key !== 'ArrowUp' && event.key !== 'ArrowDown') return;
    event.preventDefault();
    const delta = event.key === 'ArrowDown' ? 1 : -1;
    const next = stepSettingsTab(tab, delta);
    onchange(next);
    queueMicrotask(() => focusTab(next));
  }
</script>

<nav class="set-nav" aria-label="设置分区">
  <div
    class="navlist"
    role="tablist"
    aria-orientation="vertical"
    tabindex="-1"
    onkeydown={onKeydown}
  >
    {#each SETTINGS_TABS as item (item.id)}
      <button
        id={`set-tab-${item.id}`}
        class="nav-item"
        role="tab"
        type="button"
        aria-selected={tab === item.id}
        aria-controls={`set-pane-${item.id}`}
        tabindex={tab === item.id ? 0 : -1}
        title={item.hint}
        onclick={() => onchange(item.id)}
      >
        <!-- 线图标，与主侧栏同一套语法：不涂彩色底、不靠色相区分类别。
             2026-11-25（Step 4.3）：四种高饱和色块（蓝 / 紫 / 橙 / 青）是旧皮肤的残留，
             Cue Script 里一屏唯一的饱和色是蓝铅笔，类别靠「名字 + 位置」认，不靠色。 -->
        <span class="nav-icon" aria-hidden="true">
          <Icon name={item.icon} size={14} />
        </span>
        <span class="nav-label">{item.label}</span>
        {#if item.id === 'engines' && engineCount}
          <span class="nav-count">{engineCount}</span>
        {/if}
      </button>
    {/each}
  </div>
  <span class="nav-hint">↑ ↓ 切换</span>
</nav>

<style>
  .set-nav {
    display: flex;
    flex-direction: column;
    gap: var(--sp-2);
    min-width: 0;
  }
  .navlist {
    display: flex;
    flex-direction: column;
    gap: 1px;
  }
  /* macOS 侧栏条目：30px 高、圆角 6、选中是柔和的填充而不是描边 */
  .nav-item {
    appearance: none;
    border: 0;
    background: transparent;
    display: flex;
    align-items: center;
    gap: 9px;
    height: 30px;
    padding: 0 var(--sp-2);
    border-radius: 6px;
    font: inherit;
    font-size: var(--fs-ui);
    color: var(--text);
    text-align: left;
    white-space: nowrap;
    transition:
      background var(--dur-fast) var(--ease),
      color var(--dur-fast) var(--ease);
  }
  .nav-item:hover {
    background: var(--fill);
  }
  .nav-item[aria-selected='true'] {
    background: var(--fill-strong);
    font-weight: 500;
  }
  .nav-item:focus-visible {
    outline: 2px solid var(--accent-ring);
    outline-offset: -1px;
  }
  .nav-icon {
    display: grid;
    place-items: center;
    flex: 0 0 auto;
    width: 16px;
    height: 16px;
    color: var(--ink-3);
  }
  /* 选中时图标跟标签一起转蓝铅笔（与主侧栏的 active 同一条规则）；未选中是第三级墨。 */
  .nav-item[aria-selected='true'] .nav-icon {
    color: var(--accent);
  }
  .nav-label {
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .nav-count {
    margin-left: auto;
    min-width: 16px;
    height: 16px;
    padding: 0 var(--sp-1);
    border-radius: 8px;
    background: var(--fill-strong);
    color: var(--text-2);
    font-size: 11px;
    line-height: 16px;
    text-align: center;
    font-variant-numeric: tabular-nums;
  }
  .nav-item[aria-selected='true'] .nav-count {
    background: var(--accent-soft);
    color: var(--accent);
  }
  .nav-hint {
    padding-left: var(--sp-2);
    font-size: var(--fs-label);
    color: var(--text-3);
  }
  @media (max-width: 1120px) {
    .nav-hint {
      display: none;
    }
  }
</style>
