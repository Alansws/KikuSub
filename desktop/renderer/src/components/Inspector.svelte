<script lang="ts">
  /**
   * 右侧检查器的页签外壳：「当前条目 / 质检待核 / 章节」。
   *
   * 2026-11-21（Step 3）拆成子组件后，这里只做两件事：页签、装页签内容
   * （挂载点仍在 `App.svelte`：只有核对台显示它）。原来 2200 行的单文件让每次动
   * 排版都得先读完整个检查器。
   *
   * - 「当前条目」→ `inspector/CuePane.svelte`：编辑区 + 操作行 + 朗读控件 + 纠偏助手
   * - 「质检待核」→ `QaPanel mode="docked"`（不遮挡画面）
   * - 「章节」   → `ChaptersPanel.svelte`
   * - 保存栏已移出检查器（2026-11-24 Phase 1）：暂存走底栏 `DraftDock`，
   *   导出走顶栏「导出」与导出视图。检查器只留「与当前条目/队列/章节有关」的内容。
   *
   * 2026-11-25（Step 4.2）：页签从「蓝底胶囊」换成台本的**底下划线**语法——
   * 选中 = 深墨 + 2px 蓝铅笔底线，计数退成等宽数字。理由有两条：一是同一屏里
   * `.seg`（原文/译文/双语、产出的分段）已经占用了「白色凸起胶囊」，页签再用
   * 第三种选中语法会把「这一屏哪个控件是分段」搞混；二是台本页签本来就是
   * 「翻到哪一叠纸」，底线比涂色更像纸上的标记。
   */
  import Icon from './Icon.svelte';
  import QaPanel from './QaPanel.svelte';
  import ChaptersPanel from './ChaptersPanel.svelte';
  import CuePane from './inspector/CuePane.svelte';
  import InspectorMeta from './inspector/InspectorMeta.svelte';
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
  {:else}
    <QaPanel mode="docked" />
  {/if}
</aside>

<style>
  .inspector {
    width: var(--inspector-w);
    flex: 0 0 var(--inspector-w);
    background: var(--paper);
    border-left: 1px solid var(--line);
    overflow: hidden;
    display: flex;
    flex-direction: column;
    transition: width var(--dur-panel) var(--ease), flex-basis var(--dur-panel) var(--ease),
      opacity 140ms var(--ease);
  }
  /* 左右各 16：台词框拿到 316px，比 20 多 8px；三版对照的长句少折一行 */
  .ins-scroll {
    flex: 1;
    min-height: 0;
    overflow-y: auto;
    padding: var(--sp-3) var(--sp-4) var(--sp-4);
  }
  .insp-tabs {
    flex: 0 0 42px;
    display: flex;
    align-items: stretch;
    gap: var(--sp-1);
    height: 42px;
    padding: 0 var(--sp-3);
    border-bottom: 1px solid var(--line);
    background: var(--paper);
  }
  /* 页签 = 台本的分隔页：字重 + 一段蓝铅笔底线，不涂底 */
  .insp-tab {
    appearance: none;
    position: relative;
    border: 0;
    background: transparent;
    color: var(--ink-3);
    font: inherit;
    font-size: 12.5px;
    line-height: 16px;
    padding: 0 2px;
    display: inline-flex;
    align-items: center;
    gap: 5px;
    white-space: nowrap;
    transition: color var(--dur-fast) var(--ease);
  }
  .insp-tab + .insp-tab {
    margin-left: 10px;
  }
  .insp-tab:hover {
    color: var(--ink-2);
  }
  .insp-tab.on {
    color: var(--ink);
    font-weight: 600;
    box-shadow: inset 0 -2px 0 var(--accent);
  }
  /* 计数是读数，不是徽标：等宽数字 + 第二级文字色，不抢页签名 */
  .insp-tab b {
    font-family: var(--font-mono);
    font-weight: 500;
    font-size: 11px;
    color: var(--ink-3);
    font-variant-numeric: tabular-nums;
  }
  .insp-tab.on b {
    color: var(--accent-text);
  }
  .tabs-spacer {
    flex: 1;
  }
  .tabs-index {
    font-family: var(--font-mono);
    font-weight: 400;
    font-size: 11px;
    color: var(--ink-3);
    font-variant-numeric: tabular-nums;
    align-self: center;
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
      width: min(var(--inspector-w), 92vw);
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
      width: min(var(--inspector-w), 92vw);
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
      margin: 0 -4px 0 0;
      align-self: center;
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
