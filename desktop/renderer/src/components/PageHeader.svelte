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
     这一版再往前一步：页头按钮统一成**有轮廓的次级键**（纸白填充 + 1px 发丝边），
     因为用户第二次报障说的是同一个病更严重的一面——
     「任务报告 / 快捷键」用 5% 灰底时对比度太低，看着像不可点（2026-11-26）。

     为什么不再用「淡灰填充」：灰底落在浅色色板（catppuccin / cobalt）的纸白页面上
     正是 DESIGN.md 明令禁止的「灰底白框」；改成**纸白键 + `--btn-line` 细边**后，
     它在白底上靠那道边读成「一颗键」，在深色台面上靠 `--raise-bevel` 顶高光读成同一件事。 */
  .page-actions :global(.btn.ghost) {
    background: var(--raise);
    border-color: var(--btn-line);
    color: var(--text-2);
    box-shadow: var(--raise-bevel);
  }
  .page-actions :global(.btn.ghost:hover:not(:disabled)) {
    background: var(--raise);
    border-color: var(--btn-line-hover);
    color: var(--text);
  }
  .page-actions :global(.btn.ghost:disabled) {
    background: var(--fill);
    border-color: transparent;
    color: var(--ink-muted);
  }
  /* 页头的图标按钮与文字按钮同一高度、同一轮廓：标题右侧那一排是「功能入口」，
     不是一排图标贴纸。 */
  .page-actions :global(.btn.icon) {
    width: var(--ctl-h);
    padding: 0;
    justify-content: center;
  }
  .page-actions {
    display: flex;
    align-items: center;
    gap: var(--sp-2);
    flex: 0 0 auto;
    padding-top: 3px;
  }
</style>
