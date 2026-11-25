<script lang="ts">
  /**
   * 字幕字体：黑体 / 明朝。
   *
   * 和明暗正交：换它只改 `--font-cue`，配色 / 字号 / 行高 / 密度都不动。
   * 每张卡都**用该字体自己**渲一句示例字幕——否则两个选项长得一模一样。
   */
  import Icon from '../../Icon.svelte';
  import { CUE_FONTS, THEME_PREVIEW_CUE, type CueFontId } from '../../../lib/themes';

  let {
    current,
    onselect,
  }: {
    current: CueFontId;
    onselect: (id: CueFontId) => void;
  } = $props();

  /** 示例行必须按「选项自己的字体」渲染，不能读当前偏好。 */
  function fontOf(id: CueFontId): string {
    return id === 'mincho' ? 'var(--font-cue-mincho)' : 'var(--font-sans)';
  }
</script>

<div class="cue-fonts" role="group" aria-label="字幕字体">
  {#each CUE_FONTS as font (font.id)}
    <button
      class="font-card"
      class:on={current === font.id}
      type="button"
      aria-pressed={current === font.id}
      onclick={() => onselect(font.id)}
    >
      <span class="sample" style={`font-family:${fontOf(font.id)}`} aria-hidden="true">
        {THEME_PREVIEW_CUE}
      </span>
      <span class="font-meta">
        <span class="font-copy">
          <span class="font-name">{font.name}</span>
          <span class="font-note">{font.note}</span>
        </span>
        {#if current === font.id}
          <span class="font-check"><Icon name="check" size={13} /></span>
        {/if}
      </span>
    </button>
  {/each}
</div>

<style>
  .cue-fonts {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: var(--sp-3);
  }
  @media (max-width: 860px) {
    .cue-fonts {
      grid-template-columns: minmax(0, 1fr);
    }
  }

  .font-card {
    appearance: none;
    text-align: left;
    font: inherit;
    padding: var(--sp-3);
    border-radius: var(--rad-card);
    border: 1px solid transparent;
    background: var(--well);
    display: flex;
    flex-direction: column;
    gap: var(--sp-2);
    min-width: 0;
    transition:
      border-color var(--dur) var(--ease),
      background var(--dur) var(--ease);
  }
  .font-card:hover {
    background: var(--well-hover);
  }
  .font-card.on {
    border-color: var(--accent-line);
    background: var(--accent-soft);
  }
  .sample {
    font-size: 17px;
    line-height: 26px;
    color: var(--text);
    letter-spacing: 0.01em;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .font-meta {
    display: flex;
    align-items: flex-start;
    gap: var(--sp-2);
  }
  .font-copy {
    min-width: 0;
    display: flex;
    flex-direction: column;
    gap: 1px;
  }
  .font-name {
    font-size: var(--fs-ui);
    font-weight: 600;
  }
  .font-note {
    font-size: 11px;
    line-height: 1.45;
    color: var(--text-3);
  }
  .font-check {
    margin-left: auto;
    color: var(--accent);
    flex: 0 0 auto;
  }
</style>
