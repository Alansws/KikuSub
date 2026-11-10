<script lang="ts">
  import Icon from './Icon.svelte';
  import { app, deleteCue, play, updateCue } from '../lib/store.svelte';
  import { tc } from '../lib/time';

  const cue = $derived(app.cues[play.selected] ?? null);
  const quality = $derived(app.report?.quality ?? null);

  let draft = $state('');
  let editingIndex = $state(-1);

  // 选中行变化时把文本灌进编辑框（不覆盖正在输入的内容）
  $effect(() => {
    const idx = play.selected;
    const c = app.cues[idx];
    if (!c) return;
    if (idx !== editingIndex) {
      draft = c.text;
      editingIndex = idx;
    }
  });

  function commit() {
    if (!cue) return;
    if (draft === cue.text) return;
    updateCue(play.selected, { text: draft });
  }

  function remove() {
    if (!cue) return;
    deleteCue(play.selected);
    play.selected = Math.max(0, play.selected - 1);
  }
</script>

<aside class="inspector" class:hidden={!app.inspectorOpen}>
  <div>
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
          <span class="v">{cue.text.length} 字</span>
        </div>
        <div style="height:8px"></div>
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
        <div class="btn-row">
          <button class="btn" onclick={() => (play.time = cue.start + 0.02)}>
            <Icon name="play" size={11} />试听
          </button>
          <button class="btn primary" onclick={commit} disabled={draft === cue.text}>
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
        <span class="chip" class:ok={quality.missed === 0}>漏句 <b>{quality.missed}</b></span>
        {#if !quality.qwen_limited}
          <span class="chip" class:ok={quality.dropped === 0}>误删 <b>{quality.dropped}</b></span>
          <span class="chip" class:warn={quality.suspect > 0}>
            短句 <b>{quality.suspect}</b>
          </span>
        {/if}
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
</style>
