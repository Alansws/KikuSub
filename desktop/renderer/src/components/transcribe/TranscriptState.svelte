<script lang="ts">
  /**
   * 转写页右栏「现在的稿」（Cue Script 版）。
   *
   * 这一栏回答的是「我手上现在有什么」，而不是「再调一个参数」：
   * 主稿（核对台）/ 第二版（双引擎复核的 B）/ 最近一次提交 / 已有字幕入口。
   * 每段是一个小小的「读数 + 一句话 + 一个动作」，没有卡片套卡片。
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
  <section class="rail-section">
    <div class="rail-status">
      <span class="mark" class:ok={cues.length > 0}></span>
      主稿 · 核对台
    </div>
    {#if cues.length}
      <div class="rail-num">
        {cues.length}<small>条 · 主稿</small>
      </div>
      <div class="rail-meta">{primarySpanText}</div>
      <div class="rail-meta">
        {#if primaryEngineLabel}
          最近一版来自 {primaryEngineLabel}
        {:else}
          <span title="逐章替换选区不会改写主稿来源；以「最近一次」为准">来源未记录</span>
        {/if}
      </div>
      <div class="rail-actions">
        <button class="btn sm" type="button" onclick={() => setView('review')} disabled={running}>
          <Icon name="listcheck" size={10} />去核对台
        </button>
      </div>
    {:else}
      <div class="rail-num dim">还没有<small>字幕</small></div>
      <div class="rail-meta">这次转写会写进核对台。</div>
    {/if}
  </section>

  <section class="rail-section">
    <div class="rail-status">
      <span class="mark" class:ok={dual.exists}></span>
      第二版 · 对照
    </div>
    {#if dual.exists}
      <div class="rail-num">{altEngineLabel()}</div>
      <div class="rail-meta">{altSpanText}</div>
      <div class="rail-actions">
        <button class="btn sm" type="button" onclick={() => setView('dual')}>
          <Icon name="rows" size={10} />查看差异
        </button>
        <button class="btn sm ghost" type="button" onclick={dropAlt} disabled={running}>
          丢弃
        </button>
      </div>
    {:else if cues.length}
      <div class="rail-num dim">还没有</div>
      {#if target === 'alt'}
        <div class="rail-meta">产出已经是「第二版」；选好引擎、确认范围，点底栏的生成按钮。</div>
      {:else if target === 'both'}
        <div class="rail-meta">「两版一起」会同时生成第二版；确认副引擎后点底栏的开跑按钮。</div>
      {:else}
        <div class="rail-meta">换一个引擎跑同一段，逐句对照后再决定用哪份。</div>
        <div class="rail-actions">
          {#if suggest}
            <button class="btn sm" type="button" onclick={suggestAlt}>
              用 {suggest.label} 生成第二版
            </button>
          {:else}
            <button class="btn sm" type="button" onclick={onPickAlt}>
              把产出改为「第二版」
            </button>
          {/if}
        </div>
      {/if}
    {:else}
      <div class="rail-num dim">还没有</div>
      <div class="rail-meta">
        {cues.length
          ? '没有可配对的第二个日语引擎；到设置里启用后再来'
          : '先有一版主稿，第二版才有东西可对照'}
      </div>
      <div class="rail-actions">
        <button class="btn sm ghost" type="button" onclick={() => setView('dual')}>
          打开双引擎复核
        </button>
      </div>
    {/if}
  </section>

  {#if lastRun}
    <section class="rail-section">
      <div class="rail-status">
        最近一次
        {#if lastRun.at}<span class="at">{clock(lastRun.at)}</span>{/if}
      </div>
      <div class="rail-line">{lastRun.engineLabel} · {lastRun.targetText}</div>
      <div class="rail-meta">{lastRun.rangeText} · {lastRun.countText}</div>
      {#if lastRun.canReplay && onReplayAlt}
        <div class="rail-actions">
          <button class="btn sm ghost" type="button" onclick={onReplayAlt} disabled={running}>
            <Icon name="refresh" size={10} />作为第二版重跑这段
          </button>
        </div>
      {/if}
    </section>
  {/if}

  <section class="rail-section">
    <div class="rail-status">已有字幕</div>
    <div class="rail-meta">不重新转写，直接把原文 / 逐条对齐的译文导进核对台。</div>
    <div class="rail-actions col">
      <button
        class="btn sm ghost"
        type="button"
        onclick={importSubtitleFromExport}
        disabled={!app.connected || running}
      >
        <Icon name="doc" size={10} />导入原文…
      </button>
      <button
        class="btn sm ghost"
        type="button"
        onclick={importTranslationFromExport}
        disabled={!app.connected || running || !cues.length}
        title={cues.length ? '选择与当前原文逐条对齐的译文' : '先导入原文字幕，再导入译文'}
      >
        <Icon name="quote" size={10} />导入译文…
      </button>
    </div>
  </section>

  <section class="rail-section">
    <div class="rail-status">小提示</div>
    <div class="rail-meta">
      长片先整片跑，再对不确定的段落用「区间」重转。中途打断也会把已完成片段落盘为
      <span class="mono">*.part_cancelled.srt</span>。
    </div>
  </section>

  <p class="rail-foot">第二版只读：核对台的字幕不会被它改掉，采用哪一句由你在复核页决定。</p>
</aside>

<style>
  .state {
    position: sticky;
    top: 0;
    align-self: start;
    min-width: 0;
    display: flex;
    flex-direction: column;
    min-height: 100%;
  }

  .rail-section {
    padding: 14px 0;
    border-top: 1px solid var(--line);
    min-width: 0;
  }
  .rail-section:first-child {
    border-top: 0;
    padding-top: 0;
  }

  /* 段标：等宽小字 + 状态点。它先说「这一块是什么」，再给读数 */
  .rail-status {
    display: flex;
    align-items: center;
    gap: 6px;
    font-family: var(--font-mono);
    font-size: 11px;
    line-height: 16px;
    letter-spacing: 0.07em;
    text-transform: uppercase;
    color: var(--text-3);
    margin-bottom: var(--sp-2);
  }
  .rail-status .at {
    margin-left: auto;
    letter-spacing: 0;
    font-variant-numeric: tabular-nums;
  }
  .mark {
    width: 5px;
    height: 5px;
    flex: 0 0 5px;
    border-radius: 50%;
    background: var(--fill-strong);
  }
  .mark.ok {
    background: var(--success);
  }

  .rail-num {
    font-size: 22px;
    line-height: 28px;
    font-weight: 600;
    letter-spacing: -0.02em;
    color: var(--text);
    font-variant-numeric: tabular-nums;
  }
  .rail-num small {
    font-size: 11px;
    font-weight: 400;
    color: var(--text-3);
    margin-left: 5px;
    letter-spacing: 0;
  }
  .rail-num.dim {
    font-size: 15px;
    line-height: 22px;
    font-weight: 500;
    color: var(--text-3);
    letter-spacing: 0;
  }

  .rail-line {
    font-size: 12.5px;
    line-height: 18px;
    color: var(--text);
  }
  .rail-meta {
    margin-top: var(--sp-1);
    font-size: 12px;
    line-height: 1.55;
    color: var(--text-3);
    text-wrap: pretty;
  }
  .rail-meta .mono {
    font-family: var(--font-mono);
    font-size: 11px;
    color: var(--text-2);
  }

  .rail-actions {
    display: flex;
    align-items: center;
    gap: 6px;
    flex-wrap: wrap;
    margin-top: 10px;
  }
  .rail-actions.col {
    flex-direction: column;
    align-items: stretch;
  }
  .rail-actions.col .btn {
    justify-content: flex-start;
  }

  .rail-foot {
    margin: 0;
    padding-top: var(--sp-2);
    border-top: 1px solid var(--line);
    font-size: 11px;
    line-height: 1.5;
    color: var(--text-3);
  }
</style>
