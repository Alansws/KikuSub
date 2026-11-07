(payloadText) => {
  try {
    const root = document.getElementById('qa-dock');
    if (!root) return;

    // Gradio 偶尔会在真实 payload 之后补发一次空值（例如组件重新挂载）。
    // 空事件绝不能把已经渲染好的队列清空：优先用隐藏框里的最新内容兜底。
    let rawText = payloadText;
    if (!rawText || rawText === '{}' || rawText === 'null') {
      const hidden = document.querySelector('#qa-payload textarea, #qa-payload input');
      if (hidden && hidden.value) rawText = hidden.value;
    }
    let data = {};
    try { data = JSON.parse(rawText || '{}'); } catch (_) { return; }
    const items = Array.isArray(data.items) ? data.items : [];

    // 事件回调只在第一次绑定时创建，之后 payload 变化只更新这里的数据。
    // 所有 handler 必须从 RT 取最新 items/data，绝不能闭包捕获某一次的空数组。
    const RT = (window.__qaRuntime = window.__qaRuntime || {});
    RT.items = items;
    RT.data = data;

    // ── 状态（页面内保持；偏好写 localStorage，刷新后不丢）──────────────
    const S = (window.__qaState = window.__qaState || {});
    if (!S._ready) {
      S._ready = true;
      S.filter = 'pending';
      S.currentId = null;
      S.autoNext = true;
      S.open = false;
      S.pinned = true;
      S.lastActionSeq = 0;
      S.signature = '';
      S.pendingId = null;
      S.note = '';
      try {
        const pref = JSON.parse(localStorage.getItem('kikusub.qa.prefs.v1') || '{}');
        if (typeof pref.filter === 'string') S.filter = pref.filter;
        if (typeof pref.autoNext === 'boolean') S.autoNext = pref.autoNext;
        if (typeof pref.pinned === 'boolean') S.pinned = pref.pinned;
      } catch (_) {}
    }

    const savePrefs = () => {
      try {
        localStorage.setItem('kikusub.qa.prefs.v1', JSON.stringify({
          filter: S.filter, autoNext: S.autoNext, pinned: S.pinned,
        }));
      } catch (_) {}
    };

    const esc = (text) => String(text == null ? '' : text).replace(/[&<>"']/g, c => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
    }[c]));

    const fmt = (sec) => {
      sec = Math.max(0, Number(sec) || 0);
      const h = Math.floor(sec / 3600);
      const m = Math.floor((sec % 3600) / 60);
      return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}:${(sec % 60).toFixed(3).padStart(6, '0')}`;
    };

    const kinds = {
      missed: { icon: '🔍', name: '可能漏句', cls: 'kind-missed' },
      dropped: { icon: '✂️', name: '误删待核', cls: 'kind-dropped' },
      suspect: { icon: '👂', name: '短句待确认', cls: 'kind-suspect' },
    };
    const resolutions = {
      filled: '已补录', restored: '已恢复', deleted: '已删除',
      kept: '已保留', confirmed: '已确认', 'not-speech': '不是台词', skipped: '已跳过',
    };

    const statusOf = (it) => String(it.status || 'pending');
    const isPending = (it) => statusOf(it) === 'pending';
    const kindOf = (it) => kinds[it.kind] || { icon: '•', name: '待核', cls: 'kind-other' };
    const resolutionLabel = (it) => resolutions[it.resolution] || (statusOf(it) === 'skipped' ? '已跳过' : '已处理');

    // ── DOM ─────────────────────────────────────────────────────────
    const fab = root.querySelector('#qa-fab');
    const fabText = root.querySelector('#qa-fab-text');
    const panel = root.querySelector('#qa-panel');
    const progressEl = root.querySelector('#qa-progress');
    const listEl = root.querySelector('#qa-list');
    const emptyEl = root.querySelector('#qa-empty');
    const filtersEl = root.querySelector('#qa-filters');
    const startBtn = root.querySelector('#qa-start-btn');
    const nextBtn = root.querySelector('#qa-next-btn');
    const autoNextEl = root.querySelector('#qa-auto-next');
    const currentEl = root.querySelector('#qa-current');
    const footEl = root.querySelector('#qa-foot');
    const pinBtn = root.querySelector('#qa-pin-btn');
    const helpEl = root.querySelector('#qa-help');
    const helpBtn = root.querySelector('#qa-help-btn');

    const videoEl = () => document.querySelector('.reviewer-video');
    const hookVideo = () => {
      const v = videoEl();
      if (!v || v.dataset.qaHooked === '1') return;
      v.dataset.qaHooked = '1';
      ['play', 'pause', 'ended', 'seeked'].forEach(ev => v.addEventListener(ev, () => updatePlayLabels()));
    };

    const setHiddenValue = (elemId, value) => {
      const container = document.getElementById(elemId);
      if (!container) return false;
      const input = container.querySelector('input') || container.querySelector('textarea');
      if (!input) return false;
      const proto = input instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
      const setter = Object.getOwnPropertyDescriptor(proto, 'value').set;
      setter.call(input, value);
      input.dispatchEvent(new Event('input', { bubbles: true }));
      input.dispatchEvent(new Event('change', { bubbles: true }));
      return true;
    };

    const clickHidden = (elemId) => {
      const el = document.getElementById(elemId);
      if (el) el.click();
    };

    const applyCmd = (cmd) => {
      setHiddenValue('qa-cmd', JSON.stringify(cmd));
      clickHidden('btn-hidden-qa');
    };

    const pendingItems = () => {
      const items = RT.items;
      return items.filter(isPending);
    };

    // 补录/删除/编辑都会写进「核对台」。核对台为空时如果直接操作，
    // 最终导出的 SRT 就只剩这一条——先强制引导用户把本次转写设为基线。
    const requireBaseline = () => {
      const info = baselineInfo();
      if (!info.empty) return true;
      S.note = '⚠️ 核对台还是空的：先点列表顶部的「📌 把本次转写设为基线」，再补录/删除，否则导出时会只剩这一条。';
      render();
      return false;
    };

    const baselineInfo = () => {
      const data = RT.data;
      // review_payload 是 visible=False 的组件，Gradio 6 不会把它渲染进 DOM；
      // 核对台字幕数以 reviewer 实例为准，DOM 只作为非 Gradio 环境的兜底。
      let n = -1;
      const inst = window.__reviewerInstance;
      if (inst && typeof inst.getCueCount === 'function') {
        try { n = Number(inst.getCueCount()) || 0; } catch (_) { n = -1; }
      }
      if (n < 0) {
        const container = document.getElementById('review-payload');
        const input = container ? (container.querySelector('textarea') || container.querySelector('input')) : null;
        if (input) {
          try {
            const parsed = JSON.parse(input.value || '{}');
            n = Array.isArray(parsed.cues) ? parsed.cues.length : 0;
          } catch (_) {}
        }
      }
      const latest = Number(data.latest_cue_count || 0);
      return { n, latest, empty: n === 0, mismatch: n > 0 && latest > 0 && n !== latest };
    };

    // ── 主要动作 ─────────────────────────────────────────────────────
    const note = (message) => { S.note = message || ''; renderFoot(); };

    const focusItem = (id, opts = {}) => {
      const items = RT.items;
      const item = items.find(it => it.id === id);
      if (!item) return;
      S.currentId = id;
      const start = Number(item.start) || 0;
      const end = Number(item.end) || (start + 0.1);
      hookVideo();
      // 播放时如果视频/波形整块在视口外，把它带到眼前；固定面板本身不会动。
      if (opts.play) {
        const stage = document.getElementById('rw-stage');
        if (stage) {
          const rect = stage.getBoundingClientRect();
          if (rect.bottom < 0 || rect.top > window.innerHeight) {
            try { stage.scrollIntoView({ behavior: 'smooth', block: 'center' }); } catch (_) {}
          }
        }
      }
      const inst = window.__reviewerInstance;
      if (inst && typeof inst.focusRange === 'function') {
        try { inst.focusRange(start, end, { play: Boolean(opts.play) }); } catch (_) {}
      } else {
        const v = videoEl();
        if (v) {
          try {
            v.currentTime = Math.max(0, start - 0.25);
            if (opts.play) {
              const p = v.play();
              if (p && typeof p.catch === 'function') p.catch(() => {});
            }
          } catch (_) {}
        }
      }
      renderList();
      renderCurrent();
      const row = listEl.querySelector(`.qa-item[data-id="${cssEscape(id)}"]`);
      if (row && row.scrollIntoView) row.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
    };

    const cssEscape = (value) => String(value).replace(/["\\]/g, '\\$&');

    const toggleListen = (id) => {
      const v = videoEl();
      if (v && S.currentId === id && !v.paused) {
        v.pause();
        updatePlayLabels();
        return;
      }
      focusItem(id, { play: true });
      setTimeout(updatePlayLabels, 120);
    };

    const focusNext = (afterId) => {
      const items = RT.items;
      const pending = pendingItems();
      if (!pending.length) {
        S.note = '🎉 所有待核项都处理完了，可以导出最终字幕了。';
        render();
        return;
      }
      const anchor = items.find(it => it.id === afterId) || items.find(it => it.id === S.currentId);
      let next = null;
      if (anchor) {
        next = pending.find(it => Number(it.start) > Number(anchor.start) + 0.001);
        if (!next) next = pending.find(it => it.id !== anchor.id);
      }
      if (!next) next = pending[0];
      const wasOpen = S.open;
      S.open = true;
      if (!wasOpen) render();
      focusItem(next.id, { play: true });
    };

    const startReview = () => {
      const items = RT.items;
      const pending = pendingItems();
      if (!pending.length) {
        S.note = '没有待核项了；可切到「全部」查看已处理记录。';
        render();
        return;
      }
      const wasOpen = S.open;
      S.open = true;
      if (!wasOpen) render();
      if (!S.currentId || !items.some(it => it.id === S.currentId && isPending(it))) {
        focusItem(pending[0].id, { play: true });
      } else {
        focusItem(S.currentId, { play: true });
      }
    };

    const doFill = (id) => {
      if (!requireBaseline()) return;
      const items = RT.items;
      const item = items.find(it => it.id === id);
      if (!item) return;
      const start = fmt(item.start);
      const end = fmt(item.end);
      setHiddenValue('hidden-sync-start', start);
      setHiddenValue('hidden-sync-end', end);
      S.pendingId = id;
      S.note = `⏳ 正在识别 ${start} → ${end}，完成后会自动插入核对台…`;
      renderFoot();
      const row = listEl.querySelector(`.qa-item[data-id="${cssEscape(id)}"]`);
      if (row) row.classList.add('is-busy');
      clickHidden('btn-hidden-bridge-transcribe');
    };

    const doSyncBaseline = () => {
      const btn = document.getElementById('btn-latest-as-base');
      if (!btn) {
        note('⚠️ 没找到「本次设为基线」按钮，请手动点击该按钮。');
        return;
      }
      btn.click();
      note('⏳ 正在把本次转写结果同步为核对基线…');
      setTimeout(() => { S.note = ''; render(); }, 1600);
    };

    const handleAction = (act, id) => {
      const items = RT.items;
      const item = items.find(it => it.id === id);
      if (act === 'listen') { toggleListen(id); return; }
      if (act === 'select') { focusItem(id, { play: false }); return; }
      if (act === 'fill') { doFill(id); return; }
      if (act === 'sync-baseline') { doSyncBaseline(); return; }
      if (!item) return;
      if ((act === 'restore' || act === 'remove' || act === 'edit' || act === 'keep') && !requireBaseline()) return;
      if (act === 'restore') { applyCmd({ action: 'restore', id }); return; }
      if (act === 'remove') { applyCmd({ action: 'delete_cue', id }); return; }
      if (act === 'keep') {
        applyCmd({ action: 'mark', id, status: 'done', resolution: item.kind === 'dropped' ? 'confirmed' : 'kept' });
        return;
      }
      if (act === 'confirm') { applyCmd({ action: 'mark', id, status: 'done', resolution: 'confirmed' }); return; }
      if (act === 'notspeech') { applyCmd({ action: 'mark', id, status: 'done', resolution: 'not-speech' }); return; }
      if (act === 'skip') { applyCmd({ action: 'skip', id }); return; }
      if (act === 'reopen') { applyCmd({ action: 'mark', id, status: 'pending' }); return; }
      if (act === 'edit') {
        applyCmd({ action: 'focus', id });
        focusItem(id, { play: false });
        const edit = document.querySelector('#cue-edit-text textarea, #cue-edit-text input');
        if (edit && edit.scrollIntoView) edit.scrollIntoView({ behavior: 'smooth', block: 'center' });
      }
    };

    // ── 渲染 ─────────────────────────────────────────────────────────
    const renderFilters = () => {
      const items = RT.items;
      const counts = {
        pending: items.filter(isPending).length,
        all: items.length,
        missed: items.filter(it => it.kind === 'missed').length,
        dropped: items.filter(it => it.kind === 'dropped').length,
        suspect: items.filter(it => it.kind === 'suspect').length,
        done: items.filter(it => statusOf(it) !== 'pending').length,
      };
      const chips = [
        ['pending', `待处理 ${counts.pending}`],
        ['all', `全部 ${counts.all}`],
      ];
      if (counts.missed) chips.push(['missed', `🔍 可能漏句 ${counts.missed}`]);
      if (counts.dropped) chips.push(['dropped', `✂️ 误删待核 ${counts.dropped}`]);
      if (counts.suspect) chips.push(['suspect', `👂 短句待确认 ${counts.suspect}`]);
      if (counts.done) chips.push(['done', `已处理 ${counts.done}`]);
      if (!chips.some(([key]) => key === S.filter)) S.filter = 'pending';
      filtersEl.innerHTML = chips.map(([key, label]) =>
        `<button type="button" class="qa-chip${S.filter === key ? ' is-on' : ''}" data-filter="${key}">${esc(label)}</button>`
      ).join('');
    };

    const itemDisplayText = (item) => {
      // 短句待确认显示“表格里真正存在的字幕”，而不是断句前的整段原文。
      // 断句器可能把一段拆成多条、也可能清洗复读，直接显示整段会让用户
      // 在核对台里找不到对应行，误以为“保留”没有同步。
      if (item.kind === 'suspect') {
        const cueTexts = (item.cues || []).map(c => String(c.text || '').trim()).filter(Boolean);
        if (cueTexts.length) {
          const body = cueTexts.map(t => `「${esc(t)}」`).join(' ');
          const original = String(item.text || '').trim();
          const note = original && !cueTexts.some(t => t === original)
            ? `<span class="qa-orig">（原始识别：${esc(original)}）</span>`
            : '';
          return body + note;
        }
      }
      return item.text
        ? `「${esc(item.text)}」`
        : (item.kind === 'missed' ? '（这一段没有识别出字幕）' : '');
    };

    const actionButtons = (item) => {
      const status = statusOf(item);
      if (status !== 'pending') {
        return `<button type="button" class="qa-btn" data-act="listen">▶ 试听</button>
                <button type="button" class="qa-btn qa-btn-ghost" data-act="reopen">↺ 重新待核</button>`;
      }
      if (item.kind === 'missed') {
        return `<button type="button" class="qa-btn qa-btn-listen" data-act="listen">▶ 试听</button>
                <button type="button" class="qa-btn" data-act="select">🎯 框选</button>
                <button type="button" class="qa-btn qa-btn-primary" data-act="fill">⚡ 补录并插入</button>
                <button type="button" class="qa-btn qa-btn-ghost" data-act="notspeech">✓ 不是台词</button>`;
      }
      if (item.kind === 'dropped') {
        return `<button type="button" class="qa-btn qa-btn-listen" data-act="listen">▶ 试听</button>
                <button type="button" class="qa-btn qa-btn-primary" data-act="restore">↩ 恢复原句</button>
                <button type="button" class="qa-btn" data-act="fill">⚡ 重新识别</button>
                <button type="button" class="qa-btn qa-btn-ghost" data-act="confirm">✓ 确认删除</button>`;
      }
      return `<button type="button" class="qa-btn qa-btn-listen" data-act="listen">▶ 试听</button>
              <button type="button" class="qa-btn" data-act="edit">✏️ 定位编辑</button>
              <button type="button" class="qa-btn qa-btn-primary" data-act="keep" title="保留；若核对台缺少这句会自动补回">✓ 保留</button>
              <button type="button" class="qa-btn qa-btn-danger" data-act="remove">🗑 删除此句</button>`;
    };

    const renderList = () => {
      const items = RT.items;
      const base = items.slice().sort((a, b) => (Number(a.start) || 0) - (Number(b.start) || 0));
      let filtered = base;
      if (S.filter === 'pending') filtered = base.filter(isPending);
      else if (S.filter === 'done') filtered = base.filter(it => statusOf(it) !== 'pending');
      else if (kinds[S.filter]) filtered = base.filter(it => it.kind === S.filter);

      const baseline = baselineInfo();
      let banner = '';
      if (baseline.empty && items.length) {
        banner = `<div class="qa-banner qa-banner-warn">
          <b>核对台还是空的。</b>补录会写进核对台；建议先把本次结果载入，避免只看到补录的几条。
          <button type="button" class="qa-btn qa-btn-primary qa-btn-sm" data-act="sync-baseline">📌 把本次转写设为基线</button>
        </div>`;
      } else if (baseline.mismatch) {
        banner = `<div class="qa-banner">
          核对台现有 <b>${baseline.n}</b> 条、本次识别 <b>${baseline.latest}</b> 条。
          补录/删除只会作用于核对台现有字幕，已手动改过的内容不会被覆盖。
        </div>`;
      }

      if (!filtered.length) {
        emptyEl.hidden = false;
        emptyEl.innerHTML = S.filter === 'pending'
          ? (items.length ? '🎉 当前筛选下没有待处理项，可切到「全部」查看已处理记录。' : '')
          : '这个筛选下暂时没有记录。';
        listEl.innerHTML = banner;
        renderFoot();
        return;
      }
      emptyEl.hidden = true;

      listEl.innerHTML = banner + filtered.map(item => {
        const kind = kindOf(item);
        const status = statusOf(item);
        const dur = Number(item.dur || 0) || Math.max(0, Number(item.end || 0) - Number(item.start || 0));
        const peak = (typeof item.peak === 'number') ? `音量 ${item.peak.toFixed(3)}` : '';
        const text = itemDisplayText(item);
        const badge = status === 'pending'
          ? '<span class="qa-status is-pending">待核</span>'
          : (status === 'skipped'
            ? '<span class="qa-status is-skipped">已跳过</span>'
            : `<span class="qa-status is-done">${esc(resolutionLabel(item))}</span>`);
        const rule = item.rule_label && item.kind !== 'missed'
          ? `<span class="qa-rule">${esc(item.rule_label)}</span>`
          : (item.rule_label && item.kind === 'missed' ? `<span class="qa-rule">${esc(item.rule_label)}</span>` : '');
        return `<article class="qa-item ${kind.cls}${status !== 'pending' ? ' is-done' : ''}${item.id === S.currentId ? ' is-current' : ''}" data-id="${esc(item.id)}">
          <div class="qa-item-top">
            <span class="qa-kind">${kind.icon} ${esc(kind.name)}</span>
            <span class="qa-time">${fmt(item.start)}</span>
            <span class="qa-dur">${dur.toFixed(2)}s</span>
            ${peak ? `<span class="qa-peak">${peak}</span>` : ''}
            ${rule}
            ${badge}
          </div>
          <div class="qa-item-text" title="${esc(item.hint || '')}">${text}</div>
          <div class="qa-item-actions">${actionButtons(item)}</div>
        </article>`;
      }).join('');
      renderFoot();
    };

    const renderFoot = () => {
      const data = RT.data;
      const parts = [];
      if (S.note) parts.push(`<div class="qa-note-text">${esc(S.note)}</div>`);
      if (Number(data.hidden_missed || 0) > 0) {
        parts.push(`<div class="qa-note-muted">另有 ${data.hidden_missed} 处峰值极低的近静音段未列入（多为配乐/底噪误判，已留在 .missed.json 备查）。</div>`);
      }
      parts.push('<div class="qa-note-muted">同一次运行内刷新页面/重开媒体会恢复进度；重启应用后默认清空。</div>');
      footEl.innerHTML = parts.join('');
    };

    const renderCurrent = () => {
      const items = RT.items;
      const item = items.find(it => it.id === S.currentId);
      if (!item) {
        currentEl.hidden = true;
        currentEl.innerHTML = '';
        return;
      }
      const kind = kindOf(item);
      const status = statusOf(item);
      const v = videoEl();
      const playing = Boolean(v && item.id === S.currentId && !v.paused && !v.ended);
      currentEl.hidden = false;
      currentEl.className = `qa-current ${kind.cls}`;
      currentEl.innerHTML = `<span class="qa-current-kind">${kind.icon} ${esc(kind.name)}</span>
        <span class="qa-current-time">${fmt(item.start)} → ${fmt(item.end)}</span>
        <span class="qa-current-state">${status === 'pending' ? (playing ? '正在试听…' : '已暂停，待你判断') : esc(resolutionLabel(item))}</span>`;
    };

    const updatePlayLabels = () => {
      const v = videoEl();
      const playing = Boolean(v && !v.paused && !v.ended && S.currentId);
      listEl.querySelectorAll('.qa-item').forEach(row => {
        const isCurrent = row.dataset.id === S.currentId;
        row.classList.toggle('is-current', isCurrent);
        const btn = row.querySelector('[data-act="listen"]');
        if (btn) btn.textContent = (isCurrent && playing) ? '⏸ 停止' : '▶ 试听';
      });
      if (S.currentId) renderCurrent();
    };

    const render = () => {
      const items = RT.items;
      const data = RT.data;
      // 新一批待核项：先自动展开钉住面板，再按最新 open/pinned 计算显示模式。
      const signature = items.map(it => it.id).join('|');
      let isNewSignature = false;
      if (signature !== S.signature) {
        isNewSignature = true;
        S.signature = signature;
        S.currentId = null;
        S.lastActionSeq = 0;
        S.note = '';
        if (items.length && items.some(isPending)) {
          S.open = true;
          S.pinned = true;
        }
      }

      const pending = items.filter(isPending).length;
      const done = items.length - pending;
      const mode = items.length ? (S.open ? (S.pinned ? 'open-pinned' : 'open-inline') : 'mini') : 'hidden';
      root.dataset.mode = mode;
      root.dataset.pinned = S.pinned ? '1' : '0';

      if (items.length) {
        fab.classList.toggle('is-complete', pending === 0);
        if (fabText) fabText.textContent = pending === 0
          ? '质检完成 · 查看记录'
          : `质检 ${pending} 处待核`;
        progressEl.textContent = `${done} / ${items.length} 已处理`;
        startBtn.textContent = pending ? (S.currentId ? '▶ 继续核对当前处' : '▶ 开始逐条核对') : '✅ 全部处理完';
        startBtn.disabled = pending === 0;
        nextBtn.disabled = pending === 0;
        pinBtn.textContent = S.pinned ? '📌 已钉住' : '📍 钉住';
        pinBtn.classList.toggle('is-on', S.pinned);
        autoNextEl.checked = Boolean(S.autoNext);
        hookVideo();
        renderFilters();
        renderList();
        renderCurrent();
        updatePlayLabels();
      } else {
        listEl.innerHTML = '';
        filtersEl.innerHTML = '';
        currentEl.hidden = true;
        emptyEl.hidden = true;
        footEl.innerHTML = '';
        S.note = '';
        S.currentId = null;
      }

      // 处理完一条后自动跳下一条（后端用 revision 标记“这是一次真实操作”）。
      // 但重新打开已保存的队列时，last_action 是上次会话留下的：只记录基线，
      // 不能一进页面就自动播放某个片段。
      const act = data.last_action;
      if (isNewSignature) {
        S.lastActionSeq = Number((act && act.seq) || 0);
      } else if (act && Number(act.seq || 0) > S.lastActionSeq) {
        S.lastActionSeq = Number(act.seq || 0);
        if (act.message) {
          S.note = String(act.message);
          renderFoot();
        }
        if (act.auto_advance && S.autoNext && items.some(isPending)) {
          setTimeout(() => focusNext(act.id), 450);
        }
      }
    };

    // ── 事件绑定（只绑一次；数据统一走 RT，避免闭包记住旧的空数组）────
    if (!S._bound) {
      S._bound = true;
      fab.addEventListener('click', () => {
        if (!pendingItems().length) S.filter = 'all';
        S.open = true;
        S.pinned = true;
        savePrefs();
        render();
      });
      root.querySelector('#qa-collapse-btn').addEventListener('click', () => {
        S.open = false;
        savePrefs();
        render();
      });
      pinBtn.addEventListener('click', () => {
        S.pinned = !S.pinned;
        S.open = true;
        savePrefs();
        render();
        // 取消钉住后，面板回到页面顶部内嵌位置；把它带到眼前，避免“点了就消失”。
        if (!S.pinned && panel.scrollIntoView) {
          setTimeout(() => panel.scrollIntoView({ behavior: 'smooth', block: 'center' }), 60);
        }
      });
      helpBtn.addEventListener('click', () => {
        helpEl.hidden = !helpEl.hidden;
        helpBtn.classList.toggle('is-on', !helpEl.hidden);
      });
      startBtn.addEventListener('click', startReview);
      nextBtn.addEventListener('click', () => focusNext(S.currentId));
      autoNextEl.addEventListener('change', () => { S.autoNext = autoNextEl.checked; savePrefs(); });
      filtersEl.addEventListener('click', (e) => {
        const chip = e.target.closest('[data-filter]');
        if (!chip) return;
        S.filter = chip.dataset.filter;
        savePrefs();
        render();
      });
      listEl.addEventListener('click', (e) => {
        const btn = e.target.closest('button[data-act]');
        if (!btn) return;
        e.preventDefault();
        e.stopPropagation();
        const row = btn.closest('.qa-item');
        const id = row ? row.dataset.id : '';
        handleAction(btn.dataset.act, id);
      });
      panel.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') { S.open = false; render(); }
      });
    }

    // 对外接口：补录完成后由 Gradio 的 .then(js=...) 调用
    window.__qaPanel = {
      afterTranscribe: (status) => {
        const text = String(status || '');
        if (!S.pendingId) return;
        const id = S.pendingId;
        if (text.includes('已成功转录并直接入轨') || text.includes('选区已成功转录')) {
          S.pendingId = null;
          S.note = '⚡ 补录成功，已插入核对台。';
          applyCmd({ action: 'mark', id, status: 'done', resolution: 'filled' });
        } else {
          S.pendingId = null;
          S.note = text.includes('未检出语音')
            ? '⚠️ 这段没有识别出语音：可手动输入文本后点「插入为新句」，或标为「不是台词」。'
            : '⚠️ 补录没有成功，请重试，或在波形上手动框选。';
          render();
        }
      },
      focusNext: () => focusNext(S.currentId),
      focusItem: (id) => focusItem(id, { play: true }),
      open: () => { S.open = true; S.pinned = true; savePrefs(); render(); },
      refresh: () => render(),
      getState: () => ({ currentId: S.currentId, filter: S.filter, pending: RT.items.filter(isPending).length }),
    };

    render();
  } catch (err) {
    console.error('❌ [QA] 渲染异常:', err);
  }
}
