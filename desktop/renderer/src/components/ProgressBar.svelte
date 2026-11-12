<script lang="ts">
  /**
   * 统一的进度条：转写模型下载、OmniVoice 校验/下载共用。
   *
   * `percent = null` 表示不确定进度（只读校验 / 时长未知的回退压制），
   * 轨道里用一段 accent 块缓慢往返；有百分比时才使用真实的 `scaleX` 填充。
   * 动画只改 `transform`，避免低帧率下 `width` 重排。
   */
  let {
    percent = null,
    state = 'running',
    label = '进度',
  }: {
    percent?: number | null;
    state?: 'running' | 'done' | 'error';
    label?: string;
  } = $props();

  const determinate = $derived(typeof percent === 'number' && Number.isFinite(percent));
  const pct = $derived(
    determinate ? Math.min(100, Math.max(0, percent as number)) : 0,
  );
</script>

<div
  class="progress"
  class:indeterminate={!determinate}
  class:done={state === 'done'}
  class:error={state === 'error'}
  role="progressbar"
  aria-label={label}
  aria-valuemin="0"
  aria-valuemax="100"
  aria-valuenow={determinate ? Math.round(pct) : undefined}
>
  <span class="fill" style="--pct:{determinate ? pct / 100 : 0}"></span>
</div>

<style>
  .progress {
    position: relative;
    height: 4px;
    border-radius: 2px;
    background: var(--fill-strong);
    overflow: hidden;
  }
  .fill {
    display: block;
    position: absolute;
    inset: 0;
    border-radius: 2px;
    background: var(--accent);
    transform-origin: left center;
    transform: scaleX(var(--pct, 0));
    transition:
      transform 420ms cubic-bezier(0.16, 1, 0.3, 1),
      background-color 180ms ease;
    will-change: transform;
  }
  .progress:not(.done):not(.error):not(.indeterminate) .fill {
    box-shadow: 0 0 8px var(--accent-soft);
  }
  /* 运行中扫过的一道柔光：只在确定进度时出现，完成/失败立即停 */
  .fill::after {
    content: '';
    position: absolute;
    inset: 0;
    background: linear-gradient(
      90deg,
      transparent,
      rgba(255, 255, 255, 0.3),
      transparent
    );
    transform: translateX(-120%);
    animation: progress-shimmer 1.4s linear infinite;
  }
  .done .fill {
    background: var(--success);
  }
  .error .fill {
    background: var(--danger);
  }
  .done .fill::after,
  .error .fill::after {
    display: none;
  }

  .indeterminate .fill {
    width: 34%;
    transform: none;
    animation: progress-indeterminate 1.25s ease-in-out infinite;
  }
  .indeterminate .fill::after {
    display: none;
  }

  @keyframes progress-shimmer {
    0% {
      transform: translateX(-120%);
    }
    60%,
    100% {
      transform: translateX(220%);
    }
  }
  @keyframes progress-indeterminate {
    0% {
      transform: translateX(-130%);
    }
    100% {
      transform: translateX(330%);
    }
  }

  @media (prefers-reduced-motion: reduce) {
    .fill {
      transition: none;
    }
    .fill::after {
      animation: none;
      display: none;
    }
    .indeterminate .fill {
      width: 100%;
      transform: none;
      animation: none;
      opacity: 0.55;
    }
  }
</style>
