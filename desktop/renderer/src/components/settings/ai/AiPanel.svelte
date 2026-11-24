<script lang="ts">
  /**
   * AI 优化：开关、服务地址、模型、API Key、连接测试、隐私提示。
   *
   * 顶层只留核心配置；单句判定覆盖、自动判定、本地档位与分块参数都收进
   * `AiAdvancedFold`（默认收起，已配置单句覆盖时展开）。
   * Key 的加解密全在主进程，这里只拿「有没有 / 能不能读」这几个布尔值。
   */
  import Icon from '../../Icon.svelte';
  import AiAdvancedFold from './AiAdvancedFold.svelte';
  import {
    aiState,
    clearAiKey,
    loadAiConfig,
    saveAiEndpoint,
    saveAiKey,
    testAiConnection,
    toggleAi,
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
          <!-- 状态跟着说明走，放在左边（2026-11-24）：否则「已配置 + 输入框 +
               保存 + 清除」四件东西挤在右侧一行，读起来像一堆并列按钮。 -->
          <span class="key-state" class:ok={aiState.hasKey}>
            {aiState.hasKey ? '已配置' : '未配置'}
          </span>
          {#if aiState.hasKey}
            已保存，本机 AES-256-GCM 加密；输入新值可替换。
          {:else if cfg.key_optional}
            当前是本机/局域网地址，Key 可留空。
          {:else}
            还没有保存：填一次即可，之后每次请求由主进程解密。
          {/if}
        </span>
      </div>
      <!-- 输入框与其他行同宽同右边缘；保存 / 清除放到它下面一行，
           不再和输入框抢同一行（那样四件东西会横着挤成一团）。 -->
      <div class="set-row-ctl key-ctl">
        <input
          class="ai-input key-input"
          type="password"
          bind:value={aiState.keyInput}
          spellcheck="false"
          autocomplete="off"
          placeholder={aiState.hasKey ? '输入新值可替换' : 'sk-…'}
          aria-label="API Key"
        />
        <div class="key-acts">
          <button class="btn sm" onclick={saveAiKey} disabled={!aiState.keyInput.trim() || !aiState.keyReady}>
            保存 Key
          </button>
          <button class="btn sm ghost" onclick={clearAiKey} disabled={!aiState.hasKey}>清除</button>
        </div>
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

  <!-- 隐私说明放在卡片正下方（2026-11-24）：它不是一行设置，插进行列表中间
       会读成「又一条灰色警告横幅」。11px 弱化灰字，与卡片边界分开。 -->
  <p class="group-note">
    调用会把字幕文本发送到该地址。Key 只保存在本机、加密存储，升级或重装应用都不会丢；每次请求时才解密。
  </p>

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
  {#if !aiState.keyReady}
    <div class="note-box warn">
      <span class="note-icon"><Icon name="warn" size={13} /></span>
      <span>应用数据目录不可写，密钥无法保存；请检查磁盘权限。</span>
    </div>
  {/if}


  <AiAdvancedFold />

  {#if aiState.arbKeyBroken}
    <div class="note-box warn">
      <span class="note-icon"><Icon name="warn" size={13} /></span>
      <span>单句判定的 Key 解不开（主密钥文件丢了或密文被改过），请在上面的判定 Key 输入框重填一次。</span>
    </div>
  {/if}
{/if}

<style>
  /* 只让「输入框 + 按钮排」竖着落，行本身仍然按内容高度走；
     这里绝不能给 height 或 align-items: stretch，否则 .set-row 会被撑成一大块白。 */
  .key-ctl {
    display: flex;
    flex-direction: column;
    align-items: flex-end;
    gap: var(--sp-1);
    width: auto;
  }
  .key-acts {
    display: flex;
    align-items: center;
    gap: var(--sp-1);
  }
  .group-note {
    margin: var(--sp-2) 2px 0;
    font-size: 11px;
    line-height: 16px;
    color: var(--text-3);
  }
  .ai-empty {
    display: flex;
    align-items: center;
    gap: var(--sp-3);
    padding: var(--sp-3) var(--sp-4);
    border: 1px solid var(--inset-line);
    border-radius: var(--rad-inset);
    background: var(--inset-bg);
  }
</style>
