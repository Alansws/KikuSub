<script lang="ts">
  /**
   * 当前条目的朗读控件（TTS）：常驻一个图标按钮 + 音色下拉，其余收进按需展开的面板。
   *
   * 2026-11-21（Step 3）从 Inspector 的「TTS 对照」大卡片改过来：那张卡常驻在右栏
   * 底部，标准窗口高度下会被底部保存栏截断——用户要么滚动才看得见，要么以为没有
   * 这个功能。核对期间真正高频的只有两件事：**听这一句**、**换音色**，所以它们
   * 留在操作行里；语速、上传参考音频、从当前句截取、音色库、管理收进「⚙」面板，
   * 不占常驻高度。
   *
   * 只有一处推理入口：`speakCue()` / `previewTtsVoice()`（声音的合成、缓存、
   * 响度归一都在后端 `core/tts/`）。这里不读 AI Key，也不做云端 TTS。
   */
  import Icon from '../Icon.svelte';
  import {
    app,
    cloneEngineReady,
    deleteTtsVoice,
    downloadTtsModel,
    extractTtsVoiceFromCue,
    play,
    previewTtsVoice,
    renameTtsVoice,
    setTtsDefaultVoiceId,
    setTtsSpeed,
    setTtsVoiceId,
    speakCue,
    stopTts,
    toast,
    tts,
    ttsVoice,
    updateTtsRefText,
    uploadTtsVoice,
    uploadTtsVoices,
  } from '../../lib/store.svelte';

  let { index }: { index: number } = $props();

  /** 「⚙」面板：语速 / 上传 / 截取 / 音色库 / 管理。默认收起。 */
  let panelOpen = $state(false);
  let ttsManage = $state(false);
  let ttsName = $state('');
  let ttsRefText = $state('');
  let ttsSaving = $state(false);
  let uploadDraft = $state<{ path: string; name: string; refText: string } | null>(null);
  /** 从当前句截取参考音频：与右键菜单共用后端切片，但入口放在这里。 */
  let extractDraft = $state<{ index: number; name: string; refText: string } | null>(null);
  let ttsLibrary = $state(false);
  let batch = $state<{ done: number; total: number; name: string } | null>(null);

  const cue = $derived(app.cues[index] ?? null);
  const selectedTts = $derived(ttsVoice());
  const downloading = $derived(tts.download?.status === 'running');
  const playingThis = $derived(tts.playing && tts.index === index);
  const loadingThis = $derived(tts.loading && tts.index === index);
  const blocked = $derived(
    tts.loading || (selectedTts?.kind === 'clone' && !cloneEngineReady()),
  );

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
      if (!tts.engine?.installed) return '克隆模型还没下载：点「下载克隆模型」后即可用参考音频克隆';
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
  const playTitle = $derived.by(() => {
    if (!cue) return '先选中一条字幕';
    if (selectedTts?.kind === 'clone' && !cloneEngineReady()) {
      return '克隆模型还没下载：先下载模型或改用系统语音';
    }
    if (playingThis) return '再点一次停止';
    return '朗读这句字幕（TTS 合成，不是原片声音）';
  });

  // 换句关掉面板：上一句的「管理 / 截取」草稿留在面板里容易改错对象
  $effect(() => {
    void index;
    panelOpen = false;
    cancelPanels();
    ttsLibrary = false;
  });

  // 换一条字幕就停掉上一句的 TTS：否则点下一句时上一句还在念，没法对照。
  // （这条原来写在 Inspector 里，随 TTS 控件一起搬过来；只读 index，不会被播放状态回环。）
  $effect(() => {
    void index;
    stopTts();
  });

  /** 播放 / 停止是同一个入口：`speakCue()` 对「正在念这一句」自己会 stop。 */
  function toggleSpeak() {
    speakCue(index);
  }

  function togglePanel() {
    panelOpen = !panelOpen;
    if (!panelOpen) cancelPanels();
  }

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
</script>


<!-- 常驻：朗读 / 停止 + 音色下拉 + 「⚙」面板开关。放在当前条目的操作行里。 -->
<button
  class="tts-listen"
  class:playing={playingThis}
  onclick={toggleSpeak}
  disabled={!cue || blocked}
  title={playTitle}
  aria-label={playingThis ? '停止朗读' : '朗读当前句'}
>
  {#if loadingThis}
    <span class="spin"></span><span>生成中</span>
  {:else if playingThis}
    <Icon name="stop" size={11} /><span>停止</span>
  {:else}
    <Icon name="speaker" size={11} /><span>朗读</span>
  {/if}
</button>

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
    onchange={(e) => setTtsVoiceId(e.currentTarget.value)}
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

<button
  class="tts-more"
  class:on={panelOpen}
  onclick={togglePanel}
  aria-expanded={panelOpen}
  title="朗读语速 · 上传 / 截取参考音频 · 音色库"
  aria-label="朗读设置"
>
  <Icon name="gear" size={12} />
</button>

{#if panelOpen}
  <div class="tts-panel" role="group" aria-label="朗读语速与音色库">
    <div class="tts-panel-head">
      <b>朗读</b>
      <span class="tts-engine {engineTone}" title={engineTitle}>
        <i class="tts-status-dot" aria-hidden="true"></i>{engineLabel}
      </span>
      <span class="tts-meta" title={selectedMeta}>{selectedMeta}</span>
      <button class="tts-panel-close" onclick={togglePanel} title="收起" aria-label="收起朗读设置">
        <Icon name="close" size={10} />
      </button>
    </div>

    <div class="tts-panel-row">
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
{/if}

<style>

  /* ---- 常驻在操作行里的三个控件 ---- */
  .tts-listen {
    appearance: none;
    flex: 0 0 auto;
    display: inline-flex;
    align-items: center;
    gap: var(--sp-1);
    height: var(--ctl-h);
    padding: 0 var(--sp-2);
    border: 1px solid var(--line);
    border-radius: var(--rad-control);
    background: var(--raise);
    color: var(--ink-2);
    font: inherit;
    font-size: var(--fs-ui);
    line-height: 1;
    white-space: nowrap;
    cursor: default;
    transition: color var(--dur-fast) var(--ease), border-color var(--dur-fast) var(--ease),
      background var(--dur-fast) var(--ease);
  }
  .tts-listen:hover:not(:disabled) {
    border-color: var(--accent-line);
    color: var(--accent-hover);
  }
  .tts-listen.playing {
    border-color: var(--accent-line);
    background: var(--accent-soft);
    color: var(--accent-hover);
  }
  .tts-listen:disabled {
    opacity: 0.45;
  }
  .tts-more {
    appearance: none;
    flex: 0 0 var(--ctl-h);
    width: var(--ctl-h);
    height: var(--ctl-h);
    padding: 0;
    border: 1px solid transparent;
    border-radius: var(--rad-control);
    background: transparent;
    color: var(--ink-3);
    display: grid;
    place-items: center;
    cursor: default;
    transition: background var(--dur-fast) var(--ease), color var(--dur-fast) var(--ease);
  }
  .tts-more:hover,
  .tts-more.on {
    background: var(--fill);
    color: var(--ink);
  }
  .tts-panel {
    flex: 1 0 100%;
    order: 10;
    margin-top: var(--sp-2);
    padding: var(--sp-2) var(--sp-3) var(--sp-3);
    border: 1px solid var(--line-2);
    border-radius: 8px;
    background: var(--raise);
    display: flex;
    flex-direction: column;
    gap: var(--sp-2);
  }
  .tts-panel-head {
    display: flex;
    align-items: center;
    gap: var(--sp-2);
    min-width: 0;
  }
  .tts-panel-head b {
    flex: 0 0 auto;
    font-size: 12px;
    line-height: 16px;
    font-weight: 600;
    color: var(--ink-2);
  }
  .tts-panel-head .tts-meta {
    flex: 1 1 auto;
    min-width: 0;
    text-align: right;
  }
  .tts-panel-close {
    appearance: none;
    flex: 0 0 20px;
    width: 20px;
    height: 20px;
    padding: 0;
    border: 0;
    border-radius: 4px;
    background: transparent;
    color: var(--ink-3);
    display: grid;
    place-items: center;
  }
  .tts-panel-close:hover {
    background: var(--fill);
    color: var(--ink);
  }
  .tts-panel-row {
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    gap: var(--sp-1);
  }
  .mini {
    height: 26px;
    padding: 0 var(--sp-2);
    font-size: 12px;
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





  .tts-listen:focus-visible,
  .tts-more:focus-visible,
  .tts-action:focus-visible,
  .tts-download:focus-visible,
  .vp-link:focus-visible,
  .voice-act:focus-visible {
    outline: 2px solid var(--accent-ring);
    outline-offset: 2px;
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


  .tts-select-wrap {
    position: relative;
    display: flex;
    align-items: center;
    min-width: 0;
    height: 26px;
    border-radius: 6px;
    background: var(--fill);
  }
  /* 操作行里只有 ~308px：试听原声 + 朗读 + 音色 + ⚙ 必须落在同一行 */
  .tts-select-wrap.voice {
    flex: 1 1 84px;
    min-width: 84px;
    /* 上限 92px：滚动条出现时可用宽度只有 288px，再宽就会把「⚙」挤到第二行 */
    max-width: 92px;
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
</style>
