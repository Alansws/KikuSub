<script lang="ts">
  /**
   * 提案的三个低频操作（重新加载 / 另存 / 丢弃）。
   *
   * 润色页与翻译页各写过一份一模一样的「⋯」菜单；抽出来后两页的顶栏只剩
   * 来源徽标与计数，也保证「丢弃」这类危险动作在两边长得一样、位置一样。
   */
  let {
    loading = false,
    generating = false,
    saving = false,
    onReload,
    onSaveAs,
    onDiscard,
  }: {
    loading?: boolean;
    generating?: boolean;
    saving?: boolean;
    onReload: () => void;
    onSaveAs: () => void;
    onDiscard: () => void;
  } = $props();

  let open = $state(false);
</script>

<div class="aiw-menu-wrap">
  <button
    class="aiw-icon-btn"
    onclick={() => (open = !open)}
    title="更多操作"
    aria-label="更多操作"
    aria-expanded={open}
  >⋯</button>
  {#if open}
    <button class="aiw-menu-backdrop" aria-label="关闭菜单" onclick={() => (open = false)}></button>
    <div class="aiw-menu" role="menu">
      <button
        role="menuitem"
        onclick={() => {
          open = false;
          onReload();
        }}
        disabled={loading || generating}
      >重新加载</button>
      <button
        role="menuitem"
        onclick={() => {
          open = false;
          onSaveAs();
        }}
        disabled={saving}
      >另存…</button>
      <button
        class="danger"
        role="menuitem"
        onclick={() => {
          open = false;
          onDiscard();
        }}
      >丢弃</button>
    </div>
  {/if}
</div>
