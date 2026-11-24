<script lang="ts">
  /**
   * 「章节命名」设置项：模板 + 预览 + 保存。
   *
   * 模板是 `core/settings.py` 的 `chapter_name_template`（后端同一套收敛：
   * 没有占位符会补 ` {num}`、超长截前缀）。预览用 `lib/chapterNaming.ts` 的
   * 同一个函数，所见即所得——不另写一份替换逻辑。
   */
  import { app, updateSettings } from '../../../lib/store.svelte';
  import {
    DEFAULT_CHAPTER_TEMPLATE,
    formatChapterName,
    normalizeTemplate,
  } from '../../../lib/chapterNaming';

  const saved = $derived(
    normalizeTemplate(app.settings?.chapter_name_template ?? DEFAULT_CHAPTER_TEMPLATE),
  );
  /** null = 设置还没读到；读到后填一次，之后用户改什么都不再被覆盖。 */
  let draft = $state<string | null>(null);
  let busy = $state(false);

  $effect(() => {
    if (draft === null) draft = saved;
  });

  const current = $derived(draft ?? saved);
  const preview = $derived(formatChapterName(current, 3));
  const dirty = $derived(normalizeTemplate(current) !== saved);

  async function save() {
    busy = true;
    try {
      await updateSettings({ chapter_name_template: current });
    } finally {
      busy = false;
    }
  }

  function reset() {
    draft = DEFAULT_CHAPTER_TEMPLATE;
  }
</script>

<div class="set-group">
  <div class="set-row">
    <div class="set-row-main">
      <span class="set-row-title">章节名称模板</span>
      <span class="set-row-desc">
        {'{num}'} 是中文序号、{'{n}'} 是阿拉伯数字；第三段会叫「{preview}」。
      </span>
    </div>
    <div class="set-row-ctl">
      <input
        class="name-input"
        type="text"
        maxlength="40"
        aria-label="章节名称模板"
        bind:value={draft}
        onkeydown={(e) => {
          if (e.key === 'Enter') {
            e.preventDefault();
            void save();
          }
        }}
      />
      <button class="btn sm" onclick={save} disabled={busy || !dirty}>
        {busy ? '保存中…' : '保存'}
      </button>
      <button
        class="btn sm ghost"
        onclick={reset}
        disabled={busy || current === DEFAULT_CHAPTER_TEMPLATE}
      >
        恢复默认
      </button>
    </div>
  </div>
</div>

<style>
  .name-input {
    flex: 0 1 190px;
    min-width: 120px;
    height: 26px;
    padding: 0 var(--sp-2);
    border-radius: var(--rad-control);
    border: 1px solid var(--line);
    background: var(--field);
    color: var(--text);
    font-size: 12px;
  }
</style>
