<script lang="ts">
  /**
   * 设置 → AI 与技能 →「进阶：单句判定独立模型与本地部署」折叠区。
   *
   * 顶层只留「启用 / 服务地址 / 模型 / Key / 连接测试」这套核心配置；单句判定覆盖、
   * 自动判定、本地 LM Studio 档位与分块参数都收在这里，新手第一眼不用面对表单墙。
   *
   * 默认开合由 `advancedAiInUse()` 按当前配置算：全新或未配置单句覆盖时收起；已填过
   * 判定地址 / 模型 / Key 或开了自动判定时展开，既有高级配置不会因为折叠而消失。
   * 用户点过之后以用户为准（`touched`），保存 / 清 Key 引起的配置刷新不会把面板弹回去。
   */
  import Icon from '../../Icon.svelte';
  import AdvancedParams from './AdvancedParams.svelte';
  import {
    aiState,
    clearArbKey,
    reloadLocalModel,
    saveAiEndpoint,
    saveArbKey,
    setLocalContext,
    testAiConnection,
    toggleAutoArbitrate,
  } from '../../../lib/settings/aiConfig.svelte';
  import { advancedAiInUse, advancedAiMeta } from '../../../lib/settings/aiFold';

  const cfg = $derived(aiState.cfg);

  let open = $state(false);
  let touched = false;

  $effect(() => {
    // 两把 Key 的「有没有」还没问完就下结论，会把「只存过判定 Key」的配置当成未配置。
    if (touched || !cfg || !aiState.keyChecked) return;
    open = advancedAiInUse(cfg, aiState.arbHasKey || aiState.arbKeyBroken);
  });

  function onToggle(event: Event) {
    const el = event.currentTarget as HTMLDetailsElement;
    // 默认值或程序化改动也会触发 toggle：只有与状态不一致时才是用户点的。
    if (el.open === open) return;
    open = el.open;
  }

  /** 收起时也能看出里面现在是什么（跟随全局 / 独立模型 · 自动判定开没开）。 */
  const meta = $derived(advancedAiMeta(cfg, aiState.arbHasKey));
</script>

<!-- 点过折叠区（含里面的按钮）就固定用户的选择，配置刷新不再自动开合。 -->
<details class="ai-adv" open={open} ontoggle={onToggle} onclick={() => (touched = true)}>
  <summary>
    <span class="adv-chev" class:open><Icon name="chevron-down" size={11} /></span>
    <span class="adv-title">进阶：单句判定独立模型与本地部署</span>
    {#if meta}
      <span class="adv-meta">{meta}</span>
    {/if}
  </summary>

  {#if cfg}
    <div class="set-group adv-group">
      <div class="set-row">
        <div class="set-row-main">
          <span class="set-row-title">单句判定模型覆盖（可选）</span>
          <span class="set-row-desc">
            两版引擎不一致时，右侧「AI 判定」默认用上面的全局配置；这里可单独指向本机模型（如 LM Studio / Ollama），留空则跟随全局。本机 LM Studio 在运行时，下方会出现上下文档位与重载按钮。
          </span>
        </div>
      </div>

      <div class="set-row">
        <div class="set-row-main">
          <span class="set-row-title">判定服务地址</span>
        </div>
        <div class="set-row-ctl grow">
          <input
            class="ai-input mono"
            bind:value={cfg.arbitrate_base_url}
            spellcheck="false"
            placeholder="留空 = 跟随全局"
            aria-label="单句判定服务地址"
            onblur={() => saveAiEndpoint(true)}
          />
        </div>
      </div>

      <div class="set-row">
        <div class="set-row-main">
          <span class="set-row-title">判定模型</span>
        </div>
        <div class="set-row-ctl grow">
          <input
            class="ai-input mono"
            bind:value={cfg.arbitrate_model}
            spellcheck="false"
            placeholder="留空 = 跟随全局"
            aria-label="单句判定模型名"
            onblur={() => saveAiEndpoint(true)}
          />
        </div>
      </div>

      <div class="set-row">
        <div class="set-row-main">
          <span class="set-row-title">判定 API Key</span>
          <span class="set-row-desc">
            {#if aiState.arbHasKey}
              已单独保存，与全局 Key 互不影响。
            {:else if cfg.arbitrate_key_optional && cfg.arbitrate_base_url}
              当前判定地址是本机/局域网，Key 可留空。
            {:else}
              留空时若判定地址指回全局地址，会使用全局 Key。
            {/if}
          </span>
        </div>
        <div class="set-row-ctl">
          <span class="key-state" class:ok={aiState.arbHasKey}>
            {aiState.arbHasKey ? '已配置' : '未配置'}
          </span>
          <input
            class="ai-input key-input"
            type="password"
            bind:value={aiState.arbKeyInput}
            spellcheck="false"
            autocomplete="off"
            placeholder={aiState.arbHasKey ? '输入新值可替换' : 'sk-… / 本地可留空'}
            aria-label="单句判定 API Key"
          />
          <button
            class="btn sm"
            onclick={saveArbKey}
            disabled={!aiState.arbKeyInput.trim() || !aiState.keyReady}
          >
            保存 Key
          </button>
          <button class="btn sm ghost" onclick={clearArbKey} disabled={!aiState.arbHasKey}>
            清除
          </button>
        </div>
      </div>

      <div class="set-row">
        <div class="set-row-main">
          <span class="set-row-title">判定连接测试</span>
          <span class="set-row-desc" class:test-ok={aiState.arbTestMsg.startsWith('连接正常')} class:test-bad={aiState.arbTestMsg.startsWith('连接失败')}>
            {#if aiState.arbTestMsg}
              {aiState.arbTestMsg}
            {:else}
              用判定地址与判定 Key 请求一次；本地模型不要求 Key。
            {/if}
          </span>
        </div>
        <div class="set-row-ctl">
          <button
            class="btn sm"
            onclick={() => testAiConnection('arbitrate')}
            disabled={aiState.arbTesting || !(cfg.arbitrate_base_url || cfg.base_url) || !(cfg.arbitrate_model || cfg.model)}
          >
            {aiState.arbTesting ? '测试中…' : '测试判定连接'}
          </button>
        </div>
      </div>

      <div class="set-row">
        <div class="set-row-main">
          <span class="set-row-title">两版不一致时自动 AI 判定</span>
          <span class="set-row-desc">
            开启后，B 引擎复核完成且与当前稿不一致时自动判定一次；切换句子、编辑或取消都会中断在途请求。默认关闭。
          </span>
        </div>
        <div class="set-row-ctl">
          <button
            class="switch"
            class:on={cfg.auto_arbitrate}
            role="switch"
            aria-checked={cfg.auto_arbitrate}
            aria-label="两版不一致时自动 AI 判定"
            onclick={toggleAutoArbitrate}
          >
            <span class="knob"></span>
          </button>
        </div>
      </div>

      {#if cfg.arbitrate_loopback && aiState.localModel.available}
        <div class="set-row">
          <div class="set-row-main">
            <span class="set-row-title">本地上下文档位</span>
            <span class="set-row-desc">
              仅对 LM Studio 生效；2048 最省内存，单句判定不需要长上下文。切换档位后点右侧按钮重载，判定请求本身不会重载模型。
            </span>
          </div>
          <div class="set-row-ctl">
            <select
              class="ai-input mono"
              value={cfg.local_context}
              aria-label="本地上下文档位"
              onchange={(e) => void setLocalContext(Number((e.currentTarget as HTMLSelectElement).value))}
            >
              <option value={2048}>2048（推荐 · 省内存）</option>
              <option value={4096}>4096</option>
              <option value={8192}>8192</option>
            </select>
            <button
              class="btn sm"
              onclick={reloadLocalModel}
              disabled={aiState.localModel.loadingModel || aiState.localModel.loading}
            >
              {aiState.localModel.loadingModel ? '加载中…' : '加载 / 重载本地模型'}
            </button>
          </div>
        </div>
        <div class="set-row">
          <div class="set-row-main">
            <span class="set-row-desc">
              {#if aiState.localModel.loading}
                正在读取 LM Studio 状态…
              {:else if aiState.localModel.loaded}
                已加载 · 当前 context {aiState.localModel.contextLength ?? '—'}
                {#if aiState.localModel.contextLength !== cfg.local_context}
                  · 与所选档位不同，点上方按钮重载后生效
                {/if}
              {:else}
                模型未加载；首次判定会由 LM Studio JIT 按它自己的默认档位加载
              {/if}
              {#if aiState.localModel.message}
                · {aiState.localModel.message}
              {/if}
            </span>
          </div>
        </div>
      {/if}
    </div>

    <AdvancedParams />
  {/if}
</details>

<style>
  .ai-adv {
    margin-top: var(--sp-2);
  }
  .ai-adv > summary {
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
  .ai-adv > summary::-webkit-details-marker {
    display: none;
  }
  .ai-adv > summary:hover {
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
  .adv-meta {
    margin-left: auto;
    color: var(--text-3);
    font-variant-numeric: tabular-nums;
    white-space: nowrap;
  }
  .adv-group {
    margin-top: 6px;
  }
</style>
