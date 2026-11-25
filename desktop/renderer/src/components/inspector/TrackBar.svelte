<script lang="ts">
  /**
   * 译文轨状态条（单行）：左边一句读数，右边一个入口。
   *
   * 2026-11-25（Step 4.2.1，用户验收后的唯一整改）：显示模式行与「#1 单句编辑」之间
   * 原来横着**两行**——一行 `12 条 全部同步`（左对齐），一行 `导入译文 / 撤销译文 /
   * 删除译文`（右对齐、红色字常驻）。同一块地方两个对齐方向、三个裸链接和一条朱红，
   * 与下方的稿纸卡也没有层次，读起来像「表单控件溢出来了」。
   *
   * 现在压成一条 24px 的状态条（`distill`）：
   * - 有译文轨：左 `12 条 · 全部同步`（待译 / 原文已改各自带色，不折行，超长省略并带
   *   `title`）；右只在真有缺口时出现「补译」，其余低频维护动作收进 `⋯`。
   * - 没有译文轨：左 `暂无译文`，右只给一个安静的「导入译文…」次级按钮。
   * - 危险动作（删整轨）只活在菜单里，且与其它项之间有一条发丝线——朱红不再常驻在
   *   单句编辑器的正上方。
   *
   * 菜单形状对齐核对台的右键菜单（4px 内边距 / 28px 行 / 悬停整行强调色 + 白字），
   * 键盘：↑↓ 走项、Esc 关闭并把焦点还给 `⋯`、点击遮罩关闭；Esc 在这一层
   * `stopPropagation`，不会顺手把核对台的选区清掉。
   */
  import { tick } from 'svelte';
  import Icon from '../Icon.svelte';
  import {
    app,
    importTranslationFromExport,
    removeTranslationTrack,
    translationPendingCounts,
    undoTranslation,
  } from '../../lib/store.svelte';
  import { gapCountsNow, gapListNow, openGapFill } from '../../lib/gapFill.svelte';

  const track = $derived(app.translations[app.trackLang]);
  const hasTrack = $derived(Boolean(track));
  const count = $derived(Number(track?.count ?? 0));
  const pending = $derived(translationPendingCounts());
  /** 补译批次只处理「当前处理范围」；与翻译页卡片同一份口径。 */
  const gapCount = $derived(gapListNow().length);
  const gapInfo = $derived(gapCountsNow());

  const statusText = $derived(
    !hasTrack
      ? '暂无译文'
      : [
          `${count} 条`,
          pending.stale > 0 ? `${pending.stale} 条原文已改` : '',
          pending.gap > 0 ? `${pending.gap} 条待译` : '',
          !pending.stale && !pending.gap ? '全部同步' : '',
        ]
          .filter(Boolean)
          .join(' · '),
  );
  const statusTitle = $derived(
    !hasTrack
      ? '还没有译文轨：导入同语种 SRT / VTT，或在「双语翻译」页生成一版'
      : '整条译文轨的状态（读数来自当前语种；「原文已改」= 有译文但原文动过）',
  );

  let open = $state(false);
  let triggerEl = $state<HTMLButtonElement | null>(null);
  let menuEl = $state<HTMLDivElement | null>(null);

  async function show() {
    open = true;
    await tick();
    menuEl?.querySelector('button')?.focus();
  }

  function hide(refocus = false) {
    if (!open) return;
    open = false;
    if (refocus) triggerEl?.focus();
  }

  function run(action: () => void) {
    hide(false);
    action();
  }

  function onMenuKey(e: KeyboardEvent) {
    if (!open) return;
    if (e.key === 'Escape') {
      e.preventDefault();
      // 核对台的 Esc 是「清选区」；这里先关菜单，不把事件交给窗口。
      e.stopPropagation();
      hide(true);
      return;
    }
    if (e.key === 'Tab') {
      hide(false);
      return;
    }
    if (e.key !== 'ArrowDown' && e.key !== 'ArrowUp') return;
    e.preventDefault();
    e.stopPropagation();
    const items = [...(menuEl?.querySelectorAll<HTMLButtonElement>('button') ?? [])];
    if (!items.length) return;
    const at = items.indexOf(document.activeElement as HTMLButtonElement);
    const next =
      e.key === 'ArrowDown'
        ? (at + 1) % items.length
        : (at - 1 + items.length) % items.length;
    items[next]?.focus();
  }
</script>

<div class="track-bar">
  <span class="tb-status" title={statusTitle}>
    {#if hasTrack}
      <span class="tb-count">{count} 条</span>
      {#if pending.stale > 0}
        <span class="tb-dot">·</span><span class="warn">{pending.stale} 条原文已改</span>
      {/if}
      {#if pending.gap > 0}
        <span class="tb-dot">·</span><span class="todo">{pending.gap} 条待译</span>
      {/if}
      {#if !pending.stale && !pending.gap}
        <span class="tb-dot">·</span><span class="ok">全部同步</span>
      {/if}
    {:else}
      暂无译文
    {/if}
  </span>

  <div class="tb-actions">
    {#if hasTrack}
      {#if gapCount > 0}
        <button
          class="btn sm"
          onclick={() => void openGapFill(true)}
          title="只把待译条目复制给外部模型；回填只写这些条目，其余译文原样保留（当前处理范围 {gapInfo.total} 条）"
        >补译</button
        >
      {/if}
      <button
        class="tb-more"
        bind:this={triggerEl}
        onclick={() => (open ? hide(false) : void show())}
        title="译文轨操作"
        aria-label="译文轨操作"
        aria-haspopup="menu"
        aria-expanded={open}
      ><Icon name="more" size={15} /></button>
    {:else}
      <button
        class="btn sm"
        onclick={() => importTranslationFromExport()}
        disabled={!app.cues.length}
        title="选择与当前原文逐条对齐的译文 SRT / VTT"
      >导入译文…</button>
    {/if}
  </div>

  {#if open}
    <button class="tb-backdrop" aria-label="关闭译文轨菜单" onclick={() => hide(false)}></button>
    <div class="tb-menu" role="menu" bind:this={menuEl} onkeydown={onMenuKey}>
      <button
        role="menuitem"
        onclick={() => run(() => importTranslationFromExport())}
        disabled={!app.cues.length}
      >导入译文…</button>
      <button role="menuitem" onclick={() => run(() => undoTranslation())}>撤销译文</button>
      <div class="tb-sep" role="separator"></div>
      <button
        class="danger"
        role="menuitem"
        onclick={() => run(() => removeTranslationTrack())}
        title="删除整条译文轨；原文与时间轴不受影响，⌘Z 可撤回"
      >删除译文</button>
    </div>
  {/if}
</div>

<style>
  .track-bar {
    position: relative;
    display: flex;
    align-items: center;
    gap: var(--sp-2);
    margin-top: var(--sp-2);
    min-height: 24px;
  }
  /* 读数：一条行内文本，不折行；过长（待译 + 原文已改同时出现）省略并靠 title 补全。 */
  .tb-status {
    flex: 1 1 auto;
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    font-size: 12px;
    line-height: 16px;
    color: var(--ink-3);
    font-variant-numeric: tabular-nums;
  }
  .tb-count {
    color: var(--ink-2);
  }
  .tb-dot {
    padding: 0 5px;
    color: var(--ink-3);
  }
  /* 三态各有词：颜色只是加强，词本身已经说清（DESIGN「One Colour One Job」）。 */
  .ok {
    color: var(--success);
  }
  .todo {
    color: var(--accent-text);
  }
  .warn {
    color: var(--warn);
  }
  .tb-actions {
    flex: 0 0 auto;
    display: flex;
    align-items: center;
    gap: 6px;
  }
  /* ⋯：三颗实心点（`Icon name="more"`），几何居中、24px 命中区。
     2026-11-25 试过文本字形 `⋯`：字体基线把它顶到行顶，读起来像浮尘。 */
  .tb-more {
    appearance: none;
    border: 0;
    background: transparent;
    color: var(--ink-2);
    width: 24px;
    height: 24px;
    border-radius: var(--rad-control);
    display: grid;
    place-items: center;
    padding: 0;
    cursor: default;
    transition:
      background var(--dur-fast) var(--ease),
      color var(--dur-fast) var(--ease);
  }
  .tb-more:hover,
  .tb-more[aria-expanded='true'] {
    background: var(--fill);
    color: var(--ink);
  }

  .tb-backdrop {
    position: fixed;
    inset: 0;
    z-index: 20;
    border: 0;
    background: transparent;
    cursor: default;
  }
  /* 原生菜单形状：4px 内边距 / 28px 行 / 悬停整行强调色 + 白字 */
  .tb-menu {
    position: absolute;
    top: 26px;
    right: 0;
    z-index: 21;
    min-width: 148px;
    padding: var(--sp-1);
    border: 1px solid var(--line);
    border-radius: 6px;
    background: var(--raise);
    box-shadow: var(--shadow-pop);
    display: flex;
    flex-direction: column;
  }
  .tb-menu button {
    appearance: none;
    border: 0;
    background: transparent;
    color: var(--text);
    font: inherit;
    font-size: 12.5px;
    line-height: 18px;
    text-align: left;
    height: 28px;
    padding: 0 var(--sp-2);
    border-radius: 4px;
    cursor: pointer;
    white-space: nowrap;
  }
  .tb-menu button:hover:not(:disabled),
  .tb-menu button:focus-visible {
    background: var(--accent);
    color: var(--on-accent);
    outline: none;
  }
  .tb-menu button:disabled {
    color: var(--ink-muted);
    opacity: 0.6;
    cursor: default;
  }
  .tb-menu button.danger {
    color: var(--danger);
  }
  .tb-menu button.danger:hover,
  .tb-menu button.danger:focus-visible {
    color: var(--on-accent);
  }
  /* 危险动作与前面隔一条发丝线：菜单里的「隔离 16px + 发丝线」等价物 */
  .tb-sep {
    height: 1px;
    margin: var(--sp-1) 2px;
    background: var(--line);
  }
</style>
