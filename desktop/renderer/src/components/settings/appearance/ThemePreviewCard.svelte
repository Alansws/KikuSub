<script lang="ts">
  /**
   * 一张主题缩略图（所见即所得）。
   *
   * 迷你窗口的三块用该主题的真实配色（注册表 `preview`，测试与 app.css 对账），
   * 字幕那行用该主题的真实字体——明朝墨的卡里必须是明朝，否则看不出这套主题的区别。
   * 当前不是明朝墨时也要能渲染明朝：所以读的是主题无关的 --font-cue-mincho。
   */
  import Icon from '../../Icon.svelte';
  import { THEME_PREVIEW_CUE, type ThemePreview } from '../../../lib/themes';

  let {
    preview,
    selected = false,
    onselect,
  }: {
    preview: ThemePreview;
    selected?: boolean;
    onselect: () => void;
  } = $props();

  const shotStyle = $derived(
    [
      `--shot-canvas:${preview.canvas}`,
      `--shot-paper:${preview.paper}`,
      `--shot-card:${preview.card}`,
      `--shot-ink:${preview.ink}`,
      `--shot-accent:${preview.accent}`,
      `--shot-line:${preview.line}`,
      `--shot-cue:${preview.cueFont === 'mincho' ? 'var(--font-cue-mincho)' : 'var(--font-sans)'}`,
    ].join(';'),
  );
</script>

<button
  class="theme-card"
  class:on={selected}
  type="button"
  aria-pressed={selected}
  aria-label={`主题：${preview.name}，${preview.note}`}
  onclick={onselect}
>
  <span class="shot" style={shotStyle} aria-hidden="true">
    <span class="shot-rail">
      <i class="rail-line accent"></i>
      <i class="rail-line"></i>
      <i class="rail-line"></i>
      <i class="rail-line"></i>
      <i class="rail-line"></i>
    </span>
    <span class="shot-body">
      <i class="shot-title"></i>
      <i class="shot-para"></i>
      <span class="shot-card">
        <i class="shot-bar"></i>
        <i class="shot-bar faint"></i>
        <span class="shot-cue">{THEME_PREVIEW_CUE}</span>
        <i class="shot-btn"></i>
      </span>
    </span>
  </span>
  <span class="theme-meta">
    <span class="theme-copy">
      <span class="theme-name">{preview.name}</span>
      <span class="theme-note">{preview.note}</span>
    </span>
    {#if selected}
      <span class="theme-check"><Icon name="check" size={14} /></span>
    {/if}
  </span>
</button>

<style>
  .theme-card {
    appearance: none;
    text-align: left;
    font: inherit;
    padding: var(--sp-2);
    border-radius: var(--rad-card);
    border: 1px solid var(--bento-border);
    background: var(--bento-bg);
    box-shadow: var(--bento-shadow);
    display: flex;
    flex-direction: column;
    gap: var(--sp-2);
    transition:
      border-color var(--dur) var(--ease),
      box-shadow var(--dur) var(--ease);
  }
  .theme-card:hover {
    border-color: var(--bento-border-on);
  }
  .theme-card.on {
    border-color: var(--bento-border-on);
    box-shadow: var(--bento-shadow-on);
  }

  /* 迷你窗口：装饰性缩略图，颜色全部来自 --shot-* */
  .shot {
    /* 缩略图是「画」出来的迷你窗口，不是真实布局：内部间距按 1/4 尺度单独取值，
       统一收在这里，避免与页面的 --sp-* 节奏混用 */
    --shot-gap: 4px;
    --shot-pad: 8px;
    display: flex;
    height: 116px;
    border-radius: var(--rad-shot);
    overflow: hidden;
    border: 1px solid var(--separator-soft);
    background: var(--shot-canvas);
  }
  .shot-rail {
    width: 44px;
    flex: 0 0 44px;
    background: var(--shot-paper);
    border-right: 1px solid var(--shot-line);
    padding: 7px 5px;
    display: flex;
    flex-direction: column;
    gap: var(--shot-gap);
  }
  .rail-line {
    display: block;
    height: 4px;
    border-radius: 2px;
    background: var(--shot-ink);
    opacity: 0.16;
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
    gap: 5px;
  }
  .shot-title {
    display: block;
    height: 6px;
    width: 46%;
    border-radius: 3px;
    background: var(--shot-ink);
    opacity: 0.55;
  }
  .shot-para {
    display: block;
    height: 4px;
    width: 78%;
    border-radius: 2px;
    background: var(--shot-ink);
    opacity: 0.16;
  }
  .shot-card {
    margin-top: 2px;
    flex: 1;
    border-radius: 4px;
    background: var(--shot-card);
    border: 1px solid var(--shot-line);
    padding: 5px;
    display: flex;
    flex-direction: column;
    gap: var(--shot-gap);
    min-width: 0;
  }
  .shot-bar {
    display: block;
    height: 3px;
    width: 64%;
    border-radius: 2px;
    background: var(--shot-accent);
    opacity: 0.8;
  }
  .shot-bar.faint {
    width: 40%;
    background: var(--shot-ink);
    opacity: 0.14;
  }
  .shot-cue {
    font-family: var(--shot-cue);
    font-size: 8.5px;
    line-height: 1.35;
    color: var(--shot-ink);
    opacity: 0.7;
    overflow: hidden;
    display: -webkit-box;
    -webkit-line-clamp: 2;
    line-clamp: 2;
    -webkit-box-orient: vertical;
  }
  .shot-btn {
    display: block;
    margin-top: auto;
    height: 9px;
    width: 26px;
    border-radius: 3px;
    background: var(--shot-accent);
  }

  .theme-meta {
    display: flex;
    align-items: flex-start;
    gap: var(--sp-2);
    padding: 0 var(--sp-1) var(--sp-1);
  }
  .theme-copy {
    min-width: 0;
    display: flex;
    flex-direction: column;
    gap: 1px;
  }
  .theme-name {
    font-size: var(--fs-ui);
    font-weight: 600;
  }
  .theme-note {
    font-size: 11px;
    line-height: 1.45;
    color: var(--text-3);
  }
  .theme-check {
    margin-left: auto;
    color: var(--accent);
    flex: 0 0 auto;
  }
</style>
