<script lang="ts">
  /**
   * 三张主题缩略图：点卡即切（青空浅 / 青空深 / 明朝墨）。
   *
   * 「明暗」不再是独立的一行控件——它变成青空的两张卡，选哪张就同时定了皮肤与明暗；
   * 明朝墨只有浅色，所以它只有一张。这样用户不需要先懂「皮肤 / 明暗」两层概念。
   */
  import ThemePreviewCard from './ThemePreviewCard.svelte';
  import { THEME_PREVIEWS, type ThemeId } from '../../../lib/themes';

  let {
    current,
    onselect,
  }: {
    current: ThemeId;
    onselect: (id: ThemeId) => void;
  } = $props();
</script>

<div class="theme-grid">
  {#each THEME_PREVIEWS as preview (preview.id)}
    <ThemePreviewCard {preview} selected={current === preview.id} onselect={() => onselect(preview.id)} />
  {/each}
</div>

<style>
  .theme-grid {
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: var(--sp-4);
  }
  @container sheet (max-width: 560px) {
    .theme-grid {
      grid-template-columns: repeat(2, minmax(0, 1fr));
    }
  }
  @container sheet (max-width: 440px) {
    .theme-grid {
      grid-template-columns: minmax(0, 1fr);
    }
  }
</style>
