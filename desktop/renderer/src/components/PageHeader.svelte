<script lang="ts">
  import type { Snippet } from 'svelte';

  /**
   * 统一页头：一个页面只有一个 22px 标题，说明 14px，
   * 右侧动作与标题同一基线。页面宽度由各视图根容器决定（720 / 960 / 1120）。
   */
  let {
    title,
    subtitle = '',
    children,
  }: { title: string; subtitle?: string; children?: Snippet } = $props();
</script>

<header class="page-head">
  <div class="page-head-row">
    <div class="page-head-copy">
      <h1 class="page-title">{title}</h1>
      {#if subtitle}
        <p class="page-sub">{subtitle}</p>
      {/if}
    </div>
    {#if children}
      <div class="page-actions">{@render children()}</div>
    {/if}
  </div>
</header>

<style>
  .page-head {
    margin: 0 0 28px;
  }
  .page-head-row {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: var(--sp-5);
  }
  .page-head-copy {
    min-width: 0;
  }
  .page-title {
    margin: 0;
    font-size: var(--fs-display);
    line-height: var(--lh-display);
    font-weight: 600;
    letter-spacing: -0.015em;
    color: var(--text);
  }
  .page-sub {
    margin: 6px 0 0;
    max-width: 680px;
    font-size: var(--fs-body);
    line-height: var(--lh-body);
    color: var(--text-2);
  }
  /* 页头动作是「次级按钮」，不是一段裸链接：
     纸白台面上透明底的 ghost 只剩一行蓝/灰字，看起来像飘在行末的链接
     （2026-11-26 真机报障：「去双语翻译」「去转写页」都是这个病）。
     这里只给页头这一层加淡填充，标题栏里的图标 ghost 仍然是透明的。 */
  .page-actions :global(.btn.ghost) {
    background: var(--well);
    color: var(--text-2);
  }
  .page-actions :global(.btn.ghost:hover:not(:disabled)) {
    background: var(--well-hover);
    color: var(--text);
  }
  .page-actions {
    display: flex;
    align-items: center;
    gap: var(--sp-2);
    flex: 0 0 auto;
    padding-top: 3px;
  }
</style>
