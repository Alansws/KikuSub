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
  /* 确定进度就是一条纯色填充：不再扫一道柔光（2026-11-25 Step 5 去掉）。
     进度本身在动，再加一条无限循环的高光只会抢注意力；零偏移的蓝色光晕同理。 */
  .done .fill {
    background: var(--success);
  }
  .error .fill {
    background: var(--danger);
  }

  /* 不确定进度：一块固定宽度的填充在原地轻微呼吸，不再横向来回扫。
     横向运动会读成「有条进度在走」并抢视线；呼吸只表达「还在跑」。 */
  .indeterminate .fill {
    width: 34%;
    transform: none;
    animation: progress-breathe 1.6s ease-in-out infinite;
  }

  @keyframes progress-breathe {
    0%,
    100% {
      opacity: 0.55;
    }
    50% {
      opacity: 1;
    }
  }
  @media (prefers-reduced-motion: reduce) {
    .fill {
      transition: none;
    }
    .indeterminate .fill {
      width: 100%;
      transform: none;
      animation: none;
      opacity: 0.55;
    }
  }
</style>
