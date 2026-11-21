<script lang="ts">
  /**
   * 智能分段轨道：润色 / 断句重排共用。
   *
   * 自适应均分铺满内容宽度（auto-fit + 1fr），段数少时不会在右侧留一截空轨。
   * 每格固定呈现四件事：序号、完成状态点、条数、时间区间。文字不换行，
   * 段数多时由 minmax(148px, 1fr) 自动折行，不切成半格。
   */
  import type { AiSegment } from '../../lib/aiSegments';

  type SegmentState = 'done' | 'ready' | 'todo';

  let {
    segments,
    active = 0,
    status = () => 'todo',
    onselect,
    disabled = false,
    label = '',
    hint = '',
    badge = '',
    compact = false,
  }: {
    segments: AiSegment[];
    active?: number;
    status?: (segment: AiSegment, index: number) => SegmentState;
    onselect?: (index: number) => void;
    disabled?: boolean;
    label?: string;
    hint?: string;
    /** 轨道右侧的计数徽标（如「已覆盖 0/4 段」）；放在这里因为它只对多段有意义。 */
    badge?: string;
    /** 紧凑版（统一工作条里用）：单行细带，只留序号 / 条数 / 状态点。 */
    compact?: boolean;
  } = $props();

  function clock(value: number): string {
    const total = Math.max(0, Number(value) || 0);
    const hours = Math.floor(total / 3600);
    const minutes = Math.floor((total % 3600) / 60);
    const seconds = Math.floor(total % 60);
    const body = `${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`;
    return hours ? `${hours}:${body}` : body;
  }

  const stateLabel: Record<SegmentState, string> = {
    done: '已覆盖',
    ready: '已回填，待覆盖',
    todo: '还没开始',
  };
</script>

{#if segments.length}
  <div class="aiw-rail-wrap" class:compact>
    {#if label || hint || badge}
      <div class="aiw-rail-head">
        {#if label}<span>{label}</span>{/if}
        {#if badge}<span class="aiw-chip">{badge}</span>{/if}
        <span class="aiw-spacer"></span>
        {#if hint && !compact}<span>{hint}</span>{/if}
      </div>
    {/if}
    <div class="aiw-rail" class:compact role="group" aria-label={label || '智能分段'}>
      {#each segments as segment, index (segment.from)}
        {@const state = status(segment, index)}
        <button
          class="aiw-rail-item"
          class:on={index === active}
          class:done={state === 'done'}
          onclick={() => onselect?.(index)}
          disabled={disabled}
          aria-pressed={index === active}
          title={`第 ${segment.from}–${segment.to} 条 · ${clock(segment.start)}–${clock(segment.end)} · ${stateLabel[state]}`}
        >
          <span class="aiw-rail-no">{String(index + 1).padStart(2, '0')}</span>
          <span class="aiw-rail-body">
            <span class="aiw-rail-count">{segment.count} 条</span>
            <span class="aiw-rail-time">{clock(segment.start)}–{clock(segment.end)}</span>
          </span>
          <span class="aiw-rail-flag {state}" aria-hidden="true"><i></i></span>
        </button>
      {/each}
    </div>
  </div>
{/if}
