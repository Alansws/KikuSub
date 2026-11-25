<script lang="ts">
  /**
   * 转写页底部任务条（2026-11-25 Cue Script 版）。
   *
   * 为什么固定在底部：旧页面的主按钮夹在「结果与输出」卡片中间，跑起来还要在
   * 页面里插一张进度卡，下面的参数 / 已有字幕被整体推下去。用户每改一次范围都要
   * 往下找按钮，也就看不出「改了范围 = 本次任务变了」。
   *
   * 现在它是页面上唯一始终可见的动作区：左边复述「谁 × 哪一段 → 写到哪」，
   * 右边就是那一个按钮；跑起来时状态行替换成进度，进度线贴在上边缘，页面其余
   * 部分不位移。完成 / 失败时按钮仍在——想用同样的设置再跑一次不必先关掉什么。
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
</script>

<footer class="dock" class:running={state === 'running'}>
  {#if state === 'running'}
    <div class="track" aria-hidden="true"><i style="width:{pct}%"></i></div>
  {/if}

  <div class="dock-body">
    <div class="dock-copy">
      {#if state === 'running'}
        <div class="status">
          <span class="spin" aria-hidden="true"></span>
          <span class="status-text">{stage || '准备中…'}</span>
          <span class="pct">{pct}%</span>
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
          <span class="status-note err">{error}</span>
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
  .dock {
    flex: 0 0 auto;
    position: relative;
    padding: 10px 0 var(--sp-3);
    border-top: 1px solid var(--line);
    background: var(--bg-toolbar);
    backdrop-filter: saturate(180%) blur(16px);
    -webkit-backdrop-filter: saturate(180%) blur(16px);
    min-width: 0;
  }

  /* 进度线贴任务条上缘：不占高度，跑起来页面不位移 */
  .track {
    position: absolute;
    left: 0;
    right: 0;
    top: -1px;
    height: 2px;
    background: var(--fill-strong);
    overflow: hidden;
  }
  .track > i {
    display: block;
    height: 100%;
    background: var(--accent);
    transition: width 260ms var(--ease);
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
  }
  .status-note {
    min-width: 0;
    font-weight: 400;
    font-size: 11px;
    color: var(--text-3);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .status-note.err {
    color: var(--warn);
  }
  .pct {
    font-family: var(--font-mono);
    font-size: 11px;
    font-variant-numeric: tabular-nums;
    color: var(--text-2);
  }

  /* 这一行是「谁 × 哪一段 → 写到哪」的复述，唯一一行必须完整可读 */
  .plan {
    margin-top: 2px;
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
