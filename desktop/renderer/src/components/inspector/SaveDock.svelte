<script lang="ts">
  /**
   * 右侧栏底部常驻的保存区：暂存工作草稿 / 导出交付文件。
   *
   * 2026-11-21 从 Inspector.svelte 抽出来（Step 3）。两条语义不能混：
   * `暂存` 只写运行数据目录里的 `{stem}.autosave_draft.srt`（防丢，不覆盖交付文件）；
   * `导出` 写设置里的导出文件夹，不依赖「详情与导出」是否有任务报告。
   *
   * 它在 `.ins-scroll` 之外（flex 列的最后一项），内容滚动时不会盖住它；
   * 反过来说，上面那个滚动区也必须给它留出高度——可操作的控件不该滑到它下面
   * （2026-11-21 之前的「TTS 对照」大卡片就是被它截断的）。
   */
  import Icon from '../Icon.svelte';
  import {
    app,
    exportCues,
    restoreDraft,
    reviewDraft,
    saveDraft,
  } from '../../lib/store.svelte';
  import type { TrackMode } from '../../lib/api';

  let exportFormat = $state<'SRT' | 'VTT' | 'TXT'>('SRT');
  let exportTrack = $state<'source' | 'target' | 'both'>('source');
  let exporting = $state(false);

  const hasTrack = $derived(Boolean(app.translations[app.trackLang]));
  const exportNeedsTrack = $derived(exportTrack !== 'source');
  const draftLabel = $derived.by(() => {
    if (reviewDraft.saving) return '正在暂存…';
    if (!reviewDraft.exists) return '尚未暂存';
    const when = new Date(reviewDraft.saved_at * 1000).toLocaleString('zh-CN', {
      month: 'numeric',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
      hour12: false,
    });
    return `上次暂存 ${when} · ${reviewDraft.count} 条`;
  });

  async function doExport() {
    if (exporting) return;
    exporting = true;
    try {
      // 译文/双语导出必须带语种；没有对应轨时按钮本来就是禁用的
      await exportCues(exportFormat, {
        track: exportTrack as TrackMode,
        lang: exportTrack === 'source' ? '' : app.trackLang,
      });
    } finally {
      exporting = false;
    }
  }
</script>

  <div class="save-dock">
    <div class="sd-head">
      <span class="sd-title">保存</span>
      <span class="sd-state" class:warn={!reviewDraft.exists}>{draftLabel}</span>
    </div>
    <div class="sd-row">
      <button
        class="btn ghost sd-save"
        onclick={() => saveDraft()}
        disabled={!app.cues.length || reviewDraft.saving}
        title={reviewDraft.path
          ? `把当前全部字幕写入工作草稿 ${reviewDraft.path}，不会覆盖导出文件`
          : '把当前核对台的全部字幕写入工作草稿，防止应用关闭或崩溃后丢失'}
      >
        <Icon name="save" size={11} />{reviewDraft.saving ? '暂存中' : '暂存'}
      </button>
      <select
        class="sd-fmt"
        bind:value={exportTrack}
        disabled={exporting}
        title="导出内容：原文 / 仅译文 / 双语（同一时间轴下原文、译文各一条）"
      >
        <option value="source">原文</option>
        <option value="target" disabled={!hasTrack}>译文</option>
        <option value="both" disabled={!hasTrack}>双语</option>
      </select>
      <select
        class="sd-fmt"
        bind:value={exportFormat}
        disabled={exporting}
        title="导出格式"
      >
        <option value="SRT">SRT</option>
        <option value="VTT">VTT</option>
        <option value="TXT">TXT</option>
      </select>
      <button
        class="btn primary sd-export"
        onclick={doExport}
        disabled={!app.cues.length || exporting || (exportNeedsTrack && !hasTrack)}
        title={app.config?.export_dir
          ? `把核对台当前时间轴导出到 ${app.config.export_dir}`
          : '把核对台当前时间轴导出到导出文件夹'}
      >
        <Icon name="export" size={11} />{exporting ? '导出中' : '导出字幕'}
      </button>
    </div>
    {#if reviewDraft.exists || app.lastExportPath}
      <div class="sd-foot">
        {#if reviewDraft.exists}
          <button
            class="sd-link"
            onclick={restoreDraft}
            disabled={reviewDraft.restoring}
            title="用工作草稿覆盖核对台（压入撤回栈，⌘Z 可一步退回）"
          >
            {reviewDraft.restoring ? '正在恢复…' : '恢复上次暂存'}
          </button>
        {/if}
        {#if app.lastExportPath}
          <button
            class="sd-link"
            onclick={() => window.kikusub.revealInFinder(app.lastExportPath)}
            title={app.lastExportPath}
          >
            最近导出：{app.lastExportPath.split('/').pop()}
          </button>
        {/if}
      </div>
    {/if}
  </div>

<style>
  .save-dock {
    flex: 0 0 auto;
    padding: 10px var(--sp-5) var(--sp-3);
    border-top: 1px solid var(--line);
    background: var(--paper);
    box-shadow: 0 -10px 20px -18px rgba(27, 39, 64, 0.35);
    display: flex;
    flex-direction: column;
    gap: 6px;
  }
  .sd-head {
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    gap: var(--sp-2);
    min-width: 0;
  }
  .sd-title {
    font-size: 12px;
    line-height: 16px;
    font-weight: 600;
    color: var(--ink-2);
    letter-spacing: 0.02em;
    flex: 0 0 auto;
  }
  .sd-state {
    font-size: 12px;
    line-height: 16px;
    color: var(--ink-3);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  /* G17：「尚未暂存」是常规状态，不是风险 —— 原来用 --warn 金，
     会和「改动率 100%」这类真警告撞色。改为静默灰 + 一个小圆点，
     仍能看出「有未存的状态」，但不靠颜色报警。 */
  .sd-state.warn {
    color: var(--ink-3);
  }
  .sd-state.warn::before {
    content: '';
    display: inline-block;
    width: 5px;
    height: 5px;
    margin-right: 5px;
    border-radius: 50%;
    background: currentColor;
    vertical-align: 1px;
  }
  .sd-row {
    display: flex;
    align-items: center;
    gap: 5px;
  }
  .sd-save {
    flex: 1;
    justify-content: center;
    min-width: 0;
  }
  .sd-fmt {
    height: 26px;
    width: 54px;
    flex: 0 0 54px;
    border-radius: 4px;
    border: 1px solid var(--line);
    background: var(--raise);
    color: var(--ink-2);
    font: inherit;
    font-size: 12px;
    padding: 0 2px 0 5px;
  }
  .sd-export {
    min-width: 64px;
    justify-content: center;
  }
  .sd-foot {
    display: flex;
    flex-direction: column;
    gap: 2px;
    min-width: 0;
  }
  .sd-link {
    appearance: none;
    border: 0;
    background: transparent;
    color: var(--accent);
    font: inherit;
    font-size: 12px;
    text-align: left;
    padding: 0;
    cursor: pointer;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .sd-link:hover:not(:disabled) {
    text-decoration: underline;
  }
  .sd-link:disabled {
    color: var(--ink-3);
  }
</style>
