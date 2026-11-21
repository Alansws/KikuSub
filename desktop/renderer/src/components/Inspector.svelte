<script lang="ts">
  /**
   * 右侧检查器（348px）：页签 + 「当前条目 / 质检待核 / 章节」三页 + 常驻保存栏。
   *
   * 2026-11-21（Step 3）拆成子组件后，这里只做三件事：页签、装页签内容、装保存栏
   * （挂载点仍在 `App.svelte`：只有核对台显示它）。原来 2200 行的单文件让每次动
   * 排版都得先读完整个检查器。
   *
   * - 「当前条目」→ `inspector/CuePane.svelte`：编辑区 + 操作行 + 朗读控件 + 纠偏助手
   * - 「质检待核」→ `QaPanel mode="docked"`（不遮挡画面）
   * - 「章节」   → `ChaptersPanel.svelte`
   * - 底部保存栏 → `inspector/SaveDock.svelte`（在滚动区之外，不会被内容顶掉）
   */
  import Icon from './Icon.svelte';
  import QaPanel from './QaPanel.svelte';
  import ChaptersPanel from './ChaptersPanel.svelte';
  import CuePane from './inspector/CuePane.svelte';
  import InspectorMeta from './inspector/InspectorMeta.svelte';
  import SaveDock from './inspector/SaveDock.svelte';
  import {
    app,
    loadTtsVoices,
    loadTranslations,
    play,
    qa,
    refreshDraftInfo,
    setInspectorTab,
  } from '../lib/store.svelte';
  import { chapterCount } from '../lib/chapters.svelte';

  const qaPending = $derived(Number(qa.payload?.counts?.pending ?? 0));

  /** 进入核对屏 / 换片时刷新工作草稿状态（是否存在、多少条、最后写入时间）。 */
  $effect(() => {
    void app.media?.id;
    if (app.connected && app.media) {
      void refreshDraftInfo();
      void loadTranslations();
      void loadTtsVoices();
    }
  });
</script>

<aside class="inspector" class:hidden={!app.inspectorOpen}>
  <div class="insp-tabs" role="tablist" aria-label="右侧面板">
    <button
      class="insp-tab"
      class:on={app.inspectorTab === 'cue'}
      role="tab"
      aria-selected={app.inspectorTab === 'cue'}
      onclick={() => setInspectorTab('cue')}
    >当前条目</button>
    <button
      class="insp-tab"
      class:on={app.inspectorTab === 'qa'}
      role="tab"
      aria-selected={app.inspectorTab === 'qa'}
      onclick={() => setInspectorTab('qa')}
      title="质检待核队列"
    >
      质检待核
      {#if qaPending}<b>{qaPending}</b>{/if}
    </button>
    <button
      class="insp-tab"
      class:on={app.inspectorTab === 'chapters'}
      role="tab"
      aria-selected={app.inspectorTab === 'chapters'}
      onclick={() => setInspectorTab('chapters')}
      title="章节与时刻点标记（会写入导出容器）"
    >
      章节
      {#if chapterCount()}<b>{chapterCount()}</b>{/if}
    </button>
    <div class="tabs-spacer"></div>
    {#if app.inspectorTab === 'cue'}
      <b class="tabs-index">{app.cues.length ? `#${play.selected + 1}` : '—'}</b>
    {/if}
    <button
      class="ins-close"
      onclick={() => (app.inspectorOpen = false)}
      title="收起检查器（Esc）"
      aria-label="收起检查器"
    >
      <Icon name="close" size={11} />
    </button>
  </div>
  {#if app.inspectorTab === 'chapters'}
    <ChaptersPanel />
  {:else if app.inspectorTab === 'cue'}
    <div class="ins-scroll">
      <CuePane />
      <InspectorMeta />
    </div>
    <SaveDock />
  {:else}
    <QaPanel mode="docked" />
  {/if}
</aside>

<style>
  .inspector {
    width: 348px;
    flex: 0 0 348px;
    background: var(--paper);
    border-left: 1px solid var(--line-2);
    overflow: hidden;
    display: flex;
    flex-direction: column;
    transition: width var(--dur-panel) var(--ease), flex-basis var(--dur-panel) var(--ease),
      opacity 140ms var(--ease);
  }
  .ins-scroll {
    flex: 1;
    min-height: 0;
    overflow-y: auto;
    padding: var(--sp-3) var(--sp-5) var(--sp-4);
  }
  .insp-tabs {
    flex: 0 0 auto;
    display: flex;
    align-items: center;
    gap: 2px;
    min-height: 40px;
    padding: 0 var(--sp-3);
    border-bottom: 1px solid var(--line-2);
    background: var(--paper);
  }
  .insp-tab {
    appearance: none;
    border: 0;
    background: transparent;
    color: var(--ink-3);
    font: inherit;
    font-size: 12.5px;
    line-height: 16px;
    height: 28px;
    padding: 0 9px;
    border-radius: 6px;
    display: inline-flex;
    align-items: center;
    gap: 5px;
    white-space: nowrap;
  }
  .insp-tab:hover {
    background: var(--fill);
    color: var(--ink-2);
  }
  .insp-tab.on {
    background: var(--accent-soft);
    color: var(--accent);
    font-weight: 600;
  }
  .insp-tab b {
    min-width: 16px;
    height: 15px;
    padding: 0 var(--sp-1);
    border-radius: 999px;
    background: var(--accent);
    color: var(--on-accent);
    display: grid;
    place-items: center;
    font-size: 10.5px;
    font-weight: 600;
    font-variant-numeric: tabular-nums;
  }
  .tabs-spacer {
    flex: 1;
  }
  .tabs-index {
    font-family: var(--font-mono);
    font-weight: 400;
    font-size: 12px;
    color: var(--ink-3);
    margin-right: 2px;
  }
  /* 只有紧凑模式的抽屉才需要显式的关闭入口（桌面由工具栏开关控制） */
  .ins-close {
    display: none;
  }


  .inspector.hidden {
    width: 0;
    flex-basis: 0;
    opacity: 0;
    overflow: hidden;
    border-left-color: transparent;
  }


  /* 紧凑模式（≤900px）：不再占列，改成右侧抽屉。
     收起 = 平移出屏幕（不动 width，避免每次开关都触发布局）；
     遮罩与 Esc 关闭由 App.svelte 负责。 */
  @media (max-width: 900px) {
    .inspector {
      position: absolute;
      top: 0;
      right: 0;
      bottom: 0;
      width: min(348px, 92vw);
      flex: 0 0 auto;
      z-index: 20;
      border-left: 1px solid var(--line);
      box-shadow: -18px 0 46px -26px rgba(27, 39, 64, 0.5);
      transform: translateX(103%);
      transition: transform 180ms var(--ease);
      opacity: 1;
      overflow: hidden;
    }
    .inspector:not(.hidden) {
      transform: none;
    }
    .inspector.hidden {
      width: min(348px, 92vw);
      flex-basis: auto;
      opacity: 1;
      border-left-color: transparent;
      box-shadow: none;
      overflow: hidden;
      pointer-events: none;
    }
    .ins-close {
      display: grid;
      place-items: center;
      width: 22px;
      height: 22px;
      padding: 0;
      margin: -4px -4px 0 0;
      border: 0;
      border-radius: 4px;
      background: transparent;
      color: var(--ink-3);
    }
    .ins-close:hover {
      background: var(--fill);
      color: var(--ink);
    }
  }
</style>
