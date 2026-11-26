<script lang="ts">
  /**
   * 底栏右侧的「工作草稿」状态与暂存入口。
   *
   * 2026-11-24（Phase 1）从检查器底部的 `save-dock` 搬过来：那块卡片同时装了
   * 「暂存」和「导出」，在标准窗口高度下会吃掉检查器的可滚动高度（2026-11-21
   * 用户报障过 TTS 面板被它截断）。拆开之后职责更清楚：
   *
   * - **暂存**（防丢备份）留在核对期一直可见的位置 —— 底栏，且只在核对屏出现；
   * - **导出**（交付文件）走顶栏「导出」按钮与导出视图，不在这里重复一套格式/轨选择。
   *
   * 语义不变：`暂存` 只写运行数据目录的 `{stem}.autosave_draft.srt`，不覆盖交付文件；
   * 恢复草稿仍压入撤回栈（⌘Z 可一步退回）。
   */
  import Icon from './Icon.svelte';
  import { app, restoreDraft, reviewDraft, saveDraft } from '../lib/store.svelte';

  const label = $derived.by(() => {
    if (reviewDraft.saving) return '正在暂存…';
    if (!reviewDraft.exists) return '尚未暂存';
    const when = new Date(reviewDraft.saved_at * 1000).toLocaleString('zh-CN', {
      month: 'numeric',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
      hour12: false,
    });
    return `已暂存 ${when} · ${reviewDraft.count} 条`;
  });

  const title = $derived(
    reviewDraft.path
      ? `把当前全部字幕写入工作草稿 ${reviewDraft.path}，不会覆盖导出文件`
      : '把当前核对台的全部字幕写入工作草稿，防止应用关闭或崩溃后丢失',
  );
</script>

<div class="draft-dock">
  <span class="dd-state" class:pending={!reviewDraft.exists}>{label}</span>
  {#if reviewDraft.exists}
    <button
      class="dd-link"
      onclick={() => void restoreDraft()}
      disabled={reviewDraft.restoring}
      title="用工作草稿覆盖核对台（压入撤回栈，⌘Z 可一步退回）"
    >
      {reviewDraft.restoring ? '恢复中…' : '恢复'}
    </button>
  {/if}
  <button
    class="dd-save"
    onclick={() => void saveDraft()}
    disabled={!app.cues.length || reviewDraft.saving}
    {title}
  >
    <Icon name="save" size={11} />
    暂存
  </button>
</div>

<style>
  .draft-dock {
    display: flex;
    align-items: center;
    gap: var(--sp-2);
    min-width: 0;
  }
  .dd-state {
    font-size: 12px;
    line-height: 16px;
    color: var(--text-3);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  /* 「尚未暂存」是常规状态而不是风险：静默灰 + 小圆点，不靠颜色报警
     （与检查器原 save-dock 的 G17 口径一致）。 */
  .dd-state.pending::before {
    content: '';
    display: inline-block;
    width: 5px;
    height: 5px;
    margin-right: 5px;
    border-radius: 50%;
    background: currentColor;
    vertical-align: 1px;
  }
  .dd-link {
    appearance: none;
    border: 0;
    background: transparent;
    color: var(--accent-text);
    font: inherit;
    font-size: 12px;
    padding: 0 2px;
    border-radius: 3px;
  }
  .dd-link:hover:not(:disabled) {
    text-decoration: underline;
  }
  .dd-save {
    appearance: none;
    height: 20px;
    padding: 0 var(--sp-2);
    display: inline-flex;
    align-items: center;
    gap: var(--sp-1);
    border: 1px solid var(--line);
    border-radius: 4px;
    background: var(--raise);
    color: var(--text-2);
    font: inherit;
    font-size: 12px;
    white-space: nowrap;
    transition: border-color var(--dur-fast) var(--ease), color var(--dur-fast) var(--ease);
  }
  .dd-save:hover:not(:disabled) {
    border-color: var(--accent-line);
    color: var(--accent-text);
  }
  .dd-save:disabled {
    color: var(--ink-muted);
  }
  .dd-save:focus-visible,
  .dd-link:focus-visible {
    outline: 2px solid var(--accent-ring);
    outline-offset: 1px;
  }
</style>
