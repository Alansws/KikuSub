<script lang="ts">
  /**
   * 核对台的视频监看区：画面 + 字幕叠加 + 代理提示。
   *
   * 2026-11-24 从 `ReviewView.svelte` 纯搬运（Phase 0，视觉零变化）。
   * `<video>` 的生命周期、`theatre` 擦洗、首帧探测与布局恢复都还在父组件：
   * 这里只把节点交回去（`onvideo`），并把所有原生事件原样转发。
   *
   * `{@attach bindVideo}` 的挂载 / 卸载语义不能改：`bindVideo` 返回的清理函数
   * 负责 detach，视频节点换掉时必须走到它。
   */
  import ProxyGate from '../ProxyGate.svelte';

  let {
    src = '',
    captionLines = [],
    stageHeight = 0,
    maxStageHeight = 0,
    ondragbar,
    gate = null,
    proxyReason = '',
    onvideo,
    attach,
    onerror,
    onloadedmetadata,
    onloadeddata,
    onstartproxy,
    onimportproxy,
  }: {
    src?: string;
    captionLines?: string[];
    gate?: unknown;
    proxyReason?: string;
    onvideo?: (node: HTMLVideoElement) => void;
    attach: (node: HTMLVideoElement) => void | (() => void) | { destroy(): void };
    onerror: (el: HTMLVideoElement, e: Event) => void;
    onloadedmetadata: (el: HTMLVideoElement, e: Event) => void;
    onloadeddata: (el: HTMLVideoElement, e: Event) => void;
    onstartproxy: () => void;
    onimportproxy: () => void;
    /** 监看舞台高度（0 = 用 16:9 的自然高度）；可拖高，见下方 splitter。 */
    stageHeight?: number;
    /** 拖高的上限（窗口可用高度的一半），由父组件按视口算。 */
    maxStageHeight?: number;
    ondragbar?: (height: number) => void;
  } = $props();

  let videoEl = $state<HTMLVideoElement | null>(null);

  $effect(() => {
    if (videoEl) onvideo?.(videoEl);
  });
</script>

<div class="stage">
  <!-- `.player` 只负责「这一屏给监看区多高」：默认按 16:9 自然高度，
       拖过分隔条之后由内联 height 决定（见下方 :style）。
       `.frame` 才是那个 16:9 的画面本体（1px 细边 + 极轻投影）。 -->
  <div
    class="player"
    style={stageHeight ? `--stage-h:${stageHeight}px` : ''}
  >
    <div class="frame">
  {#if src}
    <video
      {@attach attach}
      bind:this={videoEl}
      {src}
      preload="auto"
      playsinline
      onerror={(e) => videoEl && onerror(videoEl, e)}
      onloadedmetadata={(e) => videoEl && onloadedmetadata(videoEl, e)}
      onloadeddata={(e) => videoEl && onloadeddata(videoEl, e)}
    ></video>
  {:else}
    <div class="empty">还没有导入媒体</div>
  {/if}

  {#if captionLines.length}
    <div class="caption">
      {#each captionLines as line, i (i)}
        <span>{line}</span>
      {/each}
    </div>
  {/if}

    <!-- 代理闸门只负责「压下画面」的提示层；状态机在 lib/videoFallback.ts -->
    <ProxyGate
      state={gate as never}
      reason={proxyReason}
      onstart={onstartproxy}
      onimport={onimportproxy}
    />
    </div>
  </div>

  <!-- 可拖的高度分隔条：向下拉 = 画面变高、时间轴与表格让位。
       双击回到默认（16:9 自然高度）。 -->
  <button
    class="splitter"
    aria-label="调整监看区高度（双击还原）"
    title="拖动调整监看区高度 · 双击还原"
    onpointerdown={(e) => {
      e.preventDefault();
      const startY = e.clientY;
      const startH = e.currentTarget.parentElement?.querySelector('.player')?.clientHeight ?? 0;
      const el = e.currentTarget as HTMLElement;
      el.setPointerCapture(e.pointerId);
      const move = (ev: PointerEvent) => {
        const next = startH + (ev.clientY - startY);
        ondragbar?.(Math.max(160, Math.min(maxStageHeight || 720, next)));
      };
      const up = () => {
        el.removeEventListener('pointermove', move);
        el.removeEventListener('pointerup', up);
        el.removeEventListener('pointercancel', up);
      };
      el.addEventListener('pointermove', move);
      el.addEventListener('pointerup', up);
      el.addEventListener('pointercancel', up);
    }}
    ondblclick={() => ondragbar?.(0)}
  ></button>
</div>

<style>
  /* 监看舞台：通栏画布（2026-11-24 Phase 2；同日二改）。
     原来是「通栏深黑 + 黑画面」，浅色主题下 16:9 画面四周（左右 + 底部）
     会露出两条生硬的黑边。现在舞台底色是主题令牌 `--stage-bg`：
     浅色 = 柔和浅灰画布、深色 = 近纯黑（与旧行为一致）。
     画面本体（`.frame`）才是唯一「暗」的东西，1px 细边 + 极轻投影让它
     读成浮在画布上的一块屏幕，而不是被裁掉一半的黑底。 */
  .stage {
    display: flex;
    flex-direction: column;
    background: var(--stage-bg);
  }
  /* `.player` = 这一屏分给监看区的高度（默认 = 16:9 自然高度；拖高后 = 内联高度）。
     它不再有底色、圆角或外边距 —— 视觉边界全部交给里面的 `.frame`。 */
  .player {
    position: relative;
    width: 100%;
    margin: 0 auto;
    display: flex;
    align-items: center;
    justify-content: center;
  }
  /* 用户拖过高度：`.player` 就是这个高度，`.frame` 在它里面按 16:9 收敛。
     宽度上限同时问两件事 —— 容器多宽、以及「拖出来的高度按 16:9 反推能有多宽」；
     取较小值，高度由 aspect-ratio 自己长出来。
     只写 `height:100%; width:auto` 时，宽度被 max-width 夹住而高度不缩，
     比例就破了（实测 856×486 = 1.76，画面被拉扁）。
     用 `--stage-h` 是否被内联设置来判定，比 `[style*='height']` 稳。 */
  .player[style*='--stage-h'] {
    height: var(--stage-h);
    max-height: none;
  }
  .player[style*='--stage-h'] .frame {
    width: min(100%, calc(var(--stage-h) * 16 / 9));
    /* 拖高就是要「变大」：默认那 640px 上限在这一态必须让开，
       否则拖到 486 高仍然只有 640 宽，留出一圈没用的画布。 */
    max-width: none;
    height: auto;
  }
  /* 画面本体：严格 16:9，高度自适应（宽由容器定、高由 aspect-ratio 定）。
     `width` 同时受三条上限约束 —— 容器宽、「高度上限按 16:9 反推出来的宽」、
     以及默认的 640px 设计宽。只写 `width:100%` + `max-height` 时，高度被夹住
     而宽度不跟着缩，比例就破了（实测 856×407 = 2.10）。
     写成 min() 之后宽度自己让位，画面永远是准确 16:9。 */
  .frame {
    position: relative;
    width: min(100%, calc(var(--stage-cap, 46vh) * 16 / 9));
    max-width: 640px;
    aspect-ratio: 16 / 9;
    margin: 0 auto;
    background: #000;
    /* 画面周围的暗色外边距全部去掉：不再有 margin / padding / 圆角，
       只留 1px 细边（--stage-frame）+ 极轻投影（--shadow-video）。
       细边用 inset box-shadow 而不是 border：border 会吃掉 1px 内容高度，
       16:9 的换算就会差一个像素，截图回归会把它读成「拉伸了」。 */
    box-shadow:
      inset 0 0 0 1px var(--stage-frame),
      var(--shadow-video);
    display: flex;
    align-items: center;
    justify-content: center;
  }
  video {
    width: 100%;
    height: 100%;
    object-fit: contain;
    background: #000;
    display: block;
  }
  .empty {
    color: rgba(255, 255, 255, 0.5);
    font-size: 12.5px;
  }

  .caption {
    position: absolute;
    left: 50%;
    bottom: 14px;
    transform: translateX(-50%);
    max-width: 84%;
    background: var(--caption-bg);
    backdrop-filter: blur(6px);
    color: #fff;
    /* 与表格、检查器同一条字幕字体角色：主题换的是「字幕」，不是「界面」 */
    font-family: var(--font-cue);
    font-size: 14px;
    line-height: 1.5;
    padding: 5px 13px;
    border-radius: 4px;
    text-align: center;
    text-shadow: 0 1px 2px rgba(0, 0, 0, 0.5);
    pointer-events: none;
    display: flex;
    flex-direction: column;
    gap: 1px;
  }
  .caption span {
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  /* 高度分隔条：6px 命中区 + 1px 视觉线；hover / 拖动时亮起来 */
  .splitter {
    appearance: none;
    display: block;
    width: 100%;
    height: 6px;
    margin: 0;
    padding: 0;
    border: 0;
    background: transparent;
    cursor: ns-resize;
    position: relative;
    flex: 0 0 6px;
  }
  .splitter::after {
    content: '';
    position: absolute;
    left: 0;
    right: 0;
    top: 2px;
    height: 1px;
    background: var(--stage-line);
  }
  .splitter:hover::after,
  .splitter:focus-visible::after {
    background: var(--accent);
  }
  .splitter:focus-visible {
    outline: none;
  }
</style>
