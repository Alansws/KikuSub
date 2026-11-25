<script lang="ts">
  /**
   * 转写页底部执行栏（2026-11-26 重做为 Docked 栏）。
   *
   * 为什么固定在底部：旧页面的主按钮夹在「结果与输出」卡片中间，跑起来还要在
   * 页面里插一张进度卡，下面的参数 / 已有字幕被整体推下去。用户每改一次范围都要
   * 往下找按钮，也就看不出「改了范围 = 本次任务变了」。
   *
   * 2026-11-26 真机反馈：「悬浮感十足的白色横条贴在灰底上非常突兀，运行中缺少
   * 直观的水平进度条」。所以这一版：
   * - **不再是浮条**：底色由外层通栏的 `.dock-wrap` 给（纸面色带 + 一条上发丝线），
   *   组件本身没有底色、圆角、模糊和投影，它只是这条带上的一行内容；
   * - **运行中有真正的进度条**：状态行下面一条 4px 细轨（中性槽 + 蓝铅笔实心填充），
   *   右侧等宽百分比；`aria-valuenow` 跟着走，读屏与视觉同源；
   * - **三态各有一行收口**：待开始只有「谁 × 哪一段 → 写到哪」；进行中把状态行换成
   *   「阶段 + 进度」；失败把原因留在那一行上（原因再长也只在 2 行内换行，不撑破栏）。
   * - 完成 / 失败时按钮仍在——想用同样的设置再跑一次不必先关掉什么。
   */
  import Icon from '../Icon.svelte';

  type RunState = 'idle' | 'running' | 'done' | 'error';

  let {
    summary = '',
    detail = '',
    blocked = '',
    buttonLabel = '开始转写',
    disabled = false,
    state = 'idle' as RunState,
    pct = 0,
    stage = '',
    statusText = '',
    statusNote = '',
    error = '',
    doneCta = null as null | { label: string; onclick: () => void },
    savedPath = '',
    onrun,
    oncancel,
    onreveal,
  }: {
    summary?: string;
    detail?: string;
    blocked?: string;
    buttonLabel?: string;
    disabled?: boolean;
    state?: RunState;
    pct?: number;
    stage?: string;
    statusText?: string;
    statusNote?: string;
    error?: string;
    doneCta?: null | { label: string; onclick: () => void };
    savedPath?: string;
    onrun?: () => void;
    oncancel?: () => void;
    onreveal?: () => void;
  } = $props();

  const shownPct = $derived(Math.max(0, Math.min(100, Math.round(pct))));
</script>

<footer class="dock" class:running={state === 'running'} aria-live="polite">
  <div class="dock-body">
    <div class="dock-copy">
      {#if state === 'running'}
        <div class="status">
          <span class="spin" aria-hidden="true"></span>
          <span class="status-text">{stage || '准备中…'}</span>
          <span class="pct">{shownPct}%</span>
        </div>
        <div
          class="meter"
          role="progressbar"
          aria-label="转写进度"
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={shownPct}
        >
          <i style="width:{shownPct}%"></i>
        </div>
      {:else if state === 'done'}
        <div class="status done">
          <Icon name="check" size={12} />
          <span class="status-text">{statusText}</span>
          {#if statusNote}<span class="status-note">{statusNote}</span>{/if}
        </div>
      {:else if state === 'error'}
        <div class="status err">
          <Icon name="warn" size={12} />
          <span class="status-text">{statusText || '转写失败'}</span>
          <span class="status-note err" title={error}>{error}</span>
        </div>
      {/if}

      <div class="plan">{summary}</div>
      <div class="detail" class:blocked={Boolean(blocked)}>{blocked || detail}</div>
    </div>

    <div class="dock-actions">
      {#if state === 'running'}
        <button class="btn danger" type="button" onclick={oncancel}>
          <Icon name="stop" size={12} />中途打断
        </button>
      {:else}
        {#if state === 'done' && savedPath}
          <button class="btn ghost sm" type="button" onclick={onreveal}>在访达中显示</button>
        {/if}
        {#if state === 'done' && doneCta}
          <button class="btn ghost" type="button" onclick={doneCta.onclick}>{doneCta.label}</button>
        {/if}
        <button
          class="btn primary lg run-btn"
          type="button"
          onclick={onrun}
          disabled={disabled || Boolean(blocked)}
        >
          <Icon name="play" size={13} />{buttonLabel}
        </button>
      {/if}
    </div>
  </div>
</footer>

<style>
  /* 这条栏自己不带底色：纸面色带与上发丝线在页面的 `.dock-wrap` 上，
     组件只负责排内容。这样它和主内容区是同一张纸，而不是贴上去的白条。 */
  .dock {
    flex: 0 0 auto;
    padding: 11px 0 var(--sp-3);
    min-width: 0;
  }

  .dock-body {
    display: flex;
    align-items: center;
    gap: var(--sp-4);
    min-width: 0;
  }
  .dock-copy {
    flex: 1;
    min-width: 0;
  }

  .status {
    display: flex;
    align-items: center;
    gap: 6px;
    min-width: 0;
    font-size: 12px;
    line-height: 17px;
    color: var(--text-2);
    margin-bottom: 5px;
  }
  .status.done {
    color: var(--success);
  }
  .status.err {
    color: var(--danger);
  }
  .status-text {
    font-weight: 600;
    white-space: nowrap;
    flex: 0 0 auto;
    max-width: 62%;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .status-note {
    min-width: 0;
    font-weight: 400;
    font-size: 11.5px;
    color: var(--text-3);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .status-note.err {
    color: var(--danger);
    flex: 1 1 auto;
  }
  .pct {
    margin-left: auto;
    font-family: var(--font-mono);
    font-size: 11.5px;
    font-variant-numeric: tabular-nums;
    color: var(--text-2);
    flex: 0 0 auto;
  }

  /* 进度条：4px 圆角细轨 + 实心蓝铅笔填充。没有条纹、没有流光、没有渐变——
     轨道本身已经在动，装饰只会和内容抢注意力（DESIGN.md §Progress）。 */
  .meter {
    height: 4px;
    border-radius: 2px;
    background: var(--fill-strong);
    overflow: hidden;
    margin: 0 0 7px;
  }
  .meter > i {
    display: block;
    height: 100%;
    border-radius: 2px;
    background: var(--accent);
    transition: width 260ms var(--ease);
  }
  @media (prefers-reduced-motion: reduce) {
    .meter > i {
      transition: none;
    }
    .spin {
      animation: none;
    }
  }

  /* 这一行是「谁 × 哪一段 → 写到哪」的复述，唯一一行必须完整可读 */
  .plan {
    margin-top: 1px;
    font-size: 12.5px;
    line-height: 18px;
    font-weight: 500;
    color: var(--text);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .detail {
    margin-top: 1px;
    font-size: 11px;
    line-height: 1.45;
    color: var(--text-3);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .detail.blocked {
    color: var(--warn);
  }

  .dock-actions {
    display: flex;
    align-items: center;
    gap: var(--sp-2);
    flex: 0 0 auto;
  }
  .run-btn {
    min-width: 156px;
    justify-content: center;
  }

  .spin {
    width: 11px;
    height: 11px;
    flex: 0 0 11px;
    border-radius: 50%;
    border: 1.5px solid var(--accent-soft);
    border-top-color: var(--accent);
    animation: spin 900ms linear infinite;
  }
  @keyframes spin {
    to {
      transform: rotate(360deg);
    }
  }

  @media (max-width: 1040px) {
    .plan,
    .detail {
      white-space: normal;
    }
  }
  @media (max-width: 900px) {
    .dock-body {
      gap: var(--sp-2);
    }
    .status-note {
      display: none;
    }
  }
</style>
