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
   *
   * 2026-11-25（Step 4.2.1）：显示模式行与「#1 单句编辑」之间的整轨读数与三个裸链接
   * 压成一条单行的 `TrackBar`（读在左、入口在右、删除进菜单），下方用一条发丝线
   * 把「整轨」与「这一句」分开。整轨逻辑全在那个组件里，这里只剩显示模式与单句编辑。
   */
  import { onMount, tick } from 'svelte';
  import Icon from '../Icon.svelte';
  import ReviewAssistant from './ReviewAssistant.svelte';
  import {
    acceptCueTranslation,
    clearCueTranslate,
    cueTranslate,
    requestCueTranslation,
  } from '../../lib/cueTranslate.svelte';
  import TtsControls from './TtsControls.svelte';
  import TrackBar from './TrackBar.svelte';
  import {
    app,
    deleteCue,
    focusRange,
    isTranslationStale,
    play,
    previewRange,
    setTrackLang,
    setTrackMode,
    translationAt,
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

  let draft = $state('');
  let draftTr = $state('');
  let editingIndex = $state(-1);
  /** 非空 = 输入框里是 AI 刚填的草稿（还没采纳），提示条据此显示。 */
  let aiDraft = $state('');
  let aiModel = $state('');
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
    aiDraft = '';
    aiModel = '';
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
    if (targetChanged) {
      await updateTranslation(index, nextTarget);
      aiDraft = '';
      aiModel = '';
    }
  }

  // 快捷键复制 / 粘贴前也要先提交文本框里的草稿；注册到共享桥，App.svelte
  // 与检查器按钮走同一条等待逻辑。
  onMount(() => registerCueDraftCommit(commit));

  function remove() {
    if (!cue) return;
    deleteCue(play.selected);
    play.selected = Math.max(0, play.selected - 1);
  }

  /**
   * 请本地单句模型翻这一条，结果直接填进译文输入框（可改）。
   * 只有点「采纳」（或 ⌘↵ / 更新此行）才落轨——AI 草稿绝不留进历史。
   */
  async function aiTranslate() {
    const index = play.selected;
    const text = await requestCueTranslation(index, app.trackLang);
    // 请求期间可能已经换了句：草稿只归发起时那一条，不许写进别的输入框。
    if (!text || play.selected !== index) return;
    draftTr = text;
    aiDraft = text;
    aiModel = cueTranslate.model;
  }

  async function acceptAiDraft() {
    const index = play.selected;
    if (!aiDraft || !draftTr.trim()) return;
    if (await acceptCueTranslation(index, draftTr)) {
      aiDraft = '';
      aiModel = '';
    }
  }

  function dismissAiDraft() {
    aiDraft = '';
    aiModel = '';
    clearCueTranslate();
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
  <!-- 整轨：一行读数 + 一个入口（低频动作进 ⋯ 菜单）。
       下面 `.cue-card` 的上边线就是「整轨 / 这一句」的分界。 -->
  <TrackBar />

{#snippet translateHeader()}
  <div class="edit-label">
    <span>译文 · {app.trackLang}</span>
    <button
      class="ai-btn"
      onclick={aiTranslate}
      disabled={cueTranslate.busy}
      title="用本地单句模型翻这一条：只填草稿，点「采纳」才保存（可 ⌘Z 撤回）"
    >
      {#if cueTranslate.busy && cueTranslate.index === play.selected}
        正在译…
      {:else if translationAt(play.selected)}
        AI 重译
      {:else}
        AI 补译
      {/if}
    </button>
  </div>
{/snippet}

{#snippet translateFooter()}
  {#if cueTranslate.error && cueTranslate.index === play.selected}
    <div class="edit-hint">{cueTranslate.error}</div>
  {:else if aiDraft}
    <div class="ai-draft">
      <span class="ai-tag">AI 草稿 · 未保存{aiModel ? ` · ${aiModel}` : ''}</span>
      <button class="ai-link" onclick={acceptAiDraft} disabled={cueTranslate.busy}>采纳</button>
      <button class="ai-link muted" onclick={dismissAiDraft}>收起</button>
    </div>
  {:else if isTranslationStale(play.selected)}
    <div class="edit-hint">这一条的原文改过了，译文可能需要同步</div>
  {:else if !translationAt(play.selected)}
    <div class="edit-hint">这条还没有译文（局部转写新加进来的句子）</div>
  {/if}
{/snippet}

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
        {@render translateHeader()}
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
        {@render translateFooter()}
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
        {@render translateHeader()}
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
        {@render translateFooter()}
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
  /* 分段控件走全局语法（灰槽 + 纯白凸起胶囊 + 深墨文字）。2026-11-25（Step 4.2）
     删掉了这里原来的「accent-soft 底 + 蓝字」覆盖：同一屏里页签是底下划线、
     分段是白色凸起胶囊，蓝色只给主操作与计数，选中态不再靠一层半透明蓝。
     只把字号收 0.5px，让它比页签轻一档。 */
  .seg button {
    font-size: 12px;
  }
  .row-end {
    margin-left: auto;
    display: flex;
    align-items: center;
    gap: 6px;
    min-width: 0;
  }
  .lang-sel {
    height: var(--ctl-h);
    border: 1px solid transparent;
    border-radius: var(--rad-control);
    background: var(--well);
    color: var(--ink);
    font: inherit;
    font-size: 12px;
    padding: 0 7px;
  }
  .lang-sel:focus-visible {
    border-color: var(--accent);
    outline: none;
  }
  /* 当前句：全屏最大的字。2026-11-24（Phase 2）去卡片化——它原来是
     「白底 + 1px 灰框 + 2px 蓝左线 + 8px 圆角」的一层套娃，检查器里还有三四个
     同款，叠起来就是「网页表单」。现在**外层**只用一条 1px 上分割线分段，
     靠字号与留白建立层级。
     同日二改：套娃层不恢复，但里面的 textarea 恢复成独立输入框——
     两者不是一回事：外层再套卡会回到「网页表单」，而输入框没有边框
     就分不清「这行字能不能改」（浅色下字号再大也是正文长相）。 */
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
    font-size: var(--fs-mono);
    line-height: 16px;
    color: var(--ink-2);
    font-variant-numeric: tabular-nums;
    letter-spacing: -0.01em;
    white-space: nowrap;
  }
  /* 可编辑台词 = 一个**凹陷的输入区**（2026-11-26 第二次重塑）。
     它是输入框而不是卡片：无边框的极淡中性灰填充，和设置页 / AI 通道的
     输入框同一个令牌（--well）。聚焦才升成纸白 + 一道蓝须 —— 白色只属于
     「正在编辑的这一块」，不再常驻一张白框（检查器里白框套白框的那一层）。
     时间码留在框外上方（.cue-tc），框内只放可编辑的台词。 */
  .cue-text {
    display: block;
    width: 100%;
    margin-top: var(--sp-2);
    border: 1px solid var(--well-line);
    border-radius: var(--rad-control);
    background: var(--well);
    /* rows=2（20/29 × 2 = 58）加上上下内边距与 1px 边框，高度才是整数像素；
       用 padding 撑而不是靠 rows 硬顶，聚焦时框体不会跳。 */
    padding: 6px 9px;
    font: inherit;
    font-family: var(--font-cue);
    font-size: 20px;
    font-weight: 600;
    line-height: 29px; /* 20/29：1.45 取整，避免 29.0004 的小数行高 */
    letter-spacing: -0.01em;
    color: var(--ink);
    resize: none;
    min-height: 72px;
    user-select: text;
    outline: none;
    transition:
      border-color var(--dur-fast) var(--ease),
      box-shadow var(--dur-fast) var(--ease),
      background var(--dur-fast) var(--ease);
  }
  .cue-text.sub {
    font-family: var(--font-sans);
    font-size: 16px;
    font-weight: 400;
    line-height: 24px;
    color: var(--ink-2);
    min-height: 62px;
  }
  .cue-text:hover {
    background: var(--well-hover);
  }
  /* 聚焦：升成纸白 + 边框转强调色 + 一圈柔和光晕。用父级 `:focus-within`
     而不是 `:focus-visible` —— 点进输入框也要亮（那是「现在可以改这一句」），
     而且焦点落在框内任何位置都成立。 */
  .cue-card:focus-within .cue-text {
    background: var(--well-focus);
    border-color: var(--accent);
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
  /* 译文标签行：语种 + 「AI 补译」。做成 flex 才不用另起一行占高度。 */
  .edit-label {
    display: flex;
    align-items: center;
    gap: var(--sp-2);
  }
  .ai-btn {
    margin-left: auto;
    height: 20px;
    padding: 0 7px;
    border: 1px solid var(--line);
    border-radius: 4px;
    background: var(--raise);
    color: var(--ink-2);
    font: inherit;
    font-size: 11px;
    line-height: 18px;
    cursor: default;
    white-space: nowrap;
  }
  .ai-btn:hover:not(:disabled) {
    border-color: var(--accent);
    color: var(--accent);
  }
  .ai-btn:disabled {
    color: var(--text-3);
    opacity: 0.6;
    cursor: default;
  }
  /* AI 草稿提示：草稿已经在输入框里，这里只说明「还没保存」并给采纳入口。 */
  .ai-draft {
    display: flex;
    align-items: center;
    gap: 10px;
    margin-top: 6px;
    font-size: 12px;
    line-height: 16px;
  }
  .ai-tag {
    color: var(--accent);
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .ai-link {
    border: 0;
    background: transparent;
    color: var(--accent);
    font: inherit;
    font-size: 12px;
    padding: 0;
    cursor: pointer;
    white-space: nowrap;
  }
  .ai-link.muted {
    color: var(--text-3);
  }
  .ai-link:disabled {
    color: var(--text-3);
    opacity: 0.55;
    cursor: default;
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
