<script lang="ts">
  import Icon from './Icon.svelte';
  import EngineSwitch from './EngineSwitch.svelte';
  import {
    app,
    clearOriginalTrack,
    cueHistory,
    importProxyFromFile,
    importSubtitleFromExport,
    importTranslationFromExport,
    jumpCueHistory,
    redo,
    removeTranslationTrack,
    setView,
    startProxyJob,
    toggleCueHistory,
    toggleTheme,
    undo,
  } from '../lib/store.svelte';
  import { formatBytes, formatDuration } from '../lib/time';

  function clock(seconds: number) {
    return new Date(seconds * 1000).toLocaleTimeString('zh-CN', {
      hour12: false,
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
    });
  }

  let { engine = $bindable('whisper') }: { engine?: string } = $props();

  /** 核对台顶部的「⋯」菜单：把低频但重要的一次性动作收起来，工具栏留给主路径。 */
  let moreOpen = $state(false);

  const proxyBusy = $derived(
    app.jobKind === 'proxy' &&
      (app.job?.status === 'running' || app.job?.status === 'queued'),
  );
  const jobBusy = $derived(
    app.job?.status === 'running' || app.job?.status === 'queued',
  );
  const proxyPct = $derived(app.jobKind === 'proxy' ? (app.job?.percent ?? 0) : 0);
  const proxyLabel = $derived(
    proxyBusy ? `压制中 ${proxyPct}%` : app.media?.proxy_ready ? '代理已就绪' : '压制代理',
  );
  const proxyHint = $derived(
    proxyBusy
      ? `正在后台压制 480p 监看代理（${proxyPct}%）`
      : app.media?.proxy_ready
        ? '480p 监看代理已就绪，无需再压'
        : '为高码率 / 特殊编码视频压制 480p 监看代理，拖动进度条更流畅',
  );
  const hasTranslation = $derived(Boolean(app.translations[app.trackLang]));

  function runProxy() {
    moreOpen = false;
    void startProxyJob();
  }

  function importSubtitle() {
    moreOpen = false;
    void importSubtitleFromExport();
  }

  function importTranslation() {
    moreOpen = false;
    void importTranslationFromExport();
  }

  function importProxy() {
    moreOpen = false;
    void importProxyFromFile();
  }

  function deleteOriginal() {
    moreOpen = false;
    void clearOriginalTrack();
  }

  function deleteTranslation() {
    moreOpen = false;
    void removeTranslationTrack();
  }

  function manageEngines() {
    setView('settings');
  }

  // 统一历史：字幕 / 译文 / 质检 / 导出设置 / AI 草稿共用一个 cursor。
  const undoInfo = $derived({ label: app.canUndo ? app.undoLabel || '上一步' : '' });
  const redoInfo = $derived({ label: app.canRedo ? app.redoLabel || '下一步' : '' });
  const cueSteps = $derived(Math.max(0, cueHistory.cursor));
  const historyRows = $derived(
    cueHistory.items.map((item) => ({ item, index: item.id })).reverse(),
  );

  // 设置页可以停用引擎；工具栏只显示启用的那几个，引擎变多也不会挤爆。
  const engines = $derived((app.config?.engines ?? []).filter((e) => e.enabled));

  const sub = $derived.by(() => {
    const m = app.media;
    if (!m) return '拖入即用';
    switch (app.view) {
      case 'import':
        return `${formatBytes(m.size)} · ${formatDuration(m.duration)} · ${m.video_codec || '—'}`;
      case 'transcribe':
        return app.job?.status === 'running'
          ? `转写中 ${app.job.percent}%`
          : `${app.cues.length} 条 · 待转写`;
      case 'review':
        return `${app.cues.length} 条 · ${formatDuration(m.duration)}`;
      case 'ai':
        return '建议对照 · 逐条采纳后整批应用';
      case 'prompts':
        return '提示词库 · 单击选中 / 双击编辑';
      case 'export':
        return `${app.cues.length} 条字幕 · 字幕 / 成片导出`;
      case 'report':
        return app.report ? `${app.cues.length} 条字幕 · 任务详报` : '任务详报';
      case 'settings':
        return '引擎与模型 · 文件夹路径 · 日志与诊断';
      default:
        return '';
    }
  });
</script>

<header class="toolbar">
  <div class="tb-title" title={app.media?.path ?? ''}>{app.media?.name ?? 'KikuSub'}</div>
  <div class="tb-sub">{sub}</div>
  <div class="tb-sep tb-sep-lead"></div>

  {#if engines.length}
    <EngineSwitch bind:engine {engines} onmanage={manageEngines} />
  {:else}
    <button class="btn ghost" onclick={() => setView('settings')}>
      <Icon name="warn" size={12} />没有启用的引擎
    </button>
  {/if}

  {#if proxyBusy}
    <div
      class="proxy-chip"
      title={proxyHint}
      role="progressbar"
      aria-label="代理压制进度"
      aria-valuemin="0"
      aria-valuemax="100"
      aria-valuenow={proxyPct}
    >
      <Icon name="film" size={11} />
      <span class="pc-label">代理</span>
      <div class="pc-track"><i style="width:{Math.max(2, proxyPct)}%"></i></div>
      <b>{proxyPct}%</b>
    </div>
  {/if}

  <div class="tb-spacer"></div>

  {#if app.view === 'review'}
    <button
      class="btn ghost top-act"
      onclick={() => setView('ai')}
      title="按全片语境修正识别错误：左原文、右 AI 建议，时间码不变"
      aria-label="AI 优化"
    >
      <Icon name="sparkle" size={12} /><span class="act-label">AI 优化</span>
    </button>
    <button
      class="btn ghost top-act"
      onclick={() => setView('export')}
      title="把当前时间轴导出为字幕或带字幕的成片"
      aria-label="导出"
    >
      <Icon name="export" size={12} /><span class="act-label">导出</span>
    </button>

    <div class="more-wrap">
      <button
        class="btn icon ghost more"
        class:on={moreOpen}
        aria-label="更多"
        aria-expanded={moreOpen}
        title="更多：代理 / 原文轨 / 译文轨"
        onclick={() => (moreOpen = !moreOpen)}
        >⋯</button
      >
      {#if moreOpen}
        <button
          class="menu-backdrop"
          aria-label="关闭更多菜单"
          onclick={() => (moreOpen = false)}
        ></button>
        <div class="more-menu" role="menu" aria-label="更多操作">
          <button
            class="menu-item"
            role="menuitem"
            onclick={runProxy}
            disabled={jobBusy || Boolean(app.media?.proxy_ready) || !app.media}
            title={proxyHint}
          >
            <Icon name="film" size={12} />
            <span class="mi-label">{proxyLabel}</span>
            <span class="mi-sub">{app.media?.proxy_ready ? '已就绪' : '480p'}</span>
          </button>
          <button
            class="menu-item"
            role="menuitem"
            onclick={importProxy}
            disabled={jobBusy || Boolean(app.media?.proxy_ready) || !app.media}
            title="选择已经压好的代理文件，直接挂到当前媒体，不再重新压制"
          >
            <Icon name="tray" size={12} />
            <span class="mi-label">导入代理…</span>
            <span class="mi-sub">已有文件</span>
          </button>

          <div class="mi-sep" role="separator"></div>

          <button
            class="menu-item"
            role="menuitem"
            onclick={importSubtitle}
            disabled={jobBusy}
            title="从导出文件夹选择原文字幕，导入核对台作为基线"
          >
            <Icon name="doc" size={12} />
            <span class="mi-label">导入原文字幕…</span>
            <span class="mi-sub">SRT / VTT</span>
          </button>
          <button
            class="menu-item"
            role="menuitem"
            onclick={importTranslation}
            disabled={jobBusy || !app.cues.length}
            title="选择与当前原文逐条对齐的译文 SRT / VTT，原文与时间轴不动"
          >
            <Icon name="quote" size={12} />
            <span class="mi-label">导入译文字幕…</span>
            <span class="mi-sub">逐条对齐</span>
          </button>

          <div class="mi-sep" role="separator"></div>

          <button
            class="menu-item"
            role="menuitem"
            onclick={deleteOriginal}
            disabled={jobBusy || !app.cues.length}
            title="删除全部原文字幕与时间轴；所有译文轨会一起清空，⌘Z 可撤回"
          >
            <Icon name="trash" size={12} />
            <span class="mi-label">删除原文字幕</span>
            <span class="mi-sub">{app.cues.length} 条</span>
          </button>
          <button
            class="menu-item"
            role="menuitem"
            onclick={deleteTranslation}
            disabled={jobBusy || !hasTranslation}
            title="只删除当前语种的译文轨，原文与时间轴保留"
          >
            <Icon name="trash" size={12} />
            <span class="mi-label">删除译文字幕</span>
            <span class="mi-sub">{hasTranslation ? app.trackLang : '当前语种无译文'}</span>
          </button>
        </div>
      {/if}
    </div>

    <div class="tb-sep"></div>
  {/if}

  <button
    class="btn icon ghost"
    onclick={undo}
    disabled={!undoInfo.label}
    title={undoInfo.label ? `撤回：${undoInfo.label}（⌘Z）` : '没有可撤回的操作'}
  >
    <Icon name="undo" size={14} />
  </button>
  <button
    class="btn icon ghost"
    onclick={redo}
    disabled={!redoInfo.label}
    title={redoInfo.label ? `重做：${redoInfo.label}（⇧⌘Z）` : '没有可重做的操作'}
  >
    <Icon name="redo" size={14} />
  </button>

  <div class="history-wrap">
    <button
      class="btn icon ghost"
      class:on={cueHistory.open}
      aria-pressed={cueHistory.open}
      onclick={() => toggleCueHistory()}
      title="撤销 / 重做历史（所有操作共用一条时间线，可点任意一步跳回）"
    >
      <Icon name="history" size={14} />
    </button>

    {#if cueHistory.open}
      <button
        class="hist-backdrop"
        aria-label="关闭历史列表"
        onclick={() => toggleCueHistory(false)}
      ></button>
      <div class="hist-panel" role="dialog" aria-label="撤销与重做历史">
        <div class="hist-head">
          <span>撤销 / 重做历史</span>
          <span class="hist-sub">全部操作 {cueSteps}/50</span>
        </div>
        <div class="hist-list">
          {#if !cueHistory.items.length}
            <div class="hist-empty">
              {cueHistory.loading ? '正在读取历史…' : '还没有可回溯的操作'}
            </div>
          {/if}
          {#each historyRows as row (row.index)}
            <button
              class="hist-item"
              class:current={row.item.state === 'current'}
              class:undone={row.item.state === 'undone'}
              onclick={() => jumpCueHistory(row.item.id)}
              title={row.item.state === 'current'
                ? '当前状态'
                : row.item.state === 'undone'
                  ? '点击重做到这一步'
                  : '点击回到这一步'}
            >
              <span class="hist-icon">
                {#if row.item.state === 'current'}
                  <Icon name="check" size={10} />
                {:else if row.item.state === 'undone'}
                  <Icon name="redo" size={10} />
                {:else}
                  <Icon name="undo" size={10} />
                {/if}
              </span>
              <span class="hist-label">{row.item.label}</span>
              <span class="hist-time">{clock(row.item.at)}</span>
            </button>
          {/each}
        </div>
        <div class="hist-foot">点任意一步回到该状态；⌘Z 撤回最近一次操作</div>
      </div>
    {/if}
  </div>

  <button class="btn icon ghost" onclick={toggleTheme} title="切换外观（⇧⌘A）">
    <Icon name="moon" size={14} />
  </button>
  <button
    class="btn icon ghost"
    onclick={() => (app.inspectorOpen = !app.inspectorOpen)}
    title="显示/隐藏检查器（⌥⌘I）"
    disabled={app.view !== 'review'}
  >
    <Icon name="sidebar" size={14} />
  </button>
</header>

<style>
  .toolbar {
    /* backdrop-filter 会建立层叠上下文；不给 z-index 的话，历史下拉会被
       后面的检查器盖住（用户看到的是半截面板）。 */
    position: relative;
    z-index: 30;
    height: 52px;
    flex: 0 0 52px;
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 0 16px;
    /* 发丝线用 inset shadow 而不是 border：border 会吃掉 1px 内容高度，
       52 高工具栏里的 18px 标题就会落在 16.5px 上（半像素发虚）。 */
    box-shadow: inset 0 -1px 0 var(--separator);
    background: var(--bg-toolbar);
    backdrop-filter: saturate(180%) blur(20px);
    -webkit-backdrop-filter: saturate(180%) blur(20px);
    -webkit-app-region: drag;
  }
  /* 用 :global 才能命中子组件（EngineSwitch 等）的根节点；Svelte 会把普通
     `.toolbar > *` 编译成带本组件作用域哈希的选择器，子组件根节点匹配不上，
     那个区域的点击就会被系统当成拖动窗口。 */
  .toolbar > :global(*) {
    -webkit-app-region: no-drag;
  }

  .tb-title {
    font-size: var(--fs-body);
    line-height: 18px;
    font-weight: 600;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    max-width: 300px;
  }
  .tb-sub {
    font-size: var(--fs-label);
    line-height: 16px;
    color: var(--text-2);
    font-variant-numeric: tabular-nums;
    white-space: nowrap;
  }
  .toolbar .btn.on {
    background: var(--accent-soft);
    color: var(--accent);
  }
  .tb-sep {
    width: 1px;
    height: 18px;
    background: var(--separator);
    flex: 0 0 1px;
  }
  .tb-spacer {
    flex: 1;
  }

  /* 代理压制在后台跑：工具栏常驻一条紧凑进度条，切换到别的页面也能看到。 */
  .proxy-chip {
    display: flex;
    align-items: center;
    gap: 6px;
    height: 24px;
    padding: 0 8px;
    border-radius: 6px;
    background: var(--accent-soft);
    color: var(--accent);
    font-size: 11.5px;
    flex: 0 0 auto;
    white-space: nowrap;
  }
  .pc-label {
    font-weight: 600;
  }
  .pc-track {
    width: 42px;
    height: 3px;
    border-radius: 2px;
    background: var(--fill-strong);
    overflow: hidden;
  }
  .pc-track > i {
    display: block;
    height: 100%;
    border-radius: 2px;
    background: var(--accent);
    transition: width 320ms var(--ease);
  }
  .proxy-chip b {
    font-variant-numeric: tabular-nums;
    font-weight: 600;
    min-width: 30px;
    text-align: right;
  }

  /* 核对台主路径：文字按钮，不抢图标按钮的安静感 */
  .top-act {
    height: 28px;
    padding: 0 9px;
    color: var(--text-2);
    gap: 5px;
  }
  .top-act:hover:not(:disabled) {
    background: var(--line-2);
    border-color: transparent;
    color: var(--text);
  }
  .more {
    font-size: 16px;
    line-height: 1;
    color: var(--text-2);
  }

  .more-wrap {
    position: relative;
    display: flex;
    align-items: center;
  }
  .menu-backdrop {
    position: fixed;
    inset: 0;
    z-index: 60;
    border: 0;
    padding: 0;
    background: transparent;
    cursor: default;
    -webkit-app-region: no-drag;
  }
  .more-menu {
    position: absolute;
    top: calc(100% + 7px);
    right: 0;
    z-index: 61;
    width: 232px;
    padding: 4px;
    display: flex;
    flex-direction: column;
    gap: 1px;
    background: var(--raise);
    border: 1px solid var(--line);
    border-radius: 8px;
    box-shadow: var(--shadow-pop);
    -webkit-app-region: no-drag;
    animation: menuIn 140ms var(--ease);
  }
  @keyframes menuIn {
    from {
      opacity: 0;
      transform: translateY(-3px);
    }
  }
  .menu-item {
    appearance: none;
    border: 0;
    background: transparent;
    color: var(--text);
    font: inherit;
    font-size: 12.5px;
    width: 100%;
    height: 30px;
    padding: 0 8px;
    border-radius: 4px;
    display: flex;
    align-items: center;
    gap: 8px;
    text-align: left;
    cursor: default;
  }
  .menu-item:hover:not(:disabled) {
    background: var(--accent-soft);
    color: var(--accent);
  }
  .menu-item:disabled {
    opacity: 0.45;
  }
  .mi-label {
    flex: 1;
    min-width: 0;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .mi-sub {
    font-size: 12px;
    color: var(--text-3);
    font-variant-numeric: tabular-nums;
  }
  .mi-sep {
    height: 1px;
    margin: 4px 6px;
    background: var(--separator-soft);
  }

  .history-wrap {
    position: relative;
    display: flex;
    align-items: center;
  }
  .hist-backdrop {
    position: fixed;
    inset: 0;
    z-index: 60;
    border: 0;
    padding: 0;
    background: transparent;
    cursor: default;
    -webkit-app-region: no-drag;
  }
  .hist-panel {
    animation: histIn 160ms var(--ease);
    position: absolute;
    top: calc(100% + 7px);
    right: 0;
    z-index: 61;
    width: 310px;
    max-height: min(420px, 64vh);
    display: flex;
    flex-direction: column;
    background: var(--bg-content);
    border: 1px solid var(--separator);
    border-radius: 8px;
    box-shadow: var(--shadow-pop);
    overflow: hidden;
    -webkit-app-region: no-drag;
  }
  @keyframes histIn {
    from {
      opacity: 0;
      transform: translateY(-4px);
    }
  }
  .hist-head {
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    gap: 8px;
    padding: 10px 12px 8px;
    font-size: 12.5px;
    font-weight: 600;
    border-bottom: 1px solid var(--separator-soft);
  }
  .hist-sub {
    font-size: 12px;
    font-weight: 400;
    color: var(--text-3);
    font-variant-numeric: tabular-nums;
  }
  .hist-list {
    overflow-y: auto;
    padding: 4px;
    display: flex;
    flex-direction: column;
    gap: 1px;
  }
  .hist-item {
    appearance: none;
    border: 0;
    background: transparent;
    color: var(--text);
    font: inherit;
    width: 100%;
    display: flex;
    align-items: center;
    gap: 7px;
    padding: 5px 7px;
    border-radius: 4px;
    text-align: left;
    cursor: pointer;
  }
  .hist-item:hover {
    background: var(--row-hover);
  }
  .hist-item.current {
    background: var(--accent-soft);
    cursor: default;
  }
  .hist-item.current .hist-label {
    color: var(--accent);
    font-weight: 600;
  }
  .hist-item.undone {
    opacity: 0.55;
  }
  .hist-icon {
    width: 16px;
    flex: 0 0 16px;
    display: grid;
    place-items: center;
    color: var(--text-3);
  }
  .hist-item.current .hist-icon {
    color: var(--accent);
  }
  .hist-label {
    flex: 1;
    min-width: 0;
    font-size: 12.5px;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .hist-time {
    flex: 0 0 auto;
    font-size: 12px;
    color: var(--text-3);
    font-variant-numeric: tabular-nums;
    font-family: ui-monospace, 'SF Mono', Menlo, monospace;
  }
  .hist-empty {
    padding: 18px 12px;
    text-align: center;
    font-size: 12.5px;
    color: var(--text-3);
  }
  .hist-foot {
    padding: 8px 12px 9px;
    border-top: 1px solid var(--separator-soft);
    font-size: 12px;
    color: var(--text-3);
  }

  /* 紧凑模式（≤900px）：标题让位给主路径，副标与引擎分段先后收起，
     「AI 优化 / 导出」只留图标（title + aria-label 仍在）。 */
  @media (max-width: 900px) {
    .toolbar {
      gap: 6px;
      padding: 0 10px;
    }
    .tb-sub {
      display: none;
    }
    .tb-title {
      min-width: 0;
      max-width: 40vw;
    }
    .top-act {
      width: 28px;
      padding: 0;
      justify-content: center;
    }
    .act-label {
      display: none;
    }
  }
  @media (max-width: 760px) {
    /* 引擎胶囊已经比平铺分段省空间；只收起标题后的分隔线，给主路径让位 */
    .tb-sep-lead {
      display: none;
    }
  }
</style>
