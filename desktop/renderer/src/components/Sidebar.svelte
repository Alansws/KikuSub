<script lang="ts">
  import Icon from './Icon.svelte';
  import SidebarToggle from './SidebarToggle.svelte';
  import { app, setView, type View } from '../lib/store.svelte';
  import { sidebarPrefs } from '../lib/sidebarPrefs.svelte';
  import { dual } from '../lib/dualReview.svelte';
  import appIcon from '../assets/app-icon.png';

  interface NavItem {
    view: View;
    icon: string;
    label: string;
    key: string;
  }

  /**
   * 按「工作心智」分四段，而不是八条平级步骤（2026-11-21 去噪）：
   * 准备（导入 / 转写）→ 核对（核对台 / 双引擎复核）→ AI 处理（润色 / 断句重排 / 翻译）
   * → 交付（导出）。分组只加视觉分隔，不改路由。
   *
   * **段内顺序必须保持不变**：`⌘1..⌘8` 与这张表一一对应（见 lib/shortcuts.svelte.ts），
   * 主进程「视图」菜单也是这个顺序；调顺序等于把快捷键和菜单一起打乱。
   * 所以 AI 处理段里仍是 润色(⌘5) / 断句重排(⌘6) / 翻译(⌘7)，不是按拼音重排。
   */
  const nav: { group: string; items: NavItem[] }[] = [
    {
      group: '准备',
      items: [
        { view: 'import', icon: 'tray', label: '导入', key: '⌘1' },
        { view: 'transcribe', icon: 'wave', label: '转写', key: '⌘2' },
      ],
    },
    {
      group: '核对',
      items: [
        { view: 'review', icon: 'listcheck', label: '核对台', key: '⌘3' },
        { view: 'dual', icon: 'rows', label: '双引擎复核', key: '⌘4' },
      ],
    },
    {
      group: 'AI 处理',
      items: [
        { view: 'polish', icon: 'sparkle', label: '润色', key: '⌘5' },
        { view: 'reshape', icon: 'split', label: '断句重排', key: '⌘6' },
        { view: 'translate', icon: 'quote', label: '翻译', key: '⌘7' },
      ],
    },
    {
      group: '交付',
      items: [{ view: 'export', icon: 'export', label: '导出', key: '⌘8' }],
    },
  ];
</script>

<aside class="sidebar" class:collapsed={sidebarPrefs.collapsed}>
  <!-- 展开态的折叠开关贴在红绿灯留白区右侧；收起态它移到顶栏
       （52px 里红绿灯占掉 x19–71，开关放在这里会被压在红绿灯上）。 -->
  {#if !sidebarPrefs.collapsed}
    <SidebarToggle floating />
  {/if}

  <div class="sb-brand" aria-label="KikuSub 字幕工作台">
    <img class="brand-mark" src={appIcon} width="20" height="20" alt="" aria-hidden="true" />
    <span class="brand-text">
      <span class="brand-name">KikuSub</span>
      <span class="brand-sub">字幕工作台</span>
    </span>
  </div>

  {#each nav as section, index (section.group)}
    <div class="sb-label" class:lead={index === 0}>{section.group}</div>
    {#each section.items as item (item.view)}
      <button
        class="sb-item"
        class:active={app.view === item.view}
        onclick={() => setView(item.view)}
        title={`${item.label}（${item.key}）`}
        aria-label={`${item.label}（${item.key}）`}
      >
        <span class="ico"><Icon name={item.icon} /></span>
        <span>{item.label}</span>
        {#if item.view === 'review' && app.cues.length}
          <span class="sb-count">{app.cues.length}</span>
        {:else if item.view === 'dual' && dual.exists}
          <span class="sb-count alt" title="文本差异行数（+ / − 漏句在页内单独显示）">
            {dual.stats?.badge ?? 0}
          </span>
        {/if}
      </button>
    {/each}
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
    title="设置：引擎与模型、文件夹路径、日志与诊断（⌘,）"
    aria-label="设置（⌘,）"
  >
    <span class="ico"><Icon name="gear" /></span>
    <span>设置</span>
    <kbd class="sb-key" aria-hidden="true">⌘,</kbd>
  </button>

</aside>

<style>
  .sb-brand {
    display: flex;
    align-items: center;
    gap: var(--sp-2);
    padding: var(--sp-1) var(--sp-2) 14px;
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
  /* 分组标签是「分隔」而不是「标题」：比导航正文更小更淡，读起来不抢行。
     第一段贴着品牌标，上边距要比后续分段小。 */
  .sb-label {
    font-size: 11px;
    font-weight: 600;
    color: var(--text-3);
    letter-spacing: 0.06em;
    padding: 16px var(--sp-2) 5px;
  }
  .sb-label.lead {
    padding-top: 6px;
  }

  .sb-item {
    appearance: none;
    border: 0;
    background: transparent;
    height: 30px;
    display: flex;
    align-items: center;
    gap: var(--sp-2);
    padding: 0 var(--sp-2);
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
  /* 选中态只有一层柔和强调色底（2026-11-21 去噪）：去掉外圈 2px 朱红左线，
     全站与设置页 / 核对台保持一致，侧栏不再像「八条带边框的步骤」。 */
  .sb-item.active {
    background: var(--accent-soft);
    color: var(--accent);
    font-weight: 500;
  }
  /* 键盘焦点用内侧细环：全局 2px 外描边套在浅底选中项外面会读成「报错框」，
     内侧环（accent-ring）既去掉外圈朱红框，又保住键盘用户看得见焦点。 */
  .sb-item:focus-visible {
    outline: 2px solid var(--accent-ring);
    outline-offset: -2px;
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
  .sb-count.alt {
    min-width: 17px;
    padding: 0 5px;
    border-radius: 999px;
    background: var(--accent-soft);
    color: var(--accent);
    text-align: center;
  }

  .sb-spacer {
    flex: 1;
  }

  /* 设置项的固定快捷键提示：⌘, 是 macOS 惯例，不属于可自定义表。 */
  .sb-key {
    margin-left: auto;
    flex: 0 0 auto;
    font-family: var(--font-sans);
    font-size: 11.5px;
    line-height: 16px;
    color: var(--text-3);
    letter-spacing: 0.02em;
    font-variant-numeric: tabular-nums;
  }
  .sb-item.active .sb-key {
    color: var(--accent);
  }

  /* 紧凑模式（≤900px）：56px 图标轨。标签的显隐在 app.css（全局骨架）里，
     品牌文字在这里收起——组件样式排在 app.css 之后，同一份规则放这里才生效。 */
  @media (max-width: 900px) {
    .sb-brand {
      justify-content: center;
      gap: 0;
      padding: var(--sp-1) 0 var(--sp-3);
    }
    .brand-name,
    .brand-sub {
      display: none;
    }
    .sb-key {
      display: none;
    }
  }
</style>
