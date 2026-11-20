<script lang="ts">
  import Icon from './Icon.svelte';
  import QaPanel from './QaPanel.svelte';
  import ChaptersPanel from './ChaptersPanel.svelte';
  import SecondOpinionCard from './SecondOpinionCard.svelte';
  import {
    app,
    deleteCue,
    exportCues,
    focusRange,
    cloneEngineReady,
    importTranslationFromExport,
    deleteTtsVoice,
    downloadTtsModel,
    extractTtsVoiceFromCue,
    loadTranslations,
    loadTtsVoices,
    play,
    previewRange,
    previewTtsVoice,
    refreshDraftInfo,
    restoreDraft,
    reviewDraft,
    renameTtsVoice,
    removeTranslationTrack,
    saveDraft,
    isTranslationStale,
    setTrackLang,
    setTrackMode,
    setTtsDefaultVoiceId,
    setTtsSpeed,
    setInspectorTab,
    setTtsVoiceId,
    setView,
    speakCue,
    staleTranslationCount,
    stopTts,
    toast,
    translationAt,
    qa,
    tts,
    ttsVoice,
    undoTranslation,
    updateCue,
    updateTranslation,
    updateTtsRefText,
    uploadTtsVoice,
    uploadTtsVoices,
    type TrackMode,
  } from '../lib/store.svelte';
  import { chapterCount } from '../lib/chapters.svelte';
  import { tc } from '../lib/time';
  import { tick, onMount } from 'svelte';
  import {
    clearCueClip,
    copySelectedCue,
    cueClip,
    pasteCueAtPlayhead,
  } from '../lib/cueClipboard.svelte';
  import { clipSummary } from '../lib/cueClip';
  import { comboOf, formatCombo } from '../lib/shortcuts.svelte';
  import { registerCueDraftCommit } from '../lib/cueDraftCommit';

  const cue = $derived(app.cues[play.selected] ?? null);
  const qaPending = $derived(Number(qa.payload?.counts?.pending ?? 0));

  /**
   * 当前核对表的来源决定右侧信息能不能引用「最近一次转写」：
   * - transcription：报告/参数/质检都属于这张表；
   * - import / draft：换了一版字幕，旧报告已经对不上，不能再展示它的数字。
   */
  const source = $derived(app.reviewSource);
  const imported = $derived(source?.kind === 'import' || source?.kind === 'draft');
  const sourceLabel = $derived(
    source?.kind === 'import'
      ? '手动导入'
      : source?.kind === 'draft'
        ? '暂存草稿'
        : source?.kind === 'transcription'
          ? '本次转写'
          : '未记录',
  );
  const report = $derived.by(() => {
    if (imported) return null;
    const data = app.report;
    if (!data) return null;
    // 任务 id 都已知时必须一致：否则是上一部片 / 上一次转写的报告。
    const sourceJob = source?.job_id || '';
    if (sourceJob && data.job_id && sourceJob !== data.job_id) return null;
    return data;
  });
  const reportStale = $derived(Boolean(app.report && !imported && !report));
  const quality = $derived(report?.quality ?? null);
  const outputName = $derived.by(() => {
    if (source?.name) return source.name;
    if (report?.out_filename) return report.out_filename;
    const fromReport = report?.overview?.find((r) => r.label === '字幕文件名')?.value;
    return fromReport ?? app.media?.name ?? '—';
  });
  const sourcePath = $derived(source?.path || '');

  let draft = $state('');
  let draftTr = $state('');
  let editingIndex = $state(-1);
  /** 同步键：换了选中行 / 语种 / 显示模式 / 换了一版译文，才重新灌编辑框 */
  let syncKey = $state('');
  let exportFormat = $state<'SRT' | 'VTT' | 'TXT'>('SRT');
  let exportTrack = $state<'source' | 'target' | 'both'>('source');
  let exporting = $state(false);
  let sourceEl = $state<HTMLTextAreaElement | null>(null);
  let targetEl = $state<HTMLTextAreaElement | null>(null);

  // ---- TTS 音色管理（克隆音色重命名/参考文本/上传） ----
  let ttsManage = $state(false);
  let ttsName = $state('');
  let ttsRefText = $state('');
  let ttsSaving = $state(false);
  let uploadDraft = $state<{ path: string; name: string; refText: string } | null>(null);
  /** 从当前句截取参考音频：与右键菜单共用后端切片，但入口放在 TTS 面板里。 */
  let extractDraft = $state<{ index: number; name: string; refText: string } | null>(null);
  /** 音色库：列出所有已保存的克隆音色，随时复用。 */
  let ttsLibrary = $state(false);
  let batch = $state<{ done: number; total: number; name: string } | null>(null);
  const selectedTts = $derived(ttsVoice());
  const downloading = $derived(tts.download?.status === 'running');
  const engineLabel = $derived.by(() => {
    // 标题跟「当前选中的音色」走：选着 Kyoko 却显示 OmniVoice 会让人以为已经在用克隆。
    if (selectedTts?.kind === 'clone') {
      if (!tts.engine?.installed) return '克隆模型未就绪';
      return tts.engine.device === 'mps' ? 'OmniVoice · Apple GPU' : 'OmniVoice · CPU';
    }
    return tts.engine ? '系统语音' : '读取中…';
  });
  const engineTone = $derived(
    selectedTts?.kind === 'clone'
      ? tts.engine?.installed
        ? 'ready'
        : 'warn'
      : tts.engine
        ? 'system'
        : 'idle',
  );
  const engineTitle = $derived.by(() => {
    if (selectedTts?.kind === 'clone') {
      if (!tts.engine?.installed) return '克隆模型还没下载：点下方「下载克隆模型」后即可使用参考音频克隆';
      const device = tts.engine?.device === 'mps' ? 'Apple GPU' : 'CPU';
      return `OmniVoice 零样本克隆 · ${device} · ${tts.engine?.loaded ? '权重已加载' : '首次合成时才加载权重'}`;
    }
    return 'macOS 系统日语语音：无需模型、零显存，秒出';
  });
  const selectedMeta = $derived.by(() => {
    if (!selectedTts) return '音色读取中…';
    if (selectedTts.kind === 'clone') {
      const duration = selectedTts.duration
        ? `${selectedTts.duration.toFixed(1)}s 参考`
        : '参考音频';
      return `${duration} · ${voiceSourceLabel(selectedTts.source)} · 音量已对齐`;
    }
    return 'macOS 内置 · 音量已对齐';
  });
  const playingThis = $derived(tts.playing && tts.index === play.selected);
  const loadingThis = $derived(tts.loading && tts.index === play.selected);

  function openManage() {
    if (!selectedTts || selectedTts.kind !== 'clone') return;
    ttsName = selectedTts.name;
    ttsRefText = selectedTts.ref_text || '';
    uploadDraft = null;
    extractDraft = null;
    ttsLibrary = false;
    ttsManage = !ttsManage;
  }

  function cancelPanels() {
    ttsManage = false;
    uploadDraft = null;
    extractDraft = null;
  }

  /** 上次上传参考音频的目录 → 当前视频所在目录 → 系统音乐目录。 */
  function lastAudioDir(): string {
    try {
      const saved = localStorage.getItem('kikusub.lastAudioDir') || '';
      if (saved) return saved;
    } catch {
      /* localStorage 不可用时直接走视频目录 */
    }
    const mediaPath = app.media?.path || '';
    if (mediaPath.includes('/')) return mediaPath.slice(0, mediaPath.lastIndexOf('/'));
    return '';
  }

  function voiceSourceLabel(source: Record<string, unknown> | undefined): string {
    const kind = String(source?.kind || '');
    if (kind === 'cue') return '视频截取';
    if (kind === 'upload') return '上传';
    return '克隆';
  }

  /** ``say`` 的日语语音名常带「(日语（日本）)」后缀；下拉框里只留可读名。 */
  function ttsDisplayName(voice: { name: string; kind: string }): string {
    if (voice.kind !== 'system') return voice.name;
    return voice.name.replace(/\s*[（(].*[）)]\s*$/, '').trim() || voice.name;
  }

  async function saveManage() {
    if (!selectedTts) return;
    ttsSaving = true;
    try {
      if (ttsName.trim() && ttsName.trim() !== selectedTts.name) {
        await renameTtsVoice(selectedTts.id, ttsName.trim());
      }
      if (ttsRefText.trim() !== (selectedTts.ref_text || '').trim()) {
        await updateTtsRefText(selectedTts.id, ttsRefText.trim());
      }
      ttsManage = false;
    } catch (err) {
      toast(`保存音色失败：${(err as Error).message}`, 'error');
    } finally {
      ttsSaving = false;
    }
  }

  async function removeManagedVoice() {
    if (!selectedTts) return;
    if (!window.confirm(`删除音色「${selectedTts.name}」？参考音频会一起删掉。`)) return;
    try {
      await deleteTtsVoice(selectedTts.id);
      if (tts.defaultVoiceId === selectedTts.id) setTtsDefaultVoiceId('');
      ttsManage = false;
      toast('音色已删除', 'info');
    } catch (err) {
      toast(`删除音色失败：${(err as Error).message}`, 'error');
    }
  }

  async function startModelDownload() {
    if (
      !window.confirm(
        '下载 OmniVoice 克隆模型（约 3.3GB）？\n\n下载后可离线使用；系统语音兜底不受影响。',
      )
    ) {
      return;
    }
    await downloadTtsModel();
  }

  async function chooseUpload() {
    const paths = await window.kikusub.pickAudio(lastAudioDir());
    if (!paths.length) return;
    try {
      const dir = paths[0].slice(0, paths[0].lastIndexOf('/'));
      if (dir) localStorage.setItem('kikusub.lastAudioDir', dir);
    } catch {
      /* 记不住目录不影响上传 */
    }
    ttsManage = false;
    extractDraft = null;
    ttsLibrary = false;
    if (paths.length === 1) {
      const base = paths[0].split('/').pop()?.replace(/\.[^.]+$/, '') || '新音色';
      uploadDraft = { path: paths[0], name: base, refText: '' };
      return;
    }
    // OmniVoice 一次只吃一段参考音频；多选就是一次建多个独立音色。
    const picked = paths.slice(0, 8);
    if (paths.length > 8) toast('一次最多处理 8 段音频，其余已忽略', 'warn');
    ttsSaving = true;
    batch = { done: 0, total: picked.length, name: '' };
    try {
      const created = await uploadTtsVoices(picked, (done, total, name) => {
        batch = { done, total, name };
      });
      toast(`已保存 ${created.length} 个克隆音色，可在「音色库」里复用`, 'info');
    } catch (err) {
      toast(`上传参考音频失败：${(err as Error).message}`, 'error');
    } finally {
      ttsSaving = false;
      batch = null;
    }
  }

  function openExtract() {
    const index = play.selected;
    const current = app.cues[index];
    if (!app.media) {
      toast('还没有导入视频，无法截取音轨', 'warn');
      return;
    }
    if (!current) {
      toast('先在字幕表里选中一句，再截取它的声音', 'warn');
      return;
    }
    ttsManage = false;
    uploadDraft = null;
    ttsLibrary = false;
    extractDraft = {
      index,
      name: `角色 ${tts.custom.length + 1}`,
      refText: current.text,
    };
  }

  async function confirmExtract() {
    if (!extractDraft) return;
    const draft = extractDraft;
    if (!draft.name.trim()) {
      toast('先给音色起个名字', 'warn');
      return;
    }
    ttsSaving = true;
    try {
      await extractTtsVoiceFromCue(draft.index, draft.name.trim(), draft.refText.trim());
      extractDraft = null;
    } catch (err) {
      toast(`截取音色失败：${(err as Error).message}`, 'error');
    } finally {
      ttsSaving = false;
    }
  }

  function openLibrary() {
    ttsManage = false;
    uploadDraft = null;
    extractDraft = null;
    ttsLibrary = !ttsLibrary;
  }

  function useLibraryVoice(id: string) {
    setTtsVoiceId(id);
    ttsLibrary = false;
  }

  async function previewLibraryVoice(id: string) {
    setTtsVoiceId(id);
    await previewTtsVoice();
  }

  function manageLibraryVoice(id: string) {
    setTtsVoiceId(id);
    const voice = tts.custom.find((item) => item.id === id);
    if (!voice) return;
    ttsName = voice.name;
    ttsRefText = voice.ref_text || '';
    uploadDraft = null;
    extractDraft = null;
    ttsLibrary = false;
    ttsManage = true;
  }

  async function removeLibraryVoice(id: string, name: string) {
    if (!window.confirm(`删除音色「${name}」？参考音频会一起删掉。`)) return;
    try {
      await deleteTtsVoice(id);
      if (tts.defaultVoiceId === id) setTtsDefaultVoiceId('');
      toast('音色已删除', 'info');
    } catch (err) {
      toast(`删除音色失败：${(err as Error).message}`, 'error');
    }
  }

  function makeDefaultVoice(id: string, name: string) {
    setTtsDefaultVoiceId(id);
    toast(`默认朗读音色已设为「${name}」`);
  }

  function openVoicesDir() {
    if (!tts.voicesDir) {
      toast('还没有音色目录，先保存一个音色', 'warn');
      return;
    }
    void window.kikusub.openPath(tts.voicesDir);
  }

  async function confirmUpload() {
    if (!uploadDraft) return;
    const draft = uploadDraft;
    if (!draft.name.trim()) {
      toast('先给音色起个名字', 'warn');
      return;
    }
    ttsSaving = true;
    try {
      await uploadTtsVoice(draft.name.trim(), draft.path, draft.refText.trim());
      uploadDraft = null;
    } catch (err) {
      toast(`上传参考音频失败：${(err as Error).message}`, 'error');
    } finally {
      ttsSaving = false;
    }
  }

  const trackLangs = $derived(Object.keys(app.translations).sort());
  const hasTrack = $derived(Boolean(app.translations[app.trackLang]));
  const staleCount = $derived(staleTranslationCount());
  const exportNeedsTrack = $derived(exportTrack !== 'source');

  /** 进入核对屏 / 换片时刷新工作草稿状态（是否存在、多少条、最后写入时间）。 */
  $effect(() => {
    void app.media?.id;
    if (app.connected && app.media) {
      void refreshDraftInfo();
      void loadTranslations();
      void loadTtsVoices();
    }
  });

  // 换一条字幕就停掉上一句的 TTS：否则点下一句时上一句还在念，没法对照
  $effect(() => {
    void play.selected;
    stopTts();
  });

  // 右键「添加字幕」后把光标直接放进文本框，用户不用再点一下。
  // 只在 nonce **变化**时聚焦：Inspector 切页重挂载时如果直接读旧 nonce，
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

  const draftLabel = $derived.by(() => {
    if (reviewDraft.saving) return '正在暂存…';
    if (!reviewDraft.exists) return '尚未暂存';
    const when = new Date(reviewDraft.saved_at * 1000).toLocaleString('zh-CN', {
      month: 'numeric',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
      hour12: false,
    });
    return `上次暂存 ${when} · ${reviewDraft.count} 条`;
  });

  async function doExport() {
    if (exporting) return;
    exporting = true;
    try {
      // 译文/双语导出必须带语种；没有对应轨时按钮本来就是禁用的
      await exportCues(exportFormat, {
        track: exportTrack as TrackMode,
        lang: exportTrack === 'source' ? '' : app.trackLang,
      });
    } finally {
      exporting = false;
    }
  }

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

<aside class="inspector" class:hidden={!app.inspectorOpen}>
  <div class="insp-tabs" role="tablist" aria-label="右侧面板">
    <button
      class="insp-tab"
      class:on={app.inspectorTab === 'cue'}
      role="tab"
      aria-selected={app.inspectorTab === 'cue'}
      onclick={() => setInspectorTab('cue')}
    >当前条目</button>
    <button
      class="insp-tab"
      class:on={app.inspectorTab === 'qa'}
      role="tab"
      aria-selected={app.inspectorTab === 'qa'}
      onclick={() => setInspectorTab('qa')}
      title="质检待核队列"
    >
      质检待核
      {#if qaPending}<b>{qaPending}</b>{/if}
    </button>
    <button
      class="insp-tab"
      class:on={app.inspectorTab === 'chapters'}
      role="tab"
      aria-selected={app.inspectorTab === 'chapters'}
      onclick={() => setInspectorTab('chapters')}
      title="章节与时刻点标记（会写入导出容器）"
    >
      章节
      {#if chapterCount()}<b>{chapterCount()}</b>{/if}
    </button>
    <div class="tabs-spacer"></div>
    {#if app.inspectorTab === 'cue'}
      <b class="tabs-index">{app.cues.length ? `#${play.selected + 1}` : '—'}</b>
    {/if}
    <button
      class="ins-close"
      onclick={() => (app.inspectorOpen = false)}
      title="收起检查器（Esc）"
      aria-label="收起检查器"
    >
      <Icon name="close" size={11} />
    </button>
  </div>
  {#if app.inspectorTab === 'chapters'}
    <ChaptersPanel />
  {:else if app.inspectorTab === 'cue'}
  <div class="ins-scroll">
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
  {:else}
    <div class="track-meta empty">
      <span>还没有译文字幕</span>
      <button
        class="link"
        onclick={() => importTranslationFromExport()}
        disabled={!app.cues.length}
        title="选择与当前原文逐条对齐的译文 SRT / VTT"
      >
        导入译文…
      </button>
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
    <div class="actions">
      <button
        class="btn"
        onclick={() => previewRange(cue.start, cue.end)}
        title="试听原片这一句的原声（在下方对照两个引擎的 TTS）"
      >
        <Icon name="play" size={11} />试听原声
      </button>
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
    <SecondOpinionCard index={play.selected} text={cue.text} />
  {/if}

  <div class="tts-block">
    <div class="tts-head">
      <b>TTS 对照</b>
      <span class="tts-engine {engineTone}" title={engineTitle}>
        <i class="tts-status-dot" aria-hidden="true"></i>{engineLabel}
      </span>
    </div>

    <div class="tts-card">
      <button
        class="tts-play"
        class:playing={playingThis}
        onclick={() => speakCue(play.selected)}
        disabled={!cue || tts.loading || (selectedTts?.kind === 'clone' && !cloneEngineReady())}
        title={!cue
          ? '先选中一条字幕'
          : selectedTts?.kind === 'clone' && !cloneEngineReady()
            ? '克隆模型还没下载，先下载模型或改用系统语音'
            : playingThis
              ? '再点一次停止'
              : '朗读这句字幕'}
        aria-label={playingThis ? '停止朗读' : '朗读当前句'}
      >
        {#if loadingThis}
          <span class="spin"></span><span>生成中</span>
        {:else if playingThis}
          <Icon name="stop" size={11} /><span>停止</span>
        {:else}
          <Icon name="play" size={11} /><span>朗读</span>
        {/if}
      </button>

      <div class="tts-main">
        <div class="tts-row">
          <div
            class="tts-select-wrap voice"
            title={selectedTts
              ? `音色：${selectedTts.name}（系统语音零显存，克隆音色按角色声线朗读）`
              : '音色：系统语音零显存，克隆音色按角色声线朗读'}
          >
            <select
              class="tts-select"
              value={tts.voiceId}
              aria-label="朗读音色"
              onchange={(e) => {
                setTtsVoiceId(e.currentTarget.value);
                ttsManage = false;
              }}
            >
              {#if tts.custom.length}
                <optgroup label="克隆音色">
                  {#each tts.custom as voice (voice.id)}
                    <option value={voice.id}>{voice.name}</option>
                  {/each}
                </optgroup>
              {/if}
              <optgroup label="系统音色 · 零显存">
                {#each tts.system as voice (voice.id)}
                  <option value={voice.id}>{ttsDisplayName(voice)}</option>
                {/each}
              </optgroup>
              {#if !tts.system.length && !tts.custom.length}
                <option value="">{tts.loaded ? '无可用语音' : '读取中…'}</option>
              {/if}
            </select>
            <Icon name="chevron-down" size={10} />
          </div>
          <div class="tts-select-wrap rate" title="语速">
            <select
              class="tts-select"
              value={tts.speed}
              aria-label="朗读语速"
              onchange={(e) => setTtsSpeed(Number(e.currentTarget.value))}
            >
              <option value={0.8}>0.8×</option>
              <option value={1}>1.0×</option>
              <option value={1.2}>1.2×</option>
            </select>
            <Icon name="chevron-down" size={10} />
          </div>
        </div>
        <div class="tts-meta" title={selectedMeta}>{selectedMeta}</div>
      </div>
    </div>

    <div class="tts-actions">
      <button
        class="tts-action"
        onclick={chooseUpload}
        title="上传 3–10 秒参考音频（单人、干声、无背景音乐）；可一次选多段，每段建一个音色"
      >
        <Icon name="export" size={12} /><span>上传</span>
      </button>
      <button
        class="tts-action"
        onclick={openExtract}
        disabled={!cue || !app.media}
        title={!app.media
          ? '先导入视频'
          : !cue
            ? '先选中一句字幕'
            : '用当前这句的原声建立克隆音色；建议 3–10 秒、单人干声'}
      >
        <Icon name="mic" size={12} /><span>截取</span>
      </button>
      <button
        class="tts-action"
        class:on={ttsLibrary}
        onclick={openLibrary}
        title="保存过的克隆音色都在这里"
      >
        <Icon name="folder" size={12} /><span>音色库</span>
        {#if tts.custom.length}<b class="tts-count">{tts.custom.length}</b>{/if}
      </button>
      {#if selectedTts?.kind === 'clone' && !ttsLibrary}
        <button
          class="tts-action"
          class:on={ttsManage}
          onclick={openManage}
          title="重命名 / 修改参考文本 / 删除"
        >
          <Icon name="gear" size={12} /><span>管理</span>
        </button>
      {/if}
    </div>

    {#if downloading}
      <div
        class="tts-progress-card"
        role="progressbar"
        aria-label="OmniVoice 模型下载进度"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={tts.download?.percent ?? 0}
      >
        <div class="tts-progress-head">
          <span>{tts.download?.stage || '正在下载…'}</span>
          <b>{tts.download?.percent ?? 0}%</b>
        </div>
        <div class="tts-progress"><div style="width:{tts.download?.percent ?? 0}%"></div></div>
      </div>
    {:else if !cloneEngineReady()}
      <button
        class="tts-download"
        onclick={startModelDownload}
        title="下载 OmniVoice 权重（约 3.3GB），之后可用参考音频克隆声线"
      >
        <Icon name="export" size={12} />
        <span>下载克隆模型</span>
        <em>约 3.3 GB</em>
      </button>
    {/if}

    {#if batch}
      <div class="tts-batch">
        正在创建音色 {batch.done}/{batch.total}{batch.name ? ` · ${batch.name}` : ''}
      </div>
    {/if}

    {#if ttsLibrary}
      <div class="voice-panel">
        <div class="vp-head">
          <span>音色库</span>
          <button class="vp-link" onclick={openVoicesDir} title="在访达中打开音色目录">
            <Icon name="folder" size={11} />打开文件夹
          </button>
        </div>
        {#if !tts.custom.length}
          <p class="vp-hint">
            还没有保存的克隆音色。参考音频 3–10 秒、单人干声效果最好；可以上传，或选中一句后点「截取」。
          </p>
        {:else}
          <div class="voice-list">
            {#each tts.custom as voice (voice.id)}
              <div class="voice-row" class:active={voice.id === tts.voiceId}>
                <button
                  class="voice-pick"
                  onclick={() => useLibraryVoice(voice.id)}
                  title="使用这个音色"
                >
                  <span class="voice-name">{voice.name}</span>
                  <span class="voice-meta">
                    {voice.duration ? `${voice.duration.toFixed(1)}s` : '—'} · {voiceSourceLabel(
                      voice.source,
                    )}
                  </span>
                </button>
                <div class="voice-acts">
                  <button
                    class="voice-act"
                    onclick={() => previewLibraryVoice(voice.id)}
                    disabled={tts.loading}
                    title="试听"
                    aria-label={`试听「${voice.name}」`}
                  >
                    <Icon name="speaker" size={11} />
                  </button>
                  <button
                    class="voice-act star"
                    class:on={tts.defaultVoiceId === voice.id}
                    onclick={() => makeDefaultVoice(voice.id, voice.name)}
                    title={tts.defaultVoiceId === voice.id ? '已是默认音色' : '设为默认音色'}
                    aria-label={`把「${voice.name}」设为默认`}
                  >
                    <Icon name="star" size={11} />
                  </button>
                  <button
                    class="voice-act"
                    onclick={() => manageLibraryVoice(voice.id)}
                    title="重命名 / 参考文本 / 删除"
                    aria-label={`管理「${voice.name}」`}
                  >
                    <Icon name="gear" size={11} />
                  </button>
                </div>
              </div>
            {/each}
          </div>
        {/if}
      </div>
    {/if}

    {#if ttsManage && selectedTts?.kind === 'clone'}
      <div class="voice-panel">
        <div class="vp-head">
          <span>{selectedTts.duration ? `${selectedTts.duration.toFixed(1)}s 参考音频` : '参考音频'}</span>
          <button class="vp-link" onclick={previewTtsVoice} disabled={tts.loading}>
            <Icon name="speaker" size={11} />{tts.loading && tts.index === -1 ? '生成中…' : '试听'}
          </button>
        </div>
        <label class="vp-field">
          <span>音色名</span>
          <input bind:value={ttsName} maxlength="40" placeholder="角色名" />
        </label>
        <label class="vp-field">
          <span>参考音频日文</span>
          <textarea
            bind:value={ttsRefText}
            rows="2"
            placeholder="这段参考音频的台词，用于对齐声线（可留空）"
          ></textarea>
        </label>
        <div class="vp-actions">
          <button class="btn mini ghost danger" onclick={removeManagedVoice}>删除</button>
          <span class="tts-spacer"></span>
          <button class="btn mini" onclick={cancelPanels}>取消</button>
          <button class="btn mini primary" onclick={saveManage} disabled={ttsSaving}>
            {ttsSaving ? '保存中…' : '保存'}
          </button>
        </div>
      </div>
    {/if}

    {#if uploadDraft}
      <div class="voice-panel">
        <div class="vp-head">
          <span title={uploadDraft.path}>{uploadDraft.path.split('/').pop()}</span>
        </div>
        <label class="vp-field">
          <span>音色名</span>
          <input bind:value={uploadDraft.name} maxlength="40" placeholder="角色名" />
        </label>
        <label class="vp-field">
          <span>参考音频日文</span>
          <textarea
            bind:value={uploadDraft.refText}
            rows="2"
            placeholder="这段参考音频的台词，用于对齐声线（可留空）"
          ></textarea>
        </label>
        <p class="vp-hint">单人干声效果最好；会自动去首尾静音并统一响度，超过 10 秒只保留前 10 秒。</p>
        <div class="vp-actions">
          <button class="btn mini ghost" onclick={() => (uploadDraft = null)}>取消</button>
          <span class="tts-spacer"></span>
          <button class="btn mini primary" onclick={confirmUpload} disabled={ttsSaving}>
            {ttsSaving ? '保存中…' : '保存音色'}
          </button>
        </div>
      </div>
    {/if}

    {#if extractDraft}
      {@const ec = app.cues[extractDraft.index]}
      <div class="voice-panel">
        <div class="vp-head">
          <span>
            {ec ? `${ec.start.toFixed(1)}–${ec.end.toFixed(1)}s` : '当前句'} 的原声
          </span>
        </div>
        <label class="vp-field">
          <span>音色名</span>
          <input bind:value={extractDraft.name} maxlength="40" placeholder="角色名" />
        </label>
        <label class="vp-field">
          <span>参考音频日文</span>
          <textarea
            bind:value={extractDraft.refText}
            rows="2"
            placeholder="这段参考音频的台词，用于对齐声线（可留空）"
          ></textarea>
        </label>
        <p class="vp-hint">单人干声效果最好；从当前音轨精准切片，前后留 0.2 秒上下文，并统一参考响度。</p>
        <div class="vp-actions">
          <button class="btn mini ghost" onclick={() => (extractDraft = null)}>取消</button>
          <span class="tts-spacer"></span>
          <button class="btn mini primary" onclick={confirmExtract} disabled={ttsSaving}>
            {ttsSaving ? '截取中…' : '建立音色'}
          </button>
        </div>
      </div>
    {/if}
  </div>

  {#if imported}
    <!--
      换了一版字幕（导入 / 恢复草稿）后，转写报告与质检队列属于另一版内容。
      这里不再展示它们的数字，改用当前字幕自己的来源与条数，避免“面板说 A、
      核对台在用 B”。
    -->
    <div class="meta-sec">
      <div class="meta-h">当前字幕</div>
      <div class="source-row">
        <span class="source-badge">{sourceLabel}</span>
        <span class="source-name" title={sourcePath || outputName}>{outputName}</span>
      </div>
      <p class="meta-note">
        质检速览与生效参数属于这次转写，和当前导入的字幕不是同一版；整片转写后会重新生成。
      </p>
      {#if app.media}
        <button class="meta-link" onclick={() => setView('transcribe')}>
          去转写
          <Icon name="chevron-right" size={10} />
        </button>
      {/if}
    </div>
  {:else if quality}
    <div class="meta-sec">
      <div class="meta-h">质检速览</div>
      <div class="chips">
        <span
          class="chip"
          class:ok={(quality.coverage ?? 0) === 0}
          class:warn={(quality.coverage ?? 0) > 0}
        >
          漏检 <b>{quality.coverage ?? 0}</b>
        </span>
        <span
          class="chip"
          class:ok={(quality.low_confidence ?? 0) === 0}
          class:warn={(quality.low_confidence ?? 0) > 0}
        >
          低置信 <b>{quality.low_confidence ?? 0}</b>
        </span>
      </div>
    </div>
  {/if}

  {#if !imported}
    <div class="meta-sec">
      <div class="meta-h">生效参数</div>
      {#if report?.params?.length}
        {#each report.params.slice(0, 6) as row (row.label)}
          <div class="kv"><span class="k">{row.label}</span><span class="v">{row.value}</span></div>
        {/each}
      {:else}
        <div class="kv"><span class="k">设备</span><span class="v mono">{app.config?.device ?? '—'}</span></div>
        <div class="kv"><span class="k">引擎</span><span class="v">{app.config?.engines?.find((e) => e.key === app.engine)?.label ?? '—'}</span></div>
        <div class="kv"><span class="k">版本</span><span class="v mono">v{app.config?.version ?? '—'}</span></div>
        <div class="kv"><span class="k">参数</span><span class="v muted">转写后可见</span></div>
      {/if}
      {#if reportStale}
        <p class="meta-note">报告属于另一次转写，已隐藏；重新整片转写后会恢复。</p>
      {/if}
    </div>
  {/if}

  <div class="meta-sec">
    <div class="meta-h">输出</div>
    <div class="kv">
      <span class="k">文件</span>
      <span class="v mono" title={sourcePath || outputName}>{outputName}</span>
    </div>
    <div class="kv"><span class="k">条数</span><span class="v">{app.cues.length} 条</span></div>
    <div class="kv">
      <span class="k">字符</span>
      <span class="v">{app.cues.reduce((n, c) => n + c.text.length, 0)} 字</span>
    </div>
  </div>

  </div>

  <!--
    常驻保存区：核对期间总是在右侧栏底部可见。
    「暂存」= 写工作草稿（运行数据目录，防丢，不覆盖交付文件）；
    「导出」= 写设置里的导出文件夹，不依赖「详情与导出」是否有任务报告。
  -->
  <div class="save-dock">
    <div class="sd-head">
      <span class="sd-title">保存</span>
      <span class="sd-state" class:warn={!reviewDraft.exists}>{draftLabel}</span>
    </div>
    <div class="sd-row">
      <button
        class="btn ghost sd-save"
        onclick={() => saveDraft()}
        disabled={!app.cues.length || reviewDraft.saving}
        title={reviewDraft.path
          ? `把当前全部字幕写入工作草稿 ${reviewDraft.path}，不会覆盖导出文件`
          : '把当前核对台的全部字幕写入工作草稿，防止应用关闭或崩溃后丢失'}
      >
        <Icon name="save" size={11} />{reviewDraft.saving ? '暂存中' : '暂存'}
      </button>
      <select
        class="sd-fmt"
        bind:value={exportTrack}
        disabled={exporting}
        title="导出内容：原文 / 仅译文 / 双语（同一时间轴下原文、译文各一条）"
      >
        <option value="source">原文</option>
        <option value="target" disabled={!hasTrack}>译文</option>
        <option value="both" disabled={!hasTrack}>双语</option>
      </select>
      <select
        class="sd-fmt"
        bind:value={exportFormat}
        disabled={exporting}
        title="导出格式"
      >
        <option value="SRT">SRT</option>
        <option value="VTT">VTT</option>
        <option value="TXT">TXT</option>
      </select>
      <button
        class="btn primary sd-export"
        onclick={doExport}
        disabled={!app.cues.length || exporting || (exportNeedsTrack && !hasTrack)}
        title={app.config?.export_dir
          ? `把核对台当前时间轴导出到 ${app.config.export_dir}`
          : '把核对台当前时间轴导出到导出文件夹'}
      >
        <Icon name="export" size={11} />{exporting ? '导出中' : '导出字幕'}
      </button>
    </div>
    {#if reviewDraft.exists || app.lastExportPath}
      <div class="sd-foot">
        {#if reviewDraft.exists}
          <button
            class="sd-link"
            onclick={restoreDraft}
            disabled={reviewDraft.restoring}
            title="用工作草稿覆盖核对台（压入撤回栈，⌘Z 可一步退回）"
          >
            {reviewDraft.restoring ? '正在恢复…' : '恢复上次暂存'}
          </button>
        {/if}
        {#if app.lastExportPath}
          <button
            class="sd-link"
            onclick={() => window.kikusub.revealInFinder(app.lastExportPath)}
            title={app.lastExportPath}
          >
            最近导出：{app.lastExportPath.split('/').pop()}
          </button>
        {/if}
      </div>
    {/if}
  </div>
  {:else}
    <QaPanel mode="docked" />
  {/if}
</aside>

<style>
  .inspector {
    width: 348px;
    flex: 0 0 348px;
    background: var(--paper);
    border-left: 1px solid var(--line-2);
    overflow: hidden;
    display: flex;
    flex-direction: column;
    transition: width var(--dur-panel) var(--ease), flex-basis var(--dur-panel) var(--ease),
      opacity 140ms var(--ease);
  }
  .ins-scroll {
    flex: 1;
    min-height: 0;
    overflow-y: auto;
    padding: var(--sp-3) var(--sp-5) var(--sp-4);
  }
  .insp-tabs {
    flex: 0 0 auto;
    display: flex;
    align-items: center;
    gap: 2px;
    min-height: 40px;
    padding: 0 var(--sp-3);
    border-bottom: 1px solid var(--line-2);
    background: var(--paper);
  }
  .insp-tab {
    appearance: none;
    border: 0;
    background: transparent;
    color: var(--ink-3);
    font: inherit;
    font-size: 12.5px;
    line-height: 16px;
    height: 28px;
    padding: 0 9px;
    border-radius: 6px;
    display: inline-flex;
    align-items: center;
    gap: 5px;
    white-space: nowrap;
  }
  .insp-tab:hover {
    background: var(--fill);
    color: var(--ink-2);
  }
  .insp-tab.on {
    background: var(--accent-soft);
    color: var(--accent);
    font-weight: 600;
  }
  .insp-tab b {
    min-width: 16px;
    height: 15px;
    padding: 0 var(--sp-1);
    border-radius: 999px;
    background: var(--accent);
    color: var(--on-accent);
    display: grid;
    place-items: center;
    font-size: 10.5px;
    font-weight: 600;
    font-variant-numeric: tabular-nums;
  }
  .tabs-spacer {
    flex: 1;
  }
  .tabs-index {
    font-family: var(--font-mono);
    font-weight: 400;
    font-size: 12px;
    color: var(--ink-3);
    margin-right: 2px;
  }
  /* 只有紧凑模式的抽屉才需要显式的关闭入口（桌面由工具栏开关控制） */
  .ins-close {
    display: none;
  }

  .display-row {
    display: flex;
    align-items: center;
    gap: var(--sp-2);
    /* 页签底边已经是一条分隔线，这里不再叠一层 12px 的空白。 */
    margin-top: 0;
  }
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
  .lang-sel {
    margin-left: auto;
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

  /* 当前句：全屏最大的字，也是唯一带蓝左线的卡片 */
  .cue-card {
    margin-top: var(--sp-4);
    background: var(--raise);
    border: 1px solid var(--line-2);
    border-left: 2px solid var(--accent);
    border-radius: 8px;
    padding: var(--sp-4);
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
    gap: var(--sp-2);
    margin-top: var(--sp-4);
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
    padding: var(--sp-2) var(--sp-3);
    border: 1px solid var(--line-2);
    border-radius: 6px;
    background: var(--raise);
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
  .tts-block {
    margin-top: var(--sp-4);
    padding: var(--sp-3) 0 0;
    border-top: 1px solid var(--line-2);
    display: flex;
    flex-direction: column;
    gap: var(--sp-2);
  }
  .tts-head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--sp-2);
    min-width: 0;
  }
  .tts-head b {
    flex: 0 0 auto;
    font-size: 12px;
    line-height: 16px;
    font-weight: 600;
    color: var(--ink-2);
  }
  .tts-engine {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    min-width: 0;
    height: 20px;
    padding: 0 7px;
    border-radius: 999px;
    background: var(--fill);
    color: var(--ink-3);
    font-size: 10.5px;
    line-height: 12px;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .tts-status-dot {
    flex: none;
    width: 5px;
    height: 5px;
    border-radius: 50%;
    background: var(--ink-3);
  }
  .tts-engine.ready .tts-status-dot {
    background: var(--success);
  }
  .tts-engine.system .tts-status-dot {
    background: var(--accent);
  }
  .tts-engine.warn {
    color: var(--warn);
    background: var(--warn-soft);
  }
  .tts-engine.warn .tts-status-dot {
    background: var(--warn);
  }
  .tts-card {
    display: flex;
    align-items: center;
    gap: 9px;
    padding: 9px 9px var(--sp-2);
    border: 1px solid var(--line-2);
    border-radius: 8px;
    background: var(--raise);
    box-shadow: 0 1px 1px rgba(27, 39, 64, 0.03);
  }
  .tts-play {
    position: relative;
    flex: 0 0 auto;
    min-width: 62px;
    height: 30px;
    padding: 0 10px;
    border: 0;
    border-radius: 8px;
    background: var(--btn-primary-bg);
    color: var(--on-accent);
    display: inline-flex;
    align-items: center;
    justify-content: center;
    gap: 5px;
    font: inherit;
    font-size: 12px;
    font-weight: 600;
    line-height: 1;
    white-space: nowrap;
    cursor: pointer;
    box-shadow: var(--shadow-btn);
    transition: background var(--dur-fast) var(--ease), transform var(--dur-fast) var(--ease);
  }
  .tts-play:hover:not(:disabled) {
    background: var(--btn-primary-hover);
    transform: translateY(-0.5px);
  }
  .tts-play:active:not(:disabled) {
    transform: scale(0.97);
  }
  .tts-play:disabled {
    background: var(--fill-strong);
    color: var(--text-3);
    cursor: default;
    box-shadow: none;
  }
  .tts-play:focus-visible,
  .tts-action:focus-visible,
  .tts-download:focus-visible,
  .vp-link:focus-visible,
  .voice-act:focus-visible {
    outline: 2px solid var(--accent-ring);
    outline-offset: 2px;
  }
  .tts-play .spin {
    width: 11px;
    height: 11px;
    border-width: 1.6px;
  }
  .tts-play.playing::after {
    content: '';
    position: absolute;
    inset: -3px;
    border-radius: 8px;
    border: 1.5px solid var(--accent);
    animation: tts-ping 1.6s var(--ease) infinite;
    pointer-events: none;
  }
  @keyframes tts-ping {
    0% {
      transform: scale(0.94);
      opacity: 0.45;
    }
    70%,
    100% {
      transform: scale(1.1);
      opacity: 0;
    }
  }
  .tts-main {
    flex: 1;
    min-width: 0;
    display: flex;
    flex-direction: column;
    gap: 3px;
  }
  .tts-row {
    display: flex;
    gap: 6px;
    min-width: 0;
  }
  .tts-select-wrap {
    position: relative;
    display: flex;
    align-items: center;
    min-width: 0;
    height: 26px;
    border-radius: 6px;
    background: var(--fill);
  }
  .tts-select-wrap.voice {
    flex: 1 1 auto;
  }
  .tts-select-wrap.rate {
    flex: 0 0 64px;
  }
  .tts-select {
    appearance: none;
    -webkit-appearance: none;
    width: 100%;
    height: 100%;
    min-width: 0;
    padding: 0 18px 0 7px;
    border: 0;
    border-radius: 6px;
    background: transparent;
    color: var(--ink);
    font: inherit;
    font-size: 12px;
    line-height: 16px;
    cursor: pointer;
    text-overflow: ellipsis;
  }
  .tts-select:focus-visible {
    outline: 2px solid var(--accent-ring);
    outline-offset: 1px;
  }
  .tts-select-wrap > svg {
    position: absolute;
    right: 6px;
    pointer-events: none;
    color: var(--ink-3);
  }
  .tts-meta {
    padding-left: 2px;
    font-size: 10.5px;
    line-height: 13px;
    color: var(--text-3);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .tts-actions {
    display: flex;
    align-items: center;
    gap: 5px;
    flex-wrap: wrap;
  }
  .tts-action {
    display: inline-flex;
    align-items: center;
    gap: var(--sp-1);
    height: 24px;
    padding: 0 var(--sp-2);
    border: 1px solid var(--line-2);
    border-radius: 6px;
    background: transparent;
    color: var(--ink-2);
    font: inherit;
    font-size: 11.5px;
    line-height: 1;
    white-space: nowrap;
    cursor: pointer;
    transition: color var(--dur-fast) var(--ease), border-color var(--dur-fast) var(--ease),
      background var(--dur-fast) var(--ease);
  }
  .tts-action:hover:not(:disabled) {
    color: var(--accent-hover);
    border-color: var(--accent-line);
    background: var(--accent-soft);
  }
  .tts-action.on {
    color: var(--accent-hover);
    border-color: var(--accent-line);
    background: var(--accent-soft);
  }
  .tts-action:disabled {
    opacity: 0.55;
    color: var(--text-3);
    cursor: default;
  }
  .tts-count {
    display: inline-grid;
    place-items: center;
    min-width: 14px;
    height: 14px;
    padding: 0 var(--sp-1);
    border-radius: 999px;
    background: var(--accent-soft);
    color: var(--accent-hover);
    font-size: 10px;
    font-weight: 600;
    line-height: 1;
  }
  .tts-download {
    display: flex;
    align-items: center;
    gap: 6px;
    height: 32px;
    padding: 0 10px;
    border: 0;
    border-radius: 8px;
    background: var(--btn-primary-bg);
    color: var(--on-accent);
    font: inherit;
    font-size: 12px;
    font-weight: 600;
    cursor: pointer;
    box-shadow: var(--shadow-btn);
    transition: background var(--dur-fast) var(--ease);
  }
  .tts-download:hover {
    background: var(--btn-primary-hover);
  }
  .tts-download em {
    margin-left: auto;
    font-style: normal;
    font-size: 10.5px;
    font-weight: 400;
    color: color-mix(in srgb, var(--on-accent) 78%, transparent);
  }
  .tts-progress-card {
    display: flex;
    flex-direction: column;
    gap: 5px;
    padding: var(--sp-2) 9px;
    border: 1px solid var(--line-2);
    border-radius: 8px;
    background: var(--fill);
  }
  .tts-progress-head {
    display: flex;
    justify-content: space-between;
    gap: var(--sp-2);
    font-size: 10.5px;
    line-height: 13px;
    color: var(--text-3);
  }
  .tts-progress-head b {
    color: var(--ink-2);
    font-weight: 600;
    font-variant-numeric: tabular-nums;
  }
  .tts-progress {
    height: 4px;
    border-radius: 999px;
    background: var(--line-2);
    overflow: hidden;
  }
  .tts-progress > div {
    height: 100%;
    border-radius: inherit;
    background: var(--accent);
    transition: width 240ms var(--ease);
  }
  .tts-batch {
    font-size: 10.5px;
    line-height: 14px;
    color: var(--text-3);
  }
  .tts-spacer {
    flex: 1;
  }
  .voice-panel {
    margin: 2px 0 var(--sp-1);
    padding: 9px;
    border: 1px solid var(--line-2);
    border-radius: 8px;
    background: var(--fill);
    display: flex;
    flex-direction: column;
    gap: var(--sp-2);
    animation: tts-panel-in 160ms var(--ease);
  }
  @keyframes tts-panel-in {
    from {
      opacity: 0;
      transform: translateY(-3px);
    }
    to {
      opacity: 1;
      transform: none;
    }
  }
  .vp-head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--sp-2);
    font-size: 11px;
    line-height: 15px;
    color: var(--text-3);
    min-width: 0;
  }
  .vp-head > span {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .vp-link {
    appearance: none;
    flex: none;
    display: inline-flex;
    align-items: center;
    gap: var(--sp-1);
    padding: 1px 0;
    border: 0;
    background: transparent;
    color: var(--accent-hover);
    font: inherit;
    font-size: 11px;
    line-height: 15px;
    cursor: pointer;
  }
  .vp-link:hover:not(:disabled) {
    text-decoration: underline;
  }
  .vp-link:disabled {
    color: var(--text-3);
    cursor: default;
  }
  .vp-field {
    display: flex;
    flex-direction: column;
    gap: var(--sp-1);
    font-size: 10.5px;
    line-height: 14px;
    color: var(--text-3);
  }
  .vp-field input,
  .vp-field textarea {
    width: 100%;
    box-sizing: border-box;
    padding: var(--sp-1) 7px;
    border: 1px solid var(--line);
    border-radius: 6px;
    background: var(--raise);
    color: var(--ink);
    font: inherit;
    font-size: 12px;
    line-height: 16px;
    resize: vertical;
  }
  .vp-field input {
    height: 26px;
    padding-top: 0;
    padding-bottom: 0;
  }
  .vp-field input:focus,
  .vp-field textarea:focus {
    outline: 2px solid var(--accent-ring);
    outline-offset: 0;
    border-color: var(--accent-line);
  }
  .vp-actions {
    display: flex;
    align-items: center;
    gap: 6px;
  }
  .vp-actions .btn.danger {
    color: var(--danger);
  }
  .vp-hint {
    margin: 0;
    font-size: 10.5px;
    line-height: 14px;
    color: var(--text-3);
  }
  .voice-list {
    display: flex;
    flex-direction: column;
    max-height: 208px;
    overflow-y: auto;
    border: 1px solid var(--line-2);
    border-radius: 8px;
    background: var(--raise);
  }
  .voice-row {
    display: flex;
    align-items: center;
    gap: 6px;
    padding: 5px 6px 5px var(--sp-2);
    border-bottom: 1px solid var(--line-2);
  }
  .voice-row:last-child {
    border-bottom: 0;
  }
  .voice-row.active {
    background: var(--accent-soft);
  }
  .voice-row:not(.active):hover {
    background: var(--fill);
  }
  .voice-pick {
    appearance: none;
    flex: 1;
    min-width: 0;
    display: flex;
    flex-direction: column;
    align-items: flex-start;
    gap: 1px;
    padding: 1px 0;
    border: 0;
    background: transparent;
    color: inherit;
    font: inherit;
    text-align: left;
    cursor: pointer;
  }
  .voice-name {
    max-width: 100%;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    font-size: 12px;
    line-height: 16px;
    color: var(--ink-2);
  }
  .voice-row.active .voice-name {
    color: var(--accent-hover);
    font-weight: 600;
  }
  .voice-meta {
    font-size: 10px;
    line-height: 13px;
    color: var(--text-3);
    font-variant-numeric: tabular-nums;
  }
  .voice-acts {
    flex: none;
    display: flex;
    align-items: center;
    gap: 1px;
  }
  .voice-act {
    width: 22px;
    height: 22px;
    padding: 0;
    border: 0;
    border-radius: 6px;
    background: transparent;
    color: var(--ink-3);
    display: grid;
    place-items: center;
    cursor: pointer;
    transition: background var(--dur-fast) var(--ease), color var(--dur-fast) var(--ease);
  }
  .voice-act:hover:not(:disabled) {
    background: var(--fill-strong);
    color: var(--ink);
  }
  .voice-act.on {
    color: var(--accent-hover);
    background: var(--accent-soft);
  }
  .voice-act.star.on svg {
    fill: currentColor;
  }
  .voice-act:disabled {
    opacity: 0.45;
    cursor: default;
  }

  .meta-sec {
    margin-top: var(--sp-3);
    padding: var(--sp-3) 0 0;
    border-top: 1px solid var(--line-2);
  }
  .meta-h {
    font-size: 12px;
    line-height: 16px;
    font-weight: 600;
    color: var(--ink-2);
    letter-spacing: 0.01em;
    margin-bottom: 5px;
  }
  .source-row {
    display: flex;
    align-items: center;
    gap: 6px;
    min-width: 0;
    margin: 2px 0 5px;
  }
  .source-badge {
    flex: 0 0 auto;
    height: 18px;
    padding: 0 6px;
    border-radius: 4px;
    background: var(--accent-soft);
    color: var(--accent);
    font-size: 12px;
    line-height: 18px;
    font-weight: 500;
  }
  .source-name {
    min-width: 0;
    font-family: var(--font-mono);
    font-size: 12px;
    color: var(--ink-2);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .meta-note {
    margin: 6px 0 0;
    font-size: 12px;
    line-height: 17px;
    color: var(--ink-3);
  }
  .meta-link {
    appearance: none;
    border: 0;
    background: transparent;
    color: var(--accent);
    font: inherit;
    font-size: 12px;
    padding: var(--sp-1) 0 0;
    display: inline-flex;
    align-items: center;
    gap: 1px;
  }
  .meta-link:hover {
    text-decoration: underline;
  }
  .muted,
  .kv .v.muted {
    color: var(--ink-3);
    font-weight: 400;
  }

  .inspector.hidden {
    width: 0;
    flex-basis: 0;
    opacity: 0;
    overflow: hidden;
    border-left-color: transparent;
  }

  /* 常驻保存区：固定在右侧栏底部，内容单独滚动 */
  .save-dock {
    flex: 0 0 auto;
    padding: 10px var(--sp-5) var(--sp-3);
    border-top: 1px solid var(--line);
    background: var(--paper);
    box-shadow: 0 -10px 20px -18px rgba(27, 39, 64, 0.35);
    display: flex;
    flex-direction: column;
    gap: 6px;
  }
  .sd-head {
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    gap: var(--sp-2);
    min-width: 0;
  }
  .sd-title {
    font-size: 12px;
    line-height: 16px;
    font-weight: 600;
    color: var(--ink-2);
    letter-spacing: 0.02em;
    flex: 0 0 auto;
  }
  .sd-state {
    font-size: 12px;
    line-height: 16px;
    color: var(--ink-3);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .sd-state.warn {
    color: var(--warn);
  }
  .sd-row {
    display: flex;
    align-items: center;
    gap: 5px;
  }
  .sd-save {
    flex: 1;
    justify-content: center;
    min-width: 0;
  }
  .sd-fmt {
    height: 26px;
    width: 54px;
    flex: 0 0 54px;
    border-radius: 4px;
    border: 1px solid var(--line);
    background: var(--raise);
    color: var(--ink-2);
    font: inherit;
    font-size: 12px;
    padding: 0 2px 0 5px;
  }
  .sd-export {
    min-width: 64px;
    justify-content: center;
  }
  .sd-foot {
    display: flex;
    flex-direction: column;
    gap: 2px;
    min-width: 0;
  }
  .sd-link {
    appearance: none;
    border: 0;
    background: transparent;
    color: var(--accent);
    font: inherit;
    font-size: 12px;
    text-align: left;
    padding: 0;
    cursor: pointer;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .sd-link:hover:not(:disabled) {
    text-decoration: underline;
  }
  .sd-link:disabled {
    color: var(--ink-3);
  }

  .spin {
    width: 9px;
    height: 9px;
    border-radius: 50%;
    border: 1.5px solid currentColor;
    border-top-color: transparent;
    animation: spin 650ms linear infinite;
  }
  @keyframes spin {
    to {
      transform: rotate(360deg);
    }
  }

  /* 紧凑模式（≤900px）：不再占列，改成右侧抽屉。
     收起 = 平移出屏幕（不动 width，避免每次开关都触发布局）；
     遮罩与 Esc 关闭由 App.svelte 负责。 */
  @media (max-width: 900px) {
    .inspector {
      position: absolute;
      top: 0;
      right: 0;
      bottom: 0;
      width: min(348px, 92vw);
      flex: 0 0 auto;
      z-index: 20;
      border-left: 1px solid var(--line);
      box-shadow: -18px 0 46px -26px rgba(27, 39, 64, 0.5);
      transform: translateX(103%);
      transition: transform 180ms var(--ease);
      opacity: 1;
      overflow: hidden;
    }
    .inspector:not(.hidden) {
      transform: none;
    }
    .inspector.hidden {
      width: min(348px, 92vw);
      flex-basis: auto;
      opacity: 1;
      border-left-color: transparent;
      box-shadow: none;
      overflow: hidden;
      pointer-events: none;
    }
    .ins-close {
      display: grid;
      place-items: center;
      width: 22px;
      height: 22px;
      padding: 0;
      margin: -4px -4px 0 0;
      border: 0;
      border-radius: 4px;
      background: transparent;
      color: var(--ink-3);
    }
    .ins-close:hover {
      background: var(--fill);
      color: var(--ink);
    }
  }
</style>
