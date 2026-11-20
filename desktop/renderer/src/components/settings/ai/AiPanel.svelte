<script lang="ts">
  /**
   * AI 优化：开关、服务地址、模型、API Key、连接测试、隐私提示。
   *
   * 左文右控的 Inset 分组；三个数字参数在「高级参数」里折叠。
   * Key 的加解密全在主进程，这里只拿「有没有 / 能不能读」这几个布尔值。
   */
  import Icon from '../../Icon.svelte';
  import AdvancedParams from './AdvancedParams.svelte';
  import {
    aiState,
    clearAiKey,
    clearArbKey,
    loadAiConfig,
    saveAiEndpoint,
    saveAiKey,
    saveArbKey,
    setLocalContext,
    testAiConnection,
    toggleAi,
    toggleAutoArbitrate,
    reloadLocalModel,
  } from '../../../lib/settings/aiConfig.svelte';

  const cfg = $derived(aiState.cfg);
</script>

{#if !cfg}
  <div class="ai-empty">
    <span class="set-row-desc">AI 配置读取失败，内核可能还没连上。</span>
    <button class="btn sm" onclick={loadAiConfig} disabled={aiState.loading}>
      {aiState.loading ? '读取中…' : '重试'}
    </button>
  </div>
{:else}
  <div class="set-group">
    <div class="set-row">
      <div class="set-row-main">
        <span class="set-row-title">启用 AI 优化</span>
        <span class="set-row-desc">关闭后「润色 / 翻译」页仍可查看、导入已有建议，只是不能再生成；单句 AI 判定也一并关闭。</span>
      </div>
      <div class="set-row-ctl">
        <button
          class="switch"
          class:on={cfg.enabled}
          role="switch"
          aria-checked={cfg.enabled}
          aria-label="启用 AI 优化"
          onclick={toggleAi}
        >
          <span class="knob"></span>
        </button>
      </div>
    </div>

    <div class="set-row">
      <div class="set-row-main">
        <span class="set-row-title">服务地址</span>
        <span class="set-row-desc">改动离开输入框即保存。本地 OpenAI 兼容服务可填 http://127.0.0.1:1234/v1。</span>
      </div>
      <div class="set-row-ctl grow">
        <input
          class="ai-input mono"
          bind:value={cfg.base_url}
          spellcheck="false"
          placeholder="https://api.deepseek.com"
          aria-label="AI 服务地址"
          onblur={() => saveAiEndpoint(true)}
        />
      </div>
    </div>

    <div class="set-row">
      <div class="set-row-main">
        <span class="set-row-title">模型</span>
      </div>
      <div class="set-row-ctl grow">
        <input
          class="ai-input mono"
          bind:value={cfg.model}
          spellcheck="false"
          placeholder="deepseek-flash"
          aria-label="模型名"
          onblur={() => saveAiEndpoint(true)}
        />
      </div>
    </div>

    <div class="set-row">
      <div class="set-row-main">
        <span class="set-row-title">API Key</span>
        <span class="set-row-desc">
          {#if aiState.hasKey}
            已保存，本机 AES-256-GCM 加密；输入新值可替换。
          {:else if cfg.key_optional}
            当前是本机/局域网地址，Key 可留空。
          {:else}
            还没有保存：填一次即可，之后每次请求由主进程解密。
          {/if}
        </span>
      </div>
      <div class="set-row-ctl">
        <span class="key-state" class:ok={aiState.hasKey}>
          {aiState.hasKey ? '已配置' : '未配置'}
        </span>
        <input
          class="ai-input key-input"
          type="password"
          bind:value={aiState.keyInput}
          spellcheck="false"
          autocomplete="off"
          placeholder={aiState.hasKey ? '输入新值可替换' : 'sk-…'}
          aria-label="API Key"
        />
        <button class="btn sm" onclick={saveAiKey} disabled={!aiState.keyInput.trim() || !aiState.keyReady}>
          保存 Key
        </button>
        <button class="btn sm ghost" onclick={clearAiKey} disabled={!aiState.hasKey}>清除</button>
      </div>
    </div>

    <div class="set-row">
      <div class="set-row-main">
        <span class="set-row-title">连接测试</span>
        <span class="set-row-desc" class:test-ok={aiState.testMsg.startsWith('连接正常')} class:test-bad={aiState.testMsg.startsWith('连接失败')}>
          {#if aiState.testMsg}
            {aiState.testMsg}
          {:else}
            用已保存的 Key 请求一次，检查地址与模型是否可用。
          {/if}
        </span>
      </div>
      <div class="set-row-ctl">
        <button
          class="btn sm"
          onclick={() => testAiConnection('global')}
          disabled={aiState.testing || !cfg.base_url || !cfg.model}
        >
          {aiState.testing ? '测试中…' : '测试连接'}
        </button>
      </div>
    </div>
  </div>

  <div class="set-group">
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
  </div>

  <div class="set-group">
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

  {#if aiState.keyBroken}
    <div class="note-box warn">
      <span class="note-icon"><Icon name="warn" size={13} /></span>
      <span>
        检测到已保存的密钥解不开（主密钥文件丢了或密文被改过）{aiState.keyLegacy
          ? '，它来自更早的钥匙串版本'
          : ''}。请在上面的输入框重新填一次。
      </span>
    </div>
  {/if}
  {#if aiState.arbKeyBroken}
    <div class="note-box warn">
      <span class="note-icon"><Icon name="warn" size={13} /></span>
      <span>单句判定的 Key 解不开（主密钥文件丢了或密文被改过），请在上面的判定 Key 输入框重填一次。</span>
    </div>
  {/if}
  {#if !aiState.keyReady}
    <div class="note-box warn">
      <span class="note-icon"><Icon name="warn" size={13} /></span>
      <span>应用数据目录不可写，密钥无法保存；请检查磁盘权限。</span>
    </div>
  {/if}

  <div class="note-box">
    <span class="note-icon"><Icon name="warn" size={13} /></span>
    <span>
      <b>调用会把字幕文本发送到该地址。</b>
      Key 只保存在本机、加密存储，升级或重装应用都不会丢；每次请求时才解密。
    </span>
  </div>

  <AdvancedParams />
{/if}

<style>
  .ai-empty {
    display: flex;
    align-items: center;
    gap: var(--sp-3);
    padding: var(--sp-3) var(--sp-4);
    border: 1px solid var(--inset-line);
    border-radius: var(--rad-inset);
    background: var(--inset-bg);
  }
  .ai-input {
    font: inherit;
    font-size: 12px;
    height: var(--ctl-h-lg);
    flex: 1;
    min-width: 0;
    padding: 0 var(--sp-2);
    border: 1px solid var(--separator);
    border-radius: var(--rad-control);
    background: var(--raise);
    color: var(--text);
    outline: none;
  }
  .ai-input:focus {
    border-color: var(--accent);
    box-shadow: 0 0 0 3px var(--accent-soft);
  }
  .ai-input.mono {
    font-family: var(--font-mono);
  }
  .key-input {
    flex: 0 1 190px;
    color: var(--text-2);
  }
  .key-state {
    font-size: var(--fs-label);
    color: var(--warn);
    white-space: nowrap;
    font-variant-numeric: tabular-nums;
  }
  .key-state.ok {
    color: var(--success);
  }
  .set-row-desc.test-ok {
    color: var(--success);
  }
  .set-row-desc.test-bad {
    color: var(--danger);
  }
</style>
