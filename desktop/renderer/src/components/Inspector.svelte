<script lang="ts">
  import Icon from './Icon.svelte';
  import {
    app,
    deleteCue,
    exportCues,
    focusRange,
    loadTranslations,
    play,
    previewRange,
    refreshDraftInfo,
    restoreDraft,
    reviewDraft,
    saveDraft,
    isTranslationStale,
    setTrackLang,
    setTrackMode,
    staleTranslationCount,
    translationAt,
    undoTranslation,
    updateCue,
    updateTranslation,
    type TrackMode,
  } from '../lib/store.svelte';
  import { tc } from '../lib/time';

  const cue = $derived(app.cues[play.selected] ?? null);
  const quality = $derived(app.report?.quality ?? null);

  let draft = $state('');
  let draftTr = $state('');
  let editingIndex = $state(-1);
  /** 同步键：换了选中行 / 语种 / 显示模式 / 换了一版译文，才重新灌编辑框 */
  let syncKey = $state('');
  let exportFormat = $state<'SRT' | 'VTT' | 'TXT'>('SRT');
  let exportTrack = $state<'source' | 'target' | 'both'>('source');
  let exporting = $state(false);

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
    }
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
    const version = app.translations[app.trackLang]?.created_at ?? 0;
    const key = `${idx}:${app.track}:${app.trackLang}:${version}`;
    if (key === syncKey) return;
    syncKey = key;
    editingIndex = idx;
    draft = c.text;
    draftTr = translationAt(idx);
  });

  /** 只提交当前显示模式里真正可见的那几个框。 */
  function commit() {
    if (!cue) return;
    if (app.track === 'source') {
      if (draft !== cue.text) updateCue(play.selected, { text: draft });
      return;
    }
    if (app.track === 'target') {
      if (draftTr !== translationAt(play.selected)) updateTranslation(play.selected, draftTr);
      return;
    }
    // 双语：两个框都能改，各自独立提交
    if (draft !== cue.text) updateCue(play.selected, { text: draft });
    if (draftTr !== translationAt(play.selected)) updateTranslation(play.selected, draftTr);
  }

  function remove() {
    if (!cue) return;
    deleteCue(play.selected);
    play.selected = Math.max(0, play.selected - 1);
  }
</script>

<aside class="inspector" class:hidden={!app.inspectorOpen}>
  <div>
    <div class="ins-h">显示</div>
    <div class="track-row">
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
        <button class="link" onclick={() => undoTranslation()}>撤销译文</button>
      </div>
    {/if}

    <div class="ins-h">
      当前条目
      <span class="muted">#{play.selected + 1}</span>
    </div>
    <div class="card">
      {#if cue}
        <div class="kv">
          <span class="k">时间</span>
          <span class="v mono">{tc(cue.start)} → {tc(cue.end)}</span>
        </div>
        <div class="kv">
          <span class="k">时长</span>
          <span class="v mono">{(cue.end - cue.start).toFixed(2)} s</span>
        </div>
        <div class="kv">
          <span class="k">字符</span>
          <span class="v">
            {cue.text.length} 字{app.track === 'source' ? '' : ` · 译文 ${translationAt(play.selected).length} 字`}
          </span>
        </div>
        <div style="height:8px"></div>

        {#if app.track === 'source'}
          <textarea
            class="cue-text"
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
            class="cue-text"
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
            class="cue-text"
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
        <div class="btn-row">
          <button class="btn" onclick={() => previewRange(cue.start, cue.end)}>
            <Icon name="play" size={11} />试听
          </button>
          <button class="btn ghost" onclick={() => focusRange(cue.start, cue.end)} title="在波形上聚焦放大这一句">
            <Icon name="search" size={11} />聚焦
          </button>
          <button
            class="btn primary"
            onclick={commit}
            disabled={app.track === 'source'
              ? draft === cue.text
              : draft === cue.text && draftTr === translationAt(play.selected)}
          >
            更新此行
          </button>
        </div>
        <div class="btn-row">
          <button class="btn danger" onclick={remove}>
            <Icon name="trash" size={11} />删除此句
          </button>
        </div>
      {:else}
        <div class="muted" style="padding:6px 2px">还没有字幕</div>
      {/if}
    </div>
  </div>

  {#if quality}
    <div>
      <div class="ins-h">质检速览</div>
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
          class:soft={(quality.low_confidence ?? 0) > 0}
        >
          低置信 <b>{quality.low_confidence ?? 0}</b>
        </span>
      </div>
    </div>
  {/if}

  <div>
    <div class="ins-h">生效参数</div>
    <div class="card">
      {#if app.report?.params?.length}
        {#each app.report.params.slice(0, 6) as row (row.label)}
          <div class="kv"><span class="k">{row.label}</span><span class="v">{row.value}</span></div>
        {/each}
      {:else}
        <div class="kv"><span class="k">设备</span><span class="v">{app.config?.device ?? '—'}</span></div>
        <div class="kv"><span class="k">引擎</span><span class="v">{app.config?.engines?.[0]?.label ?? '—'}</span></div>
        <div class="kv"><span class="k">版本</span><span class="v">v{app.config?.version ?? '—'}</span></div>
        <div class="kv" style="color:var(--text-3)">
          <span class="k">参数</span><span class="v" style="color:var(--text-3)">转写后可见</span>
        </div>
      {/if}
    </div>
  </div>

  <div>
    <div class="ins-h">输出</div>
    <div class="card">
      <div class="kv">
        <span class="k">文件</span>
        <span class="v mono" style="font-size:11px">
          {app.report?.overview?.find((r) => r.label === '字幕文件名')?.value ??
            app.media?.name ??
            '—'}
        </span>
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
        <Icon name="save" size={11} />{reviewDraft.saving ? '暂存中' : '暂存进度'}
      </button>
      <select
        class="sd-fmt"
        bind:value={exportTrack}
        disabled={exporting}
        title="导出内容：原文 / 仅译文 / 双语（一条两行）"
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
        <Icon name="export" size={11} />{exporting ? '导出中' : '导出'}
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
</aside>

<style>
  .inspector {
    width: 320px;
    flex: 0 0 320px;
    background: var(--bg-inspector);
    border-left: 1px solid var(--separator);
    overflow-y: auto;
    padding: 12px 14px 20px;
    display: flex;
    flex-direction: column;
    gap: 16px;
    transition: width var(--dur) var(--ease), flex-basis var(--dur) var(--ease),
      padding var(--dur) var(--ease), opacity 140ms var(--ease);
  }
  .edit-label {
    margin: 2px 0 3px;
    font-size: 10.5px;
    color: var(--text-3);
  }

  .edit-hint {
    margin-top: 4px;
    font-size: 10.5px;
    color: #b26a00;
  }

  html[data-theme='dark'] .edit-hint {
    color: #ffb340;
  }

  .track-row {
    display: flex;
    align-items: center;
    gap: 6px;
    margin: 0 0 6px;
  }
  .seg {
    display: inline-flex;
    padding: 2px;
    border-radius: 7px;
    background: var(--fill);
  }
  .seg button {
    border: 0;
    background: transparent;
    color: var(--text-2);
    font: inherit;
    font-size: 11px;
    padding: 3px 9px;
    border-radius: 5px;
    cursor: pointer;
  }
  .seg button.on {
    background: var(--bg-content);
    color: var(--text);
    box-shadow: 0 1px 2px rgba(0, 0, 0, 0.12);
  }
  .seg button:disabled {
    color: var(--text-3);
    cursor: default;
  }
  .lang-sel {
    margin-left: auto;
    font: inherit;
    font-size: 11px;
    padding: 2px 5px;
    border-radius: 6px;
    border: 1px solid var(--separator);
    background: var(--bg-content);
    color: var(--text);
  }
  .track-meta {
    display: flex;
    align-items: center;
    gap: 8px;
    margin: 0 0 8px;
    font-size: 10.5px;
    color: var(--text-3);
  }
  .track-meta .ok {
    color: #1c7c36;
  }
  .track-meta .warn {
    color: #b26a00;
  }
  .track-meta .link {
    margin-left: auto;
    border: 0;
    background: transparent;
    color: var(--accent);
    font: inherit;
    font-size: 10.5px;
    cursor: pointer;
    padding: 0;
  }

  .inspector.hidden {
    width: 0;
    flex-basis: 0;
    padding-left: 0;
    padding-right: 0;
    opacity: 0;
    overflow: hidden;
    border-left-color: transparent;
  }

  .muted {
    color: var(--text-3);
    font-weight: 400;
  }

  .cue-text {
    width: 100%;
    border: 1px solid transparent;
    background: var(--fill);
    border-radius: 8px;
    padding: 9px 10px;
    font: inherit;
    font-size: 15px;
    line-height: 1.5;
    color: var(--text);
    resize: vertical;
    min-height: 56px;
    user-select: text;
    transition: border-color var(--dur) var(--ease), box-shadow var(--dur) var(--ease);
  }
  .cue-text:hover {
    border-color: var(--separator);
  }
  .cue-text:focus {
    outline: none;
    border-color: var(--accent);
    background: var(--bg-content);
    box-shadow: 0 0 0 3px var(--accent-soft);
  }

  .btn-row {
    display: flex;
    gap: 6px;
    margin-top: 8px;
  }
  .btn-row .btn {
    flex: 1;
    justify-content: center;
  }

  /* 常驻保存区：吸在右侧栏底部，滚动检查器时也不消失 */
  .save-dock {
    position: sticky;
    bottom: 0;
    z-index: 3;
    margin: 0 -14px -20px;
    padding: 9px 14px 12px;
    border-top: 1px solid var(--separator);
    background: color-mix(in srgb, var(--bg-inspector) 94%, var(--bg-content));
    backdrop-filter: blur(12px);
    -webkit-backdrop-filter: blur(12px);
    box-shadow: 0 -10px 20px -16px rgba(0, 0, 0, 0.35);
    display: flex;
    flex-direction: column;
    gap: 6px;
  }
  .sd-head {
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    gap: 8px;
    min-width: 0;
  }
  .sd-title {
    font-size: 11px;
    font-weight: 600;
    color: var(--text-3);
    letter-spacing: 0.02em;
    flex: 0 0 auto;
  }
  .sd-state {
    font-size: 10.5px;
    color: var(--text-3);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .sd-state.warn {
    color: #b26a00;
  }
  :global(html[data-theme='dark']) .sd-state.warn {
    color: #ffb340;
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
    appearance: none;
    height: 26px;
    width: 58px;
    flex: 0 0 58px;
    border-radius: 6px;
    border: 1px solid var(--separator);
    background: var(--bg-content);
    color: var(--text-2);
    font: inherit;
    font-size: 11.5px;
    padding: 0 4px;
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
    font-size: 10.5px;
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
    color: var(--text-3);
  }
</style>
