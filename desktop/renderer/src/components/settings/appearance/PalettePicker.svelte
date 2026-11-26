<script lang="ts">
  /**
   * 界面配色：六套双模色板，点一下立即生效。
   *
   * 设计口径（第二阶段 Batch 3）：
   * - **一张卡只预览一套色板**，缩略图跟随当前明暗显示该色板的 light 或 dark；
   *   切昼夜时六张卡一起翻到另一面，而不是每张卡同时塞两套色（那会变成十二块彩色）。
   * - 缩略图只用四个基色（canvas / paper / surface / ink）+ 一个强调色，色相只在
   *   那一枚小按钮和侧栏游标上出现——「无多余彩色杂音」。
   * - 颜色全部来自 `PALETTES` 注册表，组件不写死色值；注册表与 app.css 由
   *   `theme-preview.test.mjs` 对账。
   */
  import Icon from '../../Icon.svelte';
  import {
    PALETTES,
    paletteShot,
    type PaletteId,
    type PaletteShot,
    type ThemeId,
  } from '../../../lib/themes';

  let {
    current,
    resolved,
    onselect,
  }: {
    current: PaletteId;
    resolved: ThemeId;
    onselect: (id: PaletteId) => void;
  } = $props();

  const cards = $derived(
    PALETTES.map((palette) => ({
      ...palette,
      shot: paletteShot(palette.id, resolved),
    })),
  );

  function shotStyle(shot: PaletteShot): string {
    return [
      `--shot-canvas:${shot.canvas}`,
      `--shot-paper:${shot.paper}`,
      `--shot-card:${shot.card}`,
      `--shot-ink:${shot.ink}`,
      `--shot-accent:${shot.accent}`,
      `--shot-rule:${shot.rule}`,
    ].join(';');
  }
</script>

<div class="palette-grid" role="group" aria-label="界面配色">
  {#each cards as card (card.id)}
    <button
      class="palette-card"
      class:on={current === card.id}
      type="button"
      aria-pressed={current === card.id}
      aria-label={`界面配色：${card.name}。${card.note}`}
      onclick={() => onselect(card.id)}
    >
      <span class="shot" style={shotStyle(card.shot)} aria-hidden="true">
        <span class="shot-rail">
          <i class="rail-line accent"></i>
          <i class="rail-line"></i>
          <i class="rail-line"></i>
        </span>
        <span class="shot-body">
          <i class="shot-title"></i>
          <span class="shot-card">
            <i class="shot-bar"></i>
            <i class="shot-line"></i>
            <i class="shot-line short"></i>
            <i class="shot-btn"></i>
          </span>
        </span>
      </span>
      <span class="card-meta">
        <span class="card-name">{card.name}</span>
        {#if current === card.id}
          <span class="card-check"><Icon name="check" size={12} /></span>
        {/if}
      </span>
    </button>
  {/each}
</div>

<style>
  .palette-grid {
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: var(--sp-3);
  }
  @media (max-width: 1120px) {
    .palette-grid {
      grid-template-columns: repeat(2, minmax(0, 1fr));
    }
  }
  @media (max-width: 860px) {
    .palette-grid {
      grid-template-columns: minmax(0, 1fr);
    }
  }

  /* 未选中 = 台面上一块凹陷填充；选中才加 1px 强调须。与外观卡同一语法。 */
  .palette-card {
    appearance: none;
    text-align: left;
    font: inherit;
    padding: var(--sp-2);
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
  .palette-card:hover {
    background: var(--well-hover);
  }
  .palette-card.on {
    border-color: var(--accent-line);
    background: var(--accent-soft);
  }

  /* 迷你窗口：颜色全部来自 --shot-*，与当前界面令牌无关，六张卡才能并排比较。 */
  .shot {
    --shot-gap: 3px;
    --shot-pad: 6px;
    display: flex;
    height: 76px;
    border-radius: var(--rad-shot);
    overflow: hidden;
    border: 1px solid var(--shot-rule);
    background: var(--shot-canvas);
  }
  .shot-rail {
    width: 30px;
    flex: 0 0 30px;
    background: var(--shot-paper);
    border-right: 1px solid var(--shot-rule);
    padding: 5px var(--sp-1);
    display: flex;
    flex-direction: column;
    gap: var(--shot-gap);
  }
  .rail-line {
    display: block;
    height: 3px;
    border-radius: 2px;
    background: var(--shot-ink);
    opacity: 0.18;
  }
  .rail-line.accent {
    background: var(--shot-accent);
    opacity: 0.85;
  }
  .shot-body {
    flex: 1;
    min-width: 0;
    background: var(--shot-paper);
    padding: var(--shot-pad);
    display: flex;
    flex-direction: column;
    gap: var(--sp-1);
  }
  .shot-title {
    display: block;
    height: 4px;
    width: 38%;
    border-radius: 2px;
    background: var(--shot-ink);
    opacity: 0.45;
  }
  .shot-card {
    flex: 1;
    border-radius: 3px;
    background: var(--shot-card);
    border: 1px solid var(--shot-rule);
    padding: 5px;
    display: flex;
    flex-direction: column;
    gap: var(--shot-gap);
    min-width: 0;
  }
  .shot-bar {
    display: block;
    height: 3px;
    width: 52%;
    border-radius: 2px;
    background: var(--shot-accent);
    opacity: 0.8;
  }
  .shot-line {
    display: block;
    height: 2px;
    width: 76%;
    border-radius: 1px;
    background: var(--shot-ink);
    opacity: 0.22;
  }
  .shot-line.short {
    width: 58%;
  }
  .shot-btn {
    display: block;
    margin-top: auto;
    height: 7px;
    width: 22px;
    border-radius: 2px;
    background: var(--shot-accent);
  }

  .card-meta {
    display: flex;
    align-items: center;
    gap: var(--sp-2);
    padding: 0 var(--sp-1) var(--sp-1);
  }
  .card-name {
    font-size: var(--fs-ui);
    font-weight: 600;
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .card-check {
    margin-left: auto;
    color: var(--accent);
    flex: 0 0 auto;
  }
</style>
