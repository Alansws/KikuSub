<script lang="ts">
  /**
   * 「高级参数」折叠面板：每块条数 / 翻译每块条数 / 上下文条数。
   *
   * 三个数字参数放明面会把 AI 分组撑成表单页，收进折叠层之后默认只显示当前值摘要
   * （`每块 200 · 翻译 120 · 上下文 5`），不打开也知道现在是多少。
   * 保存走 aiConfig 的 patch，与「服务地址 / 模型」同一条接口。
   */
  import Icon from '../../Icon.svelte';
  import { advancedParamsSummary, aiState, saveAiEndpoint } from '../../../lib/settings/aiConfig.svelte';

  let open = $state(false);
  const cfg = $derived(aiState.cfg);
</script>

<details class="advanced" bind:open>
  <summary>
    <span class="adv-chev" class:open><Icon name="chevron-down" size={11} /></span>
    <span class="adv-title">高级参数</span>
    {#if cfg}
      <span class="adv-summary">{advancedParamsSummary()}</span>
    {/if}
  </summary>

  {#if cfg}
    <div class="set-group adv-group">
      <div class="adv-fields">
        <label class="adv-field">
          <span class="adv-label">每块条数</span>
          <input class="adv-input" type="number" min="20" max="2000" bind:value={cfg.chunk_cues} />
          <span class="adv-hint">润色分块大小</span>
        </label>
        <label class="adv-field">
          <span class="adv-label">翻译每块条数</span>
          <input
            class="adv-input"
            type="number"
            min="20"
            max="2000"
            bind:value={cfg.translate_chunk_cues}
          />
          <span class="adv-hint">译文分块大小</span>
        </label>
        <label class="adv-field">
          <span class="adv-label">上下文条数</span>
          <input class="adv-input" type="number" min="0" max="30" bind:value={cfg.context_cues} />
          <span class="adv-hint">0 表示不带上下文</span>
        </label>
      </div>
      <div class="adv-foot">
        <button class="btn sm" onclick={() => saveAiEndpoint()} disabled={aiState.saving}>
          {aiState.saving ? '保存中…' : '保存'}
        </button>
        <span class="adv-note">块越大调用越少，但失败重试的成本也越高。</span>
      </div>
    </div>
  {/if}
</details>

<style>
  .advanced {
    margin-top: var(--sp-2);
  }
  .advanced > summary {
    list-style: none;
    cursor: default;
    display: flex;
    align-items: center;
    gap: 6px;
    height: var(--ctl-h);
    padding: 0 var(--sp-2);
    border-radius: var(--rad-control);
    font-size: var(--fs-label);
    color: var(--text-2);
    line-height: 1.5;
  }
  .advanced > summary::-webkit-details-marker {
    display: none;
  }
  .advanced > summary:hover {
    background: var(--fill);
    color: var(--text);
  }
  .adv-chev {
    display: grid;
    place-items: center;
    transition: transform var(--dur) var(--ease);
  }
  .adv-chev.open {
    transform: rotate(180deg);
  }
  .adv-title {
    font-weight: 500;
  }
  .adv-summary {
    margin-left: auto;
    color: var(--text-3);
    font-variant-numeric: tabular-nums;
  }
  .adv-group {
    margin-top: 6px;
  }
  .adv-fields {
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: var(--sp-3);
    padding: var(--sp-3) var(--sp-4);
  }
  .adv-field {
    display: flex;
    flex-direction: column;
    gap: var(--sp-1);
    min-width: 0;
  }
  .adv-label {
    font-size: var(--fs-label);
    color: var(--text-2);
  }
  .adv-input {
    font: inherit;
    font-size: 12px;
    height: var(--ctl-h);
    padding: 0 var(--sp-2);
    border: 1px solid var(--separator);
    border-radius: var(--rad-control);
    background: var(--raise);
    color: var(--text);
    outline: none;
    min-width: 0;
    font-family: var(--font-mono);
  }
  .adv-input:focus {
    border-color: var(--accent);
    box-shadow: 0 0 0 3px var(--accent-soft);
  }
  /* 分块参数直接决定「会不会超出模型上限、失败重试有多贵」，属于不看会填错的说明。 */
  .adv-hint {
    font-size: var(--fs-ui);
    line-height: 19px;
    color: var(--ink-2);
  }
  .adv-foot {
    display: flex;
    align-items: center;
    gap: var(--sp-2);
    padding: 0 var(--sp-4) var(--sp-3);
  }
  .adv-note {
    margin-left: auto;
    font-size: var(--fs-ui);
    line-height: 19px;
    color: var(--ink-2);
  }
  @media (max-width: 1120px) {
    .adv-fields {
      grid-template-columns: minmax(0, 1fr);
    }
  }
</style>
