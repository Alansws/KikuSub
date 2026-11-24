<script lang="ts">
  /**
   * 核对工作台。
   *
   * 这一屏是整个应用最像「专业工具」的地方，交互必须对得上肌肉记忆：
   *
   * - 波形可缩放（滚轮 / 捏合 / 滑块）与平移（双指横移 / ⌥ 拖动选区外部），
   * - 单击波形 = 跳转；按住并移动超过 4px 才算框选——全局视图下 1px 就是好几秒，
   *   手抖绝不能把「单击」判成「框选」；
   * - 顶部刻度条与播放头两侧 8px 是专属擦洗区：按住拖动即可逐帧预览，
   *   视频进度条同样支持拖动，三者共用一个「暂停 → 跟手 seek → 松手恢复」的擦洗器；
   * - 底部字幕轨道用品牌蓝块表示「这段有字幕」：拖块体整体平移、拖两端改起止；
   *   双语同区间的多行作为一块成组编辑，提交走一次撤回；
   * - 播放头进入某句字幕时，底部表格滚到该句、右侧检查器同步选中（播放中也一样）；
   * - 跟随是持久化偏好：只有点按钮才会改变；跳转（哪怕暂停）会把播放头带回视窗，
   *   播放时则整页平移跟随。缩放/平移波形不会偷偷关掉它；
   * - 每一行都能单独重转，不会冲掉整张表；
   * - 质检面板通过 store 的 focusRange 定位到这里，跳转是真的跳。
   */
  import { tick as nextTick, untrack } from 'svelte';
  import Icon from '../components/Icon.svelte';
  import ProxyGate from '../components/ProxyGate.svelte';
  import ReviewTransport from '../components/review/ReviewTransport.svelte';
  import ReviewWaveTrack from '../components/review/ReviewWaveTrack.svelte';
  import ReviewStage from '../components/review/ReviewStage.svelte';
  import ReviewTable from '../components/review/ReviewTable.svelte';
  import ChapterTrack from '../components/ChapterTrack.svelte';
  import { api, mediaUrl } from '../lib/api';
  import { logEvent } from '../lib/api';
  import {
    app,
    applyCueTimes,
    closeFind,
    deleteCue,
    deleteCues,
    extractTtsVoiceFromCue,
    findState,
    focusRange,
    importProxyFromFile,
    insertCueAt,
    isTranslationStale,
    jumpToCue,
    mergeCuesAt,
    play,
    previewRange,
    replaceAllInTracks,
    replaceInCue,
    replaceInTranslation,
    seekTo,
    setTrackMode,
    splitCueAt,
    startProxyJob,
    toast,
    translationAt,
    translationTextAt,
    transcribeRange,
    tts,
  } from '../lib/store.svelte';
  import { chapters, loadChapters, seekToMark } from '../lib/chapters.svelte';
  import { jobBusy } from '../lib/jobState';
  import { comboOf, formatCombo } from '../lib/shortcuts.svelte';
  import { formatDuration, tc, tcShort } from '../lib/time';
  import { isTypingTarget } from '../lib/typing';
  import {
    collectFindHits,
    countSkippedHits,
    filterSkippedHits,
    findHitKey,
    highlightSegments,
    ordinalOfHit,
    skippedStartsByCueTrack,
    type FindHit,
    type FindSkipAnchor,
    type FindTrack,
  } from '../lib/findMatches';
  import {
    BLANK_FRAME_TIMEOUT_MS,
    hasDecodedFrame,
    needsBlankFrameWatch,
    videoGateState,
  } from '../lib/videoFallback';
  import {
    type CueBlock,
    cueBlockAtX,
    cueDragTimes,
    cueIndexAtTime,
    cueRange,
    deleteTargets,
    indicesForLaneKeys,
    indicesInRange,
    keysInRange,
    laneKey,
    rangeSelection,
    stepSelection,
  } from '../lib/selection';
  import { canSplitAt } from '../lib/cueEdit';
  import { collectSnapTargets, snapCueTimes, snapThreshold } from '../lib/cueSnap';
  import { snapPrefs } from '../lib/snapPrefs.svelte';
  import { attachVideo, detachVideo, resetRate, transport } from '../lib/transport.svelte';
  import {
    clampTimelineView,
    focusTimelineSpan,
    revealTimelineView,
    sliderToSpan,
    spanToSlider,
    toggleFitView,
    zoomTimelineView,
  } from '../lib/timelineView';
  import { roundRect } from '../lib/waveformDraw';
  import { paintReviewCanvas } from '../lib/waveformCanvas';
  import {
    cachedPeaks,
    peakCacheKey,
    planViewportRestore,
    readViewportForRestore,
    rememberViewport,
    resolveCueIndex,
    storePeaks,
    takeExplicitJump,
  } from '../lib/reviewViewport';
  import { claimTranslationDefault, planInitialReviewView } from '../lib/reviewStart';
  import { revealScrollTop, rowHeightFor, virtualWindow } from '../lib/reviewTable';

  let { engine = 'whisper' }: { engine?: string } = $props();

  let video = $state<HTMLVideoElement | null>(null);
  let waveWrap = $state<HTMLDivElement | null>(null);
  let canvas = $state<HTMLCanvasElement | null>(null);
  let rowsEl = $state<HTMLDivElement | null>(null);

  let peaks = $state<number[]>([]);
  let peaksFrom = $state(0);
  let peaksSpan = $state(0);
  let loadingPeaks = $state(false);
  let videoFailed = $state(false);
  /** 已经解出第一帧：黑屏兜底计时据此取消，提示也就不会再出现。 */
  let videoDecoded = $state(false);
  /** container / codec 片子的兜底计时已到；首帧一到立刻清掉。 */
  let blankTimedOut = $state(false);
  let blankTimer: number | undefined;
  let scrollTop = $state(0);
  let viewH = $state(0);
  let waveW = $state(0);
  // 波形高度：默认 80（D 稿），拖底部把手可调并记住。2026-11-21 曾随字幕轨道抬到 88，轨道回到 17 后一并回到 80。
  const savedHeight = Number(localStorage.getItem('kikusub.waveHeight') || 0);
  let waveHeight = $state(Math.max(72, Math.min(300, savedHeight || 80)));

  // 波形视窗（秒）。duration 来自媒体元数据。
  const duration = $derived(app.media?.duration ?? 0);
  let viewStart = $state(0);
  let viewSpan = $state(60);
  /**
   * `<video>` 的元数据是否就绪。历史现场的播放头必须等到这一刻再 seek：
   * 早于 loadedmetadata 写 currentTime 会被浏览器丢掉，用户看到的是「没恢复」。
   */
  let videoMetaReady = $state(false);
  /** 已经为哪部影片恢复过现场（每次换片只恢复一次）。 */
  let restoreDoneFor = '';
  /** 当前核对台里实际挂载的影片路径，用于换片前把上一条现场落盘。 */
  let openedPath = '';
  /** 全片适应前记住的视窗；再次 ⇧Z 恢复。 */
  let preFitView = $state<{ start: number; span: number } | null>(null);
  /** 拖字幕块时命中的参考线；松开 / 取消即清空。 */
  let snapGuide = $state<number | null>(null);
  /**
   * 跟随是「用户偏好」，不是临时状态：
   * 只由用户点按钮改变，并持久化。缩放/平移波形、单击跳转、点字幕行、
   * 点底部字幕块都不许把它悄悄关掉（这些都被用户报成 bug）。
   */
  let follow = $state(localStorage.getItem('kikusub.follow') !== '0');
  let selection = $state<{ start: number; end: number } | null>(null);

  const MIN_SPAN = 0.5;
  /**
   * 所有「聚焦」按钮的统一倍率：相对全片时长固定 69×，不会因为当前已经放大
   * 到 145× 再点一次就叠成 415×。用户明确要求「聚焦定死 69 倍」。
   */
  const FOCUS_ZOOM = 69;

  // 时间轴三条竖带。绘制与命中判定共用同一组常量，避免“看到的”和“点到的”错位。
  const RULER_H = 17; // 顶部刻度条：按住拖动 = 擦洗播放头
  // 底部字幕轨道：块高 = LANE_H - 6（11px）。2026-11-21 曾提到 24 想放大抓取热区，用户当天报
  // 「太高、上下太宽」后回到 17；抓取不靠块高，命中判定用整条轨道（`h - RESIZE_H - LANE_H` 往上）。
  const LANE_H = 17;
  const RESIZE_H = 6; // 最底部的波形高度把手
  const EDGE = 6; // 字幕块左右端的抓取宽度（px）
  const PLAYHEAD_GRAB = 8; // 播放头两侧的抓取宽度（px）
  const CLICK_SLOP = 4; // 按下后移动超过它才算框选，否则算单击跳转

  const laneTopOf = (h: number) => h - RESIZE_H - LANE_H;

  // 光标与高亮（悬停/拖动的字幕块用 key 标识，双语同区间的两行算同一块）
  let waveCursor = $state('crosshair');
  let hoverKey = $state('');
  let dragKey = $state('');
  let cueTip = $state<{ x: number; label: string } | null>(null);
  /** 音轨/字幕表右键菜单：添加 / 切割 / 合并字幕，或把这一句切成克隆音色。 */
  let contextMenu = $state<{
    x: number;
    y: number;
    t: number;
    index: number;
    merge: number[];
  } | null>(null);
  /** 底部字幕轨道多选：存块 key（`start:end`），双语同区间算一块。 */
  let laneSelection = $state<string[]>([]);
  /**
   * ⇧ 连选的锚点行：最近一次普通单击 / ⌘ 单击的那一行。连选后**不移动**锚点，
   * 这样连续按 ⇧ 调整终点时始终从同一句开始扩（和 Finder 一致）。
   * 不用 `play.selected`：它会跟着播放头走，锚点会被播放悄悄改掉。
   */
  let rangeAnchor = -1;
  /** 只保留仍存在的块：整表被转写/导入替换后，旧 key 会让工具条卡住、行也不高亮。 */
  const multiKeys = $derived(laneSelection.filter((key) => app.cues.some((cue) => laneKey(cue) === key)));
  /** 「以此句音频新建音色」浮层：命名 + 可选参考文本。 */
  let voiceDialog = $state<{ index: number; name: string; refText: string } | null>(null);
  let voiceBusy = $state(false);
  let voiceNameEl = $state<HTMLInputElement | null>(null);

  // 视频进度条拖动
  let trackDrag = $state(false);
  // 最近一次自动滚到/选中过的字幕行，避免同一句反复滚动
  let lastRevealed = -1;


  // 有代理就走代理：Chromium 解不开 MKV / HEVC，原片喂进去只会黑屏。
  const src = $derived(
    app.media ? mediaUrl(app.media.id, Boolean(app.media.proxy_ready)) : '',
  );
  const proxyBusy = $derived(
    app.jobKind === 'proxy' &&
      (app.job?.status === 'running' || app.job?.status === 'queued'),
  );
  const videoGate = $derived(
    videoGateState({
      hasMedia: Boolean(app.media),
      hasVideo: Boolean(app.media?.has_video),
      proxyReason: app.media?.proxy_reason ?? '',
      proxyReady: Boolean(app.media?.proxy_ready),
      proxyBusy,
      failed: videoFailed,
      blankTimedOut,
    }),
  );

  /**
   * 黑屏兜底：容器卡死时 `<video>` 可能既不报 error 也不触发 loadedmetadata，
   * 所以计时从「拿到媒体 / 切到代理」开始，而不是等元数据。
   * 首帧（loadeddata）一到立即取消；正常码率的片子不会进入这里。
   */
  $effect(() => {
    void src; // 换片、代理就绪换源都要重新计时
    const media = app.media;
    // 复看/切回核对台时元素可能已经缓存了解好的帧，不要重新开计时。
    const decodedNow = Boolean(
      video && hasDecodedFrame(video.readyState, video.videoWidth),
    );
    videoFailed = false;
    videoDecoded = decodedNow;
    blankTimedOut = false;
    if (blankTimer !== undefined) {
      clearTimeout(blankTimer);
      blankTimer = undefined;
    }
    if (
      media &&
      !decodedNow &&
      needsBlankFrameWatch({
        hasMedia: true,
        hasVideo: Boolean(media.has_video),
        proxyReason: media.proxy_reason,
        proxyReady: Boolean(media.proxy_ready),
      })
    ) {
      blankTimer = window.setTimeout(() => {
        blankTimer = undefined;
        if (!videoDecoded) blankTimedOut = true;
      }, BLANK_FRAME_TIMEOUT_MS);
    }
    return () => {
      if (blankTimer !== undefined) {
        clearTimeout(blankTimer);
        blankTimer = undefined;
      }
    };
  });

  // 当前播放到的字幕。双语 SRT 的两行区间完全相同，必须一起显示。
  const captionLines = $derived.by(() => {
    // 显式依赖：切换显示模式或译文更新时，画面字幕要立刻跟着变
    void app.track;
    void app.translations[app.trackLang]?.texts.length;
    const cues = app.cues;
    if (!cues.length) return [] as string[];
    const t = play.time;
    let lo = 0;
    let hi = cues.length - 1;
    let hit = -1;
    while (lo <= hi) {
      const mid = (lo + hi) >> 1;
      const c = cues[mid];
      if (t < c.start) hi = mid - 1;
      else if (t >= c.end) lo = mid + 1;
      else {
        hit = mid;
        break;
      }
    }
    if (hit < 0) return [];
    const key = `${cues[hit].start}:${cues[hit].end}`;
    const lines: string[] = [];
    let i = hit;
    while (i >= 0 && `${cues[i].start}:${cues[i].end}` === key) i -= 1;
    const idxs: number[] = [];
    for (let k = i + 1; k < cues.length; k += 1) {
      if (`${cues[k].start}:${cues[k].end}` !== key) break;
      if (cues[k].text.trim()) idxs.push(k);
    }

    // 画面字幕跟着「原文 / 译文 / 双语」切换：双语是原文在上、译文在下。
    // 译文缺失时退回原文，绝不在画面上留空行。
    //
    // 一条 cue 里可能带 `\n`（外部 SRT 的硬换行、旧版双语文件）：必须拆成多行
    // 交给叠加层，否则 `white-space` 会把它压成「日文 中文」一行（用户报过）。
    for (const k of idxs) {
      const sourceLines = captionTextLines(cues[k].text);
      const targetLines = captionTextLines(translationAt(k));
      if (app.track === 'target') {
        lines.push(...(targetLines.length ? targetLines : sourceLines));
      } else if (app.track === 'both') {
        lines.push(...sourceLines);
        if (targetLines.length) lines.push(...targetLines);
      } else {
        lines.push(...sourceLines);
      }
    }
    return lines;
  });

  const cueIndex = $derived.by(() => {
    const t = play.time;
    const cues = app.cues;
    let lo = 0;
    let hi = cues.length - 1;
    while (lo <= hi) {
      const mid = (lo + hi) >> 1;
      const c = cues[mid];
      if (t < c.start) hi = mid - 1;
      else if (t >= c.end) lo = mid + 1;
      else return mid;
    }
    return -1;
  });

  /**
   * 当前画面对应的「字幕块」区间。双语 SRT 的日/中两行完全同区间，
   * 表格高亮与检查器都必须认这一整块，而不是只认第一条。
   */
  const activeKey = $derived.by(() => {
    const c = cueIndex >= 0 ? app.cues[cueIndex] : null;
    return c ? `${c.start}:${c.end}` : '';
  });

  // 双语是**固定双行高**：自动测量会和虚拟滚动的绝对定位打架（开发文档 §6.3.2）。
  // 窗口计算是纯函数，在 lib/reviewTable.ts（可单测，也不占这里的行数预算）。
  const rowHeight = $derived(rowHeightFor(app.track));
  const vwin = $derived(
    virtualWindow({ scrollTop, viewH, total: app.cues.length, rowH: rowHeight }),
  );
  const rowStart = $derived(vwin.start);
  const rowEnd = $derived(vwin.end);
  const visibleCues = $derived(app.cues.slice(rowStart, rowEnd));

  const zoomX = $derived(duration > 0 ? Math.max(1, duration / Math.max(viewSpan, 0.001)) : 1);
  const progressPct = $derived(
    Math.max(0, Math.min(100, duration > 0 ? (play.time / duration) * 100 : 0)),
  );
  const busy = $derived(
    app.job?.status === 'queued' ||
      app.job?.status === 'running' ||
      app.job?.status === 'cancelling',
  );
  const rangeBusy = $derived(busy && app.jobMeta?.scope === 'range');

  // ---------------- 视窗与坐标 ----------------
  /**
   * 改视窗只负责缩放/平移；跟随是独立偏好，绝不在这里被顺手关掉。
   * 专业剪辑软件也不会因为缩放时间线就取消「跟随播放头」。
   */
  function setView(start: number, span: number) {
    const next = clampTimelineView(start, span, duration, MIN_SPAN);
    viewStart = next.start;
    viewSpan = next.span;
  }

  /**
   * 跳转（包括暂停状态下点字幕）后把播放头带回视窗。
   *
   * 以前只有「播放中 + 跟随」才会平移视窗，于是暂停时点一句远处的字幕，
   * 视频跳到了对应帧，波形上的播放头却跑出画面外；用户只能先开跟随再敲空格。
   * 现在跟随开启时，任何 seek 都会补一次平移，不要求先播放。
   */
  function revealPlayhead(t = play.time) {
    const next = revealTimelineView({ start: viewStart, span: viewSpan }, t, duration, MIN_SPAN, follow);
    if (next.start !== viewStart) viewStart = next.start;
  }

  function xOf(time: number) {
    return ((time - viewStart) / (viewSpan || 1)) * waveW;
  }

  function timeAt(clientX: number) {
    if (!waveWrap) return 0;
    const r = waveWrap.getBoundingClientRect();
    const ratio = Math.max(0, Math.min(1, (clientX - r.left) / Math.max(1, r.width)));
    return viewStart + ratio * viewSpan;
  }

  /** 当前核对台状态 → 可持久化的现场快照。 */
  function currentSnapshot() {
    const cue = app.cues[play.selected];
    return {
      cueIndex: play.selected,
      cueTime: cue?.start ?? 0,
      playhead: play.time,
      viewStart,
      span: viewSpan,
      selection: selection ? { start: selection.start, end: selection.end } : null,
    };
  }

  /** 把某部影片的现场落盘（默认当前片）。切换影片前必须先调一次。 */
  function persistViewport(path = app.media?.path ?? '') {
    if (!path) return;
    // 还没给这部片定过现场（历史恢复 / 首次默认态都还没跑）就不要写：
    // 那一刻视窗还是「全片 1.0×」的复位值，写下去会变成现场快照，
    // 下一次打开反而把它当用户位置恢复回来了。
    if (restoreDoneFor !== path) return;
    rememberViewport(path, currentSnapshot());
  }

  // 章节标记按媒体加载；检查器里的「将选区设为章节」需要当前时间选区。
  $effect(() => {
    const path = app.media?.path ?? '';
    if (path) void loadChapters(true);
  });
  $effect(() => {
    chapters.selection = selection ? { start: selection.start, end: selection.end } : null;
  });

  // 媒体变化：先把上一条的现场落盘，再视窗归零、清空选区与波形
  $effect(() => {
    void app.media?.id;
    void app.media?.duration;
    const path = app.media?.path ?? '';
    // 此刻还没执行下面的复位：viewStart / viewSpan / play.time 仍是上一条的值，
    // 所以这里落盘拿到的才是用户离开时的现场（不是归零后的）。
    if (openedPath && openedPath !== path) persistViewport(openedPath);
    openedPath = path;
    videoMetaReady = false;
    restoreDoneFor = '';
    const d = app.media?.duration ?? 0;
    play.duration = d;
    viewStart = 0;
    viewSpan = d || 60;
    preFitView = null;
    snapGuide = null;
    resetRate(false);
    selection = null;
    peaks = [];
    peaksFrom = 0;
    peaksSpan = 0;
    hoverKey = '';
    dragKey = '';
    cueTip = null;
    lastRevealed = -1;
  });

  // ---------------- 波形包络 ----------------
  let peakSeq = 0;
  let peakTimer = 0;

  /**
   * 采样点数按像素的 3 倍取：放大到 1 秒视窗时仍有足够包络，不会退化成一排
   * 可数的柱子。服务端只读这一小段样本，成本可忽略。缓存键必须带上它。
   */
  function binsFor(width: number) {
    return Math.max(512, Math.min(12000, Math.round(width * 3)));
  }

  async function fetchPeaks(id: string, from: number, span: number, width: number) {
    const bins = binsFor(width);
    const key = peakCacheKey(id, from, span, bins);
    const hit = cachedPeaks(key);
    if (hit) {
      // 进程内缓存命中：切回核对台时不再闪一帧空白，也不再发同一个请求
      peaks = hit;
      peaksFrom = from;
      peaksSpan = span;
      loadingPeaks = false;
      return;
    }
    const seq = ++peakSeq;
    loadingPeaks = true;
    try {
      const data = await api.peaks(id, { from, to: from + span, bins });
      if (seq !== peakSeq) return;
      peaks = data.peaks;
      peaksFrom = from;
      peaksSpan = span;
      storePeaks(key, data.peaks);
    } catch {
      if (seq === peakSeq) peaks = [];
    } finally {
      if (seq === peakSeq) loadingPeaks = false;
    }
  }

  $effect(() => {
    const id = app.media?.id;
    const width = waveW;
    const from = viewStart;
    const span = viewSpan;
    if (!id || width <= 0 || span <= 0) return;
    const hit = cachedPeaks(peakCacheKey(id, from, span, binsFor(width)));
    if (hit) {
      // 同步命中：不等 70ms 防抖，也不重新请求——切页回来时波形立刻就在
      peaks = hit;
      peaksFrom = from;
      peaksSpan = span;
      loadingPeaks = false;
      return;
    }
    clearTimeout(peakTimer);
    peakTimer = window.setTimeout(() => void fetchPeaks(id, from, span, width), 70);
    return () => clearTimeout(peakTimer);
  });

  // ---------------- 画布 ----------------
  /** 画法整段在 lib/waveformCanvas.ts：组件只负责传当前状态。 */
  function draw() {
    if (!canvas || !waveWrap) return;
    paintReviewCanvas({
      canvas,
      waveWrap,
      peaks,
      peaksFrom,
      peaksSpan,
      viewStart,
      viewSpan,
      cues: app.cues,
      selectedIndex: play.selected,
      playTime: play.time,
      activeKey,
      hoverKey,
      dragKey,
      laneSelection,
      snapGuide,
      rulerH: RULER_H,
      laneH: LANE_H,
      resizeH: RESIZE_H,
    });
  }

  $effect(() => {
    void peaks;
    void viewStart;
    void viewSpan;
    void app.cues;
    void play.selected;
    void activeKey;
    void hoverKey;
    void dragKey;
    void laneSelection;
    void app.theme;
    void waveW;
    void snapGuide;
    void play.time;
    requestAnimationFrame(draw);
  });

  $effect(() => {
    if (!waveWrap) return;
    const ro = new ResizeObserver(() => {
      waveW = waveWrap?.clientWidth ?? 0;
      requestAnimationFrame(draw);
    });
    ro.observe(waveWrap);
    waveW = waveWrap.clientWidth;
    return () => ro.disconnect();
  });

  // ---------------- 播放头 / 擦洗 ----------------
  let rafId = 0;

  // 擦洗：拖动播放头或进度条时，play.time 立刻跟手，video.currentTime 每帧最多写一次，
  // 避免一次拖动触发上百个 seek 请求把解码器拖死。
  let scrubbing = false;
  let scrubTarget = 0;
  let scrubRaf = 0;
  let scrubResume = false;
  let lastSeekAt = 0;

  function setScrub(t: number) {
    const max = duration || video?.duration || Number.POSITIVE_INFINITY;
    const value = Math.max(0, Math.min(max, t));
    play.time = value;
    play.stopAt = 0;
    scrubTarget = value;
    // 每帧最多写一次 currentTime；窗口被遮挡时 rAF 会被节流，
    // 所以再加一条 16ms 的“立即写”分支，保证拖动时画面真的跟手。
    const now = performance.now();
    if (now - lastSeekAt >= 16) {
      lastSeekAt = now;
      flushScrub();
    } else if (!scrubRaf) {
      scrubRaf = requestAnimationFrame(flushScrub);
    }
  }

  function flushScrub() {
    scrubRaf = 0;
    if (!video) return;
    if (Math.abs(video.currentTime - scrubTarget) < 0.004) return;
    try {
      video.currentTime = scrubTarget;
    } catch {
      /* 媒体还没就绪：播放头数字照样跟手 */
    }
  }

  function beginScrub(t: number) {
    if (!scrubbing) {
      scrubResume = !video?.paused && !video?.ended && play.playing;
      if (scrubResume) video?.pause();
    }
    scrubbing = true;
    setScrub(t);
  }

  function endScrub() {
    if (!scrubbing) return;
    scrubbing = false;
    if (scrubRaf) {
      cancelAnimationFrame(scrubRaf);
      scrubRaf = 0;
    }
    if (video) {
      try {
        video.currentTime = scrubTarget;
      } catch {
        /* ignore */
      }
    }
    if (scrubResume) {
      scrubResume = false;
      void video?.play().catch(() => {});
    }
    // 擦洗期间不自动平移（手还在拖）；松手后把最终位置带回视窗
    revealPlayhead(scrubTarget);
  }

  function tick() {
    rafId = requestAnimationFrame(tick);
    if (!video) return;
    // 只在「真的能解码并且在播」时用 video.currentTime 驱动播放头。
    // MKV / HEVC 还没压好代理时 readyState 一直是 0，如果无条件同步，
    // 用户点哪里播放头都会被 video 的 0 覆盖回去——看起来就是「播放头坏了」。
    const ready = video.readyState >= 2 && !video.error;
    const t = ready ? video.currentTime : play.time;
    if (ready) {
      // 擦洗期间由手指说了算：seek 还没落盘时 currentTime 是滞后的，
      // 不能拿它把 play.time 拽回去，否则播放头会来回抖。
      if (!scrubbing && !video.paused && !video.ended) play.time = t;
      play.playing = !video.paused && !video.ended;
    } else if (!scrubbing) {
      play.playing = false;
    }
    if (play.stopAt > 0 && play.playing && t >= play.stopAt - 0.01) {
      video.pause();
      video.currentTime = play.stopAt;
      play.time = play.stopAt;
      play.stopAt = 0;
      return;
    }
    // 放大后播放：按「整页平移」跟随播放头，落点约在窗口左侧 15%
    if (
      follow &&
      play.playing &&
      !scrubbing &&
      viewSpan < duration * 0.96 &&
      (t > viewStart + viewSpan * 0.92 || t < viewStart + viewSpan * 0.02)
    ) {
      const next = clampTimelineView(t - viewSpan * 0.15, viewSpan, duration, MIN_SPAN);
      viewStart = next.start;
    }
  }

  function bindVideo(node: HTMLVideoElement) {
    video = node;
    attachVideo(node);
    rafId = requestAnimationFrame(tick);
    return {
      destroy() {
        cancelAnimationFrame(rafId);
        detachVideo(node);
        video = null;
      },
    };
  }

  // 波形高度拖拽
  let resizeStart: { y: number; h: number } | null = null;

  function onResizeDown(e: PointerEvent) {
    e.stopPropagation();
    e.preventDefault();
    resizeStart = { y: e.clientY, h: waveHeight };
    try {
      (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
    } catch {
      /* ignore */
    }
  }

  function onResizeMove(e: PointerEvent) {
    if (!resizeStart) return;
    const next = Math.max(110, Math.min(300, resizeStart.h + (e.clientY - resizeStart.y)));
    waveHeight = next;
  }

  function onResizeUp() {
    if (!resizeStart) return;
    resizeStart = null;
    localStorage.setItem('kikusub.waveHeight', String(Math.round(waveHeight)));
    requestAnimationFrame(draw);
  }

  // 所有「定位」入口都通过 seekNonce 进来，视频与播放头不会各走各的
  let seenSeek = 0;
  $effect(() => {
    const nonce = play.seekNonce;
    if (nonce === seenSeek) return;
    seenSeek = nonce;
    // 只依赖 nonce：play.time / playAfterSeek 用 untrack 读，否则「读一下再写回」
    // 会让这个 effect 自己触发自己（effect_update_depth_exceeded）。
    const request = untrack(() => ({ time: play.time, play: play.playAfterSeek }));
    const t = Math.max(0, Math.min(request.time, video?.duration || duration || request.time));
    // 暂停时的跳转也要让播放头可见（跟随开启时）；视频尚未绑定也要平移波形
    untrack(() => revealPlayhead(t));
    if (!video) return;
    scrubbing = false;
    if (scrubRaf) {
      cancelAnimationFrame(scrubRaf);
      scrubRaf = 0;
    }
    scrubTarget = t;
    try {
      video.currentTime = t;
    } catch {
      /* 媒体还没就绪 */
    }
    if (request.play) {
      play.playAfterSeek = false;
      void video.play().catch(() => {});
    }
  });

  /**
   * 恢复这部影片上次的工作现场；没有现场时用「第 1 条 + ~50× 视野」的默认态。
   *
   * 时机由 `videoMetaReady` 把关（`<video>` 的 loadedmetadata）：早于它 seek 会被
   * 浏览器丢弃，缩放也没有 duration 可夹。显式跳转（双引擎复核 / 质检面板点
   * 时间码）在 `focusRange()` 里记过一笔，这里消费掉并且**整次跳过历史恢复**，
   * 保证「用户刚点的那一下」不会被旧位置覆盖。
   *
   * 默认态（`lib/reviewStart`）解决的是长片第一次打开时「全片 1.0× + 播放头停在
   * 片头黑场」：没有快照就聚焦第 1 条字幕，而不是把整部片压进几百像素。
   */
  $effect(() => {
    const media = app.media;
    const ready = videoMetaReady;
    const d = duration;
    if (!media || !ready || d <= 0 || restoreDoneFor === media.path) return;
    const raw = readViewportForRestore(media.path);
    // 既没有现场快照、字幕也还没来：等字幕到了再定默认态（否则会停在片头全片）。
    // 这里先不记 restoreDoneFor，effect 会在 cues 变化时再跑一次。
    if (!raw && !app.cues.length) return;
    restoreDoneFor = media.path;
    const explicit = takeExplicitJump(media.path);
    const plan = planViewportRestore(raw, d, MIN_SPAN, { explicit });
    if (plan) {
      if (plan.span > 0) setView(plan.viewStart, plan.span);
      if (plan.selection) selection = { start: plan.selection.start, end: plan.selection.end };
      const index = resolveCueIndex(app.cues, raw);
      if (index !== null) {
        play.selected = index;
        play.selectNonce += 1;
      }
      // metadata 已经就绪：这里的 seek 一定落得下去
      if (plan.seekTo !== null) seekTo(plan.seekTo);
      return;
    }
    const start = explicit ? null : planInitialReviewView(d, app.cues, MIN_SPAN);
    if (!start) return;
    setView(start.viewStart, start.span);
    play.selected = start.cueIndex;
    play.selectNonce += 1;
    if (start.seekTo !== null) seekTo(start.seekTo);
  });

  /**
   * 已经挂了译文轨就默认双语：本次启动只在第一次「有译文轨 + 当前是原文」时
   * 翻一次，之后用户选什么就是什么（`setTrackMode` 仍负责持久化）。
   */
  $effect(() => {
    const hasTrack = Boolean(app.translations[app.trackLang]);
    if (!app.cues.length || !hasTrack || app.track !== 'source') return;
    if (claimTranslationDefault()) setTrackMode('both');
  });

  // 质检 / 选区聚焦请求
  let seenFocus = 0;
  $effect(() => {
    const req = play.focus;
    if (!req || req.nonce === seenFocus) return;
    seenFocus = req.nonce;
    // 右栏「聚焦」/ 质检定位也统一 69×：区间本身仍然框出来，但倍率不叠加。
    const span = focusSpan();
    const center = (req.start + req.end) / 2;
    // 这是程序化定位，不是用户手势：不要顺手关掉跟随
    setView(center - span / 2, span);
    selection = { start: req.start, end: req.end };
  });

  // ---------------- 交互 ----------------
  type DragMode =
    | 'none'
    | 'pending' // 已按下但还没超过阈值：仍可能只是单击
    | 'select'
    | 'playhead'
    | 'pan'
    | 'cue-move'
    | 'cue-l'
    | 'cue-r'
    | 'resize-l'
    | 'resize-r';

  let dragMode: DragMode = $state('none');
  let dragAnchor = 0;
  let dragMoved = false;
  let downX = 0;
  let downY = 0;
  let panStartX = 0;
  let panStartView = 0;

  let cueDrag: {
    indices: number[];
    start: number;
    end: number;
    edge: 'move' | 'start' | 'end';
    anchorT: number;
    curStart: number | null;
    curEnd: number | null;
    /** 本次拖动开始时冻结的吸附候选（含当时播放头）。 */
    snapTargets: number[];
    activeGuide: number | null;
  } | null = null;

  function xPlayhead() {
    return xOf(play.time);
  }

  function togglePlay() {
    if (!video) return;
    if (video.paused) void video.play().catch(() => {});
    else video.pause();
  }

  function seek(time: number) {
    scrubbing = false;
    if (scrubRaf) {
      cancelAnimationFrame(scrubRaf);
      scrubRaf = 0;
    }
    scrubTarget = time;
    seekTo(time);
  }

  // ---------------- 视频进度条（逐帧拖动预览） ----------------
  function timeFromTrack(clientX: number, el: HTMLElement) {
    const r = el.getBoundingClientRect();
    const ratio = Math.max(0, Math.min(1, (clientX - r.left) / Math.max(1, r.width)));
    return ratio * (duration || 0);
  }

  function onTrackPointerDown(e: PointerEvent) {
    if (e.button !== 0 || duration <= 0) return;
    e.preventDefault();
    trackDrag = true;
    try {
      (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
    } catch {
      /* ignore */
    }
    beginScrub(timeFromTrack(e.clientX, e.currentTarget as HTMLElement));
  }

  function onTrackPointerMove(e: PointerEvent) {
    if (!trackDrag) return;
    setScrub(timeFromTrack(e.clientX, e.currentTarget as HTMLElement));
  }

  function onTrackPointerUp(e: PointerEvent) {
    if (!trackDrag) return;
    trackDrag = false;
    try {
      (e.currentTarget as HTMLElement).releasePointerCapture(e.pointerId);
    } catch {
      /* ignore */
    }
    endScrub();
  }

  function wavePoint(e: PointerEvent) {
    const r = (waveWrap as HTMLDivElement).getBoundingClientRect();
    return { x: e.clientX - r.left, y: e.clientY - r.top, w: r.width, h: r.height };
  }

  /**
   * ⌘ 单击选一块字幕（表格行 / 波形主体 / 底部轨道条共用）。
   *
   * 基准是「当前句」：用户已经选中第 3 句，⌘ 点第 4 句就是 {3,4}，不需要先 ⌘ 点在 3 上。
   * 取消选中（⌘ 点已选的那块）时把当前行移到剩下的一块，避免当前行留在选中集合之外。
   */
  function metaSelect(i: number): void {
    const cue = app.cues[i];
    if (!cue) return;
    const anchor = app.cues[play.selected];
    const step = stepSelection(laneSelection, anchor ? laneKey(anchor) : '', laneKey(cue));
    laneSelection = step.keys;
    const first = step.kept ? i : indicesForLaneKeys(app.cues, step.keys)[0];
    const target = first >= 0 ? first : i;
    rangeAnchor = i;
    play.selected = target;
    // 播放头也要过去：否则「按播放头同步当前行」的 effect 会把当前行抢回上一句。
    seek(app.cues[target].start + 0.02);
    requestAnimationFrame(draw);
  }

  /**
   * ⇧ 单击（表格行 / 底部轨道块共用）：从锚点到这一句整段连选（含两端），
   * 并把时间选区设成「首块起点 → 末块终点」，方便在音轨上微调后同步到转写页。
   * 不 seek：跟随模式下跟过去会把视窗从选中的这一大段上带走。
   */
  function rangeSelectTo(i: number): void {
    const anchor =
      rangeAnchor >= 0 && rangeAnchor < app.cues.length ? rangeAnchor : play.selected;
    rangeAnchor = anchor;
    const range = rangeSelection(app.cues, anchor, i);
    if (!range) return;
    laneSelection = range.keys;
    selection = { start: range.start, end: range.end };
    // 默认视窗是全片，长选区两端拖不住：只在选区比视窗宽时缩到刚好装下（不放大、不 seek）。
    const span = range.end - range.start;
    if (span > viewSpan) setView(range.start - Math.max(0.2, span * 0.06), span * 1.12);
    play.selected = i;
    requestAnimationFrame(draw);
  }

  function beginPlayhead(t: number) {
    dragMode = 'playhead';
    dragMoved = true;
    waveCursor = 'ew-resize';
    beginScrub(t);
  }

  function beginSelectRange(a: number, b: number) {
    dragMode = 'select';
    dragMoved = true;
    dragAnchor = a;
    selection = { start: Math.min(a, b), end: Math.max(a, b) };
    laneSelection = [];
  }

  function beginCueDrag(e: PointerEvent, block: CueBlock, x: number) {
    const pixelWidth = Math.abs(xOf(block.end) - xOf(block.start));
    // 全景视图里很短的一句可能只有几像素宽：这时两端抓手会重叠，
    // 整个块都当“移动”处理，否则根本拖不动。
    const edge: 'move' | 'start' | 'end' =
      pixelWidth < EDGE * 3
        ? 'move'
        : Math.abs(x - xOf(block.start)) <= EDGE
          ? 'start'
          : Math.abs(x - xOf(block.end)) <= EDGE
            ? 'end'
            : 'move';
    cueDrag = {
      indices: block.indices,
      start: block.start,
      end: block.end,
      edge,
      anchorT: timeAt(e.clientX),
      curStart: null,
      curEnd: null,
      snapTargets: collectSnapTargets(app.cues, block.indices, play.time, duration),
      activeGuide: null,
    };
    dragMode = edge === 'move' ? 'cue-move' : edge === 'start' ? 'cue-l' : 'cue-r';
    dragKey = block.key;
    hoverKey = block.key;
    waveCursor = edge === 'move' ? 'grabbing' : 'ew-resize';
    selection = null;
    // 检查器与表格跟着正在调整的这句走
    if (block.indices.length) play.selected = block.indices[0];
  }

  function updateCueDrag(t: number) {
    const drag = cueDrag;
    if (!drag) return;
    const max = duration > 0 ? duration : Math.max(drag.end, t0());
    const base = cueDragTimes(drag, t, max);
    const snapped = snapCueTimes(
      base,
      drag.edge,
      drag.snapTargets,
      snapThreshold(waveW, viewSpan),
      max,
      drag.activeGuide,
      snapPrefs.enabled,
    );
    const { start, end } = snapped;
    drag.activeGuide = snapped.guide;
    snapGuide = snapped.guide;
    if (drag.curStart === start && drag.curEnd === end) return;
    drag.curStart = start;
    drag.curEnd = end;
    for (const i of drag.indices) {
      const cue = app.cues[i];
      if (cue) {
        cue.start = start;
        cue.end = end;
      }
    }
    const mid = (start + end) / 2;
    cueTip = {
      x: Math.max(44, Math.min(Math.max(44, waveW - 44), xOf(mid))),
      label: `${tcShort(start)} → ${tcShort(end)}`,
    };
    requestAnimationFrame(draw);
  }

  function finishCueDrag() {
    const drag = cueDrag;
    cueDrag = null;
    dragMode = 'none';
    dragKey = '';
    cueTip = null;
    snapGuide = null;
    waveCursor = 'crosshair';
    if (!drag) return;
    const moved =
      drag.curStart !== null &&
      drag.curEnd !== null &&
      (Math.abs(drag.curStart - drag.start) > 1e-6 ||
        Math.abs(drag.curEnd - drag.end) > 1e-6);
    if (!moved) {
      // 点了一下字幕块：和点表格行一样 seek，并把选区落到这一句。
      selection = { start: drag.start, end: drag.end };
      seek(drag.start + 0.02);
      return;
    }
    const changes = drag.indices.map((index) => ({
      index,
      start: drag.curStart as number,
      end: drag.curEnd as number,
    }));
    void applyCueTimes(changes);
  }

  function updateHover(e: PointerEvent) {
    if (!waveWrap) return;
    const pt = wavePoint(e);
    if (pt.y <= RULER_H + 1 || Math.abs(pt.x - xPlayhead()) <= PLAYHEAD_GRAB) {
      if (hoverKey) hoverKey = '';
      waveCursor = 'ew-resize';
      return;
    }
    if (pt.y >= pt.h - RESIZE_H - LANE_H) {
      const block = cueBlockAtX(app.cues, pt.x, xOf);
      if (!block) {
        if (hoverKey) hoverKey = '';
        waveCursor = 'crosshair';
        return;
      }
      if (hoverKey !== block.key) hoverKey = block.key;
      const pixelWidth = Math.abs(xOf(block.end) - xOf(block.start));
      const onEdge =
        pixelWidth >= EDGE * 3 &&
        (Math.abs(pt.x - xOf(block.start)) <= EDGE ||
          Math.abs(pt.x - xOf(block.end)) <= EDGE);
      waveCursor = onEdge ? 'ew-resize' : 'grab';
      return;
    }
    if (hoverKey) hoverKey = '';
    waveCursor = 'crosshair';
  }

  function onWavePointerDown(e: PointerEvent) {
    if (!waveWrap || e.button !== 0) return;
    contextMenu = null;
    try {
      (e.currentTarget as HTMLElement).setPointerCapture?.(e.pointerId);
    } catch {
      /* 合成事件 / 已释放的 pointerId：忽略即可，拖动逻辑不依赖捕获 */
    }
    const pt = wavePoint(e);
    const t = timeAt(e.clientX);
    dragMoved = false;
    downX = e.clientX;
    downY = e.clientY;
    cueTip = null;

    if (e.altKey) {
      dragMode = 'pan';
      panStartX = e.clientX;
      panStartView = viewStart;
      waveCursor = 'grabbing';
      // ⌥ 拖动只是临时平移视窗；跟随偏好保持不变（下次跳转/播放仍会带回播放头）
      return;
    }

    // 1) 顶部刻度条：专属擦洗带，拖它就只移动播放头，永远不会变成框选
    if (pt.y <= RULER_H + 1) {
      beginPlayhead(t);
      return;
    }

    // 2) 播放头两侧 8px：随时抓得住（不用精确点到 1px 的线）
    if (Math.abs(pt.x - xPlayhead()) <= PLAYHEAD_GRAB) {
      beginPlayhead(t);
      return;
    }

    // 3) 底部字幕轨道：拖块体移动整句，拖两端改时间戳
    if (pt.y >= pt.h - RESIZE_H - LANE_H) {
      const block = cueBlockAtX(app.cues, pt.x, xOf);
      if (block) {
        // ⌘ 单击 = 多选（再按一次取消）；⇧ 单击 = 从锚点连选。
        if (e.metaKey || e.ctrlKey) {
          metaSelect(block.indices[0]);
          dragMode = 'none';
          return;
        }
        if (e.shiftKey) {
          rangeSelectTo(block.indices[0]);
          dragMode = 'none';
          return;
        }
        laneSelection = [block.key];
        rangeAnchor = block.indices[0];
        beginCueDrag(e, block, pt.x);
        return;
      }
      if (laneSelection.length) {
        laneSelection = [];
        requestAnimationFrame(draw);
      }
      dragMode = 'pending';
      dragAnchor = t;
      return;
    }

    // 4) 波形主体：⌘ 点在句子范围内 = 多选（和底部轨道条同一个 key）；
    //    Shift 直接框选；否则先当作「可能是单击」。
    if (e.metaKey || e.ctrlKey) {
      const hit = app.cues.findIndex((cue) => cue.start <= t && t <= cue.end);
      if (hit >= 0) {
        metaSelect(hit);
        return;
      }
    }
    if (e.shiftKey) {
      beginSelectRange(play.time, t);
      return;
    }
    dragMode = 'pending';
    dragAnchor = t;
  }

  function onWavePointerMove(e: PointerEvent) {
    if (!waveWrap) return;
    if (dragMode === 'none') {
      updateHover(e);
      return;
    }
    const t = Math.max(0, Math.min(duration || t0(), timeAt(e.clientX)));
    if (dragMode === 'pan') {
      const dx = e.clientX - panStartX;
      const shift = -(dx / Math.max(1, waveW)) * viewSpan;
      setView(panStartView + shift, viewSpan);
      dragMoved = true;
      return;
    }
    if (dragMode === 'pending') {
      // 超过阈值才升级成框选：全局视图下 1px 可能是好几秒，
      // 但手抖不该把「单击跳转」判成「框选了几秒」。
      if (Math.hypot(e.clientX - downX, e.clientY - downY) < CLICK_SLOP) return;
      beginSelectRange(dragAnchor, t);
      return;
    }
    if (dragMode === 'playhead') {
      setScrub(t);
      return;
    }
    if (dragMode === 'cue-move' || dragMode === 'cue-l' || dragMode === 'cue-r') {
      updateCueDrag(t);
      return;
    }
    if (!selection) return;
    if (dragMode === 'resize-l') {
      selection = { start: Math.min(t, selection.end - 0.05), end: selection.end };
      if (laneSelection.length > 1) laneSelection = keysInRange(app.cues, selection.start, selection.end);
      dragMoved = true;
      return;
    }
    if (dragMode === 'resize-r') {
      selection = { start: selection.start, end: Math.max(t, selection.start + 0.05) };
      if (laneSelection.length > 1) laneSelection = keysInRange(app.cues, selection.start, selection.end);
      dragMoved = true;
      return;
    }
    dragMoved = true;
    selection = { start: Math.min(dragAnchor, t), end: Math.max(dragAnchor, t) };
  }

  // 工作现场定时落盘：播放头/视窗/选区一起存，重启或切页回来能接上。
  // 不在 $effect 里直接写：播放时 play.time 每帧变化，会变成每帧一次 localStorage。
  $effect(() => {
    const media = app.media;
    if (!media) return;
    const path = media.path;
    const timer = setInterval(() => {
      // 换片后旧 effect 的清理可能晚一拍：只写仍然挂着的那部片
      if (app.media?.path === path) persistViewport(path);
    }, 1500);
    return () => {
      clearInterval(timer);
      // 卸载（切去别的页面）时补一次；换片的情况由媒体变化 effect 负责
      if (app.media?.path === path) persistViewport(path);
    };
  });

  function t0() {
    return viewStart + viewSpan;
  }

  /**
   * 把浮层挂到 body 下。
   *
   * `.view-enter.animated` 的切页动画带 `animation-fill-mode: both`，结束后
   * 计算出的 transform 仍是 identity matrix——它会让 `position: fixed` 相对
   * 这个容器定位，于是右键菜单被整体推开了「侧栏 + 工具栏」那么多（用户报过
   * 「菜单离鼠标太远」）。挂到 body 后 clientX/clientY 才是真正的视口坐标。
   */
  function portal(node: HTMLElement) {
    document.body.appendChild(node);
    return {
      destroy() {
        node.remove();
      },
    };
  }

  /** 光标下是否有字幕；返回下标，没有就 -1。 */
  function cueUnder(t: number): number {
    for (let i = 0; i < app.cues.length; i += 1) {
      if (app.cues[i].start <= t && t <= app.cues[i].end) return i;
    }
    return -1;
  }

  /** 右键：菜单出现在光标处；越靠近窗口边缘越往回收，避免被裁掉。 */
  function onWaveContextMenu(e: MouseEvent) {
    e.preventDefault();
    const t = Math.max(0, Math.min(duration || Number.POSITIVE_INFINITY, timeAt(e.clientX)));
    const hit = cueUnder(t);
    if (hit >= 0) play.selected = hit;
    // 合并目标：优先用刚框选的区间，其次用底部轨道的 ⌘ 多选。
    let merge: number[] = [];
    if (selection && selection.end - selection.start > 0.08) {
      merge = indicesInRange(app.cues, selection.start, selection.end);
    } else if (laneSelection.length >= 2) {
      merge = indicesForLaneKeys(app.cues, laneSelection);
    }
    if (merge.length < 2) merge = [];
    const x = Math.min(e.clientX, window.innerWidth - 236);
    const y = Math.min(e.clientY, window.innerHeight - 190);
    contextMenu = { x, y, t, index: hit, merge };
  }

  /** 字幕表整行右键：选中这一行，并提供「以此句音频新建音色」。 */
  function onCueContextMenu(e: MouseEvent, index: number) {
    e.preventDefault();
    e.stopPropagation();
    play.selected = index;
    const cue = app.cues[index];
    const merge = laneSelection.length >= 2 ? indicesForLaneKeys(app.cues, laneSelection) : [];
    const x = Math.min(e.clientX, window.innerWidth - 236);
    const y = Math.min(e.clientY, window.innerHeight - 190);
    contextMenu = { x, y, t: cue?.start ?? timeAt(e.clientX), index, merge };
  }

  function canSplitHere(): boolean {
    const menu = contextMenu;
    if (!menu || menu.index < 0) return false;
    const cue = app.cues[menu.index];
    return Boolean(cue && canSplitAt(cue, menu.t));
  }

  function splitHere() {
    const menu = contextMenu;
    contextMenu = null;
    if (!menu || menu.index < 0) return;
    laneSelection = [];
    selection = null;
    void splitCueAt(menu.index, menu.t);
  }

  function mergeHere(indices: number[]) {
    contextMenu = null;
    laneSelection = [];
    selection = null;
    void mergeCuesAt(indices);
  }

  async function deleteSelectedNow() {
    if (!app.cues.length) {
      toast('当前没有可删除的字幕', 'warn');
      return;
    }
    const indices = deleteTargets(app.cues, laneSelection, play.selected);
    if (!indices.length) {
      toast('先在底部字幕轨道点选一条，⌘ 点击可以多选', 'warn');
      return;
    }
    const anchor = Math.min(...indices);
    if (indices.length > 1) {
      await deleteCues(indices);
    } else {
      const ok = await deleteCue(indices[0]);
      if (ok) toast('已删除这条字幕（⌘Z 可撤销）');
    }
    laneSelection = [];
    play.selected = Math.max(0, Math.min(anchor, app.cues.length - 1));
    play.selectNonce += 1;
  }

  /** 供 App 的「删除选中的字幕」快捷键调用。 */
  export function api_deleteSelected() {
    void deleteSelectedNow();
  }

  async function addCueHere() {
    const t = contextMenu?.t ?? play.time;
    contextMenu = null;
    await insertCueAt(t);
  }

  /** 右键「以此句音频新建音色…」：先给角色起名，再让后端精确切片。 */
  function openVoiceDialog(index: number) {
    contextMenu = null;
    const cue = app.cues[index];
    if (!cue) return;
    voiceDialog = {
      index,
      name: `角色 ${tts.custom.length + 1}`,
      refText: cue.text,
    };
  }

  // 浮层打开后把焦点放进名字输入框（比 autofocus 更可控，也不会触发 Svelte 的无障碍告警）
  $effect(() => {
    if (!voiceDialog) return;
    void nextTick().then(() => {
      voiceNameEl?.focus();
      voiceNameEl?.select();
    });
  });

  async function createVoiceFromCue() {
    if (!voiceDialog) return;
    const name = voiceDialog.name.trim();
    if (!name) {
      toast('先给这个音色起个名字', 'warn');
      return;
    }
    voiceBusy = true;
    try {
      await extractTtsVoiceFromCue(voiceDialog.index, name, voiceDialog.refText);
      voiceDialog = null;
    } catch (err) {
      toast(`提取音色失败：${(err as Error).message}`, 'error');
    } finally {
      voiceBusy = false;
    }
  }

  function onWavePointerUp(e: PointerEvent) {
    try {
      (e.currentTarget as HTMLElement).releasePointerCapture?.(e.pointerId);
    } catch {
      /* ignore */
    }
    const mode = dragMode;
    if (mode === 'playhead') {
      dragMode = 'none';
      endScrub();
      return;
    }
    if (mode === 'pan') {
      dragMode = 'none';
      waveCursor = 'crosshair';
      return;
    }
    if (mode === 'cue-move' || mode === 'cue-l' || mode === 'cue-r') {
      finishCueDrag();
      return;
    }
    if (mode === 'pending') {
      // 没超过阈值 = 单击跳转；绝不因为手抖变成框选
      dragMode = 'none';
      selection = null;
      seek(dragAnchor);
      return;
    }
    dragMode = 'none';
    if (mode === 'select') {
      if (!selection || !dragMoved || selection.end - selection.start < 0.08) {
        // 单击：跳转并清掉选区
        const t = selection ? selection.start : dragAnchor;
        selection = null;
        seek(t);
      } else {
        const hit = cueIndexAtTime(app.cues, selection.start);
        play.selected = hit >= 0 ? hit : play.selected;
      }
    }
  }


  function onWaveWheel(e: WheelEvent) {
    e.preventDefault();
    if (duration <= 0) return;
    const panning = e.shiftKey || (Math.abs(e.deltaX) > Math.abs(e.deltaY) && !e.ctrlKey);
    if (panning) {
      const delta = e.shiftKey ? e.deltaY : e.deltaX;
      setView(viewStart + (delta / Math.max(1, waveW)) * viewSpan, viewSpan);
      return;
    }
    // 触控板捏合在 macOS 上是 ctrlKey=true 的 wheel
    const factor = Math.exp(e.deltaY * (e.ctrlKey ? 0.012 : 0.0022));
    zoomAt(timeAt(e.clientX), factor);
  }

  function zoomAt(time: number, factor: number) {
    const next = zoomTimelineView({ start: viewStart, span: viewSpan }, time, factor, duration, MIN_SPAN);
    setView(next.start, next.span);
  }

  function zoomSliderInput(e: Event) {
    const v = Number((e.currentTarget as HTMLInputElement).value);
    // 0=全景，100=最深
    const span = sliderToSpan(v, duration, MIN_SPAN);
    const center = play.time;
    setView(center - span / 2, span);
  }

  const sliderValue = $derived(spanToSlider(viewSpan, duration, MIN_SPAN));

  function fit() {
    setView(0, duration || viewSpan);
  }

  /** 聚焦统一用同一个 span：duration / 69。媒体还没就绪时才退回 2–12 秒。 */
  const focusSpan = () => focusTimelineSpan(duration, viewSpan, MIN_SPAN, FOCUS_ZOOM);

  /** 一键聚焦：把播放头附近放大到固定 69×（不随当前缩放叠加）。 */
  function focusPlayhead() {
    const span = focusSpan();
    setView(play.time - span / 2, span);
    follow = true;
  }

  function focusSelection() {
    if (!selection) return;
    const span = focusSpan();
    const center = (selection.start + selection.end) / 2;
    setView(center - span / 2, span);
  }

  function clearSelection() {
    selection = null;
  }

  function toggleFollow() {
    follow = !follow;
    // 开启的瞬间就把当前播放头带回画面，不必先播放一下
    if (follow) revealPlayhead(play.time);
  }

  function selectCue(i: number, doSeek = true, withRange = false) {
    const cue = app.cues[i];
    if (!cue) return;
    play.selected = i;
    rangeAnchor = i;
    // 普通单击 = 单选。集合必须同步成 {这一句}，否则之后 ⌘ 点第二句只能得到一条。
    laneSelection = [laneKey(cue)];
    if (withRange) selection = cueRange(cue);
    if (doSeek) seek(cue.start + 0.02);
  }

  // ---------------- 查找与替换（⌘F，覆盖原文 / 译文 / 双语） ----------------
  let findInput = $state<HTMLInputElement | null>(null);
  /** 正在提交单处替换：挡住连点，避免两个 patch 请求把 pos 抢乱。 */
  let findBusy = $state(false);

  let findSkipped = $state<FindSkipAnchor[]>([]);

  /**
   * 搜索范围跟随当前显示模式：原文只搜原文、译文只搜译文、双语两条都搜。
   * 双语里同一个词可能同时命中上下两行，所以命中记录必须带 track，替换时
   * 才能改对那张表（原文进 review_cues，译文进 translations[lang]）。
   */
  const findTracks = $derived<FindTrack[]>(
    app.track === 'target' ? ['target'] : app.track === 'both' ? ['source', 'target'] : ['source'],
  );

  /** 所有命中（含已跳过）：记录属于第几条 / 哪条轨 / 在文本里的起止。 */
  const rawFindMatches = $derived(
    collectFindHits(
      app.cues,
      findTracks,
      findState.query,
      findState.caseSensitive,
      translationTextAt,
    ),
  );

  const skippedFindKeys = $derived(new Set(findSkipped.map(findHitKey)));
  /** 待处理命中：跳过的不再参与上一处/下一处/替换，本轮到它就直接略过。 */
  const findMatches = $derived(filterSkippedHits(rawFindMatches, skippedFindKeys));
  const skippedHitCount = $derived(
    findSkipped.length ? countSkippedHits(rawFindMatches, skippedFindKeys) : 0,
  );
  /** 某一轨里被跳过的起点，渲染删除线用；单行字幕与原文下标一致。 */
  const skippedStarts = $derived(skippedStartsByCueTrack(findSkipped));

  const matchedCueSet = $derived(
    new Set((findState.open ? findMatches : []).map((hit) => hit.cue)),
  );

  /** 当前这一处（未跳过的）在原始命中里的序号，用来只点亮同一个词里的那一处。 */
  const currentFind = $derived.by(() => {
    if (!findState.open) return null;
    const hit = findMatches[findState.pos];
    if (!hit) return null;
    return { ...hit, ordinal: ordinalOfHit(rawFindMatches, hit) };
  });

  const findPrevKey = $derived(formatCombo(comboOf('review.findPrev')));
  const findNextKey = $derived(formatCombo(comboOf('review.findNext')));

  function resetFindSession() {
    findSkipped = [];
    findState.pos = 0;
  }

  $effect(() => {
    const nonce = findState.focusNonce;
    void nonce;
    if (!findState.open) return;
    void nextTick().then(() => {
      findInput?.focus();
      findInput?.select();
    });
  });

  // 关掉查找栏就结束「本轮」：下次重开时不记得上一轮跳过过谁。
  $effect(() => {
    if (!findState.open && findSkipped.length) findSkipped = [];
  });

  // 原文 / 译文 / 双语切换会改变搜索范围，旧的跳过锚点不再对应同一批命中。
  let lastFindTracksKey = '';
  $effect(() => {
    const key = findTracks.join(',');
    if (key === lastFindTracksKey) return;
    const firstRun = !lastFindTracksKey;
    lastFindTracksKey = key;
    if (!firstRun) resetFindSession();
  });

  // 替换 / 跳过之后匹配数会变少：把当前位置拉回合法范围
  $effect(() => {
    const total = findMatches.length;
    if (total === 0) {
      if (findState.pos !== 0) findState.pos = 0;
      return;
    }
    if (findState.pos >= total) findState.pos = 0;
  });

  /**
   * 替换掉某条字幕里的一处命中后，同一轨后面那些跳过锚点的起点会整体左/右移。
   * 不平移的话，被跳过的逗号会因为前一个逗号被删掉而“复活”。
   */
  function shiftFindAnchors(
    cue: number,
    track: FindTrack,
    at: number,
    removed: number,
    inserted: number,
  ) {
    if (!findSkipped.length) return;
    const delta = inserted - removed;
    if (!delta) return;
    let changed = false;
    const next = findSkipped.map((anchor) => {
      if (anchor.cue !== cue || anchor.track !== track) return anchor;
      if (anchor.start <= at) return anchor;
      changed = true;
      return { ...anchor, start: Math.max(at, anchor.start + delta) };
    });
    if (changed) findSkipped = next;
  }

  function revealFindHit(hit: FindHit | undefined) {
    if (!hit) return;
    jumpToCue(hit.cue);
  }

  /**
   * 整批替换未跳过的命中以后，同一轨里被跳过的字符会随前面的删/插整体平移。
   * 按替换前的未跳过命中累计位移，把跳过锚点搬到新位置，删除线才不会消失。
   */
  function reseatSkippedAfterReplaceAll(hits: FindHit[], inserted: number) {
    if (!findSkipped.length) return;
    const byTrack = new Map<string, FindHit[]>();
    for (const hit of hits) {
      const key = `${hit.cue}:${hit.track}`;
      let list = byTrack.get(key);
      if (!list) {
        list = [];
        byTrack.set(key, list);
      }
      list.push(hit);
    }
    findSkipped = findSkipped.map((anchor) => {
      let shift = 0;
      for (const hit of byTrack.get(`${anchor.cue}:${anchor.track}`) ?? []) {
        if (hit.start < anchor.start) shift += inserted - (hit.end - hit.start);
      }
      return shift ? { ...anchor, start: Math.max(0, anchor.start + shift) } : anchor;
    });
  }

  function findGo(delta: number) {
    if (findBusy) return;
    const total = findMatches.length;
    if (!total) {
      toast(
        rawFindMatches.length
          ? '本轮匹配都已跳过，改一下查找词可以重新开始'
          : '没有找到匹配的文本',
        'warn',
      );
      return;
    }
    findState.pos = (findState.pos + delta + total) % total;
    revealFindHit(findMatches[findState.pos]);
  }

  async function findReplaceCurrent() {
    if (!findState.query || findBusy) return;
    const total = findMatches.length;
    if (!total) {
      toast(
        rawFindMatches.length
          ? '本轮匹配都已跳过，改一下查找词可以重新开始'
          : '没有可替换的匹配',
        'warn',
      );
      return;
    }
    const hit = findMatches[Math.min(findState.pos, total - 1)];
    if (!hit) return;
    const posBefore = findState.pos;
    const query = findState.query;
    const replacement = findState.replacement;
    const caseSensitive = findState.caseSensitive;
    const removed = hit.end - hit.start;
    findBusy = true;
    try {
      const ok =
        hit.track === 'source'
          ? await replaceInCue(hit.cue, query, replacement, caseSensitive, hit.start)
          : await replaceInTranslation(hit.cue, query, replacement, caseSensitive, hit.start);
      if (!ok) return;
      const where = hit.track === 'source' ? '原文' : '译文';
      // 请求期间用户把查找栏关了：替换照常生效，但不要再抢选中/滚动。
      if (!findState.open) {
        toast(`已替换 1 处${where}`);
        return;
      }
      // 请求期间用户改了查找条件：替换已经发生，但不要拿旧位置继续前进。
      if (findState.query !== query || findState.caseSensitive !== caseSensitive) {
        toast(`已替换 1 处${where}`);
        return;
      }
      // 被替换的命中已经从数组消失，后面的跳过锚点要跟着平移。
      shiftFindAnchors(hit.cue, hit.track, hit.start, removed, replacement.length);
      const left = findMatches.length;
      if (!left) {
        findState.pos = 0;
        // 还有没被替换的命中，说明它们都已经标记跳过了，不能因为“没得替换”就清标记。
        if (!rawFindMatches.length) findSkipped = [];
        toast(
          rawFindMatches.length
            ? '已替换完最后一处待处理匹配，其余都已跳过'
            : '已替换最后一处，本轮没有待处理匹配了',
        );
        return;
      }
      let wrapped = false;
      if (posBefore >= left) {
        findState.pos = 0;
        wrapped = true;
      } else {
        findState.pos = Math.min(posBefore, left - 1);
      }
      revealFindHit(findMatches[findState.pos]);
      toast(`已替换 1 处${where}${wrapped ? '，已回到第一处' : ''}`);
    } finally {
      findBusy = false;
    }
  }

  /** 跳过当前这一处：不写字幕、不进历史，本轮不再回到它。 */
  function findSkip() {
    if (!findState.query || findBusy) return;
    const total = findMatches.length;
    if (!total) {
      toast(
        rawFindMatches.length
          ? '本轮匹配都已跳过，改一下查找词可以重新开始'
          : '没有可跳过的匹配',
        'warn',
      );
      return;
    }
    const hit = findMatches[Math.min(findState.pos, total - 1)];
    if (!hit) return;
    const posBefore = findState.pos;
    const key = findHitKey(hit);
    if (!skippedFindKeys.has(key)) {
      findSkipped = [...findSkipped, { cue: hit.cue, track: hit.track, start: hit.start }];
    }
    const left = findMatches.length;
    if (!left) {
      toast('已跳过最后一处，本轮没有待处理匹配了');
      return;
    }
    let wrapped = false;
    if (posBefore >= left) {
      findState.pos = 0;
      wrapped = true;
    } else {
      findState.pos = Math.min(posBefore, left - 1);
    }
    revealFindHit(findMatches[findState.pos]);
    toast(`已跳过 1 处，本轮剩余 ${left} 处${wrapped ? '（已回到第一处）' : ''}`);
  }

  async function findReplaceAll() {
    if (!findState.query || findBusy) return;
    const query = findState.query;
    const replacement = findState.replacement;
    const caseSensitive = findState.caseSensitive;
    const activeBefore = findMatches.slice();
    findBusy = true;
    try {
      // 原文 + 译文一次提交：双语模式下只压一步历史，⌘Z 一次退干净。
      const counts = await replaceAllInTracks(
        query,
        replacement,
        caseSensitive,
        findTracks,
        skippedFindKeys,
      );
      const count = counts.source + counts.target;
      if (!count) {
        toast(
          skippedHitCount ? '剩余命中都已跳过，没有可替换的' : '没有找到匹配的文本',
          'warn',
        );
        return;
      }
      findState.pos = 0;
      // 请求期间用户改了查找条件：跳过集合已经被重置，不要再用旧位移去搬。
      if (findState.query === query && findState.caseSensitive === caseSensitive) {
        reseatSkippedAfterReplaceAll(activeBefore, replacement.length);
      }
      const kept = skippedHitCount;
      const detail =
        counts.source && counts.target
          ? `（原文 ${counts.source} / 译文 ${counts.target}）`
          : counts.target
            ? '（译文）'
            : '';
      toast(`已替换 ${count} 处${detail}${kept ? `，跳过 ${kept} 处保持原样` : ''}`);
    } finally {
      findBusy = false;
    }
  }

  /** 画面叠加层：一条 cue 里的硬换行拆成多行，空行丢掉。 */
  function captionTextLines(text: string): string[] {
    return String(text || '')
      .split('\n')
      .map((line) => line.trim())
      .filter(Boolean);
  }

  /**
   * 表格里一行只能放一行文字（虚拟列表固定行高），多行 cue 用「 / 」分隔显示，
   * 不再让 newline 被 nowrap 压成一个空格——两种语言粘在一起看起来像识别错误。
   * 完整原文仍在检查器文本框里按原样编辑。
   */
  function cueDisplayText(text: string): string {
    return captionTextLines(text).join(' / ');
  }

  /** 切片逻辑在 lib/findMatches（纯函数），这里只把当前的查找上下文接进来。 */
  const highlight = (
    text: string,
    track: FindTrack,
    currentOrdinal: number,
    skipped?: Set<number>,
  ) =>
    highlightSegments(text, track, currentOrdinal, skipped, {
      open: findState.open,
      query: findState.query,
      caseSensitive: findState.caseSensitive,
      tracks: findTracks,
    });

  /** 当前命中在这条 cue / 这条轨里的序号；不是当前行返回 -1。 */
  function currentOrdinalFor(index: number, track: FindTrack): number {
    const cur = currentFind;
    if (!cur || cur.cue !== index || cur.track !== track) return -1;
    return cur.ordinal;
  }

  function skippedStartsFor(index: number, track: FindTrack): Set<number> | undefined {
    return skippedStarts.get(`${index}:${track}`);
  }

  async function retranscribeRow(i: number) {
    if (busy) {
      toast('已有任务在跑，请先等它完成或中途打断', 'warn');
      return;
    }
    const cue = app.cues[i];
    if (!cue) return;
    play.selected = i;
    await transcribeRange({
      start: cue.start,
      end: cue.end,
      engine,
      label: `第 ${i + 1} 条`,
    });
  }

  async function transcribeSelection() {
    if (!selection) return;
    if (busy) {
      toast('已有任务在跑，请先等它完成或中途打断', 'warn');
      return;
    }
    await transcribeRange({
      start: selection.start,
      end: selection.end,
      engine,
      label: '选区',
      padStart: 0.1,
      padEnd: 0.2,
    });
  }

  function sendSelectionToTranscribe() {
    if (!selection) return;
    app.slice = {
      start: tcShort(selection.start),
      end: tcShort(selection.end),
      nonce: (app.slice?.nonce ?? 0) + 1,
    };
    app.view = 'transcribe';
    app.inspectorOpen = false;
    toast('已把时间选区同步到转写页，可直接开始局部转写');
  }

  let revealRaf = 0;

  function revealRow(i: number) {
    if (!rowsEl) return;
    // 判定与目标位置都是纯计算（lib/reviewTable.ts），这里只负责滚动动画
    const target = revealScrollTop({
      index: i,
      scrollTop: rowsEl.scrollTop,
      viewH: rowsEl.clientHeight,
      rowH: rowHeight,
    });
    if (target === null) return;
    cancelAnimationFrame(revealRaf);
    // 播放中必须瞬时：平滑滚动会被后台窗口节流，让人以为表格没跟上。
    // 暂停时的跳转用 120ms 自己滚，手感比浏览器自带 smooth（约 300ms）干脆。
    if (play.playing || matchMedia('(prefers-reduced-motion: reduce)').matches) {
      rowsEl.scrollTop = target;
      return;
    }
    const from = rowsEl.scrollTop;
    const dist = target - from;
    if (Math.abs(dist) < 2) {
      rowsEl.scrollTop = target;
      return;
    }
    const t0 = performance.now();
    const step = (now: number) => {
      const k = Math.min(1, (now - t0) / 120);
      if (rowsEl) rowsEl.scrollTop = from + dist * (1 - Math.pow(1 - k, 3)); // 导入新媒体时视图可能已卸载
      if (k < 1) revealRaf = requestAnimationFrame(step);
    };
    revealRaf = requestAnimationFrame(step);
  }

  /**
   * 播放头（点波形 / 拖播放头 / 播放中）进入某句字幕时：
   * 底部表格滚到那一行，右侧检查器切到那一条。
   * 双语同区间的两行以块内第一条为准，表格里整块都会高亮。
   */
  $effect(() => {
    const hit = cueIndex;
    if (hit < 0) return;
    const hitCue = app.cues[hit];
    if (!hitCue) return;
    const key = `${hitCue.start}:${hitCue.end}`;
    const selected = app.cues[play.selected];
    // 用户点的是同一块里的第 2/3 行（双语/三语）时保留他的选择，
    // 不要因为我们“块内第一条”的规则把选中行抢回去。
    const selectedInBlock = Boolean(
      selected && `${selected.start}:${selected.end}` === key,
    );
    let first = hit;
    while (first > 0 && `${app.cues[first - 1].start}:${app.cues[first - 1].end}` === key) {
      first -= 1;
    }
    if (first === lastRevealed) return;
    lastRevealed = first;
    if (isTypingTarget()) return;
    if (!selectedInBlock && play.selected !== first) play.selected = first;
    revealRow(selectedInBlock ? play.selected : first);
  });

  /**
   * 程序化选中（转写选区完成 / 右键添加字幕 / 查找定位）必须强制滚到目标行。
   * cueIndex 的 effect 有 lastRevealed 去重：局部转写的新句经常落在同一下标，
   * 只改 play.selected 会被当成「已经在看这句」而不滚动——用户必须手动点一下
   * 新字幕才能让底部和右侧同步。selectNonce 每次自增，绕过去重。
   */
  let seenSelect = 0;
  $effect(() => {
    const nonce = play.selectNonce;
    if (nonce === seenSelect) return;
    seenSelect = nonce;
    const index = untrack(() => play.selected);
    if (index < 0 || index >= app.cues.length) return;
    lastRevealed = index;
    revealRow(index);
  });

  // 字幕被删除 / 切割 / 合并后，多选里的旧 key 已经不存在：悄悄清掉。
  $effect(() => {
    void app.cuesRevision;
    if (!laneSelection.length) return;
    const keys = new Set(app.cues.map((cue) => `${cue.start}:${cue.end}`));
    const next = laneSelection.filter((key) => keys.has(key));
    if (next.length !== laneSelection.length) laneSelection = next;
  });

  // 切回「原文 / 译文 / 双语」时，表格要滚到当前时间对应的那一句。
  // 双语是双行高，行位置会整体变化；必须等 DOM 更新后再 revealRow。
  let lastTrackKey = `${app.track}:${app.trackLang}`;
  $effect(() => {
    const key = `${app.track}:${app.trackLang}`;
    if (key === lastTrackKey) return;
    lastTrackKey = key;
    const hit = untrack(() => cueIndex);
    const target = hit >= 0 ? hit : untrack(() => play.selected);
    if (target < 0 || target >= app.cues.length) return;
    lastRevealed = -1;
    play.selected = target;
    play.selectNonce += 1;
    void nextTick().then(() => revealRow(target));
  });

  // 跟随是持久偏好：重开应用也记住用户的选择
  $effect(() => {
    localStorage.setItem('kikusub.follow', follow ? '1' : '0');
  });

  $effect(() => {
    if (!rowsEl) return;
    const ro = new ResizeObserver(() => {
      viewH = rowsEl?.clientHeight ?? 0;
    });
    ro.observe(rowsEl);
    viewH = rowsEl.clientHeight;
    return () => ro.disconnect();
  });

  // 菜单 / 快捷键
  export function api_play() {
    togglePlay();
  }
  export function api_step(delta: number) {
    const next = Math.max(0, Math.min(app.cues.length - 1, play.selected + delta));
    if (app.cues[next]) selectCue(next);
  }

  /** Esc：只清时间选区，不动当前行 / 多选集合。返回是否真的清掉了。 */
  export function api_clearSelection(): boolean {
    if (!selection) return false;
    selection = null;
    return true;
  }
  export function api_focus() {
    focusPlayhead();
  }

  /** ⇧Z：全片适应 / 回到上一次缩放。 */
  export function api_toggleFit() {
    const next = toggleFitView({ start: viewStart, span: viewSpan }, preFitView, duration, MIN_SPAN);
    preFitView = next.saved;
    setView(next.view.start, next.view.span);
  }

  /** 供 App 的「查找：上一处 / 下一处」快捷键调用。 */
  export function api_findStep(delta: number) {
    if (!findState.open) return;
    findGo(delta);
  }
</script>

<div class="review">
  <div class="stage">
    <ReviewStage
      {src}
      {captionLines}
      gate={videoGate}
      proxyReason={app.media?.proxy_reason ?? ''}
      onvideo={(node) => (video = node)}
      attach={bindVideo}
      onerror={(el) => {
        videoFailed = true;
        if (blankTimer !== undefined) {
          clearTimeout(blankTimer);
          blankTimer = undefined;
        }
        logEvent('warn', 'video-error', `code=${el.error?.code ?? '?'} src=${el.currentSrc.slice(0, 160)}`);
      }}
      onloadedmetadata={(el) => {
        videoFailed = false;
        play.duration = el.duration || duration;
        const t = play.time;
        if (t > 0.2) el.currentTime = t;
        // 现场的恢复 effect 等这个开关：metadata 之前 seek 会被浏览器丢掉
        videoMetaReady = true;
      }}
      onloadeddata={(el) => {
        // 首帧真正出来：兜底计时与提示都作废（慢盘误判最多闪一下）。
        // videoWidth 为 0 说明容器读到了但视频轨道解不出来，仍要按黑屏处理。
        if (!hasDecodedFrame(el.readyState, el.videoWidth)) return;
        videoDecoded = true;
        videoFailed = false;
        blankTimedOut = false;
        if (blankTimer !== undefined) {
          clearTimeout(blankTimer);
          blankTimer = undefined;
        }
      }}
      onstartproxy={() => void startProxyJob()}
      onimportproxy={() => void importProxyFromFile()}
    />

    <ReviewTransport
      playing={play.playing}
      time={play.time}
      {duration}
      {progressPct}
      fps={app.media?.video_fps ?? null}
      rate={transport.rate}
      {trackDrag}
      {zoomX}
      {sliderValue}
      {follow}
      {selection}
      laneSelection={multiKeys}
      {rangeBusy}
      ontogglePlay={togglePlay}
      onresetRate={() => resetRate()}
      onTrackDown={onTrackPointerDown}
      onTrackMove={onTrackPointerMove}
      onTrackUp={onTrackPointerUp}
      onZoomAt={zoomAt}
      onZoomSlider={zoomSliderInput}
      onFit={fit}
      onFocusPlayhead={focusPlayhead}
      onToggleFollow={toggleFollow}
      onDelete={deleteSelectedNow}
      onTranscribe={transcribeSelection}
      onFocusSelection={focusSelection}
      onSendSelection={sendSelectionToTranscribe}
      onSeekSelection={() => selection && seekTo(selection.start, { stopAt: selection.end, play: true })}
      onClearLane={() => (laneSelection = [])}
      onClearSelection={clearSelection}
    />
  </div>

  <div class="timeline">
    <ReviewWaveTrack
      height={waveHeight}
      cursor={waveCursor}
      dragging={dragMode !== 'none'}
      marks={chapters.marks}
      {duration}
      {viewStart}
      {viewSpan}
      rulerH={RULER_H}
      playTime={play.time}
      playheadX={xPlayhead()}
      {waveW}
      selectionLeft={selection ? xOf(selection.start) : null}
      selectionWidth={selection ? xOf(selection.end) - xOf(selection.start) : 0}
      {cueTip}
      {loadingPeaks}
      hasPeaks={peaks.length > 0}
      onwrap={(node) => (waveWrap = node)}
      oncanvas={(node) => (canvas = node)}
      onpointerdown={onWavePointerDown}
      onpointermove={onWavePointerMove}
      onpointerup={onWavePointerUp}
      onpointerleave={(e) => {
        if (dragMode === 'none') {
          hoverKey = '';
          waveCursor = 'crosshair';
        }
      }}
      onwheel={onWaveWheel}
      oncontextmenu={onWaveContextMenu}
      ondblclick={(e) => {
        const t = timeAt(e.clientX);
        const span = Math.max(1.5, Math.min(10, viewSpan / 5 || 5));
        setView(t - span / 2, span);
      }}
      onseekmark={(id) => seekToMark(id)}
      onselectionresize={(edge, e) => {
        e.stopPropagation();
        dragMode = edge === 'l' ? 'resize-l' : 'resize-r';
      }}
      onfocusplayhead={focusPlayhead}
      onresizedown={onResizeDown}
      onresizemove={onResizeMove}
      onresizeup={onResizeUp}
    />
  </div>

  <ReviewTable
    view={{
      track: app.track,
      rows: visibleCues,
      rowStart,
      rowEnd,
      total: app.cues.length,
      rowHeight,
      padTop: rowStart * rowHeight,
      padBottom: Math.max(0, (app.cues.length - rowEnd) * rowHeight),
      selected: play.selected,
      multiKeys,
      activeKey,
      matchedSet: matchedCueSet,
      findCue: currentFind?.cue ?? -1,
      busy,
      displayText: cueDisplayText,
      translationAt,
      isStale: isTranslationStale,
      highlight,
      ordinalFor: currentOrdinalFor,
      skippedFor: skippedStartsFor,
    }}
    find={{
      open: findState.open,
      query: findState.query,
      replacement: findState.replacement,
      caseSensitive: findState.caseSensitive,
      count: findMatches.length,
      total: findState.pos,
      rawTotal: rawFindMatches.length,
      skipped: skippedHitCount,
      busy: findBusy,
      prevKey: findPrevKey,
      nextKey: findNextKey,
      onInput: resetFindSession,
      onGo: findGo,
      onReplace: () => void findReplaceCurrent(),
      onSkip: findSkip,
      onReplaceAll: findReplaceAll,
      onToggleCase: () => {
        findState.caseSensitive = !findState.caseSensitive;
        resetFindSession();
      },
      onClose: closeFind,
    }}
    onscroll={(top) => (scrollTop = top)}
    rowclick={(i, e) => {
      if (e.metaKey || e.ctrlKey) {
        metaSelect(i);
        return;
      }
      if (e.shiftKey) {
        rangeSelectTo(i);
        return;
      }
      selectCue(i, true, true);
    }}
    rowcontext={onCueContextMenu}
    rowaudition={(i) => previewRange(app.cues[i].start, app.cues[i].end)}
    rowretranscribe={retranscribeRow}
    onrows={(node) => (rowsEl = node)}
    findInput={(node) => (findInput = node)}
  />
  {#if contextMenu}
    <button
      class="ctx-backdrop"
      use:portal
      aria-label="关闭菜单"
      onclick={() => (contextMenu = null)}
    ></button>
    <div
      class="ctx-menu"
      use:portal
      style="left:{contextMenu.x}px;top:{contextMenu.y}px"
      role="menu"
      aria-label="音轨菜单"
    >
      <div class="ctx-head">
        <span>{tcShort(contextMenu.t)}</span>
        <span class="ctx-hint">
          {contextMenu.index >= 0 ? `第 ${contextMenu.index + 1} 句` : '0.8 秒'}
        </span>
      </div>
      {#if contextMenu.merge.length >= 2}
        <button
          class="ctx-item"
          onclick={() => mergeHere(contextMenu!.merge)}
          role="menuitem"
        >
          <Icon name="merge" size={12} />
          <span class="ctx-label">合并这 {contextMenu.merge.length} 句字幕</span>
          <span class="ctx-hint">一起合并</span>
        </button>
        <div class="ctx-sep"></div>
      {/if}
      {#if contextMenu.index >= 0}
        {#if canSplitHere()}
          <button class="ctx-item" onclick={splitHere} role="menuitem">
            <Icon name="split" size={12} />
            <span class="ctx-label">切割字幕</span>
            <span class="ctx-hint">分成两句</span>
          </button>
        {/if}
        <button
          class="ctx-item"
          onclick={() => openVoiceDialog(contextMenu!.index)}
          role="menuitem"
        >
          <Icon name="speaker" size={12} />
          <span class="ctx-label">以此句音频新建音色…</span>
        </button>
        <button
          class="ctx-item"
          onclick={() => {
            const index = contextMenu.index;
            const c = app.cues[index];
            contextMenu = null;
            if (c) previewRange(c.start, c.end);
          }}
          role="menuitem"
        >
          <Icon name="play" size={12} />
          <span class="ctx-label">试听这句原声</span>
        </button>
        <div class="ctx-sep"></div>
      {/if}
      <button class="ctx-item" onclick={addCueHere} role="menuitem">
        <Icon name="plus" size={12} />
        <span class="ctx-label">添加字幕</span>
        <span class="ctx-hint">在光标处居中插入空字幕</span>
      </button>
    </div>
  {/if}

  {#if voiceDialog}
    {@const vc = app.cues[voiceDialog.index]}
    <button
      class="vd-backdrop"
      use:portal
      aria-label="关闭新建音色"
      onclick={() => {
        if (!voiceBusy) voiceDialog = null;
      }}
    ></button>
    <div class="vd" use:portal role="dialog" aria-modal="true" aria-label="新建克隆音色">
      <div class="vd-head">以此句音频新建音色</div>
      <div class="vd-sub">
        {#if vc}
          第 {voiceDialog.index + 1} 句 · {tcShort(vc.start)}–{tcShort(vc.end)}
          <span class="vd-dur">{(vc.end - vc.start).toFixed(1)}s</span>
        {/if}
      </div>
      <label class="vd-field">
        <span>音色名</span>
        <input
          bind:this={voiceNameEl}
          bind:value={voiceDialog.name}
          maxlength="40"
          placeholder="角色名，例如「女主角」"
          onkeydown={(e) => {
            if (e.key === 'Enter' && !voiceBusy) {
              e.preventDefault();
              void createVoiceFromCue();
            } else if (e.key === 'Escape') {
              e.preventDefault();
              voiceDialog = null;
            }
          }}
        />
      </label>
      <label class="vd-field">
        <span>参考文本（这句的日文，用于对齐声线）</span>
        <textarea bind:value={voiceDialog.refText} rows="2"></textarea>
      </label>
      <p class="vd-note">
        后端会用 ffmpeg 从当前视频精确切出这句的人声（前后各留 0.2 秒），
        3–10 秒最稳。{tts.engine && !tts.engine.installed
          ? '提取不需要模型；朗读前再到右侧点「下载克隆模型」。'
          : ''}
      </p>
      <div class="vd-actions">
        <button class="btn mini" onclick={() => (voiceDialog = null)} disabled={voiceBusy}>
          取消
        </button>
        <span class="vd-spacer"></span>
        <button class="btn mini primary" onclick={createVoiceFromCue} disabled={voiceBusy}>
          {voiceBusy ? '提取中…' : '提取并保存'}
        </button>
      </div>
    </div>
  {/if}
</div>

<style>
  .review {
    flex: 1;
    min-height: 0;
    display: flex;
    flex-direction: column;
  }

  .timeline {
    padding: 6px 26px 0;
    flex: 0 0 auto;
  }

  .stage {
    padding: 18px 26px 0;
    display: flex;
    flex-direction: column;
    flex: 0 0 auto;
  }

  /* ---------------- 音轨右键菜单 ---------------- */
  .ctx-backdrop {
    position: fixed;
    inset: 0;
    z-index: 70;
    border: 0;
    padding: 0;
    background: transparent;
    cursor: default;
  }
  .ctx-sep {
    height: 1px;
    margin: 3px var(--sp-1);
    background: var(--separator-soft);
  }
  .ctx-menu {
    position: fixed;
    z-index: 71;
    width: 244px;
    padding: var(--sp-1);
    border-radius: 4px;
    background: var(--bg-content);
    border: 1px solid var(--separator);
    box-shadow: var(--shadow-pop);
  }
  .ctx-head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--sp-2);
    padding: var(--sp-1) 7px 5px;
    margin-bottom: 3px;
    border-bottom: 1px solid var(--separator-soft);
    font-size: 12px;
    color: var(--text-3);
    font-variant-numeric: tabular-nums;
    font-family: ui-monospace, 'SF Mono', Menlo, monospace;
  }
  .ctx-item {
    appearance: none;
    border: 0;
    background: transparent;
    color: var(--text);
    font: inherit;
    width: 100%;
    display: flex;
    align-items: center;
    gap: 7px;
    padding: 6px 7px;
    border-radius: 4px;
    cursor: pointer;
    text-align: left;
  }
  .ctx-item:hover {
    background: var(--accent-soft);
    color: var(--accent);
  }
  .ctx-label {
    flex: 0 0 auto;
    font-size: 12px;
    white-space: nowrap;
  }
  .ctx-hint {
    flex: 1;
    min-width: 0;
    font-size: 12px;
    color: var(--text-3);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    text-align: right;
  }

  /* ---------------- 以此句音频新建音色 ---------------- */
  .vd-backdrop {
    position: fixed;
    inset: 0;
    z-index: 80;
    border: 0;
    padding: 0;
    margin: 0;
    background: rgba(0, 0, 0, 0.28);
    backdrop-filter: blur(1px);
    cursor: default;
  }
  .vd {
    position: fixed;
    z-index: 81;
    left: 50%;
    top: 50%;
    transform: translate(-50%, -50%);
    width: min(340px, calc(100vw - 48px));
    padding: 14px var(--sp-4) var(--sp-3);
    border-radius: 8px;
    background: var(--bg-content);
    border: 1px solid var(--separator);
    box-shadow: var(--shadow-pop);
    display: flex;
    flex-direction: column;
    gap: 10px;
  }
  .vd-head {
    font-size: 13px;
    font-weight: 600;
    color: var(--text);
  }
  .vd-sub {
    display: flex;
    align-items: center;
    gap: 6px;
    margin-top: -5px;
    font-size: 11px;
    color: var(--text-3);
    font-variant-numeric: tabular-nums;
  }
  .vd-dur {
    padding: 0 5px;
    border-radius: 3px;
    background: var(--separator-soft);
  }
  .vd-field {
    display: flex;
    flex-direction: column;
    gap: var(--sp-1);
    font-size: 11px;
    color: var(--text-3);
  }
  .vd-field input,
  .vd-field textarea {
    width: 100%;
    box-sizing: border-box;
    border: 1px solid var(--line);
    border-radius: 4px;
    background: var(--bg-inset, var(--raise));
    color: var(--text);
    font: inherit;
    font-size: 12px;
    padding: 5px 7px;
    resize: vertical;
  }
  .vd-field input:focus,
  .vd-field textarea:focus {
    outline: none;
    border-color: var(--accent-line);
    box-shadow: 0 0 0 2px var(--accent-soft);
  }
  .vd-note {
    margin: 0;
    font-size: 11px;
    line-height: 16px;
    color: var(--text-3);
  }
  .vd-actions {
    display: flex;
    align-items: center;
    gap: var(--sp-2);
    padding-top: 2px;
  }
  .vd-spacer {
    flex: 1;
  }

  /* ============================================================
     紧凑模式（≤900px；200% 页面缩放后是 680×419 / 540×340）。
     三块保持原顺序、整屏纵向滚动：播放器按可用宽度等比缩，
     时间线跟其后，表格保底 200px（虚拟列表自己滚），
     不再出现「内容区 96px、视频 44×25」的塌陷。
     ============================================================ */
  @media (max-width: 900px) {
    .review {
      overflow-x: hidden;
      overflow-y: auto;
    }
    .stage {
      padding: var(--sp-3) var(--sp-4) 0;
    }
    /* 200% 下保持 592×333 会把播放条推出首屏：按「视频 + 播放行 + 工具行」
       正好占满一屏可用高度来定宽，波形与表格往下滚一屏即可。 */
    .player {
      width: min(640px, 100%, calc((100vh - 170px) * 16 / 9));
    }
    .timeline {
      padding: 6px var(--sp-4) 0;
    }
    .table-area {
      flex: 0 0 auto;
      height: clamp(200px, 52vh, 300px);
      margin: 6px var(--sp-4) var(--sp-4);
    }
    .transport,
    .tl-tools {
      gap: 7px;
    }
    /* 查找栏在 680/540 宽下要留在一行：隐藏「Aa」与分隔线，输入框可收缩。
       折行会把表格再吃掉一行高度，关闭按钮也会单独掉到第二行。 */
    .find-bar {
      padding: 5px 6px;
      gap: 3px;
      flex-wrap: wrap;
    }
    .find-input {
      width: auto;
      flex: 1 1 110px;
      min-width: 80px;
    }
    .find-input.replace {
      width: auto;
      flex: 1 1 96px;
      min-width: 72px;
    }
    .find-count {
      min-width: 42px;
    }
    /* 窄窗口优先保住「替换 / 跳过 / 全部替换」一行；跳过数量靠删除线判断 */
    .find-skipped {
      display: none;
    }
    .find-case,
    .find-sep {
      display: none;
    }
  }

  @media (max-width: 700px) {
    /* 540 / 680 宽：只留「# / 开始 / 字幕文本 / 行内动作」四列 */
    .thead,
    .row {
      grid-template-columns: 30px 78px minmax(0, 1fr) 36px;
      column-gap: var(--sp-1);
      padding: 0 var(--sp-2);
    }
    .thead > :nth-child(3),
    .thead > :nth-child(4),
    .row > :nth-child(3),
    .row > :nth-child(4) {
      display: none;
    }
    .find-input,
    .find-input.replace {
      width: 120px;
      flex-basis: 120px;
    }
  }
</style>
