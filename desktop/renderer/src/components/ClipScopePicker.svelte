<script lang="ts">
  /**
   * 「处理范围 / 导出范围」选择器：润色、翻译、导出三处共用同一个组件。
   *
   * 范围本身只有一份状态（`store.exporter.clip`，进统一历史）：在润色页选了
   * 「章节1」，切到翻译页 / 导出页看到的还是它；在章节面板点「仅处理此片段」
   * 也是写同一份。这里只做三件事：
   *
   * 1. 列出**带 end 的区间章节**（时刻点不单独成项，否则「章节1」会被拆碎）；
   * 2. 自定义起止时间（`mm:ss` / `h:mm:ss` / 纯秒数都接受）；
   * 3. 显示命中条数（`291 / 899 条`）——与 `core.clip_range` 同一套边界规则。
   */
  import { chapters, loadChapters } from '../lib/chapters.svelte';
  import {
    FULL_CLIP,
    chapterScopeOptions,
    clipSpan,
    customScope,
    formatClock,
    matchedChapterId,
    normalizeClip,
    scopeForChapter,
    type ClipScope,
  } from '../lib/clipRange';
  import { app, exporter, setExportClip } from '../lib/store.svelte';
  import { parseTimeInput } from '../lib/time';

  let {
    compact = false,
    label = '处理范围',
    showCounts = true,
    disabled = false,
  }: {
    /** 紧凑版：润色 / 翻译页顶栏用（单行、无大边框）。 */
    compact?: boolean;
    label?: string;
    showCounts?: boolean;
    disabled?: boolean;
  } = $props();

  const duration = $derived(app.media?.duration || 0);
  const options = $derived(chapterScopeOptions(chapters.marks, duration));
  const scope = $derived(exporter.clip);
  const span = $derived(clipSpan(app.cues, scope));
  const activeId = $derived(matchedChapterId(scope, options));
  const total = $derived(app.cues.length);

  /** 自定义输入框的草稿；只在「自定义」模式出现。 */
  let startText = $state('');
  let endText = $state('');
  let editing = $state(false);

  $effect(() => {
    // 章节随影片保存：进入任一页面都把它读进来（换片后旧列表会被服务端清掉）。
    void app.media?.id;
    void loadChapters();
  });

  $effect(() => {
    if (editing) return;
    startText = formatClock(scope.start);
    endText = scope.end > 0 ? formatClock(scope.end) : '';
  });

  const selectValue = $derived(
    !(scope.end > 0) ? 'full' : activeId ? `chapter:${activeId}` : 'custom',
  );

  function applySelect(value: string) {
    if (disabled) return;
    if (value === 'full') {
      editing = false;
      setExportClip(FULL_CLIP);
      return;
    }
    if (value.startsWith('chapter:')) {
      const id = value.slice('chapter:'.length);
      const option = options.find((item) => item.id === id);
      if (!option) return;
      editing = false;
      setExportClip(scopeForChapter(option));
      return;
    }
    // 自定义：以当前范围起手，方便微调；当前是全片就从 0 开始
    editing = true;
    const base: ClipScope = scope.end > 0 ? scope : { start: 0, end: Math.min(120, duration || 120), label: '' };
    startText = formatClock(base.start);
    endText = base.end > 0 ? formatClock(base.end) : '';
  }

  function commitCustom() {
    if (disabled) return;
    const start = parseTimeInput(startText) ?? 0;
    const rawEnd = parseTimeInput(endText);
    const end = rawEnd === null ? Math.max(start, duration || start) : rawEnd;
    const next = normalizeClip(customScope(start, end), duration);
    if (!(next.end - next.start > 0)) return;
    editing = false;
    setExportClip(next);
  }

  function onCustomKey(event: KeyboardEvent) {
    if (event.key === 'Enter') {
      event.preventDefault();
      commitCustom();
    } else if (event.key === 'Escape') {
      event.preventDefault();
      editing = false;
    }
  }
</script>

<div class="clip-scope" class:compact class:on={scope.end > 0} aria-label={label}>
  <span class="clip-label">{label}</span>
  <select
    class="clip-select"
    value={selectValue}
    disabled={disabled}
    onchange={(event) => applySelect(event.currentTarget.value)}
    title="全片 / 区间章节 / 自定义起止时间；润色、翻译、导出共用这一份"
  >
    <option value="full">全片</option>
    {#each options as option (option.id)}
      <option value={`chapter:${option.id}`}>
        {option.title} · {formatClock(option.start)} → {formatClock(option.end)}
      </option>
    {/each}
    <option value="custom">自定义起止时间…</option>
  </select>

  {#if editing || selectValue === 'custom'}
    <span class="clip-custom">
      <input
        class="clip-time"
        type="text"
        bind:value={startText}
        onkeydown={onCustomKey}
        onblur={commitCustom}
        title="起点（mm:ss）"
        aria-label="片段起点"
        {disabled}
      />
      <span class="clip-arrow" aria-hidden="true">→</span>
      <input
        class="clip-time"
        type="text"
        bind:value={endText}
        onkeydown={onCustomKey}
        onblur={commitCustom}
        title="终点（mm:ss）；留空 = 片尾"
        aria-label="片段终点"
        {disabled}
      />
    </span>
  {/if}

  {#if showCounts && app.cues.length}
    <span class="clip-count" class:warn={scope.end > 0 && span.count === 0}>
      {#if scope.end > 0}
        命中 <b>{span.count}</b> / {total} 条
      {:else}
        共 <b>{total}</b> 条
      {/if}
    </span>
  {/if}

  {#if scope.end > 0 && span.count === 0}
    <span class="clip-warn">这个范围里没有字幕</span>
  {/if}
</div>

<style>
  .clip-scope {
    display: flex;
    align-items: center;
    gap: 6px;
    min-width: 0;
    flex-wrap: wrap;
    padding: 3px 6px;
    border: 1px solid var(--well-line);
    border-radius: 6px;
    background: var(--well);
  }
  .clip-scope.compact {
    padding: 1px var(--sp-1);
    border-color: transparent;
    background: transparent;
  }
  .clip-scope.on {
    border-color: var(--accent-soft);
    background: var(--accent-soft);
  }
  .clip-label {
    font-size: 11.5px;
    color: var(--text-3);
    white-space: nowrap;
  }
  .clip-select {
    font: inherit;
    font-size: 12px;
    max-width: 260px;
    padding: 2px 5px;
    border-radius: 4px;
    border: 1px solid var(--well-line);
    background: var(--well);
    color: var(--text);
  }
  .clip-custom {
    display: inline-flex;
    align-items: center;
    gap: 3px;
  }
  .clip-time {
    width: 62px;
    font: inherit;
    font-size: 12px;
    padding: 2px 5px;
    border-radius: 4px;
    border: 1px solid var(--well-line);
    background: var(--well);
    color: var(--text);
    font-variant-numeric: tabular-nums;
  }
  .clip-arrow {
    font-size: 11px;
    color: var(--text-3);
  }
  .clip-count {
    font-size: 11.5px;
    color: var(--text-3);
    font-variant-numeric: tabular-nums;
    white-space: nowrap;
  }
  .clip-count b {
    color: var(--text);
  }
  .clip-count.warn b {
    color: var(--danger);
  }
  .clip-warn {
    font-size: 11.5px;
    color: var(--danger);
    white-space: nowrap;
  }
</style>
