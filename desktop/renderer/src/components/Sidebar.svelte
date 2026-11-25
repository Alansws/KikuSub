<script lang="ts">
  /**
   * 侧栏：四段导航（01 准备 / 02 核对 / 03 原文 / 04 交付）+ 底部工具页。
   *
   * 名字与分组来自 `lib/viewMeta.ts`——那里是唯一来源，标题栏面包屑、
   * 主进程菜单、快捷键面板都读同一份，避免「侧栏叫锁轴润色、菜单还叫润色」。
   *
   * 段内顺序与 ⌘1–⌘8 绑死，不按拼音重排。
   */
  import Icon from './Icon.svelte';
  import { app, setView } from '../lib/store.svelte';
  import { sidebarPrefs } from '../lib/sidebarPrefs.svelte';
  import { dual } from '../lib/dualReview.svelte';
  import { NAV_GROUPS, UTILITY_ITEMS } from '../lib/viewMeta';
  import appIcon from '../assets/app-icon.png';

  /** 右侧计数：只给「有东西可数」的两页，其余留空。 */
  function countOf(view: string): string {
    if (view === 'review' && app.cues.length) return String(app.cues.length);
    if (view === 'dual' && dual.exists) return String(dual.stats?.badge ?? 0);
    return '';
  }
</script>

<aside class="sidebar" class:collapsed={sidebarPrefs.collapsed}>
  <div class="sb-brand" aria-label="KikuSub 字幕工作台">
    <img class="brand-mark" src={appIcon} width="20" height="20" alt="" aria-hidden="true" />
    <span class="brand-text">
      <span class="brand-name">KikuSub</span>
      <span class="brand-sub">字幕工作台</span>
    </span>
  </div>

  <nav class="sb-nav" aria-label="工作阶段">
    {#each NAV_GROUPS as group (group.stage)}
      <div class="sb-group">
        <div class="sb-label">
          <span class="sb-num">{group.stage}</span>
          {group.label}
        </div>
        {#each group.items as item (item.view)}
          <button
            class="sb-item"
            class:active={app.view === item.view}
            onclick={() => setView(item.view)}
            title={item.key ? `${item.label}（${item.key}）` : item.label}
            aria-label={item.key ? `${item.label}（${item.key}）` : item.label}
            aria-current={app.view === item.view ? 'page' : undefined}
          >
            <span class="ico"><Icon name={item.icon} /></span>
            <span class="sb-text">
              {#if item.ordinal}<span class="sb-ord" aria-hidden="true">{item.ordinal}</span>{/if}
              {item.label}
            </span>
            {#if countOf(item.view)}
              <span
                class="sb-count"
                class:alt={item.view === 'dual'}
                title={item.view === 'dual' ? '文本差异行数（+ / − 漏句在页内单独显示）' : ''}
              >
                {countOf(item.view)}
              </span>
            {:else}
              <kbd class="sb-key" aria-hidden="true">{item.key}</kbd>
            {/if}
          </button>
        {/each}
      </div>
    {/each}
  </nav>

  <div class="sb-spacer"></div>

  <nav class="sb-foot" aria-label="工具">
    {#each UTILITY_ITEMS as item (item.view)}
      <button
        class="sb-item"
        class:active={app.view === item.view}
        onclick={() => setView(item.view)}
        title={item.key ? `${item.label}（${item.key}）` : item.label}
        aria-label={item.key ? `${item.label}（${item.key}）` : item.label}
        aria-current={app.view === item.view ? 'page' : undefined}
      >
        <span class="ico"><Icon name={item.icon} /></span>
        <span class="sb-text">{item.label}</span>
        <kbd class="sb-key" aria-hidden="true">{item.key}</kbd>
      </button>
    {/each}
  </nav>
</aside>

<style>
  .sb-brand {
    display: flex;
    align-items: center;
    gap: 9px;
    padding: var(--sp-1) var(--sp-2) var(--sp-4);
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
    font-size: 13.5px;
    font-weight: 650;
    letter-spacing: -0.01em;
    line-height: 1.1;
  }
  .brand-sub {
    display: block;
    font-size: 11px;
    color: var(--text-3);
    margin-top: 2px;
    letter-spacing: 0.02em;
  }

  .sb-nav {
    display: flex;
    flex-direction: column;
    min-height: 0;
    overflow-y: auto;
  }
  .sb-group + .sb-group {
    margin-top: var(--sp-3);
  }
  /* 段标是「分隔」不是「标题」：等宽小字 + 段号，读起来是一张任务表 */
  .sb-label {
    display: flex;
    align-items: center;
    gap: 7px;
    padding: 0 var(--sp-2) 6px;
    font-family: var(--font-mono);
    font-size: 11px;
    line-height: 16px;
    letter-spacing: 0.07em;
    color: var(--text-3);
    text-transform: uppercase;
  }
  .sb-num {
    color: var(--text-2);
    font-weight: 500;
  }

  .sb-item {
    appearance: none;
    border: 0;
    background: transparent;
    height: var(--row-h);
    width: 100%;
    display: flex;
    align-items: center;
    gap: 9px;
    padding: 0 var(--sp-2);
    border-radius: var(--rad-control);
    color: var(--text-2);
    font: inherit;
    font-size: 12.5px;
    text-align: left;
    transition:
      background var(--dur) var(--ease),
      color var(--dur) var(--ease);
  }
  .sb-item:hover {
    background: var(--fill);
    color: var(--text);
  }
  /* 选中：蓝铅笔 tint + 1px 边；不用单侧竖条，也不加阴影 */
  .sb-item.active {
    background: var(--accent-soft);
    color: var(--accent-text);
    box-shadow: inset 0 0 0 1px var(--accent-line);
    font-weight: 500;
  }
  .sb-item:focus-visible {
    outline: 2px solid var(--accent-ring);
    outline-offset: -2px;
  }
  .ico {
    width: 16px;
    height: 16px;
    flex: 0 0 16px;
    color: var(--text-3);
    display: grid;
    place-items: center;
  }
  .sb-item:hover .ico {
    color: var(--text-2);
  }
  .sb-item.active .ico {
    color: var(--accent);
  }
  .sb-text {
    flex: 1;
    min-width: 0;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  /* 段内编号（① 锁轴 / ② 重排）：11px 等宽、第三级文字色，跟在标签前当一个「页序」，
     不是徽标——它只说顺序，不抢激活态的蓝。 */
  .sb-ord {
    display: inline-block;
    margin-right: 4px;
    font-family: var(--font-mono);
    font-size: 11px;
    line-height: 16px;
    color: var(--text-3);
  }

  .sb-count {
    min-width: 16px;
    text-align: right;
    font-family: var(--font-mono);
    font-size: 11px;
    font-variant-numeric: tabular-nums;
    color: var(--text-3);
  }
  .sb-item.active .sb-count {
    color: var(--accent);
  }
  .sb-count.alt {
    min-width: 18px;
    padding: 0 5px;
    height: 16px;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    border-radius: 999px;
    background: var(--accent-soft);
    color: var(--accent);
  }

  /* 快捷键只在悬停/聚焦时出现，常驻会变成一片杂音 */
  .sb-key {
    font-family: var(--font-mono);
    font-size: 11px;
    line-height: 16px;
    color: var(--text-3);
    opacity: 0;
    flex: 0 0 auto;
  }
  .sb-item:hover .sb-key,
  .sb-item:focus-visible .sb-key {
    opacity: 1;
  }
  .sb-foot .sb-key {
    opacity: 1;
  }
  .sb-item.active .sb-key {
    color: var(--accent);
  }

  .sb-spacer {
    flex: 1;
    min-height: var(--sp-3);
  }
  .sb-foot {
    border-top: 1px solid var(--line);
    padding-top: var(--sp-2);
    display: flex;
    flex-direction: column;
    gap: 2px;
  }

  /* 紧凑模式（≤900px）：标签与快捷键的显隐在 app.css 统一处理，
     品牌文字这里收起——组件样式排在 app.css 之后，同一份规则放这里才生效。 */
  @media (max-width: 900px) {
    .sb-brand {
      justify-content: center;
      gap: 0;
      padding: var(--sp-2) 0 var(--sp-3);
    }
    .brand-name,
    .brand-sub,
    .sb-key {
      display: none;
    }
  }
</style>
