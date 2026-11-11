<script lang="ts">
  import Icon from './Icon.svelte';
  import { app, setView, type View } from '../lib/store.svelte';
  import appIcon from '../assets/app-icon.png';

  const items: { view: View; icon: string; label: string }[] = [
    { view: 'import', icon: 'tray', label: '导入' },
    { view: 'transcribe', icon: 'wave', label: '转写' },
    { view: 'review', icon: 'listcheck', label: '核对' },
    { view: 'ai', icon: 'sparkle', label: 'AI 优化' },
    { view: 'export', icon: 'export', label: '导出' },
  ];
</script>

<aside class="sidebar">
  <div class="sb-brand" aria-label="KikuSub 字幕工作台">
    <img class="brand-mark" src={appIcon} width="20" height="20" alt="" aria-hidden="true" />
    <span>
      <span class="brand-name">KikuSub</span>
      <span class="brand-sub">字幕工作台</span>
    </span>
  </div>

  <div class="sb-label">工作区</div>

  {#each items as item (item.view)}
    <button
      class="sb-item"
      class:active={app.view === item.view}
      onclick={() => setView(item.view)}
      title={item.label}
      aria-label={item.label}
    >
      <span class="ico"><Icon name={item.icon} /></span>
      <span>{item.label}</span>
      {#if item.view === 'review' && app.cues.length}
        <span class="sb-count">{app.cues.length}</span>
      {/if}
    </button>
  {/each}

  <div class="sb-spacer"></div>


  <button
    class="sb-item"
    class:active={app.view === 'prompts'}
    onclick={() => setView('prompts')}
    title="提示词库：选中、编辑并复制翻译提示词"
    aria-label="提示词库"
  >
    <span class="ico"><Icon name="quote" /></span>
    <span>提示词库</span>
  </button>

  <button
    class="sb-item"
    class:active={app.view === 'settings'}
    onclick={() => setView('settings')}
    title="设置：引擎与模型、文件夹路径、日志与诊断"
    aria-label="设置"
  >
    <span class="ico"><Icon name="gear" /></span>
    <span>设置</span>
  </button>

</aside>

<style>
  .sb-brand {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 4px 8px 14px;
    color: var(--text);
  }
  .brand-mark {
    display: block;
    width: 20px;
    height: 20px;
    flex: 0 0 20px;
    border-radius: 5px;
    overflow: hidden;
    user-select: none;
    -webkit-user-drag: none;
  }
  .brand-name {
    display: block;
    font-size: 13px;
    font-weight: 600;
    letter-spacing: 0.01em;
  }
  .brand-sub {
    display: block;
    font-size: 12px;
    color: var(--text-3);
    margin-top: 1px;
  }
  .sb-label {
    font-size: 12px;
    font-weight: 600;
    color: var(--text-2);
    padding: 10px 8px 4px;
    letter-spacing: 0.02em;
  }

  .sb-item {
    appearance: none;
    border: 0;
    background: transparent;
    height: 30px;
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 0 8px;
    border-radius: var(--rad-control);
    color: var(--text);
    font: inherit;
    font-size: 13px;
    text-align: left;
    transition: background var(--dur) var(--ease);
    width: 100%;
  }
  .sb-item:hover {
    background: var(--fill);
  }
  .sb-item.active {
    background: var(--accent-soft);
    color: var(--accent);
    font-weight: 500;
    box-shadow: inset 2px 0 0 var(--accent);
  }
  .sb-item.active .ico {
    color: var(--accent);
  }
  .ico {
    width: 16px;
    height: 16px;
    flex: 0 0 16px;
    color: var(--text-2);
    display: grid;
    place-items: center;
  }

  .sb-count {
    margin-left: auto;
    font-size: 12px;
    color: var(--text-3);
    font-variant-numeric: tabular-nums;
  }
  .sb-item.active .sb-count {
    color: var(--accent);
  }

  .sb-spacer {
    flex: 1;
  }

  /* 紧凑模式（≤900px）：56px 图标轨。标签的显隐在 app.css（全局骨架）里，
     品牌文字在这里收起——组件样式排在 app.css 之后，同一份规则放这里才生效。 */
  @media (max-width: 900px) {
    .sb-brand {
      justify-content: center;
      gap: 0;
      padding: 4px 0 12px;
    }
    .brand-name,
    .brand-sub {
      display: none;
    }
  }
</style>
