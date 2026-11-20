<script lang="ts">
  /**
   * 章节旗标 / 区间色条（时间轴顶部覆盖层）。
   *
   * 只做两件事：把当前视窗内的标记画在刻度区上面，并让单击旗标跳到章节起点。
   * 覆盖层本身 `pointer-events: none`，只有旗标可点——否则顶部的刻度擦洗会被
   * 整条色条吃掉（小红线：刻度条是专属 scrub 区）。
   *
   * 定位用百分比而不是像素：视窗缩放/平移时不需要重算 DOM 宽度，跟 canvas 里
   * 画的刻度天然对齐。
   */
  import type { ChapterMark } from '../lib/api';

  let {
    marks = [],
    duration = 0,
    viewStart = 0,
    viewSpan = 1,
    rulerH = 17,
    onseek = (_id: string, _start: number) => {},
  }: {
    marks: ChapterMark[];
    duration: number;
    viewStart: number;
    viewSpan: number;
    /** 顶部刻度条高度：色条贴在它的下沿，才不会被刻度文字盖住。 */
    rulerH?: number;
    onseek?: (id: string, start: number) => void;
  } = $props();

  const pct = (t: number) => ((t - viewStart) / (viewSpan || 1)) * 100;

  /** 展示用区间：结束时间取自己声明的 end，没有就取下一个标记起点（或片尾）。 */
  const items = $derived.by(() => {
    const ordered = [...marks].sort((a, b) => a.start - b.start);
    return ordered.map((mark, index) => {
      const next = ordered[index + 1]?.start ?? duration;
      const end = mark.end !== null ? Math.min(mark.end, next) : next;
      return { mark, start: mark.start, end: Math.max(mark.start, end) };
    });
  });

  /** 只渲染视窗附近（左右各留半屏），整片几百个标记时不至于塞满 DOM。 */
  const visible = $derived(
    items.filter(
      (item) =>
        item.end >= viewStart - viewSpan * 0.5 && item.start <= viewStart + viewSpan * 1.5,
    ),
  );

  function tc(seconds: number): string {
    const total = Math.max(0, seconds);
    const h = Math.floor(total / 3600);
    const m = Math.floor((total % 3600) / 60);
    const s = Math.floor(total % 60);
    const mm = String(m).padStart(2, '0');
    const ss = String(s).padStart(2, '0');
    return h > 0 ? `${h}:${mm}:${ss}` : `${mm}:${ss}`;
  }

  function tooltip(item: { mark: ChapterMark; start: number; end: number }): string {
    const kind = item.mark.end === null ? '时刻点' : '章节';
    return `${item.mark.title || '未命名'}（${kind} ${tc(item.start)} → ${tc(item.end)}）· 单击跳转`;
  }
</script>

{#if visible.length}
  <div class="chapter-track" style="top:{rulerH}px" aria-label="章节标记">
    <div class="band">
      {#each visible as item (item.mark.id)}
        <span
          class="range"
          class:point={item.mark.end === null}
          style="left:{pct(item.start)}%;width:{Math.max(0.12, pct(item.end) - pct(item.start))}%"
        ></span>
      {/each}
    </div>
    {#each visible as item (item.mark.id)}
      <button
        class="flag"
        class:point={item.mark.end === null}
        style="left:{pct(item.start)}%"
        title={tooltip(item)}
        aria-label={tooltip(item)}
        onclick={(e) => {
          e.stopPropagation();
          onseek(item.mark.id, item.start);
        }}
      >
        <i></i>
        <span class="flag-label">{item.mark.title || tc(item.start)}</span>
      </button>
    {/each}
  </div>
{/if}

<style>
  .chapter-track {
    position: absolute;
    left: 0;
    right: 0;
    height: 17px;
    /* 刻度擦洗属于 canvas：覆盖层整体不吃指针，只有旗标例外 */
    pointer-events: none;
    z-index: 3;
  }

  .band {
    position: absolute;
    inset: 0 0 auto 0;
    height: 6px;
  }

  .range {
    position: absolute;
    top: 0;
    height: 6px;
    border-radius: 2px;
    background: var(--accent);
    /* 底部一条深色边：与波形上方的字幕淡蓝区分开，不会读成「播放进度」 */
    box-shadow: inset 0 -1px 0 rgba(0, 0, 0, 0.28);
  }

  .range.point {
    /* 时刻点没有自己的区间：只留一个方块标记，避免看起来像一大段章节 */
    width: 6px !important;
    height: 6px;
    box-shadow: inset 0 0 0 1px rgba(0, 0, 0, 0.28);
  }

  .flag {
    position: absolute;
    top: 0;
    width: 10px;
    height: 15px;
    padding: 0;
    border: 0;
    background: transparent;
    transform: translateX(-2px);
    cursor: pointer;
    pointer-events: auto;
  }

  .flag i {
    position: absolute;
    left: 2px;
    top: 6px;
    width: 2px;
    height: 11px;
    background: var(--accent);
    border-radius: 1px;
    box-shadow: 0 0 0 1px rgba(0, 0, 0, 0.12);
  }

  .flag.point i {
    top: 6px;
    width: 6px;
    height: 6px;
    border-radius: 1px;
    box-shadow: inset 0 0 0 1px rgba(0, 0, 0, 0.28);
  }

  .flag:hover i {
    box-shadow: 0 0 0 1px var(--separator);
  }

  .flag-label {
    position: absolute;
    left: 7px;
    top: 1px;
    max-width: 160px;
    overflow: hidden;
    white-space: nowrap;
    text-overflow: ellipsis;
    font-size: 10px;
    line-height: 13px;
    padding: 0 var(--sp-1);
    border-radius: 3px;
    color: var(--on-accent);
    background: var(--accent);
    opacity: 0;
    transition: opacity 90ms ease;
    pointer-events: none;
  }

  .flag:hover .flag-label,
  .flag:focus-visible .flag-label {
    opacity: 1;
  }
</style>
