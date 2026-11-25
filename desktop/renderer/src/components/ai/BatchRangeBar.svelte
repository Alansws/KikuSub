<script lang="ts">
  /**
   * 「本次处理批次」：在已选处理范围（全片 / 章节 / 自定义时间）之内，再按条号
   * 切一小段处理（如 1–151、152–291）。
   *
   * 纯展示 + 事件：批次状态由调用方持有（润色/翻译在 `aiWorkspace`，断句重排在
   * `reshape`），夹紧与步进全部走 `lib/cueBatch.ts` 的纯函数。这样切页、改文字、
   * 换范围都不会把「当前批次」弄丢或算错。
   */
  import {
    DEFAULT_BATCH_SIZE,
    batchLabel,
    type CueRange,
  } from '../../lib/cueBatch';

  let {
    from = 1,
    to = 1,
    spanFrom = 1,
    spanTo = 1,
    count = 0,
    total = 0,
    size = DEFAULT_BATCH_SIZE,
    manual = false,
    disabled = false,
    onApply,
    onStep,
    onSize,
    onReset,
  }: {
    /** 当前批次（1 基、含两端）；会被夹进 span。 */
    from?: number;
    to?: number;
    /** 处理范围命中的区间（批次不能越出它）。 */
    spanFrom?: number;
    spanTo?: number;
    /** 批次命中条数 / 全片条数。 */
    count?: number;
    total?: number;
    size?: number;
    /** 是否已经从「整段」切到手动批次。 */
    manual?: boolean;
    disabled?: boolean;
    onApply?: (from: number, to: number) => void;
    onStep?: (direction: 1 | -1) => void;
    onSize?: (size: number) => void;
    onReset?: () => void;
  } = $props();

  let fromText = $state('');
  let toText = $state('');
  let sizeText = $state('');
  let editing = $state(false);
  let sizeEditing = $state(false);

  $effect(() => {
    if (!editing) {
      fromText = String(from);
      toText = String(to);
    }
  });
  $effect(() => {
    if (!sizeEditing) sizeText = String(size);
  });

  const current = $derived<CueRange>({ from, to });
  const atStart = $derived(from <= spanFrom);
  const atEnd = $derived(to >= spanTo);

  function commitRange() {
    editing = false;
    const first = Number.parseInt(fromText, 10);
    const last = Number.parseInt(toText, 10);
    if (!Number.isFinite(first) || !Number.isFinite(last)) {
      fromText = String(from);
      toText = String(to);
      return;
    }
    onApply?.(first, last);
  }

  function commitSize() {
    sizeEditing = false;
    const next = Number.parseInt(sizeText, 10);
    if (!Number.isFinite(next) || next < 1) {
      sizeText = String(size);
      return;
    }
    onSize?.(Math.min(5000, next));
  }

  function onKey(event: KeyboardEvent, commit: () => void) {
    if (event.key === 'Enter') {
      event.preventDefault();
      commit();
      (event.currentTarget as HTMLInputElement).blur();
    } else if (event.key === 'Escape') {
      event.preventDefault();
      editing = false;
      sizeEditing = false;
      fromText = String(from);
      toText = String(to);
      sizeText = String(size);
    }
  }
</script>

<div class="cue-batch" class:manual aria-label="本次处理批次">
  <span class="batch-label">本次批次</span>
  <input
    class="batch-no"
    type="text"
    inputmode="numeric"
    value={fromText}
    onfocus={() => (editing = true)}
    oninput={(event) => {
      editing = true;
      fromText = event.currentTarget.value;
    }}
    onblur={commitRange}
    onkeydown={(event) => onKey(event, commitRange)}
    title="本批起始条号（全片序号）"
    aria-label="本次批次起始条号"
    {disabled}
  />
  <span class="batch-tilde" aria-hidden="true">~</span>
  <input
    class="batch-no"
    type="text"
    inputmode="numeric"
    value={toText}
    onfocus={() => (editing = true)}
    oninput={(event) => {
      editing = true;
      toText = event.currentTarget.value;
    }}
    onblur={commitRange}
    onkeydown={(event) => onKey(event, commitRange)}
    title="本批结束条号（全片序号）"
    aria-label="本次批次结束条号"
    {disabled}
  />
  <span class="batch-count" title="本批命中条数 / 全片条数">
    {#if count > 0}<b>{batchLabel(current)}</b> · {count}/{total} 条{:else}范围内没有字幕{/if}
  </span>
  <button
    class="batch-step"
    onclick={() => onStep?.(-1)}
    disabled={disabled || atStart}
    title="上一批（按每批条数回退）"
  >‹ 上一批</button>
  <button
    class="batch-step"
    onclick={() => onStep?.(1)}
    disabled={disabled || atEnd}
    title="下一批（从本批结束后继续）"
  >下一批 ›</button>
  <label class="batch-size" title="每批条数：上一批 / 下一批按它步进">
    每批
    <input
      class="batch-size-no"
      type="text"
      inputmode="numeric"
      value={sizeText}
      onfocus={() => (sizeEditing = true)}
      oninput={(event) => {
        sizeEditing = true;
        sizeText = event.currentTarget.value;
      }}
      onblur={commitSize}
      onkeydown={(event) => onKey(event, commitSize)}
      aria-label="每批条数"
      {disabled}
    />
    条
  </label>
  {#if manual}
    <button class="batch-reset" onclick={() => onReset?.()} title="回到整个处理范围" {disabled}>
      整段
    </button>
  {/if}
</div>

<style>
  .cue-batch {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    min-width: 0;
    flex-wrap: wrap;
    padding: 2px 6px;
    border: 1px solid var(--well-line);
    border-radius: 6px;
    background: var(--well);
    font-size: 11.5px;
    color: var(--text-3);
  }
  .cue-batch.manual {
    border-color: var(--accent-soft);
    background: var(--accent-soft);
  }
  .batch-label {
    white-space: nowrap;
  }
  .batch-no,
  .batch-size-no {
    width: 44px;
    font: inherit;
    font-variant-numeric: tabular-nums;
    text-align: center;
    padding: 1px 3px;
    border-radius: 4px;
    border: 1px solid var(--well-line);
    background: var(--well);
    color: var(--text);
    outline: none;
  }
  .batch-no:focus,
  .batch-size-no:focus {
    border-color: var(--accent);
    box-shadow: 0 0 0 2px var(--accent-soft);
  }
  .batch-size-no {
    width: 36px;
  }
  .batch-tilde {
    color: var(--text-3);
  }
  .batch-count {
    font-variant-numeric: tabular-nums;
    white-space: nowrap;
  }
  .batch-count b {
    color: var(--text);
  }
  .batch-step,
  .batch-reset {
    border: 0;
    background: transparent;
    color: var(--accent);
    font: inherit;
    font-size: 11.5px;
    cursor: pointer;
    padding: 1px 3px;
    white-space: nowrap;
  }
  .batch-step:disabled,
  .batch-reset:disabled {
    color: var(--text-3);
    cursor: default;
  }
  .batch-reset {
    color: var(--text-2);
  }
  .batch-size {
    display: inline-flex;
    align-items: center;
    gap: 3px;
    white-space: nowrap;
  }
</style>
