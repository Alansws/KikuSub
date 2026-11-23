<script lang="ts">
  /**
   * 交付页：字幕导出 + 成片导出。
   *
   * 成片导出不要求用户先导出 SRT、再打开剪辑软件：当前时间轴与译文轨已经在内存里，
   * 这里直接选分辨率/码率/烧录或软字幕，跑完就得到一个可以发的文件。
   */
  import { onMount } from 'svelte';
  import Icon from '../components/Icon.svelte';
  import ClipScopePicker from '../components/ClipScopePicker.svelte';
  import PageHeader from '../components/PageHeader.svelte';
  import type { SubtitleStylePayload } from '../lib/api';
  import {
    app,
    applyExportStylePreset,
    cancelExport,
    defaultVideoExportDir,
    exportCues,
    exporter,
    loadExportOptions,
    loadExportStyles,
    loadTranslations,
    refreshExportPlan,
    resetExportPanel,
    resetExportStyle,
    scheduleExportPlan,
    scheduleStylePreview,
    setExportLang,
    setExportMode,
    setExportOutDir,
    setExportQuality,
    setExportResolution,
    setExportChapters,
    setExportSrt,
    setExportTrack,
    setPreviewText,
    setPreviewZoom,
    setView,
    startExport,
    toast,
    updateExportStyle,
  } from '../lib/store.svelte';
  import { chapterCount } from '../lib/chapters.svelte';
  import { clipSpan, clipLength, formatRange } from '../lib/clipRange';
  import { formatBytes, formatDuration, tcShort } from '../lib/time';

  let subFormat = $state<'SRT' | 'VTT' | 'TXT'>('SRT');
  let subTrack = $state<'source' | 'target' | 'both'>('source');
  let subLang = $state('zh-Hans');
  let lastSubtitle = $state('');
  let subBusy = $state(false);
  let mounted = false;

  const translationLangs = $derived(Object.keys(app.translations).sort());
  const hasTranslations = $derived(translationLangs.length > 0);
  /** 没有译文轨时「译文 / 双语」只能置灰：就地写一句去哪生成，而不是让按钮空着。 */
  const NO_TRANSLATION_HINT = '暂无译文轨，可在 AI 处理 → 翻译生成后导出双语';
  const selectedTranslation = $derived(
    exporter.track === 'source' ? null : (app.translations[exporter.lang] ?? null),
  );

  function setMode(key: string) {
    setExportMode(key as 'burn' | 'soft' | 'copy');
  }
  function setResolution(key: string) {
    setExportResolution(key as 'source' | '2160p' | '1440p' | '1080p' | '720p' | '480p');
  }
  function setPreset(key: string) {
    setExportQuality(key as 'small' | 'balanced' | 'high' | 'ultra');
  }
  const plan = $derived(exporter.plan);
  const presetCards = $derived(
    exporter.options?.presets ?? [
      { key: 'small', label: '小', factor: 0.55, crf: 25, hint: '文件最小，适合发群/传网盘。' },
      { key: 'balanced', label: '甜点', factor: 1, crf: 21, hint: '速度、画质、体积的平衡点。' },
      { key: 'high', label: '高', factor: 1.6, crf: 18, hint: '保留更多纹理与暗部细节。' },
      { key: 'ultra', label: '极高', factor: 2.4, crf: 15, hint: '接近源画质的收藏档。' },
    ],
  );

  onMount(() => {
    mounted = true;
    void loadExportOptions();
    void loadExportStyles().then(() => scheduleStylePreview(80));
    void loadTranslations();
    if (!exporter.outDir) exporter.outDir = defaultVideoExportDir();
    if (!exporter.plan) void refreshExportPlan();
    if (hasTranslations && !app.translations[app.trackLang]?.texts.length) {
      exporter.lang = translationLangs[0] ?? app.trackLang;
    } else {
      exporter.lang = app.trackLang;
    }
    // 用户在核对台看的是双语/译文时，交付页默认沿用同一轨，少点一次。
    if (app.track !== 'source' && app.translations[app.trackLang]?.texts.length) {
      exporter.track = app.track;
      subTrack = app.track;
    }
    subLang = exporter.lang;
    return () => {
      mounted = false;
    };
  });

  $effect(() => {
    // 译文轨是异步载入的：载入后如果当前语种不在列表里，自动落到第一个可用语种，
    // 否则 <select> 会显示空白，导出按钮也一直禁用。
    const langs = translationLangs;
    if (!langs.length) return;
    if (!langs.includes(exporter.lang)) exporter.lang = langs[0];
    if (!langs.includes(subLang)) subLang = exporter.lang;
  });

  $effect(() => {
    // 只跟踪影响规划结果的字段；outDir 不参与估算，避免读写循环。
    void app.media?.id;
    void exporter.mode;
    void exporter.track;
    void exporter.resolution;
    void exporter.preset;
    void exporter.clip.start;
    void exporter.clip.end;
    if (mounted && app.connected) scheduleExportPlan();
  });

  $effect(() => {
    // 换片/切换字幕轨/切回烧录模式后重渲一次预览；样式本身的改动由 updateExportStyle 触发。
    void app.media?.id;
    void exporter.mode;
    void exporter.track;
    void exporter.lang;
    void exporter.stylesLoaded;
    if (mounted && app.connected && burnMode && exporter.stylesLoaded) scheduleStylePreview(140);
  });

  const estimated = $derived(
    plan
      ? `${formatBytes(plan.estimated_bytes)} · ${formatDuration(plan.estimated_seconds)}`
      : '—',
  );
  const outLabel = $derived(
    exporter.mode === 'copy'
      ? '不重编码，几秒完成'
      : `${plan?.width ?? '—'}×${plan?.height ?? '—'} · ${((plan?.video_bitrate ?? 0) / 1_000_000).toFixed(1)} Mbps`,
  );

  const stylePresets = $derived(exporter.styles?.presets ?? []);
  const styleFonts = $derived(exporter.styles?.fonts ?? []);
  const styleWeights = $derived(
    exporter.styles?.weights ?? [
      { key: 'regular', label: '常规' },
      { key: 'medium', label: '中等' },
      { key: 'bold', label: '粗体' },
    ],
  );
  const styleRanges = $derived(
    exporter.styles?.ranges ?? {
      size: [0.7, 1.6] as [number, number],
      outline: [0, 2.4] as [number, number],
      margin: [1, 14] as [number, number],
    },
  );
  const burnMode = $derived(exporter.mode === 'burn');
  /** 片段范围：字幕导出与成片导出共用同一份（store 的 exporter.clip）。 */
  const scoped = $derived(exporter.clip.end > 0);
  const scopeSpan = $derived(clipSpan(app.cues, exporter.clip));
  const scopeLength = $derived(clipLength(exporter.clip, app.media?.duration || 0));
  const scopeTitle = $derived(
    scoped ? `${exporter.clip.label ? `${exporter.clip.label} · ` : ''}${formatRange(exporter.clip)}` : '',
  );

  function sameNumber(a: number, b: number): boolean {
    return Math.abs(a - b) < 0.005;
  }

  function styleMatches(style: SubtitleStylePayload): boolean {
    const current = exporter.style;
    return (
      current.font === style.font &&
      current.weight === style.weight &&
      sameNumber(current.size, style.size) &&
      sameNumber(current.outline, style.outline) &&
      current.shadow === style.shadow &&
      current.position === style.position &&
      sameNumber(current.margin, style.margin) &&
      current.fill.toUpperCase() === style.fill.toUpperCase() &&
      current.outline_color.toUpperCase() === style.outline_color.toUpperCase()
    );
  }

  const matchedPreset = $derived(
    stylePresets.find((preset) => styleMatches(preset.style))?.key ?? '',
  );

  function resetStyle() {
    resetExportStyle();
  }

  function setWeight(key: string) {
    updateExportStyle({ weight: key as SubtitleStylePayload['weight'] });
  }
  function setPosition(key: 'bottom' | 'top') {
    updateExportStyle({ position: key });
  }

  async function chooseOutDir() {
    try {
      const picked = await window.kikusub.pickDirectory({
        title: '选择成片导出文件夹',
        defaultPath: exporter.outDir || defaultVideoExportDir(),
      });
      if (!picked) return;
      setExportOutDir(picked);
      await refreshExportPlan();
    } catch (err) {
      toast((err as Error).message, 'error');
    }
  }

  async function exportSubtitle() {
    if (!app.cues.length || subBusy) return;
    if (subTrack !== 'source' && !hasTranslations) {
      toast('还没有译文轨；先在翻译页生成并应用译文', 'warn');
      return;
    }
    if (scoped && !scopeSpan.count) {
      toast('这个导出范围里没有字幕：换一个章节或时间点', 'warn');
      return;
    }
    subBusy = true;
    try {
      const res = await exportCues(subFormat, {
        track: subTrack,
        lang: subTrack === 'source' ? '' : subLang || app.trackLang,
        clipStart: scoped ? exporter.clip.start : 0,
        clipEnd: scoped ? exporter.clip.end : 0,
        clipLabel: scoped ? exporter.clip.label : '',
      });
      if (res) lastSubtitle = res.path;
    } finally {
      subBusy = false;
    }
  }

  function openResultDir() {
    const target = exporter.result?.path || exporter.outDir;
    if (target) void window.kikusub.openPath(target.replace(/\/[^/]+$/, ''));
  }

  function revealResult() {
    if (exporter.result?.path) window.kikusub.revealInFinder(exporter.result.path);
  }

  function again() {
    // 保留导出位置：用户选的文件夹不属于「这一次导出的设置」
    resetExportPanel({ record: true, keepOutDir: true });
    void refreshExportPlan();
  }
</script>

<div class="export-view">
  <PageHeader
    title="导出"
    subtitle="字幕和成片都从这里走。成片导出直接使用当前时间轴与译文轨，不用再打开剪辑软件。"
  >
    <button class="btn ghost" onclick={() => setView('report')} title="查看本次转写的任务详报">
      <Icon name="doc" size={11} />任务详报
    </button>
    <button class="btn ghost" onclick={() => setView('review')}>
      <Icon name="listcheck" size={11} />回到核对台
    </button>
  </PageHeader>

  <div class="range-row">
    <ClipScopePicker label="导出范围" disabled={exporter.running} />
    <span class="range-hint">
      {#if scoped}
        只导出这一段：音视频按 {formatRange(exporter.clip)} 裁剪，字幕与章节平移到 0 起；
        字幕文件与成片的名字都会带范围标签，不会覆盖整片成片。
      {:else}
        全片导出。选一段章节或自定义起止时间即可只导出这一段（字幕与章节自动归零）。
      {/if}
    </span>
  </div>

  <!-- 字幕交付 -->
  <section class="sec subtitle-sec">
    <div class="sec-head">
      <div>
        <div class="sec-title">字幕文件</div>
        <div class="sec-desc">
          写到你设置的导出文件夹；双语按官方双语 SRT 的写法，同一时间轴下原文、译文各一条，
          译文缺失的条目不会留空行。
        </div>
      </div>
      <span class="cue-count">
        {#if scoped}
          {scopeSpan.count} / {app.cues.length} 条
        {:else}
          {app.cues.length} 条
        {/if}
      </span>
    </div>
    <div class="sub-row">
      <div class="seg">
        <button class:on={subTrack === 'source'} onclick={() => (subTrack = 'source')}>原文</button>
        <button class:on={subTrack === 'target'} onclick={() => (subTrack = 'target')} disabled={!hasTranslations}>
          译文
        </button>
        <button class:on={subTrack === 'both'} onclick={() => (subTrack = 'both')} disabled={!hasTranslations}>
          双语
        </button>
      </div>
      {#if !hasTranslations}
        <span class="trk-hint">{NO_TRANSLATION_HINT}</span>
      {/if}
      <select class="select" bind:value={subFormat} title="字幕格式">
        <option value="SRT">SRT</option>
        <option value="VTT">VTT</option>
        <option value="TXT">TXT</option>
      </select>
      {#if subTrack !== 'source'}
        <select class="select" bind:value={subLang} title="字幕译文语种">
          {#each translationLangs as lang (lang)}
            <option value={lang}>{lang}</option>
          {/each}
        </select>
      {/if}
      <!-- 主操作：字幕和成片是两条独立导出路径，各自有一个主按钮。
           「导出字幕」此前是白底普通按钮，和旁边的选择器挤在一起，
           成了全页强调色面积只有 0.08% 的原因之一。 -->
      <button
        class="btn primary"
        onclick={exportSubtitle}
        disabled={!app.cues.length || subBusy || (scoped && !scopeSpan.count)}
      >
        <Icon name="export" size={11} />{subBusy ? '导出中…' : scoped ? '导出本段字幕' : '导出字幕'}
      </button>
      <div class="spacer"></div>
      {#if lastSubtitle}
        <button class="path-link mono" title={lastSubtitle} onclick={() => window.kikusub.revealInFinder(lastSubtitle)}>
          最近：{lastSubtitle.split('/').pop()}
        </button>
      {/if}
    </div>
  </section>

  <!-- 成片导出 -->
  <section class="sec">
    <div class="sec-head">
      <div>
        <div class="sec-title">导出成片</div>
      </div>
      {#if plan}
        <span class="estimate" title="按当前档位估算，实际大小会因画面复杂度略有出入">
          ≈ {estimated}
        </span>
      {/if}
    </div>

    {#if !app.media}
      <div class="empty-card">
        <Icon name="film" size={20} />
        <div>先导入视频并完成转写，才能导出成片。</div>
        <button class="btn primary" onclick={() => setView('import')}>去导入</button>
      </div>
    {:else}
      <div class="export-card">
        <div class="row">
          <span class="row-label">形式</span>
          <div class="mode-grid">
            {#each (exporter.options?.modes ?? [
              { key: 'burn', label: '烧录硬字幕', hint: '字幕画进画面，任何播放器都能看。' },
              { key: 'soft', label: '软字幕 MP4', hint: '字幕作为独立轨封装，可开关。' },
              { key: 'copy', label: '仅封装', hint: '不重编码，几秒完成，画质无损。' },
            ]) as mode}
              <button
                class="mode"
                class:on={exporter.mode === mode.key}
                onclick={() => setMode(mode.key)}
                disabled={exporter.running}
              >
                <b>{mode.label}</b>
                <span>{mode.hint}</span>
              </button>
            {/each}
          </div>
        </div>

        {#if scoped && exporter.mode === 'copy'}
          <div class="clip-copy-hint">
            <Icon name="warn" size={11} />
            <span>
              仅封装按关键帧切片：起点会对齐到最近的关键帧，首尾可能多出或短路几秒。
              要精确到帧（时长严格 = {formatDuration(scopeLength)}）请改用「烧录硬字幕」或「软字幕 MP4」。
            </span>
          </div>
        {/if}

        <div class="row">
          <span class="row-label">字幕轨</span>
          <div class="seg">
            <button class:on={exporter.track === 'source'} onclick={() => setExportTrack('source')}>
              原文
            </button>
            <button
              class:on={exporter.track === 'target'}
              onclick={() => setExportTrack('target')}
              disabled={!hasTranslations}
            >
              译文
            </button>
            <button
              class:on={exporter.track === 'both'}
              onclick={() => setExportTrack('both')}
              disabled={!hasTranslations}
            >
              双语
            </button>
          </div>
          {#if !hasTranslations}
            <span class="trk-hint">{NO_TRANSLATION_HINT}</span>
          {/if}
          {#if exporter.track !== 'source'}
            <select
              class="select"
              value={exporter.lang}
              onchange={(e) => setExportLang(e.currentTarget.value)}
              title="选择译文语种"
            >
              {#each translationLangs as lang (lang)}
                <option value={lang}>{lang}</option>
              {/each}
            </select>
            {#if !selectedTranslation}
              <span class="warn-text">还没有 {exporter.lang} 译文</span>
            {/if}
          {/if}
          <div class="spacer"></div>
          <label
            class="chk"
            title={chapterCount()
              ? '按起点排序写入容器；时刻点自动衔接到下一个标记或片尾。IINA 等播放器可直接跳转。'
              : '还没有章节标记：到核对台右侧「章节」页签添加'}
          >
            <input
              type="checkbox"
              checked={exporter.writeChapters && chapterCount() > 0}
              disabled={!chapterCount() || exporter.running}
              onchange={(e) => setExportChapters(e.currentTarget.checked)}
            />
            写入章节标记
            <span class="chapter-count">{chapterCount() ? `${chapterCount()} 个` : '暂无'}</span>
          </label>
          <label class="chk">
            <input
              type="checkbox"
              checked={exporter.exportSrt}
              onchange={(e) => setExportSrt(e.currentTarget.checked)}
            />
            同时导出 SRT
          </label>
        </div>

        {#if burnMode}
          <div class="style-section">
            <div class="style-head">
              <span class="row-label">字幕样式</span>
              <span class="hint-text">只影响「烧录硬字幕」；预设可以再按需微调。</span>
              <div class="spacer"></div>
              <button class="btn tiny ghost" onclick={resetStyle} disabled={exporter.running}>恢复默认</button>
            </div>
            <div class="style-body">
              <div class="style-controls">
                <div class="preset-grid">
                  {#each stylePresets as preset (preset.key)}
                    <button
                      class="style-preset"
                      class:on={matchedPreset === preset.key}
                      onclick={() => applyExportStylePreset(preset.key)}
                      disabled={exporter.running}
                      title={preset.hint}
                    >
                      <b>{preset.label}</b>
                      <span>{preset.hint}</span>
                    </button>
                  {/each}
                </div>

                <div class="style-row">
                  <label for="style-font">字体</label>
                  <select
                    id="style-font"
                    class="select compact"
                    value={exporter.style.font}
                    onchange={(e) => updateExportStyle({ font: e.currentTarget.value })}
                    disabled={exporter.running}
                  >
                    {#each styleFonts as font (font.key)}
                      <option value={font.key} disabled={!font.available}>
                        {font.label}{font.available ? '' : '（本机不可用）'}
                      </option>
                    {/each}
                  </select>
                  <span class="style-label">字重</span>
                  <div class="seg small">
                    {#each styleWeights as weight (weight.key)}
                      <button
                        class:on={exporter.style.weight === weight.key}
                        onclick={() => setWeight(weight.key)}
                        disabled={exporter.running}
                      >
                        {weight.label}
                      </button>
                    {/each}
                  </div>
                </div>

                <div class="style-row">
                  <span class="style-label">字号</span>
                  <input
                    class="slider"
                    type="range"
                    min={styleRanges.size[0]}
                    max={styleRanges.size[1]}
                    step="0.02"
                    value={exporter.style.size}
                    oninput={(e) => updateExportStyle({ size: Number(e.currentTarget.value) })}
                    disabled={exporter.running}
                  />
                  <span class="num mono">{Math.round(exporter.style.size * 100)}%</span>
                  <span class="style-label">描边</span>
                  <input
                    class="slider"
                    type="range"
                    min={styleRanges.outline[0]}
                    max={styleRanges.outline[1]}
                    step="0.05"
                    value={exporter.style.outline}
                    oninput={(e) => updateExportStyle({ outline: Number(e.currentTarget.value) })}
                    disabled={exporter.running}
                  />
                  <span class="num mono">{Math.round(exporter.style.outline * 100)}%</span>
                </div>

                <div class="style-row">
                  <span class="style-label">位置</span>
                  <div class="seg small">
                    <button
                      class:on={exporter.style.position === 'bottom'}
                      onclick={() => setPosition('bottom')}
                      disabled={exporter.running}
                    >
                      底部
                    </button>
                    <button
                      class:on={exporter.style.position === 'top'}
                      onclick={() => setPosition('top')}
                      disabled={exporter.running}
                    >
                      顶部
                    </button>
                  </div>
                  <span class="style-label">边距</span>
                  <input
                    class="slider"
                    type="range"
                    min={styleRanges.margin[0]}
                    max={styleRanges.margin[1]}
                    step="0.1"
                    value={exporter.style.margin}
                    oninput={(e) => updateExportStyle({ margin: Number(e.currentTarget.value) })}
                    disabled={exporter.running}
                  />
                  <span class="num mono">{exporter.style.margin.toFixed(1)}%</span>
                  <label class="chk inline">
                    <input
                      type="checkbox"
                      checked={exporter.style.shadow}
                      onchange={(e) => updateExportStyle({ shadow: e.currentTarget.checked })}
                      disabled={exporter.running}
                    />
                    阴影
                  </label>
                </div>

                <div class="style-row">
                  <span class="style-label">文字色</span>
                  <input
                    class="color"
                    type="color"
                    value={exporter.style.fill}
                    oninput={(e) => updateExportStyle({ fill: e.currentTarget.value.toUpperCase() })}
                    disabled={exporter.running}
                  />
                  <span class="style-label">描边色</span>
                  <input
                    class="color"
                    type="color"
                    value={exporter.style.outline_color}
                    oninput={(e) => updateExportStyle({ outline_color: e.currentTarget.value.toUpperCase() })}
                    disabled={exporter.running}
                  />
                  {#if exporter.styles && !exporter.styles.fonts_ok}
                    <span class="warn-text">{exporter.styles.font_error}</span>
                  {:else if exporter.styleError}
                    <span class="warn-text">{exporter.styleError}</span>
                  {/if}
                </div>
              </div>

              <div class="preview-panel">
                <div class="preview-head">
                  <span class="style-label">预览</span>
                  <div class="seg small">
                    <button class:on={!exporter.previewZoom} onclick={() => setPreviewZoom(false)}>整帧</button>
                    <button class:on={exporter.previewZoom} onclick={() => setPreviewZoom(true)}>字体特写</button>
                  </div>
                </div>
                <div class="preview-frame" class:busy={exporter.stylePreviewBusy} class:zoomed={exporter.previewZoom}>
                  {#if exporter.stylePreviewUrl}
                    <img src={exporter.stylePreviewUrl} alt="烧录字幕样式预览" />
                  {:else}
                    <div class="preview-empty">正在准备预览…</div>
                  {/if}
                  {#if exporter.stylePreviewBusy}<span class="preview-badge">渲染中…</span>{/if}
                </div>
                <input
                  class="preview-text"
                  type="text"
                  maxlength="120"
                  placeholder="预览文字（留空用当前字幕第一条）"
                  value={exporter.previewText}
                  oninput={(e) => setPreviewText(e.currentTarget.value)}
                  disabled={exporter.running}
                />
                <div class="preview-foot">
                  <span>
                    {styleFonts.find((font) => font.key === exporter.style.font)?.label ?? '—'}
                    · {styleWeights.find((weight) => weight.key === exporter.style.weight)?.label ?? ''}
                  </span>
                  <span>{plan ? `成片 ${plan.width}×${plan.height}` : ''}</span>
                </div>
                {#if exporter.stylePreviewError}
                  <div class="warn-text">{exporter.stylePreviewError}</div>
                {/if}
              </div>
            </div>
          </div>
        {/if}

        <div class="row" class:dim={exporter.mode === 'copy'}>
          <span class="row-label">分辨率</span>
          <div class="seg">
            {#each (exporter.options?.resolutions ?? [
              { key: 'source', label: '原始' },
              { key: '1080p', label: '1080p' },
              { key: '720p', label: '720p' },
              { key: '480p', label: '480p' },
            ]) as res}
              <button
                class:on={exporter.resolution === res.key}
                onclick={() => setResolution(res.key)}
                disabled={exporter.running || exporter.mode === 'copy'}
              >
                {res.label}
              </button>
            {/each}
          </div>
          {#if exporter.mode === 'copy'}
            <span class="hint-text">仅封装保持原分辨率</span>
          {/if}
        </div>

        <div class="row quality-row" class:dim={exporter.mode === 'copy'}>
          <span class="row-label">码率</span>
          <div class="presets">
            {#each presetCards as preset (preset.key)}
              <button
                class="preset"
                class:on={exporter.preset === preset.key}
                onclick={() => setPreset(preset.key)}
                disabled={exporter.running || exporter.mode === 'copy'}
                title={preset.hint}
              >
                <b>{preset.label}</b>
                <span>{preset.hint}</span>
              </button>
            {/each}
          </div>
        </div>

        <div class="row">
          <span class="row-label">位置</span>
          <b class="out-path mono" title={exporter.outDir}>{exporter.outDir || '—'}</b>
          <button class="btn tiny" onclick={chooseOutDir} disabled={exporter.running}>更改…</button>
          <button class="btn tiny ghost" onclick={() => exporter.outDir && window.kikusub.openPath(exporter.outDir)}>
            打开
          </button>
        </div>

        {#if plan}
          <div class="metrics">
            <span><b>{outLabel}</b></span>
            <span>预计 {estimated}</span>
            {#if scoped}
              <span>片段 {tcShort(exporter.clip.start)} → {tcShort(exporter.clip.end)} · {formatDuration(scopeLength)}</span>
            {/if}
            {#if plan.container === 'mkv'}
              <span class="warn-text">MKV 输出</span>
            {/if}
            {#each plan.warnings as warning (warning)}
              <span class="warn-text">{warning}</span>
            {/each}
          </div>
        {:else if exporter.planLoading}
          <div class="metrics muted">正在估算输出…</div>
        {:else if exporter.planError}
          <div class="metrics warn-text">{exporter.planError}</div>
        {/if}

        {#if exporter.running}
          <div class="run-card">
            <div class="run-top">
              <span class="spin"></span>
              <b>{exporter.stage || '正在导出…'}</b>
              <span class="run-pct">{exporter.progress}%</span>
            </div>
            <div class="run-bar"><i style="width:{Math.max(2, exporter.progress)}%"></i></div>
            <div class="run-meta">
              <span>已处理 {formatDuration(exporter.outS)} / {formatDuration(plan?.duration ?? 0)}</span>
              {#if exporter.speed}<span>{exporter.speed}</span>{/if}
              <div class="spacer"></div>
              <button
                class="btn tiny ghost"
                onclick={cancelExport}
                disabled={exporter.stage === '正在停止导出…'}
              >
                {exporter.stage === '正在停止导出…' ? '停止中…' : '取消'}
              </button>
            </div>
          </div>
        {:else if exporter.result}
          <div class="done-card">
            <div class="done-top">
              <span class="done-ico"><Icon name="check" size={13} /></span>
              <b>导出完成</b>
              <span class="done-meta">
                {formatBytes(exporter.result.size)} · {exporter.result.width}×{exporter.result.height} ·
                {exporter.result.elapsed.toFixed(1)}s
              </span>
            </div>
            <div class="done-path mono" title={exporter.result.path}>{exporter.result.name}</div>
            {#if exporter.result.srt_path}
              <div class="done-sub">字幕同时导出了：{exporter.result.srt_path.split('/').pop()}</div>
            {/if}
            <div class="done-actions">
              <button class="btn" onclick={revealResult}><Icon name="folder" size={11} />在访达中显示</button>
              <button class="btn ghost" onclick={openResultDir}>打开所在文件夹</button>
              <button class="btn ghost" onclick={again}>再导一份</button>
            </div>
          </div>
        {:else if exporter.error}
          <div class="err-card">
            <Icon name="warn" size={13} />
            <span>{exporter.error}</span>
          </div>
        {/if}

        <div class="actions">
          <div class="spacer"></div>
          <button
            class="btn primary go"
            onclick={startExport}
            disabled={exporter.running || !app.cues.length || (scoped && !scopeSpan.count) || (exporter.track !== 'source' && !selectedTranslation)}
          >
            <Icon name="export" size={12} />
            {exporter.running ? '导出中…' : exporter.result ? '再导一份' : '开始导出'}
          </button>
        </div>
      </div>
    {/if}
  </section>
</div>

<style>
  .export-view {
    flex: 1;
    min-height: 0;
    overflow-y: auto;
    /* G5：与转写页共用同一套页面骨架 —— 24px 左右内边距 + 1040 内容列 + 左对齐。
       原来各页自定义 1120 / 1000 并居中，导致左缘 276 / 294 / 260 三档漂移。 */
    padding: var(--sp-8) var(--sp-6) var(--sp-12);
    display: grid;
    grid-template-columns: minmax(0, 1040px);
    justify-content: start;
    align-content: start;
  }
  .range-row {
    display: flex;
    align-items: center;
    gap: var(--sp-3);
    flex-wrap: wrap;
    padding: 10px var(--sp-3);
    border: 1px solid var(--separator-soft);
    border-radius: 8px;
    background: var(--bg-content);
  }
  .range-hint {
    font-size: var(--fs-ui);
    line-height: 19px;
    color: var(--ink-2);
    min-width: 0;
    flex: 1 1 320px;
  }
  .clip-copy-hint {
    display: flex;
    align-items: flex-start;
    gap: 6px;
    margin: var(--sp-2) 0 0;
    padding: 6px 9px;
    border-radius: 6px;
    background: var(--warn-soft);
    color: var(--warn);
    font-size: var(--fs-ui);
    line-height: 19px;
  }
  .sec {
    border-top: 1px solid var(--separator-soft);
    padding: 18px 0 var(--sp-2);
  }
  .sec-head {
    display: flex;
    align-items: flex-start;
    gap: var(--sp-3);
    margin-bottom: var(--sp-3);
  }
  .sec-title {
    font-size: 14px;
    font-weight: 600;
    margin-bottom: 3px;
  }
  .sec-desc {
    font-size: var(--fs-ui);
    color: var(--ink-2);
    line-height: 19px;
    max-width: 700px;
  }
  .cue-count,
  .estimate {
    margin-left: auto;
    font-size: 12px;
    color: var(--text-3);
    font-variant-numeric: tabular-nums;
    flex: 0 0 auto;
    padding-top: 2px;
  }
  .sub-row {
    display: flex;
    align-items: center;
    gap: var(--sp-2);
    flex-wrap: wrap;
  }
  .trk-hint {
    font-size: var(--fs-ui);
    color: var(--ink-2);
    line-height: 19px;
  }
  .seg {
    display: inline-flex;
    background: var(--fill);
    border-radius: 4px;
    padding: 2px;
    flex: 0 0 auto;
  }
  .seg button {
    appearance: none;
    border: 0;
    background: transparent;
    font: inherit;
    font-size: 12px;
    height: 24px;
    padding: 0 10px;
    border-radius: 4px;
    color: var(--text-2);
  }
  .seg button:disabled {
    opacity: 0.4;
  }
  .seg button.on {
    background: var(--bg-content);
    color: var(--text);
    box-shadow: 0 0.5px 1.5px rgba(0, 0, 0, 0.12);
  }
  .select {
    font: inherit;
    font-size: 12px;
    padding: var(--sp-1) 7px;
    border-radius: 4px;
    border: 1px solid var(--separator);
    background: var(--bg-content);
    color: var(--text);
  }
  .spacer {
    flex: 1;
  }
  .path-link {
    border: 0;
    background: transparent;
    color: var(--accent);
    font-size: 12px;
    cursor: pointer;
    max-width: 320px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .mono {
    font-family: var(--mono, ui-monospace, SFMono-Regular, Menlo, monospace);
  }
  .empty-card {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 9px;
    padding: 44px var(--sp-5);
    border: 1px dashed var(--separator);
    border-radius: 12px;
    color: var(--text-2);
    font-size: 12px;
  }
  .export-card {
    border: 1px solid var(--separator);
    border-radius: 12px;
    background: var(--bg-content);
    padding: var(--sp-4) 17px 14px;
    box-shadow: 0 1px 2px rgba(0, 0, 0, 0.03);
  }
  .row {
    display: flex;
    align-items: flex-start;
    gap: 10px;
    padding: 9px 0;
    border-bottom: 1px solid var(--separator-soft);
    min-width: 0;
  }
  .row:first-child {
    padding-top: 0;
  }
  .row.dim {
    opacity: 0.55;
  }
  .row-label {
    flex: 0 0 58px;
    font-size: 12px;
    color: var(--text-3);
    padding-top: var(--sp-1);
    white-space: nowrap;
  }
  .mode-grid {
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: var(--sp-2);
    flex: 1;
    min-width: 0;
  }
  .mode {
    appearance: none;
    text-align: left;
    border: 1px solid var(--separator);
    border-radius: 4px;
    background: var(--bg-content);
    padding: 9px 10px;
    color: var(--text);
    font: inherit;
    display: flex;
    flex-direction: column;
    gap: 3px;
    min-width: 0;
    transition: border-color 140ms var(--ease), background 140ms var(--ease);
  }
  /* 三种导出方式的说明是「选错要重编码几十分钟」的文字，必须可读：13/19 + --ink-2。 */
  .mode b {
    font-size: 13.5px;
    line-height: 18px;
    font-weight: 600;
  }
  .mode span {
    font-size: var(--fs-ui);
    color: var(--ink-2);
    line-height: 19px;
  }
  .mode.on {
    border-color: var(--accent);
    background: var(--accent-soft);
  }
  .mode.on span {
    color: var(--ink-2);
  }
  .mode:disabled {
    opacity: 0.55;
  }
  .quality-row {
    align-items: stretch;
  }
  .presets {
    display: grid;
    grid-template-columns: repeat(4, minmax(0, 1fr));
    gap: var(--sp-2);
    flex: 1;
    min-width: 0;
  }
  .preset {
    appearance: none;
    text-align: left;
    border: 1px solid var(--separator);
    border-radius: 4px;
    background: var(--bg-content);
    padding: var(--sp-2) 9px;
    color: var(--text);
    font: inherit;
    display: flex;
    flex-direction: column;
    gap: 2px;
    min-width: 0;
    transition: border-color 140ms var(--ease), background 140ms var(--ease);
  }
  /* 码率预设的 hint 解释「这条在什么场景下更合适」，与样式预设同一套规则。 */
  .preset b {
    font-size: 13.5px;
    line-height: 18px;
    font-weight: 600;
  }
  .preset span {
    font-size: var(--fs-ui);
    color: var(--ink-2);
    line-height: 19px;
    display: -webkit-box;
    -webkit-line-clamp: 3;
    -webkit-box-orient: vertical;
    overflow: hidden;
  }
  .preset.on {
    border-color: var(--accent);
    background: var(--accent-soft);
  }
  .preset:disabled {
    opacity: 0.55;
  }
  .out-path {
    flex: 1;
    min-width: 0;
    font-size: 12px;
    color: var(--text-2);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    padding-top: var(--sp-1);
  }
  .chk {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    font-size: 12px;
    color: var(--text-2);
    user-select: none;
    white-space: nowrap;
    padding-top: 3px;
  }
  .hint-text {
    font-size: var(--fs-ui);
    color: var(--ink-2);
    line-height: 19px;
    padding-top: 4px;
  }
  .metrics {
    display: flex;
    gap: var(--sp-3);
    flex-wrap: wrap;
    font-size: 12px;
    color: var(--text-3);
    padding: 10px 0 2px;
    align-items: baseline;
  }
  .metrics b {
    color: var(--text-2);
    font-weight: 500;
  }
  .metrics.muted {
    color: var(--text-3);
  }
  .chapter-count {
    margin-left: var(--sp-1);
    font-size: 11px;
    color: var(--text-3);
    font-variant-numeric: tabular-nums;
  }

  .warn-text {
    color: var(--warn);
  }
  .run-card,
  .done-card {
    margin-top: var(--sp-3);
    border-radius: 8px;
    padding: var(--sp-3) 13px;
    border: 1px solid var(--separator);
  }
  .run-card {
    background: linear-gradient(120deg, var(--accent-soft), transparent 70%);
  }
  .run-top {
    display: flex;
    align-items: center;
    gap: var(--sp-2);
    font-size: 12px;
  }
  .run-top b {
    font-weight: 500;
  }
  .run-pct {
    margin-left: auto;
    font-variant-numeric: tabular-nums;
    font-weight: 600;
    color: var(--accent);
  }
  .spin {
    width: 12px;
    height: 12px;
    border-radius: 50%;
    border: 1.5px solid var(--fill-strong);
    border-top-color: var(--accent);
    animation: spin 700ms linear infinite;
    flex: 0 0 12px;
  }
  @keyframes spin {
    to {
      transform: rotate(360deg);
    }
  }
  .run-bar {
    margin: 9px 0 7px;
    height: 6px;
    border-radius: 3px;
    background: var(--fill-strong);
    overflow: hidden;
  }
  .run-bar i {
    display: block;
    height: 100%;
    border-radius: 3px;
    background: linear-gradient(90deg, var(--accent), #8fa6ff);
    transition: width 260ms var(--ease);
    position: relative;
    overflow: hidden;
  }
  .run-bar i::after {
    content: '';
    position: absolute;
    inset: 0;
    background: linear-gradient(90deg, transparent, rgba(255, 255, 255, 0.45), transparent);
    animation: shimmer 1.4s linear infinite;
  }
  @keyframes shimmer {
    from {
      transform: translateX(-100%);
    }
    to {
      transform: translateX(100%);
    }
  }
  .run-meta {
    display: flex;
    align-items: center;
    gap: var(--sp-3);
    font-size: 12px;
    color: var(--text-3);
    font-variant-numeric: tabular-nums;
  }
  .done-card {
    background: var(--success-soft);
    border-color: color-mix(in srgb, var(--success) 28%, transparent);
  }
  .done-top {
    display: flex;
    align-items: center;
    gap: 7px;
    font-size: 12px;
  }
  .done-ico {
    width: 18px;
    height: 18px;
    border-radius: 50%;
    background: var(--success);
    color: var(--on-accent);
    display: grid;
    place-items: center;
    flex: 0 0 18px;
  }
  .done-meta {
    margin-left: auto;
    font-size: 12px;
    color: var(--text-3);
    font-variant-numeric: tabular-nums;
  }
  .done-path {
    margin-top: 7px;
    font-size: 12px;
    color: var(--text-2);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .done-sub {
    margin-top: 3px;
    font-size: 12px;
    color: var(--text-3);
  }
  .done-actions {
    display: flex;
    gap: 7px;
    margin-top: 10px;
    flex-wrap: wrap;
  }
  .err-card {
    margin-top: var(--sp-3);
    display: flex;
    align-items: flex-start;
    gap: 7px;
    padding: 10px var(--sp-3);
    border-radius: 4px;
    background: var(--danger-soft);
    color: var(--danger);
    font-size: var(--fs-ui);
    line-height: 19px;
  }
  .actions {
    display: flex;
    align-items: flex-end;
    gap: 14px;
    margin-top: 14px;
    padding-top: var(--sp-3);
    border-top: 1px solid var(--separator-soft);
  }
  .go {
    height: 34px;
    padding: 0 18px;
    font-size: 12.5px;
    border-radius: 4px;
    flex: 0 0 auto;
  }
  .style-section {
    padding: var(--sp-3) 0 10px;
    border-bottom: 1px solid var(--separator-soft);
  }
  .style-head {
    display: flex;
    align-items: baseline;
    gap: 10px;
    margin-bottom: 10px;
  }
  .style-head .hint-text {
    font-size: var(--fs-ui);
    color: var(--ink-2);
    line-height: 19px;
  }
  .style-body {
    display: grid;
    grid-template-columns: minmax(0, 1fr) 340px;
    gap: var(--sp-4);
    align-items: start;
  }
  .style-controls {
    min-width: 0;
  }
  .preset-grid {
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: 6px;
    margin-bottom: 2px;
  }
  .style-preset {
    appearance: none;
    text-align: left;
    border: 1px solid var(--separator);
    border-radius: 8px;
    background: var(--bg-content);
    padding: 7px var(--sp-2);
    color: var(--text);
    font: inherit;
    display: flex;
    flex-direction: column;
    gap: 2px;
    min-width: 0;
    cursor: pointer;
    transition: border-color 140ms var(--ease), background 140ms var(--ease);
  }
  /* 「标题 ≥ 正文」：标题 13.5 略高于正文 13，正文用 --ink-2。
     6 张卡在 13/19 下仍是 2 行、不裁字（实测卡高 67 → 74），clamp 放到 3 行留余量。 */
  .style-preset b {
    font-size: 13.5px;
    line-height: 18px;
    font-weight: 600;
  }
  .style-preset span {
    font-size: var(--fs-ui);
    color: var(--ink-2);
    line-height: 19px;
    display: -webkit-box;
    -webkit-line-clamp: 3;
    -webkit-box-orient: vertical;
    overflow: hidden;
  }
  .style-preset.on {
    border-color: var(--accent);
    background: var(--accent-soft);
  }
  .style-preset:disabled {
    opacity: 0.55;
    cursor: default;
  }
  .style-row {
    display: flex;
    align-items: center;
    gap: var(--sp-2);
    flex-wrap: wrap;
    padding: 7px 0 0;
    font-size: 12px;
  }
  .style-row > label,
  .style-row > .style-label {
    color: var(--text-3);
    white-space: nowrap;
  }
  .select.compact {
    padding: 2px 6px;
    font-size: 12px;
    max-width: 160px;
  }
  .seg.small {
    padding: 1px;
  }
  .seg.small button {
    height: 20px;
    padding: 0 var(--sp-2);
    font-size: 12px;
  }
  .slider {
    width: 86px;
    accent-color: var(--control-on);
  }
  .num {
    font-size: 12px;
    color: var(--text-3);
    min-width: 34px;
    font-variant-numeric: tabular-nums;
  }
  .color {
    width: 24px;
    height: 19px;
    padding: 0;
    border: 1px solid var(--separator);
    border-radius: 4px;
    background: transparent;
    cursor: pointer;
  }
  .chk.inline {
    font-size: 12px;
  }
  .preview-panel {
    min-width: 0;
    display: flex;
    flex-direction: column;
    gap: 7px;
  }
  .preview-head {
    display: flex;
    align-items: center;
    gap: var(--sp-2);
  }
  .preview-head .style-label {
    font-size: 12px;
    color: var(--text-3);
  }
  .preview-frame {
    position: relative;
    aspect-ratio: 16 / 9;
    border-radius: 4px;
    overflow: hidden;
    border: 1px solid var(--separator);
    background: #14161c;
  }
  .preview-frame img {
    display: block;
    width: 100%;
    height: 100%;
    object-fit: cover;
  }
  .preview-frame.zoomed {
    aspect-ratio: auto;
  }
  .preview-frame.zoomed img {
    height: auto;
    object-fit: contain;
  }
  .preview-empty {
    position: absolute;
    inset: 0;
    display: grid;
    place-items: center;
    font-size: 12px;
    color: rgba(255, 255, 255, 0.45);
  }
  .preview-badge {
    position: absolute;
    right: 7px;
    bottom: 7px;
    padding: 2px 6px;
    border-radius: 4px;
    background: rgba(0, 0, 0, 0.55);
    color: rgba(255, 255, 255, 0.82);
    font-size: 12px;
    backdrop-filter: blur(4px);
  }
  .preview-text {
    font: inherit;
    font-size: 12px;
    padding: var(--sp-1) 7px;
    border-radius: 4px;
    border: 1px solid var(--separator);
    background: var(--bg-content);
    color: var(--text);
  }
  .preview-foot {
    display: flex;
    justify-content: space-between;
    gap: var(--sp-2);
    font-size: 12px;
    color: var(--text-3);
  }
  @media (max-width: 860px) {
    .style-body {
      grid-template-columns: minmax(0, 1fr);
    }
    .preset-grid {
      grid-template-columns: repeat(2, minmax(0, 1fr));
    }
  }
</style>
