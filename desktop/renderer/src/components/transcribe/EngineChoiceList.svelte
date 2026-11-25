<script lang="ts">
  /**
   * 转写页的引擎选择（2026-11-25 Cue Script 版）。
   *
   * 从「两张卡片」改成「一张表里的两行」：卡片会让人先读边框再看内容，
   * 而这里真正要回答的是「两个日语主力分别擅长什么、我这次该选哪个」。
   * 行式排布让名称、口径、状态落在同一基线上，也让「其他已启用引擎」
   * 自然接在下面而不是另起一屏。
   *
   * 为什么不用下拉：用户第一眼要看到差别。中文引擎是可选装件：只要在设置里
   * 启用了就必须在这里有入口，不能因为「主区只放日语主力」把它藏死。
   */
  import Icon from '../Icon.svelte';
  import type { EngineInfo } from '../../lib/api';

  let {
    engine = $bindable('whisper'),
    engines = [],
    onmanage,
  }: {
    engine?: string;
    engines?: EngineInfo[];
    onmanage?: () => void;
  } = $props();

  /** 日语主力：注册表里的 whisper / qwen 两族；其余已启用引擎单独一行。 */
  const primary = $derived(
    engines.filter((item) => item.family === 'whisper' || item.family === 'qwen'),
  );
  const others = $derived(
    engines.filter((item) => item.family !== 'whisper' && item.family !== 'qwen'),
  );

  function tagline(item: EngineInfo): string {
    if (item.family === 'whisper') return '日语自然对话';
    if (item.family === 'qwen') return '逐字精确时间轴';
    return item.purpose;
  }
</script>

<div class="engines">
  {#if primary.length}
    <div class="engine-list" role="group" aria-label="日语主力引擎">
      {#each primary as item (item.key)}
        <button
          type="button"
          class="engine"
          class:on={engine === item.key}
          aria-pressed={engine === item.key}
          onclick={() => (engine = item.key)}
          title={item.description}
        >
          <span class="radio" aria-hidden="true"></span>
          <span class="engine-body">
            <span class="engine-name">
              {item.label}
              {#if item.family === 'whisper'}<span class="tag rec">推荐</span>{/if}
            </span>
            <span class="engine-desc">{item.description}</span>
            <span class="engine-meta">
              <span class="badge" class:ok={item.installed}>
                {item.installed ? '已安装' : `未下载 · ${item.approx_label}`}
              </span>
              <span class="badge">{tagline(item)}</span>
              <span class="badge">{item.languages.join(' / ')}</span>
              {#if item.reviewable}<span class="badge">可做复核</span>{/if}
            </span>
          </span>
          <span class="engine-stat">
            <b>{item.installed ? '就绪' : item.approx_label}</b>
            {#if item.min_ram_gb}≥ {item.min_ram_gb} GB 内存{/if}
          </span>
        </button>
      {/each}
    </div>
  {:else}
    <div class="pick-empty">
      还没有启用日语主力引擎。到「设置 → 引擎与模型」里启用 Anime Whisper 或 Qwen3-ASR。
    </div>
  {/if}

  {#if others.length}
    <div class="others">
      <div class="others-head">
        <span>其他已启用引擎</span>
        <span class="others-hint">在设置里启用后保留入口；与标题栏引擎胶囊同步</span>
      </div>
      <div class="others-row">
        {#each others as item (item.key)}
          <button
            type="button"
            class="other-chip"
            class:on={engine === item.key}
            aria-pressed={engine === item.key}
            onclick={() => (engine = item.key)}
            title={item.description}
          >
            <span class="other-name">{item.label}</span>
            <span class="other-meta">
              {item.installed ? '已安装' : item.approx_label} · {item.purpose}
            </span>
          </button>
        {/each}
      </div>
    </div>
  {/if}

  <div class="pick-foot">
    <span>选择结果与标题栏的引擎胶囊是同一个值</span>
    {#if onmanage}
      <button class="btn ghost sm" type="button" onclick={onmanage}>
        <Icon name="gear" size={11} />管理引擎…
      </button>
    {/if}
  </div>
</div>

<style>
  .engines {
    display: flex;
    flex-direction: column;
    gap: var(--sp-2);
    min-width: 0;
  }

  .engine-list {
    display: flex;
    flex-direction: column;
    border-top: 1px solid var(--line);
  }
  .engine {
    appearance: none;
    display: grid;
    grid-template-columns: 16px minmax(0, 1fr) auto;
    gap: 10px;
    align-items: start;
    width: 100%;
    padding: 11px var(--sp-2) 11px 6px;
    border: 0;
    border-bottom: 1px solid var(--line);
    border-radius: 0;
    background: transparent;
    color: var(--text);
    font: inherit;
    text-align: left;
    transition: background var(--dur) var(--ease);
  }
  .engine:hover {
    background: var(--fill);
  }
  /* 选中：干净纸白底 + 1px 蓝边框（macOS 原生层级）。
     旧版整行涂 10% 半透明蓝，叠在灰底上会显脏；蓝色现在只留在
     圆点、推荐徽章和边框上，文字回到深墨。 */
  .engine.on {
    background: var(--raise);
    border-bottom-color: transparent;
    border-radius: var(--rad-control);
    box-shadow: inset 0 0 0 1px var(--accent);
  }
  .engine:focus-visible {
    outline: 2px solid var(--accent-ring);
    outline-offset: -2px;
  }

  .radio {
    width: 14px;
    height: 14px;
    margin-top: 2px;
    border-radius: 50%;
    border: 1px solid var(--line);
    display: grid;
    place-items: center;
    flex: 0 0 14px;
  }
  .engine.on .radio {
    border-color: var(--accent);
  }
  .engine.on .radio::after {
    content: '';
    width: 7px;
    height: 7px;
    border-radius: 50%;
    background: var(--accent);
  }

  .engine-body {
    min-width: 0;
    display: flex;
    flex-direction: column;
    gap: 3px;
  }
  .engine-name {
    display: flex;
    align-items: center;
    gap: 7px;
    font-size: 12.5px;
    font-weight: 600;
    color: var(--text);
  }
  .tag {
    flex: 0 0 auto;
    height: 17px;
    padding: 0 5px;
    border-radius: 3px;
    font-size: 10.5px;
    line-height: 17px;
    font-weight: 500;
    color: var(--text-3);
    background: var(--fill-strong);
  }
  .tag.rec {
    color: var(--accent-text);
    background: var(--accent-soft);
  }
  .engine-desc {
    font-size: 12px;
    line-height: 1.5;
    color: var(--text-3);
    text-wrap: pretty;
  }
  .engine-meta {
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    gap: 5px;
    margin-top: 2px;
  }
  .badge {
    height: 17px;
    padding: 0 5px;
    display: inline-flex;
    align-items: center;
    border-radius: 3px;
    background: var(--fill);
    font-size: 10.5px;
    line-height: 17px;
    color: var(--text-2);
    font-variant-numeric: tabular-nums;
    white-space: nowrap;
  }
  .badge.ok {
    background: var(--success-soft);
    color: var(--success);
  }

  .engine-stat {
    flex: 0 0 auto;
    text-align: right;
    font-family: var(--font-mono);
    font-size: 10.5px;
    line-height: 1.5;
    color: var(--text-3);
    white-space: nowrap;
    padding-top: 1px;
  }
  .engine-stat b {
    display: block;
    font-size: 11px;
    font-weight: 500;
    color: var(--text-2);
  }

  .others {
    display: flex;
    flex-direction: column;
    gap: 6px;
    padding: var(--sp-2) var(--sp-3);
    border: 1px solid var(--line);
    border-radius: var(--rad-card);
    background: var(--fill);
    min-width: 0;
  }
  .others-head {
    display: flex;
    align-items: baseline;
    gap: var(--sp-2);
    flex-wrap: wrap;
    font-size: 11.5px;
    font-weight: 600;
    color: var(--text-2);
  }
  .others-hint {
    font-weight: 400;
    font-size: 11px;
    color: var(--text-3);
  }
  .others-row {
    display: flex;
    gap: 6px;
    flex-wrap: wrap;
    min-width: 0;
  }
  .other-chip {
    appearance: none;
    display: inline-flex;
    align-items: baseline;
    gap: 6px;
    min-width: 0;
    padding: 4px var(--sp-2);
    border: 1px solid var(--line);
    border-radius: var(--rad-control);
    background: var(--raise);
    color: var(--text);
    font: inherit;
    text-align: left;
  }
  .other-chip:hover {
    border-color: var(--accent-line);
  }
  .other-chip.on {
    border-color: var(--accent);
    background: var(--raise);
  }
  .other-name {
    font-size: 12px;
    font-weight: 500;
    white-space: nowrap;
  }
  .other-chip.on .other-name {
    color: var(--text);
  }
  .other-meta {
    font-size: 10.5px;
    color: var(--text-3);
    white-space: nowrap;
  }

  .pick-empty {
    padding: var(--sp-3);
    border: 1px dashed var(--line);
    border-radius: var(--rad-card);
    font-size: 12px;
    line-height: 1.55;
    color: var(--text-3);
  }

  .pick-foot {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--sp-2);
    font-size: 11px;
    color: var(--text-3);
  }

  @media (max-width: 1040px) {
    .engine {
      grid-template-columns: 16px minmax(0, 1fr);
    }
    .engine-stat {
      display: none;
    }
  }
</style>
