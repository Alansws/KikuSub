<script lang="ts">
  /**
   * 外观三选一（跟随系统 / 日间校样 / 夜间配音）。
   *
   * 为什么是卡片而不是下拉：macOS 系统设置 → 外观本身就是三张缩略图，用户
   * 一眼就能比较。`auto` 那张用一个「半亮半暗」的迷你窗口表示跟随系统。
   *
   * 颜色只从注册表 `APPEARANCE_SHOTS` 来（测试与 app.css 对账），组件不写死色值。
   */
  import Icon from '../../Icon.svelte';
  import {
    APPEARANCE_SHOTS,
    THEME_PREVIEW_CUE,
    type AppearanceId,
    type ThemeId,
  } from '../../../lib/themes';

  let {
    current,
    resolved,
    systemDark,
    onselect,
  }: {
    current: AppearanceId;
    resolved: ThemeId;
    systemDark: boolean;
    onselect: (id: AppearanceId) => void;
  } = $props();

  const light = APPEARANCE_SHOTS.find((shot) => shot.id === 'light')!;
  const dark = APPEARANCE_SHOTS.find((shot) => shot.id === 'dark')!;

  const cards = $derived([
    {
      id: 'auto' as AppearanceId,
      name: '跟随系统',
      note: `现在按系统：${resolved === 'dark' ? '夜间配音' : '日间校样'}${systemDark ? '（系统深色）' : '（系统浅色）'}`,
      split: true,
      shot: light,
    },
    {
      id: 'light' as AppearanceId,
      name: '日间校样',
      note: '中性浅灰铬件 · 纸白台面 · 皇家钴蓝；白天与交付前通读',
      split: false,
      shot: light,
    },
    {
      id: 'dark' as AppearanceId,
      name: '夜间配音',
      note: '纯中性深炭黑 · 下沉暗槽 · 中性近白字；画面是唯一亮面',
      split: false,
      shot: dark,
    },
  ]);

  function shotStyle(split: boolean, shot: typeof light): string {
    const base = (s: typeof light) =>
      [
        `--shot-canvas:${s.canvas}`,
        `--shot-paper:${s.paper}`,
        `--shot-card:${s.card}`,
        `--shot-ink:${s.ink}`,
        `--shot-accent:${s.accent}`,
        `--shot-line:${s.line}`,
      ].join(';');
    // auto 卡：左半日间、右半夜间，中间一条发丝线
    return split
      ? `${base(light)};--shot-canvas-r:${dark.canvas};--shot-paper-r:${dark.paper};--shot-card-r:${dark.card};--shot-accent-r:${dark.accent}`
      : base(shot);
  }
</script>

<div class="appearance-grid">
  {#each cards as card (card.id)}
    <button
      class="appearance-card"
      class:on={current === card.id}
      type="button"
      aria-pressed={current === card.id}
      aria-label={`外观：${card.name}。${card.note}`}
      onclick={() => onselect(card.id)}
    >
      <span class="shot" class:split={card.split} style={shotStyle(card.split, card.shot)} aria-hidden="true">
        <span class="shot-rail">
          <i class="rail-line accent"></i>
          <i class="rail-line"></i>
          <i class="rail-line"></i>
        </span>
        <span class="shot-body">
          <i class="shot-title"></i>
          <span class="shot-card">
            <i class="shot-bar"></i>
            <span class="shot-cue">{THEME_PREVIEW_CUE}</span>
            <i class="shot-btn"></i>
          </span>
        </span>
      </span>
      <span class="card-meta">
        <span class="card-copy">
          <span class="card-name">{card.name}</span>
          <span class="card-note">{card.note}</span>
        </span>
        {#if current === card.id}
          <span class="card-check"><Icon name="check" size={13} /></span>
        {/if}
      </span>
    </button>
  {/each}
</div>

<style>
  .appearance-grid {
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: var(--sp-3);
  }
  @media (max-width: 1120px) {
    .appearance-grid {
      grid-template-columns: repeat(2, minmax(0, 1fr));
    }
  }
  @media (max-width: 860px) {
    .appearance-grid {
      grid-template-columns: minmax(0, 1fr);
    }
  }

  /* 未选中的外观卡 = 台面上的一块凹陷填充；选中才加一道细蓝须。
     缩略图本身的颜色仍来自 --shot-*（它必须在任何外观下都能同时显示两套色）。 */
  .appearance-card {
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
    transition:
      border-color var(--dur) var(--ease),
      background var(--dur) var(--ease);
  }
  .appearance-card:hover {
    background: var(--well-hover);
  }
  .appearance-card.on {
    border-color: var(--accent-line);
    background: var(--accent-soft);
  }

  /* 迷你窗口：装饰性缩略图，颜色全部来自 --shot-*（1/4 尺度的间距单列在这里） */
  .shot {
    --shot-gap: 4px;
    --shot-pad: 7px;
    display: flex;
    height: 104px;
    border-radius: var(--rad-shot);
    overflow: hidden;
    border: 1px solid var(--shot-line);
    background: var(--shot-canvas);
  }
  .shot.split {
    background: linear-gradient(
      90deg,
      var(--shot-canvas) 0 50%,
      var(--shot-canvas-r) 50% 100%
    );
  }
  .shot-rail {
    width: 38px;
    flex: 0 0 38px;
    background: var(--shot-paper);
    border-right: 1px solid var(--shot-line);
    padding: 6px var(--sp-1);
    display: flex;
    flex-direction: column;
    gap: var(--shot-gap);
  }
  .shot.split .shot-rail {
    background: linear-gradient(90deg, var(--shot-paper) 0 50%, var(--shot-paper-r) 50% 100%);
  }
  .rail-line {
    display: block;
    height: 4px;
    border-radius: 2px;
    background: var(--shot-ink);
    opacity: 0.18;
  }
  .rail-line.accent {
    background: var(--shot-accent);
    opacity: 0.85;
  }
  .shot.split .rail-line.accent {
    background: linear-gradient(90deg, var(--shot-accent) 0 50%, var(--shot-accent-r) 50% 100%);
    opacity: 1;
  }
  .shot-body {
    flex: 1;
    min-width: 0;
    background: var(--shot-paper);
    padding: var(--shot-pad);
    display: flex;
    flex-direction: column;
    gap: 5px;
  }
  .shot.split .shot-body {
    background: linear-gradient(90deg, var(--shot-paper) 0 50%, var(--shot-paper-r) 50% 100%);
  }
  .shot-title {
    display: block;
    height: 5px;
    width: 42%;
    border-radius: 3px;
    background: var(--shot-ink);
    opacity: 0.5;
  }
  .shot-card {
    flex: 1;
    border-radius: 3px;
    background: var(--shot-card);
    border: 1px solid var(--shot-line);
    padding: 5px;
    display: flex;
    flex-direction: column;
    gap: var(--shot-gap);
    min-width: 0;
  }
  .shot.split .shot-card {
    background: linear-gradient(90deg, var(--shot-card) 0 50%, var(--shot-card-r) 50% 100%);
  }
  .shot-bar {
    display: block;
    height: 3px;
    width: 58%;
    border-radius: 2px;
    background: var(--shot-accent);
    opacity: 0.8;
  }
  .shot-cue {
    font-family: var(--font-cue);
    font-size: 8.5px;
    line-height: 1.35;
    color: var(--shot-ink);
    opacity: 0.72;
    overflow: hidden;
    display: -webkit-box;
    -webkit-line-clamp: 2;
    line-clamp: 2;
    -webkit-box-orient: vertical;
  }
  .shot-btn {
    display: block;
    margin-top: auto;
    height: 8px;
    width: 24px;
    border-radius: 3px;
    background: var(--shot-accent);
  }

  .card-meta {
    display: flex;
    align-items: flex-start;
    gap: var(--sp-2);
    padding: 0 var(--sp-1) var(--sp-1);
  }
  .card-copy {
    min-width: 0;
    display: flex;
    flex-direction: column;
    gap: 1px;
  }
  .card-name {
    font-size: var(--fs-ui);
    font-weight: 600;
  }
  .card-note {
    font-size: 11px;
    line-height: 1.45;
    color: var(--text-3);
  }
  .card-check {
    margin-left: auto;
    color: var(--accent);
    flex: 0 0 auto;
  }
</style>
