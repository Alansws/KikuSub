<script lang="ts">
  /**
   * 右侧检查器的「当前条目」页：显示模式行、译文轨信息、稿纸卡（原文 / 译文编辑）、
   * 操作行（试听原声 / TTS 朗读 / 聚焦 / 复制 / 删除 / 更新此行）、字幕剪贴板。
   *
   * 2026-11-21 从 Inspector.svelte 抽出来（Step 3）：那一个文件已经 2200 行，而
   * 「当前条目」是核对期间真正一直要用的那一块，改它的排版不该先读完整份检查器。
   *
   * TTS 只有一个图标按钮 + 音色下拉常驻在操作行里（`TtsControls`）；语速、上传 /
   * 截取 / 音色库 / 管理收进它自己按需展开的面板——原来的底部「TTS 对照」大卡片
   * 在标准窗口高度下会被底部保存栏截断，用户得滚动才看得见。
   */
  import { onMount, tick } from 'svelte';
  import Icon from '../Icon.svelte';
  import ReviewAssistant from './ReviewAssistant.svelte';
  import TtsControls from './TtsControls.svelte';
  import {
    app,
    deleteCue,
    focusRange,
    importTranslationFromExport,
    isTranslationStale,
    play,
    previewRange,
    removeTranslationTrack,
    setTrackLang,
    setTrackMode,
    staleTranslationCount,
    translationAt,
    undoTranslation,
    updateCue,
    updateTranslation,
  } from '../../lib/store.svelte';
  import {
    clearCueClip,
    copySelectedCue,
    cueClip,
    pasteCueAtPlayhead,
  } from '../../lib/cueClipboard.svelte';
  import { clipSummary } from '../../lib/cueClip';
  import { tc } from '../../lib/time';
  import { comboOf, formatCombo } from '../../lib/shortcuts.svelte';
  import { registerCueDraftCommit } from '../../lib/cueDraftCommit';

  const cue = $derived(app.cues[play.selected] ?? null);
  const trackLangs = $derived(Object.keys(app.translations).sort());
  const hasTrack = $derived(Boolean(app.translations[app.trackLang]));
  const staleCount = $derived(staleTranslationCount());

  let draft = $state('');
  let draftTr = $state('');
  let editingIndex = $state(-1);
  /** 同步键：换了选中行 / 语种 / 显示模式 / 换了一版译文，才重新灌编辑框 */
  let syncKey = $state('');
  let sourceEl = $state<HTMLTextAreaElement | null>(null);
  let targetEl = $state<HTMLTextAreaElement | null>(null);

  // 右键「添加字幕」后把光标直接放进文本框，用户不用再点一下。
  // 只在 nonce **变化**时聚焦：切页重挂载时如果直接读旧 nonce，
  // 每次回到核对页都会把整段文本选中，用户按空格试听就把字幕替换成空格了。
  let seenEditNonce = play.editNonce;
  $effect(() => {
    const nonce = play.editNonce;
    if (nonce === seenEditNonce) return;
    seenEditNonce = nonce;
    void tick().then(() => {
      const el = app.track === 'target' ? targetEl : sourceEl;
      el?.focus();
      el?.select();
    });
  });

  // 选中行 / 语种 / 模式 / 译文版本变化时，把文本灌进编辑框。
  // 不用 `editingIndex` 单判：切到译文模式时同一行也要换内容。
  $effect(() => {
    const idx = play.selected;
    const c = app.cues[idx];
    if (!c) return;
    // 撤销 / 历史跳转 / 删除 / 切割 / 合并后，cue 与译文都会重新拉取：
    // 只用 created_at 当版本号时，⌘Z 恢复了原文、右侧编辑框却还是空白的。
    const key = `${idx}:${app.track}:${app.trackLang}:${app.cuesRevision}:${app.translationsRevision}`;
    if (key === syncKey) return;
    syncKey = key;
    editingIndex = idx;
    draft = c.text;
    draftTr = translationAt(idx);
  });

  /** 只提交当前显示模式里真正可见的那几个框。 */
  async function commit() {
    if (!cue) return;
    const index = play.selected;
    const nextSource = draft;
    const nextTarget = draftTr;
    const sourceChanged = nextSource !== cue.text;
    const targetChanged = nextTarget !== translationAt(index);

    if (app.track === 'source') {
      if (sourceChanged) await updateCue(index, { text: nextSource });
      return;
    }
    if (app.track === 'target') {
      if (targetChanged) await updateTranslation(index, nextTarget);
      return;
    }
    // 双语：两个框都能改。必须先落原文再落译文——服务端在改译文时会用
    // 当前原文刷新 base，顺序反了会让「原文改过了」的提示永远消不掉。
    if (sourceChanged) await updateCue(index, { text: nextSource });
    if (targetChanged) await updateTranslation(index, nextTarget);
  }

  // 快捷键复制 / 粘贴前也要先提交文本框里的草稿；注册到共享桥，App.svelte
  // 与检查器按钮走同一条等待逻辑。
  onMount(() => registerCueDraftCommit(commit));

  function remove() {
    if (!cue) return;
    deleteCue(play.selected);
    play.selected = Math.max(0, play.selected - 1);
  }

  async function removeTranslation() {
    const lang = app.trackLang;
    if (!lang || !app.translations[lang]) return;
    await removeTranslationTrack(lang);
  }
</script>

  <div class="display-row">
    <div class="seg">
      <button class:on={app.track === 'source'} onclick={() => setTrackMode('source')}>原文</button>
      <button
        class:on={app.track === 'target'}
        disabled={!hasTrack}
        title={hasTrack ? '只显示译文' : '还没有译文'}
        onclick={() => setTrackMode('target')}>译文</button
      >
      <button
        class:on={app.track === 'both'}
        disabled={!hasTrack}
        title={hasTrack ? '原文 + 译文上下两行' : '还没有译文'}
        onclick={() => setTrackMode('both')}>双语</button
      >
    </div>
    <div class="row-end">
      {#if !hasTrack}
        <!-- 没有译文轨时不再单独占一行说「还没有译文字幕」：译文 / 双语两个按钮本来就
             是灰的，导入入口就放在这一行右端（省下一条 24px 的空态行）。 -->
        <button
          class="link import-link"
          onclick={() => importTranslationFromExport()}
          disabled={!app.cues.length}
          title="选择与当前原文逐条对齐的译文 SRT / VTT"
        >导入译文…</button>
      {/if}
      <select
        class="lang-sel"
        value={app.trackLang}
        title="译文语种"
        onchange={(e) => setTrackLang(e.currentTarget.value)}
      >
        {#each trackLangs as lang (lang)}
          <option value={lang}>{lang}</option>
        {/each}
        {#if !trackLangs.length}
          <option value={app.trackLang}>{app.trackLang}</option>
        {/if}
      </select>
    </div>
  </div>
  {#if hasTrack}
    <div class="track-meta">
      <span>{app.translations[app.trackLang]?.count ?? 0} 条</span>
      {#if staleCount > 0}
        <span class="warn">{staleCount} 条待更新</span>
      {:else}
        <span class="ok">全部同步</span>
      {/if}
      <button class="link" onclick={() => importTranslationFromExport()}>导入译文</button>
      <button class="link" onclick={() => undoTranslation()}>撤销译文</button>
      <button class="link danger" onclick={removeTranslation}>删除译文</button>
    </div>
  {/if}

  <!-- 当前句 = 一张稿纸卡：20/600、白色卡片、2px 蓝左线。它是这一屏最大的字。 -->
  <div class="cue-card">
    {#if cue}
      <div class="cue-tc">{tc(cue.start)} → {tc(cue.end)} · {(cue.end - cue.start).toFixed(2)}s</div>

      {#if app.track === 'source'}
        <textarea
          class="cue-text"
          bind:this={sourceEl}
          bind:value={draft}
          onblur={commit}
          onkeydown={(e) => {
            if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) commit();
          }}
          spellcheck="false"
          rows="2"
        ></textarea>
      {:else if app.track === 'target'}
        <div class="edit-label">译文 · {app.trackLang}</div>
        <textarea
          class="cue-text sub"
          bind:this={targetEl}
          bind:value={draftTr}
          onblur={commit}
          onkeydown={(e) => {
            if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) commit();
          }}
          spellcheck="false"
          rows="2"
        ></textarea>
        {#if isTranslationStale(play.selected)}
          <div class="edit-hint">这一条的原文改过了，译文可能需要同步</div>
        {/if}
      {:else}
        <div class="edit-label">原文</div>
        <textarea
          class="cue-text"
          bind:this={sourceEl}
          bind:value={draft}
          onblur={commit}
          onkeydown={(e) => {
            if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) commit();
          }}
          spellcheck="false"
          rows="2"
        ></textarea>
        <div class="edit-label">译文 · {app.trackLang}</div>
        <textarea
          class="cue-text sub"
          bind:this={targetEl}
          bind:value={draftTr}
          onblur={commit}
          onkeydown={(e) => {
            if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) commit();
          }}
          spellcheck="false"
          rows="2"
        ></textarea>
        {#if isTranslationStale(play.selected)}
          <div class="edit-hint">这一条的原文改过了，译文可能需要同步</div>
        {/if}
      {/if}
    {:else}
      <div class="cue-empty">还没有字幕。到「转写」跑一次，或在音轨上右键添加一条。</div>
    {/if}
  </div>

  {#if cue}
    <!-- 两行：第一行「听」（原声 + TTS 朗读与音色），第二行「改」。 -->
    <div class="actions">
      <button
        class="btn"
        onclick={() => previewRange(cue.start, cue.end)}
        title="试听原片这一句的原声（下方的朗读是 TTS 合成，两者可对照）"
      >
        <Icon name="play" size={11} />试听原声
      </button>
      <TtsControls index={play.selected} />
    </div>
    <div class="actions edit-row">
      <button class="btn ghost" onclick={() => focusRange(cue.start, cue.end)} title="在波形上聚焦放大这一句">
        <Icon name="search" size={11} />聚焦
      </button>
      <button
        class="btn icon ghost"
        data-copy-cue
        onclick={() => copySelectedCue()}
        title={`复制这句的字幕文本与时长（${formatCombo(comboOf('review.copyCue'))}）；再把播放头移到目标位置粘贴`}
        aria-label="复制这句字幕"
      >
        <Icon name="copy" size={12} />
      </button>
      <button class="btn icon ghost danger" onclick={remove} title="删除此句">
        <Icon name="trash" size={12} />
      </button>
      <button
        class="btn primary commit"
        onclick={commit}
        disabled={app.track === 'source'
          ? draft === cue.text
          : draft === cue.text && draftTr === translationAt(play.selected)}
      >
        更新此行
      </button>
    </div>
  {/if}

  {#if cueClip.value}
    <div class="clip-strip" aria-label="字幕剪贴板">
      <Icon name="paste" size={12} />
      <span class="clip-text" title={cueClip.value.text}>{clipSummary(cueClip.value)}</span>
      <button
        class="link"
        data-paste-cue
        onclick={() => pasteCueAtPlayhead()}
        title={`在播放头新建一条（${formatCombo(comboOf('review.pasteCue'))}）`}
      >粘贴到播放头</button>
      <button
        class="btn icon ghost clip-clear"
        onclick={clearCueClip}
        title="清空字幕剪贴板"
        aria-label="清空字幕剪贴板"
      >
        <Icon name="close" size={10} />
      </button>
    </div>
  {/if}

  {#if cue}
    <ReviewAssistant index={play.selected} text={cue.text} />
  {/if}

<style>
  .display-row {
    display: flex;
    align-items: center;
    gap: var(--sp-2);
    /* 页签底边已经是一条分隔线，这里不再叠一层 12px 的空白。 */
    margin-top: 0;
  }
  /* G15：与上方页签（.insp-tab.on）统一成一套语法 ——
     选中态 = accent-soft 底 + accent-text 字，不再用「白底 + 阴影」那套。
     只作用于检查器内的这个 .seg，全局 .seg 不动（20+ 处复用，改动面太大）。 */
  .seg {
    height: 26px;
    padding: 2px;
    border-radius: 6px;
  }
  .seg button {
    height: 20px;
    padding: 0 9px;
    font-size: 12px;
    border-radius: 4px;
  }
  .seg button.on {
    background: var(--accent-soft);
    color: var(--accent-text);
    box-shadow: none;
    font-weight: 600;
  }
  .row-end {
    margin-left: auto;
    display: flex;
    align-items: center;
    gap: 6px;
    min-width: 0;
  }
  .import-link {
    appearance: none;
    border: 0;
    background: transparent;
    color: var(--accent);
    font: inherit;
    font-size: 12px;
    padding: 0;
    white-space: nowrap;
    cursor: pointer;
  }
  .import-link:disabled {
    color: var(--text-3);
    opacity: 0.55;
    cursor: default;
  }
  .lang-sel {
    height: 26px;
    border: 1px solid var(--line);
    border-radius: 4px;
    background: var(--raise);
    color: var(--ink);
    font: inherit;
    font-size: 12px;
    padding: 0 7px;
  }
  .track-meta {
    display: flex;
    align-items: center;
    gap: var(--sp-2);
    margin-top: var(--sp-2);
    font-size: 12px;
    line-height: 16px;
    color: var(--ink-3);
  }
  .track-meta .ok {
    color: var(--success);
  }
  .track-meta .warn {
    color: var(--warn);
  }
  .track-meta .link {
    margin-left: auto;
    border: 0;
    background: transparent;
    color: var(--accent);
    font: inherit;
    font-size: 12px;
    cursor: pointer;
    padding: 0;
  }
  .track-meta .link + .link {
    margin-left: 2px;
  }
  .track-meta .link:disabled {
    color: var(--text-3);
    opacity: 0.55;
    cursor: default;
  }
  .track-meta .link.danger {
    color: var(--danger);
  }

  /* 当前句：全屏最大的字。2026-11-24（Phase 2）去卡片化——它原来是
     「白底 + 1px 灰框 + 2px 蓝左线 + 8px 圆角」的一层套娃，检查器里还有三四个
     同款，叠起来就是「网页表单」。现在只用一条 1px 上分割线分段，
     靠字号与留白建立层级；可编辑能力一点没变（还是 textarea）。 */
  .cue-card {
    margin-top: var(--sp-3);
    padding: var(--sp-3) 0 0;
    background: transparent;
    border: 0;
    border-top: 1px solid var(--line);
    border-radius: 0;
  }
  .cue-tc {
    font-family: var(--font-mono);
    font-size: 12px;
    line-height: 16px;
    color: var(--ink-2);
    font-variant-numeric: tabular-nums;
    letter-spacing: -0.01em;
    white-space: nowrap;
  }
  .cue-text {
    display: block;
    width: 100%;
    margin-top: var(--sp-2);
    border: 0;
    border-radius: 4px;
    background: transparent;
    padding: 0;
    font: inherit;
    font-family: var(--font-cue);
    font-size: 20px;
    font-weight: 600;
    line-height: 29px; /* 20/29：1.45 取整，避免 29.0004 的小数行高 */
    letter-spacing: -0.01em;
    color: var(--ink);
    resize: none;
    min-height: 58px;
    user-select: text;
    outline: none;
    transition: box-shadow var(--dur-fast) var(--ease);
  }
  .cue-text.sub {
    font-family: var(--font-sans);
    font-size: 16px;
    font-weight: 400;
    line-height: 24px;
    color: var(--ink-2);
    min-height: 44px;
  }
  .cue-text:focus-visible {
    outline: none;
    box-shadow: 0 0 0 3px var(--accent-soft);
  }
  .edit-label {
    margin: var(--sp-3) 0 0;
    font-size: 12px;
    line-height: 16px;
    color: var(--ink-3);
  }
  .edit-hint {
    margin-top: 6px;
    font-size: 12px;
    color: var(--warn);
  }
  .cue-empty {
    padding-top: var(--sp-2);
    font-size: 12.5px;
    line-height: 1.6;
    color: var(--ink-3);
  }

  .actions {
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    gap: var(--sp-2);
    margin-top: var(--sp-4);
  }
  /* 第二行贴紧第一行：它们是一组操作，不是两个区块 */
  .actions.edit-row {
    margin-top: var(--sp-2);
  }
  .actions .btn.primary {
    flex: 1;
    justify-content: center;
  }
  .actions .btn.icon {
    flex: 0 0 28px;
  }
  /* 字幕剪贴板：只在复制过之后出现；把「粘贴到播放头」放在一眼能看到的位置。 */
  .clip-strip {
    margin-top: var(--sp-2);
    padding: var(--sp-2) 0;
    border: 0;
    border-top: 1px solid var(--line-2);
    border-radius: 0;
    background: transparent;
    display: flex;
    align-items: center;
    gap: var(--sp-2);
    font-size: 12px;
    color: var(--text-2);
  }
  .clip-text {
    flex: 1;
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .clip-strip .link {
    appearance: none;
    flex: 0 0 auto;
    border: 0;
    background: transparent;
    color: var(--accent);
    font: inherit;
    font-size: 12px;
    padding: 0;
    cursor: default;
  }
  .clip-strip .link:hover {
    text-decoration: underline;
  }
  .clip-clear {
    flex: 0 0 22px;
    width: 22px;
    height: 22px;
    padding: 0;
  }
  .danger {
    color: var(--danger);
  }

  .mini {
    height: 26px;
    padding: 0 var(--sp-2);
    font-size: 12px;
  }
</style>
