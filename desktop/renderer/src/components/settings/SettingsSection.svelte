<script lang="ts">
  /**
   * 设置页的分区外壳：标题 + 口径说明 + 右侧统计 + 内容。
   *
   * `layout='grid2'` 时内容排成两列 Bento（引擎页）；其余页签用 `block`。
   * 四个页签的分区头只保留这一份实现，不再各写一套（`style-drift` 里
   * `.sec / .sec-head` 被重复定义的老问题就是这么来的）。
   */
  import type { Snippet } from 'svelte';

  let {
    title,
    caption = '',
    meta = '',
    layout = 'block',
    children,
  }: {
    title: string;
    caption?: string;
    meta?: string;
    layout?: 'block' | 'grid2';
    children: Snippet;
  } = $props();
</script>

<section class="set-section">
  <div class="set-section-head">
    <div class="set-section-copy">
      <h2 class="set-section-title">{title}</h2>
      {#if caption}
        <p class="set-section-caption">{caption}</p>
      {/if}
    </div>
    {#if meta}
      <span class="set-section-meta">{meta}</span>
    {/if}
  </div>
  {#if layout === 'grid2'}
    <div class="set-section-grid">
      {@render children()}
    </div>
  {:else}
    {@render children()}
  {/if}
</section>

<style>
  .set-section-head {
    display: flex;
    align-items: flex-end;
    gap: var(--sp-3);
    margin-bottom: var(--sp-3);
  }
  .set-section-copy {
    min-width: 0;
  }
  .set-section-title {
    margin: 0;
    font-size: var(--fs-heading);
    line-height: var(--lh-heading);
    font-weight: 600;
  }
  /* 分区说明：解释这一块是干什么的，属于解释性正文 → 13/19 + --ink-2。 */
  .set-section-caption {
    margin: 2px 0 0;
    font-size: var(--fs-ui);
    line-height: 19px;
    color: var(--ink-2);
    max-width: 620px;
  }
  .set-section-meta {
    margin-left: auto;
    font-size: var(--fs-label);
    color: var(--text-3);
    white-space: nowrap;
    flex: 0 0 auto;
  }
  .set-section-grid {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: var(--sp-4);
  }
  @media (max-width: 1120px) {
    .set-section-grid {
      grid-template-columns: minmax(0, 1fr);
    }
  }
</style>
