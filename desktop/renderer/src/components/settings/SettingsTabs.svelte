<script lang="ts">
  /**
   * 设置页顶部的分段导航。
   *
   * 只做四页签的展示与键盘（←/→ 绕回、roving tabindex）；选中态由父组件持有并持久化。
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
    if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return;
    event.preventDefault();
    const delta = event.key === 'ArrowRight' ? 1 : -1;
    const next = stepSettingsTab(tab, delta);
    onchange(next);
    // 等 DOM 更新后把焦点交给新的页签，键盘用户不会掉焦点
    queueMicrotask(() => focusTab(next));
  }
</script>

<nav class="set-tabs" aria-label="设置分区">
  <div
    class="tablist"
    role="tablist"
    aria-orientation="horizontal"
    tabindex="-1"
    onkeydown={onKeydown}
  >
    {#each SETTINGS_TABS as item (item.id)}
      <button
        id={`set-tab-${item.id}`}
        class="tab"
        role="tab"
        type="button"
        aria-selected={tab === item.id}
        aria-controls={`set-pane-${item.id}`}
        tabindex={tab === item.id ? 0 : -1}
        title={item.hint}
        onclick={() => onchange(item.id)}
      >
        <span class="tab-icon"><Icon name={item.icon} size={14} /></span>
        <span class="tab-label">{item.label}</span>
        {#if item.id === 'engines' && engineCount}
          <span class="tab-count" aria-label={`${engineCount} 个引擎`}>{engineCount}</span>
        {/if}
      </button>
    {/each}
  </div>
  <span class="tabs-hint">← → 切换</span>
</nav>

<style>
  .set-tabs {
    position: sticky;
    top: 0;
    z-index: 5;
    display: flex;
    align-items: center;
    gap: var(--sp-3);
    margin: 0 0 var(--sp-5);
    padding: var(--sp-2) 0 var(--sp-3);
    background: var(--paper);
    border-bottom: 1px solid var(--separator-soft);
  }
  .tablist {
    display: inline-flex;
    gap: 2px;
    padding: 3px;
    border-radius: var(--rad-tab);
    background: var(--seg-track);
    box-shadow: inset 0 0 0 1px var(--separator-soft);
  }
  .tab {
    appearance: none;
    border: 0;
    background: transparent;
    display: inline-flex;
    align-items: center;
    gap: 7px;
    height: var(--seg-h);
    padding: 0 var(--sp-3);
    border-radius: var(--rad-control);
    font: inherit;
    font-size: var(--fs-ui);
    color: var(--seg-ink);
    white-space: nowrap;
    transition:
      color var(--dur) var(--ease),
      background var(--dur) var(--ease);
  }
  .tab-icon {
    display: grid;
    place-items: center;
    opacity: 0.75;
  }
  .tab:hover {
    color: var(--seg-ink-on);
  }
  .tab[aria-selected='true'] {
    background: var(--seg-thumb);
    color: var(--seg-ink-on);
    font-weight: 500;
    /* 白胶囊压浅灰轨道只有 1.05:1：靠 1px 描边兜底，不只靠阴影 */
    box-shadow:
      var(--seg-thumb-shadow),
      inset 0 0 0 1px var(--seg-thumb-ring);
  }
  .tab[aria-selected='true'] .tab-icon {
    opacity: 1;
    color: var(--accent);
  }
  .tab-count {
    min-width: 16px;
    height: 16px;
    padding: 0 var(--sp-1);
    border-radius: var(--rad-control);
    background: var(--fill-strong);
    color: var(--text-2);
    font-size: 11px;
    line-height: 16px;
    text-align: center;
    font-variant-numeric: tabular-nums;
  }
  .tab[aria-selected='true'] .tab-count {
    background: var(--accent-soft);
    color: var(--accent);
  }
  .tabs-hint {
    margin-left: auto;
    font-size: var(--fs-label);
    color: var(--text-3);
  }
  @media (max-width: 1120px) {
    .tabs-hint {
      display: none;
    }
  }
</style>
