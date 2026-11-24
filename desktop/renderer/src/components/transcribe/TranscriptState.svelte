<script lang="ts">
  /**
   * 转写页右栏「现在的稿」（2026-11-25）。
   *
   * 这一栏回答的是「我手上现在有什么」，而不是「再调一个参数」：
   * 主稿（核对台）/ 第二版（双引擎复核的 B）/ 最近一次提交 / 已有字幕入口。
   *
   * 旧页面把这些塞在「结果与输出」的条件块里——只有整片、且核对台非空时才
   * 出现「已有第二版」；逐章转录时连入口都没有。放到右栏之后，空态本身也成了
   * 下一步：用另一个引擎生成第二版。
   */
  import Icon from '../Icon.svelte';
  import { app, importSubtitleFromExport, importTranslationFromExport, setView, toast } from '../../lib/store.svelte';
  import { altEngineLabel, deleteAltReview, dual } from '../../lib/dualReview.svelte';
  import { tcShort } from '../../lib/time';
  import type { OutputTarget } from '../../lib/transcribePlan';
  import type { LastRunView } from '../../lib/transcribeTask.svelte';

  let {
    primaryEngineKey = '',
    primaryEngineLabel = '',
    target = 'primary' as OutputTarget,
    lastRun = null as LastRunView | null,
    onSuggestAlt,
    onPickAlt,
    onReplayAlt,
  }: {
    primaryEngineKey?: string;
    primaryEngineLabel?: string;
    target?: OutputTarget;
    lastRun?: LastRunView | null;
    onSuggestAlt?: (engineKey: string) => void;
    onPickAlt?: () => void;
    onReplayAlt?: () => void;
  } = $props();

  const cues = $derived(app.cues);
  const running = $derived(
    app.job?.status === 'queued' ||
      app.job?.status === 'running' ||
      app.job?.status === 'cancelling',
  );

  const primarySpanText = $derived.by(() => {
    if (!cues.length) return '';
    return `${tcShort(cues[0].start)} – ${tcShort(cues[cues.length - 1].end)}`;
  });

  const altSpanText = $derived.by(() => {
    if (!dual.cues.length) return `${dual.count} 条`;
    const first = dual.cues[0];
    const last = dual.cues[dual.cues.length - 1];
    return `${tcShort(first.start)} – ${tcShort(last.end)} · ${dual.count} 条`;
  });

  /** 主稿引擎未知（逐章转录的 replace_range 不写 review_source）时用上次提交兜底。 */
  const knownMainKey = $derived(primaryEngineKey || String(app.reviewSource?.engine || ''));

  /** 建议的「另一个日语引擎」：主稿引擎已知时取另一个，未知时不瞎猜。 */
  const suggest = $derived.by(() => {
    const enabled = (app.config?.engines ?? []).filter(
      (item) => item.enabled && (item.family === 'whisper' || item.family === 'qwen'),
    );
    if (!enabled.length || !knownMainKey) return null;
    return (
      enabled.find((item) => item.key !== knownMainKey && item.installed) ??
      enabled.find((item) => item.key !== knownMainKey) ??
      null
    );
  });

  function clock(seconds: number): string {
    if (!seconds) return '';
    return new Date(seconds).toLocaleTimeString('zh-CN', {
      hour12: false,
      hour: '2-digit',
      minute: '2-digit',
    });
  }

  async function dropAlt() {
    if (!window.confirm('删除当前第二版？核对台不受影响。')) return;
    await deleteAltReview();
  }

  function suggestAlt() {
    if (!suggest || !onSuggestAlt) return;
    onSuggestAlt(suggest.key);
    toast(`已切到 ${suggest.label}，产出改为「第二版」；确认范围后点生成第二版`);
  }
</script>

<aside class="state" aria-label="现在的稿">
  <div class="st-head">现在的稿</div>

  <section class="st-row">
    <div class="st-label">
      <span class="dot" class:ok={cues.length > 0}></span>
      主稿 · 核对台
    </div>
    {#if cues.length}
      <div class="st-value">{cues.length} 条</div>
      <div class="st-meta">{primarySpanText}</div>
      <div class="st-meta">
        {#if primaryEngineLabel}
          最近一版来自 {primaryEngineLabel}
        {:else}
          <span title="逐章替换选区不会改写主稿来源；以「最近一次」为准">来源未记录</span>
        {/if}
      </div>
      <div class="st-actions">
        <button class="btn tiny ghost" type="button" onclick={() => setView('review')} disabled={running}>
          <Icon name="listcheck" size={10} />去核对台
        </button>
      </div>
    {:else}
      <div class="st-value dim">还没有字幕</div>
      <div class="st-meta">这次转写会写进核对台</div>
    {/if}
  </section>

  <section class="st-row">
    <div class="st-label">
      <span class="dot" class:ok={dual.exists}></span>
      第二版 · 对照
    </div>
    {#if dual.exists}
      <div class="st-value">{altEngineLabel()}</div>
      <div class="st-meta">{altSpanText}</div>
      <div class="st-actions">
        <button class="btn tiny" type="button" onclick={() => setView('dual')}>
          <Icon name="rows" size={10} />查看差异
        </button>
        <button class="btn tiny ghost" type="button" onclick={dropAlt} disabled={running}>
          丢弃
        </button>
      </div>
    {:else if cues.length}
      <div class="st-value dim">还没有</div>
      {#if target === 'alt'}
        <div class="st-meta">产出已经是「第二版」；选好引擎、确认范围，点底栏的生成按钮。</div>
      {:else if target === 'both'}
        <div class="st-meta">「两版一起」会同时生成第二版；确认副引擎后点底栏的开跑按钮。</div>
      {:else}
        <div class="st-meta">换一个引擎跑同一段，逐句对照后再决定用哪份</div>
        <div class="st-actions">
          {#if suggest}
            <button class="btn tiny" type="button" onclick={suggestAlt}>
              用 {suggest.label} 生成第二版
            </button>
          {:else}
            <button class="btn tiny" type="button" onclick={onPickAlt}>
              把产出改为「第二版」
            </button>
          {/if}
        </div>
      {/if}
    {:else}
      <div class="st-value dim">还没有</div>
      <div class="st-meta">
        {cues.length
          ? '没有可配对的第二个日语引擎；到设置里启用后再来'
          : '先有一版主稿，第二版才有东西可对照'}
      </div>
      <div class="st-actions">
        <button class="btn tiny ghost" type="button" onclick={() => setView('dual')}>
          打开双引擎复核
        </button>
      </div>
    {/if}
  </section>

  {#if lastRun}
    <section class="st-row">
      <div class="st-label">
        最近一次
        {#if lastRun.at}<span class="at">{clock(lastRun.at)}</span>{/if}
      </div>
      <div class="st-value">{lastRun.engineLabel} · {lastRun.targetText}</div>
      <div class="st-meta">{lastRun.rangeText} · {lastRun.countText}</div>
      {#if lastRun.canReplay && onReplayAlt}
        <div class="st-actions">
          <button class="btn tiny ghost" type="button" onclick={onReplayAlt} disabled={running}>
            <Icon name="refresh" size={10} />作为第二版重跑这段
          </button>
        </div>
      {/if}
    </section>
  {/if}

  <section class="st-row">
    <div class="st-label">已有字幕</div>
    <div class="st-meta">不重新转写，直接把原文 / 逐条对齐的译文导进核对台</div>
    <div class="st-actions col">
      <button
        class="btn tiny ghost"
        type="button"
        onclick={importSubtitleFromExport}
        disabled={!app.connected || running}
      >
        <Icon name="doc" size={10} />导入原文…
      </button>
      <button
        class="btn tiny ghost"
        type="button"
        onclick={importTranslationFromExport}
        disabled={!app.connected || running || !cues.length}
        title={cues.length ? '选择与当前原文逐条对齐的译文' : '先导入原文字幕，再导入译文'}
      >
        <Icon name="quote" size={10} />导入译文…
      </button>
    </div>
  </section>

  <p class="st-foot">第二版只读：核对台的字幕不会被它改掉，采用哪一句由你在复核页决定。</p>
</aside>

<style>
  .state {
    position: sticky;
    top: 0;
    align-self: start;
    min-width: 0;
    display: flex;
    flex-direction: column;
    padding: 2px 0 0 var(--sp-1);
  }

  .st-head {
    font-size: 12.5px;
    font-weight: 600;
    letter-spacing: 0.02em;
    color: var(--text-2);
    padding-bottom: var(--sp-2);
  }
  .st-row {
    padding: 11px 0;
    border-top: 1px solid var(--separator-soft);
    min-width: 0;
  }
  .st-row:first-of-type {
    border-top: 0;
    padding-top: 0;
  }

  .st-label {
    display: flex;
    align-items: center;
    gap: 6px;
    font-size: 12px;
    color: var(--text-2);
    min-width: 0;
  }
  .st-label .at {
    margin-left: auto;
    font-size: 11px;
    color: var(--text-3);
    font-variant-numeric: tabular-nums;
  }
  .dot {
    width: 6px;
    height: 6px;
    flex: 0 0 6px;
    border-radius: 50%;
    background: var(--fill-strong);
    box-shadow: 0 0 0 2px var(--fill);
  }
  .dot.ok {
    background: var(--success);
    box-shadow: 0 0 0 2px var(--success-soft);
  }

  .st-value {
    margin-top: var(--sp-1);
    font-size: 12.5px;
    line-height: 1.4;
    color: var(--text);
    font-variant-numeric: tabular-nums;
    overflow-wrap: break-word;
  }
  .st-value.dim {
    color: var(--text-3);
  }
  .st-meta {
    margin-top: 2px;
    font-size: 11px;
    line-height: 1.5;
    color: var(--text-3);
    text-wrap: pretty;
  }
  .st-actions {
    display: flex;
    align-items: center;
    gap: 6px;
    flex-wrap: wrap;
    margin-top: var(--sp-2);
  }
  .st-actions.col {
    flex-direction: column;
    align-items: stretch;
  }
  .st-actions.col .btn {
    justify-content: flex-start;
  }

  .st-foot {
    margin: 2px 0 0;
    padding-top: 10px;
    border-top: 1px solid var(--separator-soft);
    font-size: 11px;
    line-height: 1.5;
    color: var(--text-3);
  }
</style>
