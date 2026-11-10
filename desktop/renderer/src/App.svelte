<script lang="ts">
  import Icon from './components/Icon.svelte';
  import Sidebar from './components/Sidebar.svelte';
  import Toolbar from './components/Toolbar.svelte';
  import StatusBar from './components/StatusBar.svelte';
  import Inspector from './components/Inspector.svelte';
  import QaPanel from './components/QaPanel.svelte';
  import ImportView from './views/ImportView.svelte';
  import TranscribeView from './views/TranscribeView.svelte';
  import ReviewView from './views/ReviewView.svelte';
  import ReportView from './views/ReportView.svelte';
  import {
    app,
    applyDevSeed,
    boot,
    cancelJob,
    markSidecarDown,
    openMedia,
    play,
    redo,
    setView,
    toggleTheme,
    undo,
    type View,
  } from './lib/store.svelte';

  let engine = $state('whisper');
  let review: {
    api_play: () => void;
    api_step: (d: number) => void;
    api_focus: () => void;
  } | undefined = $state();
  let dragging = $state(false);

  // ---------------- 握手 ----------------
  $effect(() => {
    let alive = true;
    let booted = false;

    /**
     * 握手只处理一次。
     *
     * 注意：页面挂载时 sidecar 通常还没起好，`getSidecar()` 会返回 null；
     * 真正可用的是随后到达的 `sidecar:ready` 事件。两条路径都要走这里，
     * 否则「启动后注入种子」这类逻辑只会在其中一条上生效（踩过）。
     */
    async function onReady(payload: { port: number; token: string } | null) {
      if (!alive || booted || !payload?.port) return;
      booted = true;
      await boot(payload.port, payload.token);
      if (!alive) return;
      const seed = await window.kikusub.getDevSeed?.().catch(() => null);
      if (alive && seed) applyDevSeed(seed);
    }

    window.kikusub.getSidecar().then(onReady).catch(() => {});

    const offReady = window.kikusub.onSidecarReady((p) => onReady(p));
    const offDown = window.kikusub.onSidecarDown(() => markSidecarDown());
    const offFile = window.kikusub.onFileOpened((path) => openMedia(path));

    return () => {
      alive = false;
      offReady();
      offDown();
      offFile();
    };
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
      }
    });
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
  function onKey(e: KeyboardEvent) {
    const target = e.target as HTMLElement | null;
    const typing =
      target &&
      (target.tagName === 'INPUT' ||
        target.tagName === 'TEXTAREA' ||
        target.isContentEditable);
    if (typing) return;

    if (e.code === 'Space') {
      e.preventDefault();
      review?.api_play();
    } else if (e.code === 'ArrowDown') {
      e.preventDefault();
      review?.api_step(1);
    } else if (e.code === 'ArrowUp') {
      e.preventDefault();
      review?.api_step(-1);
    } else if (e.key === 'Escape' && app.job?.status === 'running') {
      cancelJob();
    }
  }

  $effect(() => {
    // 工具栏切引擎后，核对台的「重转此句 / 质检补录」用同一个引擎
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
        {#if app.view === 'import'}
          <ImportView />
        {:else if app.view === 'transcribe'}
          <TranscribeView bind:engine />
        {:else if app.view === 'review'}
          <ReviewView bind:this={review} {engine} />
        {:else if app.view === 'report'}
          <ReportView />
        {/if}
      </section>

      {#if app.view === 'review'}
        <Inspector />
      {/if}

      <QaPanel />
    </div>

    <StatusBar />
  </div>
</div>

{#if app.connecting}
  <div class="overlay">
    <div class="overlay-card">
      <div class="spinner"></div>
      <div>正在启动转写内核…</div>
    </div>
  </div>
{/if}

{#if !app.connected && !app.connecting}
  <div class="overlay">
    <div class="overlay-card error">
      <Icon name="warn" size={18} />
      <div>内核未连接</div>
      <div class="hint">侧栏底部会显示重连状态；连续失败请查看终端日志。</div>
    </div>
  </div>
{/if}

{#if dragging}
  <div class="drop-hint">
    <Icon name="tray" size={26} />
    <div>松手导入</div>
  </div>
{/if}

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
    padding: 20px 26px;
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 10px;
    font-size: 12.5px;
  }
  .overlay-card.error {
    color: #ff453a;
  }
  .hint {
    color: var(--text-3);
    font-size: 11.5px;
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
    gap: 8px;
    color: var(--accent);
    font-size: 15px;
    font-weight: 500;
    z-index: 300;
    pointer-events: none;
  }

  .toast {
    position: fixed;
    left: 50%;
    bottom: 44px;
    transform: translateX(-50%);
    background: rgba(30, 30, 32, 0.94);
    color: #fff;
    font-size: 12.5px;
    padding: 8px 14px;
    border-radius: 9px;
    box-shadow: var(--shadow-pop);
    z-index: 250;
    max-width: 70vw;
    text-align: center;
  }
  .toast.warn {
    background: rgba(120, 74, 0, 0.96);
  }
  .toast.error {
    background: rgba(140, 30, 26, 0.96);
  }
</style>
