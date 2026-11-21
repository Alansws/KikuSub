<script lang="ts">
  /**
   * 「纠偏助手」：另一引擎复核（A/B 两版 + 逐字差异）与单句 AI 判定（听音线索）。
   *
   * 两块内容分别在 `SecondOpinionCard`（复核）与它挂载的 `ArbitrationCard`（AI 判定）
   * 里，这里只负责「在检查器里出现、并且只有这一份」——原来直接写在 Inspector
   * 模板里，抽出当前条目页以后，它的挂载点在 `CuePane`。
   *
   * 只在选中了字幕时挂载：没有当前句就没有可复核的对象。
   */
  import SecondOpinionCard from '../SecondOpinionCard.svelte';

  let { index, text }: { index: number; text: string } = $props();
</script>

<div class="assistant" aria-label="纠偏助手">
  <SecondOpinionCard {index} {text} />
</div>

<style>
  /* 复核 / AI 判定是「同一件事的两层」，整块上沿一条分隔线把它们和编辑区分开 */
  .assistant {
    margin-top: var(--sp-3);
    padding-top: var(--sp-2);
    border-top: 1px solid var(--line-2);
  }
</style>
