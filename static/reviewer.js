(payloadText) => {
  try {
    const shell = document.querySelector('#reviewer-shell');
    if (!shell) return;
    let data;
    try { data = JSON.parse(payloadText || '{}'); } catch (_) { return; }

    if (data.is_patch_only) {
      // 纯字幕补丁：只更新字幕轨，绝不重建画面（关闭监看后也不该被顶掉）
      if (window.__reviewerInstance) {
        window.__reviewerInstance.updateCues(data.cues || []);
      }
      return;
    }

    if (!data.src) {
      // 关闭监看 / 片源不可用：销毁旧播放器实例，避免残留快捷键与悬空引用
      window.__reviewerInstance = null;
      if (window.__reviewerKeyHandler) {
        window.removeEventListener('keydown', window.__reviewerKeyHandler);
        window.__reviewerKeyHandler = null;
      }
      window.onbeforeunload = null;
      shell.innerHTML = data.error || '<div class="reviewer-empty">上传媒体后，这里会自动载入视频监看画面与精确时间轴波形轨。</div>';
      return;
    }
    const existingVideo = shell.querySelector('.reviewer-video');
    if (existingVideo && existingVideo.getAttribute('src') === data.src && window.__reviewerInstance) {
      window.__reviewerInstance.updateCues(data.cues || []);
      return;
    }
    const esc = (text) => String(text || '').replace(/[&<>'"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));
    
    let duration = Number(data.duration || 0);
    const peaks = data.peaks || [];
    const cues = data.cues || [];

    shell.innerHTML = `
      <div class="reviewer-stage" id="rw-stage">
        <video class="reviewer-video" preload="metadata" src="${data.src}"></video>
        <div class="reviewer-caption" id="reviewer-caption"></div>
        <div class="reviewer-codec-hint" id="rw-codec-hint" style="display:none;">
          ⚠️ 浏览器未能解码 <b id="rw-codec-name"></b> 视频；画面若黑屏，请点左侧「⚡ 压制 480p 代理」。
        </div>
        
        <div class="rw-center-play-indicator" id="rw-center-play" style="display:none;">
          <div class="rw-center-play-icon">▶</div>
        </div>

        <div class="reviewer-custom-controls" id="rw-custom-controls">
          <div class="rw-scrub-track-wrap">
            <input type="range" class="rw-scrubber-slider" id="rw-scrubber-slider" min="0" max="${Number(data.duration || 0) || 100}" step="0.04" value="0">
            <div class="rw-scrub-hover-tip" id="rw-scrub-tip" style="display:none;">00:00:00.000</div>
          </div>

          <div class="rw-controls-row">
            <div class="rw-ctrl-left">
              <button type="button" class="rw-ctrl-btn rw-btn-main-play" id="rw-btn-play-toggle" title="播放/暂停 (空格)">▶</button>
              <button type="button" class="rw-ctrl-btn" id="rw-btn-step-prev" title="后退 1 帧 (←)">⏮ 1F</button>
              <button type="button" class="rw-ctrl-btn" id="rw-btn-step-next" title="前进 1 帧 (→)">⏭ 1F</button>
              
              <div class="rw-ctrl-time-display">
                <span class="rw-time-cur" id="rw-ctrl-current">00:00:00.000</span>
                <span class="rw-time-sep">/</span>
                <span class="rw-time-dur" id="rw-ctrl-total">00:00:00.000</span>
              </div>
            </div>

            <div class="rw-ctrl-right">
              <button type="button" class="rw-ctrl-btn" id="rw-btn-mute" title="静音切换">🔊</button>
              <input type="range" class="rw-vol-slider" id="rw-vol-slider" min="0" max="1" step="0.05" value="1" title="调节音量">
              <button type="button" class="rw-ctrl-btn" id="rw-btn-fullscreen" title="全屏画面">⛶</button>
            </div>
          </div>
        </div>
      </div>

      <div class="reviewer-wave-header">
        <div class="reviewer-clock">
          <span class="reviewer-playhead-time" id="rw-current-time">00:00:00.000</span>
          <span class="reviewer-divider">/</span>
          <span class="reviewer-total-time" id="rw-total-time">00:00:00.000</span>
        </div>

        <div class="reviewer-selection-bar" id="rw-selection-bar" style="display:none;">
          <span class="rw-sel-icon">✂️</span>
          <span class="rw-sel-info" id="rw-selection-info">已选: 00:00:00.000 → 00:00:00.000 (0.00s)</span>
          <button type="button" class="rw-btn rw-btn-play-sel" id="rw-play-sel-btn" title="试听当前框选声音">▶ 试听</button>
          <button type="button" class="rw-btn rw-btn-transcribe-sel" id="rw-transcribe-sel-btn" title="立即识别当前选区并直接插入时间轴">⚡ 识别并直接入轨</button>
          <button type="button" class="rw-btn rw-btn-sync" id="rw-sync-btn" title="仅同步起止时间到顶部时间切片输入框">⏱ 同步时间到顶部</button>
          <button type="button" class="rw-btn rw-btn-clear" id="rw-clear-sel-btn">✕</button>
        </div>

        <div class="reviewer-zoom-controls">
          <button type="button" class="rw-tool-btn" id="rw-zoom-out" title="缩小轨道">🔍 -</button>
          <input type="range" class="rw-zoom-slider" id="rw-zoom-slider" min="1" max="50" step="0.5" value="1" title="水平缩放轨道">
          <button type="button" class="rw-tool-btn" id="rw-zoom-in" title="放大轨道">🔍 +</button>
          <button type="button" class="rw-tool-btn" id="rw-zoom-fit" title="显示全片视图">100% 全景</button>
          <button type="button" class="rw-tool-btn" id="rw-center-playhead" title="聚焦到当前播放头并放大50倍">🎯 聚焦</button>
          <button type="button" class="rw-tool-btn is-on" id="rw-follow-toggle" title="播放时自动跟随播放头（字幕始终同步）">🧲 跟随</button>
          <span class="reviewer-zoom-level" id="rw-zoom-level">1.0×</span>
        </div>
      </div>

      <div class="reviewer-canvas-wrap" id="rw-canvas-wrap">
        <canvas class="reviewer-ruler-canvas" id="rw-ruler-canvas" height="24"></canvas>
        <canvas class="reviewer-wave-canvas" id="rw-wave-canvas" height="110" aria-label="音频波形时间轴"></canvas>
        <div class="reviewer-playhead-line" id="rw-playhead-line" style="display:none;">
          <div class="rw-playhead-flag">▼</div>
        </div>
      </div>

      <div class="reviewer-wave-hint">
        <div class="rw-hint-row">⌨️ <strong>快捷键：</strong><span>【<strong>空格</strong>】播放/暂停</span> ｜ <span>【<strong>← / →</strong>】1 帧微调（约 0.042s）</span> ｜ <span>【<strong>Shift + ← / →</strong>】5 帧快速定位</span> ｜ <span>【<strong>Cmd/Ctrl + Z</strong>】撤销</span> ｜ <span>【<strong>Cmd/Ctrl + Shift + Z</strong>】重做</span></div>
        <div class="rw-hint-row">💡 <strong>手势：</strong><span>Mac 触控板在波形上<strong>双指横滑平移</strong>，<strong>双指垂直/捏合无级缩放</strong> ｜ 拖拽框选后点击<strong>「⚡ 识别此段送入精修」</strong>即可零位移秒出字幕！</span></div>
      </div>
    `;

    const stage = shell.querySelector('#rw-stage');
    const video = shell.querySelector('.reviewer-video');
    const caption = shell.querySelector('#reviewer-caption');
    const codecHint = shell.querySelector('#rw-codec-hint');
    const codecName = shell.querySelector('#rw-codec-name');
    const waveCanvas = shell.querySelector('#rw-wave-canvas');
    const rulerCanvas = shell.querySelector('#rw-ruler-canvas');
    const canvasWrap = shell.querySelector('#rw-canvas-wrap');
    const playheadLine = shell.querySelector('#rw-playhead-line');
    const currentTimeText = shell.querySelector('#rw-current-time');
    const totalTimeText = shell.querySelector('#rw-total-time');
    const selectionBar = shell.querySelector('#rw-selection-bar');
    const selectionInfo = shell.querySelector('#rw-selection-info');
    const syncBtn = shell.querySelector('#rw-sync-btn');
    const transcribeSelBtn = shell.querySelector('#rw-transcribe-sel-btn');
    const playSelBtn = shell.querySelector('#rw-play-sel-btn');
    const clearSelBtn = shell.querySelector('#rw-clear-sel-btn');
    const zoomInBtn = shell.querySelector('#rw-zoom-in');
    const zoomOutBtn = shell.querySelector('#rw-zoom-out');
    const zoomFitBtn = shell.querySelector('#rw-zoom-fit');
    const centerPlayheadBtn = shell.querySelector('#rw-center-playhead');
    const followToggleBtn = shell.querySelector('#rw-follow-toggle');
    const zoomSlider = shell.querySelector('#rw-zoom-slider');
    const zoomLevelText = shell.querySelector('#rw-zoom-level');

    const scrubberSlider = shell.querySelector('#rw-scrubber-slider');
    const scrubTip = shell.querySelector('#rw-scrub-tip');
    const playToggleBtn = shell.querySelector('#rw-btn-play-toggle');
    const stepPrevBtn = shell.querySelector('#rw-btn-step-prev');
    const stepNextBtn = shell.querySelector('#rw-btn-step-next');
    const ctrlCurrentTime = shell.querySelector('#rw-ctrl-current');
    const ctrlTotalTime = shell.querySelector('#rw-ctrl-total');
    const muteBtn = shell.querySelector('#rw-btn-mute');
    const volSlider = shell.querySelector('#rw-vol-slider');
    const fullscreenBtn = shell.querySelector('#rw-btn-fullscreen');

    const waveCtx = waveCanvas.getContext('2d');
    const rulerCtx = rulerCanvas.getContext('2d');

    let viewStart = 0;
    let viewSpan = duration || 1;
    let selected = null;
    let isDragging = false;
    let dragAnchor = null;
    let isPlayingSelection = false;
    let lastSyncedCueIndex = -1;
    let isScrubbingSlider = false;
    let followPlayhead = true;
    let followUserLocked = false;
    let hideControlsTimer = null;

    window.__isTranscribing = false;
    let syncInputDebounceTimer = null;

    const format = sec => {
      sec = Math.max(0, Number(sec) || 0);
      const h = Math.floor(sec / 3600);
      const m = Math.floor((sec % 3600) / 60);
      const s = sec % 60;
      return `${String(h).padStart(2,'0')}:${String(m).padStart(2,'0')}:${s.toFixed(3).padStart(6,'0')}`;
    };

    if (duration > 0) {
      totalTimeText.textContent = format(duration);
      if (ctrlTotalTime) ctrlTotalTime.textContent = format(duration);
      if (scrubberSlider) scrubberSlider.max = String(duration);
    }

    // ── 字幕叠加层索引 ───────────────────────────────────────────────
    // 关键点 1：同一时间区间内的多条字幕（中日双语 SRT 通常把日语行和
    // 中文行拆成两条、起止时间完全相同）必须聚合成一个「字幕块」多行显示，
    // 不能用 find() 只取第一条，否则永远只显示一行。
    // 关键点 2：字幕显示与下方波形的缩放视窗完全解耦，任何时间点都要更新。
    let captionGroups = [];
    let lastCaptionText = null;

    const rebuildCaptionIndex = () => {
      const buckets = new Map();
      const groups = [];
      for (const cue of cues) {
        const start = Number(cue.start) || 0;
        const end = Number(cue.end) || 0;
        const key = `${Math.round(start * 1000)}|${Math.round(end * 1000)}`;
        let group = buckets.get(key);
        if (!group) {
          group = { start, end, lines: [], seen: new Set() };
          buckets.set(key, group);
          groups.push(group);
        }
        const text = String(cue.text == null ? '' : cue.text).trim();
        if (!text || group.seen.has(text)) continue;
        group.seen.add(text);
        group.lines.push(text);
      }
      groups.sort((a, b) => (a.start - b.start) || (a.end - b.end));
      captionGroups = groups;
      lastCaptionText = null;
    };

    const findCaptionGroup = (time) => {
      const groups = captionGroups;
      if (!groups.length) return null;
      let lo = 0;
      let hi = groups.length - 1;
      let idx = -1;
      while (lo <= hi) {
        const mid = (lo + hi) >> 1;
        if (groups[mid].start <= time + 0.0005) { idx = mid; lo = mid + 1; }
        else { hi = mid - 1; }
      }
      if (idx === -1) return null;
      for (let i = idx; i >= 0 && i > idx - 64; i--) {
        if (groups[i].end + 0.0005 >= time) return groups[i];
        if (groups[i].end < time - 60) break;
      }
      return null;
    };

    const updateCaption = (time) => {
      if (!caption) return;
      const group = findCaptionGroup(time);
      const text = group ? group.lines.join('\n') : '';
      if (text === lastCaptionText) return;
      lastCaptionText = text;
      if (!text) {
        caption.textContent = '';
        caption.style.display = 'none';
      } else {
        caption.textContent = text;
        caption.style.display = 'block';
      }
    };

    rebuildCaptionIndex();

    const clampView = () => {
      const minSpan = Math.min(duration || 1, 0.4);
      const maxSpan = duration || 1;
      viewSpan = Math.max(minSpan, Math.min(maxSpan, viewSpan));
      viewStart = Math.max(0, Math.min(Math.max(0, duration - viewSpan), viewStart));
      const ratio = duration ? (duration / viewSpan) : 1;
      zoomSlider.value = Math.min(50, Math.max(1, ratio));
      zoomLevelText.textContent = `${ratio.toFixed(1)}×`;
    };

    const drawRuler = () => {
      const rect = rulerCanvas.getBoundingClientRect();
      const ratio = window.devicePixelRatio || 1;
      rulerCanvas.width = Math.max(1, Math.floor(rect.width * ratio));
      rulerCanvas.height = Math.max(1, Math.floor(rect.height * ratio));
      rulerCtx.setTransform(ratio, 0, 0, ratio, 0, 0);

      const w = rect.width;
      const h = rect.height;

      rulerCtx.fillStyle = '#0f172a';
      rulerCtx.fillRect(0, 0, w, h);

      if (!duration) return;

      const targetDivs = w / 90;
      const rawStep = viewSpan / targetDivs;
      const niceSteps = [0.05, 0.1, 0.2, 0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300, 600, 1800, 3600];
      let step = niceSteps[niceSteps.length - 1];
      for (const ns of niceSteps) {
        if (ns >= rawStep) { step = ns; break; }
      }

      rulerCtx.strokeStyle = 'rgba(148, 163, 184, 0.35)';
      rulerCtx.fillStyle = '#94a3b8';
      rulerCtx.font = '10px ui-monospace, SFMono-Regular, Menlo, monospace';
      rulerCtx.textBaseline = 'bottom';

      const firstMark = Math.floor(viewStart / step) * step;
      for (let t = firstMark; t <= viewStart + viewSpan; t += step) {
        if (t < viewStart) continue;
        const x = ((t - viewStart) / viewSpan) * w;
        rulerCtx.beginPath();
        rulerCtx.moveTo(x, h);
        rulerCtx.lineTo(x, h - 8);
        rulerCtx.stroke();

        const subStep = step / 5;
        for (let s = 1; s < 5; s++) {
          const subT = t + s * subStep;
          if (subT > viewStart && subT < viewStart + viewSpan) {
            const subX = ((subT - viewStart) / viewSpan) * w;
            rulerCtx.beginPath();
            rulerCtx.moveTo(subX, h);
            rulerCtx.lineTo(subX, h - 4);
            rulerCtx.stroke();
          }
        }

        const label = step < 1 ? t.toFixed(2) + 's' : (t >= 60 ? `${Math.floor(t/60)}m${(t%60).toFixed(0)}s` : t.toFixed(0) + 's');
        rulerCtx.fillText(label, x + 3, h - 3);
      }

      rulerCtx.strokeStyle = 'rgba(99, 102, 241, 0.4)';
      rulerCtx.beginPath();
      rulerCtx.moveTo(0, h - 0.5);
      rulerCtx.lineTo(w, h - 0.5);
      rulerCtx.stroke();
    };

    const drawWave = () => {
      const rect = waveCanvas.getBoundingClientRect();
      const ratio = window.devicePixelRatio || 1;
      waveCanvas.width = Math.max(1, Math.floor(rect.width * ratio));
      waveCanvas.height = Math.max(1, Math.floor(rect.height * ratio));
      waveCtx.setTransform(ratio, 0, 0, ratio, 0, 0);

      const w = rect.width;
      const h = rect.height;
      const mid = h / 2;

      waveCtx.fillStyle = '#090d16';
      waveCtx.fillRect(0, 0, w, h);

      waveCtx.strokeStyle = 'rgba(255, 255, 255, 0.06)';
      waveCtx.lineWidth = 1;
      waveCtx.beginPath();
      waveCtx.moveTo(0, mid);
      waveCtx.lineTo(w, mid);
      waveCtx.stroke();

      if (!duration) return;

      if (cues && cues.length > 0) {
        waveCtx.fillStyle = 'rgba(56, 189, 248, 0.12)';
        for (const cue of cues) {
          if (cue.end < viewStart || cue.start > viewStart + viewSpan) continue;
          const x1 = ((cue.start - viewStart) / viewSpan) * w;
          const x2 = ((cue.end - viewStart) / viewSpan) * w;
          waveCtx.fillRect(Math.max(0, x1), 0, Math.min(w, x2) - Math.max(0, x1), h);
          
          waveCtx.strokeStyle = 'rgba(56, 189, 248, 0.4)';
          waveCtx.beginPath();
          waveCtx.moveTo(Math.max(0, x1), 2);
          waveCtx.lineTo(Math.min(w, x2), 2);
          waveCtx.stroke();
        }
      }

      if (peaks.length > 0) {
        const firstIdx = Math.max(0, Math.floor((viewStart / duration) * peaks.length));
        const lastIdx = Math.min(peaks.length, Math.ceil(((viewStart + viewSpan) / duration) * peaks.length));

        const pts = [];
        for (let i = firstIdx; i < lastIdx; i++) {
          const t = (i / Math.max(1, peaks.length - 1)) * duration;
          const x = ((t - viewStart) / viewSpan) * w;
          const amp = Math.max(1.5, peaks[i] * (h * 0.44));
          pts.push({ x, amp });
        }

        if (pts.length > 0) {
          waveCtx.fillStyle = 'rgba(129, 140, 248, 0.45)';
          waveCtx.beginPath();
          waveCtx.moveTo(pts[0].x, mid - pts[0].amp);
          for (let j = 1; j < pts.length; j++) {
            waveCtx.lineTo(pts[j].x, mid - pts[j].amp);
          }
          for (let j = pts.length - 1; j >= 0; j--) {
            waveCtx.lineTo(pts[j].x, mid + pts[j].amp);
          }
          waveCtx.closePath();
          waveCtx.fill();

          waveCtx.strokeStyle = '#a5b4fc';
          waveCtx.lineWidth = 1.2;
          waveCtx.beginPath();
          for (let j = 0; j < pts.length; j++) {
            if (j === 0) waveCtx.moveTo(pts[j].x, mid - pts[j].amp);
            else waveCtx.lineTo(pts[j].x, mid - pts[j].amp);
          }
          waveCtx.stroke();

          waveCtx.beginPath();
          for (let j = 0; j < pts.length; j++) {
            if (j === 0) waveCtx.moveTo(pts[j].x, mid + pts[j].amp);
            else waveCtx.lineTo(pts[j].x, mid + pts[j].amp);
          }
          waveCtx.stroke();
        }
      }

      if (selected && duration) {
        const s0 = Math.min(selected[0], selected[1]);
        const s1 = Math.max(selected[0], selected[1]);
        const x1 = ((s0 - viewStart) / viewSpan) * w;
        const x2 = ((s1 - viewStart) / viewSpan) * w;

        if (x2 >= 0 && x1 <= w) {
          waveCtx.fillStyle = 'rgba(99, 102, 241, 0.38)';
          waveCtx.fillRect(Math.max(0, x1), 0, Math.min(w, x2) - Math.max(0, x1), h);

          waveCtx.strokeStyle = '#a5b4fc';
          waveCtx.lineWidth = 2;
          if (x1 >= 0 && x1 <= w) {
            waveCtx.beginPath();
            waveCtx.moveTo(x1, 0);
            waveCtx.lineTo(x1, h);
            waveCtx.stroke();
          }
          if (x2 >= 0 && x2 <= w) {
            waveCtx.beginPath();
            waveCtx.moveTo(x2, 0);
            waveCtx.lineTo(x2, h);
            waveCtx.stroke();
          }
        }
      }
    };

    const setGradioValue = (elemId, value, triggerEvents = true) => {
      const container = document.getElementById(elemId);
      if (!container) return false;
      const input = container.querySelector('input') || container.querySelector('textarea');
      if (!input) return false;
      const nativeSetter = Object.getOwnPropertyDescriptor(
        input instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype,
        'value'
      ).set;
      nativeSetter.call(input, value);

      if (triggerEvents && !window.__isTranscribing) {
        input.dispatchEvent(new Event('input', { bubbles: true }));
        input.dispatchEvent(new Event('change', { bubbles: true }));
      }
      return true;
    };

    const safeSeekVideo = (targetSec) => {
      targetSec = Math.max(0, Math.min(duration || Infinity, Number(targetSec) || 0));
      if (typeof video.fastSeek === 'function') {
        try { video.fastSeek(targetSec); } catch (_) { video.currentTime = targetSec; }
      } else {
        video.currentTime = targetSec;
      }
    };

    // 播放头跑出可视范围时，把视窗整页平移到播放头附近（默认落在左侧 15% 处），
    // 保证放大后长时间播放也不会「看不见播放头」。返回是否真的移动了视窗。
    const ensurePlayheadVisible = (cur) => {
      if (!followPlayhead || !duration) return false;
      if (isDragging || isScrubbingSlider) return false;
      if (cur >= viewStart && cur <= viewStart + viewSpan) return false;
      const maxStart = Math.max(0, duration - viewSpan);
      const next = Math.max(0, Math.min(maxStart, cur - viewSpan * 0.15));
      if (Math.abs(next - viewStart) < 1e-6) return false;
      viewStart = next;
      return true;
    };

    const updatePlayhead = (syncInputBoxes = false) => {
      const cur = video.currentTime;
      currentTimeText.textContent = format(cur);
      if (ctrlCurrentTime && !isScrubbingSlider) {
        ctrlCurrentTime.textContent = format(cur);
      }
      if (scrubberSlider && !isScrubbingSlider && duration > 0) {
        scrubberSlider.value = String(cur);
      }

      if (isPlayingSelection && selected) {
        const endLimit = Math.max(selected[0], selected[1]);
        if (cur >= endLimit) {
          video.pause();
          isPlayingSelection = false;
          playSelBtn.textContent = '▶ 试听';
        }
      }

      const canSyncToGradio = syncInputBoxes && !window.__isTranscribing && !isEditingText() && cues.length > 0;
      if (canSyncToGradio) {
        let matchedIdx = -1;
        for (let i = cues.length - 1; i >= 0; i--) {
          if (cur >= cues[i].start) {
            matchedIdx = i;
            break;
          }
        }
        if (matchedIdx === -1 && cur < cues[0].start) {
          matchedIdx = 0;
        }
        if (matchedIdx !== -1 && matchedIdx !== lastSyncedCueIndex) {
          lastSyncedCueIndex = matchedIdx;
          const target = cues[matchedIdx];
          const srtFmt = (t) => {
            const s = Math.max(0, Number(t) || 0);
            const hh = String(Math.floor(s / 3600)).padStart(2, '0');
            const mm = String(Math.floor((s % 3600) / 60)).padStart(2, '0');
            const ss = (s % 60).toFixed(3).padStart(6, '0').replace('.', ',');
            return `${hh}:${mm}:${ss}`;
          };
          clearTimeout(syncInputDebounceTimer);
          syncInputDebounceTimer = setTimeout(() => {
            if (!window.__isTranscribing) {
              setGradioValue('cue-edit-idx', matchedIdx + 1, true);
              setGradioValue('cue-edit-start', srtFmt(target.start), true);
              setGradioValue('cue-edit-end', srtFmt(target.end), true);
              setGradioValue('cue-edit-text', target.text, true);
            }
          }, 250);
        }
      }

      // ① 字幕永远优先更新：与缩放视窗、光标位置、是否拖动进度条无关，
      //    避免播放头一旦跑出可视范围就「卡住不动」。
      updateCaption(cur);

      // ② 播放时自动跟随播放头（整页平移，不做连续滚动，避免干扰框选）
      if (duration && !video.paused && !video.ended && ensurePlayheadVisible(cur)) {
        drawRuler();
        drawWave();
      }

      // ③ 播放头时间游标
      if (!duration || cur < viewStart || cur > viewStart + viewSpan) {
        playheadLine.style.display = 'none';
        return;
      }

      const rect = waveCanvas.getBoundingClientRect();
      const x = ((cur - viewStart) / viewSpan) * rect.width;

      playheadLine.style.display = 'block';
      playheadLine.style.left = `${x}px`;
    };

    const renderAll = () => {
      drawRuler();
      drawWave();
      updatePlayhead(false);
    };

    let animId = null;
    const loop = () => {
      if (!video.paused && !video.ended) {
        updatePlayhead(true);
        animId = requestAnimationFrame(loop);
      }
    };

    const togglePlay = () => {
      if (video.paused || video.ended) {
        video.play();
      } else {
        video.pause();
      }
    };

    video.addEventListener('click', (e) => {
      e.stopPropagation();
      togglePlay();
    });

    if (playToggleBtn) {
      playToggleBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        togglePlay();
      });
    }

    const onPlayStateChanged = () => {
      const isPaused = video.paused || video.ended;
      if (playToggleBtn) {
        playToggleBtn.textContent = isPaused ? '▶' : '⏸';
      }
      if (stage) {
        if (isPaused) {
          stage.classList.remove('is-playing', 'is-inactive');
        } else {
          stage.classList.add('is-playing');
        }
      }
    };

    video.addEventListener('play', () => {
      onPlayStateChanged();
      if (!followUserLocked) setFollow(true);
      cancelAnimationFrame(animId);
      animId = requestAnimationFrame(loop);
    });
    video.addEventListener('pause', () => {
      onPlayStateChanged();
      cancelAnimationFrame(animId);
      updatePlayhead(true);
    });
    // 不能用 canPlayType 判断：Chromium 对 HEVC 常返回空字符串，但实际能通过
    // 系统解码器播放（实测会误报）。以「真的没有画面/报错」为准。
    const maybeShowCodecHint = () => {
      if (!codecHint) return;
      const codec = String(data.codec || '').toLowerCase();
      const failed = Boolean(video.error) || (video.readyState >= 1 && video.videoWidth === 0);
      if (failed && codec) {
        if (codecName) codecName.textContent = codec.toUpperCase();
        codecHint.style.display = 'block';
      } else {
        codecHint.style.display = 'none';
      }
    };
    video.addEventListener('seeked', () => updatePlayhead(true));
    video.addEventListener('timeupdate', () => updatePlayhead(!video.paused));
    video.addEventListener('error', maybeShowCodecHint);
    video.addEventListener('playing', () => {
      if (codecHint) codecHint.style.display = 'none';
    });
    video.addEventListener('loadedmetadata', () => {
      setTimeout(maybeShowCodecHint, 1200);
      if (video.duration && !duration) {
        duration = video.duration;
        viewSpan = duration;
        totalTimeText.textContent = format(duration);
        if (ctrlTotalTime) ctrlTotalTime.textContent = format(duration);
        if (scrubberSlider) scrubberSlider.max = String(duration);
        renderAll();
      }
    });

    const resetHideControlsTimer = () => {
      if (!stage) return;
      stage.classList.remove('is-inactive');
      clearTimeout(hideControlsTimer);
      if (!video.paused && !video.ended) {
        hideControlsTimer = setTimeout(() => {
          if (!isScrubbingSlider) {
            stage.classList.add('is-inactive');
          }
        }, 2500);
      }
    };
    if (stage) {
      stage.addEventListener('mousemove', resetHideControlsTimer);
      stage.addEventListener('mouseleave', () => {
        if (!video.paused && !video.ended && !isScrubbingSlider) {
          stage.classList.add('is-inactive');
        }
      });
    }

    if (stepPrevBtn) {
      stepPrevBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        safeSeekVideo(video.currentTime - (1 / 24.0));
        updatePlayhead(true);
      });
    }
    if (stepNextBtn) {
      stepNextBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        safeSeekVideo(video.currentTime + (1 / 24.0));
        updatePlayhead(true);
      });
    }

    if (volSlider && muteBtn) {
      volSlider.addEventListener('input', (e) => {
        e.stopPropagation();
        video.volume = Number(e.target.value);
        video.muted = (video.volume === 0);
        muteBtn.textContent = video.muted ? '🔇' : (video.volume < 0.5 ? '🔉' : '🔊');
      });

      muteBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        video.muted = !video.muted;
        muteBtn.textContent = video.muted ? '🔇' : (video.volume < 0.5 ? '🔉' : '🔊');
        volSlider.value = video.muted ? '0' : String(video.volume || 1);
      });
    }

    if (fullscreenBtn) {
      fullscreenBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        if (!document.fullscreenElement) {
          if (stage.requestFullscreen) stage.requestFullscreen();
          else if (video.requestFullscreen) video.requestFullscreen();
        } else {
          if (document.exitFullscreen) document.exitFullscreen();
        }
      });
    }

    if (scrubberSlider) {
      scrubberSlider.addEventListener('input', (e) => {
        isScrubbingSlider = true;
        const targetSec = Number(e.target.value);
        currentTimeText.textContent = format(targetSec);
        if (ctrlCurrentTime) ctrlCurrentTime.textContent = format(targetSec);
        updateCaption(targetSec);   // 拖动进度条时字幕实时预览
        if (scrubTip) {
          scrubTip.style.display = 'block';
          scrubTip.textContent = format(targetSec);
          const pct = (targetSec / (duration || 1)) * 100;
          scrubTip.style.left = `${pct}%`;
        }
      });

      const commitScrub = (e) => {
        if (!isScrubbingSlider) return;
        isScrubbingSlider = false;
        if (scrubTip) scrubTip.style.display = 'none';
        const targetSec = Number(scrubberSlider.value);
        safeSeekVideo(targetSec);
        updatePlayhead(true);
        resetHideControlsTimer();
      };
      scrubberSlider.addEventListener('change', commitScrub);
      scrubberSlider.addEventListener('pointerup', commitScrub);
      scrubberSlider.addEventListener('touchend', commitScrub);

      // 兜底：无论指针在哪里松开，都复位拖动状态，
      // 避免 isScrubbingSlider 卡在 true 导致进度条/时间读数不再跟随播放。
      window.addEventListener('pointerup', () => {
        if (!isScrubbingSlider) return;
        isScrubbingSlider = false;
        if (scrubTip) scrubTip.style.display = 'none';
        safeSeekVideo(Number(scrubberSlider.value));
        updatePlayhead(true);
      });
    }

    const xToTime = (clientX) => {
      const rect = waveCanvas.getBoundingClientRect();
      const ratio = Math.max(0, Math.min(1, (clientX - rect.left) / Math.max(1, rect.width)));
      return Math.max(0, Math.min(duration, viewStart + ratio * viewSpan));
    };

    let downScreenX = 0;
    let downScreenY = 0;

    const onPointerDown = (e) => {
      if (!duration) return;
      noteManualViewChange();
      downScreenX = e.clientX;
      downScreenY = e.clientY;
      dragAnchor = xToTime(e.clientX);
      selected = [dragAnchor, dragAnchor];
      isDragging = true;
      waveCanvas.setPointerCapture(e.pointerId);
      renderAll();
    };

    const onPointerMove = (e) => {
      if (!isDragging || dragAnchor === null) return;
      const curTime = xToTime(e.clientX);
      selected = [Math.min(dragAnchor, curTime), Math.max(dragAnchor, curTime)];

      const span = selected[1] - selected[0];
      const moveDistance = Math.hypot(e.clientX - downScreenX, e.clientY - downScreenY);
      if (moveDistance > 5 && span > 0.05) {
        selectionBar.style.display = 'flex';
        selectionInfo.textContent = `已选: ${format(selected[0])} → ${format(selected[1])} (${span.toFixed(2)}s)`;
      }
      renderAll();
    };

    const onPointerUp = (e) => {
      if (!isDragging) return;
      isDragging = false;
      dragAnchor = null;
      try { waveCanvas.releasePointerCapture(e.pointerId); } catch (_) {}

      const moveDistance = Math.hypot(e.clientX - downScreenX, e.clientY - downScreenY);
      const span = selected ? (selected[1] - selected[0]) : 0;

      if (moveDistance > 5 && span > 0.05) {
        selectionBar.style.display = 'flex';
        selectionInfo.textContent = `已选: ${format(selected[0])} → ${format(selected[1])} (${span.toFixed(2)}s)`;
        safeSeekVideo(selected[0]);
        updatePlayhead(true);
      } else {
        selected = null;
        selectionBar.style.display = 'none';
        const targetTime = xToTime(e.clientX);
        safeSeekVideo(targetTime);
        updatePlayhead(true);
      }
      renderAll();
    };

    waveCanvas.addEventListener('pointerdown', onPointerDown);
    waveCanvas.addEventListener('pointermove', onPointerMove);
    waveCanvas.addEventListener('pointerup', onPointerUp);

    waveCanvas.addEventListener('dblclick', (e) => {
      if (!duration) return;
      const targetTime = xToTime(e.clientX);
      safeSeekVideo(targetTime);
      video.play();
    });

    rulerCanvas.addEventListener('click', (e) => {
      if (!duration) return;
      const targetTime = xToTime(e.clientX);
      safeSeekVideo(targetTime);
      updatePlayhead(true);
    });

    const onWheelZoomPan = (e) => {
      if (!duration) return;
      e.preventDefault();
      noteManualViewChange();

      const isMacPinch = e.ctrlKey || e.metaKey;
      const isHorizontal = Math.abs(e.deltaX) > Math.abs(e.deltaY) && !isMacPinch;

      if (isHorizontal) {
        const panDelta = (e.deltaX / Math.max(1, waveCanvas.clientWidth)) * viewSpan;
        viewStart += panDelta;
        clampView();
        renderAll();
        return;
      }

      const mouseTime = xToTime(e.clientX);
      const zoomFactor = isMacPinch ? Math.exp(e.deltaY * 0.015) : Math.exp(e.deltaY * 0.003);
      const nextSpan = Math.max(Math.min(duration, 0.4), Math.min(duration, viewSpan * zoomFactor));

      const timeRatio = (mouseTime - viewStart) / Math.max(0.001, viewSpan);
      viewStart = mouseTime - timeRatio * nextSpan;
      viewSpan = nextSpan;

      clampView();
      renderAll();
    };

    waveCanvas.addEventListener('wheel', onWheelZoomPan, { passive: false });
    rulerCanvas.addEventListener('wheel', onWheelZoomPan, { passive: false });

    zoomInBtn.addEventListener('click', () => {
      noteManualViewChange();
      const centerTime = viewStart + viewSpan / 2;
      viewSpan = Math.max(0.4, viewSpan * 0.65);
      viewStart = centerTime - viewSpan / 2;
      clampView();
      renderAll();
    });

    zoomOutBtn.addEventListener('click', () => {
      noteManualViewChange();
      const centerTime = viewStart + viewSpan / 2;
      viewSpan = Math.min(duration, viewSpan * 1.5);
      viewStart = centerTime - viewSpan / 2;
      clampView();
      renderAll();
    });

    zoomFitBtn.addEventListener('click', () => {
      viewStart = 0;
      viewSpan = duration || 1;
      clampView();
      renderAll();
    });

    centerPlayheadBtn.addEventListener('click', () => {
      const maxZoom = 50;
      viewSpan = (duration || 1) / maxZoom;
      viewStart = video.currentTime - viewSpan / 2;
      clampView();
      renderAll();
    });

    const syncFollowBtn = () => {
      if (!followToggleBtn) return;
      followToggleBtn.classList.toggle('is-on', followPlayhead);
      followToggleBtn.textContent = followPlayhead ? '🧲 跟随' : '🧲 不跟随';
      followToggleBtn.title = followPlayhead
        ? '播放时自动跟随播放头（点击关闭）'
        : '已关闭自动跟随（点击开启）';
    };

    const setFollow = (on) => {
      followPlayhead = !!on;
      syncFollowBtn();
    };

    if (followToggleBtn) {
      followToggleBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        const next = !followPlayhead;
        followUserLocked = !next;
        setFollow(next);
      });
      syncFollowBtn();
    }

    // 播放中用户主动拖动/缩放波形时，暂停自动跟随，避免画面被强行拽走
    const noteManualViewChange = () => {
      if (followPlayhead && !video.paused && !video.ended) setFollow(false);
    };

    zoomSlider.addEventListener('input', () => {
      noteManualViewChange();
      const zoomLevel = Number(zoomSlider.value);
      const nextSpan = duration / zoomLevel;
      const centerTime = viewStart + viewSpan / 2;
      viewSpan = nextSpan;
      viewStart = centerTime - viewSpan / 2;
      clampView();
      renderAll();
    });

    playSelBtn.addEventListener('click', () => {
      if (!selected) return;
      if (isPlayingSelection) {
        video.pause();
        isPlayingSelection = false;
        playSelBtn.textContent = '▶ 试听';
      } else {
        safeSeekVideo(selected[0]);
        video.play();
        isPlayingSelection = true;
        playSelBtn.textContent = '⏸ 停止';
      }
    });

    clearSelBtn.addEventListener('click', () => {
      selected = null;
      selectionBar.style.display = 'none';
      renderAll();
    });

    syncBtn.addEventListener('click', () => {
      if (!selected) return;
      const startStr = format(selected[0]);
      const endStr = format(selected[1]);

      setGradioValue('slice-start', startStr);
      setGradioValue('slice-end', endStr);
      setGradioValue('hidden-sync-start', startStr);
      setGradioValue('hidden-sync-end', endStr);

      const startElem = document.getElementById('slice-start');
      if (startElem) {
        const details = startElem.closest('details');
        if (details) { details.open = true; }
      }

      const bridgeBtn = document.getElementById('btn-hidden-bridge-sync');
      if (bridgeBtn) { bridgeBtn.click(); }

      syncBtn.textContent = '✅ 已同步！';
      setTimeout(() => {
        syncBtn.textContent = '⏱ 同步时间到顶部';
      }, 1500);
    });

    transcribeSelBtn.addEventListener('click', () => {
      if (!selected) return;
      const startStr = format(selected[0]);
      const endStr = format(selected[1]);

      setGradioValue('hidden-sync-start', startStr);
      setGradioValue('hidden-sync-end', endStr);

      transcribeSelBtn.textContent = '⏳ 正在转写…';
      transcribeSelBtn.disabled = true;

      const patchBtn = document.getElementById('btn-hidden-bridge-transcribe');
      if (patchBtn) {
        patchBtn.click();
      }
    });

    const isEditingText = () => {
      const active = document.activeElement;
      if (!active) return false;
      const tag = active.tagName.toLowerCase();
      if (tag === 'input' || tag === 'textarea') return true;
      if (active.isContentEditable) return true;
      return false;
    };

    const handleKeyDown = (e) => {
      if (isEditingText()) return;

      if (e.code === 'Space' || e.key === ' ' || e.keyCode === 32) {
        e.preventDefault();
        togglePlay();
        return;
      }

      if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') {
        e.preventDefault();
        const frameRate = 24.0;
        const frameCount = e.shiftKey ? 5 : 1;
        const stepSeconds = frameCount / frameRate;

        if (!video.paused) {
          video.pause();
        }

        if (e.key === 'ArrowLeft') {
          safeSeekVideo(Math.max(0, video.currentTime - stepSeconds));
        } else {
          const maxTime = duration || video.duration || Infinity;
          safeSeekVideo(Math.min(maxTime, video.currentTime + stepSeconds));
        }

        updatePlayhead(true);

        if (duration && (video.currentTime < viewStart || video.currentTime > viewStart + viewSpan)) {
          viewStart = Math.max(0, Math.min(duration - viewSpan, video.currentTime - viewSpan / 2));
          renderAll();
        }
        return;
      }

      const isZKey = e.key === 'z' || e.key === 'Z';
      const isYKey = e.key === 'y' || e.key === 'Y';
      const isMod = e.metaKey || e.ctrlKey;

      if (isMod && (isZKey || isYKey)) {
        e.preventDefault();
        const isRedo = (isZKey && e.shiftKey) || (isYKey && !e.shiftKey);
        if (isRedo) {
          const redoBtn = document.querySelector('#btn-reviewer-redo button') || document.getElementById('btn-reviewer-redo');
          if (redoBtn) {
            redoBtn.click();
          }
        } else {
          const undoBtn = document.querySelector('#btn-reviewer-undo button') || document.getElementById('btn-reviewer-undo');
          if (undoBtn) {
            undoBtn.click();
          }
        }
        return;
      }
    };

    if (window.__reviewerKeyHandler) {
      window.removeEventListener('keydown', window.__reviewerKeyHandler);
    }
    window.__reviewerKeyHandler = handleKeyDown;
    window.addEventListener('keydown', window.__reviewerKeyHandler);

    new ResizeObserver(renderAll).observe(canvasWrap);
    clampView();

    // 质检队列联动：聚焦一个时间段并框选，可选自动播放（播到段尾自动停）。
    // 面板只调用这个方法，不直接操作内部 viewStart/selected，避免两套状态打架。
    const focusRange = (targetStart, targetEnd, opts = {}) => {
      if (!duration) return false;
      const s = Math.max(0, Number(targetStart) || 0);
      const e = Math.min(duration, Math.max(s + 0.03, Number(targetEnd) || 0));
      const span = Math.max(0.05, e - s);
      const pad = Math.max(0.9, span * 1.4);
      let nextSpan = Math.max(2.4, span + pad * 1.6);
      if (nextSpan > duration) nextSpan = duration;
      let nextStart = Math.max(0, s - pad * 0.4);
      if (nextStart + nextSpan > duration) nextStart = Math.max(0, duration - nextSpan);

      selected = [s, e];
      viewStart = nextStart;
      viewSpan = nextSpan;
      clampView();
      selectionBar.style.display = 'flex';
      selectionInfo.textContent = `已选: ${format(s)} → ${format(e)} (${span.toFixed(2)}s)`;
      isPlayingSelection = false;
      safeSeekVideo(s);
      if (opts.play) {
        isPlayingSelection = true;
        playSelBtn.textContent = '⏸ 停止';
        const p = video.play();
        if (p && typeof p.catch === 'function') p.catch(() => {});
      } else {
        playSelBtn.textContent = '▶ 试听';
      }
      renderAll();
      return true;
    };

    const stopPlayback = () => {
      isPlayingSelection = false;
      try { video.pause(); } catch (_) {}
      if (playSelBtn) playSelBtn.textContent = '▶ 试听';
    };

    window.__reviewerInstance = {
      updateCues: (newCues) => {
        cues.length = 0;
        cues.push(...newCues);
        lastSyncedCueIndex = -1;
        rebuildCaptionIndex();
        renderAll();
      },
      seekAndCenter: (targetTime) => {
        safeSeekVideo(targetTime);
        if (duration && (targetTime < viewStart || targetTime > viewStart + viewSpan)) {
          viewStart = Math.max(0, Math.min(duration - viewSpan, targetTime - viewSpan / 2));
        }
        renderAll();
      },
      focusRange: (start, end, opts) => focusRange(start, end, opts),
      playRange: (start, end) => focusRange(start, end, { play: true }),
      stopPlayback: () => stopPlayback(),
      getCueCount: () => cues.length,
      getCues: () => cues.map(cue => ({ start: cue.start, end: cue.end, text: cue.text }))
    };
    renderAll();
  } catch (err) {
    console.error('❌ [Reviewer] 渲染异常:', err);
  }
}
