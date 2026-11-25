<script lang="ts">
  /**
   * 音轨 / 字幕表的右键菜单。
   *
   * 从 `ReviewView.svelte` 原样搬出（Step 4.1 纯结构拆分）：打开位置与
   * 「合并目标」仍由 ReviewView 判定（它知道选区与轨道多选），这里只负责
   * 菜单里的动作与浮层定位。菜单挂 body，见 lib/portal.ts。
   */
  import Icon from '../Icon.svelte';
  import {
    app,
    insertCueAt,
    mergeCuesAt,
    play,
    previewRange,
    splitCueAt,
    tts,
  } from '../../lib/store.svelte';
  import { canSplitAt } from '../../lib/cueEdit';
  import { portal } from '../../lib/portal';
  import { tcShort } from '../../lib/time';

  interface ContextMenuState {
    x: number;
    y: number;
    t: number;
    index: number;
    merge: number[];
  }

  interface VoiceDialogState {
    index: number;
    name: string;
    refText: string;
  }

  let {
    menu = $bindable(null),
    selection = $bindable(null),
    laneSelection = $bindable([]),
    voiceDialog = $bindable(null),
  }: {
    menu?: ContextMenuState | null;
    selection?: { start: number; end: number } | null;
    laneSelection?: string[];
    voiceDialog?: VoiceDialogState | null;
  } = $props();

  const canSplit = $derived.by(() => {
    const m = menu;
    if (!m || m.index < 0) return false;
    const cue = app.cues[m.index];
    return Boolean(cue && canSplitAt(cue, m.t));
  });

  function splitHere() {
    const m = menu;
    menu = null;
    if (!m || m.index < 0) return;
    laneSelection = [];
    selection = null;
    void splitCueAt(m.index, m.t);
  }

  function mergeHere(indices: number[]) {
    menu = null;
    laneSelection = [];
    selection = null;
    void mergeCuesAt(indices);
  }

  async function addCueHere() {
    const t = menu?.t ?? play.time;
    menu = null;
    await insertCueAt(t);
  }

  /** 右键「以此句音频新建音色…」：先给角色起名，再让后端精确切片。 */
  function openVoiceDialog(index: number) {
    menu = null;
    const cue = app.cues[index];
    if (!cue) return;
    voiceDialog = {
      index,
      name: `角色 ${tts.custom.length + 1}`,
      refText: cue.text,
    };
  }

  function audition() {
    const index = menu?.index ?? -1;
    const cue = app.cues[index];
    menu = null;
    if (cue) previewRange(cue.start, cue.end);
  }
</script>

{#if menu}
  <button
    class="ctx-backdrop"
    use:portal
    aria-label="关闭菜单"
    onclick={() => (menu = null)}
  ></button>
  <div
    class="ctx-menu"
    use:portal
    style="left:{menu.x}px;top:{menu.y}px"
    role="menu"
    aria-label="音轨菜单"
  >
    <div class="ctx-head">
      <span>{tcShort(menu.t)}</span>
      <span class="ctx-hint">
        {menu.index >= 0 ? `第 ${menu.index + 1} 句` : '0.8 秒'}
      </span>
    </div>
    {#if menu.merge.length >= 2}
      <button class="ctx-item" onclick={() => mergeHere(menu!.merge)} role="menuitem">
        <Icon name="merge" size={12} />
        <span class="ctx-label">合并这 {menu.merge.length} 句字幕</span>
        <span class="ctx-hint">一起合并</span>
      </button>
      <div class="ctx-sep"></div>
    {/if}
    {#if menu.index >= 0}
      {#if canSplit}
        <button class="ctx-item" onclick={splitHere} role="menuitem">
          <Icon name="split" size={12} />
          <span class="ctx-label">切割字幕</span>
          <span class="ctx-hint">分成两句</span>
        </button>
      {/if}
      <button
        class="ctx-item"
        onclick={() => openVoiceDialog(menu!.index)}
        role="menuitem"
      >
        <Icon name="speaker" size={12} />
        <span class="ctx-label">以此句音频新建音色…</span>
      </button>
      <button class="ctx-item" onclick={audition} role="menuitem">
        <Icon name="play" size={12} />
        <span class="ctx-label">试听这句原声</span>
      </button>
      <div class="ctx-sep"></div>
    {/if}
    <button class="ctx-item" onclick={addCueHere} role="menuitem">
      <Icon name="plus" size={12} />
      <span class="ctx-label">添加字幕</span>
      <span class="ctx-hint">在光标处居中插入空字幕</span>
    </button>
  </div>
{/if}

<style>
  .ctx-backdrop {
    position: fixed;
    inset: 0;
    z-index: 70;
    border: 0;
    padding: 0;
    background: transparent;
    cursor: default;
  }
  .ctx-sep {
    height: 1px;
    margin: var(--sp-1) 6px;
    background: var(--line);
  }
  /* 原生上下文菜单的形状：纸白、4px 内边距、6px 圆角、popover 阴影；
     悬停 = 整行强调色 + 白字（macOS 的菜单高亮就是这个），
     右侧说明在同一行里退成半透明的白，不换行、不抖动。 */
  .ctx-menu {
    position: fixed;
    z-index: 71;
    width: 248px;
    padding: var(--sp-1);
    border-radius: 6px;
    background: var(--raise);
    border: 1px solid var(--line);
    box-shadow: var(--shadow-pop);
  }
  .ctx-head {
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    gap: var(--sp-2);
    padding: var(--sp-1) var(--sp-2) 5px;
    margin-bottom: var(--sp-1);
    border-bottom: 1px solid var(--line);
    font-size: var(--fs-mono);
    line-height: 14px;
    color: var(--ink-3);
    font-variant-numeric: tabular-nums;
    font-family: var(--font-mono);
  }
  .ctx-item {
    appearance: none;
    border: 0;
    background: transparent;
    color: var(--text);
    font: inherit;
    width: 100%;
    display: flex;
    align-items: center;
    gap: var(--sp-2);
    height: 28px;
    padding: 0 var(--sp-2);
    border-radius: 4px;
    cursor: pointer;
    text-align: left;
  }
  .ctx-item:hover {
    background: var(--accent);
    color: var(--on-accent);
  }
  .ctx-label {
    flex: 0 0 auto;
    font-size: 12.5px;
    white-space: nowrap;
  }
  .ctx-hint {
    flex: 1;
    min-width: 0;
    font-size: 11px;
    color: var(--ink-3);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    text-align: right;
  }
  .ctx-item:hover .ctx-hint {
    color: var(--on-accent);
    opacity: 0.78;
  }
</style>
