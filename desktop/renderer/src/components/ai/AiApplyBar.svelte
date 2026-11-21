<script lang="ts">
  /**
   * 底部应用条（润色 / 翻译共用）。
   *
   * 一条规则写在这里，两页就不会再漂移：**源文本已变化（digest 不符）时，
   * 主按钮必须禁用**，并明确说「请先重新生成」。以前润色页会同时亮着红色
   * 告警横幅和红色主提交按钮，看起来像是可以硬提交。
   */
  import type { Snippet } from 'svelte';

  let {
    applyLabel,
    accepted = 0,
    changed = 0,
    busy = false,
    requireAccepted = true,
    invalid = false,
    changedOnly = true,
    onChangedOnly,
    onAll,
    onApply,
    extra,
  }: {
    applyLabel: string;
    accepted?: number;
    changed?: number;
    busy?: boolean;
    /** 采纳数是否参与禁用（翻译页整版写轨，逐条 pin 只做标记，不决定写多少）。 */
    requireAccepted?: boolean;
    invalid?: boolean;
    changedOnly?: boolean;
    onChangedOnly: (value: boolean) => void;
    onAll: (value: boolean) => void;
    onApply: () => void;
    /** 额外的应用方式（润色页的「更多应用」菜单）。 */
    extra?: Snippet;
  } = $props();
</script>

<div class="aiw-applybar">
  {#if invalid}
    <span class="aiw-applybar-note danger">
      已失效 · 请先重新生成
    </span>
  {:else}
    <span class="aiw-hint">
      ⌘Z 一次整批退回{changed ? ` · 改动 ${changed}` : ''}{accepted && requireAccepted
        ? ` · 采纳 ${accepted}`
        : ''}
    </span>
  {/if}
  <div class="aiw-spacer"></div>
  <label class="aiw-check">
    <input
      type="checkbox"
      checked={changedOnly}
      onchange={(event) => onChangedOnly(event.currentTarget.checked)}
    />
    只看改动
  </label>
  <button class="aiw-link" onclick={() => onAll(true)}>全选</button>
  <button class="aiw-link" onclick={() => onAll(false)}>全不选</button>
  {@render extra?.()}
  <button
    class="btn primary"
    onclick={onApply}
    disabled={invalid || busy || (requireAccepted && accepted === 0)}
    title={invalid
      ? '源文本已变化：重新生成或重新粘贴后才能应用'
      : '只应用「已采纳且确有差异」的条目；⌘Z 一次全退'}
  >
    {busy ? '应用中…' : applyLabel}
  </button>
</div>

<style>
  .aiw-applybar-note {
    font-size: 12px;
    line-height: 18px;
  }
  .aiw-applybar-note.danger {
    color: var(--danger);
  }
</style>
