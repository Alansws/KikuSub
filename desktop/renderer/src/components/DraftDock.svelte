<script lang="ts">
  /**
   * 底栏的「工作草稿」状态（只读）。
   *
   * 2026-11-25（Cue Script）：底栏回到**只读状态条**——HIG 明确说不要把关键
   * 动作放底栏（`windows.md › Desktop (macOS)`）。暂存 / 恢复移到「文件」菜单
   * （⌘S / 恢复工作草稿…），这里只报告「上一次暂存是什么时候、几条」。
   *
   * 语义不变：`暂存` 只写运行数据目录的 `{stem}.autosave_draft.srt`，不覆盖交付文件；
   * 恢复草稿仍压入撤回栈（⌘Z 可一步退回）。
   */
  import { reviewDraft } from '../lib/store.svelte';

  const label = $derived.by(() => {
    if (reviewDraft.saving) return '正在暂存…';
    if (!reviewDraft.exists) return '草稿未暂存';
    const when = new Date(reviewDraft.saved_at * 1000).toLocaleTimeString('zh-CN', {
      hour: '2-digit',
      minute: '2-digit',
      hour12: false,
    });
    return `已暂存 ${when} · ${reviewDraft.count} 条`;
  });

  const title = $derived.by(() => {
    if (!reviewDraft.path) return '工作草稿会用「文件 → 暂存工作草稿（⌘S）」写入运行数据目录';
    return `工作草稿：${reviewDraft.path}（⌘S 暂存，不影响导出文件）`;
  });
</script>

<span class="draft-state" class:pending={!reviewDraft.exists} {title}>
  {label}
</span>

<style>
  .draft-state {
    font-size: 11px;
    line-height: 16px;
    color: var(--text-3);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  /* 「尚未暂存」是常规状态而不是风险：静默灰 + 小圆点，不靠颜色报警 */
  .draft-state.pending::before {
    content: '';
    display: inline-block;
    width: 5px;
    height: 5px;
    margin-right: 5px;
    border-radius: 50%;
    background: currentColor;
    vertical-align: 1px;
  }
</style>
