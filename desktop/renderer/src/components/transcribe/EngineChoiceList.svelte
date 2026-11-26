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
    <!-- 「其他已启用引擎」原来是一层厚灰底盒子、里面再塞白色小卡（2026-11-26 报障：
         典型的灰底套白框）。按 DESIGN.md 的 No White Frame：它是**页面里的一个分区**，
         所以只留「标题 + 一条发丝线」，胶囊自己带细边。 -->
    <div class="others">
      <div class="others-head">
        <span class="others-title">其他已启用引擎</span>
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
            <span class="radio" aria-hidden="true"></span>
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
      <button class="btn soft sm" type="button" onclick={onmanage}>
        <Icon name="gear" size={11} />管理引擎
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
  /* 选中：一层**清透微蓝**的填充 + 一道细蓝须（2026-11-26）。
     台面变纸白之后「纸白底 + 蓝边」在白底上只剩一根线，选中读不出来；
     改成半透明蓝底（与页边记号、导航选中同一族），未选中那条则完全无底色。 */
  .engine.on {
    background: var(--accent-soft);
    border-bottom-color: transparent;
    border-radius: var(--rad-control);
    box-shadow: inset 0 0 0 1px var(--accent-line);
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

  /* 分区 = 标题 + 发丝线（No White Frame）：不再是一层灰底盒子里面塞白卡。
     灰底盒子配上里面的白胶囊，正是用户说的「厚灰底套白框」套娃。 */
  .others {
    display: flex;
    flex-direction: column;
    gap: var(--sp-2);
    padding-top: 10px;
    border-top: 1px solid var(--line);
    min-width: 0;
  }
  .others-head {
    display: flex;
    align-items: baseline;
    gap: var(--sp-2);
    flex-wrap: wrap;
    min-width: 0;
  }
  .others-title {
    font-family: var(--font-mono);
    font-size: 11px;
    line-height: 16px;
    letter-spacing: 0.06em;
    text-transform: uppercase;
    color: var(--text-3);
  }
  .others-hint {
    font-weight: 400;
    font-size: 11px;
    line-height: 16px;
    color: var(--text-3);
  }
  .others-row {
    display: flex;
    gap: 6px;
    flex-wrap: wrap;
    min-width: 0;
  }
  /* 单层质感控件：纸白键 + 1px 发丝边（与 .btn 同一套语法），
     靠边线在白台面上读成「可以选」，而不是靠灰底衬托。 */
  .other-chip {
    appearance: none;
    display: inline-flex;
    align-items: center;
    gap: 6px;
    min-width: 0;
    height: 26px;
    padding: 0 9px 0 7px;
    border: 1px solid var(--btn-line);
    border-radius: var(--rad-control);
    background: var(--raise);
    color: var(--text);
    font: inherit;
    text-align: left;
    box-shadow: var(--raise-bevel);
    transition:
      background var(--dur) var(--ease),
      border-color var(--dur) var(--ease);
  }
  .other-chip:hover {
    border-color: var(--btn-line-hover);
  }
  .other-chip.on {
    border-color: var(--accent);
    background: var(--accent-soft);
  }
  /* 与主力引擎行同一颗单选圈：选中状态在这张表里只有一个语法。 */
  .other-chip .radio {
    width: 11px;
    height: 11px;
    flex: 0 0 11px;
    margin-top: 0;
    border: 1px solid var(--line);
    border-radius: 50%;
    display: grid;
    place-items: center;
  }
  .other-chip.on .radio {
    border-color: var(--accent);
  }
  .other-chip.on .radio::after {
    content: '';
    width: 5px;
    height: 5px;
    border-radius: 50%;
    background: var(--accent);
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
    border: 0;
    border-radius: var(--rad-card);
    background: var(--well);
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
