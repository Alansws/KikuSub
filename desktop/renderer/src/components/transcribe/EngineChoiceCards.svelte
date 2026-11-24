<script lang="ts">
  /**
   * 转写页的引擎选择卡（2026-11-21 Step 4）。
   *
   * 为什么不用下拉：用户第一眼要看到「两个日语主力分别擅长什么」。
   * 顶栏胶囊负责全局快捷切换，这里负责把两种口径讲清楚；两边共用同一个
   * `engine` prop（App.svelte 里的单一状态），所以不存在两份引擎状态。
   *
   * 中文引擎是可选装件：**只要用户在设置里启用了，就必须在这里有入口**，
   * 不能因为「主区只放日语主力」就把已启用的引擎藏死。它们以紧凑小卡出现在
   * 「其他已启用引擎」一行，与主力卡共用同一个 `engine`。
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

  function stateText(item: EngineInfo): string {
    return item.installed ? '已安装' : `未下载 · ${item.approx_label}`;
  }
</script>

<div class="pick">
  {#if primary.length}
    <div class="primary-grid" role="group" aria-label="日语主力引擎">
      {#each primary as item (item.key)}
        <button
          type="button"
          class="engine-card"
          class:on={engine === item.key}
          aria-pressed={engine === item.key}
          onclick={() => (engine = item.key)}
          title={item.description}
        >
          <span class="ec-head">
            <span class="ec-name">{item.label}</span>
            {#if item.family === 'whisper'}
              <span class="tag rec">推荐</span>
            {/if}
            <span class="ec-check" aria-hidden="true">
              {#if engine === item.key}<Icon name="check" size={11} />{/if}
            </span>
          </span>
          <span class="ec-tagline">{tagline(item)}</span>
          <span class="ec-desc">{item.description}</span>
          <span class="ec-foot">
            <span class="state" class:ready={item.installed}>
              <span class="state-dot" class:ready={item.installed}></span>
              {stateText(item)}
            </span>
            <span class="ec-lang">{item.languages.join(' / ')}</span>
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
        <span class="others-hint">在设置里启用后保留入口；切换与顶栏胶囊同步</span>
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
    <span>选择结果与顶栏引擎胶囊是同一个值</span>
    {#if onmanage}
      <button class="btn tiny ghost" type="button" onclick={onmanage}>
        <Icon name="gear" size={11} />管理引擎…
      </button>
    {/if}
  </div>
</div>

<style>
  .pick {
    display: flex;
    flex-direction: column;
    gap: var(--sp-2);
    min-width: 0;
  }

  .primary-grid {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: var(--sp-3);
    min-width: 0;
  }

  .engine-card {
    appearance: none;
    display: flex;
    flex-direction: column;
    gap: var(--sp-1);
    min-width: 0;
    padding: 9px var(--sp-3) var(--sp-2);
    border: 1px solid var(--separator);
    border-radius: 10px;
    background: var(--bg-content);
    color: var(--text);
    font: inherit;
    text-align: left;
    cursor: default;
    transition:
      border-color var(--dur) var(--ease),
      background var(--dur) var(--ease),
      box-shadow var(--dur) var(--ease);
  }
  .engine-card:hover {
    border-color: var(--accent-line);
    background: var(--accent-soft);
  }
  .engine-card.on {
    border-color: var(--accent);
    background: var(--accent-soft);
    box-shadow: 0 0 0 2px var(--accent-soft);
  }

  .ec-head {
    display: flex;
    align-items: center;
    gap: 6px;
    min-width: 0;
  }
  .ec-name {
    font-size: 13px;
    font-weight: 600;
    line-height: 18px;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .tag {
    flex: 0 0 auto;
    height: 17px;
    padding: 0 5px;
    border-radius: 3px;
    font-size: 10.5px;
    line-height: 17px;
    color: var(--text-3);
    background: var(--fill-strong);
  }
  .tag.rec {
    color: var(--accent);
    background: var(--fill);
  }
  .ec-check {
    margin-left: auto;
    width: 14px;
    flex: 0 0 14px;
    display: grid;
    place-items: center;
    color: var(--accent);
  }
  .ec-tagline {
    font-size: 12px;
    line-height: 16px;
    color: var(--text-2);
  }
  .engine-card.on .ec-tagline {
    color: var(--accent);
    font-weight: 500;
  }
  /* 这张卡要回答「两个日语主力分别擅长什么」，所以描述是「不看会选错引擎」的说明文字，
     按规则提到 13/19 并迁到 --ink-2。
     原来 clamp 在 1 行：Anime Whisper 那条 49 字在 11.5px 下就要两行，一直是被裁的
     （实测 clientHeight 19 / scrollHeight 38）。改 2 行 + 固定最小高度，
     两张卡描述块等高，卡脚才对得齐；整句仍可通过 title 看到。 */
  .ec-desc {
    display: -webkit-box;
    -webkit-line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
    font-size: var(--fs-ui);
    line-height: 19px;
    min-height: 38px;
    color: var(--ink-2);
  }
  .ec-foot {
    display: flex;
    align-items: center;
    gap: var(--sp-2);
    margin-top: 0;
    min-width: 0;
    font-size: 11px;
    color: var(--text-3);
  }
  .state {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    min-width: 0;
    white-space: nowrap;
  }
  .state-dot {
    width: 6px;
    height: 6px;
    flex: 0 0 6px;
    border-radius: 50%;
    background: var(--warn);
    box-shadow: 0 0 0 2px var(--warn-soft);
  }
  .state-dot.ready {
    background: var(--success);
    box-shadow: 0 0 0 2px var(--success-soft);
  }
  .ec-lang {
    margin-left: auto;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    font-size: 10.5px;
    color: var(--text-3);
  }

  .others {
    display: flex;
    flex-direction: column;
    gap: 6px;
    padding: var(--sp-2) var(--sp-3);
    border: 1px dashed var(--separator);
    border-radius: 8px;
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
    padding: 5px var(--sp-2);
    border: 1px solid var(--separator);
    border-radius: 7px;
    background: var(--bg-content);
    color: var(--text);
    font: inherit;
    cursor: default;
    text-align: left;
  }
  .other-chip:hover {
    border-color: var(--accent-line);
  }
  .other-chip.on {
    border-color: var(--accent);
    background: var(--accent-soft);
  }
  .other-name {
    font-size: 12px;
    font-weight: 500;
    white-space: nowrap;
  }
  .other-chip.on .other-name {
    color: var(--accent);
  }
  .other-meta {
    font-size: 10.5px;
    color: var(--text-3);
    white-space: nowrap;
  }

  .pick-empty {
    padding: var(--sp-3);
    border: 1px dashed var(--separator);
    border-radius: 8px;
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

  @media (max-width: 960px) {
    .primary-grid {
      grid-template-columns: minmax(0, 1fr);
    }
  }
</style>
