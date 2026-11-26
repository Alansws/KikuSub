<script lang="ts">
  /**
   * 标题栏（44px，横跨整窗）。
   *
   * 结构照 Cue Script 原型：左侧「本次文档」（片名 + 规格 + 代理状态），
   * 中间「我在哪」（段号 / 页名 / 这一页的状态），右侧「这一屏能做什么」。
   *
   * 为什么标题栏横跨整窗而不是停在侧栏右缘：macOS 的红绿灯是原生绘制、
   * DOM 量不到，一旦标题栏从半腰开始，就得靠 `--tl-safe-x` 反算内边距、
   * 再给侧栏顶部铺一条「连续的顶带」，任何一处不同步就会出现「竖线穿过
   * 黄绿灯」。横跨整窗之后，红绿灯永远在标题栏的左侧安全区里，几何问题消失。
   *
   * 收起/展开侧栏的开关现在常驻标题栏最左（红绿灯右侧），不再有「收起态
   * 换位置」的分支。
   */
  import Icon from './Icon.svelte';
  import EngineSwitch from './EngineSwitch.svelte';
  import SidebarToggle from './SidebarToggle.svelte';
  import { sidebarPrefs } from '../lib/sidebarPrefs.svelte';
  import PunctCleanPanel from './PunctCleanPanel.svelte';
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
    undo,
  } from '../lib/store.svelte';
  import { loadChapters } from '../lib/chapters.svelte';
  import { formatBytes, formatDuration } from '../lib/time';
  import { closePunctPanel, openPunctPanel, punctPanel } from '../lib/punctuationPanel.svelte';
  import { stageOf } from '../lib/viewMeta';
  import { appearanceName } from '../lib/themes';
  import { toggleAppearance } from '../lib/appearanceState.svelte';

  function clock(seconds: number) {
    return new Date(seconds * 1000).toLocaleTimeString('zh-CN', {
      hour12: false,
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
    });
  }

  let { engine = $bindable('whisper') }: { engine?: string } = $props();

  /** 低频但重要的一次性动作收在「⋯」里，标题栏留给主路径。 */
  let moreOpen = $state(false);

  const proxyBusy = $derived(
    app.jobKind === 'proxy' && (app.job?.status === 'running' || app.job?.status === 'queued'),
  );
  const jobBusy = $derived(app.job?.status === 'running' || app.job?.status === 'queued');
  const proxyPct = $derived(app.jobKind === 'proxy' ? (app.job?.percent ?? 0) : 0);
  const proxyLabel = $derived(
    proxyBusy ? '压制中…' : app.media?.proxy_ready ? '代理已就绪' : '压制代理',
  );
  const proxyHint = $derived(
    proxyBusy
      ? '正在后台压制 480p 监看代理（进度见标题栏右侧的胶囊）'
      : app.media?.proxy_ready
        ? '480p 监看代理已就绪，无需再压'
        : '为高码率 / 特殊编码视频压制 480p 监看代理，拖动进度条更流畅',
  );
  const hasTranslation = $derived(Boolean(app.translations[app.trackLang]));

  /** 文档规格：片长 · 编码 · 帧率。放标题栏左侧，属于「这份稿是什么片子」。 */
  const mediaMeta = $derived.by(() => {
    const m = app.media;
    if (!m) return '拖入视频或字幕开始';
    const parts = [formatDuration(m.duration)];
    if (m.video_codec) parts.push(m.video_codec);
    if (m.video_fps && m.video_fps > 0) parts.push(`${m.video_fps.toFixed(3)} fps`);
    return parts.filter(Boolean).join(' · ');
  });

  const crumb = $derived(stageOf(app.view));

  /** 这一页「此刻在做什么」：一句话，和页面主体说的是同一件事。 */
  const crumbNote = $derived.by(() => {
    const m = app.media;
    const n = app.cues.length;
    switch (app.view) {
      case 'import':
        return m ? `${formatBytes(m.size)} · ${formatDuration(m.duration)}` : '继续上次工程，或换一部片';
      case 'transcribe':
        return app.job?.status === 'running'
          ? `转写中 ${app.job.percent}%`
          : n
            ? `${n} 条主稿`
            : '待转写';
      case 'review':
        return n ? `${n} 条 · ${formatDuration(m?.duration ?? 0)}` : '还没有字幕';
      case 'dual':
        return '只读比较 · 编辑回核对台';
      case 'polish':
        return '时间轴锁定 · 只改文字';
      case 'reshape':
        return '会改条数与时间码';
      case 'translate':
        return '译文平行轨 · 不改原文';
      case 'export':
        return n ? `${n} 条 · 字幕 / 成片` : '字幕 / 成片';
      case 'report':
        return app.report ? `${n} 条 · 任务详报` : '任务详报';
      case 'prompts':
        return '单击选中 · 双击编辑';
      case 'settings':
        return '外观 · 引擎 · 路径 · 日志';
      default:
        return '';
    }
  });

  /**
   * 外观按钮是**两态开关**：图标 = 现在就是夜间（月亮）/ 现在就是日间（太阳），
   * 标题 = 点下去会变成什么。`auto` 不再有自己的第三个图标——按钮只回答
   * 「从眼前的画面翻到另一面」，跟随系统在设置 → 外观里。
   */
  const appearanceIcon = $derived(app.theme === 'dark' ? 'moon' : 'sun');
  const appearanceTitle = $derived(
    `现在：${app.theme === 'dark' ? appearanceName('dark') : appearanceName('light')} · 点击切到${
      app.theme === 'dark' ? appearanceName('light') : appearanceName('dark')
    }（⇧⌘A）`,
  );

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

  // 设置页可以停用引擎；标题栏只显示启用的那几个。
  const engines = $derived((app.config?.engines ?? []).filter((e) => e.enabled));

  /**
   * 引擎胶囊只属于「要选识别引擎」的两页：转写与核对台。
   * 其余页面与引擎无关，胶囊在那儿只是常驻杂音。
   */
  const engineVisible = $derived(app.view === 'transcribe' || app.view === 'review');
</script>

<header class="titlebar">
  <SidebarToggle />
  <span class="tb-sep tb-sep-lead"></span>

  <div class="doc" title={app.media?.path ?? ''}>
    <span class="doc-title">{app.media?.name ?? 'KikuSub'}</span>
    <span class="doc-meta">{mediaMeta}</span>
  </div>

  <!-- 监看代理状态：轻量胶囊，只在核对屏出现 -->
  {#if app.view === 'review' && app.media}
    <button
      class="proxy-state"
      class:busy={proxyBusy}
      class:ready={!proxyBusy && app.media.proxy_ready}
      class:warn={!proxyBusy && !app.media.proxy_ready && app.media.needs_proxy}
      onclick={() => {
        moreOpen = true;
      }}
      title={proxyHint}
      aria-label={proxyLabel}
    >
      <i class="ps-dot" aria-hidden="true"></i>
      {#if proxyBusy}
        <span>代理 {proxyPct}%</span>
      {:else if app.media.proxy_ready}
        <span>监看代理</span>
      {:else if app.media.needs_proxy}
        <span>需代理</span>
      {:else}
        <span>原始画面</span>
      {/if}
    </button>
  {/if}

  <!-- 我在哪：段号 / 页名 / 这一页的状态。居中，是标题栏唯一的「导航」信息 -->
  <div class="crumb">
    {#if crumb.stage}
      <span class="crumb-stage">{crumb.stage}</span>
      <span class="crumb-sep" aria-hidden="true">/</span>
    {/if}
    <span class="crumb-current">{crumb.label}</span>
    {#if crumbNote}
      <span class="crumb-note">{crumbNote}</span>
    {/if}
  </div>

  <div class="top-actions">
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

    {#if engineVisible}
      {#if engines.length}
        <EngineSwitch bind:engine {engines} onmanage={manageEngines} />
      {:else}
        <button class="btn ghost" onclick={() => setView('settings')}>
          <Icon name="warn" size={12} />没有启用的引擎
        </button>
      {/if}
      <span class="tb-sep"></span>
    {/if}

    {#if app.view === 'review'}
      <div class="punct-wrap">
        <button
          class="btn ghost top-act"
          class:on={punctPanel.open}
          data-punct-trigger
          aria-expanded={punctPanel.open}
          onclick={() => (punctPanel.open ? closePunctPanel() : openPunctPanel())}
          title="清理整轨里多余的标点（可只清原文 / 只清译文 / 两轨一起；译文的句中语义标点保留，只清行尾与重复；条数与时间轴不变；⌘⇧L）"
          aria-label="清理标点"
        >
          <Icon name="punct" size={12} /><span class="act-label">清理标点</span>
        </button>
        <PunctCleanPanel />
      </div>
      <button
        class="btn ghost top-act"
        onclick={() => setView('polish')}
        title="锁轴润色：按全片语境修正识别错误，只改文字、不动时间轴"
        aria-label="锁轴润色"
      >
        <Icon name="pencil" size={12} /><span class="act-label">锁轴润色</span>
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
              disabled={jobBusy || !app.media}
              title={app.media?.proxy_ready
                ? '选择另一份已经压好的代理文件，替换当前监看代理（不再重新压制）'
                : '选择已经压好的代理文件，直接挂到当前媒体，不再重新压制'}
            >
              <Icon name="tray" size={12} />
              <span class="mi-label">导入代理</span>
              <span class="mi-sub">{app.media?.proxy_ready ? '替换现有' : '已有文件'}</span>
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
              <span class="mi-label">导入原文字幕</span>
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
              <span class="mi-label">导入译文字幕</span>
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

      <span class="tb-sep"></span>
    {/if}

    <button
      class="btn icon ghost"
      onclick={undo}
      disabled={!undoInfo.label}
      title={undoInfo.label ? `撤回：${undoInfo.label}（⌘Z）` : '没有可撤回的操作'}
      aria-label="撤回"
    >
      <Icon name="undo" size={14} />
    </button>
    <button
      class="btn icon ghost"
      onclick={redo}
      disabled={!redoInfo.label}
      title={redoInfo.label ? `重做：${redoInfo.label}（⇧⌘Z）` : '没有可重做的操作'}
      aria-label="重做"
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
        aria-label="撤销历史"
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
                onclick={() => {
                  void jumpCueHistory(row.item.id);
                  void loadChapters(true);
                }}
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

    <button
      class="btn icon ghost"
      onclick={toggleAppearance}
      title={appearanceTitle}
      aria-label={appearanceTitle}
    >
      <Icon name={appearanceIcon} size={14} />
    </button>
    <button
      class="btn icon ghost"
      onclick={() => (app.inspectorOpen = !app.inspectorOpen)}
      title="显示/隐藏检查器（⌥⌘I）"
      aria-label="显示/隐藏检查器"
      disabled={app.view !== 'review'}
    >
      <Icon name="sidebar" size={14} />
    </button>
  </div>
</header>

<style>
  .titlebar {
    position: relative;
    z-index: 30;
    height: var(--topbar-h);
    flex: 0 0 var(--topbar-h);
    display: flex;
    align-items: center;
    gap: var(--sp-2);
    /* 红绿灯是原生绘制的：标题栏横跨整窗，所以恒定让出安全区。
       右侧 12px 是与窗口右缘的呼吸。 */
    padding: 0 12px 0 var(--tl-safe-x);
    box-shadow: inset 0 -1px 0 var(--line);
    background: var(--bg-toolbar);
    backdrop-filter: saturate(180%) blur(20px);
    -webkit-backdrop-filter: saturate(180%) blur(20px);
    -webkit-app-region: drag;
  }
  /* 只有**真正可点的东西**断开拖拽。不能一刀切成 `.titlebar > * { no-drag }`：
     那样片名、面包屑与它们之间的空白都不再能拖窗口，标题栏只剩几像素可以抓。
     （子组件里的按钮也要覆盖，所以用 :global。） */
  .titlebar :global(button),
  .titlebar :global(a),
  .titlebar :global(input),
  .titlebar :global(select),
  .titlebar :global(textarea) {
    -webkit-app-region: no-drag;
  }
  .titlebar > :global(.sb-toggle) {
    flex: 0 0 auto;
  }

  .doc {
    display: flex;
    align-items: baseline;
    gap: var(--sp-2);
    min-width: 0;
    flex: 0 1 auto;
  }
  .doc-title {
    font-size: var(--fs-body);
    font-weight: 600;
    letter-spacing: -0.005em;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    max-width: 260px;
  }
  .doc-meta {
    font-size: 11px;
    color: var(--text-3);
    font-variant-numeric: tabular-nums;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  /* 面包屑是标题栏唯一的导航信息：段号 / 页名 / 状态，居中且可省略 */
  .crumb {
    flex: 1 1 auto;
    min-width: 0;
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 7px;
    padding: 0 var(--sp-2);
  }
  .crumb-stage {
    font-family: var(--font-mono);
    font-size: 11px;
    letter-spacing: 0.04em;
    color: var(--text-3);
    flex: 0 0 auto;
  }
  .crumb-sep {
    font-size: 11px;
    color: var(--text-3);
    flex: 0 0 auto;
  }
  .crumb-current {
    font-size: 12px;
    font-weight: 600;
    color: var(--text);
    white-space: nowrap;
    flex: 0 0 auto;
  }
  .crumb-note {
    font-size: 11px;
    color: var(--text-3);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    min-width: 0;
  }

  .top-actions {
    display: flex;
    align-items: center;
    gap: 6px;
    flex: 0 0 auto;
  }

  .tb-sep {
    width: 1px;
    height: 16px;
    background: var(--line);
    flex: 0 0 1px;
  }

  .titlebar .btn.on {
    background: var(--accent-soft);
    color: var(--accent);
  }

  /* 代理压制在后台跑：标题栏常驻一条紧凑进度条，切到别的页面也看得见 */
  .proxy-chip {
    display: flex;
    align-items: center;
    gap: 6px;
    height: 24px;
    padding: 0 var(--sp-2);
    border-radius: var(--rad-control);
    background: var(--accent-soft);
    color: var(--accent-text);
    font-size: 11px;
    flex: 0 0 auto;
    white-space: nowrap;
  }
  .pc-label {
    font-weight: 600;
  }
  .pc-track {
    width: 40px;
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
    min-width: 28px;
    text-align: right;
  }

  /* 核对台主路径：文字按钮，不抢图标按钮的安静感 */
  .top-act {
    height: 26px;
    padding: 0 var(--sp-2);
    color: var(--text-2);
    gap: 5px;
  }
  .more {
    font-size: 15px;
    line-height: 1;
    color: var(--text-2);
  }

  .more-wrap,
  .punct-wrap,
  .history-wrap {
    position: relative;
    display: flex;
    align-items: center;
  }
  .menu-backdrop,
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
  .more-menu {
    position: absolute;
    top: calc(100% + 7px);
    right: 0;
    z-index: 61;
    width: 232px;
    padding: var(--sp-1);
    display: flex;
    flex-direction: column;
    gap: 1px;
    background: var(--raise);
    border: 1px solid var(--line);
    border-radius: var(--rad-card);
    box-shadow: var(--shadow-pop);
    -webkit-app-region: no-drag;
    animation: menuIn 120ms var(--ease);
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
    height: var(--row-h);
    padding: 0 var(--sp-2);
    border-radius: 4px;
    display: flex;
    align-items: center;
    gap: var(--sp-2);
    text-align: left;
    cursor: default;
  }
  .menu-item:hover:not(:disabled) {
    background: var(--accent-soft);
    color: var(--accent-text);
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
    font-size: 11px;
    color: var(--text-3);
    font-variant-numeric: tabular-nums;
  }
  .mi-sep {
    height: 1px;
    margin: var(--sp-1) 6px;
    background: var(--line-2);
  }

  .hist-panel {
    animation: histIn 140ms var(--ease);
    position: absolute;
    top: calc(100% + 7px);
    right: 0;
    z-index: 61;
    width: 310px;
    max-height: min(420px, 64vh);
    display: flex;
    flex-direction: column;
    background: var(--raise);
    border: 1px solid var(--line);
    border-radius: var(--rad-card);
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
    gap: var(--sp-2);
    padding: 10px var(--sp-3) var(--sp-2);
    font-size: 12.5px;
    font-weight: 600;
    border-bottom: 1px solid var(--line);
  }
  .hist-sub {
    font-size: 11px;
    font-weight: 400;
    color: var(--text-3);
    font-variant-numeric: tabular-nums;
  }
  .hist-list {
    overflow-y: auto;
    padding: var(--sp-1);
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
    color: var(--accent-text);
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
    font-size: 11px;
    color: var(--text-3);
    font-family: var(--font-mono);
    font-variant-numeric: tabular-nums;
  }
  .hist-empty {
    padding: 18px var(--sp-3);
    text-align: center;
    font-size: 12.5px;
    color: var(--text-3);
  }
  .hist-foot {
    padding: var(--sp-2) var(--sp-3) 9px;
    border-top: 1px solid var(--line);
    font-size: 11px;
    color: var(--text-3);
  }

  /* 监看代理状态：22px 高的小胶囊，和片名同一行 */
  .proxy-state {
    appearance: none;
    flex: 0 0 auto;
    display: inline-flex;
    align-items: center;
    gap: 5px;
    height: 22px;
    padding: 0 var(--sp-2);
    border: 1px solid var(--line);
    border-radius: 11px;
    background: transparent;
    color: var(--text-3);
    font: inherit;
    font-size: 11px;
    line-height: 1;
    white-space: nowrap;
    transition:
      border-color var(--dur-fast) var(--ease),
      color var(--dur-fast) var(--ease);
  }
  .proxy-state:hover {
    border-color: var(--accent-line);
    color: var(--accent-text);
  }
  .proxy-state:focus-visible {
    outline: 2px solid var(--accent-ring);
    outline-offset: 1px;
  }
  .ps-dot {
    width: 5px;
    height: 5px;
    flex: 0 0 5px;
    border-radius: 50%;
    background: currentColor;
    opacity: 0.55;
  }
  .proxy-state.ready {
    color: var(--success);
  }
  .proxy-state.ready .ps-dot {
    opacity: 1;
  }
  .proxy-state.warn {
    color: var(--warn);
  }
  .proxy-state.busy {
    color: var(--accent-text);
    border-color: var(--accent-line);
  }

  /* 窄窗：先收「文档规格」与动作文字，保住面包屑与主路径 */
  @media (max-width: 1240px) {
    .doc-meta {
      display: none;
    }
    .act-label {
      display: none;
    }
    .top-act {
      width: 26px;
      padding: 0;
      justify-content: center;
    }
  }
  @media (max-width: 1040px) {
    .crumb-note {
      display: none;
    }
    .doc-title {
      max-width: 150px;
    }
  }
  @media (max-width: 900px) {
    .titlebar {
      gap: 6px;
      padding-right: 10px;
    }
    .doc {
      display: none;
    }
  }
</style>
