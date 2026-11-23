<script lang="ts">
  /**
   * 检查器底部的只读信息：当前字幕来源 / 质检速览 / 生效参数 / 输出。
   *
   * 2026-11-21 从 Inspector.svelte 抽出来（Step 3）。这些是**读**的内容，不参与
   * 核对操作；抽成独立组件后，`Inspector` 只剩页签、当前条目与保存栏。
   *
   * 「换了一版字幕（导入 / 恢复草稿）后不要引用上一次转写的数字」这条规则
   * 仍然在这里唯一实现：`report` 会按 `review_source.job_id` 校验，对不上就当
   * 没有报告。
   */
  import Icon from '../Icon.svelte';
  import { app, setView } from '../../lib/store.svelte';

  /**
   * 当前核对表的来源决定右侧信息能不能引用「最近一次转写」：
   * - transcription：报告/参数/质检都属于这张表；
   * - import / draft：换了一版字幕，旧报告已经对不上，不能再展示它的数字。
   */
  const source = $derived(app.reviewSource);
  const imported = $derived(source?.kind === 'import' || source?.kind === 'draft');
  const sourceLabel = $derived(
    source?.kind === 'import'
      ? '手动导入'
      : source?.kind === 'draft'
        ? '暂存草稿'
        : source?.kind === 'transcription'
          ? '本次转写'
          : '未记录',
  );
  const report = $derived.by(() => {
    if (imported) return null;
    const data = app.report;
    if (!data) return null;
    // 任务 id 都已知时必须一致：否则是上一部片 / 上一次转写的报告。
    const sourceJob = source?.job_id || '';
    if (sourceJob && data.job_id && sourceJob !== data.job_id) return null;
    return data;
  });
  const reportStale = $derived(Boolean(app.report && !imported && !report));
  const quality = $derived(report?.quality ?? null);
  const outputName = $derived.by(() => {
    if (source?.name) return source.name;
    if (report?.out_filename) return report.out_filename;
    const fromReport = report?.overview?.find((r) => r.label === '字幕文件名')?.value;
    return fromReport ?? app.media?.name ?? '—';
  });
  const sourcePath = $derived(source?.path || '');
</script>

  {#if imported}
    <!--
      换了一版字幕（导入 / 恢复草稿）后，转写报告与质检队列属于另一版内容。
      这里不再展示它们的数字，改用当前字幕自己的来源与条数，避免“面板说 A、
      核对台在用 B”。
    -->
    <div class="meta-sec">
      <div class="meta-h">当前字幕</div>
      <div class="source-row">
        <span class="source-badge">{sourceLabel}</span>
        <span class="source-name" title={sourcePath || outputName}>{outputName}</span>
      </div>
      <p class="meta-note">
        质检速览与生效参数属于这次转写，和当前导入的字幕不是同一版；整片转写后会重新生成。
      </p>
      {#if app.media}
        <button class="meta-link" onclick={() => setView('transcribe')}>
          去转写
          <Icon name="chevron-right" size={10} />
        </button>
      {/if}
    </div>
  {:else if quality}
    <div class="meta-sec">
      <div class="meta-h">质检速览</div>
      <div class="chips">
        <span
          class="chip"
          class:ok={(quality.coverage ?? 0) === 0}
          class:warn={(quality.coverage ?? 0) > 0}
        >
          漏检 <b>{quality.coverage ?? 0}</b>
        </span>
        <span
          class="chip"
          class:ok={(quality.low_confidence ?? 0) === 0}
          class:warn={(quality.low_confidence ?? 0) > 0}
        >
          低置信 <b>{quality.low_confidence ?? 0}</b>
        </span>
      </div>
    </div>
  {/if}

  {#if !imported}
    <div class="meta-sec">
      <div class="meta-h">生效参数</div>
      {#if report?.params?.length}
        {#each report.params.slice(0, 6) as row (row.label)}
          <div class="kv"><span class="k">{row.label}</span><span class="v">{row.value}</span></div>
        {/each}
      {:else}
        <div class="kv"><span class="k">设备</span><span class="v mono">{app.config?.device ?? '—'}</span></div>
        <div class="kv"><span class="k">引擎</span><span class="v">{app.config?.engines?.find((e) => e.key === app.engine)?.label ?? '—'}</span></div>
        <div class="kv"><span class="k">版本</span><span class="v mono">v{app.config?.version ?? '—'}</span></div>
        <div class="kv"><span class="k">参数</span><span class="v muted">转写后可见</span></div>
      {/if}
      {#if reportStale}
        <p class="meta-note">报告属于另一次转写，已隐藏；重新整片转写后会恢复。</p>
      {/if}
    </div>
  {/if}

  <div class="meta-sec">
    <div class="meta-h">输出</div>
    <div class="kv">
      <span class="k">文件</span>
      <span class="v mono" title={sourcePath || outputName}>{outputName}</span>
    </div>
    <div class="kv"><span class="k">条数</span><span class="v">{app.cues.length} 条</span></div>
    <div class="kv">
      <span class="k">字符</span>
      <span class="v">{app.cues.reduce((n, c) => n + c.text.length, 0)} 字</span>
    </div>
  </div>


<style>
  /* G16：检查器三层信息的层级原来几乎是平的 ——
     分区标题 12/600、字段键 12.5/400、值 12/400，键比标题还大。
     现在把三层拉开：标题 12.5/600 + 字距（像小标题）往下靠上，键降为 12/400/ink-3 退后，
     值 12.5/500/ink 作为可读内容。分区线保留并稍微拉开，让「参数块」有起点。 */
  .meta-sec {
    margin-top: var(--sp-4);
    padding: var(--sp-3) 0 0;
    border-top: 1px solid var(--line-2);
  }
  .meta-h {
    font-size: 12.5px;
    line-height: 17px;
    font-weight: 600;
    color: var(--ink-2);
    letter-spacing: 0.03em;
    margin-bottom: 6px;
  }
  .source-row {
    display: flex;
    align-items: center;
    gap: 6px;
    min-width: 0;
    margin: 2px 0 5px;
  }
  .source-badge {
    flex: 0 0 auto;
    height: 18px;
    padding: 0 6px;
    border-radius: 4px;
    background: var(--accent-soft);
    color: var(--accent);
    font-size: 12px;
    line-height: 18px;
    font-weight: 500;
  }
  .source-name {
    min-width: 0;
    font-family: var(--font-mono);
    font-size: 12px;
    color: var(--ink-2);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .meta-note {
    margin: 6px 0 0;
    font-size: 12px;
    line-height: 17px;
    color: var(--ink-3);
  }
  .meta-link {
    appearance: none;
    border: 0;
    background: transparent;
    color: var(--accent);
    font: inherit;
    font-size: 12px;
    padding: var(--sp-1) 0 0;
    display: inline-flex;
    align-items: center;
    gap: 1px;
  }
  .meta-link:hover {
    text-decoration: underline;
  }
  .muted,
  .kv .v.muted {
    color: var(--ink-3);
    font-weight: 400;
  }
</style>
