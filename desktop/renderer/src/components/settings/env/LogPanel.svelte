<script lang="ts">
  /**
   * 日志与诊断：摘要行 + 五个动作 + 最近问题（2–3 行）+ 默认收起的 120 行原文。
   *
   * 原来的问题是「一个 120 行 pre + 五个按钮 + 三行元信息」平铺，把设置页最后一屏
   * 撑得很长。现在摘要一眼能看完，原文要展开才出现。
   */
  import Icon from '../../Icon.svelte';
  import { diagnostics } from '../../../lib/settings/diagnostics.svelte';
  import {
    cleanOldLogs,
    clearAllLogs,
    copyDiagnosticsSummary,
    copyRecentLogs,
    loadDiagnostics,
    sizeText,
  } from '../../../lib/settings/diagnostics.svelte';
  import { openPath } from '../../../lib/settings/paths.svelte';

  const diag = $derived(diagnostics.data);
  const problems = $derived(diag?.recent_problems ?? []);
  const tailLines = $derived((diag?.log_tail ?? '').split('\n').filter(Boolean).length);
  const logBig = $derived((diag?.log_bytes ?? 0) > 8 * 1024 * 1024);
</script>

<div class="set-group">
  <div class="log-summary">
    <span class="log-dot" class:on={diag?.log_exists}></span>
    <span class="log-state">
      {diag?.log_exists ? '已写入' : '尚未生成'} · {sizeText(diag?.log_bytes ?? 0)} · 保留 14 天 / 64 MB
    </span>
    <span class="set-path log-path" title={diag?.log_path ?? ''}>{diag?.log_path || '—'}</span>
  </div>

  <div class="log-actions">
    <button class="btn sm primary" onclick={copyDiagnosticsSummary}>
      <Icon name="copy" size={11} />
      {diagnostics.copying === 'diag' ? '已复制' : '复制精简诊断'}
    </button>
    <button class="btn sm" onclick={copyRecentLogs}>
      <Icon name="copy" size={11} />
      {diagnostics.copying === 'log' ? '已复制' : '复制最近日志'}
    </button>
    <button class="btn sm" onclick={() => openPath(diag?.paths.log_dir ?? '')}>
      <Icon name="folder" size={11} />打开日志目录
    </button>
    <button class="btn sm" onclick={cleanOldLogs} disabled={diagnostics.cleaning}>
      <Icon name="refresh" size={11} />
      {diagnostics.cleaning ? '清理中…' : '清理旧日志'}
    </button>
    <button class="btn sm danger" onclick={clearAllLogs} disabled={diagnostics.cleaning}>
      <Icon name="trash" size={11} />清空全部日志
    </button>
    <button
      class="btn sm ghost log-refresh"
      onclick={() => loadDiagnostics()}
      disabled={diagnostics.loading}
    >
      {diagnostics.loading ? '读取中…' : '刷新'}
    </button>
  </div>

  {#if logBig}
    <div class="log-warn">
      <Icon name="warn" size={12} />
      日志已超过 {sizeText(diag?.log_bytes ?? 0)}。可以点「清空全部日志」立即释放；不会影响字幕和设置。
    </div>
  {/if}

  {#if problems.length}
    <pre class="log-problems" aria-label="最近问题">{problems.join('\n')}</pre>
  {:else}
    <p class="log-empty">最近日志里没有 ERROR / WARNING。</p>
  {/if}

  <details class="log-more">
    <summary>
      <span class="more-chev"><Icon name="chevron-down" size={11} /></span>
      查看最近日志原文（{tailLines} 行）
    </summary>
    <pre class="log-raw">{diag?.log_tail || '（空）'}</pre>
  </details>
</div>

<style>
  .log-summary {
    display: flex;
    align-items: center;
    gap: var(--sp-3);
    padding: var(--sp-3) var(--sp-4);
    min-width: 0;
  }
  .log-dot {
    width: 6px;
    height: 6px;
    border-radius: 50%;
    background: var(--warn);
    flex: 0 0 6px;
  }
  .log-dot.on {
    background: var(--success);
  }
  .log-state {
    font-size: var(--fs-label);
    color: var(--text-2);
    font-variant-numeric: tabular-nums;
    white-space: nowrap;
  }
  .log-path {
    flex: 1 1 260px;
    text-align: right;
    color: var(--text-3);
  }
  .log-actions {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
    padding: var(--sp-3) var(--sp-4);
    border-top: 1px solid var(--inset-line);
    background: var(--fill);
  }
  .log-refresh {
    margin-left: auto;
  }
  .log-warn {
    display: flex;
    align-items: center;
    gap: 6px;
    padding: var(--sp-2) var(--sp-4);
    border-top: 1px solid var(--inset-line);
    background: var(--warn-soft);
    color: var(--warn);
    font-size: var(--fs-label);
  }
  .log-problems,
  .log-raw {
    margin: 0;
    padding: var(--sp-3) var(--sp-4);
    border-top: 1px solid var(--inset-line);
    font-family: var(--font-mono);
    font-size: 12px;
    line-height: 1.55;
    color: var(--text-2);
    white-space: pre-wrap;
    word-break: break-all;
    max-height: 128px;
    overflow: auto;
    user-select: text;
  }
  .log-raw {
    max-height: 220px;
    background: var(--fill);
  }
  .log-empty {
    margin: 0;
    padding: var(--sp-2) var(--sp-4);
    border-top: 1px solid var(--inset-line);
    font-size: var(--fs-label);
    color: var(--text-3);
  }
  .log-more > summary {
    list-style: none;
    cursor: default;
    display: flex;
    align-items: center;
    gap: 6px;
    padding: var(--sp-2) var(--sp-4);
    border-top: 1px solid var(--inset-line);
    font-size: var(--fs-label);
    color: var(--text-2);
  }
  .log-more > summary::-webkit-details-marker {
    display: none;
  }
  .log-more > summary:hover {
    background: var(--fill);
    color: var(--text);
  }
  .more-chev {
    display: grid;
    place-items: center;
    transition: transform var(--dur) var(--ease);
  }
  .log-more[open] .more-chev {
    transform: rotate(180deg);
  }
  .log-more[open] > summary {
    border-bottom: 1px solid var(--inset-line);
  }
</style>
