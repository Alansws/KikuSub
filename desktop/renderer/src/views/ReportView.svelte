<script lang="ts">
  /**
   * 任务详报。
   *
   * 服务层返回的是结构化数据（overview / params / quality / sections），所以这里
   * 不解析任何文本：三类质检明细、幻觉门控、逐字对齐降级都能展开看逐条，
   * 点时间码直接跳回核对台并聚焦该区间。
   */
  import Icon from '../components/Icon.svelte';
  import {
    app,
    exportCues,
    focusRange,
    loadReport,
    setView,
    toast,
    toggleQaPanel,
  } from '../lib/store.svelte';

  $effect(() => {
    if (app.view === 'report' && !app.report) loadReport({ silent: true });
  });

  const report = $derived(app.report);
  const q = $derived(report?.quality);

  let lastExport = $state('');

  const exportDir = $derived(
    app.job?.result?.export_dir || app.config?.export_dir || app.config?.output_dir || '',
  );
  const savedPath = $derived(app.lastSavedPath || '');

  async function copyRaw() {
    if (!report) return;
    try {
      if (window.kikusub.writeClipboard) await window.kikusub.writeClipboard(report.raw_text);
      else await navigator.clipboard.writeText(report.raw_text);
      toast('任务详报已复制到剪贴板');
    } catch (err) {
      toast(`复制失败：${(err as Error).message}`, 'error');
    }
  }

  async function exportAs(fmt: 'SRT' | 'VTT' | 'TXT') {
    const res = await exportCues(fmt);
    if (res) lastExport = res.path;
  }

  function reveal() {
    if (lastExport) window.kikusub.revealInFinder(lastExport);
  }

  function goToItem(item: any) {
    const start = Number(item.start ?? 0);
    const end = Number(item.end ?? start + 0.5);
    setView('review');
    focusRange(start, end);
  }

  const sectionCount = $derived(
    (report?.sections ?? []).reduce((n, s) => n + (s.items?.length ?? 0), 0),
  );

  /** 报告内核与旧 Gradio 界面共用，文案里带 ✅🔍 这类 emoji；桌面端视觉规范是零 emoji。 */
  function plain(text: string | undefined | null): string {
    return String(text ?? '')
      .replace(/[\u{1F000}-\u{1FAFF}\u{2600}-\u{27BF}\u{2B00}-\u{2BFF}\u{FE0F}]/gu, '')
      .replace(/\s{2,}/g, ' ')
      .trim();
  }

  function openExportFolder() {
    if (!exportDir) {
      toast('还没有可用的导出文件夹，请先到设置里选择', 'warn');
      return;
    }
    void window.kikusub.openPath(exportDir);
  }
</script>

<div class="report-wrap">
  {#if !report}
    <div class="empty">
      <Icon name="doc" size={22} />
      <p>还没有任务报告。</p>
      <p class="hint">
        跑一次整片转写后，这里会显示任务概览、生效参数、质检清单与逐条明细。
      </p>
      {#if app.cues.length}
        <div class="empty-export">
          <p class="hint">
            不过核对台当前已有 <b>{app.cues.length}</b> 条字幕（例如重开应用后手动导入的基线），
            可以直接导出，不需要等任务报告。
          </p>
          <div class="export-row">
            <button class="btn" onclick={() => exportAs('SRT')}>导出 SRT</button>
            <button class="btn" onclick={() => exportAs('VTT')}>导出 VTT</button>
            <button class="btn" onclick={() => exportAs('TXT')}>导出 TXT</button>
            <button class="btn ghost" onclick={() => setView('review')}>回到核对台</button>
          </div>
          {#if lastExport}
            <span class="path">{lastExport}</span>
          {/if}
        </div>
      {/if}
    </div>
  {:else}
    <div class="report-h">
      <div class="rh-main">
        <h2>转录任务详报</h2>
        <span class="meta">
          {app.cues.length} 条 · {app.media?.name ?? ''} · {sectionCount} 条明细
        </span>
      </div>
      <div class="rh-actions">
        <button class="btn ghost" onclick={copyRaw} title="复制纯文本报告">
          <Icon name="export" size={11} />复制全文
        </button>
        <button class="btn ghost" onclick={() => loadReport()} title="重新拉取报告">
          <Icon name="undo" size={11} />
        </button>
      </div>
    </div>

    {#if report.overview.find((r) => r.label === '完成状态')?.value?.includes('打断') ||
      report.raw_text.includes('转录已中途打断')}
      <div class="banner">
        <Icon name="warn" size={12} />
        本次转写被中途打断，报告只统计已保存的字幕。
      </div>
    {/if}

    <!-- 指标 -->
    <div class="grid">
      {#each report.overview as row (row.label)}
        <div class="kv">
          <span class="k">{row.label}</span>
          <span class="v" class:mono={/路径|文件名|耗时|时间/.test(row.label)}>{plain(row.value)}</span>
        </div>
      {/each}
    </div>

    <!-- 质检速览 -->
    <div class="sec-head">
      <span class="sec-h">质检速览</span>
      <span class="sec-note">{plain(q?.headline)}</span>
      <button class="btn tiny" onclick={() => toggleQaPanel(true)}>去逐项核对 →</button>
    </div>
    <div class="chips">
      <span class="chip" class:ok={(q?.coverage ?? 0) === 0} class:warn={(q?.coverage ?? 0) > 0}>
        漏检（未覆盖） <b>{q?.coverage ?? 0}</b>
      </span>
      <span
        class="chip"
        class:ok={(q?.low_confidence ?? 0) === 0}
        class:soft={(q?.low_confidence ?? 0) > 0}
      >
        低置信 <b>{q?.low_confidence ?? 0}</b>
      </span>
      {#if !q?.qwen_limited}
        <span class="chip muted">
          切片内：空 {q?.missed ?? 0} / 删 {q?.dropped ?? 0} / 短 {q?.suspect ?? 0}
        </span>
      {:else}
        <span class="chip muted">该引擎只覆盖切片内空结果</span>
      {/if}
      <span class="chip" class:muted={q?.degraded === 0}>
        降级对齐 <b>{q?.degraded ?? 0}</b>
      </span>
      {#if q?.hidden_missed}
        <span class="chip muted">另有 {q.hidden_missed} 处近静音段未列入</span>
      {/if}
    </div>

    <!-- 分段明细 -->
    <div class="sec-head">
      <span class="sec-h">质检与对齐明细</span>
      <span class="sec-note">展开看逐条，点时间码回核对台</span>
    </div>
    <div class="sections">
      {#each report.sections as s (s.id)}
        <details class="sec" open={s.id === 'missed' || (s.items?.length ?? 0) > 0}>
          <summary>
            <span class="st">{s.title}</span>
            <span class="sh" class:muted={s.disabled}>{plain(s.headline)}</span>
            {#if s.items?.length}
              <span class="sn">{s.items.length}</span>
            {/if}
            {#if s.truncated}
              <span class="sn muted">另有 {s.truncated} 条</span>
            {/if}
          </summary>

          {#if s.note}
            <div class="note">{plain(s.note)}</div>
          {/if}
          {#if s.hidden_text}
            <div class="note muted">{plain(s.hidden_text)}</div>
          {/if}

          {#if s.items?.length}
            <div class="items">
              {#each s.items as item, i (i)}
                <div class="item">
                  <button
                    class="time-link"
                    onclick={() => goToItem(item)}
                    title="跳到核对台并聚焦这一段"
                  >
                    {item.time_text ?? `${Number(item.start ?? 0).toFixed(2)}s`}
                  </button>
                  {#if item.rule_text}
                    <span class="tag">{item.rule_text}</span>
                  {:else if item.reason_text}
                    <span class="tag">{item.reason_text}</span>
                  {/if}
                  {#if item.dur}
                    <span class="dur">{Number(item.dur).toFixed(2)}s</span>
                  {/if}
                  {#if item.chars}
                    <span class="dur">{item.chars} 字</span>
                  {/if}
                  {#if item.text}
                    <span class="it-text">{item.text}</span>
                  {/if}
                  {#if item.peak !== null && item.peak !== undefined}
                    <span class="peak">峰值 {Number(item.peak).toFixed(2)}</span>
                  {/if}
                </div>
              {/each}
            </div>
          {:else if s.empty_text && plain(s.empty_text) !== plain(s.headline)}
            <div class="note muted">{plain(s.empty_text)}</div>
          {/if}
        </details>
      {/each}
    </div>

    <!-- 生效参数 -->
    <details class="sec params">
      <summary>
        <span class="st">执行生效参数</span>
        <span class="sh muted">{report.params.length} 项</span>
      </summary>
      <div class="grid inner">
        {#each report.params as row (row.label)}
          <div class="kv">
            <span class="k">{row.label}</span>
            <span class="v">{row.value}</span>
          </div>
        {/each}
      </div>
    </details>

    <!-- 导出 -->
    <div class="sec-head">
      <span class="sec-h">保存与导出</span>
      <span class="sec-note">转写完成即自动写入导出文件夹；这里的按钮导出核对台当前时间轴</span>
    </div>
    {#if savedPath}
      <div class="saved-line">
        <span class="saved-ok"><Icon name="check" size={10} />本次转写已自动保存</span>
        <span class="path" title={savedPath}>{savedPath}</span>
        <button class="btn tiny ghost" onclick={() => window.kikusub.revealInFinder(savedPath)}>
          在访达中显示
        </button>
      </div>
    {/if}
    <div class="export-row">
      <button class="btn" onclick={() => exportAs('SRT')}>导出 SRT</button>
      <button class="btn" onclick={() => exportAs('VTT')}>导出 VTT</button>
      <button class="btn" onclick={() => exportAs('TXT')}>导出 TXT</button>
      <button class="btn ghost" onclick={openExportFolder} title={exportDir}>
        <Icon name="folder" size={11} />打开导出文件夹
      </button>
      {#if lastExport}
        <button class="btn ghost" onclick={reveal}>
          <Icon name="folder" size={11} />在访达中显示
        </button>
        <span class="path">{lastExport}</span>
      {/if}
    </div>
  {/if}
</div>

<style>
  .report-wrap {
    padding: 18px 26px 34px;
    overflow-y: auto;
    flex: 1;
  }
  .report-wrap > * {
    max-width: 900px;
  }

  .empty {
    color: var(--text-2);
    font-size: 13px;
    padding-top: 46px;
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 4px;
  }
  .hint {
    color: var(--text-3);
    font-size: 12px;
  }

  .empty-export {
    margin-top: 18px;
    padding: 12px 14px;
    border: 1px solid var(--separator-soft);
    border-radius: 10px;
    max-width: 520px;
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 9px;
  }
  .empty-export .hint {
    text-align: center;
    line-height: 1.55;
  }
  .empty-export .path {
    max-width: 100%;
  }

  .report-h {
    display: flex;
    align-items: flex-start;
    gap: 10px;
    margin-bottom: 13px;
  }
  .rh-main {
    display: flex;
    align-items: baseline;
    gap: 10px;
    min-width: 0;
  }
  .rh-actions {
    margin-left: auto;
    display: flex;
    gap: 4px;
    flex: 0 0 auto;
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
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  .banner {
    display: flex;
    align-items: center;
    gap: 6px;
    font-size: 11.5px;
    color: #b26a00;
    background: rgba(255, 159, 10, 0.12);
    border-radius: 8px;
    padding: 7px 10px;
    margin-bottom: 12px;
  }

  .grid {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 0 22px;
    border: 1px solid var(--separator-soft);
    border-radius: 10px;
    padding: 9px 14px;
  }
  .grid.inner {
    margin: 2px 14px 10px;
    border: 0;
    padding: 0;
    gap: 0 22px;
  }
  .kv {
    display: flex;
    gap: 10px;
    padding: 4px 0;
    font-size: 12px;
    border-bottom: 1px solid var(--separator-soft);
    min-width: 0;
  }
  .kv:last-child {
    border-bottom: 0;
  }
  .k {
    color: var(--text-3);
    flex: 0 0 auto;
    min-width: 72px;
  }
  .v {
    color: var(--text);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .v.mono {
    font-family: ui-monospace, 'SF Mono', Menlo, monospace;
    font-size: 11px;
  }

  .sec-head {
    display: flex;
    align-items: baseline;
    gap: 10px;
    margin: 18px 0 8px;
  }
  .sec-h {
    font-size: 11px;
    font-weight: 600;
    color: var(--text-3);
    letter-spacing: 0.02em;
    flex: 0 0 auto;
  }
  .sec-note {
    font-size: 10.5px;
    color: var(--text-3);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .sec-head .btn {
    margin-left: auto;
    flex: 0 0 auto;
  }
  .tiny {
    height: 21px;
    font-size: 10.5px;
    padding: 0 7px;
  }

  .chips {
    display: flex;
    gap: 6px;
    flex-wrap: wrap;
  }
  .chip {
    display: inline-flex;
    align-items: baseline;
    gap: 5px;
    font-size: 11.5px;
    color: var(--text-2);
    background: var(--fill);
    border-radius: 8px;
    padding: 4px 9px;
  }
  .chip b {
    font-family: ui-monospace, 'SF Mono', Menlo, monospace;
    font-size: 11.5px;
    font-weight: 600;
    color: var(--text);
  }
  .chip.ok {
    background: rgba(48, 209, 88, 0.12);
    color: #1c7c36;
  }
  .chip.ok b {
    color: #1c7c36;
  }
  .chip.warn {
    background: rgba(255, 69, 58, 0.12);
    color: #c0392b;
  }
  .chip.warn b {
    color: #c0392b;
  }
  .chip.soft {
    background: rgba(255, 159, 10, 0.13);
    color: #b26a00;
  }
  .chip.soft b {
    color: #b26a00;
  }
  .chip.muted {
    background: transparent;
    color: var(--text-3);
    border: 1px solid var(--separator-soft);
  }
  html[data-theme='dark'] .chip.ok,
  html[data-theme='dark'] .chip.ok b {
    color: #4cd964;
  }
  html[data-theme='dark'] .chip.warn,
  html[data-theme='dark'] .chip.warn b {
    color: #ff7b70;
  }
  html[data-theme='dark'] .chip.soft,
  html[data-theme='dark'] .chip.soft b {
    color: #ffb340;
  }

  .sections {
    border: 1px solid var(--separator-soft);
    border-radius: 10px;
    overflow: hidden;
  }
  .sec {
    border-bottom: 1px solid var(--separator-soft);
  }
  .sec:last-child {
    border-bottom: 0;
  }
  .sec.params {
    margin-top: 14px;
    border: 1px solid var(--separator-soft);
    border-radius: 10px;
  }
  summary {
    display: flex;
    align-items: baseline;
    gap: 10px;
    padding: 8px 14px;
    font-size: 12.5px;
    cursor: default;
    list-style: none;
  }
  summary::-webkit-details-marker {
    display: none;
  }
  summary:hover {
    background: var(--row-hover);
  }
  .st {
    width: 112px;
    flex: 0 0 112px;
    color: var(--text-2);
  }
  .sh {
    flex: 1;
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .sh.muted,
  .muted {
    color: var(--text-3);
  }
  .sn {
    font-size: 10.5px;
    color: var(--text-3);
    font-variant-numeric: tabular-nums;
    flex: 0 0 auto;
  }

  .note {
    font-size: 11px;
    color: var(--text-2);
    padding: 0 14px 7px;
    line-height: 1.5;
  }
  .items {
    padding: 0 14px 8px;
  }
  .item {
    display: flex;
    align-items: baseline;
    gap: 9px;
    padding: 4px 0;
    border-top: 1px solid var(--separator-soft);
    font-size: 11.5px;
    min-width: 0;
  }
  .time-link {
    appearance: none;
    border: 0;
    background: transparent;
    font-family: ui-monospace, 'SF Mono', Menlo, monospace;
    font-size: 10.5px;
    color: var(--accent);
    padding: 0;
    flex: 0 0 auto;
    font-variant-numeric: tabular-nums;
  }
  .time-link:hover {
    text-decoration: underline;
  }
  .tag {
    font-size: 10px;
    color: var(--text-2);
    background: var(--fill);
    border-radius: 6px;
    padding: 0 5px;
    flex: 0 0 auto;
  }
  .dur,
  .peak {
    font-size: 10px;
    color: var(--text-3);
    font-variant-numeric: tabular-nums;
    flex: 0 0 auto;
  }
  .it-text {
    flex: 1;
    min-width: 0;
    color: var(--text);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .saved-line {
    display: flex;
    align-items: center;
    gap: 7px;
    margin: 0 0 9px;
    min-width: 0;
    font-size: 11px;
    color: var(--text-3);
  }
  .saved-ok {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    flex: 0 0 auto;
    color: #1c7c36;
  }
  .saved-line .path {
    flex: 1;
    min-width: 0;
  }
  .saved-line .btn {
    flex: 0 0 auto;
  }

  .export-row {
    display: flex;
    align-items: center;
    gap: 6px;
    flex-wrap: wrap;
  }
  .path {
    font-size: 10.5px;
    color: var(--text-3);
    font-family: ui-monospace, 'SF Mono', Menlo, monospace;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    max-width: 420px;
  }
</style>
