<script lang="ts">
  /**
   * 顶部引擎切换：胶囊只显示当前引擎，点开是一个可滚动的引擎列表。
   *
   * 为什么不用平铺分段：接下来会到 3–4 个引擎，全部平铺会挤占工具栏；
   * 胶囊给当前引擎一个稳定位置，列表给每个引擎留出「用途 + 就绪状态 + 体积」。
   */
  import Icon from './Icon.svelte';
  import type { EngineInfo } from '../lib/api';
  import { formatBytes } from '../lib/time';

  let {
    engine = $bindable('whisper'),
    engines = [],
    onmanage,
  }: {
    engine?: string;
    engines?: EngineInfo[];
    onmanage?: () => void;
  } = $props();

  let open = $state(false);
  let capsuleEl = $state<HTMLButtonElement | null>(null);
  let menuEl = $state<HTMLDivElement | null>(null);

  const current = $derived(engines.find((item) => item.key === engine) ?? engines[0] ?? null);
  const currentLabel = $derived(current?.short_label || current?.label || '选择引擎');

  function meta(item: EngineInfo): string {
    if (!item.installed) return item.approx_label;
    return item.size_bytes > 0 ? formatBytes(item.size_bytes) : '已安装';
  }

  function close(focusCapsule = false) {
    open = false;
    if (focusCapsule) capsuleEl?.focus();
  }

  function choose(key: string) {
    engine = key;
    close(true);
  }

  function manage() {
    close();
    onmanage?.();
  }

  function onMenuKeydown(event: KeyboardEvent) {
    if (event.key === 'Escape') {
      event.preventDefault();
      close(true);
      return;
    }
    if (event.key !== 'ArrowDown' && event.key !== 'ArrowUp') return;
    event.preventDefault();
    const items = Array.from(
      menuEl?.querySelectorAll<HTMLButtonElement>('.ec-item') ?? [],
    );
    if (!items.length) return;
    const index = items.indexOf(document.activeElement as HTMLButtonElement);
    const next =
      event.key === 'ArrowDown'
        ? (index + 1 + items.length) % items.length
        : (index - 1 + items.length) % items.length;
    items[next]?.focus();
  }

  // 打开后把焦点放到当前引擎上，键盘用户可以直接上下选。
  $effect(() => {
    if (!open) return;
    const frame = requestAnimationFrame(() => {
      const active = menuEl?.querySelector<HTMLButtonElement>('.ec-item.on');
      const first = menuEl?.querySelector<HTMLButtonElement>('.ec-item');
      (active ?? first)?.focus();
    });
    return () => cancelAnimationFrame(frame);
  });
</script>

<div class="engine-switch">
  <button
    bind:this={capsuleEl}
    class="ec"
    class:open
    aria-haspopup="listbox"
    aria-expanded={open}
    title={current ? `${current.label} · ${current.purpose}` : '选择识别引擎'}
    onclick={() => (open = !open)}
    onkeydown={(event) => {
      if (event.key === 'Escape' && open) {
        event.preventDefault();
        close(true);
      } else if (event.key === 'ArrowDown' && !open) {
        event.preventDefault();
        open = true;
      }
    }}
  >
    <span class="ec-dot" class:ready={current?.installed}></span>
    <span class="ec-name">{currentLabel}</span>
    <span class="ec-purpose">{current?.purpose ?? ''}</span>
    <span class="ec-chevron"><Icon name="chevron-down" size={11} /></span>
  </button>

  {#if open}
    <button
      class="ec-backdrop"
      tabindex="-1"
      aria-label="关闭引擎菜单"
      onclick={() => close()}
    ></button>
    <div
      class="ec-menu"
      role="listbox"
      aria-label="识别引擎"
      tabindex="-1"
      bind:this={menuEl}
      onkeydown={onMenuKeydown}
    >
      <div class="ec-head">
        <span>识别引擎</span>
        <button class="ec-manage" onclick={manage}>管理…</button>
      </div>
      <div class="ec-list">
        {#each engines as item (item.key)}
          <button
            class="ec-item"
            class:on={engine === item.key}
            role="option"
            aria-selected={engine === item.key}
            onclick={() => choose(item.key)}
            title={item.description}
          >
            <span class="ec-item-dot" class:ready={item.installed}></span>
            <span class="ec-item-main">
              <span class="ec-item-name">{item.label}</span>
              <span class="ec-item-purpose">{item.purpose}</span>
            </span>
            <span class="ec-item-meta">{meta(item)}</span>
            <span class="ec-item-check">
              {#if engine === item.key}<Icon name="check" size={11} />{/if}
            </span>
          </button>
        {/each}
      </div>
      <div class="ec-foot">启用的引擎会出现在这里；可在设置里调整</div>
    </div>
  {/if}
</div>

<style>
  .engine-switch {
    position: relative;
    display: flex;
    align-items: center;
    flex: 0 0 auto;
    /* 工具栏整条是窗口拖动区。Svelte 的作用域哈希让 Toolbar 里的
       `.toolbar > *` 匹配不到子组件根节点，必须在这里自己声明可点击，
       否则整个引擎胶囊会被系统当成拖窗区域，点击被吞掉。 */
    -webkit-app-region: no-drag;
  }

  .ec {
    appearance: none;
    height: 30px;
    display: flex;
    align-items: center;
    gap: 7px;
    padding: 0 8px 0 9px;
    border: 1px solid var(--separator-soft);
    border-radius: 8px;
    background: var(--fill);
    color: var(--text);
    font: inherit;
    cursor: default;
    transition:
      border-color var(--dur) var(--ease),
      background var(--dur) var(--ease),
      box-shadow var(--dur) var(--ease);
  }
  .ec:hover {
    border-color: var(--accent-line);
    background: var(--accent-soft);
  }
  .ec.open {
    border-color: var(--accent-ring);
    background: var(--accent-soft);
    box-shadow: 0 0 0 3px var(--accent-soft);
  }
  .ec-dot,
  .ec-item-dot {
    width: 6px;
    height: 6px;
    border-radius: 50%;
    flex: 0 0 6px;
    background: var(--warn);
    box-shadow: 0 0 0 2px var(--warn-soft);
  }
  .ec-dot.ready,
  .ec-item-dot.ready {
    background: var(--success);
    box-shadow: 0 0 0 2px var(--success-soft);
  }
  .ec-name {
    font-size: 12.5px;
    font-weight: 600;
    line-height: 16px;
    white-space: nowrap;
  }
  .ec-purpose {
    max-width: 148px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    font-size: 11px;
    color: var(--text-3);
  }
  .ec-chevron {
    color: var(--text-3);
    display: grid;
    place-items: center;
    transition: transform 160ms var(--ease), color var(--dur) var(--ease);
  }
  .ec.open .ec-chevron {
    transform: rotate(180deg);
    color: var(--accent);
  }

  .ec-backdrop {
    position: fixed;
    inset: 0;
    z-index: 60;
    border: 0;
    padding: 0;
    background: transparent;
    cursor: default;
    -webkit-app-region: no-drag;
  }

  .ec-menu {
    position: absolute;
    top: calc(100% + 7px);
    left: 0;
    z-index: 61;
    width: min(340px, calc(100vw - 36px));
    max-height: min(440px, 66vh);
    display: flex;
    flex-direction: column;
    overflow: hidden;
    padding: 4px;
    background: var(--raise);
    border: 1px solid var(--line);
    border-radius: 10px;
    box-shadow: var(--shadow-pop);
    -webkit-app-region: no-drag;
    animation: ecMenuIn 140ms var(--ease);
  }
  @keyframes ecMenuIn {
    from {
      opacity: 0;
      transform: translateY(-3px);
    }
  }

  .ec-head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 8px;
    padding: 6px 7px 7px;
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 0.04em;
    color: var(--text-3);
    text-transform: uppercase;
  }
  .ec-manage {
    appearance: none;
    border: 0;
    background: transparent;
    color: var(--accent);
    font: inherit;
    font-size: 11px;
    letter-spacing: 0;
    text-transform: none;
    padding: 2px 4px;
    border-radius: 4px;
    cursor: default;
  }
  .ec-manage:hover {
    background: var(--accent-soft);
  }

  .ec-list {
    display: flex;
    flex-direction: column;
    gap: 1px;
    overflow-y: auto;
    flex: 1 1 auto;
    min-height: 0;
  }
  .ec-item {
    appearance: none;
    border: 0;
    background: transparent;
    color: var(--text);
    font: inherit;
    width: 100%;
    min-height: 44px;
    display: flex;
    align-items: center;
    gap: 9px;
    padding: 6px 8px;
    border-radius: 7px;
    text-align: left;
    cursor: default;
  }
  .ec-item:hover {
    background: var(--row-hover);
  }
  .ec-item.on {
    background: var(--accent-soft);
  }
  .ec-item-main {
    display: flex;
    flex-direction: column;
    gap: 1px;
    flex: 1;
    min-width: 0;
  }
  .ec-item-name {
    font-size: 12.5px;
    font-weight: 500;
    line-height: 16px;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .ec-item.on .ec-item-name {
    color: var(--accent);
    font-weight: 600;
  }
  .ec-item-purpose {
    font-size: 11px;
    line-height: 14px;
    color: var(--text-3);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .ec-item-meta {
    flex: 0 0 auto;
    font-size: 10.5px;
    color: var(--text-3);
    font-variant-numeric: tabular-nums;
    white-space: nowrap;
  }
  .ec-item-check {
    width: 14px;
    flex: 0 0 14px;
    display: grid;
    place-items: center;
    color: var(--accent);
  }

  .ec-foot {
    padding: 7px 8px 5px;
    margin-top: 3px;
    border-top: 1px solid var(--separator-soft);
    font-size: 11px;
    line-height: 15px;
    color: var(--text-3);
  }

  @media (max-width: 1180px) {
    .ec-purpose {
      display: none;
    }
  }
  @media (prefers-reduced-motion: reduce) {
    .ec-chevron,
    .ec,
    .ec-menu {
      transition: none;
      animation: none;
    }
  }
</style>
