<script lang="ts">
  /**
   * 模板选择：`模板` 标签 + 下拉框。
   *
   * 之前润色页把当前模板名既写成静态文字又塞进下拉框，读起来像两件事。
   * 模板名只属于下拉框，标签只负责说明这一格是什么。
   */
  let {
    items,
    value,
    title = '提示词模板',
    onchange,
  }: {
    items: { id: string; name: string }[];
    value: string;
    title?: string;
    onchange: (id: string) => void;
  } = $props();
</script>

{#if items.length}
  <label class="aiw-template">
    <span class="aiw-label">模板</span>
    <select
      class="aiw-select"
      {title}
      {value}
      onchange={(event) => onchange(event.currentTarget.value)}
    >
      {#each items as item (item.id)}
        <option value={item.id}>{item.name}</option>
      {/each}
    </select>
  </label>
{/if}
