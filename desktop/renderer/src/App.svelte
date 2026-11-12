<script lang="ts">
  import { tick, untrack } from 'svelte';
  import Icon from './components/Icon.svelte';
  import Sidebar from './components/Sidebar.svelte';
  import Toolbar from './components/Toolbar.svelte';
  import StatusBar from './components/StatusBar.svelte';
  import Inspector from './components/Inspector.svelte';
  import QaPanel from './components/QaPanel.svelte';
  import FirstRun from './components/FirstRun.svelte';
  import QuitPrompt from './components/QuitPrompt.svelte';
  import ShortcutsDialog from './components/ShortcutsDialog.svelte';
  import ImportView from './views/ImportView.svelte';
  import TranscribeView from './views/TranscribeView.svelte';
  import ReviewView from './views/ReviewView.svelte';
  import AiView from './views/AiView.svelte';
  import ReportView from './views/ReportView.svelte';
  import PromptView from './views/PromptView.svelte';
  import ExportView from './views/ExportView.svelte';
  import SettingsView from './views/SettingsView.svelte';
  import {
    app,
    applyDevSeed,
    boot,
    cancelJob,
    closeFind,
    findState,
    insertCueAt,
    markQuitting,
    markSidecarDown,
    openFind,
    openMedia,
    play,
    restoreLastSession,
    qa,
    redo,
    setView,
    toast,
    toggleQaPanel,
    toggleTheme,
    undo,
    type View,
  } from './lib/store.svelte';
  import { resolveShortcut, shortcuts } from './lib/shortcuts.svelte';

  let engine = $state('whisper');
  let review: {
    api_play: () => void;
    api_step: (d: number) => void;
    api_focus: () => void;
    api_deleteSelected: () => void;
    api_findStep: (d: number) => void;
  } | undefined = $state();
  let dragging = $state(false);
  /** 紧凑模式（≤900px CSS 视口）：检查器变成抽屉，内容区拿回整宽。 */
  let compact = $state(false);
  /**
   * 首屏不播页面转场：冷启动时淡入一次会像「页面晚了一拍」，切页才播。
   * 故意不用 $state：它只在 {#key app.view} 重建 DOM 时读取，
   * 变成响应式反而会把 class 补到已经存在的首屏元素上，等于又播了一次。
   */
  let viewsAnimate = false;

  $effect(() => {
    const id = requestAnimationFrame(() => {
      viewsAnimate = true;
    });
    return () => cancelAnimationFrame(id);
  });

  // 首次启动向导 / 退出前清理。两者都由主进程先问状态，不依赖 sidecar。
  let setup = $state<{
    firstRun: boolean;
    modelsDir: string;
    defaultModelsDir: string;
    dataDir: string;
    ffmpeg: string;
  } | null>(null);
  let setupLoading = $state(true);
  let quitFiles = $state<
    { path: string; name: string; kind: 'fragment' | 'proxy'; size: number; mtime: number }[]
  >([]);
  let quitBusy = $state(false);

  $effect(() => {
    let alive = true;
    const bridge = window.kikusub;
    if (!bridge?.getSetupState) {
      setupLoading = false;
      return;
    }
    bridge
      .getSetupState()
      .then((state) => {
        if (alive) setup = state;
      })
      .catch(() => {
        /* 老版本主进程没有这个桥时按“非首次启动”处理 */
      })
      .finally(() => {
        if (alive) setupLoading = false;
      });
    return () => {
      alive = false;
    };
  });

  $effect(() => {
    const offPrompt = window.kikusub?.onQuitPrompt?.((payload) => {
      quitFiles = payload.files ?? [];
      quitBusy = false;
    });
    const offCancelled = window.kikusub?.onQuitCancelled?.(() => {
      quitFiles = [];
      quitBusy = false;
    });
    // 主进程开始退出：收掉启动遮罩，别再让用户对着「正在启动转写内核」等 sidecar 收尾
    const offQuitting = window.kikusub?.onQuitting?.(() => {
      quitFiles = [];
      markQuitting();
    });
    // 事件可能在 App 挂载前就发出（启动瞬间按 ⌘Q），补问一次
    window.kikusub
      ?.getQuitPrompt?.()
      .then((payload) => {
        if (payload?.files?.length) quitFiles = payload.files;
      })
      .catch(() => {});
    return () => {
      offPrompt?.();
      offCancelled?.();
      offQuitting?.();
    };
  });

  // ---------------- 握手 ----------------
  $effect(() => {
    let alive = true;
    let booting = false;
    let lastPort = 0;

    /**
     * 握手可能发生多次：首次启动、改模型目录后内核重启、崩溃自动重启。
     *
     * 注意：页面挂载时 sidecar 通常还没起好，`getSidecar()` 会返回 null；
     * 真正可用的是随后到达的 `sidecar:ready` 事件。两条路径都要走这里，
     * 否则「启动后注入种子」这类逻辑只会在其中一条上生效（踩过）。
     */
    async function onReady(payload: { port: number; token: string } | null) {
      if (!alive || booting || !payload?.port) return;
      // 同一个内核的重复 ready（getSidecar + 事件广播）不必重新握手
      if (lastPort === payload.port && app.connected) return;
      booting = true;
      try {
        await boot(payload.port, payload.token);
        if (!alive) return;
        lastPort = payload.port;
        const seed = await window.kikusub.getDevSeed?.().catch(() => null);
        if (!alive) return;
        if (seed) {
          await applyDevSeed(seed);
        } else {
          // 冷启动自动接上上次的视频、草稿/导入字幕与播放头。
          // 有种子（开发截图）或双击文件启动（openMedia 已绑定）时不会走到这里。
          await restoreLastSession();
        }
      } finally {
        booting = false;
      }
    }

    window.kikusub.getSidecar().then(onReady).catch(() => {});

    const offReady = window.kikusub.onSidecarReady((p) => onReady(p));
    const offDown = window.kikusub.onSidecarDown(() => {
      lastPort = 0;
      markSidecarDown();
    });
    const offFile = window.kikusub.onFileOpened((path) => openMedia(path));

    return () => {
      alive = false;
      offReady();
      offDown();
      offFile();
    };
  });

  function finishFirstRun() {
    if (setup) setup = { ...setup, firstRun: false };
  }

  async function confirmQuit(keep: string[]) {
    quitBusy = true;
    try {
      await window.kikusub.confirmQuit(keep);
    } catch (err) {
      quitBusy = false;
      toast(`退出清理失败：${(err as Error).message}`, 'error');
    }
  }

  async function cancelQuit() {
    quitFiles = [];
    quitBusy = false;
    await window.kikusub.cancelQuit?.();
  }

  // ---------------- 紧凑模式（≤900px） ----------------
  // 页面缩放会让 CSS 视口变小，媒体查询自动生效；这里只做两件 CSS 做不到的事：
  // 1) 进入紧凑模式时先把抽屉收起一次，200% 下先看到画面而不是被检查器盖住；
  // 2) 回到宽屏时恢复「上一次宽屏的开关」，不永久改写用户的桌面偏好。
  $effect(() => {
    const mq = window.matchMedia('(max-width: 900px)');
    let wideOpen = untrack(() => app.inspectorOpen);
    compact = mq.matches;
    app.compact = mq.matches;
    if (mq.matches) app.inspectorOpen = false;

    const onChange = () => {
      if (mq.matches) {
        // 进紧凑模式前记下宽屏值，回到宽屏原样还回去
        wideOpen = untrack(() => app.inspectorOpen);
        app.inspectorOpen = false;
      } else {
        app.inspectorOpen = wideOpen;
      }
      compact = mq.matches;
      app.compact = mq.matches;
    };
    mq.addEventListener('change', onChange);
    return () => mq.removeEventListener('change', onChange);
  });

  // ---------------- 菜单 ----------------
  $effect(() => {
    return window.kikusub.onMenu((ev) => {
      switch (ev.type) {
        case 'undo':
          undo();
          break;
        case 'redo':
          redo();
          break;
        case 'play':
          review?.api_play();
          break;
        case 'prev-cue':
          review?.api_step(-1);
          break;
        case 'next-cue':
          review?.api_step(1);
          break;
        case 'view':
          setView(ev.view as View);
          break;
        case 'inspector':
          app.inspectorOpen = !app.inspectorOpen;
          break;
        case 'theme':
          toggleTheme();
          break;
        case 'settings':
          setView('settings');
          break;
        case 'export':
          setView('export');
          break;
        case 'find':
          openFind();
          break;
        case 'shortcuts':
          shortcuts.open = true;
          break;
      }
    });
  });

  // 进入核对屏时先交还键盘焦点：从 AI 建议 / 其他页面跳回来时，如果光标还停在
  // 右侧检查器的文本框里（且可能选中了整段文本），用户习惯性按空格试听就会把
  // 文本替换成一个空格。核对台的空格应该是播放 / 暂停，不是输入。
  $effect(() => {
    if (app.view !== 'review') return;
    const el = document.activeElement as HTMLElement | null;
    if (!el || el === document.body) return;
    // 只处理右侧检查器里的输入框：查找栏、AI 编辑框等由各自组件管理焦点，
    // 在这里统一 blur 会把刚打开的查找框也踢掉。
    const inInspector = Boolean(el.closest?.('.inspector')) || el.classList?.contains('cue-text');
    if (!inInspector) return;
    if (el.tagName === 'TEXTAREA' || el.tagName === 'INPUT' || el.isContentEditable) {
      el.blur();
    }
  });

  // ---------------- 拖放 ----------------
  function onDragOver(e: DragEvent) {
    e.preventDefault();
    if (e.dataTransfer?.types.includes('Files')) dragging = true;
  }

  function onDragLeave(e: DragEvent) {
    if (e.target === document.documentElement) dragging = false;
  }

  async function onDrop(e: DragEvent) {
    e.preventDefault();
    dragging = false;
    const file = e.dataTransfer?.files?.[0];
    if (!file) return;
    const path = window.kikusub.getPathForFile(file);
    if (path) await openMedia(path);
  }

  // ---------------- 快捷键 ----------------
  /** 执行一个可自定义快捷键对应的动作。 */
  function runShortcut(id: string) {
    switch (id) {
      case 'shortcuts.open':
        shortcuts.open = !shortcuts.open;
        return;
      case 'review.togglePlay':
        if (app.view === 'review') review?.api_play();
        return;
      case 'review.prevCue':
        if (app.view === 'review') review?.api_step(-1);
        return;
      case 'review.nextCue':
        if (app.view === 'review') review?.api_step(1);
        return;
      case 'review.deleteCue':
        if (app.view === 'review') review?.api_deleteSelected();
        return;
      case 'review.addCue': {
        if (app.view !== 'review') setView('review');
        void tick().then(() => insertCueAt(play.time));
        return;
      }
      case 'review.find':
        openFind();
        return;
      case 'review.findPrev':
        if (app.view === 'review') review?.api_findStep(-1);
        return;
      case 'review.findNext':
        if (app.view === 'review') review?.api_findStep(1);
        return;
      case 'review.toggleQa':
        void toggleQaPanel();
        return;
      case 'view.import':
        setView('import');
        return;
      case 'view.transcribe':
        setView('transcribe');
        return;
      case 'view.review':
        setView('review');
        return;
      case 'view.ai':
        setView('ai');
        return;
      case 'view.export':
        setView('export');
        return;
    }
  }

  function onKey(e: KeyboardEvent) {
    // ⌘, 是 macOS 的「设置…」惯例。菜单里也绑了同一条，但菜单快捷键在
    // 输入框聚焦时会被输入法/文本框吃掉，这里再兜一层。
    const mod = e.metaKey || e.ctrlKey;
    if (mod && (e.key === ',' || e.code === 'Comma')) {
      e.preventDefault();
      setView('settings');
      return;
    }

    if (shortcuts.open && e.key === 'Escape') {
      e.preventDefault();
      shortcuts.open = false;
      return;
    }

    if (e.key === 'Escape' && quitFiles.length) {
      e.preventDefault();
      void cancelQuit();
      return;
    }

    // 质检面板是浮层：Esc 先收起它，再轮到查找栏 / 抽屉。
    if (e.key === 'Escape' && qa.open) {
      e.preventDefault();
      void toggleQaPanel(false);
      return;
    }

    // 查找栏打开时 Esc 关闭它（输入框自己的 onkeydown 也会处理，这里兜住焦点不在输入框的情况）
    if (e.key === 'Escape' && app.view === 'review' && findState.open) {
      e.preventDefault();
      closeFind();
      return;
    }

    // 紧凑模式：抽屉打开时 Esc 先收抽屉，和工具栏的开关是同一个动作
    if (e.key === 'Escape' && compact && app.inspectorOpen) {
      e.preventDefault();
      app.inspectorOpen = false;
      return;
    }

    const target = e.target as HTMLElement | null;
    const typing =
      target &&
      (target.tagName === 'INPUT' ||
        target.tagName === 'TEXTAREA' ||
        target.isContentEditable);
    // 文本框里保留原生的逐字撤销；滑杆 / 复选框 / 下拉没有原生撤销，
    // 焦点停在字号滑杆上按 ⌘Z 也要能撤回导出设置（用户报过这里没反应）。
    const textEntry =
      target &&
      (target.tagName === 'TEXTAREA' ||
        target.isContentEditable ||
        (target.tagName === 'INPUT' &&
          ['text', 'search', 'email', 'number', 'password', 'url'].includes(
            (target as HTMLInputElement).type,
          )));
    if (mod && (e.key === 'z' || e.key === 'Z')) {
      if (!textEntry) {
        e.preventDefault();
        if (e.shiftKey) redo();
        else undo();
      }
      return;
    }

    // 用户自定义的快捷键：输入框聚焦时只有 allowInTyping 的动作生效。
    const action = resolveShortcut(e, app.view, { findOpen: findState.open });
    if (action) {
      // 快捷键面板是模态：只有「再按一次打开键」能关闭，其余按键不穿透到核对台。
      if (shortcuts.open && action.id !== 'shortcuts.open') return;
      e.preventDefault();
      runShortcut(action.id);
      return;
    }

    if (typing) return;

    // 物理 Delete / Backspace 始终可以删除选中的字幕（多选时一起删），
    // 不必先记住默认的 Enter；文本框里不触发。
    if (app.view === 'review' && (e.key === 'Backspace' || e.key === 'Delete')) {
      e.preventDefault();
      review?.api_deleteSelected();
      return;
    }

    if (e.key === 'Escape' && app.job?.status === 'running') {
      cancelJob();
    }
  }

  $effect(() => {
    // 工具栏只列「已启用」的引擎；当前引擎被停用/移除时自动切到第一个可用的。
    const enabled = (app.config?.engines ?? []).filter((e) => e.enabled);
    if (!enabled.length) return;
    if (!enabled.some((e) => e.key === engine)) {
      engine = (enabled.find((e) => e.installed) ?? enabled[0]).key;
    }
    // 核对台的「重转此句 / 质检补录」用同一个引擎
    app.engine = engine;
  });

  $effect(() => {
    // 窗口标题跟着媒体走，Dock 与 Mission Control 才对得上
    window.kikusub.setTitle(app.media ? `${app.media.name} — KikuSub` : 'KikuSub');
  });
</script>

<svelte:window
  ondragover={onDragOver}
  ondragleave={onDragLeave}
  ondrop={onDrop}
  onkeydown={onKey}
/>

<div class="shell">
  <Sidebar />

  <div class="main">
    <Toolbar bind:engine />

    <div class="workspace">
      <section class="content">
        {#key app.view}
        <div class="view-enter" class:animated={viewsAnimate}>
        {#if app.view === 'import'}
          <ImportView />
        {:else if app.view === 'transcribe'}
          <TranscribeView bind:engine />
        {:else if app.view === 'review'}
          <ReviewView bind:this={review} {engine} />
        {:else if app.view === 'ai'}
          <AiView />
        {:else if app.view === 'prompts'}
          <PromptView />
        {:else if app.view === 'export'}
          <ExportView />
        {:else if app.view === 'report'}
          <ReportView />
        {:else if app.view === 'settings'}
          <SettingsView />
        {/if}
        </div>
        {/key}
      </section>

      {#if app.view === 'review'}
        {#if compact && app.inspectorOpen}
          <!-- 紧凑模式下检查器是抽屉：点空白处收起，Esc 同样关闭 -->
          <button
            class="ins-scrim"
            aria-label="关闭检查器"
            onclick={() => (app.inspectorOpen = false)}
          ></button>
        {/if}
        <Inspector />
      {/if}

      {#if qa.floating}
        <QaPanel mode="floating" />
      {/if}
    </div>

    <StatusBar {engine} />
  </div>
</div>

{#if app.quitting}
  <!-- 退出流程里什么都不显示：窗口马上就会被主进程收起 -->
{:else if setupLoading}
  <div class="overlay">
    <div class="overlay-card">
      <div class="spinner"></div>
      <div>正在准备…</div>
    </div>
  </div>
{:else if setup?.firstRun}
  <FirstRun
    defaultDir={setup.defaultModelsDir}
    currentDir={setup.modelsDir}
    dataDir={setup.dataDir}
    ffmpeg={setup.ffmpeg}
    ondone={finishFirstRun}
  />
{:else if app.connecting}
  <div class="overlay">
    <div class="overlay-card">
      <div class="spinner"></div>
      <div>正在启动转写内核…</div>
    </div>
  </div>
{/if}

{#if !app.quitting && !setupLoading && !setup?.firstRun && !app.connected && !app.connecting}
  <div class="overlay">
    <div class="overlay-card error">
      <Icon name="warn" size={18} />
      <div>内核未连接</div>
      <div class="hint">状态栏会显示重连状态；持续失败请到「设置 → 日志与诊断」复制日志反馈。</div>
    </div>
  </div>
{/if}

{#if !app.quitting && quitFiles.length}
  <QuitPrompt files={quitFiles} busy={quitBusy} onconfirm={confirmQuit} oncancel={cancelQuit} />
{/if}

{#if dragging}
  <div class="drop-hint">
    <Icon name="tray" size={26} />
    <div>松手导入</div>
  </div>
{/if}

<ShortcutsDialog />

{#if app.toast}
  <div class="toast" class:warn={app.toastKind === 'warn'} class:error={app.toastKind === 'error'}>
    {app.toast}
  </div>
{/if}

<style>
  .overlay {
    position: fixed;
    inset: 0;
    background: rgba(0, 0, 0, 0.18);
    backdrop-filter: blur(2px);
    display: grid;
    place-items: center;
    z-index: 200;
  }
  .overlay-card {
    background: var(--bg-content);
    border: 1px solid var(--separator);
    border-radius: 12px;
    box-shadow: var(--shadow-pop);
    padding: var(--sp-5) 26px;
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 10px;
    font-size: 12.5px;
  }
  .overlay-card.error {
    color: var(--danger);
  }
  .hint {
    color: var(--text-3);
    font-size: 12px;
    max-width: 260px;
    text-align: center;
  }
  .spinner {
    width: 18px;
    height: 18px;
    border-radius: 50%;
    border: 2px solid var(--fill-strong);
    border-top-color: var(--accent);
    animation: spin 700ms linear infinite;
  }
  @keyframes spin {
    to {
      transform: rotate(360deg);
    }
  }

  .drop-hint {
    position: fixed;
    inset: 0;
    border: 2.5px dashed var(--accent);
    background: var(--accent-soft);
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: var(--sp-2);
    color: var(--accent);
    font-size: 15px;
    font-weight: 500;
    z-index: 300;
    pointer-events: none;
  }

  .view-enter {
    flex: 1;
    min-height: 0;
    display: flex;
    flex-direction: column;
  }
  /* 只有切页才播；首屏（冷启动）不播，避免「页面晚了一拍」 */
  .view-enter.animated {
    animation: viewIn var(--dur-page) var(--ease) both;
  }
  /* 紧凑模式的抽屉遮罩：只盖住工作区，不挡工具栏（工具栏仍是拖窗与切换入口） */
  .ins-scrim {
    position: absolute;
    inset: 0;
    z-index: 19;
    border: 0;
    padding: 0;
    background: rgba(13, 20, 36, 0.22);
    cursor: default;
    animation: scrimIn 120ms var(--ease) both;
  }
  @keyframes scrimIn {
    from {
      opacity: 0;
    }
  }  @keyframes viewIn {
    from {
      opacity: 0;
      transform: translateY(4px);
    }
    to {
      opacity: 1;
      transform: none;
    }
  }

  .toast {
    animation: toastIn 180ms var(--ease) both;
    position: fixed;
    left: 50%;
    bottom: 44px;
    transform: translateX(-50%);
    background: rgba(30, 30, 32, 0.94);
    color: #fff;
    font-size: 12.5px;
    padding: var(--sp-2) 14px;
    border-radius: 8px;
    box-shadow: var(--shadow-pop);
    z-index: 250;
    max-width: 70vw;
    text-align: center;
  }
  @keyframes toastIn {
    from {
      opacity: 0;
      transform: translate(-50%, 6px);
    }
    to {
      opacity: 1;
      transform: translate(-50%, 0);
    }
  }
  .toast.warn {
    background: rgba(120, 74, 0, 0.96);
  }
  .toast.error {
    background: rgba(140, 30, 26, 0.96);
  }
</style>
