<script lang="ts">
  import Icon from '../components/Icon.svelte';
  import { app, loadReport, toast } from '../lib/store.svelte';

  $effect(() => {
    if (app.view === 'report' && !app.report) loadReport();
  });

  const report = $derived(app.report);

  async function copyRaw() {
    if (!report) return;
    await navigator.clipboard.writeText(report.raw_text);
    toast('任务详报已复制到剪贴板');
  }
</script>

<div class="report-wrap">
  {#if !report}
    <div class="empty">
      <p>还没有报告。</p>
      <p class="hint">跑一次转写后，这里会显示任务详报、质检速览与逐字对齐统计。</p>
    </div>
  {:else}
    <div class="report-h">
      <h2>转录任务详报</h2>
      <span class="meta">{app.cues.length} 条 · {app.media?.name ?? ''}</span>
      <button class="btn ghost" onclick={copyRaw} style="margin-left:auto">
        <Icon name="export" size={12} />复制全文
      </button>
    </div>

    <div class="grid">
      {#each report.overview as row (row.label)}
        <div class="kv">
          <span class="k">{row.label}</span>
          <span class="v" class:mono={/路径|文件名/.test(row.label)}>{row.value}</span>
        </div>
      {/each}
    </div>

    <div class="sec-h">质检速览</div>
    <div class="chips">
      <span class="chip" class:ok={report.quality.missed === 0}>
        漏句 <b>{report.quality.missed}</b>
      </span>
      {#if !report.quality.qwen_limited}
        <span class="chip" class:ok={report.quality.dropped === 0}>
          误删 <b>{report.quality.dropped}</b>
        </span>
        <span class="chip" class:warn={report.quality.suspect > 0}>
          短句待确认 <b>{report.quality.suspect}</b>
        </span>
      {/if}
      <span class="chip">降级对齐 <b>{report.quality.degraded}</b></span>
    </div>

    <div class="sec-h">执行生效参数</div>
    <div class="grid">
      {#each report.params as row (row.label)}
        <div class="kv">
          <span class="k">{row.label}</span>
          <span class="v">{row.value}</span>
        </div>
      {/each}
    </div>

    <div class="sec-h">质检与对齐</div>
    <div class="sections">
      {#each report.sections as s (s.id)}
        <div class="sec-row" class:disabled={s.disabled}>
          <span class="st">{s.title}</span>
          <span class="sh">{s.headline}</span>
          {#if s.items?.length}
            <span class="sn">{s.items.length} 条</span>
          {/if}
        </div>
      {/each}
    </div>
  {/if}
</div>

<style>
  .report-wrap {
    padding: 18px 26px 30px;
    overflow-y: auto;
    flex: 1;
  }
  .report-wrap > * {
    max-width: 880px;
  }

  .empty {
    color: var(--text-2);
    font-size: 13px;
    padding-top: 40px;
  }
  .hint {
    color: var(--text-3);
    font-size: 12px;
  }

  .report-h {
    display: flex;
    align-items: baseline;
    gap: 10px;
    margin-bottom: 14px;
  }
  .report-h h2 {
    font-size: 15px;
    font-weight: 600;
    margin: 0;
    letter-spacing: -0.01em;
  }
  .meta {
    font-size: 11.5px;
    color: var(--text-3);
    font-variant-numeric: tabular-nums;
  }

  .grid {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 0 22px;
    border: 1px solid var(--separator-soft);
    border-radius: 10px;
    padding: 10px 14px;
  }

  .sec-h {
    font-size: 11px;
    font-weight: 600;
    color: var(--text-3);
    margin: 18px 0 8px;
    letter-spacing: 0.02em;
  }

  .sections {
    border: 1px solid var(--separator-soft);
    border-radius: 10px;
    padding: 2px 14px;
  }
  .sec-row {
    display: flex;
    align-items: baseline;
    gap: 10px;
    padding: 8px 0;
    border-bottom: 1px solid var(--separator-soft);
    font-size: 12.5px;
  }
  .sec-row:last-child {
    border-bottom: 0;
  }
  .sec-row.disabled .sh {
    color: var(--text-3);
  }
  .st {
    width: 116px;
    flex: 0 0 116px;
    color: var(--text-2);
  }
  .sh {
    flex: 1;
  }
  .sn {
    font-size: 11px;
    color: var(--text-3);
    font-variant-numeric: tabular-nums;
  }
</style>
