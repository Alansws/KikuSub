<script lang="ts">
  /**
   * 键盘快捷键面板（⌘K）。
   *
   * 这里只负责「列出动作 + 录制新组合 + 持久化」；真正的执行在 App.svelte，
   * 这样同一份映射可以被核对台统计、AI 优化台与视图切换共用。
   */
  import Icon from './Icon.svelte';
  import {
    SHORTCUT_DEFS,
    comboFromEvent,
    comboOf,
    conflictingShortcut,
    formatCombo,
    resetShortcuts,
    setShortcut,
    shortcuts,
  } from '../lib/shortcuts.svelte';

  const groups = ['全局', '核对台', 'AI 优化台', '视图'];

  function groupDefs(group: string) {
    return SHORTCUT_DEFS.filter((def) => def.group === group);
  }

  function capture(id: string) {
    shortcuts.capturing = id;
    shortcuts.conflict = '';
  }

  function close() {
    shortcuts.capturing = '';
    shortcuts.conflict = '';
    shortcuts.open = false;
  }

  function onKey(e: KeyboardEvent) {
    if (!shortcuts.capturing) return;
    e.preventDefault();
    e.stopPropagation();

    if (e.key === 'Escape') {
      shortcuts.capturing = '';
      shortcuts.conflict = '';
      return;
    }
    const combo = comboFromEvent(e);
    if (!combo) return;

    const conflict = conflictingShortcut(shortcuts.capturing, combo);
    if (conflict) {
      shortcuts.conflict = `与「${conflict.label}」重复，换一个组合`;
      return;
    }
    setShortcut(shortcuts.capturing, combo);
    shortcuts.capturing = '';
  }

  $effect(() => {
    if (!shortcuts.capturing) return;
    const handler = (e: KeyboardEvent) => onKey(e);
    window.addEventListener('keydown', handler, true);
    return () => window.removeEventListener('keydown', handler, true);
  });
</script>

{#if shortcuts.open}
  <button class="sc-backdrop" aria-label="关闭快捷键面板" onclick={close}></button>
  <div class="sc-dialog" role="dialog" aria-modal="true" aria-label="键盘快捷键">
    <header class="sc-head">
      <span class="sc-mark"><Icon name="listcheck" size={14} /></span>
      <div class="sc-title">
        <b>键盘快捷键</b>
        <span>点击右侧按键，然后按下新的组合；输入框内不会触发播放 / 删除等编辑动作</span>
      </div>
      <button class="sc-close" onclick={close} title="关闭（Esc）" aria-label="关闭">
        <Icon name="close" size={12} />
      </button>
    </header>

    <div class="sc-body">
      {#each groups as group (group)}
        <div class="sc-group">
          <div class="sc-group-head">{group}</div>
          {#each groupDefs(group) as def (def.id)}
            <div class="sc-row" class:capturing={shortcuts.capturing === def.id}>
              <span class="sc-label">
                {def.label}
                {#if def.note}<span class="sc-note">{def.note}</span>{/if}
              </span>
              <button
                class="sc-key"
                class:listening={shortcuts.capturing === def.id}
                onclick={() => capture(def.id)}
                title="点击后按下新的快捷键"
              >
                {shortcuts.capturing === def.id ? '按下新快捷键…' : formatCombo(comboOf(def.id))}
              </button>
            </div>
          {/each}
        </div>
      {/each}
      {#if shortcuts.conflict}
        <div class="sc-conflict">
          <Icon name="warn" size={11} />{shortcuts.conflict}
        </div>
      {/if}
    </div>

    <footer class="sc-foot">
      <span class="sc-hint">按 Esc 取消当前录制</span>
      <div class="sc-spacer"></div>
      <button class="btn mini" onclick={resetShortcuts}>恢复默认</button>
      <button class="btn mini primary" onclick={close}>完成</button>
    </footer>
  </div>
{/if}

<style>
  .sc-backdrop {
    position: fixed;
    inset: 0;
    z-index: 330;
    border: 0;
    padding: 0;
    background: rgba(13, 20, 36, 0.26);
    backdrop-filter: blur(2px);
    cursor: default;
    animation: scFade 120ms var(--ease) both;
  }
  @keyframes scFade {
    from {
      opacity: 0;
    }
  }

  .sc-dialog {
    position: fixed;
    z-index: 331;
    left: 50%;
    top: 50%;
    transform: translate(-50%, -50%);
    width: min(560px, 88vw);
    max-height: min(76vh, 680px);
    display: flex;
    flex-direction: column;
    background: var(--raise);
    border: 1px solid var(--line);
    border-radius: 14px;
    box-shadow: var(--shadow-pop);
    overflow: hidden;
  }

  .sc-head {
    display: flex;
    align-items: flex-start;
    gap: 10px;
    padding: 14px 14px 12px 16px;
    border-bottom: 1px solid var(--separator);
  }
  .sc-mark {
    width: 28px;
    height: 28px;
    flex: 0 0 28px;
    border-radius: 8px;
    background: var(--accent-soft);
    color: var(--accent);
    display: grid;
    place-items: center;
    margin-top: 1px;
  }
  .sc-title {
    flex: 1;
    min-width: 0;
    display: flex;
    flex-direction: column;
    gap: 2px;
  }
  .sc-title b {
    font-size: 13.5px;
    line-height: 19px;
    font-weight: 600;
  }
  .sc-title span {
    font-size: 11.5px;
    line-height: 16px;
    color: var(--text-3);
  }
  .sc-close {
    appearance: none;
    border: 0;
    background: transparent;
    width: 24px;
    height: 24px;
    border-radius: 6px;
    display: grid;
    place-items: center;
    color: var(--text-3);
    padding: 0;
  }
  .sc-close:hover {
    background: var(--fill);
    color: var(--text);
  }

  .sc-body {
    overflow-y: auto;
    padding: 10px 14px 12px 16px;
  }
  .sc-group + .sc-group {
    margin-top: 12px;
    padding-top: 10px;
    border-top: 1px solid var(--separator-soft);
  }
  .sc-group-head {
    font-size: 11.5px;
    color: var(--text-3);
    padding: 0 2px 5px;
  }
  .sc-row {
    display: flex;
    align-items: center;
    gap: 12px;
    min-height: 34px;
    padding: 0 2px;
    border-radius: 6px;
  }
  .sc-row.capturing {
    background: var(--accent-soft);
  }
  .sc-label {
    flex: 1;
    min-width: 0;
    font-size: 12.5px;
    line-height: 17px;
    color: var(--text);
    display: flex;
    flex-direction: column;
    gap: 1px;
  }
  .sc-note {
    font-size: 11px;
    color: var(--text-3);
  }
  .sc-key {
    appearance: none;
    border: 1px solid var(--line);
    background: var(--bg-content);
    color: var(--text);
    min-width: 82px;
    height: 26px;
    padding: 0 9px;
    border-radius: 6px;
    font: inherit;
    font-size: 12px;
    font-variant-numeric: tabular-nums;
    cursor: pointer;
    transition: border-color var(--dur-fast) var(--ease), background var(--dur-fast) var(--ease);
  }
  .sc-key:hover {
    border-color: var(--accent);
  }
  .sc-key.listening {
    border-color: var(--accent);
    color: var(--accent);
    background: var(--accent-soft);
    animation: scPulse 900ms var(--ease) infinite alternate;
  }
  @keyframes scPulse {
    from {
      opacity: 0.72;
    }
    to {
      opacity: 1;
    }
  }

  .sc-conflict {
    display: flex;
    align-items: center;
    gap: 5px;
    margin-top: 10px;
    padding: 6px 9px;
    border-radius: 6px;
    background: var(--warn-soft);
    color: var(--warn);
    font-size: 11.5px;
    line-height: 16px;
  }

  .sc-foot {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 10px 14px 12px 16px;
    border-top: 1px solid var(--separator);
    background: var(--bg-inspector);
  }
  .sc-hint {
    font-size: 11.5px;
    color: var(--text-3);
  }
  .sc-spacer {
    flex: 1;
  }
</style>
