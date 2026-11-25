<script lang="ts">
  /**
   * 检查器底部的只读信息——2026-11-25（Step 4.2）按 `distill` 收成三件事：
   * **质检速览**（只在有问题时出现）、**当前字幕的来源**（只在换过稿时出现）、
   * **任务报告入口**。
   *
   * 删掉的是「生效参数（设备 / 引擎 / 版本 / 参数）」与「输出（文件 / 条数 / 字数）」：
   * 设备与引擎在底栏、条数与字数在底栏、文件名在标题栏，参数与版本属于任务报告——
   * 同一组读数在三处出现，正是用户说的「重复视觉噪音」。现在只在需要的地方出现一次，
   * 完整的一份留在「任务报告」里（这里是它在核对台的唯一入口）。
   *
   * 「换了一版字幕（导入 / 恢复草稿）后不要引用上一次转写的数字」这条规则仍然在这里
   * 唯一实现：`report` 会按 `review_source.job_id` 校验，对不上就当没有报告。
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
  const quality = $derived(report?.quality ?? null);
  const coverage = $derived(Number(quality?.coverage ?? 0));
  const lowConf = $derived(Number(quality?.low_confidence ?? 0));
  const outputName = $derived(source?.name || app.media?.name || '');
  const sourcePath = $derived(source?.path || '');
</script>

{#if imported}
  <!--
    换了一版字幕（导入 / 恢复草稿）后，转写报告与质检队列属于另一版内容。
    这里不再展示它们的数字，只说清「这一版是哪来的」，避免“面板说 A、核对台在用 B”。
  -->
  <div class="meta-sec">
    <div class="source-row">
      <span class="source-badge">{sourceLabel}</span>
      <span class="source-name" title={sourcePath || outputName}>{outputName || '—'}</span>
    </div>
    <p class="meta-note">
      质检速览与生效参数属于上一次转写，和这一版字幕对不上；整片转写后会重新生成。
    </p>
  </div>
{:else if coverage || lowConf}
  <div class="meta-sec">
    <div class="chips">
      {#if coverage}
        <span class="chip warn">漏检 <b>{coverage}</b></span>
      {/if}
      {#if lowConf}
        <span class="chip warn">低置信 <b>{lowConf}</b></span>
      {/if}
      <span class="meta-note inline">都在「质检待核」里逐条处理</span>
    </div>
  </div>
{/if}

{#if app.report && !imported}
  <button class="meta-link" onclick={() => setView('report')} title="这一趟转写的完整参数、耗时与漏句清单">
    任务报告
    <Icon name="chevron-right" size={10} />
  </button>
{/if}

<style>
  .meta-sec {
    margin-top: var(--sp-4);
    padding-top: var(--sp-3);
    border-top: 1px solid var(--line);
  }
  .meta-note {
    margin: 6px 0 0;
    font-size: 11.5px;
    line-height: 17px;
    color: var(--ink-3);
  }
  .meta-note.inline {
    margin: 0;
    flex: 1 1 auto;
    min-width: 90px;
  }
  .chips {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 6px;
  }
  .source-row {
    display: flex;
    align-items: center;
    gap: 6px;
    min-width: 0;
  }
  /* 来源是「值」不是「状态」：底色退到 fill，只有文字说明它是哪一版 */
  .source-badge {
    flex: 0 0 auto;
    height: 18px;
    padding: 0 6px;
    border-radius: 3px;
    background: var(--fill);
    color: var(--ink-2);
    font-size: 11px;
    line-height: 18px;
    font-weight: 500;
  }
  .source-name {
    min-width: 0;
    font-family: var(--font-mono);
    font-size: 11.5px;
    color: var(--ink-2);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .meta-link {
    appearance: none;
    border: 0;
    background: transparent;
    color: var(--ink-3);
    font: inherit;
    font-size: 12px;
    padding: var(--sp-3) 0 0;
    display: inline-flex;
    align-items: center;
    gap: 1px;
  }
  .meta-link:hover {
    color: var(--accent-text);
  }
</style>
